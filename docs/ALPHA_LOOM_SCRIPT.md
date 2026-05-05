# Compass Alpha — Loom Walkthrough Script

**Target length: 5 minutes.** Read straight through; pauses are marked
with `[…]`. Designed for a recording where you screen-share Compass and
narrate as you click. Replace `https://alpha.compass.example.com` with
the actual deployed URL before recording.

---

## Pre-record checklist

- [ ] Run `make seed-alpha` against the alpha database (with `MCP_ENCRYPTION_KEY` set) so the home page is populated and a demo MCP connector is "Connected".
- [ ] Open three browser tabs side-by-side, in order:
  1. `https://alpha.compass.example.com/welcome` (the public landing — the "what is this" tab)
  2. `https://alpha.compass.example.com/` (the in-app Home page)
  3. `https://alpha.compass.example.com/sources` (Sources + App connectors)
- [ ] Make sure DevTools are closed and the browser zoom is reset.
- [ ] Have a question typed-but-not-sent in your head: _"What was Q3 revenue by region?"_
- [ ] Optional but recommended: prepend the Loom title with `[Internal] Compass alpha — 5-min walkthrough — please leave feedback in #compass-alpha`.

---

## Script

### 1. Open — what this is and why we want feedback (~30s)

> "Hi team — quick five-minute walkthrough of Compass alpha. **Compass is the enterprise data agent we've been building.** The pitch is on the screen: _Ask. Verify. Act._ — any employee can ask company questions across our warehouse, docs, code, and SaaS tools, and get answers anyone can verify and act on, with a full audit trail.
>
> This is internal-only right now. We're shipping it to you for two reasons: (1) we want to find what's broken before we open it to customers, and (2) we want your feedback on the UX. Please be brutal. There's a feedback channel I'll point at the end."

`[switch from /welcome tab to /]`

### 2. The "Ask" surface — the home page (~75s)

> "Here's the home page. The top-of-fold is the ask box — type any question you'd ask a Slack bot or a teammate.
>
> Below the ask box: pinned questions (frequently-asked metrics you've saved), recent threads (your conversation history), and quick-start categories.
>
> Let me ask one — _'What was Q3 revenue by region?'_"

`[type, hit enter, let the answer stream]`

> "Notice three things while it streams:
>
> One — the **pipeline status** at the top of the answer card shows what the agent is doing: planning, retrieving, executing SQL, writing the answer.
>
> Two — when the SQL runs, you see the **actual SQL** rendered above the result. We didn't make this up — Compass generated it, and you can run it in your warehouse to verify.
>
> Three — the **answer cites its sources**. Click a citation — it pops up the underlying document chunk or row. Trust on by default."

### 3. Verify and follow up (~45s)

> "On the right rail you'll see the **Sources & Reasoning** trace. Every step the planner took is here, expandable, exportable. Auditable.
>
> Below the answer there are **follow-up suggestions** the agent thinks you might want next — click one to ask it without typing.
>
> If this answer is something I'd ask weekly, I can hit _Save_ to pin it as a saved question. From there it's two clicks to re-run, or to drop it into a dashboard."

`[click 'Open in thread' on the answer card]`

> "Every conversation is a thread you can come back to. Threads are tenant-isolated, so my colleague Bob doesn't see mine."

### 4. App connectors — the Phase 5 work (~60s)

`[switch to /sources tab]`

> "Head to Sources. Top half is our **infrastructure** — Postgres, the vector index, the graph store. Live health probes; you can see the freshness right there.
>
> Bottom half is the new piece: **App connectors.**
>
> This is the MCP integration — Model Context Protocol, Anthropic's open standard for plugging LLMs into SaaS data. Slack, GitHub, Notion, Drive, all here.
>
> GitHub is wired up as a demo — you can see the green Connected badge. To enable a new one, click Connect — _[click Connect on Notion]_ — paste a token, hit Connect. The form fields are generated from the catalog metadata, so adding a new connector type is zero frontend work for the team.
>
> Drive is the one you'll see marked as a Phase-4 placeholder — that needs the OAuth flow which ships next."

`[close the dialog]`

### 5. Mobile — same app, no separate codebase (~20s)

`[open Chrome DevTools → toggle device toolbar → iPhone 14]`

> "One more thing — the entire app is mobile-first. Same React app, same routes, same data, no separate iOS or Android. Tap targets are 48 pixels minimum. The full demo I just showed you works the same on a phone, including the App connectors section."

`[close DevTools]`

### 6. How to give feedback (~30s)

> "When you find something — and you will — please flag it. Three ways:
>
> One — **#compass-alpha Slack channel** for anything broken or confusing.
>
> Two — **the Send Feedback button** in the top right of the app — it goes to the same Slack channel, but with the URL and a screenshot pre-filled, which saves you a step.
>
> Three — **questions that didn't work**. If you asked something you'd expect Compass to answer and it gave you garbage or punted, those are gold for us. Paste the question into the channel verbatim."

### 7. Close (~10s)

> "That's it — five minutes. We'll iterate based on what you find. Thank you for trying it. The URL is in the channel pin."

---

## What to flag during the demo

If asked, here are the honest gaps to acknowledge upfront:

- **The GitHub connector uses a placeholder token** — you'll see "Connected" but actual GitHub tool calls would fail at first invocation. Real tokens go in next.
- **No Google Drive yet** (Phase 4 — OAuth2 flow under development).
- **No real Slack data yet** — that's the next demo enhancement.
- **The seed data is illustrative** — Q3 revenue numbers and the customer names are placeholder. When you connect to your warehouse the data will be real.
- **No real-time streaming** of typing indicators between users (single-user surface for alpha).

## Common stakeholder questions + answers

| Question | Answer |
|---|---|
| Is my data leaving the building? | No. Tenant-isolated; LLM calls go through our routing layer. SOC 2 Type I in progress. |
| Can I use my own Slack token? | Yes — ask in #compass-alpha and we'll wire it up via the Sources page. |
| What's the difference vs ChatGPT? | Compass is enterprise-grounded — answers are tied to YOUR warehouse, docs, and SaaS. Every answer ships with citations and SQL. ChatGPT can't see your data. |
| How does it know our metric definitions? | The Knowledge tab — glossary, business rules, KPI definitions. The agent reads these into every answer. |
| Can it edit / write back? | Today: read-only. Action layer (open Jira tickets, update CRM under audit) is on the roadmap. |
| What about cost? | Internal cost ledger by tenant — you'll see your team's LLM usage in the admin tab once we wire it up. Not customer-facing yet. |
