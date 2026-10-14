# ADS-064: Customer-Data-Plane Protocol and Local VPC-Boundary Simulator

Status: **Review** (implemented and locally verified; independent review of the code pending)
Milestone: M6 (wave 6B)
Depends on: ADS-040, ADS-063

## Decisions made under the user's delegation ("make the decision")

1. **The split is at the gateway.** The control plane keeps intent, compilation, policy, review, and evidence. The data plane (in
   the customer's network) holds the warehouse credentials, runs the compiled query, **validates the result locally** (the ADS-041
   checks, including the control-total reconciliation), and keeps the rows. Compiled SQL and policy filter values go *into* the data
   plane; that is not result data and not a credential.
2. **Rows never go to the control plane.** The control plane gets metadata (counts, byte size, truncation, cost, elapsed time,
   fingerprints), a validation verdict (status, issue codes, fingerprints), and an opaque delivery handle. Rows reach the user on a
   separate client path, straight from the data plane, and only for the person who asked, using that person's token for the data
   plane's own issuer. The handle is useless alone, and "unknown" and "not yours" give the same refusal so handles cannot be probed.
3. **Credentials never leave the data plane.** The control plane names a connection by alias; the data plane resolves it to a secret
   with its own provider. Any failure is reported as a stable code, never as text.
4. **The channel is authenticated.** Every control-path message is an envelope signed with a shared channel key (HMAC-SHA256), fresh
   (five-minute window) and unique (a replayed message ID is refused). The key never appears in a message.
5. **Grounded explanations in this mode are evidence-only.** The control plane cannot cite cells it never sees, so the ADS-043
   `evidence_only` status (no narrative claims) is the only one possible. Delivering the explanation step across the boundary is
   follow-up work (see Boundary).

## Deliverable

- `packages/platform_contracts/data_plane.py` (`data-plane-v1`): strict messages (`extra=forbid`): `EstimateRequest`,
  `ExecuteRequest` (alias, plan, plan fingerprint, certified intent, contract reference, policy values, limits, requester
  reference), `EstimateResponse`, `ExecuteResponse` (metadata, verdict, handle), `FetchRequest`/`FetchResponse` (client path only),
  and the signed `Envelope`. A test proves no control-path field name can denote rows or a credential.
- `app/data_plane/agent.py` (`DataPlaneAgent`): verifies signature, freshness, and replay; checks connection, tenant, dialect, and plan
  fingerprint; executes under the supplied limits (typed error codes); validates locally; stores rows behind a TTL handle; serves them
  to the requester.
- `app/data_plane/boundary.py` (`VpcBoundary`): serializes every crossing, logs it per direction, and scans control-path messages for
  registered forbidden values (result values, credentials). A hit is **blocked** and recorded as a violation.
- `app/data_plane/client.py` (`ControlPlaneClient`): builds requests and reads responses. It imports only the contracts (tested).
- Nothing mounts the agent or simulator; `app.main` and `api_v2` do not import them.

## Evidence

- `tests/test_ads064_data_plane.py` (15 tests): no control-path field can hold rows or a credential and an extra field is rejected;
  the plan fingerprint both planes compute equals the ADS-041 one; an honest run returns metadata and a valid verdict while the control
  log holds neither a result value nor the credential and the rows reach only the user's fetch (exactly the oracle's rows, as REST
  renders them); the data plane's result fingerprint equals a direct run's; **a row-leaking agent and a credential-leaking agent are
  blocked and recorded** (the scanner is a real oracle); a driver error that quotes the credential becomes
  `connection_unavailable` and nothing crosses; unsigned, forged-key, tampered, garbled, stale, and replayed envelopes are refused; unknown
  connection, tenant mismatch, and a dishonest fingerprint are refused; a join fanout is caught **in the data plane** and only
  `fanout_suspected` crosses; truncation, a cost limit, unsafe SQL, an unusable intent, and a missing certified contract are enforced
  there; rows are refused to a colleague, another tenant, the wrong purpose, a bad or wrong-audience token, an unknown handle, an expired
  handle, and the user's token never appears on the control path; and the control-plane client imports only the contracts.
- One test-oracle weakness found by the suite itself: the leak oracle first registered only raw decimals, so a leaked canonical value
  went undetected until the oracle also registered the canonical form.

## Boundary

- **A simulator, not isolation.** It proves the protocol's contract and that this agent honours it; it is not a network boundary, a
  deployment, or a penetration test. A real deployment needs mTLS or private link, key management for the channel key, and egress rules.
- **Graph integration is not done.** The reference graph's `result_validate`, `explain`, and answer assembly still expect rows. Running
  the governed graph over this protocol needs a remote result stage that trusts the data plane's verdict, an evidence envelope that
  records it, and an answer outcome that withholds rows (rows delivered by handle). That is a follow-up, not part of this packet.
- The shared channel key is symmetric; a compromised control plane can sign arbitrary requests, so the data plane still enforces
  its own limits, certified contract, dialect, and read-only gateway on every request.
- Policy filter values and compiled SQL are visible to the customer's data plane by design.
- The agent keeps results in memory behind a TTL; a restart loses undelivered rows (the user re-asks).
- No live warehouse, identity provider, or network was used.
