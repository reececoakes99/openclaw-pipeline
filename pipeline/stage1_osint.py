#!/usr/bin/env python3
"""
pipeline/stage1_osint.py
OpenClaw Pipeline — Stage 1: OSINT & Reconnaissance
Agent: Elkin 🔱 | Version: 2.0
"""

import os
import json
import logging
import sqlite3
import requests
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("stage1_osint")
DB_PATH = Path("reports/sqlite/engagement.db")


def _db_insert(engagement: str, dtype: str,
 value: str, tool: str, confidence: float = 0.8):
 try:
 conn = sqlite3.connect(DB_PATH)
 c = conn.cursor()
 c.execute("""
 INSERT INTO discoveries
 (engagement_name, stage, type, value, confidence, source_tool)
 VALUES (?, ?, ?, ?, ?, ?)
 """, (engagement, "OSINT", dtype, value, confidence, tool))
 conn.commit()
 conn.close()
 except Exception as e:
 log.error(f"DB insert failed: {e}")


def _run_tool(cmd: list, timeout: int = 60) -> str:
 """Run external tool, return stdout. Fails gracefully."""
 try:
 result = subprocess.run(
 cmd,
 capture_output=True,
 text=True,
 timeout=timeout
 )
 return result.stdout
 except FileNotFoundError:
 log.warning(f"Tool not found: {cmd[0]}")
 return ""
 except subprocess.TimeoutExpired:
 log.warning(f"Tool timed out: {cmd[0]}")
 return ""
 except Exception as e:
 log.error(f"Tool error {cmd[0]}: {e}")
 return ""


def _theHarvester(target: str, engagement: str) -> dict:
 """Email, subdomain, host harvesting via theHarvester."""
 log.info(f"theHarvester — {target}")
 findings = {"emails": [], "hosts": []}

 output = _run_tool([
 "theHarvester", "-d", target, "-b", "all",
 "-l", "200", "-f", f"/tmp/theharvester_{target}"
 ], timeout=120)

 if output:
 for line in output.splitlines():
 line = line.strip()
 if "@" in line and "." in line:
 findings["emails"].append(line)
 _db_insert(engagement, "email", line, "theHarvester")
 elif target in line and line not in findings["hosts"]:
 findings["hosts"].append(line)
 _db_insert(engagement, "host", line, "theHarvester")

 log.info(
 f"theHarvester found {len(findings['emails'])} emails, "
 f"{len(findings['hosts'])} hosts"
 )
 return findings


def _subfinder(target: str, engagement: str) -> list:
 """Passive subdomain discovery via subfinder."""
 log.info(f"subfinder — {target}")
 subdomains = []

 output = _run_tool(["subfinder", "-d", target, "-silent"], timeout=120)
 for line in output.splitlines():
 line = line.strip()
 if line and target in line:
 subdomains.append(line)
 _db_insert(engagement, "subdomain", line, "subfinder")

 log.info(f"subfinder found {len(subdomains)} subdomains")
 return subdomains


def _amass_passive(target: str, engagement: str) -> list:
 """Passive enumeration via amass."""
 log.info(f"amass passive — {target}")
 subdomains = []

 output = _run_tool([
 "amass", "enum", "-passive", "-d", target, "-timeout", "5"
 ], timeout=360)

 for line in output.splitlines():
 line = line.strip()
 if line and target in line:
 subdomains.append(line)
 _db_insert(engagement, "subdomain", line, "amass")

 log.info(f"amass found {len(subdomains)} subdomains")
 return subdomains


def _shodan_lookup(target: str, engagement: str) -> dict:
 """Shodan host lookup via API."""
 api_key = os.getenv("SHODAN_API_KEY", "")
 if not api_key:
 log.warning("SHODAN_API_KEY not set — skipping")
 return {}

 log.info(f"Shodan lookup — {target}")
 findings = {}

 try:
 resp = requests.get(
 f"https://api.shodan.io/shodan/host/search",
 params={"key": api_key, "query": f"hostname:{target}"},
 timeout=15
 )
 if resp.status_code == 200:
 data = resp.json()
 for match in data.get("matches", []):
 ip = match.get("ip_str", "")
 port = match.get("port", "")
 if ip:
 findings[ip] = {"port": port, "data": match.get("data", "")}
 _db_insert(
 engagement, "ip_port",
 f"{ip}:{port}", "shodan"
 )
 except Exception as e:
 log.error(f"Shodan error: {e}")

 log.info(f"Shodan found {len(findings)} hosts")
 return findings


def run(target: str, config: dict) -> dict:
 """
 Stage 1 entry point.
 Returns structured OSINT findings dict.
 """
 log.info(f"{'='*60}")
 log.info(f"Stage 1 — OSINT & Reconnaissance")
 log.info(f"Target: {target}")

 engagement = config.get("engagement_name", "default")

 # Verify target is in authorized scope
 authorized = config.get("authorized_domains", [])
 if target not in authorized:
 raise ValueError(
 f"Target {target} not in authorized_domains — aborting"
 )

 findings = {
 "stage": 1,
 "name": "OSINT",
 "target": target,
 "timestamp": datetime.utcnow().isoformat(),
 "tools_invoked": [],
 "emails_found": [],
 "subdomains_found": [],
 "hosts_found": [],
 "ip_ports_found": {}
 }

 # theHarvester
 harvester_results = _theHarvester(target, engagement)
 findings["emails_found"].extend(harvester_results["emails"])
 findings["hosts_found"].extend(harvester_results["hosts"])
 findings["tools_invoked"].append("theHarvester")

 # subfinder
 subdomains = _subfinder(target, engagement)
 findings["subdomains_found"].extend(subdomains)
 findings["tools_invoked"].append("subfinder")

 # amass passive
 amass_subs = _amass_passive(target, engagement)
 for s in amass_subs:
 if s not in findings["subdomains_found"]:
 findings["subdomains_found"].append(s)
 findings["tools_invoked"].append("amass")

 # Shodan
 shodan_results = _shodan_lookup(target, engagement)
 findings["ip_ports_found"].update(shodan_results)
 findings["tools_invoked"].append("shodan")

 # Deduplicate
 findings["subdomains_found"] = list(set(findings["subdomains_found"]))
 findings["emails_found"] = list(set(findings["emails_found"]))
 findings["hosts_found"] = list(set(findings["hosts_found"]))

 log.info(
 f"Stage 1 complete — "
 f"{len(findings['subdomains_found'])} subdomains, "
 f"{len(findings['emails_found'])} emails, "
 f"{len(findings['hosts_found'])} hosts"
 )

 return findings
