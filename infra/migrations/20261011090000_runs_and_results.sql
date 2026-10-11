-- migrate:up

-- Check runs and their results (PLAN.md §4 work data, §6.5). CLAUDE.md rule 3:
-- results are never changed after they are stored; re-checking creates a new run.
--   work.run           one run: selected sources, rule set (snapshot), thresholds
--   work.run_version   the dataset versions pinned at the start of the run
--   work.run_target    the resolved targets as given (one row per input object)
--   work.check_result  one row per target, unit and module (§6.2 contract)
-- Guards: check_result, run_version and run_target reject UPDATE and DELETE;
-- run allows only the status transition running -> done | failed; results can
-- be added only while their run is running; TRUNCATE needs the session setting
-- kadastrs.allow_truncate = on (test resets only).
CREATE SCHEMA work;

CREATE TABLE work.run (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at       timestamptz NOT NULL DEFAULT now(),
    finished_at      timestamptz,
    status           text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done', 'failed')),
    origin           text NOT NULL,                     -- api | cli | compare | test
    sources          text[] NOT NULL,                   -- selected check sources
    modules          text[] NOT NULL,                   -- modules run
    engine_version   text NOT NULL,
    rule_set_version text NOT NULL,
    rule_set_status  text NOT NULL,                     -- draft | agreed
    rule_set_sha256  text NOT NULL CHECK (rule_set_sha256 ~ '^[0-9a-f]{64}$'),
    rule_set         jsonb NOT NULL,                    -- config/rules.yaml as used (replay)
    error            text,
    CHECK ((status = 'running') = (finished_at IS NULL))
);

CREATE TABLE work.run_version (
    run_id             bigint NOT NULL REFERENCES work.run (id),
    source_id          text NOT NULL,
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    source             jsonb NOT NULL,   -- {id, name, dataset_date, datagov_url, max_age} as of the run
    PRIMARY KEY (run_id, source_id),
    UNIQUE (run_id, dataset_version_id)
);

CREATE TABLE work.run_target (
    run_id        bigint NOT NULL REFERENCES work.run (id),
    target_no     integer NOT NULL,                    -- 0-based, input order
    input         text,                                -- the value as typed
    type          text NOT NULL CHECK (type IN ('property', 'parcel', 'building',
                                                'parcel_part', 'premise_group')),
    designation   text NOT NULL CHECK (designation ~ '^[0-9]{11}([0-9]{3,4}|[0-9]{6})?$'),
    given_address text CHECK (given_address ~ '^[0-9]{9}$'),  -- VARIS code (module 2)
    project_no    text,
    warnings      jsonb NOT NULL DEFAULT '[]',          -- carried over from resolution
    units         jsonb NOT NULL DEFAULT '[]',          -- [{type, designation}] checked
    PRIMARY KEY (run_id, target_no)
);

CREATE TABLE work.check_result (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id              bigint NOT NULL,
    target_no           integer NOT NULL,
    scope               text NOT NULL CHECK (scope IN ('target', 'unit')),
    unit_type           text NOT NULL,
    unit_code           text NOT NULL,
    module              text NOT NULL,
    module_no           integer NOT NULL,
    module_version      text NOT NULL,
    status              text NOT NULL CHECK (status IN ('found', 'clear', 'not_covered', 'no_data',
                                                        'source_unavailable', 'error')),
    reason              text,
    risk                text NOT NULL CHECK (risk IN ('high', 'medium', 'low', 'none', 'unknown')),
    rule_ids            text[] NOT NULL,
    items               jsonb NOT NULL,
    match_type          text,
    warnings            jsonb NOT NULL,
    source              jsonb,
    sources             jsonb NOT NULL,
    dataset_version_ids bigint[] NOT NULL,
    display             jsonb NOT NULL,
    computed_at         timestamptz NOT NULL,
    FOREIGN KEY (run_id, target_no) REFERENCES work.run_target (run_id, target_no),
    UNIQUE (run_id, target_no, module, scope, unit_code),
    CHECK (status <> 'no_data' OR reason IS NOT NULL),
    CHECK (cardinality(dataset_version_ids) > 0 OR status = 'source_unavailable')
);
CREATE INDEX check_result_run ON work.check_result (run_id, target_no);

-- --- guards ---------------------------------------------------------------------------

CREATE FUNCTION work.reject_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% rows are never changed after they are stored (CLAUDE.md rule 3); '
                    're-checking creates a new run', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;

CREATE FUNCTION work.guard_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF coalesce(current_setting('kadastrs.allow_truncate', true), '') <> 'on' THEN
        RAISE EXCEPTION 'TRUNCATE of % is not allowed: runs and results are kept (D3)', TG_TABLE_NAME
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NULL;
END
$$;

CREATE FUNCTION work.guard_run_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'running' OR NEW.status NOT IN ('done', 'failed')
       OR (to_jsonb(NEW) - '{status,finished_at,error}'::text[])
          IS DISTINCT FROM (to_jsonb(OLD) - '{status,finished_at,error}'::text[]) THEN
        RAISE EXCEPTION 'run % is finished or the change is not a status transition: runs are '
                        'never changed after they are stored (CLAUDE.md rule 3)', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

-- A result may be added only while its run is running, and every dataset
-- version it names must be one of the run's pinned versions.
CREATE FUNCTION work.guard_result_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    run_status text;
    unknown bigint[];
BEGIN
    SELECT status INTO run_status FROM work.run WHERE id = NEW.run_id;
    IF run_status IS DISTINCT FROM 'running' THEN
        RAISE EXCEPTION 'run % is not running (status %): results cannot be added',
            NEW.run_id, run_status USING ERRCODE = 'restrict_violation';
    END IF;
    SELECT array_agg(v) INTO unknown
    FROM unnest(NEW.dataset_version_ids) AS v
    WHERE NOT EXISTS (SELECT 1 FROM work.run_version rv
                      WHERE rv.run_id = NEW.run_id AND rv.dataset_version_id = v);
    IF unknown IS NOT NULL THEN
        RAISE EXCEPTION 'check_result names dataset versions % that run % did not pin',
            unknown, NEW.run_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER run_update BEFORE UPDATE ON work.run
    FOR EACH ROW EXECUTE FUNCTION work.guard_run_update();
CREATE TRIGGER run_delete BEFORE DELETE ON work.run
    FOR EACH ROW EXECUTE FUNCTION work.reject_change();
CREATE TRIGGER run_version_change BEFORE UPDATE OR DELETE ON work.run_version
    FOR EACH ROW EXECUTE FUNCTION work.reject_change();
CREATE TRIGGER run_target_change BEFORE UPDATE OR DELETE ON work.run_target
    FOR EACH ROW EXECUTE FUNCTION work.reject_change();
CREATE TRIGGER check_result_change BEFORE UPDATE OR DELETE ON work.check_result
    FOR EACH ROW EXECUTE FUNCTION work.reject_change();
CREATE TRIGGER check_result_insert BEFORE INSERT ON work.check_result
    FOR EACH ROW EXECUTE FUNCTION work.guard_result_insert();

CREATE TRIGGER run_truncate BEFORE TRUNCATE ON work.run
    FOR EACH STATEMENT EXECUTE FUNCTION work.guard_truncate();
CREATE TRIGGER run_version_truncate BEFORE TRUNCATE ON work.run_version
    FOR EACH STATEMENT EXECUTE FUNCTION work.guard_truncate();
CREATE TRIGGER run_target_truncate BEFORE TRUNCATE ON work.run_target
    FOR EACH STATEMENT EXECUTE FUNCTION work.guard_truncate();
CREATE TRIGGER check_result_truncate BEFORE TRUNCATE ON work.check_result
    FOR EACH STATEMENT EXECUTE FUNCTION work.guard_truncate();

-- BIS object points in EPSG:10306 for the "nearby" match (module 5). The CSV
-- coordinates are WGS84 (lon/lat as published); ST_Transform is immutable.
CREATE INDEX bis_object_point ON ref.bis_object USING gist (
    ST_Transform(ST_SetSRID(ST_MakePoint(lon, lat), 4326), 10306)
) WHERE lon IS NOT NULL AND lat IS NOT NULL;

-- migrate:down

DROP INDEX ref.bis_object_point;
DROP SCHEMA work CASCADE;
