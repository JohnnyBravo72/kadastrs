-- migrate:up

-- Freshness against the source (decided 2026-10-11, docs/decisions.md "Freshness";
-- PLAN.md §2.2). A source is fresh when we hold the newest file the publisher has
-- released, not when our copy is younger than a fixed age:
--   source.source_stale_after  how long the publisher may go without a new release
--                              before we warn (NULL = never, e.g. a frozen list);
--                              replaces source.max_age
--   source_check               one row per look at the source's latest release
--                              (package_show), from a run, `etl status` or an import;
--                              the last good row is used when the source is offline
ALTER TABLE source
    ADD COLUMN source_stale_after interval CHECK (source_stale_after > interval '0'),
    DROP COLUMN max_age;

CREATE TABLE source_check (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id            text NOT NULL REFERENCES source (id),
    checked_at           timestamptz NOT NULL DEFAULT now(),
    origin               text NOT NULL CHECK (origin IN ('run', 'status', 'import')),
    ok                   boolean NOT NULL,
    remote_last_modified timestamptz,          -- the source's latest release (CKAN date)
    error                text,
    CHECK (ok OR error IS NOT NULL)
);
CREATE INDEX source_check_last ON source_check (source_id, checked_at DESC) WHERE ok;

-- migrate:down

DROP TABLE source_check;
ALTER TABLE source DROP COLUMN source_stale_after,
    ADD COLUMN max_age interval NOT NULL DEFAULT interval '14 days';
