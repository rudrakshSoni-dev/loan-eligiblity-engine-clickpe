"""Measure what asking the LLM about one applicant at a time costs, from real Groq calls.

Each sampled borderline pair becomes its own request using the Stage 3 system prompt taken
from the exported Workflow B and the same strict response schema, with a single applicant
instead of a packed cohort. Token counts and latencies come from the Groq responses.
"""

import argparse
import ast
import json
import logging
import os
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-120b"
WORKFLOW_B = Path("n8n/workflows/workflow-b-matching.json")
STAGE3_NODE = "Stage 3 · Build LLM requests"
COHORT_ID = "c01"
COMPLETION_TOKENS = 700
REQUEST_TIMEOUT_SECONDS = 30
PAUSE_SECONDS = 2.5
SYSTEM_PROMPT_PATTERN = re.compile(r"const SYSTEM_PROMPT = (\[.*?\])\.join\('\\n'\);", re.DOTALL)

logger = logging.getLogger("measure_naive_llm")


def stage3_system_prompt(workflow_path: Path) -> str:
    """Return the Stage 3 system prompt exactly as the exported workflow sends it."""
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    nodes = workflow[0]["nodes"] if isinstance(workflow, list) else workflow["nodes"]
    code = next(n["parameters"]["jsCode"] for n in nodes if n["name"] == STAGE3_NODE)
    match = SYSTEM_PROMPT_PATTERN.search(code)
    if match is None:
        raise ValueError(f"no SYSTEM_PROMPT in node {STAGE3_NODE!r}")
    return "\n".join(ast.literal_eval(match.group(1)))


def shortfall_text(pair: dict[str, Any]) -> str:
    """Describe the criterion this applicant is within 5% of failing, in Stage 3's wording."""
    parts = []
    near_miss = pair["near_miss_criteria"]
    if "min_credit_score" in near_miss:
        parts.append(
            f"credit score {pair['credit_score']}, below the lender's figure of "
            f"{pair['min_credit_score']} (worst value {pair['credit_score']})"
        )
    if "max_credit_score" in near_miss:
        parts.append(
            f"credit score {pair['credit_score']}, above the lender's figure of "
            f"{pair['max_credit_score']} (worst value {pair['credit_score']})"
        )
    if "min_monthly_income" in near_miss:
        parts.append(
            f"net monthly income Rs {pair['monthly_income']:,}, below the lender's figure of "
            f"Rs {pair['min_monthly_income']:,} (worst value Rs {pair['monthly_income']:,})"
        )
    return "; and ".join(parts)


def build_request(pair: dict[str, Any], system_prompt: str) -> dict[str, Any]:
    """One Groq request asking about exactly one applicant."""
    user_content = "\n".join(
        [
            f"Lender: {pair['source']}",
            f"Product: {pair['product_name']}",
            "Lender eligibility text:",
            pair["criteria_text"],
            "",
            "Cohorts:",
            f"{COHORT_ID}: {pair['employment_status']} applicants; {shortfall_text(pair)}.",
        ]
    )
    schema = {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "cohort_id": {"type": "string", "enum": [COHORT_ID]},
                        "eligible": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["cohort_id", "eligible", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["verdicts"],
        "additionalProperties": False,
    }
    return {
        "model": MODEL,
        "temperature": 0,
        "reasoning_effort": "low",
        "include_reasoning": False,
        "max_completion_tokens": COMPLETION_TOKENS,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "cohort_verdicts", "strict": True, "schema": schema},
        },
    }


def call_groq(request: dict[str, Any], api_key: str) -> dict[str, int]:
    """Send one request and return its measured prompt tokens, completion tokens, latency."""
    http_request = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(request).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "clickpe-benchmark/1.0",
        },
    )
    started = time.monotonic()
    with urllib.request.urlopen(http_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        body = json.load(response)
    usage = body["usage"]
    return {
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "latency_ms": round((time.monotonic() - started) * 1000),
    }


def summarise(calls: list[dict[str, int]]) -> dict[str, float]:
    """Average the measured calls."""
    return {
        "calls": len(calls),
        "mean_prompt_tokens": statistics.mean(c["prompt_tokens"] for c in calls),
        "mean_completion_tokens": statistics.mean(c["completion_tokens"] for c in calls),
        "mean_total_tokens": statistics.mean(
            c["prompt_tokens"] + c["completion_tokens"] for c in calls
        ),
        "mean_latency_ms": statistics.mean(c["latency_ms"] for c in calls),
    }


def main(argv: list[str]) -> int:
    """Read the sampled pairs, call Groq once per pair and log the summary."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("pairs", type=Path, help="JSON array of sampled borderline pairs")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    api_key = os.environ["GROQ_API_KEY"]
    system_prompt = stage3_system_prompt(WORKFLOW_B)
    pairs = json.loads(args.pairs.read_text(encoding="utf-8"))[: args.limit]
    calls = []
    for pair in pairs:
        calls.append(call_groq(build_request(pair, system_prompt), api_key))
        logger.info("call %d %s", len(calls), json.dumps(calls[-1]))
        time.sleep(PAUSE_SECONDS)
    logger.info("summary %s", json.dumps(summarise(calls)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
