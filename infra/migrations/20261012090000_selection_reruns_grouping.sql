-- migrate:up

-- Phase 7 (PLAN.md §8.1, §8.2): the entry dialog's unit selection, new runs made
-- from a stored run, and project groups. CLAUDE.md rule 3 still holds: nothing
-- here changes a stored run or result.
--   work.run_target.unit_selection  the units ticked in the entry dialog
--                                   ([{type, designation}]); NULL = all units
--   work.run.parent_run_id          the run this one was made from:
--                                   "Atjaunot" (same pinned versions, new source set)
--                                   or "Pārbaudīt ar jaunākajiem datiem" (live versions)
--   work.run.checked_as_of          the time the modules evaluate at (e.g. the age of
--                                   a BIS case); NULL = created_at. "Atjaunot" keeps
--                                   the parent's, so unchanged modules give the same
--                                   results
--   work.run_grouping               project groups of a run, insert-only: each row is
--                                   the whole grouping; the newest row is current.
--                                   No row = groups from run_target.project_no
ALTER TABLE work.run
    ADD COLUMN parent_run_id bigint REFERENCES work.run (id),
    ADD COLUMN rerun_kind text CHECK (rerun_kind IN ('sources', 'latest')),
    ADD COLUMN checked_as_of timestamptz,
    ADD CHECK ((parent_run_id IS NULL) = (rerun_kind IS NULL));

ALTER TABLE work.run_target
    ADD COLUMN unit_selection jsonb CHECK (unit_selection IS NULL
                                           OR jsonb_typeof(unit_selection) = 'array');

CREATE TABLE work.run_grouping (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id     bigint NOT NULL REFERENCES work.run (id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    -- [{id, name}] in display order; every target is in exactly one group
    groups     jsonb NOT NULL CHECK (jsonb_typeof(groups) = 'array'),
    -- {"<target_no>": "<group id>"}
    assignment jsonb NOT NULL CHECK (jsonb_typeof(assignment) = 'object'),
    origin     text NOT NULL CHECK (origin IN ('user', 'rerun'))
);
CREATE INDEX run_grouping_run ON work.run_grouping (run_id, id DESC);

-- A grouping is only accepted for a finished run (results are stored).
CREATE FUNCTION work.guard_grouping_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    run_status text;
BEGIN
    SELECT status INTO run_status FROM work.run WHERE id = NEW.run_id;
    IF run_status IS DISTINCT FROM 'done' THEN
        RAISE EXCEPTION 'run % is not done (status %): groups cannot be stored',
            NEW.run_id, run_status USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER run_grouping_change BEFORE UPDATE OR DELETE ON work.run_grouping
    FOR EACH ROW EXECUTE FUNCTION work.reject_change();
CREATE TRIGGER run_grouping_insert BEFORE INSERT ON work.run_grouping
    FOR EACH ROW EXECUTE FUNCTION work.guard_grouping_insert();
CREATE TRIGGER run_grouping_truncate BEFORE TRUNCATE ON work.run_grouping
    FOR EACH STATEMENT EXECUTE FUNCTION work.guard_truncate();

-- migrate:down

DROP TABLE work.run_grouping;
DROP FUNCTION work.guard_grouping_insert();
ALTER TABLE work.run_target DROP COLUMN unit_selection;
ALTER TABLE work.run DROP COLUMN parent_run_id, DROP COLUMN rerun_kind, DROP COLUMN checked_as_of;
