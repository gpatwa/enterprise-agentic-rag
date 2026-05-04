# Compass — Design System

> Single source of truth for brand, tokens, components. Read by Claude Design, Claude Code, and humans.

---

## Brand

- **Product name:** **Compass**
- **One-liner:** Compass is the unified answer-and-action layer for enterprise data.
- **Tagline:** **Ask. Verify. Act.**
- **Sub-positioning:** Governed answers across warehouses, documents, code, and SaaS tools — with citations, SQL, lineage, permissions, and audit trails built into every response.
- **Voice:** Calm, precise, expert. No marketing fluff. No hype words. No emojis in body copy.
- **Audience:** Enterprise buyers — CFO/Finance, RevOps, Data leaders, Engineering, Security, and every employee.
- **Inspiration ladder:** Linear (calmness) → Notion (density) → Glean (trust) → Wisdom AI (agentic answers) → Cube (governance).

### The three modes (apply consistently across product + GTM)

1. **Ask** — every employee asks in plain language across data, docs, code, SaaS.
2. **Verify** — every answer ships with citations, SQL, glossary, lineage, freshness, confidence, permissions trail.
3. **Act** — governed execution back into the systems where work happens (reports, tickets, workflows, alerts) — under approval flows, RBAC, and audit.

### Competitive positioning sentence (use verbatim where possible)

> Glean searches. Cube governs metrics. Hex serves analysts. Julius analyzes files. **Compass is the governed layer where every employee can ask, verify, and act across enterprise data.**

### Copy do's and don'ts

| ✓ Do | ✗ Don't |
|------|---------|
| "governed answers" | "trustworthy AI" |
| "citations, SQL, lineage, audit" | "fully transparent" |
| "every employee" | "anyone" |
| "ask, verify, act" | "ask anything" (loses the verify/act distinction) |
| Specific numbers and concrete claims | "transformative", "revolutionary", "next-gen" |
| "Book a demo" / "Talk to sales" | "Get started in seconds" (under-positions enterprise) |

## Personality matrix

| Axis | Where we sit |
|------|--------------|
| Playful ←→ **Serious** | Serious-leaning |
| Casual ←→ **Professional** | Professional |
| Loud ←→ **Calm** | Calm |
| Sparse ←→ **Dense** | Calm-density (Notion-esque) |
| Generic ←→ **Distinctive** | Distinctive (won't be mistaken for ChatGPT) |

---

## Design Principles (non-negotiable)

1. **Answer-first** — first pixel below a question is the answer card, not chat history
2. **Trust visible** — sources, freshness, SQL, confidence always 1 click away
3. **Calm density** — show more without cognitive load
4. **Keyboard-first** — `⌘K` palette, `⌘/` focus input, `⌘.` follow-ups
5. **Just-in-time guidance** — never an empty state, always a next action
6. **Governance is design** — tenant, role, freshness shown as design elements
7. **Mobile-equal** — every surface works at 360px

---

## Color Tokens (HSL)

### Dark theme (default)

```css
--background:        222 47% 6%      /* near-black w/ cool blue */
--surface:           222 35% 11%     /* cards */
--surface-elevated:  222 28% 16%     /* popovers, modals */
--surface-muted:     222 22% 21%     /* input bg, subtle hovers */
--border:            222 20% 25%
--border-strong:     222 18% 35%
--ring:              250 80% 70%

--text-primary:      210 18% 92%
--text-secondary:    215 12% 65%
--text-muted:        215 10% 50%

--accent:            252 80% 68%     /* indigo-purple, primary */
--accent-fg:         0 0% 100%
--data-blue:         210 90% 65%     /* data scope chip + tables */
--knowledge-green:   158 60% 56%     /* citations, fresh sources */
--governance-amber:  35  85% 60%     /* warnings, stale data */
--destructive:       0   75% 60%     /* errors */
--success:           142 65% 50%
```

### Light theme (must support, not default)

```css
--background:        0 0% 100%
--surface:           240 10% 98%
--surface-elevated:  0 0% 100%
--surface-muted:     240 5% 96%
--border:            240 6% 90%
--border-strong:     240 6% 78%
--text-primary:      222 47% 11%
--text-secondary:    222 14% 35%
--text-muted:        215 10% 50%
/* Accents same hue, slightly darker */
```

---

## Typography

| Token | Value |
|-------|-------|
| `--font-sans` | `'Inter Variable', -apple-system, system-ui, sans-serif` |
| `--font-mono` | `'JetBrains Mono', 'SF Mono', 'Fira Code', monospace` |
| `--font-serif` | `'Tiempos Headline', 'Charter', Georgia, serif` (sparingly, hero only) |

### Scale (no in-between sizes)

| Class | Size / line-height | Use |
|-------|---------------------|-----|
| `text-xs` | 11px / 1.4 | Caption, badge |
| `text-sm` | 13px / 1.5 | **Body default** |
| `text-base` | 14px / 1.5 | Compact card titles |
| `text-md` | 16px / 1.4 | Section heads |
| `text-lg` | 18px / 1.3 | Page sub-heads |
| `text-xl` | 22px / 1.25 | Section heads, big number labels |
| `text-2xl` | 28px / 1.2 | Page heads, KPI numbers |
| `text-3xl` | 36px / 1.1 | Hero, dashboard hero KPI |

Body weight: **regular (400)**. Emphasis: **medium (500)**. Headings: **semibold (600)**. Bold (700) is rare.

---

## Spacing & Sizing

- **Base unit:** 4px
- **Scale:** 1 (4px), 2 (8px), 3 (12px), 4 (16px), 5 (20px), 6 (24px), 8 (32px), 12 (48px), 16 (64px)
- **Card padding:** 16-20px
- **Section gap (desktop):** 32px
- **Section gap (mobile):** 24px
- **Min touch target:** 44×44 (mobile-critical)

## Radius

| Token | Value | Use |
|-------|-------|-----|
| `--radius-sm` | 4px | Tags, badges, chips |
| `--radius-md` | 6px | Buttons, inputs |
| `--radius-lg` | 8px | Cards, panels |
| `--radius-xl` | 12px | Modals, sheets |
| `--radius-full` | 9999px | Avatars, pills |

## Borders & Shadows

- **Cards:** 1px border (`--border`), **no shadow**
- **Hover state:** Border brightens 1 step (`--border-strong`)
- **Popover:** 1px border + `shadow-sm`
- **Modal/Sheet:** No border, `shadow-xl`, backdrop blur 8px
- **Focus ring:** 2px `--ring` + 2px offset

---

## Components (shadcn baseline)

Use these copy-pasted into `frontend/src/components/ui/`:
`button`, `card`, `dialog`, `sheet`, `command`, `dropdown-menu`, `tabs`, `toast`, `tooltip`, `badge`, `separator`, `scroll-area`, `table`, `skeleton`, `input`, `textarea`, `select`, `avatar`, `popover`, `hover-card`, `accordion`, `progress`.

### Customization rules

- All buttons: `cursor-pointer`, `active:scale-[0.98]` for haptic feel, `focus-visible:ring-2`
- Card hover: border brightens, no shadow shift
- Modal/Sheet backdrop: `backdrop-blur-md bg-background/80`
- Skeletons: `animate-pulse` on `--surface-muted`

---

## Iconography

- **Library:** [Lucide React](https://lucide.dev) only. No emoji in chrome.
- **Size scale:** 14, 16, 18, 20 (no others)
- **Stroke:** 1.5px default (lighter than Lucide's 2px default — calmer feel)
- **Color:** `--text-secondary` default, `--text-primary` on hover

Emoji **is** allowed in user content (questions, document titles), never in product chrome.

---

## Motion

| Behavior | Duration / Easing |
|----------|---------------------|
| Hover state | 120ms `ease-out` |
| Press / scale | 80ms `ease-out` |
| Sheet/modal in | 240ms `cubic-bezier(0.16, 1, 0.3, 1)` (out-quint) |
| Sheet/modal out | 180ms `ease-in` |
| Skeleton pulse | 1.4s `ease-in-out` infinite |
| Streaming text fade | 80ms `ease-out` per token |

No animations >300ms. No bounce. No spring overshoots.

---

## Density modes

User-toggleable via `⌘,` settings:
- **Comfortable** (default): card padding 20px, section gap 32px
- **Compact**: card padding 12px, section gap 20px (for analysts who want more on screen)

---

## Accessibility

- Min contrast: 4.5:1 body, 3:1 large text (WCAG AA)
- All interactive elements keyboard-reachable, with visible focus
- Screen reader: every chart has `<title>` + `<desc>`, every table is `<caption>`-ed
- Reduced motion: honor `prefers-reduced-motion`
- Color is never the only signal (icons + text labels too)

---

## Anti-patterns (do NOT do)

- ❌ Drop shadows on cards (use border)
- ❌ Gradients in body content (only allowed in hero, sparingly)
- ❌ Round buttons or pills as primary CTAs (rectangles only)
- ❌ Emojis in chrome (icons only)
- ❌ Loading spinners (use skeletons)
- ❌ Bold headings >700 weight (looks shouty)
- ❌ Three-letter color words ("red", "green") in CSS — use tokens
- ❌ Bespoke one-off colors per feature — extend the token list instead

---

## Updating this document

When adding a token, add it here first, then to `tailwind.config.ts`. CI fails if tokens diverge.
