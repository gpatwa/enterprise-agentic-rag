# Semantic Registry

This directory is the local, Git-backed source of versioned semantic contracts.
Each `*.json` file is a `SemanticRegistryDocument` with a `lifecycle` of
`draft`, `certified`, or `deprecated` and a validated semantic contract.

Registry changes are ordinary reviewed Git changes. The runtime registry is
read-only: it does not write files, invoke Git, or auto-promote contracts.
Malformed documents remain visible to callers as `invalid` entries and cannot
be resolved for execution. Only `get_certified()` returns a certified contract.
