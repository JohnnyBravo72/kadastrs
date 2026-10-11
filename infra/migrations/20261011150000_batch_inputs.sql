-- migrate:up

-- Batch input (PLAN.md §9 Phase 5). The uploaded file is never stored (§1); only
-- the cleaned list is kept, one work.run_input row per input row, so the Excel
-- report (sheet "Neatrasts") is built from stored data only and a replayed run
-- gives the same report.
--   work.run_input   one row per input row: cleaned values, resolution status,
--                    problems per column (reason, suggestions), targets made from it
--   work.run_target  + input_no (the input row), label (e.g. "divdomīgs: zemes
--                    vienība") and applicant_reg_no (legal-entity pattern only)
-- Same guards as run_target: no UPDATE / DELETE, rows only while the run is
-- running, TRUNCATE only with kadastrs.allow_truncate = on (test resets).

ALTER TABLE work.run_target
    ADD COLUMN input_no integer,
    ADD COLUMN label text,
    -- CLAUDE.md rule 5: an 11-digit number starting with 4, 5 or 9 (companies,
    -- associations, institutions). Anything else may be a personal code and is
    -- never stored.
    ADD COLUMN applicant_reg_no text CHECK (applicant_reg_no ~ '^[459][0-9]{10}$');

CREATE TABLE work.run_input (
    run_id           bigint NOT NULL REFERENCES work.run (id),
    input_no         integer NOT NULL,                 -- 0-based, input order
    row_no           integer NOT NULL,                 -- row in the file or pasted list (1-based)
    value            text,                             -- vertiba as read (cleaned list)
    kind             text CHECK (kind IN ('property', 'parcel', 'building')),  -- veids
    project_no       text,
    address          text,                             -- adrese as read
    applicant_reg_no text CHECK (applicant_reg_no ~ '^[459][0-9]{10}$'),
    status           text NOT NULL,                    -- resolution status of vertiba
    problems         jsonb NOT NULL DEFAULT '[]',      -- [{column, status, reason, suggestions}]
    target_nos       integer[] NOT NULL DEFAULT '{}',  -- targets checked for this row
    PRIMARY KEY (run_id, input_no)
);

CREATE FUNCTION work.guard_input_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    run_status text;
BEGIN
    SELECT status INTO run_status FROM work.run WHERE id = NEW.run_id;
    IF run_status IS DISTINCT FROM 'running' THEN
        RAISE EXCEPTION 'run % is not running (status %): inputs cannot be added',
            NEW.run_id, run_status USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER run_input_change BEFORE UPDATE OR DELETE ON work.run_input
    FOR EACH ROW EXECUTE FUNCTION work.reject_change();
CREATE TRIGGER run_input_insert BEFORE INSERT ON work.run_input
    FOR EACH ROW EXECUTE FUNCTION work.guard_input_insert();
CREATE TRIGGER run_input_truncate BEFORE TRUNCATE ON work.run_input
    FOR EACH STATEMENT EXECUTE FUNCTION work.guard_truncate();

-- migrate:down

DROP TABLE work.run_input;
DROP FUNCTION work.guard_input_insert();
ALTER TABLE work.run_target DROP COLUMN input_no, DROP COLUMN label, DROP COLUMN applicant_reg_no;
