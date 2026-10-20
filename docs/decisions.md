# Design decisions

One section per decision: what was chosen, what was rejected, and why.
Every number here comes from a recorded command or console page, cited inline.

## LLM provider: Groq

**Choice.** Groq's OpenAI-compatible API (`https://api.groq.com/openai/v1/chat/completions`),
called from n8n through one reusable "LLM Gateway" sub-workflow with JSON mode,
`temperature: 0` and `reasoning_effort: "low"`.

**Rejected alternative.** Calling the LLM per (user, product) pair. The free-tier limits below
make that impossible at 10,000 users, which is why matching filters deterministically first
and only sends borderline cohorts to the LLM (Workflow B, stages 1–3).

### Models available to this key (2026-10-20)

`GET /openai/v1/models` returned these chat-capable models:
`openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b` (all 131,072-token context),
plus `allam-2-7b` (4,096 context). No Llama chat models are offered to this account.

### Chosen models

| Use | Model | Why |
|---|---|---|
| Workflow A structuring, Workflow B cohort judgment | `openai/gpt-oss-120b` | Largest model available; same rate limits as the 20b model, so there is no throughput reason to pick the smaller one. |
| Fallback on 429 / outage | `openai/gpt-oss-20b` | Groq limits are per model, so falling back gives a second, independent quota. |

### Free-tier limits (organization level, measured 2026-10-20)

Source: console.groq.com → Settings → Limits (screenshot by the user), cross-checked against the
`x-ratelimit-limit-*` response headers of a real request.

| Model | Requests/min | Requests/day | Tokens/min | Tokens/day |
|---|---|---|---|---|
| openai/gpt-oss-120b | 30 | 1,000 | 8,000 | 200,000 |
| openai/gpt-oss-20b | 30 | 1,000 | 8,000 | 200,000 |
| qwen/qwen3.8-27b | 30 | 1,000 | 8,000 | 200,000 |

Header check on `openai/gpt-oss-120b`: `x-ratelimit-limit-requests: 1000` (per day) and
`x-ratelimit-limit-tokens: 8000` (per minute), matching the console.

### Verification request and token cost

Same prompt (extract income and rate range from one sentence of loan text) on 2026-10-20:

| Model | `reasoning_effort` | HTTP | Latency | Prompt tok | Completion tok | Output |
|---|---|---|---|---|---|---|
| gpt-oss-120b | default | 200 | 0.71 s | 154 | 153 | `{"min_monthly_income":25000,"interest_rate_min":10.5,"interest_rate_max":24}` |
| gpt-oss-20b | default | 200 | 0.74 s | 154 | 191 | same JSON |
| gpt-oss-120b | low | 200 | 0.64 s | 154 | 79 | same JSON |

gpt-oss models spend completion tokens on hidden reasoning, so the JSON itself is a small part
of what is billed against the limits. `reasoning_effort: "low"` halved completion tokens here
with identical output, so it is the gateway default.

### What the limits mean for the design

- **Which per-minute limit binds depends on call size.** 8,000 tokens ÷ 30 requests ≈ 267
  tokens per call is the crossover. The ~233-token test call is limited by requests (30/min),
  but real prompts (product text, several cohorts per request) will be larger, so in practice
  tokens/min binds. The gateway must therefore retry 429s with a wait (honouring
  `retry-after`) rather than assume a fixed call rate.
- **1,000 requests/day** caps the whole system. Calling the LLM on every pair of
  10,000 users × even 5 products = 50,000 calls would take 50 days of quota. Cohort batching
  in Workflow B stage 3 is therefore a requirement, not an optimisation.
- **Change detection in Workflow A** matters for the same reason: an unchanged crawl page must cost
  zero calls.
- Measured pipeline numbers will go in `scripts/benchmark.md` once the benchmark is run; none are claimed here.
