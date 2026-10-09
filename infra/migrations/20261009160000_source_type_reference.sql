-- migrate:up

-- `reference`: core data every check relies on (cadastre, addresses, admin
-- boundaries). Always used, never shown in the sources checklist (Phase 2a).
ALTER TABLE source DROP CONSTRAINT source_type_check;
ALTER TABLE source ADD CONSTRAINT source_type_check
    CHECK (type IN ('layer', 'check', 'reference'));
ALTER TABLE source ADD CONSTRAINT source_reference_always_selected
    CHECK (type <> 'reference' OR default_selected);

ALTER TABLE source ADD COLUMN user_selectable boolean
    GENERATED ALWAYS AS (type <> 'reference') STORED;

COMMENT ON COLUMN source.user_selectable IS
    'false for reference sources: hidden from the sources checklist, always used';

-- migrate:down

ALTER TABLE source DROP COLUMN user_selectable;
ALTER TABLE source DROP CONSTRAINT source_reference_always_selected;
ALTER TABLE source DROP CONSTRAINT source_type_check;
ALTER TABLE source ADD CONSTRAINT source_type_check CHECK (type IN ('layer', 'check'));
