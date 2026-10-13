-- migrate:up

-- Phase 8b (PLAN.md §6.1 modules 7, 10–13, 18; docs/decisions.md D11).
-- CLAUDE.md rule 5 enforced in the tables: legal-entity reg. nos only where
-- applicable; no columns for natural persons' names, birth dates or personal
-- codes; codes are text (rule 8).

-- 7 Ownership (pilot members of ownership.zip; type only, D5)
CREATE TABLE ref.ownership (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    object_cadastre_nr text NOT NULL,                 -- property / parcel / building / …
    object_type        text NOT NULL,                 -- PROPERTY, PARCEL, BUILDING, …
    ownership_status   text NOT NULL,                 -- Īpašnieks, Tiesiskais valdītājs, …
    person_status      text NOT NULL CHECK (
        person_status IN (
            'fiziska persona', 'juridiska persona', 'valsts', 'pašvaldība', 'cits'
        )
    ),
    person_kind        text NOT NULL CHECK (
        person_kind IN ('natural', 'legal', 'state', 'municipality', 'other')
    ),
    PRIMARY KEY (dataset_version_id, object_cadastre_nr, ownership_status, person_status)
);
CREATE INDEX ownership_object ON ref.ownership (dataset_version_id, object_cadastre_nr);

-- 10 VID taxpayer rating (name never stored, D11)
CREATE TABLE ref.vid_rating (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    reg_no        text NOT NULL CHECK (reg_no ~ '^[459][0-9]{10}$'),
    rating        text NOT NULL CHECK (rating IN ('A', 'B', 'C', 'J', 'N')),
    explanation   text,
    rated_on      date NOT NULL,
    PRIMARY KEY (dataset_version_id, reg_no)
);

-- 11 De minimis (legal-entity rows only; person_title / project_title never stored)
CREATE TABLE ref.deminimis_aid (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    row_no        integer NOT NULL,
    reg_no        text NOT NULL CHECK (reg_no ~ '^[459][0-9]{10}$'),
    assign_date   date NOT NULL,
    assigner      text,
    programme     text,
    amount        numeric NOT NULL,
    regulation    text NOT NULL,                      -- regul_title as published
    regulation_key text NOT NULL,                     -- e.g. 2023/2831
    instrument    text,
    PRIMARY KEY (dataset_version_id, row_no)
);
CREATE INDEX deminimis_reg ON ref.deminimis_aid (dataset_version_id, reg_no);

-- 12 EU co-financed projects (three CFLA periods)
CREATE TABLE ref.eu_project (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    period        text NOT NULL CHECK (period IN ('2014-20', '2021-27', 'RRF')),
    project_no    text NOT NULL,
    title         text,                               -- NULL for natural-person / IK rows
    status        text,
    applicant_type text,
    applicant_reg_no text CHECK (applicant_reg_no ~ '^[459][0-9]{10}$'),
    applicant_name text,                              -- legal entities that are not IK only
    is_natural_or_ik boolean NOT NULL DEFAULT false,
    started_on    date,
    ended_on      date,
    fund          text,
    measure_no    text,
    measure_name  text,
    total_cost    numeric,
    eu_funding    numeric,
    monitoring_years integer,
    updated_on    date,
    PRIMARY KEY (dataset_version_id, period, project_no),
    -- natural-person / IK rows: no name, title, reg. no. or address (D11)
    CHECK (
        NOT is_natural_or_ik
        OR (title IS NULL AND applicant_name IS NULL AND applicant_reg_no IS NULL)
    )
);
CREATE INDEX eu_project_applicant ON ref.eu_project (dataset_version_id, applicant_reg_no);

CREATE TABLE ref.eu_project_location (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    period        text NOT NULL CHECK (period IN ('2014-20', '2021-27', 'RRF')),
    project_no    text NOT NULL,
    row_no        integer NOT NULL,
    cadastre_nr   text,                               -- text; leading zeros kept (E2)
    address       text,                               -- only for legal-entity (non-IK) projects
    region        text,
    PRIMARY KEY (dataset_version_id, period, project_no, row_no)
);
CREATE INDEX eu_location_cadastre ON ref.eu_project_location (dataset_version_id, cadastre_nr);

CREATE TABLE ref.eu_project_partner (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    period        text NOT NULL CHECK (period IN ('2014-20', '2021-27', 'RRF')),
    project_no    text NOT NULL,
    row_no        integer NOT NULL,
    reg_no        text NOT NULL CHECK (reg_no ~ '^[459][0-9]{10}$'),  -- never names (D11)
    PRIMARY KEY (dataset_version_id, period, project_no, row_no)
);

-- 13 EIS procurement (winner name never stored; winner reg. no. legal-entity only)
CREATE TABLE ref.eis_contract (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    year          integer NOT NULL,
    row_no        integer NOT NULL,
    procurement_id text,
    procurement_no text,
    title         text,
    buyer_reg_no  text CHECK (buyer_reg_no ~ '^[459][0-9]{10}$'),
    buyer_name    text,                               -- contracting authority (legal entity)
    winner_reg_no text CHECK (winner_reg_no ~ '^[459][0-9]{10}$'),
    winner_country text,
    status        text,
    amount        numeric,
    currency      text,
    signed_on     date,
    ended_on      date,
    eis_url       text,
    iub_url       text,
    PRIMARY KEY (dataset_version_id, year, row_no)
);
CREATE INDEX eis_buyer ON ref.eis_contract (dataset_version_id, buyer_reg_no);
CREATE INDEX eis_winner ON ref.eis_contract (dataset_version_id, winner_reg_no);

-- 18 FID frozen real estate (TA, VZD); no person columns (D11)
CREATE TABLE ref.fid_frozen_property (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    row_no        integer NOT NULL,
    cadastre_nr   text NOT NULL,                      -- text; E2 leading zeros
    asset_type    text,
    subject_link  text,                               -- column 5
    holder_reg_no text CHECK (holder_reg_no ~ '^[459][0-9]{10}$'),  -- col 2 when legal entity
    mark_ta       text,
    mark_vzd      text,
    basis         text,
    sanctions_from text,
    legal_act     text,
    fid_checked   text,
    published_on  date,
    PRIMARY KEY (dataset_version_id, row_no)
);
CREATE INDEX fid_frozen_cadastre ON ref.fid_frozen_property (dataset_version_id, cadastre_nr);

CREATE VIEW ref.ownership_current AS
SELECT * FROM ref.ownership WHERE dataset_version_id = ref.live_version('cadastre_ownership');
CREATE VIEW ref.vid_rating_current AS
SELECT * FROM ref.vid_rating WHERE dataset_version_id = ref.live_version('vid_rating');
CREATE VIEW ref.deminimis_aid_current AS
SELECT * FROM ref.deminimis_aid WHERE dataset_version_id = ref.live_version('deminimis');
CREATE VIEW ref.eu_project_current AS
SELECT * FROM ref.eu_project WHERE dataset_version_id = ref.live_version('eu_projects');
CREATE VIEW ref.eu_project_location_current AS
SELECT * FROM ref.eu_project_location WHERE dataset_version_id = ref.live_version('eu_projects');
CREATE VIEW ref.eu_project_partner_current AS
SELECT * FROM ref.eu_project_partner WHERE dataset_version_id = ref.live_version('eu_projects');
CREATE VIEW ref.eis_contract_current AS
SELECT * FROM ref.eis_contract WHERE dataset_version_id = ref.live_version('eis_procurement');
CREATE VIEW ref.fid_frozen_property_current AS
SELECT * FROM ref.fid_frozen_property WHERE dataset_version_id = ref.live_version('fid_frozen_property');

-- migrate:down

DROP VIEW ref.fid_frozen_property_current, ref.eis_contract_current,
    ref.eu_project_partner_current, ref.eu_project_location_current, ref.eu_project_current,
    ref.deminimis_aid_current, ref.vid_rating_current, ref.ownership_current;
DROP TABLE ref.fid_frozen_property, ref.eis_contract, ref.eu_project_partner,
    ref.eu_project_location, ref.eu_project, ref.deminimis_aid, ref.vid_rating, ref.ownership;
