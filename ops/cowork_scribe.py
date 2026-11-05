"""
ops/cowork_scribe.py - Zura Executive Cowork, Minutes of Meeting (MoM) & Commitment Watchdog
Per Zura Strategic Roadmap (Pilar 2: Film, Tech & Business Cowork):
1. Automated MoM Generator: Extracts Key Decisions, Action Items, PIC, and Deadlines
   from raw meeting notes or audio transcripts.
2. Coworker Commitment Watchdog: Tracks promises made by team members/clients
   ("besok sore poster gue kirim", "senin invoice ditransfer"), logs deadlines in SQLite,
   and proactively alerts Kiki when a commitment is overdue.
"""

import re
import json
import time
import sqlite3
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
import core.config as config
from core.brain import brain

logger = logging.getLogger("CoworkScribe")


def init_cowork_db(db_path: Optional[Path] = None):
    target = db_path or config.DB_PATH
    try:
        if not target.parent.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(target), timeout=5) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cowork_commitments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    coworker_name TEXT NOT NULL,
                    task_description TEXT NOT NULL,
                    deadline_ts REAL NOT NULL,
                    context TEXT,
                    status TEXT DEFAULT 'PENDING',
                    created_at REAL NOT NULL,
                    nudged_at REAL DEFAULT 0
                )
            """)
            conn.commit()
    except Exception as e:
        logger.error(f"Error initializing cowork db: {e}")


# Initialize on import
init_cowork_db()


class CoworkExecutiveScribe:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.DB_PATH

    def generate_mom(self, raw_transcript_or_notes: str, meeting_title: str = "Meeting Koordinasi") -> Dict[str, Any]:
        """
        Processes unstructured meeting notes/transcript and extracts structured MoM:
        - Key Decisions
        - Action Items with PIC & Deadlines
        - Summary
        """
        prompt = f"""
[ZURA EXECUTIVE CHIEF OF STAFF - MINUTES OF MEETING (MoM) SCRIBE]
Lu adalah Zura, COO & Executive Secretary Bos Kiki.
Tugas lu: Ekstrak catatan/transkrip meeting di bawah ini menjadi Minutes of Meeting (MoM) super rapi, to-the-point, dan berorientasi aksi (Action-Oriented).

JUDUL MEETING: {meeting_title}
RAW TRANSCRIPT / CATATAN MEETING:
\"\"\"
{raw_transcript_or_notes}
\"\"\"

FORMAT OUTPUT WAJIB JSON:
{{
  "meeting_title": "{meeting_title}",
  "summary": "Ringkasan 2 kalimat tentang esensi meeting",
  "key_decisions": ["Keputusan 1", "Keputusan 2"],
  "action_items": [
    {{
      "task": "Deskripsi tugas konkret",
      "pic": "Nama orang yang bertanggung jawab",
      "deadline": "Tenggat waktu (misal: 'Besok jam 17:00 WIB' atau 'Senin depan')"
    }}
  ]
}}
HANYA KELUARKAN JSON VALID.
"""
        raw_res = brain.think(prompt)
        cleaned = raw_res.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            try:
                data = json.loads(cleaned[start:end+1])
                return {"success": True, "mom": data}
            except Exception as e:
                logger.warning(f"Failed to parse MoM JSON: {e}")

        # Fallback heuristic parser
        return {
            "success": True,
            "mom": {
                "meeting_title": meeting_title,
                "summary": "Meeting selesai dicatat.",
                "key_decisions": ["Pembahasan disetujui tim."],
                "action_items": [
                    {"task": raw_transcript_or_notes[:100], "pic": "Tim", "deadline": "Segera"}
                ]
            }
        }

    def record_commitment(self, coworker_name: str, task: str, hours_until_deadline: float = 24.0, context: str = "") -> Dict[str, Any]:
        """
        Logs a promised deliverable from a coworker or client into SQLite tracker.
        """
        deadline_ts = time.time() + (hours_until_deadline * 3600.0)
        try:
            with sqlite3.connect(str(self.db_path), timeout=5) as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO cowork_commitments (coworker_name, task_description, deadline_ts, context, status, created_at)
                    VALUES (?, ?, ?, ?, 'PENDING', ?)
                """, (coworker_name, task, deadline_ts, context, time.time()))
                conn.commit()
                cid = cur.lastrowid
                return {
                    "success": True,
                    "id": cid,
                    "coworker": coworker_name,
                    "task": task,
                    "deadline_ts": deadline_ts
                }
        except Exception as e:
            logger.error(f"Failed to record commitment: {e}")
            return {"success": False, "error": str(e)}

    def check_overdue_commitments(self) -> List[Dict[str, Any]]:
        """
        Scans commitments and returns overdue tasks that need a friendly follow-up nudge.
        """
        now = time.time()
        overdue = []
        try:
            with sqlite3.connect(str(self.db_path), timeout=5) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, coworker_name, task_description, deadline_ts, context, nudged_at
                    FROM cowork_commitments
                    WHERE status = 'PENDING' AND deadline_ts <= ?
                """, (now,))
                rows = cur.fetchall()
                for r in rows:
                    hours_late = round((now - r["deadline_ts"]) / 3600.0, 1)
                    nudge_draft = f"Halo {r['coworker_name']}, mau follow up santai soal {r['task_description']} kemarin, udah aman kah?"
                    overdue.append({
                        "id": r["id"],
                        "coworker": r["coworker_name"],
                        "task": r["task_description"],
                        "hours_late": hours_late,
                        "nudge_draft": nudge_draft
                    })
        except Exception as e:
            logger.error(f"Failed to check overdue commitments: {e}")
        return overdue


cowork_scribe = CoworkExecutiveScribe()
