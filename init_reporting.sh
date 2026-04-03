#!/bin/bash
# init_reporting.sh — Initialize full OpenClaw Pipeline structure
# Agent: Elkin 🔱

set -e

echo "🔱 Elkin — Initializing pipeline structure..."

# Verify schema exists
if [ ! -f reports/sqlite/schema.sql ]; then
 echo "❌ reports/sqlite/schema.sql not found — aborting"
 exit 1
fi

# Create all directories
mkdir -p reports/sqlite
mkdir -p reports/json
mkdir -p reports/csv
mkdir -p reports/html
mkdir -p reports/markdown
mkdir -p reports/screenshots
mkdir -p .openclaw/logs
mkdir -p .openclaw/github-discovery
mkdir -p memory/entities
mkdir -p memory/daily-logs
mkdir -p memory/methodologies

# Initialize SQLite databases
sqlite3 reports/sqlite/engagement.db < reports/sqlite/schema.sql
echo "✅ engagement.db initialized"

sqlite3 reports/sqlite/capabilities.db < reports/sqlite/schema.sql
echo "✅ capabilities.db initialized"

# Initialize empty capability registry if not exists
if [ ! -f .openclaw/capability_registry.json ]; then
 cat > .openclaw/capability_registry.json << 'REGISTRY'
{
 "capabilities": {},
 "pattern_index": {},
 "last_updated": null,
 "version": "2.0"
}
REGISTRY
 echo "✅ capability_registry.json initialized"
fi

# Verify .env exists
if [ ! -f .env ]; then
 echo "⚠️ .env not found — copy .env.example to .env and populate"
fi

echo ""
echo "✅ Directory structure created"
echo "✅ Databases initialized"
echo "✅ OpenClaw Pipeline ready"
echo ""
echo "Next steps:"
echo " 1. cp .env.example .env && populate with real values"
echo " 2. pip install -r requirements.txt"
echo " 3. playwright install chromium"
echo " 4. python capability_harvester.py"
echo " 5. python master_pipeline.py -t <target> --config engagement_config.json"
