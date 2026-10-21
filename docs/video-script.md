# Video script

Target length 8:45 (limit 9:00). Narration is written at about 140 words a minute, so each segment's word count matches its time box. Read it aloud once with a timer before recording: if a segment runs long, cut the last sentence of that segment, never speed up.

| # | Segment | Time box | Running |
|---|---|---|---|
| 1 | Problem and architecture | 1:00 | 1:00 |
| 2 | Ingestion: why presigned POST and SQS | 1:00 | 2:00 |
| 3 | Workflow A, node by node | 1:30 | 3:30 |
| 4 | Workflow B: the funnel | 2:00 | 5:30 |
| 5 | Workflow C and the recipient guard | 0:45 | 6:15 |
| 6 | Live run from the UI | 1:30 | 7:45 |
| 7 | The email in the inbox | 0:30 | 8:15 |
| 8 | Wrap-up and trade-offs | 0:30 | 8:45 |

---

## Before you press record

Long steps are done now, so nothing waits on camera.

1. **State.** `dry_run` is `true` (check with `SELECT key, value FROM app_config;`). Leave it `true` for the whole recording.
2. **Tabs, in this order, all logged in and zoomed to 125%:**
   1. `docs/architecture.md` rendered on GitHub (or the README Architecture section).
   2. n8n editor at `http://localhost:5678` through the SSM port forward, Workflow A open.
   3. n8n Workflow B and Workflow C, each in its own tab.
   4. The UI at `http://localhost:8000` (`scripts/serve_ui.sh`) with nothing loaded.
   5. The UI at `http://localhost:8000/?batch_id=903ba6d4-d5a4-4cea-ab36-0f3ee7a4f170` (the first-run batch from T42), already finished, so the funnel is on screen.
   6. Gmail, search box already filled with `from:` the sender address, results visible.
   7. `data/users.csv` in the file picker's last-used folder.
3. **n8n executions to have open** (so you can click, not search): Workflow B execution 94 and Workflow C execution 95 (both from the T42 run). If they were pruned (168 h), open the newest B and C executions instead and read the numbers off the screen, not from this script.
4. **Phone on silent, notifications off, secrets hidden.** Open the `webhook-secret` and `groq-api` credentials only as screenshots, never live. Do not open a Workflow B execution's trigger node on camera: it stores the `X-Webhook-Secret` header in plain text (known issue, T43 and T45). Rotate the secret after the video.
5. **Rehearse the upload once** with `scripts/smoke_test.sh data/users.csv` so the S3 path is warm. It creates one extra no-op batch and no emails.

Why the live upload will show zeros: re-uploading the identical file is a no-op by design (0 inserted, 0 updated, so 0 users in the new batch, 0 pairs, 0 emails). That is the idempotency result and the script says so out loud. The real funnel is shown from the first-run batch in tab 5. If you want a true first run instead, repeat the T42 reset (backup, delete the data tables, fresh Workflow A run, clear `cohort_verdicts`) before recording; that is destructive and needs a fresh go.

---

## 1. Problem and architecture (1:00)

**Screen:** architecture diagram, full width. Point at each part as it is named.

> Lenders publish eligibility rules on their websites. An operations team has a CSV of ten thousand users. Who qualifies for which loan, and how do we tell them without ever emailing a real person?
>
> This is my answer, running on a real AWS account in Sydney. An admin uploads a CSV in a browser. It goes straight to S3, gets split into five-thousand-row chunks, and Lambda loads the chunks in parallel into a private PostgreSQL database. When the last chunk lands, exactly one webhook starts an n8n pipeline on an EC2 box. Workflow A reads lender websites. Workflow B matches users to products. Workflow C emails the matches, but only to my own test inboxes.
>
> Three constraints shaped everything: no NAT Gateway, no public database, and an LLM free tier that allows one thousand requests a day. I'll show how each one is handled.

**Check:** the words "private" (RDS box) and "no inbound rules" (EC2 box) are pointed at.

---

## 2. Ingestion: why presigned POST and SQS (1:00)

**Screen:** diagram, ingestion half. Then `serverless.yml` scrolled to the queue and event source mapping (`MaximumConcurrency: 3`).

> The browser uploads straight to S3 with a presigned POST. I chose POST over PUT because only a POST policy lets S3 itself enforce the exact key, the content type and a size range. On real S3, a valid file returns 204 and a twenty-two megabyte file is refused.
>
> S3 triggers a splitter Lambda. It uses the same CSV parser as the loader, so a quoted newline never breaks a chunk, and it emits one SQS message per five thousand rows with exact byte offsets. Each loader reads only its own range, so file size is bounded by S3, not by one Lambda's timeout. Failed chunks retry alone and reach a dead-letter queue after five tries.
>
> Concurrency is capped at three on the event source mapping. Reserved concurrency is impossible here: this account's limit is ten. The cap also protects RDS, which allows seventy-nine connections.

**Check:** say "measured" when you say seventy-nine; the number is from `SHOW max_connections`.

---

## 3. Workflow A, node by node (1:30)

**Screen:** n8n, Workflow A. Zoom so node names are readable. Move left to right.

> Workflow A runs daily at six IST, or manually. `Config · Crawl targets` holds the site list, so adding a lender is one line, not a new branch. `Fetch · Crawl page` makes a plain GET from the instance's own IP, with a real user agent, a thirty-second timeout and three tries. I checked each site's robots.txt and all three allow it.
>
> If a fetch fails, `Check · Page fetched OK` routes that one site to `Mark · Fetch failed` and the others carry on. I proved it: I made HDFC unreachable, and ICICI and IDFC FIRST still upserted.
>
> `Extract · Criteria blocks` and `Normalize · Criteria lines` keep only text that looks like a criterion, so a redesign gives `no_criteria_found`, not a silent empty result.
>
> Now the LLM. `LLM · Structure criteria (LLM Gateway)` calls one shared sub-workflow, the only thing that talks to Groq: strict JSON schema, temperature zero, it waits out a 429 and then falls back to the smaller model. `Coerce · Validate product` still rejects any number not in the source text, because a null would widen eligibility.
>
> `Upsert · loan_products + crawl_runs` is one statement. Products are never deleted: after three failed crawls a product goes inactive, and the next good crawl brings it back.

**Honesty line, say it here or in segment 8:** Workflow A calls Groq for every site on every run. Change detection, which would skip unchanged pages, is designed but not built.

---

## 4. Workflow B: the funnel (2:00)

**Screen:** n8n, Workflow B, then the UI tab 5 (`?batch_id=903ba6d4-…`) with the funnel and per-stage milliseconds. Return to n8n for the individual stages.

> This is where the work is. The naive design asks the LLM about every user and every product. Ten thousand users, three products: thirty thousand calls. Groq's free tier is one thousand a day. That is thirty days of quota for one upload. So I spend tokens only on what columns cannot say.
>
> *Show the funnel in the UI, read it left to right.* Thirty thousand pairs. Stage 1 is one SQL statement, `Stage 1 · SQL pre-filter`: income, score, age, employment, with NULL meaning no limit. Fourteen thousand one hundred sixty-five candidates in five hundred seventy-eight milliseconds. Pairs never leave Postgres; they are not n8n items.
>
> Stage 2 is deterministic rules. An EMI affordability check, capped at sixty-five percent of income, plus a classifier. Ten thousand four hundred five clear matches, fifteen hundred thirty-nine clear rejects, and two thousand two hundred twenty-one borderline. Those borderline pairs are the only ones a model may see.
>
> Stage 3 groups them into cohorts: by product, why it is borderline, employment, and a coarse band of the score or income. Twenty cohorts. Two Groq calls, thirty-five hundred tokens. Fourteen hundred thirty-six eligible, seven hundred eighty-five not. Final: eleven thousand eight hundred forty-one matches for six thousand seventeen users.
>
> Two details a reviewer will care about. Verdicts are cached by cohort and the product's content hash, so uploading the same file again makes zero calls, and a changed product invalidates its own verdicts. And a budget guard: if tokens run out, pairs are marked unresolved, never guessed.
>
> I also found a bug by timing nodes: stale planner statistics made cohort forming take sixteen seconds. An ANALYZE node brought it to one hundred sixty-eight milliseconds.

**Check:** the borderline count is 2,221, not "about two thousand". Per-pair asking for those alone would be 2,221 calls.

**Optional, only if time allows:** at 100,000 synthetic users the batch was matched 72.3 seconds after the upload started and Stage 3 made one Groq call (20 of 22 cohorts were cached). Say "warm cache" with it. Source: `scripts/benchmark.md`. Do not give a cold-cache figure for 100,000 users; none was measured.

---

## 5. Workflow C and the recipient guard (0:45)

**Screen:** n8n, Workflow C. Zoom on `Compose · Build emails`, then `Guard · Recipients are test inboxes`, then `Send · SES email`.

> Workflow C redirects every recipient, deterministically, to one of three verified test inboxes. The original address appears only in an "Intended for" line.
>
> A separate guard node re-reads the allowed list and throws on any other recipient, any cc, bcc or reply-to, or too many messages. I tested it with the original address: it blocked both messages, the batch failed, nothing was sent. SES is also in sandbox, so AWS would refuse them anyway.
>
> There is no SES key in n8n: the EC2 role assumes an SES-only role. Sending stays off unless `dry_run` is false, capped at five emails a run.

---

## 6. Live run from the UI (1:30)

**Screen:** UI tab 4 (empty). Start the upload at the first sentence. Keep the screen on the stage timeline.

> I choose the real ten-thousand-row file. The page checks extension, size and header before any batch exists.
>
> *Click upload.* Straight to S3 with a progress bar, then two chunks, ten thousand rows, zero rejected.
>
> This is the same file I uploaded before, so watch: zero inserted, zero updated. The upsert only rewrites a row whose data changed, so this batch introduces no users. Workflow B finds zero pairs and Workflow C sends zero emails. That is idempotency, proved with sending turned on.
>
> *Switch to tab 5, the first-run batch.* The first run of this file went from batch creation to notified in forty-one and a half seconds, browser upload included: ten thousand rows in, eleven thousand eight hundred forty-one matches, five emails sent.
>
> *Optional, only if on time:* a malformed file loads its one good row and stores ten rejects with line numbers.

**If the live upload misbehaves:** do not retry on camera. Cut to tab 5 and say "this is the recorded run from earlier". Never invent numbers.

---

## 7. The email in the inbox (0:30)

**Screen:** Gmail tab, the five test emails, then open one.

> Here are the emails from that first run: five, because the demo cap is five. The subject starts with TEST, and the body has an "Intended for" line with the original address. Gmail filed them in Spam. The likely cause is that the sender is a gmail.com address, so there is no DKIM alignment. I haven't verified that from the headers. The production fix, a domain identity with DKIM, is documented.

**Check:** use the T39 screenshot (`docs/screenshots/t39-gmail-drill-email-in-spam.png`) if Gmail is slow.

---

## 8. Wrap-up and trade-offs (0:30)

**Screen:** README, "Limitations" section.

> Plainly: ingestion, the three workflows, the funnel, the guard and the failure drills are built and measured. Designed but not built: change detection and the cost table. I have measured up to a hundred thousand users.
>
> Deliberate trade-offs: Sydney, because the account is locked there; Function URLs instead of API Gateway; a single-AZ database to stay on the cheap tier. The README has every command and every number.

---

## Number sources (check before recording)

Every number in the narration comes from a recorded run. If any of them changes, change the narration.

| Number said | Source |
|---|---|
| 1,000 requests a day, 30 days of quota for 30,000 calls | T04 limits, `docs/decisions.md` → "LLM provider: Groq" |
| 22 MB file rejected `EntityTooLarge`, valid file 204 | T15 |
| `max_connections` 79 | T11 |
| account Lambda concurrency 10, 100 unreserved needed | T10 (measured), README → Ingestion pattern |
| 2 chunks, 10,000 rows, 0 rejected | T42 |
| about 7 seconds to `processed` | T22: 6.9 s |
| 41.5 s from batch creation to `notified` | T42 |
| 30,000 → 14,165 (578 ms) | T33 |
| 10,405 / 1,539 / 2,221 | T34, T42 execution 94 |
| 20 cohorts, 2 calls, 3,536 tokens | T42 execution 94 |
| 1,436 eligible / 785 not | T42 execution 94 |
| 11,841 matches for 6,017 users | T36, T42 |
| 16 s to 168 ms after ANALYZE | T35 |
| 0 inserted / 0 updated, 0 emails on identical re-upload | T43(a) |
| malformed fixture: 1 loaded, 10 rejects with line numbers | T43(b) |
| HDFC unreachable, other two sites still upserted | T43(d) |
| guard blocked 2 of 2 messages, batch `failed` | T38 |
| 5 emails sent, 10 matches notified | T42 execution 95 |
| emails land in Spam | T39, T42 |

## Not to claim

- No cold-cache figure for 100,000 users (only the warm-cache run in `scripts/benchmark.md` exists), and nothing beyond 100,000 users.
- No dollar costs (T46 not written).
- No "security review done" (T45 not run).
- No "change detection" as built (T29). The LLM Gateway is built (T26); its 429 wait was seen live, but the 20b fallback only in a throwaway drill copy, so do not say a production run fell back. The error workflow is built (T25); do not say it catches errors a workflow handles itself. The DLQ alarm is built (T21) but has no notification target.
- No UI features beyond the deployed page: the grouped reject table and CSV download (T41) are built locally, not deployed.
