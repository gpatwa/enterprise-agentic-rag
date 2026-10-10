# Search Golden Corpus

This directory contains fictional, deterministic support-search data for OS-005
and later provider comparisons. It must not contain customer records or data
copied from production systems.

## Files

- `documents.json`: searchable records and normalized metadata.
- `queries.json`: query text, tenant scope, filters, and ACL tokens.
- `judgments.json`: graded query/document relevance decisions.

## Document Schema

Each document contains:

- `document_id`: unique derived search ID.
- `tenant_id`: owning tenant.
- `source_type`: `ticket`, `comment`, or `article`.
- `source_id`, `provider`, `title`, `text`.
- `status`, `tags`, and `source_uri`.
- `acl_tokens`: normalized permission tokens. A result is retrievable only when
  the query scope includes the tenant token and at least one required group
  token for the document.
- `updated_at`: fixed UTC timestamp.
- `content_version`: deterministic source/content version.

## Query Schema

Each query contains `query_id`, `tenant_id`, `text`, `filters`, and
`acl_tokens`. The query tenant and ACL tokens are the minimum security scope;
they are not optional metadata.

## Judgment Schema

Each judgment references one query and document and has a grade from `0` to `3`:

- `3`: direct resolution evidence.
- `2`: strongly relevant supporting evidence.
- `1`: weak context.
- `0`: irrelevant or inaccessible.

An inaccessible document must have grade `0`, even if its text is semantically
similar. This prevents relevance evaluation from rewarding a security failure.

## Extension Rules

When adding a fixture:

1. Use fictional data and fixed timestamps.
2. Keep tenant distribution explicit.
3. Add at least one positive or negative judgment for every new query.
4. Add cross-tenant or ACL judgments for security-sensitive queries.
5. Update the loader test only when the schema changes, not for ordinary data.
