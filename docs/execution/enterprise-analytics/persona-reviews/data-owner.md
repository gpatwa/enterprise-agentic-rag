Status: AI persona advisory review (data owner / steward). Not an approval, certification, or human sign-off.

Reviewer: an AI model acting as a data owner / analytics data steward, on 2026-10-15. Nothing here fills the `definitions_owner` or
`results_owner` fields in `m7/corpus-approval.proposed.json`, changes any threshold, or certifies any contract. All recommendations are for a
named human owner to accept, change, or reject.

Inputs read: `ADS-070-reference-corpus.md`, `reference_stack/m7/corpus-v1.json`, `reference_stack/m7/corpus-approval.proposed.json`,
`reference_stack/m7_corpus.py`, `reference_stack/fakes.py` (scripted model and seed SQL), `reference_stack/golden.py` (grader),
`app/runtime/intent_echo.py`, `semantic_registry/contracts/*.json`, `packages/platform_contracts/semantic.py`, `ADS-067`, `ADS-073`,
`ADS-078`, `M7-hardening.md`, migration `0012_durable_run_material.py`, and the M1 entries in `agentic-data-stack-program.yaml`.

## Summary

- **Numbers: no wrong value.** I recomputed every expected row of all 60 answer cases in plain Python from the seed formula, without
  importing `m7_corpus`. All 60 match in value and column count. The corpus file's SHA-256 matches the pinned digest
  (`d0d2cce4...6bf76747`).
- **Meaning: one wrong expectation and one inconsistent definition.**
  - A043 ("Revenue by month, oldest to newest") expects the newest month first. The grader compares rows in order, so the question asks
    for one order and the expectation encodes the other.
  - The word "revenue" means two things in this corpus. "Total revenue" includes refunded orders (5,050). "Monthly revenue" silently
    filters to `status = paid`, so the three months add up to 4,000. The certified contract has no such filter. The filter comes from the
    scripted model, and the intent-echo check does not catch it because it does not require filters to be named in the question. The
    oracle encodes the same choice, so it is independent in **arithmetic** but not in **definition**.
- **Other risks to the definition:**
  - Month buckets depend on time zone. Order 72 is at exactly `2024-03-01 00:00`.
  - Questions with "trend" or "month over month" are sorted by value, not by time.
  - "Revenue for refunded orders" calls refunded money revenue.
  - Several P0 cases differ only in case or punctuation, which inflates the P0 count.
- **The 30 "customer-style" P0 questions are reference phrasings, not customer questions.** ADS-070 says so too. I drafted 25 realistic
  replacements below. They are drafts for a real data owner to replace.
- **Recommendations (advisory):**
  - `min_cohort` by classification: public off, internal off with an exception rule, confidential 10, restricted 25. Restricted data also
    needs per-person query auditing before onboarding.
  - Retention: policy values 7 days after a run ends; plans and result links 30 days after a run ends; legal hold overrides; tenant
    offboarding purges at once.
- **M1 semantic certification is not done in a sense that would hold up for real data.** `sales-core-v1.json` says
  `lifecycle: certified`, but it has no definition text, policies, classifications, currency, time zone, status domain, or recorded
  certifier. The manifest's M1 gate record explicitly does not certify any contract. A checklist follows.

## Results-owner check (method and outcome)

### Method

1. I hashed `corpus-v1.json` and compared the hash to `corpus_sha256` in the approval file. They match.
2. I wrote my own oracle in a scratch script and ran it with `python3 -I` from outside the repository. It does not import `m7_corpus` or
   `app`. It uses only the seed string: `i = 1..100`, `amount = i`, `status = refunded iff i % 5 == 0`,
   `created_at = 2024-01-01 00:00 + 20h * i`. This matches `fakes.SEED_SQL`.
3. I computed each intent from first principles, then compared each case two ways: as an unordered set (are the values right?) and as
   an ordered list (is the order right?). The ordered comparison matters because `golden._answer_case` checks `rows == expected` in order.

### Recomputed values

| Intent | Recomputed (my oracle) | Corpus | Value match |
|---|---|---|---|
| total | 5050 | 5050 | yes |
| by_status | paid 4000, refunded 1050 | same, desc by value | yes |
| monthly_paid | Jan 563, Feb 1468, Mar 1969 | same | yes |
| monthly_all | Jan 703, Feb 1853, Mar 2494 | same | yes |
| refunded | refunded 1050 | same | yes |
| top_status | paid 4000 | same | yes |

Cross-checks:

- Order counts by month are 37 / 34 / 29, with 7 / 7 / 6 refunded in each month.
- The first order is at 2024-01-01 20:00 and the last at 2024-03-24 08:00. February 2024 has 29 days, and the arithmetic accounts for
  it.
- Gross revenue minus refunded revenue equals paid revenue in every month: 703 − 140 = 563, 1853 − 385 = 1468, 2494 − 525 = 1969.

### Outcome

- **0 of 60 answer cases have a wrong value or column count.**
- **Every monthly case lists months by descending revenue (March, February, January).** The corpus never asks for a chronological
  order. Revenue happens to rise every month in this seed, so descending by value equals newest first. That is a coincidence of the
  seed, not a rule.
- **A043 "Revenue by month, oldest to newest": wrong expectation for its question.** The question asks for January first. The
  expectation is March first, and the ordered grader rewards the order the question did not ask for. Fix one of two ways: make the
  expectation chronological and the intent sort by `created_at asc`, or drop the "oldest to newest" wording. Either change alters the
  digest and needs new approvals.
- **A035 "Give me the monthly revenue trend", A042 "How did monthly revenue trend", A038 "What is revenue month over month":** a reader
  expects these in time order. "Month over month" usually means the change between months, which the contract cannot compute. The
  values are right, but the presentation is misleading. I flag these but do not count them as wrong.
- **The oracle shares a definitional assumption with the system under test.** Both `expected("monthly_paid")` and
  `ScriptedIntentClient` apply `status = paid` to monthly questions. A value check therefore cannot detect whether that filter is right.
  Only the definition owner can decide that (see below).
- **Formatting:** expectations are strings such as `"5050"`, while the seed column is `DECIMAL(12,2)`. The grader compares cell strings
  exactly. The results owner should confirm the canonical numeric rendering (scale, trailing zeros, currency), so that a real warehouse
  returning `5050.00` is not graded as wrong, and a truncated value is not graded as right.

## Definition-owner check

The certified contract `sales-core` v1 defines:

- `revenue = sum(orders.amount)`, at order grain, with no required filters.
- Dimension `status` (categorical) and dimension `created_at` (temporal).
- No policies, no field classifications (so all fields default to `internal`), no currency, and no description of what `amount` is.

### Findings, most important first

1. **Revenue is gross in one place and net in another (high).**
   - Total, by-status, and monthly-all use the contract as written. Refunded orders count as revenue, giving 5,050.
   - The 14 `monthly_paid` cases, eight of them P0, add `status = paid`, giving 4,000 across the three months.
   - A user who asks "Total revenue" and then "Monthly revenue" gets totals that do not reconcile.
   - The filter is not in the contract: it is neither a `required_filter_ids` entry nor a named `SemanticFilter`. The user never asked
     for it, and intent-echo does not require filters to be named in the question.
   - For real data this would be a silent definition change. The owner must decide whether revenue includes refunded orders. Then:
     - If revenue is net, put the exclusion in the contract as a required filter, so every revenue question applies it.
     - If revenue is gross, remove the paid filter from monthly questions, and add a separately named metric such as `paid_revenue` or
       `net_revenue` for the paid-only view.
   - I would also extend intent-echo, or the evidence display, so that any filter not named in the question is shown to the user.
2. **"Revenue for refunded orders" (A051–A055) treats refunded money as revenue (medium).** A finance owner would call this "refunded
   amount" or "value of refunded orders". The contract also cannot say whether a refund is always the full order amount: there is no
   refund amount field and no partial-refund status.
3. **Month boundaries depend on the time zone (medium).**
   - Order 72 is at exactly 2024-03-01 00:00. Order 38 is at 2024-02-01 16:00.
   - With the UTC session that ADS-067 F-06 pinned, the monthly totals are as expected.
   - On a US-Pacific business calendar (UTC−8), order 72 moves to February:
     - All statuses: Feb 1925, Mar 2422, instead of 1853 and 2494.
     - Paid only: Feb 1540, Mar 1897.
   - The contract does not state a reporting time zone or fiscal calendar. The scripted model's range
     `2024-01-01T00:00:00Z .. 2024-03-31T23:59:59Z` also contains an implicit Jan–Mar window and an inclusive end second. A real question
     such as "Monthly revenue" needs a decided default window.
4. **The order of results is part of the expectation but not part of the question (medium).** See A043 / A035 / A038 / A042 above. The
   intent schema supports `sort` by dimension ascending, so time-series questions should sort by time.
5. **`created_at` is the only date (medium).** Recognised revenue is usually dated by payment, shipment, or recognition date, not
   order creation. The definition owner should state that the reporting date is the order creation date, or add the right date.
6. **Ties in "Top revenue status" are undefined (low).** With two statuses and very different totals this does not matter here. It will
   matter on real data with `limit 1`, which needs a deterministic tie-break.
7. **P0 inflation (low).** Of the 30 P0 cases:
   - Six are case and punctuation variants of two strings: "Revenue for refunded orders" ×3 and "Top revenue status" ×3.
   - Several `total` P0s are near-identical.
   - The P0 set has about 26 distinct phrasings and 6 distinct intents. The six `monthly_all` cases are all one string.
   - This measures normalisation, not coverage.
8. **Clarify cases are a harness mechanism, not real ambiguity (informational).** In the ambiguous stack, every grouping, including
   `status`, is renamed to the label `time`. So "Revenue by status" becomes a clarify case for an artificial reason. That is fine for
   testing the clarify path, but these cases say nothing about whether real questions are ambiguous.
9. **Refusal, policy, and tenant cases look appropriate.** "Forecast next year's revenue" and "Predict churn" are correctly
   unsupported, because the contract has no forecasting. The PII and DDL requests are correctly refused. One gap: none of the refusals is
   a *near miss on the contract*, such as "profit", "order count", or "average order value". These are the questions real users will ask
   of this contract. ADS-073 covers near misses separately.

### Honesty note

The 30 "customer-style" P0 questions are phrasings of six reference intents, written to match a scripted keyword model. They are not
questions collected from customers or business users, and they do not show what real users will ask. ADS-070 already says this. The
drafts below are also not real customer questions. They are a steward's guess at realistic ones, to be replaced by the data owner.

## Draft P0 questions

**DRAFT — written by an AI persona, not collected from customers. A real data owner must replace or confirm each one and approve the
expected results independently.**

Each question is answerable by `sales-core` v1: the `revenue` metric, grouping by `status` and/or `created_at` at
day/week/month/quarter/year, filters on `status`, and a time range. Where an indicative value is given, it assumes **gross revenue
(refunds included), UTC, ISO weeks starting Monday, and an inclusive date range**. Each of those assumptions is an open decision, and
the values are not expected results until a results owner approves them.

| # | Draft question | Intent shape | Indicative value (assumptions above) | Decision it exercises |
|---|---|---|---|---|
| 1 | What was our total revenue for Q1 2024? | total, range Jan–Mar | 5050 | gross vs net |
| 2 | How much revenue did we book in February 2024? | total, Feb range | 1853 | month boundary, time zone |
| 3 | Show monthly revenue for Q1 2024 in date order. | month, sort time asc | Jan 703, Feb 1853, Mar 2494 | chronological order |
| 4 | Which month in Q1 2024 had the highest revenue? | month, sort value desc, limit 1 | Mar 2494 | tie-break |
| 5 | What was revenue from paid orders in January 2024? | total, status=paid, Jan | 563 | paid vs gross naming |
| 6 | What is the total value of refunded orders in Q1 2024? | total, status=refunded | 1050 | "refunded amount" wording |
| 7 | Break down March 2024 revenue by order status. | status, Mar range | paid 1969, refunded 525 | status domain |
| 8 | Show revenue by month and status for Q1 2024. | month × status | 6 rows (e.g. Feb paid 1468, Feb refunded 385) | two-dimension grouping allowed? |
| 9 | What was revenue excluding refunded orders, by month? | month, status≠refunded | Jan 563, Feb 1468, Mar 1969 | net definition |
| 10 | How did paid and refunded revenue compare in February 2024? | status, Feb | paid 1468, refunded 385 | comparison without ratio |
| 11 | Show weekly revenue for February 2024. | week, Feb | weeks of Jan 29 (158 Feb-only), Feb 5 414, Feb 12 436, Feb 19 567, Feb 26 278 | partial weeks at month edges |
| 12 | What was revenue in the week starting 12 February 2024? | total, 7-day range | 436 | week start day |
| 13 | Show daily revenue for the first week of January 2024. | day, Jan 1–7 | 1, 2, 3, 4, 5, 13, 8 | small cohorts (1–2 orders/day) |
| 14 | What was revenue on 29 February 2024? | total, one day | 71 | leap day, small cohort |
| 15 | What was revenue on 1 March 2024? | total, one day | 145 (UTC) | midnight boundary order |
| 16 | What was revenue between 1 January and 15 February 2024? | total, custom range | 1540 | inclusive end date |
| 17 | What is year-to-date revenue as of 31 March 2024? | total, YTD | 5050 | "as of" date semantics |
| 18 | Show quarterly revenue for 2024. | quarter | Q1 5050 | empty future quarters shown or not |
| 19 | Which order status brings in the most revenue? | status, limit 1 | paid 4000 | tie-break |
| 20 | How much refunded order value did we have each month? | month, status=refunded | Jan 140, Feb 385, Mar 525 | refund naming |
| 21 | What was revenue last month? | total, relative range | depends on run date | relative dates, business calendar |
| 22 | Show revenue by month for paid orders, oldest first. | month, paid, asc | Jan 563, Feb 1468, Mar 1969 | sort direction |
| 23 | Compare revenue in March 2024 with February 2024. | month, Feb–Mar | Feb 1853, Mar 2494 (no computed delta) | contract has no change metric |
| 24 | What was revenue for the second half of January 2024? | total, Jan 16–31 | owner to compute | half-open vs inclusive ranges |
| 25 | Show revenue by status for orders created in Q1 2024. | status, Q1 | paid 4000, refunded 1050 | date basis is creation date |

Realistic questions that are deliberately **not** in the table, because this contract cannot answer them: order count, average order
value, refund rate (a ratio of two metrics, neither defined), revenue by customer, product, or region, profit or margin, and forecasts.
These belong in the abstention corpus.

## min_cohort and retention recommendations

### min_cohort by dataset sensitivity class (advisory)

The classes come from `classification` in `platform_contracts.semantic`: public, internal, confidential, restricted. Today `min_cohort`
is `HAVING COUNT(*) >= k`, which counts **rows**, not people.

| Class | Recommended `min_cohort` | Conditions |
|---|---|---|
| public | off (1) | Aggregates are publishable anyway. |
| internal (no person-linked dimensions) | off (1) by default; **5** if any certified dimension or filter can isolate a single person or counterparty (customer, employee, supplier) | `sales-core` as written (status, creation date) qualifies for off. Daily grouping gives 1–2 orders per bucket, so k = 5 would suppress almost all daily answers, which shows the usability cost. |
| confidential (commercially sensitive, or person-linked but not special-category) | **10** | Also refuse filters on entity keys (already enforced when on), and require a coarsest time grain (week or more) for person-linked datasets. |
| restricted (personal or special-category data, salaries, health, HR) | **25**, and **do not onboard** until per-person query auditing and differencing controls exist | Matches ADS-067's "no such dataset should be onboarded" until F-03 is decided. |

Caveats for the owner:

- **k on rows does not protect people when one person has many rows.** For person-linked data, k should count distinct entities, for
  example `COUNT(DISTINCT customer_id)`. That is a code change, not a configuration value.
- **`min_cohort` does not stop differencing.** Two large overlapping cohorts or time ranges can still reveal a small one. ADS-067
  found this with a 4950 vs 5050 probe. Thresholds alone are not enough for restricted data.
- **Values are per dataset, not per tenant.** The owner should record the chosen k in the contract or policy file, with a named
  approver.

### Retention for the durable run tables (advisory)

From M7-H1 and migration `0012`:

- `analytics_run_plans` holds SQL and bound parameters, which may include filter literals.
- `analytics_run_policy_values` holds filter literals and **identity claims**, which are personal data.
- `analytics_run_result_links` holds references only.
- None of them stores result rows. All are in backups, and none has a purge job.

| Table | Recommended rule | Reason |
|---|---|---|
| `analytics_run_policy_values` | Delete **7 days after the run reaches a terminal state**. Runs paused for human review keep the row until the review resolves or expires, then 7 days. | Needed only to resume an in-flight run. Holds identity claims, so minimise them. |
| `analytics_run_plans` | Delete **30 days after terminal state**, with the same rule for paused runs. | Supports incident investigation and re-execution while a question is fresh. The sealed evidence envelope, not the plan, is the long-lived record. |
| `analytics_run_result_links` | Delete with its plan (same 30 days). | References are meaningless without the plan. |
| All three | Purge at once on tenant offboarding or a valid erasure request. A **legal hold** overrides all deletion. | Standard data lifecycle duties. |
| Backups | Backup retention should be no longer than about 35 days, or the backups should be documented as holding these rows longer. A purge job does not reach existing backups. | Deletion in the database is not deletion everywhere. |

Before accepting this, the owner should confirm three things:

- Nothing re-runs a plan after the terminal state. Replay uses the stored outcome and fingerprint; the only re-run is `resume` while
  the run is in flight.
- The evidence and audit retention is set separately and is at least as long.
- 30 days covers the review queue's longest pause.

## Certification checklist

This is what M1 semantic certification should require **before any real data**, per contract version. None of it is done for
`sales-core` v1 beyond the structural items marked with a dagger (†).

**Ownership and record**

1. A named accountable person as definition owner, not just `team.data`, plus a named results owner who is not the person who
   implemented the contract.
2. A certification record in Git: certifier, date, contract version, digest, and evidence links. Today `lifecycle: certified` has no
   such record, and the manifest's M1 gate approval explicitly does not certify any contract.

**Metric definition**

3. Written business definition of `revenue`:
   - gross or net of refunds and cancellations;
   - tax, shipping, discounts, and partial refunds;
   - currency and FX treatment;
   - recognition date (creation, payment, or shipment).
4. If revenue is net, the exclusion is a contract `required_filter_ids` entry, not something a model adds. Variants such as paid or net
   revenue are separate named metrics.

**Fields and dimensions**

5. Grain and key verified on the real table: `orders.id` unique and not null (†grain declared; uniqueness not verified on real data).
6. Status domain enumerated (allowed values, meaning, how new values are handled) and tested against the source.
7. Reporting time zone, fiscal calendar, week start, and default time window stated. Month and day boundaries tested with a row at
   exactly midnight.
8. Each field classified (public / internal / confidential / restricted). Policies with allowed purposes, tenant and row filters, and
   `min_cohort` per classification. `sales-core` has no policies in the registry file.

**Data quality and reconciliation**

9. Data quality tests: amount not null and non-negative (or refund sign convention documented), freshness and late-arriving data SLA,
   duplicate detection.
10. Reconciliation: `revenue` by month matches the finance system of record within an agreed tolerance for at least three closed
    periods, signed off by the results owner.

**Language and corpus**

11. Glossary: approved synonyms and aliases (what "sales", "bookings", "income" map to) and terms that must **not** map to revenue,
    such as "profit" and "margin". This feeds intent-echo.
12. A real P0 question set of 25–50 questions from actual users, with expected results approved independently by the definition owner
    and the results owner, pinned by digest. The current corpus approval stays `null` until then.

**Lifecycle and verification**

13. Lineage to source (OpenMetadata/dbt mapping) checked for the physical table and columns (†mapping code exists; not validated live).
14. Change control: what triggers re-certification (a definition, source, or policy change), the deprecation path, and a version bump
    rule.
15. Evidence that the certification gate works for this contract: a draft is refused, and a certified contract is resolved only for
    its own tenant (†shown locally in ADS-078 for a sandbox copy).

## Questions for the human owner

1. Does revenue include refunded orders? If not, should the exclusion become a required filter on the certified metric? Should the
   paid-only monthly filter in the scripted model and the oracle then become the rule, or be removed?
2. Should A043 be fixed, and time-series questions in general sort chronologically? Either change alters the corpus digest and needs
   both approvals again.
3. Which reporting time zone, fiscal calendar, and week start apply? What default window applies when a question gives no dates?
4. Is `created_at` the right date for revenue, or is a payment or recognition date needed?
5. Is a refund always the full order amount? What should "refunded" questions be called in user-facing answers?
6. Who are the named definition owner and results owner for `sales-core`? Will they write the real 25–50 P0 questions?
7. Do you accept the proposed `min_cohort` values by classification? Should k count distinct entities for person-linked data, which is
   a code change?
8. Do you accept the retention rule (7 / 30 days, legal hold, offboarding purge)? What backup retention applies?
9. What reconciliation tolerance against the finance system would you accept for certification, and over how many periods?
10. Should intent-echo or the evidence view be extended to show any filter the user did not ask for?
