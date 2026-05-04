# Compass Frontend (W1)

Vite + React 18 + TypeScript + Tailwind + shadcn/ui scaffold for the Compass v2 product surface.

## Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Build | Vite 5 | Fast HMR, well-supported, ESM-native |
| Framework | React 18 | Industry standard, vast component ecosystem |
| Type system | TypeScript 5.6 strict | Catch errors at compile time |
| Styling | Tailwind 3 + CSS variables | Direct mapping to `/DESIGN.md` tokens |
| Components | shadcn/ui (Radix primitives) | Copy-paste, no version-lock dep, owns the code |
| Icons | lucide-react | Matches Direction 06 iconography |
| State | Local React state for now; TanStack Query in W2 | Simple first |

## First run

```bash
cd services/api/frontend
npm install
npm run dev          # → http://localhost:5173
```

The dev server proxies `/api/*` and `/auth/*` to FastAPI on `http://localhost:8080`. Start the backend first:

```bash
# in another terminal
cd services/api
uvicorn main:app --port 8080 --reload
```

The Home page falls back to a built-in mock dataset when the backend isn't reachable, so you can develop UI without the backend running.

## Build for production

```bash
npm run build        # → services/api/frontend/dist/
npm run preview      # serve the build locally for sanity check
```

After the build, FastAPI can mount `dist/` at `/v2/` (or replace `/static/` in W4 when we flip the feature flag).

## Project layout

```
src/
├── main.tsx                          # entry
├── App.tsx                           # routes (single page in W1)
├── index.css                         # Tailwind + token CSS variables
├── lib/
│   ├── utils.ts                      # cn() helper
│   └── api.ts                        # fetch wrapper (auth + base URL)
├── types/
│   └── index.ts                      # shared types matching backend response
├── components/
│   ├── ui/                           # shadcn primitives (button, card, badge, input)
│   ├── layout/
│   │   ├── AppShell.tsx              # 3-pane shell
│   │   ├── Sidebar.tsx               # left nav
│   │   ├── TopBar.tsx                # search + actions
│   │   └── RightRail.tsx             # sources + knowledge + governance
│   └── home/
│       ├── AskBox.tsx                # the ask textarea + scope chips
│       ├── QuickStart.tsx            # 4-card category grid
│       ├── Pinned.tsx                # saved-question list
│       └── RecentThreads.tsx         # thread list
└── pages/
    └── Home.tsx                      # composes everything for the W1 landing
```

## Design tokens

All colors, sizes, radii live in `src/index.css` as HSL CSS variables, mirrored to `tailwind.config.ts`. **The single source of truth is `/DESIGN.md` at the repo root** — edit that first, then this file. CI in W4 will fail if they diverge.

## Theme

Dark by default (Direction 06 — Calm Glass). Add `class="light"` to `<html>` to test light theme; toggle ships in W2.

## Routes scaffolded for later weeks

| Path | Status | Week |
|------|--------|------|
| `/` | ✅ Home | W1 |
| `/threads` · `/threads/:id` | 🚧 stub | W2 |
| `/saved` | 🚧 stub | W2 |
| `/dashboards` | 🚧 stub | W3 |
| `/sources` | 🚧 stub | W2 |
| `/knowledge` | 🚧 stub | W2 |
| `/agents` | 🚧 stub | W3 (Skills marketplace) |
| `/solutions/:persona` | 🚧 stub | W2 (CFO, RevOps, Data, Eng, Security, Everyone) |

## What's NOT in W1

- Routing — single Home page is the only screen. React Router lands W2.
- TanStack Query — fetch-and-state-cache lands W2 alongside threads.
- Voice input — W4.
- PWA / service worker — W4.
- Tests — Vitest + Testing Library lands W2 alongside the first persistent feature.
- shadcn-cli setup — primitives are written by hand in W1 (Button/Card/Badge/Input). Run `npx shadcn@latest init` in W2 to add Dialog/Sheet/DropdownMenu/Tabs/Toast/Tooltip/etc.

## CI / engineering hygiene (W2)

- `npm run typecheck` (already wired)
- `npm run lint` (ESLint config lands W2)
- `npm test` (Vitest lands W2)
- Pre-commit hook to verify token parity between `DESIGN.md` and `tailwind.config.ts`
