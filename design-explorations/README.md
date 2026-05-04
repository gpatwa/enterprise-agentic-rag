# W0 Design Directions — Home Page

Five distinct visual directions for the Acme RAG Platform Home page, generated for stakeholder review and selection.

## How to view

```bash
cd design-explorations
open index.html       # gallery — all 5 in iframes side-by-side
# or open any individual file:
open 01-linear-calm/home.html
```

Each prototype is a single-file HTML using **Tailwind via CDN** + **Lucide icons** + **mock data**. No build step needed. They render the same DOM structure but diverge on every visual axis.

## The six directions

| # | Direction | Aesthetic | Best for | Risk |
|---|-----------|-----------|----------|------|
| 1 | **Linear Calm** | Dark, minimal, indigo accent. Generous whitespace. | Engineers, ICs, dev-tool buyers | May feel "cold" to non-technical execs |
| 2 | **Notion Workspace** | Light, paper-like, emoji nav. Block-based. | Knowledge workers, hybrid teams | Less "AI-product" looking |
| 3 | **Bloomberg Terminal** | Dark, dense, monospace, multi-panel. | Quant analysts, finance, ops centers | Intimidating for casual users |
| 4 | **Wisdom Premium** | Light, soft gradients, big numbers. Stripe/Vercel feel. | Execs, board, sales demos | Could read as "marketing" not "tool" |
| 5 | **Anthropic Warm** | Cream paper, serif headings, terracotta accent. Claude.ai-inspired. | Conversational, accessible, brand-distinctive | Polarizing — people love or hate cream |
| **6** | **⭐ Calm Glass (RECOMMENDED)** | Dark + glassmorphism + indigo→cyan gradient + serif italic accent in hero | All audiences. Synthesis of Cube/Julius standards + Anthropic brand-distinctive moment | Glass blur perf on low-end devices (mitigation: `prefers-reduced-transparency`) |

## Why Direction 06 (recommended)

After auditing **Cube.dev**, **Hex.tech**, and **Julius.ai**, three patterns emerged for AI-data tools in 2026:

1. **Dark-first** — both Cube and Julius default dark; 82% of users prefer dark for AI-heavy sessions
2. **Glassmorphism panels** — Julius and modern AI products use translucent frosted layers
3. **Single bright accent** — Cube uses cyan, Hex uses purple, Julius indigo. Never multi-color.

Direction 06 takes the **dark-glass-single-accent foundation** that all three reference products share, then adds **one serif italic moment in the hero** as our brand-distinctive signature (inherited from Direction 05 — Anthropic Warm). This gets us the credibility of the category leaders + a recognizable touch that competitors don't have.

## Selection criteria (rank 1-5 each)

- [ ] **Trust at first glance** — does it look enterprise-grade in 5 seconds?
- [ ] **Information density** — can a power user see what they need without scrolling?
- [ ] **Emotional response** — calm, confident, premium?
- [ ] **Brand differentiation** — would we be mistaken for ChatGPT?
- [ ] **Mobile feasibility** — does the layout obviously translate to phone?
- [ ] **Build cost** — how custom is this? (lower = cheaper)

## Decision

Once a direction is chosen (or hybrid agreed), we:
1. Lock the tokens in `DESIGN.md`
2. Configure `tailwind.config.ts` to match
3. Begin W1 build with React + Vite + shadcn/ui scaffold

## Sample data used (consistent across all 5)

- **User:** Gopal (admin)
- **Tenant:** Acme Corp
- **Sources:** PostgreSQL Olist (1.5M rows, fresh), Qdrant Vector Docs (302 chunks, fresh), Neo4j Graph (2.4K nodes, 3h ago)
- **Knowledge:** 12 glossary terms, 8 business rules, 5 code contexts
- **Recent threads:** 3 examples (revenue investigation, Q1 board prep, payment methods)
- **Pinned questions:** 2 examples
- **Quick-start categories:** Revenue, Products, Reviews, Delivery
