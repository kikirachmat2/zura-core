"""
core/supabase_hub.py - Secondary Offsite Backup & Alternative Cloud Mirror
ROLE: Secondary Backup & Alternative Channel ONLY (Local SQLite is Primary Source of Truth).
All calls here are non-blocking / shadow mirrors. If Supabase is unreachable, all core
operations in Zura, KisahKomisi, and KiBot continue with zero interruption from local SQLite.
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

from core.config import (
    SUPABASE_DB_HOST, SUPABASE_DB_PORT, SUPABASE_DB_USER,
    SUPABASE_DB_PASS, SUPABASE_DB_NAME
)

logger = logging.getLogger("SupabaseHub")


def get_pg_connection():
    """Returns a new PostgreSQL connection to Supabase pooler."""
    if not psycopg2 or not SUPABASE_DB_PASS:
        return None

    try:
        conn = psycopg2.connect(
            host=SUPABASE_DB_HOST,
            port=SUPABASE_DB_PORT,
            dbname=SUPABASE_DB_NAME,
            user=SUPABASE_DB_USER,
            password=SUPABASE_DB_PASS,
            connect_timeout=6,
            sslmode="require"
        )
        return conn
    except Exception as e:
        logger.warning(f"⚠️ Supabase PostgreSQL connection failed: {e}")
        return None


# =====================================================================
# 1. FLEET TELEMETRY & HEARTBEAT
# =====================================================================

def update_fleet_heartbeat(bot_id: str, bot_name: str, role: str, status: str, host: str = "SG1 Cloud", metrics: Optional[Dict[str, Any]] = None) -> bool:
    """Updates live heartbeat and system metrics for a bot in Supabase."""
    conn = get_pg_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fleet_telemetry (bot_id, bot_name, role, status, last_heartbeat, host, metrics, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), %s, %s, NOW())
                ON CONFLICT (bot_id) DO UPDATE SET
                    bot_name = EXCLUDED.bot_name,
                    role = EXCLUDED.role,
                    status = EXCLUDED.status,
                    last_heartbeat = NOW(),
                    host = EXCLUDED.host,
                    metrics = EXCLUDED.metrics,
                    updated_at = NOW();
            """, (bot_id, bot_name, role, status, host, json.dumps(metrics or {})))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error updating fleet heartbeat: {e}")
        return False
    finally:
        conn.close()


def get_fleet_telemetry() -> List[Dict[str, Any]]:
    """Retrieves current telemetry of all fleet bots (Zura, Threads, KiBot)."""
    conn = get_pg_connection()
    if not conn:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT bot_id, bot_name, role, status, last_heartbeat, host, metrics,
                       EXTRACT(EPOCH FROM (NOW() - last_heartbeat)) as seconds_since_heartbeat
                FROM fleet_telemetry
                ORDER BY bot_id;
            """)
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching fleet telemetry: {e}")
        return []
    finally:
        conn.close()


# =====================================================================
# 2. TRI-PARTY HYBRID EVENT BUS
# =====================================================================

def publish_event(
    sender: str,
    recipient: str,
    topic: str,
    action: str,
    payload: Dict[str, Any],
    telegram_broadcast: bool = False
) -> Optional[int]:
    """Publishes a cross-bot event to the tri-party bus."""
    conn = get_pg_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tri_party_bus (sender, recipient, topic, action, payload, telegram_broadcast, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', NOW())
                RETURNING id;
            """, (sender, recipient, topic, action, json.dumps(payload), telegram_broadcast))
            row = cur.fetchone()
            conn.commit()
            return row[0] if row else None
    except Exception as e:
        logger.error(f"Error publishing to tri_party_bus: {e}")
        return None
    finally:
        conn.close()


def fetch_pending_events(recipient: str = "zura", limit: int = 10) -> List[Dict[str, Any]]:
    """Fetches pending events targeted at recipient or 'all'."""
    conn = get_pg_connection()
    if not conn:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, event_id, sender, recipient, topic, action, payload, telegram_broadcast, status, created_at
                FROM tri_party_bus
                WHERE status = 'PENDING'
                  AND (recipient = %s OR recipient = 'all')
                  AND NOT (%s = ANY(processed_by))
                ORDER BY id ASC
                LIMIT %s;
            """, (recipient, recipient, limit))
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching pending events: {e}")
        return []
    finally:
        conn.close()


def mark_event_processed(event_id_or_row_id: int, bot_id: str = "zura", final_status: str = "COMPLETED") -> bool:
    """Marks an event as acknowledged and processed by the bot."""
    conn = get_pg_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE tri_party_bus
                SET processed_by = array_append(processed_by, %s),
                    status = %s
                WHERE id = %s;
            """, (bot_id, final_status, event_id_or_row_id))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error marking event processed: {e}")
        return False
    finally:
        conn.close()


# =====================================================================
# 3. THREADS STAGING & DELIBERATION
# =====================================================================

def stage_threads_post(
    story_id: Optional[int],
    slot_number: int,
    slot_time: str,
    draft_text: str,
    topic: str,
    product_name: str,
    affiliate_link: str,
    virality_score: float = 0.0,
    deliberation_start: Optional[float] = None
) -> Optional[int]:
    """Stages a draft from KisahKomisi bot into Supabase for Zura's review."""
    conn = get_pg_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO threads_staging (
                    story_id, slot_number, slot_time, deliberation_start,
                    draft_text, topic, product_name, affiliate_link, virality_score,
                    status, created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, TO_TIMESTAMP(%s),
                    %s, %s, %s, %s, %s,
                    'STAGED', NOW(), NOW()
                )
                RETURNING id;
            """, (
                story_id, slot_number, slot_time, deliberation_start or time.time(),
                draft_text, topic, product_name, affiliate_link, virality_score
            ))
            row = cur.fetchone()
            staging_id = row[0] if row else None
            conn.commit()

            # Also publish event to tri_party_bus
            if staging_id:
                publish_event(
                    sender="threads",
                    recipient="zura",
                    topic="deliberation",
                    action="DELIBERATION_REQUEST",
                    payload={
                        "staging_id": staging_id,
                        "slot_number": slot_number,
                        "slot_time": slot_time,
                        "topic": topic,
                        "product_name": product_name,
                        "draft_snippet": draft_text[:200]
                    },
                    telegram_broadcast=True
                )
            return staging_id
    except Exception as e:
        logger.error(f"Error staging threads post: {e}")
        return None
    finally:
        conn.close()


def submit_deliberation_verdict(
    staging_id: int,
    verdict: str,
    zura_feedback: str,
    final_approved_text: str,
    human_check_passed: bool = True,
    warganet_score: float = 0.0
) -> bool:
    """Zura submits review verdict (APPROVED / REVISE / REJECTED) to Supabase."""
    conn = get_pg_connection()
    if not conn:
        return False
    try:
        new_status = "APPROVED" if verdict == "APPROVED" else ("REVISING" if verdict == "REVISE" else "REJECTED")
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE threads_staging
                SET zura_verdict = %s,
                    zura_feedback = %s,
                    final_approved_text = %s,
                    human_check_passed = %s,
                    warganet_score = %s,
                    status = %s,
                    updated_at = NOW()
                WHERE id = %s;
            """, (verdict, zura_feedback, final_approved_text, human_check_passed, warganet_score, new_status, staging_id))
            conn.commit()

            # Publish approval event back to threads
            publish_event(
                sender="zura",
                recipient="threads",
                topic="deliberation",
                action=f"VERDICT_{verdict}",
                payload={
                    "staging_id": staging_id,
                    "verdict": verdict,
                    "status": new_status,
                    "warganet_score": warganet_score
                },
                telegram_broadcast=True
            )
            return True
    except Exception as e:
        logger.error(f"Error submitting deliberation verdict: {e}")
        return False
    finally:
        conn.close()


def get_latest_threads_staging(limit: int = 5) -> List[Dict[str, Any]]:
    """Retrieves recent staged posts from Supabase."""
    conn = get_pg_connection()
    if not conn:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, story_id, slot_number, slot_time, topic, product_name,
                       virality_score, warganet_score, human_check_passed,
                       zura_verdict, status, views, likes, replies, created_at
                FROM threads_staging
                ORDER BY id DESC
                LIMIT %s;
            """, (limit,))
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error getting threads staging: {e}")
        return []
    finally:
        conn.close()


# =====================================================================
# 4. KIBOT PORTFOLIO & VOLATILITY DCA
# =====================================================================

def record_kibot_execution(
    pair: str,
    action: str,
    amount_idr: float,
    price_idr: float,
    crypto_units: float,
    volatility_factor: float = 1.0,
    fear_greed_score: Optional[int] = None,
    total_equity_idr: Optional[float] = None,
    cash_idr: Optional[float] = None,
    allocations: Optional[Dict[str, Any]] = None,
    tx_hash_or_id: Optional[str] = None
) -> Optional[int]:
    """Records an Indodax trade execution or portfolio snapshot to Supabase."""
    conn = get_pg_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO kibot_portfolio_ledger (
                    pair, action, amount_idr, price_idr, crypto_units,
                    volatility_factor, fear_greed_score, total_equity_idr,
                    cash_idr, allocations, execution_status, tx_hash_or_id,
                    timestamp, created_at
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, 'COMPLETED', %s,
                    NOW(), NOW()
                )
                RETURNING id;
            """, (
                pair, action, amount_idr, price_idr, crypto_units,
                volatility_factor, fear_greed_score, total_equity_idr,
                cash_idr, json.dumps(allocations or {}), tx_hash_or_id
            ))
            row = cur.fetchone()
            trade_id = row[0] if row else None
            conn.commit()

            # Broadcast event to tri_party_bus
            if trade_id:
                publish_event(
                    sender="kibot",
                    recipient="zura",
                    topic="trade",
                    action=action,
                    payload={
                        "trade_id": trade_id,
                        "pair": pair,
                        "amount_idr": amount_idr,
                        "price_idr": price_idr,
                        "volatility_factor": volatility_factor,
                        "fear_greed_score": fear_greed_score,
                        "total_equity_idr": total_equity_idr,
                        "cash_idr": cash_idr
                    },
                    telegram_broadcast=True
                )
            return trade_id
    except Exception as e:
        logger.error(f"Error recording KiBot execution: {e}")
        return None
    finally:
        conn.close()


def get_latest_kibot_portfolio() -> Optional[Dict[str, Any]]:
    """Gets the most recent portfolio snapshot from KiBot ledger."""
    conn = get_pg_connection()
    if not conn:
        return None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, timestamp, pair, action, amount_idr, price_idr,
                       crypto_units, volatility_factor, fear_greed_score,
                       total_equity_idr, cash_idr, allocations, execution_status
                FROM kibot_portfolio_ledger
                ORDER BY id DESC
                LIMIT 1;
            """)
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error fetching latest KiBot portfolio: {e}")
        return None
    finally:
        conn.close()


# =====================================================================
# 5. CAPITAL FLYWHEEL & EXECUTIVE DECISIONS
# =====================================================================

def record_capital_flywheel(source: str, destination: str, amount_idr: float, rationale: str) -> bool:
    """Logs capital reinvestment transaction in Supabase."""
    conn = get_pg_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO capital_flywheel_ledger (source, destination, amount_idr, rationale, status, created_at)
                VALUES (%s, %s, %s, %s, 'COMMITTED', NOW());
            """, (source, destination, amount_idr, rationale))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error recording capital flywheel: {e}")
        return False
    finally:
        conn.close()


def record_executive_decision(domain: str, trigger_event: str, decision_taken: str, outcome: str, telegram_broadcast: bool = False) -> bool:
    """Logs COO executive decision to Supabase."""
    conn = get_pg_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO executive_decisions (domain, trigger_event, decision_taken, outcome, telegram_broadcast, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW());
            """, (domain, trigger_event, decision_taken, outcome, telegram_broadcast))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error recording executive decision: {e}")
        return False
    finally:
        conn.close()


def set_shared_user_profile(category: str, key: str, value: str, confidence: float = 1.0) -> bool:
    """Updates user profile or preferences in Supabase shared profile."""
    conn = get_pg_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO shared_user_profile (category, key, value, confidence, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    category = EXCLUDED.category,
                    value = EXCLUDED.value,
                    confidence = EXCLUDED.confidence,
                    updated_at = NOW();
            """, (category, key, value, confidence))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error setting shared user profile in Supabase: {e}")
        return False
    finally:
        conn.close()


# =====================================================================
# 6. KIBOT DIRECT SYNC ENGINE (SQLITE -> SUPABASE)
# =====================================================================

def sync_kibot_to_supabase(kibot_db_path: Optional[Any] = None) -> Dict[str, Any]:
    """
    Ingests live portfolio snapshots, transactions, and positions from kibot_v3.db
    and synchronizes them into Supabase Cloud PostgreSQL.
    Non-blocking, fail-safe fallback.
    """
    import sqlite3
    from pathlib import Path

    candidate_paths = [
        Path(kibot_db_path) if kibot_db_path else None,
        Path("/home/ubuntu/KiBotV3/kibot_v3.db"),
        Path.home() / "Documents/Web Develop/KiBot/kibot_v3.db",
        Path(__file__).resolve().parent.parent / "data/kibot_v3.db"
    ]

    target_db = None
    for p in candidate_paths:
        if p and p.exists():
            target_db = p
            break

    if not target_db:
        return {"success": False, "reason": "KIBOT_DB_NOT_FOUND"}

    conn_pg = get_pg_connection()
    if not conn_pg:
        return {"success": False, "reason": "SUPABASE_CONNECTION_UNAVAILABLE"}

    synced_snaps = 0
    synced_txs = 0
    synced_pos = 0

    try:
        # Read from SQLite
        conn_lite = sqlite3.connect(str(target_db), timeout=5)
        conn_lite.row_factory = sqlite3.Row
        cur_lite = conn_lite.cursor()

        # 1. Snapshots
        cur_lite.execute("""
            SELECT id, total_equity_idr, cash_idr, allocations_json, regime_phase, is_paper, timestamp
            FROM portfolio_snapshots
            ORDER BY timestamp DESC
            LIMIT 50;
        """)
        snapshots = cur_lite.fetchall()

        # 2. Transactions
        cur_lite.execute("""
            SELECT id, order_id, pair, side, order_type, price, amount, fee, fee_asset, is_paper, timestamp
            FROM transactions
            ORDER BY timestamp DESC
            LIMIT 50;
        """)
        transactions = cur_lite.fetchall()

        # 3. Positions
        cur_lite.execute("""
            SELECT asset, amount, cost_basis_idr, total_invested_idr, updated_at
            FROM positions;
        """)
        positions = cur_lite.fetchall()

        conn_lite.close()

        # Write to Supabase PG
        with conn_pg.cursor() as cur_pg:
            # Upsert snapshots
            for s in snapshots:
                alloc_json = s["allocations_json"] if s["allocations_json"] else "{}"
                if isinstance(alloc_json, str):
                    try:
                        json.loads(alloc_json)
                    except Exception:
                        alloc_json = "{}"
                cur_pg.execute("""
                    INSERT INTO kibot_snapshots (id, total_equity_idr, cash_idr, allocations_json, regime_phase, is_paper, timestamp, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        total_equity_idr = EXCLUDED.total_equity_idr,
                        cash_idr = EXCLUDED.cash_idr,
                        allocations_json = EXCLUDED.allocations_json,
                        regime_phase = EXCLUDED.regime_phase;
                """, (
                    s["id"], s["total_equity_idr"], s["cash_idr"], alloc_json,
                    s["regime_phase"], s["is_paper"], s["timestamp"]
                ))
                synced_snaps += 1

            # Upsert transactions
            for t in transactions:
                cur_pg.execute("""
                    INSERT INTO kibot_transactions (id, order_id, pair, side, order_type, price, amount, fee, fee_asset, is_paper, timestamp, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (id) DO NOTHING;
                """, (
                    t["id"], t["order_id"], t["pair"], t["side"], t["order_type"],
                    t["price"], t["amount"], t["fee"], t["fee_asset"], t["is_paper"], t["timestamp"]
                ))
                synced_txs += 1

            # Upsert positions
            for pos in positions:
                cur_pg.execute("""
                    INSERT INTO kibot_positions (asset, amount, cost_basis_idr, total_invested_idr, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (asset) DO UPDATE SET
                        amount = EXCLUDED.amount,
                        cost_basis_idr = EXCLUDED.cost_basis_idr,
                        total_invested_idr = EXCLUDED.total_invested_idr,
                        updated_at = EXCLUDED.updated_at;
                """, (
                    pos["asset"], pos["amount"], pos["cost_basis_idr"], pos["total_invested_idr"], pos["updated_at"]
                ))
                synced_pos += 1

            # Update KiBot heartbeat in fleet_telemetry
            latest_snap = snapshots[0] if snapshots else None
            metrics = {
                "total_equity_idr": float(latest_snap["total_equity_idr"]) if latest_snap else 0.0,
                "cash_idr": float(latest_snap["cash_idr"]) if latest_snap else 0.0,
                "regime": latest_snap["regime_phase"] if latest_snap else "ACCUMULATE_70_30",
                "total_tx_count": len(transactions),
                "synced_at": datetime.now().isoformat()
            } if latest_snap else {}

            cur_pg.execute("""
                INSERT INTO fleet_telemetry (bot_id, bot_name, role, status, last_heartbeat, host, metrics, updated_at)
                VALUES ('kibot', 'KiBot V3 Indodax Trader', 'ASSET_GROWTH', 'ONLINE', NOW(), 'SG1 Cloud', %s, NOW())
                ON CONFLICT (bot_id) DO UPDATE SET
                    last_heartbeat = NOW(),
                    metrics = EXCLUDED.metrics,
                    status = 'ONLINE',
                    updated_at = NOW();
            """, (json.dumps(metrics),))

            conn_pg.commit()

        return {
            "success": True,
            "snapshots_synced": synced_snaps,
            "transactions_synced": synced_txs,
            "positions_synced": synced_pos,
            "db_path": str(target_db)
        }

    except Exception as e:
        logger.error(f"Error syncing KiBot to Supabase: {e}")
        return {"success": False, "error": str(e)}
    finally:
        conn_pg.close()

