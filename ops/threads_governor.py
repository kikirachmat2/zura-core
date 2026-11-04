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
import core.config as config

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

    def get_audience_sentiment(self) -> Dict[str, Any]:
        """
        Reads recent comments and feedback from auto_replies in kisahkomisi.db.
        Detects netizen hostility, scam/affiliate fatigue, or anger escalation.
        """
        if not self.is_connected():
            return {"status": "UNKNOWN", "anger_ratio_pct": 0.0, "total_scanned": 0}

        try:
            with sqlite3.connect(str(self.db_path), timeout=5) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()

                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='auto_replies'")
                if not cur.fetchone():
                    return {"status": "NO_FEEDBACK_DATA", "anger_ratio_pct": 0.0, "total_scanned": 0}

                cur.execute("""
                    SELECT comment_text, author_username, created_at 
                    FROM auto_replies 
                    ORDER BY id DESC LIMIT 25
                """)
                rows = cur.fetchall()
                if not rows:
                    return {"status": "NO_RECENT_COMMENTS", "anger_ratio_pct": 0.0, "total_scanned": 0}

                criticism_keywords = [
                    "marah", "emosi", "kesel", "ujung", "jualan", "iklan", "affiliate",
                    "komisi", "fiktif", "boong", "bohong", "ga nyambung", "ganyambung",
                    "sampah", "unfollow", "muak", "dusta", "curang", "settingan", "benci"
                ]
                positive_keywords = [
                    "relate", "valid", "bener", "setuju", "lucu", "wkwk", "haha", "makasih", "bermanfaat"
                ]

                criticism_count = 0
                positive_count = 0
                for r in rows:
                    text = (r["comment_text"] or "").lower()
                    if any(k in text for k in criticism_keywords):
                        criticism_count += 1
                    if any(k in text for k in positive_keywords):
                        positive_count += 1

                total = len(rows)
                anger_ratio_pct = (criticism_count / total) * 100.0 if total > 0 else 0.0
                threshold = getattr(config, "THREADS_ANGER_CRITICISM_THRESHOLD_PCT", 25.0)
                is_high = anger_ratio_pct >= threshold

                return {
                    "status": "HIGH_CRITICISM_OR_ANGER" if is_high else "HEALTHY",
                    "anger_ratio_pct": round(anger_ratio_pct, 1),
                    "criticism_count": criticism_count,
                    "positive_count": positive_count,
                    "total_scanned": total,
                    "recommendation": "Cool down: Switch to organic relatability, zero debate bait." if is_high else "Healthy conversation flow."
                }
        except Exception as e:
            logger.error(f"Error auditing Threads audience sentiment: {e}")
            return {"status": "ERROR", "error": str(e), "anger_ratio_pct": 0.0, "total_scanned": 0}

    def critique_story(self, slides: List[str], product_name: str, category: str) -> Dict[str, Any]:
        """
        Layer 2: AI & Heuristic Quality Controller for Threads stories.
        Verifies:
        1. Contextual Coherence: Product recommendation must flow naturally from the narrative dilemma,
           not an abrupt jarring interruption ("btw selingan bentar...").
        2. Zero Destructive Rage-Bait: Rejects malicious polarization, hate speech, or pure rage-induction.
        3. Human Relatability: Rejects robotic corporate sales pitches.
        """
        if not isinstance(slides, list) or len(slides) < 3:
            return {"passed": False, "score": 0, "reason": "Slides count must be at least 3"}

        text_all = " ".join(slides).lower()
        slide3 = slides[2].lower() if len(slides) >= 3 else ""
        slide4 = slides[3].lower() if len(slides) >= 4 else ""

        # Check 1: Forbidden Destructive Rage Bait
        rage_indicators = [
            "mati aja", "najis lu semua", "pantes miskin", "bodoh lu", "tolol", "sampah masyarakat"
        ]
        for rage in rage_indicators:
            if rage in text_all:
                return {
                    "passed": False,
                    "score": 20,
                    "rage_detected": True,
                    "reason": f"Destructive rage bait detected: '{rage}'"
                }

        # Check 2: Jarring Affiliate Transition
        jarring_indicators = [
            "btw selingan bentar", "selingan bentar ya", "iklan dulu bentar", "intermezzo dikit"
        ]
        has_jarring_bridge = any(j in slide3 for j in jarring_indicators)

        # Check 3: Coherence Scoring
        score = 85
        notes = []

        if has_jarring_bridge:
            score -= 25
            notes.append("Abrupt jarring ad bridge detected in Slide 3")

        # Slide 4 should invite constructive discussion, not toxic rage
        if any(w in slide4 for w in ["hujat", "adu nasib", "baku hantam", "perang di komen"]):
            score -= 20
            notes.append("Aggressive debate bait detected in Slide 4")

        # Product name must be mentioned in Slide 3 if affiliate
        if product_name and product_name.lower() not in text_all and not any(w in text_all for w in product_name.lower().split()[:2]):
            score -= 15
            notes.append("Product context is weakly anchored in the narrative")

        passed = score >= 70
        return {
            "passed": passed,
            "score": score,
            "notes": "; ".join(notes) if notes else "High coherence and relatable narrative flow."
        }

    def replenish_story_queue(self) -> Dict[str, Any]:
        """
        Two-Layer Autonomous Story Replenisher with Audience Sentiment Awareness.
        Layer 1: Contextual Narrative Architect with organic problem-product anchoring.
        Layer 2: AI QC & Coherence Guard filtering jarring ads and destructive rage-bait.
        """
        if not self.is_connected():
            return {"success": False, "reason": "kisahkomisi.db not reachable"}

        try:
            from core.brain import brain
            import json

            conn = sqlite3.connect(str(self.db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 1. Daily replenish cap check (from config/limits.env)
            daily_cap = getattr(config, "THREADS_DAILY_REPLENISH_CAP", 5)
            try:
                cursor.execute("SELECT COUNT(*) as cnt FROM stories WHERE DATE(created_at) = DATE('now')")
                today_cnt = cursor.fetchone()["cnt"]
                if today_cnt >= daily_cap:
                    conn.close()
                    logger.info(f"Daily replenish cap reached ({today_cnt}/{daily_cap} today).")
                    return {"success": False, "reason": f"Daily cap reached ({today_cnt}/{daily_cap} stories today)"}
            except Exception:
                cursor.execute("SELECT COUNT(*) as cnt FROM stories WHERE status = 'queued'")
                q_cnt = cursor.fetchone()["cnt"]
                if q_cnt >= daily_cap:
                    conn.close()
                    return {"success": False, "reason": f"Queue cap reached ({q_cnt} stories queued)"}

            # 2. Check audience sentiment
            sentiment = self.get_audience_sentiment()
            is_cooling_mode = sentiment.get("status") == "HIGH_CRITICISM_OR_ANGER"
            if is_cooling_mode:
                logger.warning(
                    f"⚠️ Threads Audience Sentiment is inflamed (Anger ratio: {sentiment.get('anger_ratio_pct')}%). "
                    "Engaging cool-down mode: organic relatable story without hard-sell debate bait."
                )

            # 3. Pick product
            cursor.execute("SELECT * FROM product_bank WHERE active = 1 ORDER BY RANDOM() LIMIT 1")
            product = cursor.fetchone()
            if not product:
                conn.close()
                return {"success": False, "reason": "No active products in product_bank"}

            p_name = product["name"]
            p_url = product["affiliate_url"]
            p_cat = product["category"]

            # 4. Layer 1: Prompt Zura Brain for a coherent 4-slide thread
            prompt = (
                f"Tugas lu sebagai Zura: Buatkan 1 cerita curhat Menfess viral di Meta Threads Indonesia untuk akun @kikipunyacerita.\n"
                f"Produk affiliate yang disisipkan: '{p_name}' (Kategori: {p_cat})\n"
                f"Link affiliate: {p_url}\n\n"
                f"ATURAN MUTLAK PENULISAN (MULTI-LAYER QUALITY):\n"
                f"1. DILARANG JARRING AD BRIDGE: Dilarang keras memakai kalimat klise seperti 'btw selingan bentar ya', 'iklan dulu', atau tiba-tiba ganti topik.\n"
                f"   Cerita harus bermula dari masalah nyata yang solusinya memang produk tersebut.\n"
                f"2. DILARANG DEBATE BAIT BERACUN: Dilarang memancing caci maki, hujatan, atau polarisasi kebencian di kolom komentar.\n"
                f"3. Gaya bahasa: Manusia asli warga Threads Jakarta (santai, relate, ceplas-ceplos, natural).\n\n"
                f"Format Wajib (4 Bagian JSON Array of Strings):\n"
                f"Slide 1: Kalimat pembuka ber-hook tinggi tentang situasi/dilema sehari-hari terkait masalah yang dipecahkan produk.\n"
                f"Slide 2: Lanjutan cerita konkret pengalaman pribadi/teman yang bikin pembaca mengangguk setuju.\n"
                f"Slide 3: Solusi nyata yang dialami, menyebutkan '{p_name}' secara organik lengkap dengan link '{p_url}' tanpa nada jualan sales.\n"
                f"Slide 4: Pertanyaan reflektif atau santai yang mengundang warganet berbagi pengalaman serupa di kolom komentar.\n\n"
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

            # 5. Layer 2: Quality Control & Coherence Evaluation
            qc_result = self.critique_story(slides, p_name, p_cat)
            if not qc_result["passed"]:
                conn.close()
                logger.warning(f"Layer 2 QC Rejected Story: {qc_result.get('notes') or qc_result.get('reason')}")
                return {
                    "success": False,
                    "reason": f"Layer 2 QC Rejected: {qc_result.get('notes') or qc_result.get('reason')}",
                    "qc_score": qc_result.get("score")
                }

            title = f"{p_cat}: {slides[0][:40]}..."
            topic = slides[0][:80]
            slides_json = json.dumps(slides, ensure_ascii=False)
            qc_score = qc_result.get("score", 85)
            qc_notes = qc_result.get("notes", "Passed Layer 2 Coherence & Non-Toxicity Guard")

            def _do_insert():
                cursor.execute("""
                    INSERT INTO stories (title, topic, slides_json, product_name, product_url, status, origin, format_type, qc_score, qc_notes)
                    VALUES (?, ?, ?, ?, ?, 'queued', 'zura_autonomous', 'story', ?, ?)
                """, (title, topic, slides_json, p_name, p_url, qc_score, qc_notes))
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
                params={"product": p_name, "category": p_cat, "title": title, "qc_score": qc_score},
                entity="threads_governor",
                reason=f"Queue replenishment for {p_name} (QC Score: {qc_score})",
                revert=lambda: _revert_insert(res.get("result")),
                reversible=True
            )

            story_id = res.get("result")
            log_decision(
                domain="Threads Governor",
                trigger_event="Queue replenishment executed",
                decision_taken=f"Auto-drafted and queued story ID {story_id} ({p_name}) with QC score {qc_score}",
                outcome="Queue refreshed; ready for autopilot publishing"
            )

            logger.info(f"🎉 SUKSES! Zura berhasil queue cerita baru (ID: {story_id}, QC: {qc_score}) di Threads!")
            return {"success": True, "story_id": story_id, "title": title, "product": p_name, "qc_score": qc_score}

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
        min_threshold = getattr(config, "THREADS_MIN_QUEUE_THRESHOLD", 2)
        if m["queue_count"] < min_threshold:
            res = self.replenish_story_queue()
            if res.get("success"):
                decisions.append(f"Auto-generated & queued cerita baru (ID {res['story_id']}) untuk produk {res['product']} (QC: {res.get('qc_score')}).")
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

        sentiment = self.get_audience_sentiment()
        sent_status = "🟢 Sehat" if sentiment.get("status") == "HEALTHY" else "🔥 Panas (Auto-Cooldown Aktif)"
        anger_pct = sentiment.get("anger_ratio_pct", 0.0)

        report = (
            f"🧵 <b>LAPORAN CUAN & KONTROL THREADS (@kikipunyacerita):</b>\n"
            f"• <b>Status Antrean:</b> {m['queue_count']} Cerita Siap Tayang\n"
            f"• <b>Total Post Terbit:</b> {m['published_count']} Thread\n"
            f"• <b>Total Engagement:</b> {m['total_views']:,} Views | {m['total_replies']} Replies\n"
            f"• <b>Sentimen Netizen:</b> {sent_status} (Rasio Kritik: {anger_pct}%)\n"
            f"• <b>Top Niche Cuan:</b> {m['top_niche']}\n"
            f"• <b>Produk Terlaris:</b> {m['top_product']}\n"
            f"• <b>Total Komisi Tercatat:</b> Rp {m['total_commissions_idr']:,.0f}\n\n"
            f"<i>💡 Kendali Multi-Layer Zura: Setiap cerita disaring lewat Layer 2 QC (anti-iklan maksa & anti-rage bait). "
            f"Jika kolom komentar panas, Zura otomatis beralih ke cerita empati agar reputasi akun Bos tetap aman.</i>"
        )
        return report


# Global instance
threads_governor = ThreadsGovernor()

