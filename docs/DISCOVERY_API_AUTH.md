# Discovery API authentication

Status: **implemented in code, off by default.** Owner decision (2026-11-05): the API validates Entra tokens itself. Nothing is deployed or applied by this change.

## Why
Before this, the API performed no authentication. Sign-in existed only at the edge (Container Apps built-in Entra login on the web app, with the API internal-only), `DISCOVERY_AUTH_ENABLED` was read only by the production-settings check, and the tenant and principal came from the request body, so anyone who could reach the API could claim any tenant.

## What it does when `DISCOVERY_AUTH_ENABLED=true`
- Every `/api/discovery/*` route requires `Authorization: Bearer <jwt>`. `/health` stays open.
- The token must be RS256, signed by a key in the directory's published key set, with the configured issuer and audience, unexpired (60 s leeway), and a `tid` equal to the configured directory and an `oid`.
- The tenant comes from `DISCOVERY_ENTRA_TENANT_MAP` and the principal from `DISCOVERY_ENTRA_PRINCIPAL_MAP` (object id to user id; an unmapped id is used as is and has no profile, so it sees nothing). **The `tenant_id`, `principal_id` and `user_id` in the request body are overwritten from the token.**
- Failures return a generic 401 (or 403/503) with no reason; the reason goes to the server log without the token. Keys are cached for an hour, refetched at most once a minute on an unknown key id, and the cache keeps serving if the key endpoint fails; with no cache at all it fails closed with 503.
- `alg: none`, HMAC-with-the-public-key, tampered payloads, wrong audience, issuer or directory, expired tokens and unknown key ids are refused (covered by tests).

## Settings
| Variable | Meaning |
|---|---|
| `DISCOVERY_AUTH_ENABLED` | `true` turns enforcement on. Requires the four below. |
| `DISCOVERY_ENTRA_TENANT_ID` | The Entra directory (tenant) id tokens must come from. |
| `DISCOVERY_ENTRA_AUDIENCE` | The `aud` the token must carry (the app registration's client id). |
| `DISCOVERY_ENTRA_TENANT_MAP` | JSON `{ "<entra tenant id>": "<discovery tenant>" }`; must include the directory above. |
| `DISCOVERY_ENTRA_PRINCIPAL_MAP` | Optional JSON `{ "<oid>": "<discovery user id>" }`. |
| `DISCOVERY_ENTRA_JWKS_URL` | Optional; defaults to the directory's v2.0 key endpoint. https is required in staging and production. |
| `DISCOVERY_ENTRA_REQUIRED_SCOPE` | Optional (2026-11-07). When set, the token's `scp` must contain it (for example `access_as_user`). An ID token for the same app has the same audience and issuer but no `scp`, so this keeps it from working as an API token. The Terraform stack sets it whenever `enable_api_auth` is true. |

**Token version.** The defaults match a **version 2** access token: `aud` is the app's client id (a GUID, not `api://<id>`) and `iss` is `https://login.microsoftonline.com/<tenant>/v2.0`. The app registration must have `requested_access_token_version = 2` (declared in `infra/terraform/azure-discovery-pilot`); a version 1 token (`aud = api://<id>`, `iss = https://sts.windows.net/<tenant>/`) is refused, so a missing setting fails closed with a 401. Checked against the real tenant's published metadata (issuer and key endpoint match; the keys parse) and in `tests/test_entra_v2_tokens.py` with a realistic v2 claim set; never against a token issued by Entra for this app.

Production settings validation already required `auth_enabled`; it now means something.

## What is not done (needs an owner decision)
**Where the token comes from.** The API accepts any compliant bearer token, but the web tier does not send one yet. Options:
1. **MSAL in the single-page app** with a separate API app registration (exposed scope, assignment required), sending `Authorization: Bearer` from the browser. Standard and independent of the edge; needs a web dependency and a Terraform change to the app registrations.
2. **Forward the sign-in token from the edge** through nginx. This depends on Container Apps built-in auth exposing an ID token to the container; I could not confirm that it does, and it would need a real deployment to test.
3. **Trust the platform-injected identity header** instead of verifying a JWT. Simplest, but it is not token validation and relies on the API staying internal-only.

Until one is chosen and deployed, leave `DISCOVERY_AUTH_ENABLED` off in the pilot (the API is internal-only behind the Entra-protected web app); turning it on without a token source would lock the web app out.

## Known limits
- `GET /explanations/{ref}` requires a valid token but does not check that the decision belongs to the caller's tenant; references are unguessable digests, but this is not an authorization check.
- Single Entra directory per deployment (one `tid`).
- No token revocation beyond expiry.
- Tested with locally generated keys and a mock key endpoint; never against Entra.

## Web sign-in (MSAL)

The web app can send an Entra access token. It is off unless all three build settings are set; with none set the app
sends no token (today's behaviour, so keep `DISCOVERY_AUTH_ENABLED` off then):

| Build arg / env | Meaning |
|---|---|
| `VITE_ENTRA_CLIENT_ID` | the SPA app registration's client ID |
| `VITE_ENTRA_TENANT_ID` | the Entra tenant ID |
| `VITE_ENTRA_API_SCOPE` | the API scope to request, e.g. `api://<api-app-id>/access_as_user` |

Behaviour: `@azure/msal-browser` (3.28.1, loaded on first request) tries a silent token, otherwise redirects to sign in.
The token is attached as `Authorization: Bearer` on the search and product-search calls and is kept in
`sessionStorage` by MSAL only.

**Needs the owner (an Entra change I have not made):** a SPA app registration with the web URL as a redirect URI, an
API app registration exposing the scope, and that API's client ID as `DISCOVERY_ENTRA_AUDIENCE` on the API with the
tenant and principal maps set. Not tested against a real tenant; the unit tests cover the config and the header only.

## Web sign-in states and the one-redirect rule (2026-11-07)

Applies only when the three `VITE_ENTRA_*` settings are set. With them unset nothing below runs: no token source, no
extra requests, `fetch` is still called synchronously, and a 401 or 403 from the edge is still shown with the states below
(the button then reloads the page so the edge sign-in takes over).

**No visible second sign-in.** The web app already sits behind Entra easy-auth, so a person arrives with an Entra session.
At page load the SPA tries, in order: a cached MSAL token; `ssoSilent` against the existing session, with a login hint
read from easy-auth's `/.auth/me` when present (a 404 or the SPA's own index.html in local dev means no hint; only an
email-shaped identity claim is read, any token in that response is ignored); then, as a last resort, **one** automatic
redirect. A silent refresh after a 401 never redirects.

**One automatic redirect per page load.** Before redirecting, the app claims a flag in `sessionStorage`
(`discovery.auth.redirect-attempt`, a timestamp). While the flag is fresh (5 minutes) no second automatic redirect
happens. A good token clears it. If `sessionStorage` cannot be written, no automatic redirect happens at all. Concurrent
requests share one attempt. A redirect that returns with an error is remembered by code only, is never retried
automatically, and `access_denied` maps to the no-access state. `interaction_in_progress` never starts a second
interaction. Only the person pressing the button starts another redirect (and, for a stale `interaction_in_progress`,
reloads the page, which MSAL clears on load). The hidden sign-in frame (our own origin loaded with a response hash) does
not run the app, so it cannot consume that hash.

**States** (one page-level panel; experience search and product search share it):

| State | When | Copy | Behaviour |
|---|---|---|---|
| Signing in | token acquisition still pending after 400 ms, or a redirect under way | "Signing you in..." | polite live region, always mounted; not an alert; never shown for a quick sign-in |
| Session ended | 401 after one silent refresh and one retry; silent sign-in needs the person; redirect returned an error | "Your session ended. Sign in again." | `role="alert"`, focus moves to the single "Sign in again" button |
| No access | 403 (no refresh, no retry); redirect returned `access_denied` | "You don't have access to this demo. Ask the owner to add you." | `role="alert"`, focus moves to the notice (no button) |
| API unavailable | any other failure | the existing "... is unavailable right now. Try again in a moment." with Retry | unchanged |

No status code, provider error or token content is shown; the status lives on a typed `DiscoveryApiError` for logic only.
A later good answer clears the session-ended or no-access panel.

**Not tested:** a real tenant or real Entra tokens (MSAL is faked in unit tests); a real `/.auth/me` response shape from
Container Apps (the parser follows the documented array of `user_claims` and tolerates absence); real browsers (tests run
in jsdom, so third-party-cookie and iframe `ssoSilent` behaviour, and the real redirect round trip, are unverified); screen
readers (roles, live regions and focus are asserted, not heard); visual layout of the new panel at real viewport sizes.
The Entra side (SPA redirect URI, exposed scope, v2 tokens) is owned by the Terraform work item and is not part of this change.
