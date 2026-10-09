-- migrate:up

-- Agency-hosted resources allowed under decision D1 (docs/decisions.md).
-- Loaded from config/sources.yaml (allowed_external_resources) by `python -m etl.sources load`.
CREATE TABLE allowed_external_resource (
    id               text PRIMARY KEY CHECK (id ~ '^E[0-9]+$'),
    name             text NOT NULL,
    urls             text[] NOT NULL CHECK (cardinality(urls) > 0),
    host             text NOT NULL,
    datagov_datasets text[] NOT NULL DEFAULT '{}',
    status           text NOT NULL CHECK (status IN ('allowed', 'withdrawn')),
    config           jsonb NOT NULL,            -- the full YAML entry as loaded
    active           boolean NOT NULL DEFAULT true,  -- false = no longer in sources.yaml
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

-- Source registry (PLAN.md §4). Loaded from config/sources.yaml (sources).
-- Rows are never deleted, because dataset_version and import_log point to them;
-- an entry removed from the YAML is set active = false.
CREATE TABLE source (
    id                   text PRIMARY KEY CHECK (id ~ '^[a-z][a-z0-9_]*$'),
    name_lv              text NOT NULL,
    name_en              text NOT NULL,
    owner                text NOT NULL,
    source_group         text NOT NULL,
    display_order        integer NOT NULL,
    type                 text NOT NULL CHECK (type IN ('layer', 'check')),
    subject_kinds        text[] NOT NULL
        CHECK (cardinality(subject_kinds) > 0
               AND subject_kinds <@ ARRAY['object', 'applicant', 'municipality']),
    default_selected     boolean NOT NULL,
    coverage             text,
    max_age              interval NOT NULL CHECK (max_age > interval '0'),
    datagov_dataset_ids  text[] NOT NULL DEFAULT '{}',
    datagov_resource_ids text[] NOT NULL DEFAULT '{}',
    external_resource_ids text[] NOT NULL DEFAULT '{}',  -- ids in allowed_external_resource
    licence              text,
    config               jsonb NOT NULL,        -- the full YAML entry as loaded
    active               boolean NOT NULL DEFAULT true,
    loaded_at            timestamptz NOT NULL DEFAULT now(),
    CHECK (cardinality(datagov_dataset_ids) > 0 OR cardinality(external_resource_ids) > 0)
);

-- One imported snapshot of a source (PLAN.md §2.2, ETL rule E7).
-- version_date comes from the source (CKAN last_modified or the file's own date),
-- never the run date. Same checksum = same version.
CREATE TABLE dataset_version (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id            text NOT NULL REFERENCES source (id),
    datagov_dataset_ids  text[] NOT NULL DEFAULT '{}',
    datagov_resource_ids text[] NOT NULL DEFAULT '{}',
    resource_urls        text[] NOT NULL DEFAULT '{}',
    licence              text,
    version_date         date NOT NULL,
    source_last_modified timestamptz,
    checksum             text NOT NULL CHECK (checksum ~ '^sha256:[0-9a-f]{64}$'),
    row_count            bigint CHECK (row_count >= 0),
    status               text NOT NULL DEFAULT 'loading'
        CHECK (status IN ('loading', 'live', 'superseded', 'failed')),
    imported_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, checksum)
);

-- At most one live version per source; the last good version stays live on failure.
CREATE UNIQUE INDEX dataset_version_one_live ON dataset_version (source_id) WHERE status = 'live';

-- One row per import attempt, successful or not (PLAN.md §2.2).
CREATE TABLE import_log (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id            text NOT NULL REFERENCES source (id),
    dataset_version_id   bigint REFERENCES dataset_version (id),
    started_at           timestamptz NOT NULL DEFAULT now(),
    finished_at          timestamptz,
    status               text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'succeeded', 'unchanged', 'failed')),
    datagov_dataset_ids  text[] NOT NULL DEFAULT '{}',
    datagov_resource_ids text[] NOT NULL DEFAULT '{}',
    resource_urls        text[] NOT NULL DEFAULT '{}',
    licence              text,
    source_last_modified timestamptz,
    checksum             text CHECK (checksum ~ '^sha256:[0-9a-f]{64}$'),
    row_counts           jsonb NOT NULL DEFAULT '{}',  -- per table or layer
    message              text,
    CHECK ((status = 'running') = (finished_at IS NULL)),
    CHECK (status NOT IN ('succeeded', 'unchanged') OR dataset_version_id IS NOT NULL)
);

CREATE INDEX import_log_source_started ON import_log (source_id, started_at DESC);

-- migrate:down

DROP TABLE import_log;
DROP TABLE dataset_version;
DROP TABLE source;
DROP TABLE allowed_external_resource;
