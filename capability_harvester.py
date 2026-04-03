#!/usr/bin/env python3
"""
capability_harvester.py
OpenClaw Pipeline — GitHub Capability Harvester
Agent: Elkin 🔱 | Version: 2.0
"""

import os
import json
import time
import shutil
import sqlite3
import subprocess
import logging
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from github import Github, RateLimitExceededException, GithubException

load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================

GITHUB_ACCESS_TOKEN = os.getenv("GITHUB_PAT", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8069069638")

OUTPUT_DIR = Path(".openclaw/github-discovery")
CAPABILITY_REGISTRY = Path(".openclaw/capability_registry.json")
DB_PATH = Path("reports/sqlite/capabilities.db")
LOG_PATH = Path(".openclaw/logs/harvester.log")
CLONE_ROOT = Path("/tmp/openclaw-clones")

MAX_RETRIES = 5
BACKOFF_BASE = 2
SLEEP_BETWEEN_REPOS = 2
STARS_MIN = 15
MATCH_THRESHOLD = 2

# ============================================================
# PATTERN SIGNATURE TAXONOMY
# ============================================================

PATTERN_SIGNATURES = {
 "fuzzing": [
 "ffuf", "dirsearch", "wfuzz", "feroxbuster", "gobuster",
 "dirb", "bruteforce", "wordlist", "fuzz", "brute-force",
 "content discovery", "burp intruder"
 ],
 "crawling": [
 "katana", "gospider", "hakrawler", "scrapy", "playwright",
 "puppeteer", "selenium", "crawlergo", "cariddi", "blackwidow",
 "photon", "spider", "web crawl", "link extractor",
 "recursive crawl", "sitemap", "linkfinder", "paramspider"
 ],
 "osint": [
 "spiderfoot", "recon-ng", "theharvester", "bbot", "amass",
 "maltego", "osmedeus", "datasploit", "sn0int", "lazyrecon",
 "shodan", "censys", "sublist3r", "fierce", "aquatone",
 "eyewitness", "hunter.io", "clearbit", "metagoofil", "foca"
 ],
 "evasion": [
 "flaresolverr", "undetected", "stealth", "camoufox",
 "nodriver", "antibot", "cloudflare bypass", "captcha",
 "proxy rotation", "user-agent rotation", "fingerprint spoof",
 "rate limit bypass", "waf bypass", "undetected-chromedriver",
 "2captcha", "anticaptcha", "capmonster", "drissionpage"
 ],
 "secrets": [
 "trufflehog", "gitleaks", "gitdorker", "secret scanning",
 "api key", "hardcoded", "credential", "token leak",
 "sensitive data", "git secret", "env leak"
 ],
 "darkweb": [
 "torbot", "onionscan", "darkscrape", "ahmia",
 "dark web", "deep web", "hidden service", "i2p", "socks5"
 ],
 "extraction": [
 "beautifulsoup", "lxml", "cheerio", "camelot", "tabula",
 "mechanicalsoup", "requests-html", "httpx",
 "html parser", "xpath", "css selector", "pdf extract",
 "docparser", "data extract", "scrape"
 ],
 "scaling": [
 "celery", "scrapy-cluster", "redis", "dask", "kafka",
 "distributed", "workers", "queue", "parallel",
 "frontera", "apify", "lambda", "serverless", "docker",
 "kubernetes", "container", "microservice"
 ],
 "ai": [
 "scrapegraphai", "firecrawl", "autoscraper", "diffbot",
 "agentql", "llm", "langchain", "ml scraper",
 "ai extract", "neural", "transformer"
 ],
 "recon": [
 "nmap", "masscan", "nuclei", "nikto", "arachni",
 "burp suite", "zaproxy", "owasp zap",
 "port scan", "network scan", "vulnerability scan",
 "subdomain enum", "dns enum", "attack surface"
 ]
}

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
log = logging.getLogger("capability_harvester")

# ============================================================
# TELEGRAM
# ============================================================

def notify_telegram(message: str):
 """Send notification to Operator via Telegram."""
 if not TELEGRAM_BOT_TOKEN:
 log.warning("TELEGRAM_BOT_TOKEN not set — skipping notification")
 return
 try:
 requests.post(
 f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
 json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
 timeout=10
 )
 log.info("Telegram notification sent")
 except Exception as e:
 log.error(f"Telegram notify failed: {e}")

# ============================================================
# GITHUB CLIENT
# ============================================================

class RateLimitAwareGitHub:
 def __init__(self, token: str):
 self.client = Github(token, per_page=10)
 self.request_count = 0

 def get_remaining(self) -> int:
 return self.client.get_rate_limit().core.remaining

 def wait_if_needed(self):
 remaining = self.get_remaining()
 log.info(f"GitHub API rate limit remaining: {remaining}")
 if remaining < 100:
 reset_time = self.client.get_rate_limit().core.reset
 wait_seconds = (reset_time - datetime.utcnow()).total_seconds() + 10
 log.warning(f"Rate limit low — sleeping {wait_seconds:.0f}s")
 time.sleep(max(wait_seconds, 60))

 def search_repositories(self, query: str):
 for attempt in range(MAX_RETRIES):
 try:
 self.wait_if_needed()
 results = self.client.search_repositories(query)
 self.request_count += 1
 return results
 except RateLimitExceededException:
 wait = BACKOFF_BASE ** attempt
 log.warning(f"Rate limit hit — backing off {wait}s")
 time.sleep(wait)
 except GithubException as e:
 log.error(f"GitHub API error: {e}")
 time.sleep(BACKOFF_BASE ** attempt)
 log.error("Max retries exceeded")
 return []

# ============================================================
# DATABASE
# ============================================================

def init_database():
 DB_PATH.parent.mkdir(parents=True, exist_ok=True)
 conn = sqlite3.connect(DB_PATH)
 c = conn.cursor()
 c.executescript("""
 CREATE TABLE IF NOT EXISTS capabilities (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 repo_name TEXT NOT NULL,
 pattern TEXT NOT NULL,
 signature TEXT NOT NULL,
 first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
 times_seen INTEGER DEFAULT 1,
 UNIQUE(repo_name, pattern, signature)
 );
 CREATE TABLE IF NOT EXISTS harvester_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 run_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 repos_scanned INTEGER DEFAULT 0,
 patterns_found INTEGER DEFAULT 0,
 new_capabilities INTEGER DEFAULT 0,
 status TEXT
 );
 CREATE INDEX IF NOT EXISTS idx_capability_pattern
 ON capabilities (pattern);
 """)
 conn.commit()
 conn.close()
 log.info("Database initialized")

def db_insert_capabilities(repo_name: str, patterns: dict):
 conn = sqlite3.connect(DB_PATH)
 c = conn.cursor()
 for pattern, signatures in patterns.items():
 for sig in signatures:
 c.execute("""
 INSERT INTO capabilities (repo_name, pattern, signature)
 VALUES (?, ?, ?)
 ON CONFLICT(repo_name, pattern, signature)
 DO UPDATE SET times_seen = times_seen + 1
 """, (repo_name, pattern, sig))
 conn.commit()
 conn.close()

def db_log_run(repos_scanned: int, patterns_found: int,
 new_caps: int, status: str):
 conn = sqlite3.connect(DB_PATH)
 c = conn.cursor()
 c.execute("""
 INSERT INTO harvester_runs
 (repos_scanned, patterns_found, new_capabilities, status)
 VALUES (?, ?, ?, ?)
 """, (repos_scanned, patterns_found, new_caps, status))
 conn.commit()
 conn.close()

# ============================================================
# PATTERN MATCHING
# ============================================================

def extract_patterns(content: str) -> dict:
 content_lower = content.lower()
 matched = {}
 for category, signatures in PATTERN_SIGNATURES.items():
 hits = [sig for sig in signatures if sig.lower() in content_lower]
 if len(hits) >= MATCH_THRESHOLD:
 matched[category] = hits
 return matched

def analyze_repo(local_path: Path) -> dict:
 log.info(f"Analyzing: {local_path}")
 combined_content = ""

 priority_files = [
 "README.md", "README.rst", "requirements.txt",
 "setup.py", "pyproject.toml", "package.json"
 ]
 for fname in priority_files:
 fpath = local_path / fname
 if fpath.exists():
 try:
 combined_content += fpath.read_text(encoding="utf-8", errors="ignore")
 except Exception:
 pass

 extensions = [".py", ".sh", ".js", ".ts", ".go", ".rb", ".yaml", ".yml"]
 files_read = 0
 for fpath in local_path.rglob("*"):
 if fpath.suffix in extensions and fpath.is_file() and files_read < 50:
 try:
 combined_content += fpath.read_text(encoding="utf-8", errors="ignore")
 files_read += 1
 except Exception:
 pass

 matched = extract_patterns(combined_content)
 if matched:
 log.info(f"Patterns found: {list(matched.keys())}")
 else:
 log.info("No significant patterns detected")
 return matched

# ============================================================
# REGISTRY
# ============================================================

def load_registry() -> dict:
 if CAPABILITY_REGISTRY.exists():
 with open(CAPABILITY_REGISTRY, "r") as f:
 return json.load(f)
 return {
 "capabilities": {},
 "pattern_index": {},
 "last_updated": None,
 "version": "2.0"
 }

def update_registry(registry: dict, repo_name: str,
 patterns: dict) -> tuple:
 new_count = 0
 pattern_index = registry.setdefault("pattern_index", {})
 capabilities = registry.setdefault("capabilities", {})

 for category, signatures in patterns.items():
 existing_sigs = set(pattern_index.get(category, []))
 new_sigs = set(signatures) - existing_sigs

 if not new_sigs:
 log.info(f"[DEDUP] {category} — all signatures already registered")
 continue

 pattern_index[category] = list(existing_sigs | new_sigs)
 capabilities.setdefault(repo_name, {})
 capabilities[repo_name][category] = {
 "signatures_matched": list(new_sigs),
 "first_seen": datetime.utcnow().isoformat(),
 "source_repo": repo_name
 }
 new_count += 1
 log.info(f"[NEW CAPABILITY] {category} — {list(new_sigs)} from {repo_name}")

 registry["last_updated"] = datetime.utcnow().isoformat()
 return registry, new_count

def save_registry(registry: dict):
 CAPABILITY_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
 with open(CAPABILITY_REGISTRY, "w") as f:
 json.dump(registry, f, indent=4)
 log.info(f"Registry saved: {CAPABILITY_REGISTRY}")

# ============================================================
# DISK MANAGEMENT
# ============================================================

def clone_repo(repo_url: str, local_path: Path) -> bool:
 try:
 subprocess.run(
 ["git", "clone", "--depth", "1", repo_url, str(local_path)],
 check=True,
 capture_output=True,
 timeout=120
 )
 return True
 except subprocess.CalledProcessError as e:
 log.error(f"Clone failed for {repo_url}: {e}")
 return False
 except subprocess.TimeoutExpired:
 log.error(f"Clone timed out: {repo_url}")
 return False

def cleanup_clone(local_path: Path):
 if local_path.exists():
 shutil.rmtree(local_path, ignore_errors=True)
 log.info(f"Cleaned up: {local_path}")

# ============================================================
# MAIN HARVESTER
# ============================================================

class CapabilityHarvester:
 def __init__(self):
 if not GITHUB_ACCESS_TOKEN:
 raise ValueError("GITHUB_PAT not set in environment")
 self.gh = RateLimitAwareGitHub(GITHUB_ACCESS_TOKEN)
 self.registry = load_registry()
 self.stats = {
 "repos_scanned": 0,
 "patterns_found": 0,
 "new_capabilities": 0,
 "repos_skipped": 0,
 "clone_failures": 0
 }

 def search_targets(self) -> list:
 targets = []
 seen_repos = set()

 search_terms = [
 "web crawler security tool",
 "osint framework recon",
 "web fuzzer endpoint discovery",
 "payload generator red team",
 "secret scanner git",
 "stealth scraper evasion",
 "distributed scraping celery redis",
 "ai scraper llm extraction",
 "subdomain enumeration amass",
 "vulnerability scanner nuclei"
 ]

 for term in search_terms:
 query = (
 f"{term} stars:>{STARS_MIN} "
 f"language:Python OR language:Go OR language:JavaScript"
 )
 log.info(f"Searching: {query}")
 results = self.gh.search_repositories(query)

 try:
 for repo in results:
 if repo.full_name not in seen_repos:
 seen_repos.add(repo.full_name)
 targets.append({
 "name": repo.full_name,
 "url": repo.clone_url,
 "stars": repo.stargazers_count,
 "description": repo.description or ""
 })
 time.sleep(0.5)
 except GithubException as e:
 log.error(f"Search error: {e}")

 log.info(f"Total unique repos to process: {len(targets)}")
 return targets

 def process_repo(self, repo: dict) -> int:
 repo_name = repo["name"]
 log.info(f"\n{'='*60}")
 log.info(f"Processing: {repo_name} ({repo['stars']} stars)")

 # Pre-screen description before cloning
 pre_match = extract_patterns(repo.get("description", "") or "")
 if not pre_match:
 log.info(f"[SKIP] Pre-screen failed: {repo_name}")
 self.stats["repos_skipped"] += 1
 return 0

 local_path = CLONE_ROOT / repo_name.replace("/", "_")
 local_path.parent.mkdir(parents=True, exist_ok=True)

 if not clone_repo(repo["url"], local_path):
 self.stats["clone_failures"] += 1
 return 0

 try:
 patterns = analyze_repo(local_path)
 self.stats["repos_scanned"] += 1

 if not patterns:
 log.info(f"No patterns extracted from {repo_name}")
 return 0

 self.stats["patterns_found"] += len(patterns)

 self.registry, new_caps = update_registry(
 self.registry, repo_name, patterns
 )
 self.stats["new_capabilities"] += new_caps

 if new_caps > 0:
 db_insert_capabilities(repo_name, patterns)

 return new_caps

 finally:
 cleanup_clone(local_path)
 time.sleep(SLEEP_BETWEEN_REPOS)

 def run(self):
 log.info("🔱 Elkin — Capability Harvester v2.0 starting")
 log.info(
 f"Registry loaded: "
 f"{len(self.registry.get('capabilities', {}))} existing entries"
 )

 notify_telegram(
 "🔄 [HARVESTER] Starting capability scan\n"
 f"Registry entries: {len(self.registry.get('capabilities', {}))}"
 )

 init_database()
 CLONE_ROOT.mkdir(parents=True, exist_ok=True)

 status = "complete"
 try:
 repos = self.search_targets()
 for repo in repos:
 try:
 self.process_repo(repo)
 except Exception as e:
 log.error(f"Error processing {repo['name']}: {e}")
 continue

 except Exception as e:
 log.error(f"Harvester run failed: {e}")
 status = "failed"

 finally:
 save_registry(self.registry)

 db_log_run(
 self.stats["repos_scanned"],
 self.stats["patterns_found"],
 self.stats["new_capabilities"],
 status
 )

 if CLONE_ROOT.exists():
 shutil.rmtree(CLONE_ROOT, ignore_errors=True)

 summary = (
 f"\n{'='*60}\n"
 f"🔱 Harvester Run Complete\n"
 f"Repos scanned: {self.stats['repos_scanned']}\n"
 f"Repos skipped: {self.stats['repos_skipped']}\n"
 f"Clone failures: {self.stats['clone_failures']}\n"
 f"Patterns found: {self.stats['patterns_found']}\n"
 f"New capabilities: {self.stats['new_capabilities']}\n"
 f"Status: {status}\n"
 f"{'='*60}"
 )
 log.info(summary)

 notify_telegram(
 f"✅ [HARVESTER] Run complete\n"
 f"Repos scanned: {self.stats['repos_scanned']}\n"
 f"New capabilities: {self.stats['new_capabilities']}\n"
 f"Status: {status}"
 )


if __name__ == "__main__":
 harvester = CapabilityHarvester()
 harvester.run()
