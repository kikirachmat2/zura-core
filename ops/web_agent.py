"""
ops/web_agent.py - Zura Autonomous Web Agent & Research Intelligence
Hardened with centralized Anti-SSRF safe_fetch engine:
- Whitelists http/https, ports 80/443, rejects userinfo
- Single DNS resolution, strict IP validation (blocks metadata, private, loopback, CGNAT/Tailscale)
- Max 3 redirect hops re-validated, 2MB size cap, text/HTML content-type only
- Wraps fetched content in <untrusted_web> tags before passing to LLM
"""

import re
import urllib.parse
import logging
from html import unescape
from typing import Dict, Any, List, Optional
from network.safe_fetch import safe_fetch_url, SSRFSecurityError

logger = logging.getLogger("WebAgent")


class AutonomousWebAgent:
    def __init__(self, timeout: int = 12):
        self.timeout = timeout

    def safe_fetch(self, url: str) -> Dict[str, Any]:
        """Direct access to centralized safe fetch engine."""
        return safe_fetch_url(url, timeout=self.timeout)

    def fetch_and_clean_markdown(self, url: str) -> Dict[str, Any]:
        """Fetches web page securely and converts it into markdown wrapped in <untrusted_web> tags."""
        try:
            fetch_res = safe_fetch_url(url, timeout=self.timeout)
            html = fetch_res["raw_text"]

            # 1. Extract Title
            title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            title = unescape(title_m.group(1)).strip() if title_m else "Untitled Page"

            # 2. Strip scripts, styles, navigations, and footers
            cleaned = re.sub(r"<(script|style|nav|footer|header|aside)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)

            # 3. Convert basic HTML structures to Markdown
            cleaned = re.sub(r"<h1[^>]*>(.*?)</h1>", r"\n# \1\n", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"<p[^>]*>(.*?)</p>", r"\n\1\n", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"<li[^>]*>(.*?)</li>", r"\n* \1", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"<[^>]+>", " ", cleaned)
            cleaned = unescape(cleaned)
            cleaned = re.sub(r"[ \t]+", " ", cleaned)
            cleaned = re.sub(r"\n\s*\n+", "\n\n", cleaned).strip()

            trimmed_content = cleaned[:4000]
            # Strict LLM prompt boundary wrapping
            wrapped_content = f"<untrusted_web>\n{trimmed_content}\n</untrusted_web>"

            return {
                "success": True,
                "url": fetch_res["url"],
                "resolved_ip": fetch_res["resolved_ip"],
                "title": title,
                "content": wrapped_content,
                "raw_cleaned": trimmed_content,
                "length": len(trimmed_content)
            }
        except SSRFSecurityError as se:
            logger.warning(f"SSRF violation blocked for URL {url}: {se}")
            return {
                "success": False,
                "url": url,
                "error": f"🚨 Akses ditolak oleh Anti-SSRF Sentinel: {se}"
            }
        except Exception as e:
            logger.error(f"Error fetching URL {url}: {e}")
            return {
                "success": False,
                "url": url,
                "error": str(e)
            }

    def search_web_lite(self, query: str, limit: int = 5) -> List[Dict[str, str]]:
        """Lightweight DuckDuckGo web search extractor running through anti-SSRF engine."""
        encoded_q = urllib.parse.quote_plus(query)
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_q}"

        try:
            fetch_res = safe_fetch_url(search_url, timeout=self.timeout)
            html = fetch_res["raw_text"]

            # Extract search result links and snippets
            results = []
            matches = re.findall(r'<a class="result__url" href="([^"]+)".*?<a class="result__snippet[^>]*>(.*?)</a>', html, re.DOTALL)

            for m in matches[:limit]:
                raw_url, snippet = m
                if "uddg=" in raw_url:
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
                    real_url = parsed.get("uddg", [raw_url])[0]
                else:
                    real_url = raw_url

                clean_snip = re.sub(r"<[^>]+>", "", snippet).strip()
                clean_snip = unescape(clean_snip)
                if clean_snip and "http" in real_url:
                    results.append({
                        "url": real_url,
                        "snippet": f"<untrusted_web>\n{clean_snip}\n</untrusted_web>"
                    })

            return results
        except Exception as e:
            logger.error(f"Error during DuckDuckGo search for '{query}': {e}")
            return []


# Global instance
web_agent = AutonomousWebAgent()
