#!/usr/bin/env python3
"""
pipeline/stage8_darkweb.py
OpenClaw Pipeline — Stage 8: Dark Web & Breach Intelligence
Agent: Elkin 🔱 | Version: 2.0

Scope: Authorized defensive intelligence gathering only.
- Breach monitoring for operator's authorized domains
- Paste site monitoring for credential leaks
- Threat actor mention tracking for targets
"""

import os
import logging
import sqlite3
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("stage8_darkweb")
DB_PATH = Path("reports/sqlite/engagement.db")


def _db_insert(engagement: str, dtype: str,
 value: str, tool: str, confidence: float = 0.7):
 try:
 conn = sqlite3.connect(DB_PATH)
 c = conn.cursor()
 c.execute("""
 INSERT INTO discoveries
 (engagement_name, stage, type, value, confidence, source_tool)
 VALUES (?, ?, ?, ?, ?, ?)
 """, (engagement, "DARK_WEB", dtype, value, confidence, tool))
 conn.commit()
 conn.close()
 except Exception as e:
 log.error(f"DB insert failed: {e}")


def _hibp_check(domain: str, engagement: str) -> list:
 """
 Check HaveIBeenPwned for breaches affecting domain.
 Authorized defensive intelligence only.
 """
 api_key = os.getenv("HIBP_API_KEY", "")
 if not api_key:
 log.warning("HIBP_API_KEY not set — skipping breach check")
 return []

 log.info(f"HIBP domain breach check — {domain}")
 breaches = []

 try:
 resp = requests.get(
 f"https://haveibeenpwned.com/api/v3/breacheddomain/{domain}",
 headers={
 "hibp-api-key": api_key,
 "User-Agent": "OpenClaw-Elkin-RedTeam"
 },
 timeout=15
 )
 if resp.status_code == 200:
 data = resp.json()
 for email, breach_list in data.items():
 entry = f"{email}: {', '.join(breach_list)}"
 breaches.append(entry)
 _db_insert(engagement, "breach", entry, "hibp")
 log.info(f"HIBP found {len(breaches)} breached accounts")
 elif resp.status_code == 404:
 log.info("HIBP: no breaches found for domain")
 except Exception as e:
 log.error(f"HIBP error: {e}")

 return breaches


def _pastebin_search(domain: str, engagement: str) -> list:
 """Search for domain mentions in paste sites via Google dork."""
 log.info(f"Paste site search — {domain}")
 hits = []

 # Use Google Custom Search if key available
 api_key = os.getenv("GOOGLE_API_KEY", "")
 cx = os.getenv("GOOGLE_CX", "")

 if not api_key or not cx:
 log.warning("Google API key/CX not set — skipping paste search")
 return hits

 try:
 query = f'site:pastebin.com OR site:paste.ee OR site:ghostbin.com "{domain}"'
 resp = requests.get(
 "https://www.googleapis.com/customsearch/v1",
 params={"key": api_key, "cx": cx, "q": query},
 timeout=15
 )
 if resp.status_code == 200:
 items = resp.json().get("items", [])
 for item in items:
 link = item.get("link", "")
 hits.append(link)
 _db_insert(engagement, "paste_hit", link, "google_cse")
 log.info(f"Paste search found {len(hits)} hits")
 except Exception as e:
 log.error(f"Paste search error: {e}")

 return hits


def run(target: str, config: dict) -> dict:
 """
 Stage 8 entry point.
 Defensive intelligence gathering only — authorized domains.
 """
 log.info(f"{'='*60}")
 log.info(f"Stage 8 — Dark Web & Breach Intelligence")
 log.info(f"Target: {target}")
 log.info("Scope: Authorized defensive intelligence only")

 engagement = config.get("engagement_name", "default")
 authorized = config.get("authorized_domains", [])

 if target not in authorized:
 raise ValueError(
 f"Target {target} not in authorized_domains — aborting"
 )

 findings = {
 "stage": 8,
 "name": "DARK_WEB",
 "target": target,
 "timestamp": datetime.utcnow().isoformat(),
 "tools_invoked": [],
 "breaches_found": [],
 "paste_hits": [],
 "breach_count": 0
 }

 # HIBP breach check
 breaches = _hibp_check(target, engagement)
 findings["breaches_found"].extend(breaches)
 findings["breach_count"] = len(breaches)
 findings["tools_invoked"].append("hibp")

 # Paste site monitoring
 paste_hits = _pastebin_search(target, engagement)
 findings["paste_hits"].extend(paste_hits)
 findings["tools_invoked"].append("paste_monitor")

 log.info(
 f"Stage 8 complete — "
 f"{findings['breach_count']} breaches, "
 f"{len(findings['paste_hits'])} paste hits"
 )

 return findings
