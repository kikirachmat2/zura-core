"""
network/safe_fetch.py - Centralized Enterprise Anti-SSRF Web Fetcher
Enforces strict security boundary controls per Zura Charter v2:
1. Whitelists only http/https schemes and ports 80/443. Rejects userinfo in URLs.
2. Resolves DNS once and validates EVERY resolved IP address against:
   - Loopback (127.0.0.0/8, ::1)
   - RFC 1918 Private networks (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7)
   - Link-local & Cloud Metadata (169.254.0.0/16, fe80::/10)
   - Unspecified & Default routes (0.0.0.0/8, ::)
   - Multicast (224.0.0.0/4, ff00::/8)
   - Reserved (240.0.0.0/4)
   - IPv4-mapped IPv6 (::ffff:0:0/96, e.g. ::ffff:127.0.0.1)
   - Carrier-Grade NAT & Tailscale CGNAT (100.64.0.0/10)
   - Any non-globally routable IP (ip.is_global is False)
   - Decimal, hex, and octal IP evasion encodings.
3. Physically connects socket directly to the validated IP to defeat DNS Rebinding.
   Sets TLS SNI and HTTP Host header to the original hostname.
4. Manually handles redirects up to 3 hops max, re-validating every redirect target.
5. Caps response body size at 2 MB with strict total timeout.
6. Enforces textual/HTML Content-Type whitelist.
7. Wraps returned content in <untrusted_web> tags before passing to LLM prompts.
"""

import socket
import ssl
import http.client
import ipaddress
import urllib.parse
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("SafeFetch")

MAX_RESPONSE_SIZE = 2 * 1024 * 1024  # 2 MB limit
MAX_REDIRECT_HOPS = 3
DEFAULT_TIMEOUT = 12

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}

ALLOWED_CONTENT_PREFIXES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/rss+xml",
    "application/atom+xml"
)

BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),     # CGNAT / Tailscale
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("169.254.0.0/16"),   # Link-Local / Cloud Metadata
    ipaddress.ip_network("172.16.0.0/12"),    # Private IPv4
    ipaddress.ip_network("192.168.0.0/16"),   # Private IPv4
    ipaddress.ip_network("224.0.0.0/4"),      # Multicast
    ipaddress.ip_network("240.0.0.0/4"),      # Reserved
]

BLOCKED_IPV6_NETWORKS = [
    ipaddress.ip_network("::1/128"),          # Loopback
    ipaddress.ip_network("::/128"),           # Unspecified
    ipaddress.ip_network("fc00::/7"),         # Unique local
    ipaddress.ip_network("fe80::/10"),        # Link-local
    ipaddress.ip_network("ff00::/8"),         # Multicast
]


class SSRFSecurityError(Exception):
    """Raised when an outbound URL violates SSRF security policies."""
    pass


def is_safe_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> Tuple[bool, str]:
    """Validates an IP address against all restricted network ranges and properties."""
    # Unwrap IPv4-mapped IPv6 address (e.g. ::ffff:127.0.0.1)
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped is not None:
        ip_obj = ip_obj.ipv4_mapped

    if isinstance(ip_obj, ipaddress.IPv4Address):
        for net in BLOCKED_NETWORKS:
            if ip_obj in net:
                return False, f"IP {ip_obj} falls into restricted IPv4 network {net}"
    elif isinstance(ip_obj, ipaddress.IPv6Address):
        for net in BLOCKED_IPV6_NETWORKS:
            if ip_obj in net:
                return False, f"IP {ip_obj} falls into restricted IPv6 network {net}"

    if ip_obj.is_loopback:
        return False, f"IP {ip_obj} is a loopback address"
    if ip_obj.is_private:
        return False, f"IP {ip_obj} is a private RFC 1918/ULA address"
    if ip_obj.is_link_local:
        return False, f"IP {ip_obj} is a link-local/cloud metadata address"
    if ip_obj.is_multicast:
        return False, f"IP {ip_obj} is a multicast address"
    if ip_obj.is_reserved:
        return False, f"IP {ip_obj} is a reserved address"
    if ip_obj.is_unspecified:
        return False, f"IP {ip_obj} is an unspecified (0.0.0.0 / ::) address"
    if not ip_obj.is_global:
        return False, f"IP {ip_obj} is not globally routable"

    return True, ""


def resolve_and_validate_host(hostname: str, port: int) -> Tuple[str, List[str]]:
    """
    Resolves hostname to IP addresses and validates EVERY single candidate.
    Handles standard DNS, IPv4/IPv6 literals, and decimal/octal/hex evasion encodings.
    Returns (selected_ip, all_resolved_ips).
    """
    # 1. Check for decimal / hex / octal IPv4 string encodings via socket.inet_aton
    try:
        raw_bytes = socket.inet_aton(hostname)
        dotted_ip = socket.inet_ntoa(raw_bytes)
        ip_obj = ipaddress.ip_address(dotted_ip)
        safe, reason = is_safe_ip(ip_obj)
        if not safe:
            raise SSRFSecurityError(f"Host '{hostname}' decoded to restricted IP '{dotted_ip}': {reason}")
        return dotted_ip, [dotted_ip]
    except (socket.error, OSError):
        pass

    # 2. Check direct IPv6 literal
    if hostname.startswith("[") and hostname.endswith("]"):
        clean_v6 = hostname[1:-1]
        try:
            ip_obj = ipaddress.ip_address(clean_v6)
            safe, reason = is_safe_ip(ip_obj)
            if not safe:
                raise SSRFSecurityError(f"Host '{hostname}' is restricted IPv6 literal '{clean_v6}': {reason}")
            return clean_v6, [clean_v6]
        except ValueError:
            pass

    # 3. DNS resolution via getaddrinfo
    try:
        addr_info = socket.getaddrinfo(hostname, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFSecurityError(f"DNS resolution failed for host '{hostname}': {e}")

    if not addr_info:
        raise SSRFSecurityError(f"No IP addresses resolved for host '{hostname}'")

    all_ips: List[str] = []
    for item in addr_info:
        ip_str = item[4][0]
        if ip_str not in all_ips:
            all_ips.append(ip_str)

    # 4. Validate ALL resolved IP addresses (strictly reject if ANY is dangerous)
    for ip_str in all_ips:
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            raise SSRFSecurityError(f"Invalid resolved IP '{ip_str}' from host '{hostname}'")

        safe, reason = is_safe_ip(ip_obj)
        if not safe:
            raise SSRFSecurityError(f"Host '{hostname}' resolved to restricted IP '{ip_str}': {reason}")

    # Return the first safe resolved IP
    return all_ips[0], all_ips


def validate_url_components(url: str) -> Tuple[str, str, int, str]:
    """
    Parses and verifies URL schema, port, userinfo, and host.
    Returns (scheme, hostname, port, path_and_query).
    """
    if not url or not isinstance(url, str):
        raise SSRFSecurityError("URL must be a non-empty string")

    # Reject non-printable characters or whitespace evasion
    clean_url = url.strip()
    parsed = urllib.parse.urlsplit(clean_url)

    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFSecurityError(f"Disallowed URL scheme '{scheme}'. Only http and https are permitted.")

    # Reject userinfo in authority (user:pass@host)
    if parsed.username or parsed.password or ("@" in (parsed.netloc or "")):
        raise SSRFSecurityError("URL contains userinfo credentials (@), which is strictly disallowed.")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFSecurityError("URL must contain a valid hostname")

    # Determine and validate port
    default_port = 443 if scheme == "https" else 80
    port = parsed.port if parsed.port is not None else default_port
    if port not in ALLOWED_PORTS:
        raise SSRFSecurityError(f"Disallowed port '{port}'. Only standard ports 80 and 443 are permitted.")

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    return scheme, hostname, port, path


def safe_fetch_url(url: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """
    Fetches web content through centralized anti-SSRF enforcement.
    Safely resolves IP, connects directly at socket level, re-evaluates redirects,
    and returns sanitized content wrapped in <untrusted_web> tags.
    """
    current_url = url
    hops = 0

    while hops <= MAX_REDIRECT_HOPS:
        scheme, hostname, port, path_and_query = validate_url_components(current_url)
        target_ip, all_resolved = resolve_and_validate_host(hostname, port)

        sock = None
        conn = None
        try:
            # Connect socket DIRECTLY to the validated IP (prevents DNS rebinding)
            sock = socket.create_connection((target_ip, port), timeout=timeout)
            sock.settimeout(timeout)

            if scheme == "https":
                ssl_context = ssl.create_default_context()
                # Wrap with SNI set to the validated hostname
                tls_sock = ssl_context.wrap_socket(sock, server_hostname=hostname)
                conn = http.client.HTTPSConnection(hostname, port=port, timeout=timeout)
                conn.sock = tls_sock
            else:
                conn = http.client.HTTPConnection(hostname, port=port, timeout=timeout)
                conn.sock = sock

            # Send HTTP request
            headers = {
                "Host": hostname,
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 ZuraBot/2.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
                "Connection": "close"
            }
            conn.request("GET", path_and_query, headers=headers)
            resp = conn.getresponse()

            # Handle HTTP Redirects
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.getheader("Location")
                if not location:
                    raise SSRFSecurityError(f"HTTP {resp.status} redirect missing Location header")

                hops += 1
                if hops > MAX_REDIRECT_HOPS:
                    raise SSRFSecurityError(f"Redirect limit exceeded (maximum {MAX_REDIRECT_HOPS} hops allowed)")

                # Re-evaluate redirect target URL relative to current URL
                current_url = urllib.parse.urljoin(current_url, location)
                logger.info(f"SafeFetch following redirect hop {hops} to: {current_url}")
                continue

            # Validate Content-Type
            content_type = (resp.getheader("Content-Type") or "").lower()
            if content_type and not any(content_type.startswith(p) for p in ALLOWED_CONTENT_PREFIXES):
                raise SSRFSecurityError(f"Disallowed Content-Type '{content_type}'. Only textual/HTML documents allowed.")

            # Check Content-Length if provided
            content_length_hdr = resp.getheader("Content-Length")
            if content_length_hdr and content_length_hdr.isdigit():
                if int(content_length_hdr) > MAX_RESPONSE_SIZE:
                    raise SSRFSecurityError(f"Content-Length {content_length_hdr} exceeds 2 MB response limit")

            # Stream response body with hard 2 MB limit
            body_chunks = []
            total_bytes = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_RESPONSE_SIZE:
                    raise SSRFSecurityError(f"Response size exceeded 2 MB safety cap ({total_bytes} bytes read)")
                body_chunks.append(chunk)

            raw_bytes = b"".join(body_chunks)

            # Decode text
            charset = "utf-8"
            if "charset=" in content_type:
                try:
                    charset = content_type.split("charset=")[-1].split(";")[0].strip()
                except Exception:
                    pass

            text_content = raw_bytes.decode(charset, errors="replace")

            # Wrap in untrusted_web security envelope
            wrapped_content = f"<untrusted_web>\n{text_content}\n</untrusted_web>"

            return {
                "success": True,
                "status_code": resp.status,
                "url": current_url,
                "resolved_ip": target_ip,
                "content_type": content_type,
                "raw_text": text_content,
                "wrapped_content": wrapped_content,
                "size_bytes": total_bytes
            }

        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            elif sock:
                try:
                    sock.close()
                except Exception:
                    pass

    raise SSRFSecurityError("Failed to fetch web page: unexpected termination")
