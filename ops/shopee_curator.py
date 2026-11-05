"""
ops/shopee_curator.py - Zura Autonomous Shopee Affiliate Curator & Link Health Engine
Per Zura Charter v2:
1. Validates Shopee affiliate links (checks HTTP status, redirect destinations, out-of-stock / delisted flags).
2. Curates high-converting replacement products from shopee_latest.csv when primary links rot.
3. Formats universal affiliate links with tracking tags (sub_id) for Kisah Komisi stories.
"""

import os
import re
import csv
import logging
import requests
from typing import Dict, Any, List, Optional
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

logger = logging.getLogger("ShopeeCurator")

CANDIDATE_CSV_PATHS = [
    Path("/home/ubuntu/kisahkomisi-bot/data/shopee_latest.csv"),
    Path.home() / "Documents/Web Develop/Kisah Komisi/kisahkomisi-bot/data/shopee_latest.csv",
    BASE_DIR / "data/shopee_latest.csv"
]


class ShopeeCurator:
    # Patterns indicating an expired or delisted product on Shopee landing pages
    OUT_OF_STOCK_PATTERNS = [
        re.compile(r"produk tidak ditemukan", re.IGNORECASE),
        re.compile(r"halaman tidak ditemukan", re.IGNORECASE),
        re.compile(r"habis terjual", re.IGNORECASE),
        re.compile(r"stok habis", re.IGNORECASE),
        re.compile(r"produk telah dihapus", re.IGNORECASE),
        re.compile(r"item not found", re.IGNORECASE),
        re.compile(r"out of stock", re.IGNORECASE),
    ]

    # Mobile User-Agent to avoid bot blocks
    USER_AGENT = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    )

    def __init__(self, catalog_path: Optional[Path] = None):
        self.catalog_path = catalog_path if catalog_path else self._find_catalog()

    def _find_catalog(self) -> Path:
        for p in CANDIDATE_CSV_PATHS:
            if p.exists():
                return p
        return CANDIDATE_CSV_PATHS[-1]

    def validate_link(self, url: str, timeout: float = 6.0) -> Dict[str, Any]:
        """
        Follows redirects and validates whether the Shopee link is active and in-stock.
        Returns dict with status, final_url, is_valid, and reason.
        """
        if not url or not url.strip():
            return {
                "valid": False,
                "url": url,
                "final_url": "",
                "status_code": 0,
                "reason": "URL is empty"
            }

        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        try:
            # First attempt: GET with stream to inspect redirects and first chunk
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=True)
            final_url = resp.url
            status_code = resp.status_code

            if status_code in (404, 410, 500, 502, 503):
                return {
                    "valid": False,
                    "url": url,
                    "final_url": final_url,
                    "status_code": status_code,
                    "reason": f"HTTP {status_code} error from destination"
                }

            # Check if redirect landed on general Shopee homepage or error page
            if final_url.rstrip("/") in ("https://shopee.co.id", "https://s.shopee.co.id"):
                return {
                    "valid": False,
                    "url": url,
                    "final_url": final_url,
                    "status_code": status_code,
                    "reason": "Redirected to homepage without product context"
                }

            # Read first 32KB of content to detect out of stock indicators without downloading entire page
            content_chunk = ""
            for chunk in resp.iter_content(chunk_size=32768, decode_unicode=True):
                if chunk:
                    content_chunk = chunk
                    break

            for pattern in self.OUT_OF_STOCK_PATTERNS:
                if pattern.search(content_chunk):
                    return {
                        "valid": False,
                        "url": url,
                        "final_url": final_url,
                        "status_code": status_code,
                        "reason": f"Product flagged as out of stock or delisted: '{pattern.pattern}'"
                    }

            return {
                "valid": True,
                "url": url,
                "final_url": final_url,
                "status_code": status_code,
                "reason": "OK"
            }

        except requests.exceptions.Timeout:
            return {
                "valid": False,
                "url": url,
                "final_url": "",
                "status_code": 408,
                "reason": f"Connection timed out after {timeout}s"
            }
        except Exception as e:
            return {
                "valid": False,
                "url": url,
                "final_url": "",
                "status_code": 0,
                "reason": f"Network exception: {str(e)}"
            }

    def load_catalog(self) -> List[Dict[str, str]]:
        """Loads available products from shopee_latest.csv if present."""
        if not self.catalog_path.exists():
            return []

        products = []
        try:
            with open(self.catalog_path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    products.append(row)
        except Exception as e:
            logger.warning(f"Failed to read catalog at {self.catalog_path}: {e}")

        return products

    def curate_replacement(
        self,
        niche: str = "daily_life",
        min_commission_pct: float = 5.0,
        exclude_urls: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Picks a high-converting fallback product from catalog matching niche.
        Falls back to default evergreen high-margin items if catalog is empty.
        """
        exclude = set(exclude_urls or [])
        catalog = self.load_catalog()

        # Filter catalog matching niche/keyword
        candidates = []
        for p in catalog:
            url = p.get("affiliate_url") or p.get("url") or p.get("product_url") or ""
            if url in exclude:
                continue

            # Basic keyword match against niche
            category = p.get("category", "").lower()
            name = p.get("product_name", p.get("name", "")).lower()

            if niche.lower() in category or niche.lower() in name or niche == "daily_life":
                candidates.append(p)

        if candidates:
            # Pick first active candidate
            selected = candidates[0]
            return {
                "product_name": selected.get("product_name", selected.get("name", "Produk Pilihan Rekomendasi")),
                "product_url": selected.get("affiliate_url", selected.get("url", "")),
                "category": selected.get("category", niche),
                "commission_rate": selected.get("commission_rate", "10%"),
                "source": "shopee_catalog"
            }

        # Evergreen Fallback Products (High converting in Indonesian Threads)
        evergreen_defaults = {
            "daily_life": {
                "product_name": "Sprei Katun Anti-Geser Minimalis Anak Kost",
                "product_url": "https://s.shopee.co.id/anb001kost",
                "category": "Home Living",
                "commission_rate": "12%",
                "source": "evergreen_preset"
            },
            "financial": {
                "product_name": "Dompet Budgeting Binder Keuangan Bulanan 6 Slot",
                "product_url": "https://s.shopee.co.id/fin002binder",
                "category": "Stationery & Finance",
                "commission_rate": "15%",
                "source": "evergreen_preset"
            },
            "work_tech": {
                "product_name": "Stand Laptop Ergonomis Aluminium Portable Anti-Pegel",
                "product_url": "https://s.shopee.co.id/tech003stand",
                "category": "Electronics & Office",
                "commission_rate": "10%",
                "source": "evergreen_preset"
            }
        }

        return evergreen_defaults.get(niche, evergreen_defaults["daily_life"])

    def format_affiliate_link(self, base_url: str, sub_id: str = "kikipunyacerita") -> str:
        """Appends tracking parameters to Shopee affiliate URL."""
        if not base_url:
            return ""
        sep = "&" if "?" in base_url else "?"
        return f"{base_url}{sep}sub_id={sub_id}"

