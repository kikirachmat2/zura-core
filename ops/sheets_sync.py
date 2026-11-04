"""
ops/sheets_sync.py - Zura Meticulous Financial Bookkeeper & Spreadsheet Engine (DECOMMISSIONED)
Spreadsheet syncing and financial ledger exports are decommissioned
per Zura Charter v2 (Out-of-scope).
"""

import logging
from pathlib import Path

logger = logging.getLogger("SheetsSync")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
EXPORT_CSV_PATH = DATA_DIR / "Buku_Kas_Bos_Kiki.csv"


class SheetsSyncEngine:
    def __init__(self):
        self.csv_path = EXPORT_CSV_PATH

    def export_ledger_to_csv(self, month_prefix: str = "") -> Path:
        """Decommissioned: does not query financial ledger."""
        return self.csv_path

    def generate_executive_spreadsheet_summary(self, month_prefix: str = "") -> str:
        """Decommissioned notice."""
        return (
            "📊 <b>BUKU KAS & SPREADSHEET:</b>\n\n"
            "⚠️ <i>Fitur sinkronisasi spreadsheet dan buku kas telah dinonaktifkan (di luar scope Zura Charter v2).</i>\n\n"
            "• Status Ledger: <code>tidak diketahui</code>\n"
            "• Saldo Kas: <code>tidak diketahui</code>"
        )


# Global instance
sheets_sync = SheetsSyncEngine()
