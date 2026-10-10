-- migrate:up

-- BIS construction cases (Phase 2c, docs/data-sources.md §7). Pilot scope: case
-- objects whose ATVK is a pilot city or whose designation starts with the city's
-- cadastral territory code, and the cases they belong to. Codes are text (rule 8).
CREATE TABLE ref.bis_case (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    case_number  text NOT NULL,                     -- Buvniecibas_lietas_numurs (BIS-… or TMP-…)
    authority    text,                              -- Atbildigas_iestades_nosaukums
    application_kind text,                          -- Buvniecibas_iesnieguma_veids
    object_name  text,                              -- Objekta_nosaukums
    stage        text,                              -- Aktuala_stadija
    construction_kind text,                         -- Buvniecibas_veids
    created_date date,                              -- Lietas_izveidosanas_datums
    PRIMARY KEY (dataset_version_id, case_number)
);

-- One row per row of the case-objects CSV in the pilot (exact duplicate rows in
-- the source are kept as published; row_no is the CSV data row number).
CREATE TABLE ref.bis_object (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    row_no       integer NOT NULL,
    case_number  text NOT NULL,
    designation  text,                              -- Buves_kadastra_apzimejums (E2-restored)
    building_code text CHECK (building_code ~ '^[0-9]{14}$'),   -- designation, room groups cut to 14
    engineering_id text,                            -- Objekta_identifikators_inzenierbuvem
    melioration_number text,                        -- Melioracijas_kadastra_numurs
    lon          double precision,                  -- WGS84, as published
    lat          double precision,
    name         text,                              -- Buves_nosaukums
    address_text text,                              -- Buves_objekta_adreses_teksts
    address_code text CHECK (address_code ~ '^[0-9]{9}$'),      -- VARIS code
    construction_kind text,                         -- Buvniecibas_veids
    atvk         text CHECK (atvk ~ '^[0-9]{7}$'),  -- zero-padded (atvk_zero_padded)
    atvk_name    text,
    in_scope_by  text[] NOT NULL,                   -- {atvk, designation_prefix}
    flags        text[] NOT NULL DEFAULT '{}',      -- leading_zero_restored, room_group_cut, …
    PRIMARY KEY (dataset_version_id, row_no)
);
CREATE INDEX bis_object_building ON ref.bis_object (dataset_version_id, building_code);
CREATE INDEX bis_object_address ON ref.bis_object (dataset_version_id, address_code);
CREATE INDEX bis_object_case ON ref.bis_object (dataset_version_id, case_number);

-- The address route matches cadastre VARIS codes.
CREATE INDEX building_varis ON ref.building (dataset_version_id, varis_code);
CREATE INDEX parcel_varis ON ref.parcel (dataset_version_id, varis_code);

-- BIS object -> cadastre links (PLAN §6.1 module 5). Deterministic: the result
-- depends only on the two dataset versions passed in, so a check result that
-- stores both version ids can be rebuilt exactly (PLAN §6.5). Routes:
--   building_link       the designation is a cadastre building: exact_building, and
--                       building_on_parcel for each parcel of the cadastre's own link
--   designation_prefix  the building is not in the cadastre but the first 11 digits
--                       are a cadastre parcel: probable_parcel
--   address_code        the VARIS address code equals a cadastre building's or
--                       parcel's VARIS code: same_address_code (runs on every row)
CREATE FUNCTION ref.bis_links(p_bis_version bigint, p_cadastre_text_version bigint)
RETURNS TABLE (
    row_no integer, case_number text, route text, match_type text,
    building_code text, parcel_code text
)
LANGUAGE sql STABLE AS $$
    WITH o AS (
        SELECT * FROM ref.bis_object WHERE dataset_version_id = p_bis_version
    ), b AS (
        SELECT * FROM ref.building WHERE dataset_version_id = p_cadastre_text_version
    ), p AS (
        SELECT * FROM ref.parcel WHERE dataset_version_id = p_cadastre_text_version
    ), bp AS (
        SELECT * FROM ref.building_parcel WHERE dataset_version_id = p_cadastre_text_version
    )
    SELECT * FROM (
        SELECT o.row_no, o.case_number, 'building_link', 'exact_building', b.code, NULL::text
        FROM o JOIN b ON b.code = o.building_code
        UNION ALL
        SELECT o.row_no, o.case_number, 'building_link', 'building_on_parcel', b.code, bp.parcel_code
        FROM o JOIN b ON b.code = o.building_code
               JOIN bp ON bp.building_code = b.code
        UNION ALL
        SELECT o.row_no, o.case_number, 'designation_prefix', 'probable_parcel', o.building_code, p.code
        FROM o JOIN p ON p.code = left(o.building_code, 11)
        WHERE NOT EXISTS (SELECT 1 FROM b WHERE b.code = o.building_code)
        UNION ALL
        SELECT o.row_no, o.case_number, 'address_code', 'same_address_code', b.code, NULL
        FROM o JOIN b ON b.varis_code = o.address_code
        UNION ALL
        SELECT o.row_no, o.case_number, 'address_code', 'same_address_code', NULL, p.code
        FROM o JOIN p ON p.varis_code = o.address_code
    ) l (row_no, case_number, route, match_type, building_code, parcel_code)
    ORDER BY row_no, route, match_type, building_code NULLS FIRST, parcel_code NULLS FIRST
$$;

-- Best match per object row: exact (building link) > probable (prefix) > address only > none.
CREATE FUNCTION ref.bis_object_best_match(p_bis_version bigint, p_cadastre_text_version bigint)
RETURNS TABLE (row_no integer, case_number text, best_match text)
LANGUAGE sql STABLE AS $$
    SELECT o.row_no, o.case_number,
           CASE
               WHEN bool_or(l.route = 'building_link') THEN 'exact'
               WHEN bool_or(l.route = 'designation_prefix') THEN 'probable'
               WHEN bool_or(l.route = 'address_code') THEN 'address_only'
               ELSE 'none'
           END
    FROM ref.bis_object o
    LEFT JOIN ref.bis_links(p_bis_version, p_cadastre_text_version) l USING (row_no)
    WHERE o.dataset_version_id = p_bis_version
    GROUP BY o.row_no, o.case_number
    ORDER BY o.row_no
$$;

CREATE VIEW ref.bis_case_current AS
SELECT * FROM ref.bis_case WHERE dataset_version_id = ref.live_version('bis_cases');

CREATE VIEW ref.bis_object_current AS
SELECT * FROM ref.bis_object WHERE dataset_version_id = ref.live_version('bis_cases');

-- Links over the live versions; both version ids are columns, so a check result
-- can store them (PLAN §6.5).
CREATE VIEW ref.bis_object_link_current AS
SELECT l.*, ref.live_version('bis_cases') AS bis_version_id,
       ref.live_version('cadastre_text') AS cadastre_text_version_id
FROM ref.bis_links(ref.live_version('bis_cases'), ref.live_version('cadastre_text')) l;

-- migrate:down

DROP VIEW ref.bis_object_link_current, ref.bis_object_current, ref.bis_case_current;
DROP FUNCTION ref.bis_object_best_match(bigint, bigint);
DROP FUNCTION ref.bis_links(bigint, bigint);
DROP INDEX ref.parcel_varis, ref.building_varis;
DROP TABLE ref.bis_object, ref.bis_case;
