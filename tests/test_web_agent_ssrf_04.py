"""
tests/test_web_agent_ssrf_04.py - Verification Suite for Step 0.4 Anti-SSRF Defense
Tests:
1. Cloud Metadata (169.254.169.254) blocked
2. Loopback (127.0.0.1, localhost, 0.0.0.0, ::1, ::ffff:127.0.0.1) blocked
3. RFC 1918 Private networks (10.x, 172.16.x, 192.168.x) blocked
4. CGNAT / Tailscale (100.64.0.1, 100.100.100.100) blocked
5. Decimal / Hex / Octal integer IP encodings blocked
6. Userinfo (user:pass@host) in URL blocked
7. Non-standard ports (:8080, :22, :3000) blocked
8. Non-HTTP schemes (file://, ftp://, gopher://) blocked
9. Redirect to metadata and redirect to Tailscale blocked
10. DNS Rebinding (resolver returning mixed public & private IPs) blocked
11. Untrusted web envelope (<untrusted_web>) wrapping and valid public fetch
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from network.safe_fetch import safe_fetch_url, SSRFSecurityError, resolve_and_validate_host, is_safe_ip
from ops.web_agent import web_agent
import ipaddress


class TestWebAgentSSRF04(unittest.TestCase):

    def test_01_cloud_metadata_blocked(self):
        """Verifies AWS/OCI/GCP link-local metadata IP is strictly blocked."""
        with self.assertRaises(SSRFSecurityError) as ctx:
            safe_fetch_url("http://169.254.169.254/latest/meta-data/")
        self.assertIn("restricted", str(ctx.exception).lower())

    def test_02_loopback_and_zero_blocked(self):
        """Verifies 127.0.0.1, localhost, 0.0.0.0, ::1, and ::ffff:127.0.0.1 are blocked."""
        targets = [
            "http://127.0.0.1/",
            "http://localhost/",
            "http://0.0.0.0/",
            "http://[::1]/",
            "http://[::ffff:127.0.0.1]/"
        ]
        for url in targets:
            with self.assertRaises(SSRFSecurityError, msg=f"Should block {url}") as ctx:
                safe_fetch_url(url)
            self.assertTrue(any(w in str(ctx.exception).lower() for w in ["restricted", "loopback", "unspecified"]))

    def test_03_private_rfc1918_blocked(self):
        """Verifies RFC 1918 subnets (10/8, 172.16/12, 192.168/16) are blocked."""
        targets = [
            "http://10.0.0.1/",
            "http://172.16.0.1/",
            "http://192.168.1.1/"
        ]
        for url in targets:
            with self.assertRaises(SSRFSecurityError, msg=f"Should block {url}"):
                safe_fetch_url(url)

    def test_04_tailscale_cgnat_blocked(self):
        """Verifies 100.64.0.0/10 Carrier-Grade NAT and Tailscale IPs are blocked."""
        targets = [
            "http://100.64.0.1/",
            "http://100.100.100.100/"
        ]
        for url in targets:
            with self.assertRaises(SSRFSecurityError, msg=f"Should block {url}") as ctx:
                safe_fetch_url(url)
            self.assertIn("100.64.0.0/10", str(ctx.exception))

    def test_05_decimal_hex_octal_evasion_blocked(self):
        """Verifies decimal, hex, and octal integer formats for loopback are decoded and blocked."""
        targets = [
            "http://2130706433/",  # Decimal 127.0.0.1
            "http://0177.0.0.1/",  # Octal 127.0.0.1
            "http://0x7f000001/"   # Hex 127.0.0.1
        ]
        for url in targets:
            with self.assertRaises(SSRFSecurityError, msg=f"Should block {url}") as ctx:
                safe_fetch_url(url)
            self.assertIn("127.0.0.0/8", str(ctx.exception))

    def test_06_userinfo_credentials_rejected(self):
        """Verifies URL with username/password is rejected immediately."""
        with self.assertRaises(SSRFSecurityError) as ctx:
            safe_fetch_url("http://admin:secret@example.com/")
        self.assertIn("userinfo", str(ctx.exception).lower())

        with self.assertRaises(SSRFSecurityError) as ctx2:
            safe_fetch_url("http://user@example.com/")
        self.assertIn("userinfo", str(ctx2.exception).lower())

    def test_07_non_standard_ports_rejected(self):
        """Verifies only ports 80 and 443 are allowed."""
        for port in [8080, 22, 3000, 6379, 8443]:
            with self.assertRaises(SSRFSecurityError) as ctx:
                safe_fetch_url(f"http://example.com:{port}/")
            self.assertIn("disallowed port", str(ctx.exception).lower())

    def test_08_disallowed_schemes_rejected(self):
        """Verifies non-http/https schemes are rejected."""
        for url in ["file:///etc/passwd", "ftp://ftp.example.com/", "gopher://example.com/"]:
            with self.assertRaises(SSRFSecurityError) as ctx:
                safe_fetch_url(url)
            self.assertIn("disallowed url scheme", str(ctx.exception).lower())

    def test_09_redirect_to_metadata_and_tailscale_blocked(self):
        """Verifies that HTTP redirects to metadata and Tailscale IPs are caught and aborted."""
        # 1. Redirect to metadata
        with patch("network.safe_fetch.resolve_and_validate_host") as mock_dns, \
             patch("network.safe_fetch.socket.create_connection") as mock_conn:

            mock_dns.side_effect = [
                ("93.184.216.34", ["93.184.216.34"]), # First hop safe
                SSRFSecurityError("Redirect host resolved to restricted IP 169.254.169.254") # Second hop
            ]

            mock_sock = MagicMock()
            mock_conn.return_value = mock_sock

            with patch("http.client.HTTPConnection") as mock_http:
                mock_inst = MagicMock()
                mock_resp = MagicMock()
                mock_resp.status = 302
                mock_resp.getheader.side_effect = lambda h: "http://169.254.169.254/meta" if h == "Location" else None
                mock_inst.getresponse.return_value = mock_resp
                mock_http.return_value = mock_inst

                with self.assertRaises(SSRFSecurityError) as ctx:
                    safe_fetch_url("http://example.com/redirect-meta")
                self.assertIn("169.254.169.254", str(ctx.exception))

        # 2. Redirect to Tailscale
        with patch("network.safe_fetch.resolve_and_validate_host") as mock_dns, \
             patch("network.safe_fetch.socket.create_connection") as mock_conn:

            mock_dns.side_effect = [
                ("93.184.216.34", ["93.184.216.34"]),
                SSRFSecurityError("Redirect host resolved to restricted IP 100.100.100.100 (in 100.64.0.0/10)")
            ]
            mock_sock = MagicMock()
            mock_conn.return_value = mock_sock

            with patch("http.client.HTTPConnection") as mock_http:
                mock_inst = MagicMock()
                mock_resp = MagicMock()
                mock_resp.status = 301
                mock_resp.getheader.side_effect = lambda h: "http://100.100.100.100/admin" if h == "Location" else None
                mock_inst.getresponse.return_value = mock_resp
                mock_http.return_value = mock_inst

                with self.assertRaises(SSRFSecurityError) as ctx:
                    safe_fetch_url("http://example.com/redirect-tailscale")
                self.assertIn("100.64.0.0/10", str(ctx.exception))

    def test_10_dns_rebinding_defense(self):
        """Verifies that resolver returning mixed public & private IPs is rejected upfront."""
        with patch("socket.getaddrinfo") as mock_gai:
            # Attacker DNS returns both public IP and private/metadata IP in one answer
            mock_gai.return_value = [
                (2, 1, 6, '', ('93.184.216.34', 80)),
                (2, 1, 6, '', ('169.254.169.254', 80))
            ]
            with self.assertRaises(SSRFSecurityError) as ctx:
                resolve_and_validate_host("rebind.attacker.com", 80)
            self.assertIn("169.254.169.254", str(ctx.exception))

        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, '', ('93.184.216.34', 80)),
                (2, 1, 6, '', ('127.0.0.1', 80))
            ]
            with self.assertRaises(SSRFSecurityError) as ctx:
                resolve_and_validate_host("rebind.attacker.com", 80)
            self.assertIn("127.0.0.1", str(ctx.exception))

    def test_11_valid_public_url_wrapped_in_untrusted_web(self):
        """Verifies valid public fetch succeeds and wraps content in <untrusted_web>."""
        with patch("network.safe_fetch.resolve_and_validate_host") as mock_dns, \
             patch("network.safe_fetch.socket.create_connection") as mock_conn, \
             patch("network.safe_fetch.ssl.create_default_context") as mock_ssl_ctx, \
             patch("network.safe_fetch.http.client.HTTPSConnection") as mock_https:

            mock_dns.return_value = ("93.184.216.34", ["93.184.216.34"])
            mock_sock = MagicMock()
            mock_conn.return_value = mock_sock

            mock_ctx_inst = MagicMock()
            mock_ctx_inst.wrap_socket.return_value = mock_sock
            mock_ssl_ctx.return_value = mock_ctx_inst

            mock_inst = MagicMock()
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.getheader.side_effect = lambda h, d=None: "text/html; charset=utf-8" if h == "Content-Type" else d
            mock_resp.read.side_effect = [b"<h1>Welcome to Verified News</h1><p>Legitimate article.</p>", b""]
            mock_inst.getresponse.return_value = mock_resp
            mock_https.return_value = mock_inst

            res = web_agent.fetch_and_clean_markdown("https://news.example.com/article")
            self.assertTrue(res["success"])
            self.assertIn("<untrusted_web>", res["content"])
            self.assertIn("</untrusted_web>", res["content"])
            self.assertIn("Legitimate article.", res["content"])


if __name__ == "__main__":
    unittest.main()
