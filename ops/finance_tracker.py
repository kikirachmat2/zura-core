"""
ops/finance_tracker.py - Zura Money-Oriented Financial & Wealth Accelerator
Tracks Bos Kiki's monthly cashflow, counts expenses, and delivers wealth-velocity blueprints:
- Monitors Burn Rate vs Incomes (Shopee Affiliate, Freelance Dev, KiBot PnL)
- Analyzes bank/e-wallet transaction alerts from email_watchdog
- Delivers the "Kaya Cepat" Strategic Blueprint tailored for a money-oriented Developer
"""

import logging
from typing import Dict, Any, List
from core.memory import record_transaction, get_monthly_finance_summary, set_state
from ops.threads_governor import threads_governor

logger = logging.getLogger("FinanceTracker")


class FinanceTracker:
    def __init__(self):
        pass

    def get_full_financial_snapshot(self) -> Dict[str, Any]:
        """Consolidates financial metrics across all active streams."""
        monthly = get_monthly_finance_summary()
        threads_m = threads_governor.get_metrics()

        affiliate_comm = threads_m.get("total_commissions_idr", 0.0)

        snapshot = {
            "month": monthly["month"],
            "income_tracked_idr": monthly["income_idr"],
            "expense_tracked_idr": monthly["expense_idr"],
            "net_cashflow_idr": monthly["net_cashflow_idr"],
            "savings_rate_pct": monthly["savings_rate_pct"],
            "threads_affiliate_comm_idr": affiliate_comm,
            "threads_queue_ready": threads_m.get("queue_count", 0),
            "threads_total_views": threads_m.get("total_views", 0)
        }
        set_state("financial_snapshot", snapshot)
        return snapshot

    def generate_wealth_acceleration_briefing(self) -> str:
        """Zura's signature savage, money-oriented wealth briefing."""
        s = self.get_full_financial_snapshot()

        report = (
            f"💰 <b>FINANCIAL & WEALTH RADAR (Sekretaris Zura):</b>\n\n"
            f"💵 <b>Cashflow Bulan Ini ({s['month']}):</b>\n"
            f"• Pemasukan Tercatat: Rp {s['income_tracked_idr']:,.0f}\n"
            f"• Pengeluaran (Burn Rate): Rp {s['expense_tracked_idr']:,.0f}\n"
            f"• Net Cashflow: Rp {s['net_cashflow_idr']:,.0f} (Saving Rate: {s['savings_rate_pct']}%)\n"
            f"• Komisi Threads Shopee: Rp {s['threads_affiliate_comm_idr']:,.0f}\n\n"
            f"🔥 <b>3 BLUEPRINT ZURA BIAR BOS KIKI KAYA CEPAT:</b>\n"
            f"1. <b>Scale-up Threads Shopee Affiliate:</b>\n"
            f"   Gue udah ambil alih antrean cerita di server. Niche drama kosan & drama kantor lagi top views ({s['threads_total_views']:,} views). Kita rotasi produk Shopee ke kategori elektronik & gadget rumah tangga yang komisinya 5-10% (bukan recehan fashion 2%). Jadwal posting gue kunci di peak jam makan siang (12:15) & santai malam (19:45).\n\n"
            f"2. <b>Developer Leverage (Micro-SaaS & White-Label):</b>\n"
            f"   Bos, lu developer jago. Jangan cuma tuker waktu sama gaji/proyek sekali putus. Script bot yang udah lu punya (Monev WA Bot, Kisah Komisi auto-thread, KiBot DCA) bisa kita package jadi Micro-SaaS langganan bulanan (MRR) buat agensi atau affiliate marketer lain. 20 klien bayar Rp 300rb/bulan = Rp 6jt passive income murni tiap bulan!\n\n"
            f"3. <b>Crypto Compounding Machine (KiBot 70/30):</b>\n"
            f"   Begitu komisi Shopee cair, langsung Zura dorong 30% ke saldo Indodax buat nambah peluru DCA BTC/ETH. Biar duit yang kerja keras, bukan kitanya yang tipes!\n\n"
            f"<i>💅 Motto Zura: 'Kalo gak ngasilin leverage atau cuan, coret dari agenda hari ini!'</i>"
        )
        return report


# Global instance
finance_tracker = FinanceTracker()

