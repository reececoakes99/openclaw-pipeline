#!/usr/bin/env python3
"""
master_pipeline.py
OpenClaw Pipeline — Master Orchestrator
Agent: Elkin 🔱 | Version: 2.0
"""

import os
import sys
import json
import time
import sqlite3
import logging
import argparse
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8069069638")
DB_PATH = Path("reports/sqlite/engagement.db")
LOG_PATH = Path(".openclaw/logs/pipeline.log")
REPORTS_DIR = Path("reports")

# ============================================================
# LOGGING
# ============================================================

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
 level=logging.INFO,
 format="%(asctime)s [%(levelname)s] %(message)s",
 handlers=[
 logging.FileHandler(LOG_PATH),
 logging.StreamHandler()
 ]
)
log = logging.getLogger("master_pipeline")

# ============================================================
# TELEGRAM
# ============================================================

def notify(message: str):
 if not TELEGRAM_BOT_TOKEN:
 log.warning("TELEGRAM_BOT_TOKEN not set — skipping notification")
 return
 try:
 requests.post(
 f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
 json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
 timeout=10
 )
 except Exception as e:
 log.error(f"Telegram notify failed: {e}")

# ============================================================
# PREFLIGHT CHECKS
# ============================================================

def preflight(config: dict) -> bool:
 """Verify all prerequisites before pipeline run."""
 log.info("Running preflight checks...")
 passed = True

 # Authorized domains populated
 if not config.get("authorized_domains"):
 log.error("PREFLIGHT FAIL: authorized_domains is empty")
 passed = False

 # Engagement name set
 if config.get("engagement_name") == "default":
 log.warning("PREFLIGHT WARN: engagement_name is still 'default'")

 # Capability registry accessible
 registry_path = Path(".openclaw/capability_registry.json")
 if not registry_path.exists():
 log.warning("PREFLIGHT WARN: capability_registry.json not found")

 # Reports directory exists
 if not Path("reports/sqlite").exists():
 log.error("PREFLIGHT FAIL: reports/sqlite/ not found — run init_reporting.sh")
 passed = False

 # GitHub PAT set if harvester enabled
 if not os.getenv("GITHUB_PAT"):
 log.warning("PREFLIGHT WARN: GITHUB_PAT not set — harvester will fail")

 # Telegram configured
 if not TELEGRAM_BOT_TOKEN:
 log.warning("PREFLIGHT WARN: TELEGRAM_BOT_TOKEN not set")

 if passed:
 log.info("✅ Preflight checks passed")
 else:
 log.error("❌ Preflight checks failed — aborting")

 return passed

# ============================================================
# DATABASE
# ============================================================

def log_stage(engagement: str, stage: str,
 tool: str, status: str, output_file: str = ""):
 conn = sqlite3.connect(DB_PATH)
 c = conn.cursor()
 c.execute("""
 INSERT INTO reports
 (engagement_name, stage, tool_used, output_file, status)
 VALUES (?, ?, ?, ?, ?)
 """, (engagement, stage, tool, output_file, status))
 conn.commit()
 conn.close()

# ============================================================
# STAGE RUNNER
# ============================================================

def run_stage(stage_num: int, stage_name: str,
 target: str, config: dict) -> dict:
 """
 Execute a single pipeline stage.
 Returns stage result dict.
 """
 log.info(f"\n{'='*60}")
 log.info(f"STAGE {stage_num} — {stage_name}")
 log.info(f"Target: {target}")

 start_time = time.time()

 result = {
 "stage": stage_num,
 "name": stage_name,
 "target": target,
 "status": "pending",
 "duration_seconds": 0,
 "findings": {}
 }

 try:
 # Dynamic stage module import
 module_map = {
 1: ("pipeline.stage1_osint", "run"),
 2: ("pipeline.stage2_asset_discovery", "run"),
 3: ("pipeline.stage3_crawling", "run"),
 4: ("pipeline.stage4_dynamic_rendering", "run"),
 5: ("pipeline.stage5_extraction", "run"),
 6: ("pipeline.stage6_evasion", "run"),
 7: ("pipeline.stage7_distributed", "run"),
 8: ("pipeline.stage8_darkweb", "run"),
 9: ("pipeline.stage9_ai_enrichment", "run"),
 10: ("pipeline.stage10_output", "run"),
 }

 if stage_num not in module_map:
 raise ValueError(f"Unknown stage: {stage_num}")

 module_path, func_name = module_map[stage_num]

 import importlib
 module = importlib.import_module(module_path)
 stage_func = getattr(module, func_name)

 findings = stage_func(target=target, config=config)
 result["findings"] = findings
 result["status"] = "complete"

 log_stage(
 config["engagement_name"],
 stage_name,
 "pipeline",
 "complete"
 )

 duration = round(time.time() - start_time, 2)
 result["duration_seconds"] = duration

 notify(
 f"✅ [PIPELINE] Stage {stage_num} complete — {stage_name}\n"
 f"Target: {target} | Duration: {duration}s"
 )

 except Exception as e:
 result["status"] = "failed"
 result["error"] = str(e)
 log.error(f"Stage {stage_num} failed: {e}")

 log_stage(
 config["engagement_name"],
 stage_name,
 "pipeline",
 "failed"
 )

 notify(
 f"⚠️ [PIPELINE] Stage {stage_num} failed — {stage_name}\n"
 f"Error: {str(e)}"
 )

 return result

# ============================================================
# MEMORY INTEGRATION
# ============================================================

def write_memory(target: str, results: list, config: dict):
 """Write pipeline results back to openclaw-brain memory."""
 brain_workspace = Path(os.getenv(
 "BRAIN_WORKSPACE",
 "/root/.openclaw/workspace"
 ))

 entity_dir = brain_workspace / "memory" / "entities" / target
 entity_dir.mkdir(parents=True, exist_ok=True)

 recon_dir = entity_dir / "recon_data"
 recon_dir.mkdir(exist_ok=True)

 date_str = datetime.utcnow().strftime("%Y-%m-%d")

 # Write engagement summary to daily log
 daily_log = brain_workspace / "memory" / "daily-logs" / f"{date_str}.md"
 with open(daily_log, "a") as f:
 f.write(f"\n## Pipeline Run — {target} — {datetime.utcnow().isoformat()}\n\n")
 for r in results:
 f.write(
 f"- Stage {r['stage']} ({r['name']}): "
 f"{r['status']} — {r.get('duration_seconds', 0)}s\n"
 )

 log.info(f"Memory written to {daily_log}")

# ============================================================
# MAIN ORCHESTRATOR
# ============================================================

class Pipeline:
 def __init__(self, target: str, config_path: str):
 self.target = target
 with open(config_path, "r") as f:
 self.config = json.load(f)
 self.results = []

 # Inject target into config
 self.config["target"] = target

 # Create engagement-specific output dirs
 date_str = datetime.utcnow().strftime("%Y-%m-%d")
 self.run_id = f"{self.config['engagement_name']}_{date_str}"
 for subdir in ["json", "csv", "html", "markdown", "screenshots"]:
 Path(f"reports/{subdir}/{self.run_id}").mkdir(
 parents=True, exist_ok=True
 )

 def run(self):
 log.info(f"🔱 Elkin Pipeline v2.0 — Starting")
 log.info(f"Target: {self.target}")
 log.info(f"Engagement: {self.config['engagement_name']}")

 notify(
 f"🔄 [PIPELINE] Starting engagement\n"
 f"Target: {self.target}\n"
 f"Engagement: {self.config['engagement_name']}"
 )

 # Preflight
 if not preflight(self.config):
 notify("🚨 [PIPELINE] Preflight failed — aborting")
 sys.exit(1)

 stages = self.config.get("stages", {})

 stage_map = {
 1: ("OSINT_RECON", stages.get("osint_recon", True)),
 2: ("ASSET_DISCOVERY", stages.get("asset_discovery", True)),
 3: ("CRAWLING", stages.get("crawl_scrape", True)),
 4: ("DYNAMIC_RENDERING", stages.get("dynamic_render", True)),
 5: ("EXTRACTION", stages.get("data_extraction", True)),
 6: ("EVASION", stages.get("anti_detection", False)),
 7: ("DISTRIBUTED", stages.get("distributed_scaling", False)),
 8: ("DARK_WEB", stages.get("dark_web", False)),
 9: ("AI_ENRICHMENT", stages.get("ai_enrichment", True)),
 10: ("OUTPUT", stages.get("output", True)),
 }

 for stage_num, (stage_name, enabled) in stage_map.items():
 if not enabled:
 log.info(f"Stage {stage_num} ({stage_name}) — disabled, skipping")
 continue

 result = run_stage(stage_num, stage_name, self.target, self.config)
 self.results.append(result)

 # Abort on critical stage failure
 if result["status"] == "failed" and stage_num <= 5:
 log.error(
 f"Critical stage {stage_num} failed — aborting pipeline"
 )
 notify(
 f"🚨 [PIPELINE] Critical stage {stage_num} failed\n"
 f"Pipeline aborted for {self.target}"
 )
 break

 # Write results back to brain memory
 write_memory(self.target, self.results, self.config)

 completed = sum(1 for r in self.results if r["status"] == "complete")
 failed = sum(1 for r in self.results if r["status"] == "failed")

 final_summary = (
 f"\n{'='*60}\n"
 f"🔱 Pipeline Complete\n"
 f"Target: {self.target}\n"
 f"Stages completed: {completed}\n"
 f"Stages failed: {failed}\n"
 f"Run ID: {self.run_id}\n"
 f"{'='*60}"
 )
 log.info(final_summary)

 notify(
 f"✅ [PIPELINE] Engagement complete\n"
 f"Target: {self.target}\n"
 f"Stages: {completed} complete, {failed} failed\n"
 f"Reports: reports/*/{self.run_id}/"
 )

 return self.results


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
 parser = argparse.ArgumentParser(
 description="OpenClaw Pipeline — Elkin 🔱"
 )
 parser.add_argument(
 "-t", "--target",
 required=True,
 help="Target domain (must be in engagement_config.json authorized_domains)"
 )
 parser.add_argument(
 "--config",
 default="engagement_config.json",
 help="Path to engagement config file"
 )
 args = parser.parse_args()

 pipeline = Pipeline(target=args.target, config_path=args.config)
 pipeline.run()
