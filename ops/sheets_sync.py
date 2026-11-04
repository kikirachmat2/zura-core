"""
ops/sheets_sync.py - Zura Meticulous Financial Bookkeeper & Spreadsheet Engine
Maintains pristine financial ledgers and exports synced spreadsheets for Bos Kiki:
- Ingests all recorded transactions from zura.db (financial_ledger)
- Formats structured CSV/Excel reports with accounting-grade cleanliness
- Generates categorized monthly summaries (Transport, F&B, Shopping, Utilities, Transfer)
- Dispatches export files directly to Kiki on Telegram
"""

import os
import sys
import csv
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.memory import get_connection, get_monthly_finance_summary

logger = logging.getLogger("SheetsSync")

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_CSV_PATH = DATA_DIR / "Buku_Kas_Bos_Kiki.csv"


class SheetsSyncEngine:
    def __init__(self):
        self.csv_path = EXPORT_CSV_PATH

    def export_ledger_to_csv(self, month_prefix: str = "") -> Path:
        """Exports financial ledger into a clean, accountant-formatted CSV spreadsheet."""
        if not month_prefix:
            month_prefix = datetime.now().strftime("%Y-%m")

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, date, flow_type, amount, category, description, source, timestamp
                FROM financial_ledger
                WHERE date LIKE ?
                ORDER BY date DESC, id DESC
            """, (f"{month_prefix}%",))
            rows = cursor.fetchall()

        # Write clean, UTF-8 encoded CSV with Excel compatibility (BOM)
        with open(self.csv_path, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            # Header
            writer.writerow([
                "ID", "Tanggal", "Tipe Arus", "Nominal (IDR)", "Kategori",
                "Keterangan / Merchant", "Sumber Dana / Akun", "Waktu Pencatatan"
            ])

            total_income = 0.0
            total_expense = 0.0

            for r in rows:
                amt = float(r["amount"] or 0.0)
                flow = str(r["flow_type"]).upper()
                if flow == "INCOME":
                    total_income += amt
                else:
                    total_expense += amt

                logged_time = datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d %H:%M:%S") if r["timestamp"] else "N/A"

                writer.writerow([
                    r["id"],
                    r["date"],
                    "Pemasukan" if flow == "INCOME" else "Pengeluaran",
                    f"{amt:,.2f}",
                    r["category"] or "Umum",
                    r["description"] or "-",
                    r["source"] or "BCA",
                    logged_time
                ])

            # Summary Divider
            writer.writerow([])
            writer.writerow(["---", "RINGKASAN KEUANGAN BULAN INI", f"Bulan: {month_prefix}", "---", "---", "---", "---", "---"])
            writer.writerow(["", "Total Pemasukan", f"Rp {total_income:,.2f}", "", "", "", "", ""])
            writer.writerow(["", "Total Pengeluaran (Burn Rate)", f"Rp {total_expense:,.2f}", "", "", "", "", ""])
            writer.writerow(["", "Net Cashflow", f"Rp {total_income - total_expense:,.2f}", "", "", "", "", ""])

        logger.info(f"Financial spreadsheet successfully generated at: {self.csv_path}")
        return self.csv_path

    def get_category_breakdown(self, month_prefix: str = "") -> List[Dict[str, Any]]:
        """Calculates exact spending distribution across expense categories."""
        if not month_prefix:
            month_prefix = datetime.now().strftime("%Y-%m")

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT category, COUNT(*) as tx_count, SUM(amount) as total_spent
                FROM financial_ledger
                WHERE flow_type = 'expense' AND date LIKE ?
                GROUP BY category
                ORDER BY total_spent DESC
            """, (f"{month_prefix}%",))
            rows = cursor.fetchall()

        total_expense = sum(float(r["total_spent"] or 0.0) for r in rows) or 1.0

        breakdown = []
        for r in rows:
            spent = float(r["total_spent"] or 0.0)
            pct = (spent / total_expense) * 100
            breakdown.append({
                "category": r["category"] or "Lain-lain",
                "count": r["tx_count"],
                "total_spent_idr": spent,
                "percentage": round(pct, 1)
            })

        return breakdown

    def generate_executive_spreadsheet_summary(self) -> str:
        """Produces a pristine, neat financial briefing with category analytics."""
        monthly = get_monthly_finance_summary()
        breakdown = self.get_category_breakdown()

        lines = []
        for b in breakdown:
            lines.append(f"• <b>{b['category']}</b>: Rp {b['total_spent_idr']:,.0f} (<i>{b['percentage']}%</i> - {b['count']} transaksi)")

        breakdown_text = "\n".join(lines) if lines else "<i>Belum ada transaksi tercatat bulan ini.</i>"

        return (
            f"📋 <b>REKAP BUKU KAS & SPREADSHEET (Sekretaris Zura):</b>\n\n"
            f"💵 <b>Bulan Berjalan:</b> <code>{monthly['month']}</code>\n"
            f"• <b>Total Pengeluaran:</b> <code>Rp {monthly['expense_idr']:,.0f}</code>\n"
            f"• <b>Total Pemasukan:</b> <code>Rp {monthly['income_idr']:,.0f}</code>\n"
            f"• <b>Net Saldo:</b> <code>Rp {monthly['net_cashflow_idr']:,.0f}</code>\n\n"
            f"📊 <b>Distribusi Pengeluaran Berdasarkan Kategori:</b>\n"
            f"{breakdown_text}\n\n"
            f"<i>💡 Ketik /sheet untuk mengunduh file spreadsheet (.CSV) lengkapnya ke Telegram!</i>"
        )


# Global instance
sheets_sync = SheetsSyncEngine()

