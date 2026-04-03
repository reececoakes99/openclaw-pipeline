#!/usr/bin/env python3
"""
pipeline/stage9_ai_enrichment.py
OpenClaw Pipeline — Stage 9: AI Enrichment & Intelligence Synthesis
Agent: Elkin 🔱 | Version: 2.0
"""

import os
import json
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("stage9_ai_enrichment")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")


def _call_claude(prompt: str) -> str:
 """Call Claude via Anthropic API with OpenRouter fallback."""
 headers = {"Content-Type": "application/json"}
 payload = {
 "model": "claude-sonnet-4-20250514",
 "max_tokens": 2000,
 "messages": [{"role": "user", "content": prompt}]
 }

 # Try Anthropic direct first
 if ANTHROPIC_API_KEY:
 try:
 resp = requests.post(
 "https://api.anthropic.com/v1/messages",
 headers={
 **headers,
 "x-api-key": ANTHROPIC_API_KEY,
 "anthropic-version": "2023-06-01"
 },
 json=payload,
 timeout=60
 )
 if resp.status_code == 200:
 return resp.json()["content"][0]["text"]
 except Exception as e:
 log.error(f"Anthropic API error: {e}")

 # Fallback to OpenRouter
 if OPENROUTER_API_KEY:
 try:
 payload["model"] = "anthropic/claude-sonnet-4-20250514"
 resp = requests.post(
 "https://openrouter.ai/api/v1/chat/completions",
 headers={
 **headers,
 "Authorization": f"Bearer {OPENROUTER_API_KEY}"
 },
 json={
 "model": payload["model"],
 "messages": payload["messages"],
 "max_tokens": payload["max_tokens"]
 },
 timeout=60
 )
 if resp.status_code == 200:
 return resp.json()["choices"][0]["message"]["content"]
 except Exception as e:
 log.error(f"OpenRouter API error: {e}")

 log.warning("All AI providers failed — returning empty synthesis")
 return ""


def _synthesize_findings(target: str, all_findings: dict) -> str:
 """Use Claude to synthesize all stage findings into actionable intel."""
 summary = {
 "target": target,
 "subdomains_count": len(
 all_findings.get("stage1", {}).get("subdomains_found", [])
 ),
 "emails_count": len(
 all_findings.get("stage1", {}).get("emails_found", [])
 ),
 "live_hosts_count": len(
 all_findings.get("stage2", {}).get("live_hosts", [])
 ),
 "open_ports": all_findings.get("stage2", {}).get("open_ports", {}),
 "tech_stack": all_findings.get("stage2", {}).get("tech_stack", {}),
 "urls_count": len(
 all_findings.get("stage3", {}).get("urls_discovered", [])
 ),
 "endpoints_count": len(
 all_findings.get("stage3", {}).get("endpoints_found", [])
 ),
 "forms_count": len(
 all_findings.get("stage4", {}).get("forms_detected", [])
 ),
 "api_calls_count": len(
 all_findings.get("stage4", {}).get("api_calls_intercepted", [])
 ),
 "critical_secrets": all_findings.get("stage5", {}).get("critical_count", 0),
 "high_secrets": all_findings.get("stage5", {}).get("high_count", 0),
 "breaches": all_findings.get("stage8", {}).get("breach_count", 0)
 }

 prompt = f"""You are Elkin, an autonomous red team intelligence agent.
Analyze these engagement findings for target: {target}

Findings summary:
{json.dumps(summary, indent=2)}

Provide:
1. Executive summary (3-4 sentences)
2. Top 5 highest-priority attack vectors based on findings
3. Critical findings requiring immediate Operator attention
4. Recommended next steps for the engagement
5. Overall attack surface score (1-10) with justification

Be precise, tactical, and actionable. Lead with the highest-impact findings.
"""

 return _call_claude(prompt)


def _classify_sensitivity(findings: dict) -> dict:
 """Classify all findings by sensitivity level."""
 classified = {
 "critical": [],
 "high": [],
 "medium": [],
 "low": []
 }

 stage5 = findings.get("stage5", {})
 secrets = stage5.get("secrets_found", {})

 critical_types = [
 "aws_access_key", "aws_secret_key",
 "private_key", "stripe_secret", "database_url"
 ]
 high_types = [
 "github_token", "google_api_key",
 "jwt_token", "bearer_token", "api_key_generic"
 ]

 for stype, matches in secrets.items():
 for match in matches:
 entry = f"{stype}: [REDACTED]"
 if stype in critical_types:
 classified["critical"].append(entry)
 elif stype in high_types:
 classified["high"].append(entry)
 else:
 classified["medium"].append(entry)

 # Breaches are always high
 breaches = findings.get("stage8", {}).get("breaches_found", [])
 for breach in breaches:
 classified["high"].append(f"breach: {breach}")

 return classified


def run(target: str, config: dict) -> dict:
 """Stage 9 entry point."""
 log.info(f"{'='*60}")
 log.info(f"Stage 9 — AI Enrichment & Intelligence Synthesis")
 log.info(f"Target: {target}")

 all_findings = config.get("all_stage_findings", {})

 findings = {
 "stage": 9,
 "name": "AI_ENRICHMENT",
 "target": target,
 "timestamp": datetime.utcnow().isoformat(),
 "tools_invoked": ["claude-sonnet"],
 "sensitivity_classifications": {},
 "intelligence_summary": "",
 "attack_surface_score": 0,
 "recommendations": []
 }

 # Sensitivity classification
 classified = _classify_sensitivity(all_findings)
 findings["sensitivity_classifications"] = classified

 log.info(
 f"Classified — Critical: {len(classified['critical'])}, "
 f"High: {len(classified['high'])}, "
 f"Medium: {len(classified['medium'])}"
 )

 # AI synthesis
 if ANTHROPIC_API_KEY or OPENROUTER_API_KEY:
 synthesis = _synthesize_findings(target, all_findings)
 findings["intelligence_summary"] = synthesis
 log.info("AI synthesis complete")
 else:
 log.warning("No AI API key configured — skipping synthesis")
 findings["intelligence_summary"] = (
 "AI synthesis unavailable — "
 "set ANTHROPIC_API_KEY or OPENROUTER_API_KEY"
 )

 log.info("Stage 9 complete")
 return findings
