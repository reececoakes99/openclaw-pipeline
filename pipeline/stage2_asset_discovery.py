#!/usr/bin/env python3
"""
pipeline/stage2_asset_discovery.py
OpenClaw Pipeline — Stage 2: Asset Discovery & Enumeration
Agent: Elkin 🔱 | Version: 2.0
"""

import json
import logging
import sqlite3
import subprocess
import requests
from pathlib import Path
from datetime import datetime

log = logging.getLogger("stage2_asset_discovery")
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
 """, (engagement, "ASSET_DISCOVERY", dtype, value, confidence, tool))
 conn.commit()
 conn.close()
 except Exception as e:
 log.error(f"DB insert failed: {e}")


def _run_tool(cmd: list, timeout: int = 120) -> str:
 try:
 result = subprocess.run(
 cmd, capture_output=True, text=True, timeout=timeout
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


def _whatweb(target: str, engagement: str) -> dict:
 """Technology fingerprinting via whatweb."""
 log.info(f"whatweb — {target}")
 tech = {}

 output = _run_tool([
 "whatweb", f"https://{target}", "--log-json=/tmp/whatweb.json"
 ])

 try:
 with open("/tmp/whatweb.json", "r") as f:
 data = json.load(f)
 for entry in data:
 plugins = entry.get("plugins", {})
 for name, details in plugins.items():
 tech[name] = details
 _db_insert(engagement, "technology", name, "whatweb")
 except Exception:
 pass

 log.info(f"whatweb detected {len(tech)} technologies")
 return tech


def _httpx_probe(subdomains: list, engagement: str) -> list:
 """Probe subdomains for live HTTP hosts via httpx."""
 log.info(f"httpx probing {len(subdomains)} subdomains")
 live_hosts = []

 if not subdomains:
 return live_hosts

 # Write subdomain list to temp file
 tmp_input = Path("/tmp/subdomains.txt")
 tmp_input.write_text("\n".join(subdomains))

 output = _run_tool([
 "httpx", "-l", str(tmp_input),
 "-silent", "-status-code", "-title",
 "-tech-detect", "-no-color"
 ], timeout=180)

 for line in output.splitlines():
 line = line.strip()
 if line:
 live_hosts.append(line)
 host = line.split()[0] if line.split() else line
 _db_insert(engagement, "live_host", host, "httpx")

 log.info(f"httpx found {len(live_hosts)} live hosts")
 return live_hosts


def _nmap_quick(target: str, engagement: str) -> dict:
 """Quick port scan via nmap — top 1000 ports."""
 log.info(f"nmap quick scan — {target}")
 open_ports = {}

 output = _run_tool([
 "nmap", "-T4", "--top-ports", "1000",
 "-oG", "-", target
 ], timeout=300)

 for line in output.splitlines():
 if "Ports:" in line:
 parts = line.split("Ports:")
 if len(parts) > 1:
 ports_str = parts[1].strip()
 for port_entry in ports_str.split(","):
 port_entry = port_entry.strip()
 if "/open/" in port_entry:
 port_num = port_entry.split("/")[0].strip()
 service = port_entry.split("/")[4] \
 if len(port_entry.split("/")) > 4 else "unknown"
 open_ports[port_num] = service
 _db_insert(
 engagement, "open_port",
 f"{target}:{port_num}/{service}", "nmap"
 )

 log.info(f"nmap found {len(open_ports)} open ports")
 return open_ports


def _certificate_transparency(target: str, engagement: str) -> list:
 """Certificate transparency log search via crt.sh."""
 log.info(f"Certificate transparency — {target}")
 subdomains = []

 try:
 resp = requests.get(
 f"https://crt.sh/?q=%.{target}&output=json",
 timeout=15
 )
 if resp.status_code == 200:
 data = resp.json()
 for entry in data:
 name = entry.get("name_value", "")
 for sub in name.split("\n"):
 sub = sub.strip().lstrip("*.")
 if sub and target in sub and sub not in subdomains:
 subdomains.append(sub)
 _db_insert(engagement, "subdomain", sub, "crt.sh")
 except Exception as e:
 log.error(f"crt.sh error: {e}")

 log.info(f"crt.sh found {len(subdomains)} subdomains")
 return subdomains


def run(target: str, config: dict) -> dict:
 """Stage 2 entry point."""
 log.info(f"{'='*60}")
 log.info(f"Stage 2 — Asset Discovery & Enumeration")
 log.info(f"Target: {target}")

 engagement = config.get("engagement_name", "default")
 stage1_subs = config.get("stage1_findings", {}).get("subdomains_found", [])

 findings = {
 "stage": 2,
 "name": "ASSET_DISCOVERY",
 "target": target,
 "timestamp": datetime.utcnow().isoformat(),
 "tools_invoked": [],
 "live_hosts": [],
 "tech_stack": {},
 "open_ports": {},
 "subdomains": []
 }

 # Certificate transparency
 ct_subs = _certificate_transparency(target, engagement)
 findings["subdomains"].extend(ct_subs)
 findings["tools_invoked"].append("crt.sh")

 # Combine with stage 1 subdomains
 all_subs = list(set(stage1_subs + ct_subs))

 # httpx probe
 live = _httpx_probe(all_subs, engagement)
 findings["live_hosts"].extend(live)
 findings["tools_invoked"].append("httpx")

 # whatweb fingerprint
 tech = _whatweb(target, engagement)
 findings["tech_stack"].update(tech)
 findings["tools_invoked"].append("whatweb")

 # nmap quick scan
 ports = _nmap_quick(target, engagement)
 findings["open_ports"].update(ports)
 findings["tools_invoked"].append("nmap")

 log.info(
 f"Stage 2 complete — "
 f"{len(findings['live_hosts'])} live hosts, "
 f"{len(findings['open_ports'])} open ports, "
 f"{len(findings['tech_stack'])} technologies"
 )

 return findings
