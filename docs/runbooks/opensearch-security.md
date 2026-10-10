# OpenSearch Security and Credential Runbook

Production endpoints must use TLS with certificate verification enabled.
Credentials are injected through the Helm `secretRef`; they are never placed
in values files, logs, search documents, or audit payloads.

Rotate the least-privilege credential by creating a new secret version, deploy
it to the API and indexing worker, verify health and a scoped query, then revoke
the old credential. A credential rotation must not require reindexing.

The service identity needs only index read/search, bulk write for the indexing
worker, alias management for the release job, and health access. Query callers
cannot change tenant or ACL clauses.
