#!/usr/bin/env python3
"""
pipeline/stage5_extraction.py
OpenClaw Pipeline — Stage 5: Data Extraction & Secret Detection
Agent: Elkin 🔱 | Version: 2.0
"""

import re
import os
import json
import hashlib
import logging
import sqlite3
import requests
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("stage5_extraction")
DB_PATH = Path("reports/sqlite/engagement.db")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8069069638")

# ============================================================
# SECRET PATTERNS
# ============================================================

SECRET_PATTERNS = {
 "aws_access_key": r"AKIA[0-9A-Z]{16}",
 "aws_secret_key": r"(?i)aws.{0,20}secret.{0,20}['\"][0-9a-zA-Z/+]{40}['\"]",
 "github_token": r"ghp_[a-zA-Z0-9]{36}",
 "google_api_key": r"AIza[0-9A-Za-z\-_]{35}",
 "stripe_secret": r"sk_live_[0-9a-zA-Z]{24,}",
 "stripe_publishable":r"pk_live_[0-9a-zA-Z]{24,}",
 "jwt_token": r"eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+",
 "private_key": r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----",
 "password_field": r"(?i)(?:password|passwd|pwd)\s*[=:]\s*['\"][^'\"]{6,}['\"]",
 "api_key_generic": r"(?i)api[_-]?key\s*[=:]\s*['\"][a-zA-Z0-9_\-]{16,}['\"]",
 "bearer_token": r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{20,}",
 "database_url": r"(?i)(?:mysql|postgres|mongodb|redis)://[^\s'\"]+",
 "email_address": r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
 "internal_ip": r"(?:10\.|172\.(?:1[6-9]|2[0-9]|3[01])\.|192\.168\.)\d{1,3}\.\d{1,3}",
 "wp_auth_key": r"(?i)define\s*\(\s*['\"](?:AUTH_KEY|SECURE_AUTH_KEY|LOGGED_IN_KEY)['\"]",
}


def _db_insert_secret(engagement: str, stype: str,
 value: str, source: str, severity: str):
 """Store secret with hashed value — never store plaintext."""
 value_hash = hashlib.sha256(value.encode()).hexdigest()
 try:
 conn = sqlite3.connect(DB_PATH)
 c = conn.cursor()
 c.execute("""
 INSERT INTO secrets
 (engagement_name, type, value_hash, source_url, source_tool, severity)
 VALUES (?, ?, ?, ?, ?, ?)
 """, (engagement, stype, value_hash, source, "regex", severity))
 conn.commit()
 conn.close()
 except Exception as e:
 log.error(f"DB insert failed: {e}")


def _db_insert(engagement: str, dtype: str,
 value: str, tool: str, confidence: float = 0.8):
 try:
 conn = sqlite3.connect(DB_PATH)
 c = conn.cursor()
 c.execute("""
 INSERT INTO discoveries
 (engagement_name, stage, type, value, confidence, source_tool)
 VALUES (?, ?, ?, ?, ?, ?)
 """, (engagement, "EXTRACTION", dtype, value, confidence, tool))
 conn.commit()
 conn.close()
 except Exception as e:
 log.error(f"DB insert failed: {e}")


def _notify_critical(message: str):
 """Immediate Telegram alert for critical findings."""
 if not TELEGRAM_BOT_TOKEN:
 return
 try:
 requests.post(
 f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
 json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
 timeout=10
 )
 except Exception as e:
 log.error(f"Telegram notify failed: {e}")


def _classify_severity(secret_type: str) -> str:
 critical = [
 "aws_access_key", "aws_secret_key", "private_key",
 "stripe_secret", "database_url"
 ]
 high = [
 "github_token", "google_api_key", "jwt_token",
 "bearer_token", "api_key_generic"
 ]
 if secret_type in critical:
 return "critical"
 if secret_type in high:
 return "high"
 return "medium"


def _scan_content(content: str, source_url: str,
 engagement: str) -> dict:
 """Scan content string for all secret patterns."""
 found = {k: [] for k in SECRET_PATTERNS}

 for secret_type, pattern in SECRET_PATTERNS.items():
 matches = re.findall(pattern, content)
 if matches:
 severity = _classify_severity(secret_type)
 for match in matches:
 found[secret_type].append(match)
 _db_insert_secret(
 engagement, secret_type,
 match, source_url, severity
 )
 log.warning(
 f"[SECRET] {secret_type} ({severity}) found at {source_url}"
 )
 if severity == "critical":
 _notify_critical(
 f"🚨 [CRITICAL SECRET] {secret_type}\n"
 f"Source: {source_url}\n"
 f"Engagement: {engagement}"
 )

 return {k: v for k, v in found.items() if v}


def _fetch_and_scan(url: str, engagement: str,
 session: requests.Session) -> dict:
 """Fetch URL and scan content for secrets."""
 try:
 resp = session.get(url, timeout=10, verify=False)
 if resp.status_code == 200:
 return _scan_content(resp.text, url, engagement)
 except Exception as e:
 log.debug(f"Fetch failed {url}: {e}")
 return {}


def _run_tool(cmd: list, timeout: int = 120) -> str:
 try:
 result = subprocess.run(
 cmd, capture_output=True, text=True, timeout=timeout
 )
 return result.stdout
 except FileNotFoundError:
 log.warning(f"Tool not found: {cmd[0]}")
 return ""
 except Exception as e:
 log.error(f"Tool error {cmd[0]}: {e}")
 return ""


def _trufflehog_scan(target_url: str, engagement: str) -> list:
 """Secret scanning via trufflehog."""
 log.info(f"trufflehog — {target_url}")
 secrets = []

 output = _run_tool([
 "trufflehog", "http", "--url", target_url,
 "--json", "--no-verification"
 ], timeout=120)

 for line in output.splitlines():
 try:
 entry = json.loads(line)
 secret_type = entry.get("DetectorName", "unknown")
 raw = entry.get("Raw", "")
 source = entry.get("SourceMetadata", {}).get("Data", {})
 src_url = str(source) if source else target_url

 if raw:
 secrets.append({
 "type": secret_type,
 "source": src_url
 })
 severity = _classify_severity(secret_type.lower())
 _db_insert_secret(
 engagement, secret_type, raw, src_url, severity
 )
 if severity == "critical":
 _notify_critical(
 f"🚨 [TRUFFLEHOG] {secret_type}\n"
 f"Source: {src_url}\n"
 f"Engagement: {engagement}"
 )
 except json.JSONDecodeError:
 pass

 log.info(f"trufflehog found {len(secrets)} secrets")
 return secrets


def run(target: str, config: dict) -> dict:
 """Stage 5 entry point."""
 log.info(f"{'='*60}")
 log.info(f"Stage 5 — Data Extraction & Secret Detection")
 log.info(f"Target: {target}")

 engagement = config.get("engagement_name", "default")
 urls = config.get("stage3_findings", {}).get("urls_discovered", [])
 endpoints = config.get("stage3_findings", {}).get("endpoints_found", [])

 findings = {
 "stage": 5,
 "name": "EXTRACTION",
 "target": target,
 "timestamp": datetime.utcnow().isoformat(),
 "tools_invoked": [],
 "secrets_found": {},
 "emails_found": [],
 "api_keys_found": 0,
 "critical_count": 0,
 "high_count": 0
 }

 session = requests.Session()
 session.headers.update({
 "User-Agent": (
 "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
 "AppleWebKit/537.36"
 )
 })

 # Scan all discovered URLs
 all_urls = list(set(urls + endpoints))
 log.info(f"Scanning {len(all_urls)} URLs for secrets")

 for url in all_urls[:500]: # Cap at 500 to prevent runaway
 url_secrets = _fetch_and_scan(url, engagement, session)
 for secret_type, matches in url_secrets.items():
 findings["secrets_found"].setdefault(secret_type, [])
 findings["secrets_found"][secret_type].extend(matches)

 if secret_type == "email_address":
 findings["emails_found"].extend(matches)
 if "key" in secret_type or "token" in secret_type:
 findings["api_keys_found"] += len(matches)

 findings["tools_invoked"].append("regex_scanner")

 # TruffleHog on target
 trufflehog_results = _trufflehog_scan(
 f"https://{target}", engagement
 )
 findings["tools_invoked"].append("trufflehog")

 # Count by severity
 critical_types = [
 "aws_access_key", "aws_secret_key",
 "private_key", "stripe_secret", "database_url"
 ]
 high_types = [
 "github_token", "google_api_key",
 "jwt_token", "bearer_token", "api_key_generic"
 ]

 for stype, matches in findings["secrets_found"].items():
 if stype in critical_types:
 findings["critical_count"] += len(matches)
 elif stype in high_types:
 findings["high_count"] += len(matches)

 # Deduplicate emails
 findings["emails_found"] = list(set(findings["emails_found"]))

 log.info(
 f"Stage 5 complete — "
 f"Critical: {findings['critical_count']}, "
 f"High: {findings['high_count']}, "
 f"Emails: {len(findings['emails_found'])}"
 )

 return findings
