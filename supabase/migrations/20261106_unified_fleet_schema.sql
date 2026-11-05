-- ====================================================================
-- SUPABASE UNIFIED FLEET SCHEMA FOR ZURA, THREADS, AND KIBOT
-- Target: Singapore AWS Pooler (PostgreSQL 17)
-- ====================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. FLEET TELEMETRY & HEARTBEATS
CREATE TABLE IF NOT EXISTS fleet_telemetry (
    id SERIAL PRIMARY KEY,
    bot_id VARCHAR(64) UNIQUE NOT NULL,
    bot_name VARCHAR(128) NOT NULL,
    role VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ONLINE',
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    host VARCHAR(128),
    ip_address VARCHAR(64),
    metrics JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fleet_telemetry_bot ON fleet_telemetry(bot_id);
CREATE INDEX IF NOT EXISTS idx_fleet_telemetry_status ON fleet_telemetry(status);

-- 2. TRI-PARTY HYBRID EVENT BUS
CREATE TABLE IF NOT EXISTS tri_party_bus (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID DEFAULT gen_random_uuid(),
    sender VARCHAR(64) NOT NULL,
    recipient VARCHAR(64) NOT NULL DEFAULT 'all',
    topic VARCHAR(64) NOT NULL,
    action VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    telegram_broadcast BOOLEAN DEFAULT FALSE,
    processed_by TEXT[] DEFAULT '{}',
    status VARCHAR(32) DEFAULT 'PENDING',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tri_bus_status ON tri_party_bus(status);
CREATE INDEX IF NOT EXISTS idx_tri_bus_topic ON tri_party_bus(topic);
CREATE INDEX IF NOT EXISTS idx_tri_bus_created ON tri_party_bus(created_at DESC);

-- 3. THREADS STAGING & DELIBERATION LEDGER
CREATE TABLE IF NOT EXISTS threads_staging (
    id SERIAL PRIMARY KEY,
    story_id INTEGER,
    slot_number INTEGER NOT NULL,
    slot_time VARCHAR(16) NOT NULL,
    deliberation_start TIMESTAMPTZ,
    scheduled_publish TIMESTAMPTZ,
    draft_text TEXT NOT NULL,
    topic VARCHAR(255),
    product_name VARCHAR(255),
    affiliate_link TEXT,
    virality_score NUMERIC(5,2) DEFAULT 0.0,
    warganet_score NUMERIC(5,2) DEFAULT 0.0,
    human_check_passed BOOLEAN DEFAULT FALSE,
    human_feedback TEXT,
    zura_verdict VARCHAR(32) DEFAULT 'PENDING',
    zura_feedback TEXT,
    final_approved_text TEXT,
    status VARCHAR(32) DEFAULT 'STAGED',
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    replies INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_threads_staging_status ON threads_staging(status);
CREATE INDEX IF NOT EXISTS idx_threads_staging_slot ON threads_staging(slot_number, slot_time);

-- 4. KIBOT PORTFOLIO & VOLATILITY DCA LEDGER
CREATE TABLE IF NOT EXISTS kibot_portfolio_ledger (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    pair VARCHAR(32) NOT NULL,
    action VARCHAR(32) NOT NULL,
    amount_idr NUMERIC(18,2) NOT NULL,
    price_idr NUMERIC(18,2) NOT NULL,
    crypto_units NUMERIC(18,8) NOT NULL,
    volatility_factor NUMERIC(5,2) DEFAULT 1.0,
    fear_greed_score INTEGER,
    total_equity_idr NUMERIC(18,2),
    cash_idr NUMERIC(18,2),
    allocations JSONB DEFAULT '{}'::jsonb,
    execution_status VARCHAR(32) DEFAULT 'COMPLETED',
    tx_hash_or_id VARCHAR(128),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kibot_ledger_pair ON kibot_portfolio_ledger(pair);
CREATE INDEX IF NOT EXISTS idx_kibot_ledger_ts ON kibot_portfolio_ledger(timestamp DESC);

-- 5. UNIFIED CAPITAL FLYWHEEL
CREATE TABLE IF NOT EXISTS capital_flywheel_ledger (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(64) NOT NULL,
    destination VARCHAR(64) NOT NULL,
    amount_idr NUMERIC(18,2) NOT NULL,
    rationale TEXT,
    status VARCHAR(32) DEFAULT 'COMMITTED',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. EXECUTIVE DECISIONS LEDGER (COO)
CREATE TABLE IF NOT EXISTS executive_decisions (
    id BIGSERIAL PRIMARY KEY,
    domain VARCHAR(64) NOT NULL,
    trigger_event TEXT NOT NULL,
    decision_taken TEXT NOT NULL,
    outcome TEXT,
    telegram_broadcast BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 7. SHARED USER PROFILE & PREFERENCES
CREATE TABLE IF NOT EXISTS shared_user_profile (
    id SERIAL PRIMARY KEY,
    category VARCHAR(64) NOT NULL,
    key VARCHAR(128) UNIQUE NOT NULL,
    value TEXT NOT NULL,
    confidence NUMERIC(3,2) DEFAULT 1.0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed initial fleet entries
INSERT INTO fleet_telemetry (bot_id, bot_name, role, status, host)
VALUES 
    ('zura', 'ZURA Autonomous Personal AI', 'COO_LEADER', 'ONLINE', 'SG1 / MacBook Pro'),
    ('threads', 'KisahKomisi Threads Bot', 'CONTENT_CREATOR', 'ONLINE', 'SG1 Cloud'),
    ('kibot', 'KiBot V3 Indodax Trader', 'ASSET_GROWTH', 'ONLINE', 'SG1 Cloud')
ON CONFLICT (bot_id) DO UPDATE SET 
    updated_at = NOW(),
    status = EXCLUDED.status;

