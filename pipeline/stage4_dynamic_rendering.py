#!/usr/bin/env python3
"""
pipeline/stage4_dynamic_rendering.py
OpenClaw Pipeline — Stage 4: Dynamic JS Rendering
Agent: Elkin 🔱 | Version: 2.0
"""

import logging
import sqlite3
import asyncio
import json
from pathlib import Path
from datetime import datetime

log = logging.getLogger("stage4_dynamic_rendering")
DB_PATH = Path("reports/sqlite/engagement.db")
SCREENSHOTS = Path("reports/screenshots")


def _db_insert(engagement: str, dtype: str,
 value: str, tool: str, confidence: float = 0.8):
 try:
 conn = sqlite3.connect(DB_PATH)
 c = conn.cursor()
 c.execute("""
 INSERT INTO discoveries
 (engagement_name, stage, type, value, confidence, source_tool)
 VALUES (?, ?, ?, ?, ?, ?)
 """, (engagement, "DYNAMIC_RENDERING", dtype, value, confidence, tool))
 conn.commit()
 conn.close()
 except Exception as e:
 log.error(f"DB insert failed: {e}")


async def _render_page(url: str, engagement: str,
 run_id: str) -> dict:
 """
 Render a single page with Playwright.
 Captures: DOM, API calls, forms, cookies, screenshot.
 """
 try:
 from playwright.async_api import async_playwright
 except ImportError:
 log.warning("playwright not installed — skipping dynamic rendering")
 return {}

 page_data = {
 "url": url,
 "api_calls": [],
 "forms": [],
 "cookies": [],
 "screenshot": "",
 "title": ""
 }

 try:
 async with async_playwright() as p:
 browser = await p.chromium.launch(headless=True)
 context = await browser.new_context(
 user_agent=(
 "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
 "AppleWebKit/537.36 (KHTML, like Gecko) "
 "Chrome/120.0.0.0 Safari/537.36"
 )
 )
 page = await context.new_page()

 # Intercept network requests
 api_calls = []
 page.on("request", lambda r: api_calls.append({
 "url": r.url,
 "method": r.method,
 "headers": dict(r.headers)
 }) if r.resource_type in ["xhr", "fetch"] else None)

 await page.goto(url, wait_until="networkidle", timeout=30000)
 await page.wait_for_timeout(2000)

 # Extract data
 page_data["title"] = await page.title()
 page_data["api_calls"] = api_calls
 page_data["cookies"] = await context.cookies()

 # Extract forms
 forms = await page.query_selector_all("form")
 for form in forms:
 action = await form.get_attribute("action") or ""
 method = await form.get_attribute("method") or "GET"
 inputs = await form.query_selector_all("input")
 input_names = []
 for inp in inputs:
 name = await inp.get_attribute("name") or ""
 itype = await inp.get_attribute("type") or "text"
 if name:
 input_names.append({"name": name, "type": itype})
 page_data["forms"].append({
 "action": action,
 "method": method.upper(),
 "inputs": input_names
 })

 # Screenshot
 ss_dir = SCREENSHOTS / run_id
 ss_dir.mkdir(parents=True, exist_ok=True)
 safe_name = url.replace("https://", "").replace(
 "/", "_"
 )[:80]
 ss_path = ss_dir / f"{safe_name}.png"
 await page.screenshot(path=str(ss_path), full_page=True)
 page_data["screenshot"] = str(ss_path)

 await browser.close()

 # Store API calls
 for call in api_calls:
 _db_insert(engagement, "api_call", call["url"], "playwright")

 # Store forms
 for form in page_data["forms"]:
 _db_insert(
 engagement, "form",
 json.dumps(form), "playwright"
 )

 except Exception as e:
 log.error(f"Playwright render error for {url}: {e}")

 return page_data


def _select_urls(all_urls: list, max_urls: int = 50) -> list:
 """
 Select highest-value URLs for dynamic rendering.
 Prioritise: login pages, checkout, API endpoints, forms.
 """
 priority_keywords = [
 "login", "signin", "checkout", "payment",
 "account", "admin", "api", "auth", "register",
 "upload", "search", "contact"
 ]

 priority = []
 standard = []

 for url in all_urls:
 url_lower = url.lower()
 if any(kw in url_lower for kw in priority_keywords):
 priority.append(url)
 else:
 standard.append(url)

 selected = priority[:max_urls]
 remaining = max_urls - len(selected)
 selected += standard[:remaining]

 return selected


def run(target: str, config: dict) -> dict:
 """Stage 4 entry point."""
 log.info(f"{'='*60}")
 log.info(f"Stage 4 — Dynamic JS Rendering")
 log.info(f"Target: {target}")

 engagement = config.get("engagement_name", "default")
 all_urls = config.get("stage3_findings", {}).get("urls_discovered", [])
 max_depth = config.get("rate_limits", {}).get("max_urls_per_domain", 5000)
 run_id = config.get("run_id", "default")

 findings = {
 "stage": 4,
 "name": "DYNAMIC_RENDERING",
 "target": target,
 "timestamp": datetime.utcnow().isoformat(),
 "tools_invoked": ["playwright"],
 "pages_rendered": [],
 "api_calls_intercepted": [],
 "forms_detected": [],
 "screenshots": []
 }

 if not all_urls:
 # Fallback to target root
 all_urls = [f"https://{target}"]

 selected = _select_urls(all_urls, max_urls=50)
 log.info(f"Rendering {len(selected)} selected URLs")

 async def render_all():
 tasks = [
 _render_page(url, engagement, run_id)
 for url in selected
 ]
 return await asyncio.gather(*tasks, return_exceptions=True)

 results = asyncio.run(render_all())

 for result in results:
 if isinstance(result, dict) and result:
 findings["pages_rendered"].append(result.get("url", ""))
 findings["api_calls_intercepted"].extend(
 result.get("api_calls", [])
 )
 findings["forms_detected"].extend(result.get("forms", []))
 if result.get("screenshot"):
 findings["screenshots"].append(result["screenshot"])

 log.info(
 f"Stage 4 complete — "
 f"{len(findings['pages_rendered'])} pages rendered, "
 f"{len(findings['api_calls_intercepted'])} API calls, "
 f"{len(findings['forms_detected'])} forms"
 )

 return findings
