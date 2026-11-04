"""
core/memory.py - Zura Persistent SQLite Memory & State Ledger
Stores chat history, system telemetry, and autonomous decision logs.
"""

import sqlite3
import json
import time
from typing import Dict, Any, List, Optional
from core.config import DB_PATH, DATA_DIR

DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes schema for Zura's memory system."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Conversation History
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                role TEXT,
                content TEXT,
                media_type TEXT DEFAULT 'text',
                timestamp REAL
            )
        """)
        
        # 2. Autonomous Decision Ledger (COO decisions taken)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decisions_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT,
                trigger_event TEXT,
                decision_taken TEXT,
                outcome TEXT,
                timestamp REAL
            )
        """)
        
        # 3. System State Key-Value Store
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at REAL
            )
        """)
        
        # 4. Sensor & Alert Telemetry
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT,
                source TEXT,
                message TEXT,
                resolved INTEGER DEFAULT 0,
                timestamp REAL
            )
        """)

        # 5. Financial Cashflow & Wealth Ledger
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS financial_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                amount REAL,
                flow_type TEXT CHECK(flow_type IN ('income', 'expense')),
                category TEXT,
                description TEXT,
                source TEXT,
                timestamp REAL
            )
        """)
        
        conn.commit()


# --- Decision Ledger Helpers ---
def log_decision(domain: str, trigger_event: str, decision_taken: str, outcome: str):
    """Records an autonomous decision made by Zura without Kiki's prompt."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO decisions_log (domain, trigger_event, decision_taken, outcome, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (domain, trigger_event, decision_taken, outcome, time.time()))
        conn.commit()


def get_recent_decisions(limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieves recent decisions for executive briefing."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT domain, trigger_event, decision_taken, outcome, timestamp
            FROM decisions_log
            ORDER BY timestamp DESC LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


# --- State Helpers ---
def set_state(key: str, value: Any):
    val_str = json.dumps(value) if not isinstance(value, str) else value
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO system_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (key, val_str, time.time()))
        conn.commit()


def get_state(key: str, default: Any = None) -> Any:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_state WHERE key = ?", (key,))
        row = cursor.fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]


# --- Chat History Helpers ---
def save_message(chat_id: int, role: str, content: str, media_type: str = "text"):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO conversation_history (chat_id, role, content, media_type, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, role, content, media_type, time.time()))
        conn.commit()


def get_recent_chat(chat_id: int, limit: int = 12) -> List[Dict[str, str]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT role, content FROM conversation_history
            WHERE chat_id = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (chat_id, limit))
        rows = cursor.fetchall()
        # Return in chronological order
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# --- Financial Ledger Helpers ---
def record_transaction(amount: float, flow_type: str, category: str, description: str, source: str = "manual", tx_date: str = ""):
    """Records an income or expense transaction."""
    if not tx_date:
        import datetime
        tx_date = datetime.date.today().isoformat()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO financial_ledger (date, amount, flow_type, category, description, source, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (tx_date, amount, flow_type, category, description, source, time.time()))
        conn.commit()


def get_monthly_finance_summary(month_prefix: str = "") -> Dict[str, Any]:
    """Calculates income, expense, and net savings for the given month (YYYY-MM)."""
    if not month_prefix:
        import datetime
        month_prefix = datetime.date.today().strftime("%Y-%m")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT flow_type, SUM(amount) as total
            FROM financial_ledger
            WHERE date LIKE ?
            GROUP BY flow_type
        """, (f"{month_prefix}%",))
        rows = cursor.fetchall()

        income = 0.0
        expense = 0.0
        for r in rows:
            if r["flow_type"] == "income":
                income = r["total"] or 0.0
            elif r["flow_type"] == "expense":
                expense = r["total"] or 0.0

        net = income - expense
        savings_rate = round((net / income * 100), 1) if income > 0 else 0.0

        return {
            "month": month_prefix,
            "income_idr": income,
            "expense_idr": expense,
            "net_cashflow_idr": net,
            "savings_rate_pct": savings_rate
        }


# Initialize DB on load
init_db()

