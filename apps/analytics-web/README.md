# Compass Analytics Web

Independent React product for the commerce analytics workflow.

```bash
cd apps/analytics-web
npm install
npm run dev
```

The app listens on http://localhost:5174 and proxies `/api` and `/health` to
the analytics API on port 8090. Production builds are served from the app's
own Nginx image; they are not bundled into the support API container.

## Azure deployment

The image is deployed independently as the `analytics-web` Helm release. Its
Nginx container receives `ANALYTICS_API_HOST=analytics-api:8090`, proxies API
requests inside the cluster, and is exposed through the configured analytics
hostname. See [the Azure deployment guide](../../docs/deployment-azure.md).

## Governed analysis (ADS-047)

The **Governed** view uses the `/api/v2/analytics` endpoints. It is inert until the API
has a governed runtime configured (otherwise it reports that governed analysis is not
enabled). It needs an OIDC access token, entered in the page and held only in memory, and a
purpose (`VITE_ANALYTICS_PURPOSE`, default `analytics`). Reviewers open a run by ID with their
own token. Tests: `npm test` (Node's built-in runner; no extra dependencies).
