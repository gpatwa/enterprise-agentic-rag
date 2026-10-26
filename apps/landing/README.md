# Compass marketing site

Static site for the public landing page and persona pages. It is a separate deployable from the product apps
(`apps/support-web`, `apps/analytics-web`, `apps/discovery-web`) so marketing copy ships on its own cadence and carries no
product code, API URLs or keys.

- `npm run dev` serves on :5174. `npm run build` type-checks, builds, templates the sitemap/robots, and prerenders `/welcome`
  with Playwright (`npx playwright install chromium` once).
- Build-time settings: `VITE_SITE_URL` (canonical origin), `VITE_APP_URL` (where "Try Compass" and "Sign in" go; defaults to
  the analytics pilot app), `VITE_PILOT_MAILTO` (pilot-request link; defaults to demo@kavachiq.com).
- Deploy: `.github/workflows/deploy-landing-azure.yml` (manual) publishes `dist/` to the landing Static Web App; it needs the
  `AZURE_STATIC_WEB_APPS_API_TOKEN` secret (`terraform output -raw landing_deploy_token` in `infra/terraform/azure-analytics-pilot`).
- Copy rule: claim only what the product demonstrably does. See `docs/LANDING_MESSAGING_REVIEW.md`. CI fails if the built page
  contains SOC 2 Type II, GDPR-ready, or aggregateRating strings.
