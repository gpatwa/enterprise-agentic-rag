-- IMD-013 authoritative local PostgreSQL baseline.
-- Search indexes, embeddings, and feature values are derived and rebuildable.

CREATE TABLE discovery_catalog_records (
    tenant_id TEXT NOT NULL,
    experience_id TEXT NOT NULL,
    creator_id TEXT NOT NULL,
    record_version TEXT NOT NULL,
    content_version TEXT NOT NULL,
    permission_version TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    provenance_ref TEXT NOT NULL,
    synthetic BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    authoritative_payload JSONB NOT NULL,
    PRIMARY KEY (tenant_id, experience_id),
    CHECK (tenant_id <> ''),
    CHECK (experience_id <> ''),
    CHECK (jsonb_typeof(authoritative_payload) = 'object'),
    CHECK (updated_at >= created_at)
);

CREATE TABLE discovery_profiles (
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    consent_state TEXT NOT NULL,
    synthetic BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    profile_payload JSONB NOT NULL,
    PRIMARY KEY (tenant_id, user_id),
    CHECK (tenant_id <> ''),
    CHECK (user_id <> ''),
    CHECK (consent_state IN ('personalization_allowed', 'personalization_denied')),
    CHECK (jsonb_typeof(profile_payload) = 'object'),
    CHECK (updated_at >= created_at)
);

CREATE TABLE discovery_interaction_events (
    tenant_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    event_version TEXT NOT NULL,
    event_type TEXT NOT NULL,
    user_id TEXT NOT NULL,
    experience_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    consent_state TEXT NOT NULL,
    synthetic BOOLEAN NOT NULL,
    event_payload JSONB NOT NULL,
    PRIMARY KEY (tenant_id, event_id),
    UNIQUE (tenant_id, idempotency_key),
    CHECK (tenant_id <> ''),
    CHECK (event_id <> ''),
    CHECK (jsonb_typeof(event_payload) = 'object'),
    CHECK (received_at >= occurred_at)
);

CREATE TABLE discovery_derived_version_metadata (
    tenant_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    derived_kind TEXT NOT NULL,
    derived_version TEXT NOT NULL,
    source_version TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL,
    PRIMARY KEY (tenant_id, subject_type, subject_id, derived_kind, derived_version),
    CHECK (tenant_id <> ''),
    CHECK (subject_id <> ''),
    CHECK (jsonb_typeof(metadata) = 'object')
);
