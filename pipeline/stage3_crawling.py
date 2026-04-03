#!/usr/bin/env python3
"""
pipeline/stage3_crawling.py
OpenClaw Pipeline — Stage 3: Crawling & Endpoint Discovery
Agent: Elkin 🔱 | Version: 2.0
"""

import logging
import sqlite3
import subprocess
import requests
from pathlib import Path
from datetime import datetime

log = logging.getLogger("stage3_crawling")
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
 """, (engagement, "CRAWLING", dtype, value, confidence, tool))
 conn.commit()
 conn.close()
 except Exception as e:
 log.error(f"DB insert failed: {e}")


def _run_tool(cmd: list, timeout: int = 300) -> str:
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


def _katana(target: str, engagement: str,
 max_depth: int = 3) -> list:
 """Recursive JS-aware crawling via katana."""
 log.info(f"katana — {target} (depth {max_depth})")
 urls = []

 output = _run_tool([
 "katana", "-u", f"https://{target}",
 "-d", str(max_depth), "-silent",
 "-jc", "-kf", "all"
 ], timeout=300)

 for line in output.splitlines():
 line = line.strip()
 if line and target in line:
 urls.append(line)
 _db_insert(engagement, "url", line, "katana")

 log.info(f"katana found {len(urls)} URLs")
 return urls


def _gau(target: str, engagement: str) -> list:
 """Passive URL aggregation via gau."""
 log.info(f"gau — {target}")
 urls = []

 output = _run_tool(["gau", target, "--subs"], timeout=120)
 for line in output.splitlines():
 line = line.strip()
 if line:
 urls.append(line)
 _db_insert(engagement, "url", line, "gau")

 log.info(f"gau found {len(urls)} URLs")
 return urls


def _waybackurls(target: str, engagement: str) -> list:
 """Wayback Machine URL extraction."""
 log.info(f"waybackurls — {target}")
 urls = []

 output = _run_tool(["waybackurls", target], timeout=120)
 for line in output.splitlines():
 line = line.strip()
 if line:
 urls.append(line)
 _db_insert(engagement, "url", line, "waybackurls")

 log.info(f"waybackurls found {len(urls)} URLs")
 return urls


def _feroxbuster(target: str, engagement: str,
 wordlist: str = None) -> list:
 """Recursive content discovery via feroxbuster."""
 log.info(f"feroxbuster — {target}")
 endpoints = []

 # Use SecLists if available
 if not wordlist:
 seclists_path = Path(
 "/root/.openclaw/workspace/openclaw-skills/repos"
 "/SecLists/Discovery/Web-Content/common.txt"
 )
 wordlist = str(seclists_path) if seclists_path.exists() \
 else "/usr/share/wordlists/dirb/common.txt"

 output = _run_tool([
 "feroxbuster", "-u", f"https://{target}",
 "-w", wordlist, "-s", "200,201,204,301,302,403",
 "-q", "--no-recursion", "-t", "50"
 ], timeout=300)

 for line in output.splitlines():
 line = line.strip()
 if line and target in line:
 endpoints.append(line)
 _db_insert(engagement, "endpoint", line, "feroxbuster")

 log.info(f"feroxbuster found {len(endpoints)} endpoints")
 return endpoints


def _paramspider(target: str, engagement: str) -> list:
 """Parameter mining via paramspider."""
 log.info(f"paramspider — {target}")
 params = []

 output = _run_tool([
 "python3", "-m", "paramspider",
 "--domain", target, "--quiet"
 ], timeout=120)

 for line in output.splitlines():
 line = line.strip()
 if line and "?" in line:
 params.append(line)
 _db_insert(engagement, "parameter_url", line, "paramspider")

 log.info(f"paramspider found {len(params)} parameterized URLs")
 return params


def _filter_scope(urls: list, authorized: list,
 exclude: list) -> list:
 """Filter URLs to authorized scope, remove excluded patterns."""
 import re
 filtered = []
 for url in urls:
 in_scope = any(domain in url for domain in authorized)
 excluded = any(
 re.search(pattern.replace("*", ".*"), url)
 for pattern in exclude
 )
 if in_scope and not excluded:
 filtered.append(url)
 return list(set(filtered))


def run(target: str, config: dict) -> dict:
 """Stage 3 entry point."""
 log.info(f"{'='*60}")
 log.info(f"Stage 3 — Crawling & Endpoint Discovery")
 log.info(f"Target: {target}")

 engagement = config.get("engagement_name", "default")
 authorized = config.get("authorized_domains", [target])
 exclude = config.get("exclude_patterns", [])
 max_depth = config.get("rate_limits", {}).get("max_depth", 3)

 findings = {
 "stage": 3,
 "name": "CRAWLING",
 "target": target,
 "timestamp": datetime.utcnow().isoformat(),
 "tools_invoked": [],
 "urls_discovered": [],
 "endpoints_found": [],
 "parameter_urls": []
 }

 # Active crawl
 katana_urls = _katana(target, engagement, max_depth)
 findings["urls_discovered"].extend(katana_urls)
 findings["tools_invoked"].append("katana")

 # Passive URL aggregation
 gau_urls = _gau(target, engagement)
 findings["urls_discovered"].extend(gau_urls)
 findings["tools_invoked"].append("gau")

 wayback_urls = _waybackurls(target, engagement)
 findings["urls_discovered"].extend(wayback_urls)
 findings["tools_invoked"].append("waybackurls")

 # Directory discovery
 endpoints = _feroxbuster(target, engagement)
 findings["endpoints_found"].extend(endpoints)
 findings["tools_invoked"].append("feroxbuster")

 # Parameter mining
 params = _paramspider(target, engagement)
 findings["parameter_urls"].extend(params)
 findings["tools_invoked"].append("paramspider")

 # Scope filter
 findings["urls_discovered"] = _filter_scope(
 findings["urls_discovered"], authorized, exclude
 )
 findings["endpoints_found"] = _filter_scope(
 findings["endpoints_found"], authorized, exclude
 )

 log.info(
 f"Stage 3 complete — "
 f"{len(findings['urls_discovered'])} URLs, "
 f"{len(findings['endpoints_found'])} endpoints, "
 f"{len(findings['parameter_urls'])} parameter URLs"
 )

 return findings
