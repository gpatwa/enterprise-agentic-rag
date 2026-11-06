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
