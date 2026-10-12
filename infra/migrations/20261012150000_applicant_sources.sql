-- migrate:up

-- Applicant data (Phase 8a, PLAN.md §6.1 modules 9, 14, 17; docs/decisions.md D10).
-- CLAUDE.md rule 5 is enforced here, not only in the importers: every table holds
-- legal entities only, no column can hold a natural person's name, birth date or
-- personal code, and a registration number must have the legal-entity pattern
-- (UR's 9-digit old numbers allowed for companies). Codes are text (rule 8).
--   ref.ur_company      UR register.csv, whole country
--   ref.ur_insolvency   UR insolvency proceedings of legal entities
--   ref.ur_sanction     UR sanctions file: LEGAL_ENTITY / FOREIGN_ENTITY rows only
--   ref.fid_sanction    FID "Sankciju subjekti": rows with a Latvian legal-entity reg. no.

CREATE TABLE ref.ur_company (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    reg_no        text NOT NULL CHECK (reg_no ~ '^([459][0-9]{10}|[0-9]{9})$'),  -- regcode
    name          text,                              -- NULL for IK and IND (D10)
    form          text NOT NULL,                     -- type: SIA, AS, IK, ZEM, ...
    form_text     text,                              -- type_text
    register      text,                              -- regtype_text
    registered    date,
    terminated    date,
    closed        text CHECK (closed IN ('L', 'R')), -- L likvidēts / izslēgts, R reorganizēts
    address       text,                              -- legal address as published
    varis_code    text CHECK (varis_code ~ '^[0-9]{9}$'),   -- addressid (NULL when 0)
    atvk          text CHECK (atvk ~ '^[0-9]{7}$'),
    PRIMARY KEY (dataset_version_id, reg_no),
    -- individual merchants and enterprises are named after their owner (rule 5)
    CHECK (name IS NULL OR form NOT IN ('IK', 'IND'))
);
CREATE INDEX ur_company_varis ON ref.ur_company (dataset_version_id, varis_code);

CREATE TABLE ref.ur_insolvency (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    proceeding_id text NOT NULL,
    reg_no        text NOT NULL CHECK (reg_no ~ '^[459][0-9]{10}$'),  -- legal entities only
    started_on    date,
    ended_on      date,
    form          text,                              -- proceeding_form
    type          text,                              -- proceeding_type
    subtype       text,
    resolution_type text,
    resolution_name text,
    PRIMARY KEY (dataset_version_id, proceeding_id)
);
CREATE INDEX ur_insolvency_reg ON ref.ur_insolvency (dataset_version_id, reg_no);

-- No name, birth_date, latvian_identity_number_masked or nationality columns:
-- natural-person rows are never stored (D10 option A).
CREATE TABLE ref.ur_sanction (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    entry_id      text NOT NULL,                     -- id
    entity_type   text NOT NULL CHECK (entity_type IN ('LEGAL_ENTITY', 'FOREIGN_ENTITY')),
    registered_on date,
    legal_form_code text,
    reg_no        text CHECK (reg_no ~ '^[459][0-9]{10}$'),  -- legal_entity_registration_number (LV)
    foreign_reg_no text,                             -- the same field when not a LV number
    entity_name   text,                              -- legal_entity_name (an entity, never a person)
    entity_country text,
    position_text_lv text,
    subject_legal_form_code text,
    subject_reg_no text CHECK (subject_reg_no ~ '^[459][0-9]{10}$'),
    subject_name  text,
    list          text,
    list_text     text,
    program       text,
    entry_date    date,
    legal_base    text,
    legal_base_url text,
    PRIMARY KEY (dataset_version_id, entry_id)
);
CREATE INDEX ur_sanction_reg ON ref.ur_sanction (dataset_version_id, reg_no);
CREATE INDEX ur_sanction_subject ON ref.ur_sanction (dataset_version_id, subject_reg_no);

-- Column 6 of the FID file (the sanctioned person) and rows without a Latvian
-- legal-entity reg. no. are never stored (D10).
CREATE TABLE ref.fid_sanction (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    row_no        integer NOT NULL,                  -- data row in the sheet (1-based)
    reg_no        text NOT NULL CHECK (reg_no ~ '^[459][0-9]{10}$'),
    entity_name   text,                              -- column 1 (an entity: it has a reg. no.)
    country       text,                              -- column 3
    asset_kind    text,                              -- column 4
    basis         text,                              -- column 5 (e.g. "... kontrole")
    sanctions_from text,                             -- column 7, as published
    legal_act     text,                              -- column 8
    first_published text,                            -- column 10, as published
    PRIMARY KEY (dataset_version_id, row_no)
);
CREATE INDEX fid_sanction_reg ON ref.fid_sanction (dataset_version_id, reg_no);

CREATE VIEW ref.ur_company_current AS
SELECT * FROM ref.ur_company WHERE dataset_version_id = ref.live_version('ur_companies');
CREATE VIEW ref.ur_insolvency_current AS
SELECT * FROM ref.ur_insolvency WHERE dataset_version_id = ref.live_version('ur_insolvency');
CREATE VIEW ref.ur_sanction_current AS
SELECT * FROM ref.ur_sanction WHERE dataset_version_id = ref.live_version('ur_sanctions');
CREATE VIEW ref.fid_sanction_current AS
SELECT * FROM ref.fid_sanction WHERE dataset_version_id = ref.live_version('fid_sanctions');

-- Applicant results (subject kind applicant): one result per applicant and
-- module per run, stored on the first target that names the applicant.
ALTER TABLE work.check_result DROP CONSTRAINT check_result_scope_check;
ALTER TABLE work.check_result
    ADD CONSTRAINT check_result_scope_check CHECK (scope IN ('target', 'unit', 'applicant'));

-- migrate:down

ALTER TABLE work.check_result DROP CONSTRAINT check_result_scope_check;
ALTER TABLE work.check_result
    ADD CONSTRAINT check_result_scope_check CHECK (scope IN ('target', 'unit'));
DROP VIEW ref.fid_sanction_current, ref.ur_sanction_current, ref.ur_insolvency_current,
    ref.ur_company_current;
DROP TABLE ref.fid_sanction, ref.ur_sanction, ref.ur_insolvency, ref.ur_company;
