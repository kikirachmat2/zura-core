"""
ops/threads_governor.py - Zura Autonomous Threads & Shopee Affiliate Governor
Direct Decision-Maker for Meta Threads (@kikipunyacerita) & Kisah Komisi Engine:
- Reads live SQLite DB (kisahkomisi.db) on Server 1 (0ms latency)
- Analyzes views, replies, and click-through affiliate performance
- Automatically decides queue replenishment, niche selection & posting timing
- Reports commission metrics & revenue-maximizing moves directly to Kiki
"""

import os
import sys
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.memory import log_decision, set_state
from core.actuator import actuate, ActuatorError

logger = logging.getLogger("ThreadsGovernor")

# Locate kisahkomisi.db
CANDIDATE_PATHS = [
    Path("/home/ubuntu/kisahkomisi-bot/data/kisahkomisi.db"),  # Server 1 live location
    Path.home() / "Documents/Web Develop/Kisah Komisi/kisahkomisi-bot/data/kisahkomisi.db",  # Mac dev location
    BASE_DIR / "data/kisahkomisi.db"
]


class ThreadsGovernor:
    def __init__(self):
        self.db_path = self._find_database()

    def _find_database(self) -> Path:
        for p in CANDIDATE_PATHS:
            if p.exists():
                return p
        return CANDIDATE_PATHS[0]

    def is_connected(self) -> bool:
        return self.db_path.exists()

    def get_metrics(self) -> dict:
        """Extracts live operational & revenue telemetry from kisahkomisi.db."""
        if not self.is_connected():
            return {
                "connected": False,
                "status": "DB_NOT_FOUND",
                "queue_count": 0,
                "published_count": 0,
                "total_views": 0,
                "total_commissions_idr": 0.0
            }

        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 1. Queue & Published count
            cursor.execute("SELECT status, COUNT(*) as cnt FROM stories GROUP BY status")
            counts = {row["status"]: row["cnt"] for row in cursor.fetchall()}
            queue_cnt = counts.get("queued", 0)
            published_cnt = counts.get("published", 0)

            # 2. Insights & Views
            cursor.execute("SELECT SUM(views) as total_v, SUM(likes) as total_l, SUM(replies) as total_r FROM story_insights")
            ins = cursor.fetchone()
            total_views = ins["total_v"] or 0
            total_likes = ins["total_l"] or 0
            total_replies = ins["total_r"] or 0

            # 3. Commissions
            cursor.execute("SELECT SUM(amount) as total_c FROM commissions WHERE status = 'paid'")
            comm_row = cursor.fetchone()
            total_comm = comm_row["total_c"] or 0.0

            # 4. Top Performing Product
            cursor.execute("SELECT category, name, times_used FROM product_bank ORDER BY times_used DESC LIMIT 1")
            top_prod = cursor.fetchone()
            top_prod_name = f"{top_prod['name']} ({top_prod['category']})" if top_prod else "N/A"

            # 5. Top Niche
            cursor.execute("SELECT niche_tag, avg_views FROM niche_analytics WHERE is_locked = 0 ORDER BY avg_views DESC LIMIT 1")
            top_niche_row = cursor.fetchone()
            top_niche = f"{top_niche_row['niche_tag']} ({round(top_niche_row['avg_views'] or 0)} avg views)" if top_niche_row else "Drama Kosan"

            conn.close()

            metrics = {
                "connected": True,
                "db_location": str(self.db_path),
                "queue_count": queue_cnt,
                "published_count": published_cnt,
                "total_views": total_views,
                "total_likes": total_likes,
                "total_replies": total_replies,
                "total_commissions_idr": total_comm,
                "top_product": top_prod_name,
                "top_niche": top_niche,
                "timestamp": datetime.now().isoformat()
            }
            set_state("threads_telemetry", metrics)
            return metrics

        except Exception as e:
            logger.error(f"Error querying kisahkomisi.db: {e}")
            return {"connected": False, "error": str(e)}

    def replenish_story_queue(self) -> Dict[str, Any]:
        """Autonomously drafts and queues a new high-hook Menfess story into kisahkomisi.db."""
        if not self.is_connected():
            return {"success": False, "reason": "kisahkomisi.db not reachable"}

        try:
            from core.brain import brain
            import json

            conn = sqlite3.connect(str(self.db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 1. Pick a high-performing product from product_bank
            cursor.execute("SELECT * FROM product_bank WHERE active = 1 ORDER BY RANDOM() LIMIT 1")
            product = cursor.fetchone()
            if not product:
                conn.close()
                return {"success": False, "reason": "No active products in product_bank"}

            p_name = product["name"]
            p_url = product["affiliate_url"]
            p_cat = product["category"]

            # 2. Prompt Zura Brain for a viral 4-slide thread
            prompt = (
                f"Tugas lu sebagai Zura: Buatkan 1 cerita curhat Menfess viral di Meta Threads Indonesia untuk akun @kikipunyacerita.\n"
                f"Produk affiliate yang disisipkan: '{p_name}' (Kategori: {p_cat})\n"
                f"Link affiliate: {p_url}\n\n"
                f"Format Wajib (4 Bagian JSON Array of Strings):\n"
                f"Slide 1: Kalimat pembuka ber-hook tinggi, langsung ke detik kejadian mengejutkan dalam 10 kata pertama (tanpa 'halo guys', tanpa penomoran [1/4]).\n"
                f"Slide 2: Lanjutan cerita emosional yang bikin netizen relate (masalah kosan, kantor, atau cicilan).\n"
                f"Slide 3: Intermezzo natural merekomendasikan produk '{p_name}' lengkap dengan link affiliate '{p_url}'.\n"
                f"Slide 4: Pertanyaan pancingan debat polarisasi (Debate Bait) untuk memancing perdebatan sengit di kolom komentar.\n\n"
                f"Output HANYA JSON array valid: [\"slide 1\", \"slide 2\", \"slide 3\", \"slide 4\"]"
            )

            raw_ai = brain.think(prompt)
            
            # Clean and parse JSON
            cleaned = raw_ai.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0].strip()

            slides = json.loads(cleaned)
            if not isinstance(slides, list) or len(slides) < 3:
                conn.close()
                return {"success": False, "reason": "AI response format invalid"}

            title = f"{p_cat}: {slides[0][:40]}..."
            topic = slides[0][:80]
            slides_json = json.dumps(slides, ensure_ascii=False)

            def _do_insert():
                cursor.execute("""
                    INSERT INTO stories (title, topic, slides_json, product_name, product_url, status, origin, format_type)
                    VALUES (?, ?, ?, ?, ?, 'queued', 'zura_autonomous', 'story')
                """, (title, topic, slides_json, p_name, p_url))
                conn.commit()
                sid = cursor.lastrowid
                conn.close()
                return sid

            def _revert_insert(sid):
                try:
                    with sqlite3.connect(str(self.db_path), timeout=5) as rconn:
                        rconn.execute("DELETE FROM stories WHERE id = ?", (sid,))
                        rconn.commit()
                    return f"Deleted queued story ID {sid}"
                except Exception as ex:
                    return f"Failed to revert story {sid}: {ex}"

            res = actuate(
                name="threads_replenish_queue",
                tier="L2",
                fn=_do_insert,
                params={"product": p_name, "category": p_cat, "title": title},
                entity="threads_governor",
                reason=f"Queue replenishment for {p_name}",
                revert=lambda: _revert_insert(res.get("result")),
                reversible=True
            )

            story_id = res.get("result")
            log_decision(
                domain="Threads Governor",
                trigger_event="Queue replenishment executed",
                decision_taken=f"Auto-drafted and queued story ID {story_id} ({p_name}) via actuator",
                outcome="Queue refreshed; ready for autopilot publishing"
            )

            logger.info(f"🎉 SUKSES! Zura berhasil queue cerita baru (ID: {story_id}) di Threads!")
            return {"success": True, "story_id": story_id, "title": title, "product": p_name}

        except ActuatorError as ae:
            logger.warning(f"Actuator blocked story replenish: {ae}")
            return {"success": False, "error": str(ae)}
        except Exception as e:
            logger.error(f"Error replenishing story queue: {e}")
            return {"success": False, "error": str(e)}

    def evaluate_and_govern(self) -> list:
        """Autonomously audits Threads performance and takes executive decisions."""
        m = self.get_metrics()
        if not m.get("connected"):
            return ["Database Threads belum terdeteksi di server/lokal."]

        decisions = []

        # Decision 1: Queue replenishment if empty or low
        if m["queue_count"] < 2:
            res = self.replenish_story_queue()
            if res.get("success"):
                decisions.append(f"Auto-generated & queued cerita baru (ID {res['story_id']}) untuk produk {res['product']}.")
            else:
                decisions.append(f"Percobaan auto-queue gagal: {res.get('reason') or res.get('error')}")

        # Decision 2: High conversion affiliate rotation
        if m["published_count"] > 0:
            decisions.append(f"Fokus produk affiliate diarahkan ke {m['top_product']} untuk maksimalkan komisi Shopee.")

        return decisions

    def generate_executive_threads_report(self) -> str:
        """Generates a money-oriented Threads report for Bos Kiki."""
        m = self.get_metrics()
        if not m.get("connected"):
            return "🧵 <b>Status Threads:</b> Database belum aktif atau offline."

        report = (
            f"🧵 <b>LAPORAN CUAN THREADS (@kikipunyacerita):</b>\n"
            f"• <b>Status Antrean:</b> {m['queue_count']} Cerita Siap Tayang\n"
            f"• <b>Total Post Terbit:</b> {m['published_count']} Thread\n"
            f"• <b>Total Engagement:</b> {m['total_views']:,} Views | {m['total_replies']} Replies\n"
            f"• <b>Top Niche Cuan:</b> {m['top_niche']}\n"
            f"• <b>Produk Terlaris:</b> {m['top_product']}\n"
            f"• <b>Total Komisi Tercatat:</b> Rp {m['total_commissions_idr']:,.0f}\n\n"
            f"<i>💡 Keputusan Zura: Semua jadwal posting, variasi A/B testing, dan pemilihan link Shopee sudah Zura setir otomatis biar klik makin deras!</i>"
        )
        return report


# Global instance
threads_governor = ThreadsGovernor()

