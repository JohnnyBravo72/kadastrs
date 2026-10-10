-- migrate:up

-- Registered encumbrances (Phase 2c, PLAN §6.1 module 6; docs/data-sources.md §7.2-7.3).
-- Text and area only: no ATIS geometries are open. Codes are text (rule 8).

-- Current list: cadastre text encumbrance.zip, pilot members. One row per
-- EncumbranceRowData; row_no counts rows across the pilot members in file order.
CREATE TABLE ref.encumbrance (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    row_no       integer NOT NULL,
    object_code  text NOT NULL,                     -- ObjectCadastreNr (11, 15 or 14 digits)
    object_type  text NOT NULL CHECK (object_type IN ('PARCEL', 'PARCEL PART', 'BUILDING')),
    file_atvk    text NOT NULL CHECK (file_atvk ~ '^[0-9]{7}$'),
    kind_id      text NOT NULL CHECK (kind_id ~ '^[0-9]{10}$'),   -- EncumbranceKindId (ATIS code)
    kind_name    text,                              -- EncumbranceKindName as in the file
    encumbrance_nr text,
    establish_date date,
    area         numeric,                           -- EncumbranceArea
    measure      text,                              -- EncumbranceMeasure (ha, m, km)
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, row_no)
);
CREATE INDEX encumbrance_object ON ref.encumbrance (dataset_version_id, object_code);
CREATE INDEX encumbrance_kind ON ref.encumbrance (dataset_version_id, kind_id);

-- ATIS and cadastre encumbrance classifier, as published (Jā / Nē / Neattiecas kept as text).
CREATE TABLE ref.atis_classifier (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    code         text NOT NULL CHECK (code ~ '^[0-9]{10}$'),       -- Kods
    data_kind    text NOT NULL,                     -- Dati (ATIS / Kadastrs)
    group_name   text,                              -- Grupa
    kind         text,                              -- Veids
    description  text NOT NULL,                     -- Apraksts
    elements     text,                              -- Elements (geometry kinds in ATIS)
    in_cadastre  text,                              -- DatiKadastra
    public_data  text,                              -- Visparpieejami_dati
    restricted_data text,                           -- Ierobezoti_dati
    PRIMARY KEY (dataset_version_id, code)
);

-- Frozen list of encumbrances registered until 2025-01-31 (pilot rows of the
-- Latgale, Rīga and Zemgale files). Imported because part of it is not in the
-- current list (§7.3); every row carries the flag `frozen` and its as-of date.
CREATE TABLE ref.encumbrance_frozen (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    file_role    text NOT NULL,                     -- config/etl.yaml role, e.g. zemgale_parcel
    row_no       integer NOT NULL,                  -- CSV data row number in that file
    object_code  text NOT NULL,                     -- CAD_NR (11 or 15 digits)
    object_kind  text NOT NULL CHECK (object_kind IN ('parcel', 'parcel_part')),
    region_kind  text,                              -- ADMRKIND
    territory    text,                              -- ADMTKIND (city name)
    code         text NOT NULL,                     -- ENCD_ID as published (10, 8 or 6 digits)
    description  text,
    encumbrance_nr text,                            -- NR
    establish_date date,                            -- ENC_DATE
    area         numeric,                           -- ENC_SIZE
    measure      text,
    frozen_as_of date NOT NULL,                     -- 2025-01-31 (file date)
    flags        text[] NOT NULL DEFAULT '{}' CHECK ('frozen' = ANY (flags)),
    PRIMARY KEY (dataset_version_id, file_role, row_no)
);
CREATE INDEX encumbrance_frozen_object ON ref.encumbrance_frozen (dataset_version_id, object_code);

CREATE VIEW ref.atis_classifier_current AS
SELECT * FROM ref.atis_classifier WHERE dataset_version_id = ref.live_version('atis_classifier');

CREATE VIEW ref.encumbrance_current AS
SELECT e.*, c.description AS classifier_description, c.group_name AS classifier_group,
       c.restricted_data AS classifier_restricted, c.dataset_version_id AS classifier_version_id
FROM ref.encumbrance e
LEFT JOIN ref.atis_classifier_current c ON c.code = e.kind_id
WHERE e.dataset_version_id = ref.live_version('cadastre_encumbrances');

-- Status of each frozen row against a current encumbrance version and a cadastre
-- text version. Deterministic given the three version ids (PLAN §6.5):
--   in_current          the same object has the same code in the current list
--   object_in_cadastre  the parcel or parcel part still exists in the cadastre text
--   frozen_only         object exists, code not in the current list: module 6 shows
--                       it separately as "reģistrēts līdz 31.01.2025; pašreizējā sarakstā nav"
CREATE FUNCTION ref.encumbrance_frozen_status(
    p_frozen_version bigint, p_encumbrance_version bigint, p_cadastre_text_version bigint
)
RETURNS TABLE (
    file_role text, row_no integer, object_code text, code text,
    in_current boolean, object_in_cadastre boolean, frozen_only boolean
)
LANGUAGE sql STABLE AS $$
    SELECT f.file_role, f.row_no, f.object_code, f.code, s.in_current, s.object_in_cadastre,
           s.object_in_cadastre AND NOT s.in_current
    FROM ref.encumbrance_frozen f
    CROSS JOIN LATERAL (
        SELECT EXISTS (
                   SELECT 1 FROM ref.encumbrance e
                   WHERE e.dataset_version_id = p_encumbrance_version
                     AND e.object_code = f.object_code AND e.kind_id = f.code
               ) AS in_current,
               EXISTS (
                   SELECT 1 FROM ref.parcel p
                   WHERE p.dataset_version_id = p_cadastre_text_version AND p.code = f.object_code
                   UNION ALL
                   SELECT 1 FROM ref.parcel_part pp
                   WHERE pp.dataset_version_id = p_cadastre_text_version AND pp.code = f.object_code
               ) AS object_in_cadastre
    ) s
    WHERE f.dataset_version_id = p_frozen_version
    ORDER BY f.file_role, f.row_no
$$;

CREATE VIEW ref.encumbrance_frozen_current AS
SELECT f.*, s.in_current, s.object_in_cadastre, s.frozen_only,
       ref.live_version('cadastre_encumbrances') AS encumbrance_version_id,
       ref.live_version('cadastre_text') AS cadastre_text_version_id
FROM ref.encumbrance_frozen f
JOIN ref.encumbrance_frozen_status(
         ref.live_version('encumbrances_frozen'), ref.live_version('cadastre_encumbrances'),
         ref.live_version('cadastre_text')) s
    USING (file_role, row_no)
WHERE f.dataset_version_id = ref.live_version('encumbrances_frozen');

-- migrate:down

DROP VIEW ref.encumbrance_frozen_current, ref.encumbrance_current, ref.atis_classifier_current;
DROP FUNCTION ref.encumbrance_frozen_status(bigint, bigint, bigint);
DROP TABLE ref.encumbrance_frozen, ref.atis_classifier, ref.encumbrance;
