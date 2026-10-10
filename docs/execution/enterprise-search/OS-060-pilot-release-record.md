# OS-060 Design-Partner Pilot Release Record

Status: local release packet complete; production cutover intentionally not
executed.

The pilot sequence is: run OS-057 and OS-058, review OS-080/082/084 evidence,
set canary percentage, observe shadow comparison, then switch the index alias
only after product, security, and operations approval. Instant rollback is the
previous generation alias plus `OPENSEARCH_CANARY_PERCENT=0`.

Open items requiring an external release decision are the selected customer,
live managed-cluster evidence, and human sign-off. This record prevents those
items from being mistaken for code-complete local work.
