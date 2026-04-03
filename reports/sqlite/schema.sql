-- OpenClaw Pipeline — SQLite Schema
-- Agent: Elkin 🔱 | Version: 2.0

-- Pipeline run tracking
CREATE TABLE IF NOT EXISTS reports (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 engagement_name TEXT NOT NULL,
 stage TEXT NOT NULL,
 tool_used TEXT,
 output_file TEXT,
 status TEXT,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- All discovered intelligence
CREATE TABLE IF NOT EXISTS discoveries (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 engagement_name TEXT NOT NULL,
 stage TEXT NOT NULL,
 type TEXT NOT NULL,
 value TEXT NOT NULL,
 confidence REAL,
 source_tool TEXT,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Capability registry entries
CREATE TABLE IF NOT EXISTS capabilities (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 repo_name TEXT NOT NULL,
 pattern TEXT NOT NULL,
 signature TEXT NOT NULL,
 first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
 times_seen INTEGER DEFAULT 1,
 UNIQUE(repo_name, pattern, signature)
);

-- Harvester run metadata
CREATE TABLE IF NOT EXISTS harvester_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 run_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 repos_scanned INTEGER DEFAULT 0,
 patterns_found INTEGER DEFAULT 0,
 new_capabilities INTEGER DEFAULT 0,
 status TEXT
);

-- Engagement assets
CREATE TABLE IF NOT EXISTS assets (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 engagement_name TEXT NOT NULL,
 type TEXT NOT NULL,
 value TEXT NOT NULL,
 source_stage TEXT,
 source_tool TEXT,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Secrets and credentials found
CREATE TABLE IF NOT EXISTS secrets (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 engagement_name TEXT NOT NULL,
 type TEXT NOT NULL,
 value_hash TEXT NOT NULL,
 source_url TEXT,
 source_tool TEXT,
 severity TEXT,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_engagement
 ON reports (engagement_name);
CREATE INDEX IF NOT EXISTS idx_discovery_type
 ON discoveries (type, engagement_name);
CREATE INDEX IF NOT EXISTS idx_capability_pattern
 ON capabilities (pattern);
CREATE INDEX IF NOT EXISTS idx_assets_engagement
 ON assets (engagement_name, type);
CREATE INDEX IF NOT EXISTS idx_secrets_engagement
 ON secrets (engagement_name, severity);
