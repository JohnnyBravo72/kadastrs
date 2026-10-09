-- migrate:up

-- Per-file details of an import (URL, CKAN last_modified, size, SHA-256; for
-- Range-fetched zips the central-directory fingerprint and the members).
-- docs/data-sources.md §5.4.
ALTER TABLE dataset_version ADD COLUMN files jsonb NOT NULL DEFAULT '[]';
ALTER TABLE import_log ADD COLUMN files jsonb NOT NULL DEFAULT '[]';

-- Reference data (PLAN.md §4). Every row belongs to one dataset_version; a
-- version is a full snapshot (rule E8). Codes and designations are text
-- (rule 8). Geometries are EPSG:10306 (D9). `flags` holds per-row notes such
-- as leading_zero_restored (rule E2).
CREATE SCHEMA ref;

CREATE FUNCTION ref.live_version(p_source text) RETURNS bigint
LANGUAGE sql STABLE AS $$
    SELECT id FROM public.dataset_version WHERE source_id = p_source AND status = 'live'
$$;

-- --- admin_boundaries (VARIS aw_shp.zip) ---------------------------------------
CREATE TABLE ref.admin_area (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    varis_code   text NOT NULL CHECK (varis_code ~ '^[0-9]{9}$'),
    level        text NOT NULL CHECK (level IN ('novads', 'pilseta', 'pagasts')),
    name         text NOT NULL,
    atvk         text,                              -- ATRIB: 7-digit ATVK code
    parent_code  text,
    status       text NOT NULL,
    geom         geometry(MultiPolygon, 10306) NOT NULL,
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, varis_code)
);
CREATE INDEX admin_area_geom ON ref.admin_area USING gist (geom);

-- --- varis_addresses (aw_eka.csv + aw_eka_his.csv), pilot cities ----------------
CREATE TABLE ref.address (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    code         text NOT NULL CHECK (code ~ '^[0-9]{9}$'),
    status       text NOT NULL CHECK (status IN ('EKS', 'DEL')),   -- ERR is never imported
    type_code    text NOT NULL,                     -- TIPS_CD
    parent_code  text NOT NULL,                     -- VKUR_CD (street or city)
    parent_type  text NOT NULL,                     -- VKUR_TIPS
    city_code    text NOT NULL,                     -- pilot city (VARIS code)
    city_atvk    text NOT NULL CHECK (city_atvk ~ '^[0-9]{7}$'),
    name         text,                              -- NOSAUKUMS (house name or number)
    sort_name    text,
    postal_code  text,                              -- ATRIB
    full_text    text NOT NULL,                     -- STD
    for_build    text,
    plan_adr     text,
    date_start   date,
    date_modified date,
    date_end     date,
    geom         geometry(Point, 10306),            -- EKS only; from KOORD_Y (E) / KOORD_X (N)
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, code),
    CHECK ((status = 'EKS') = (geom IS NOT NULL))
);
CREATE INDEX address_geom ON ref.address USING gist (geom);

CREATE TABLE ref.address_history (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    row_no       integer NOT NULL,                  -- position in aw_eka_his.csv
    code         text NOT NULL,
    code_his     text,                              -- KODS_HIS
    type_code    text,
    full_text    text,                              -- earlier STD
    name         text,
    parent_code  text,
    parent_type  text,
    date_start   date,
    date_modified date,
    date_end     date,
    PRIMARY KEY (dataset_version_id, row_no)
);
CREATE INDEX address_history_code ON ref.address_history (dataset_version_id, code);
CREATE INDEX address_history_code_his ON ref.address_history (dataset_version_id, code_his);

-- --- cadastre_spatial (kk_shp.zip per pilot city) ------------------------------
-- One row per key after normalisation (rule E5): make_valid, polygon parts
-- only, union per key, MultiPolygon. `parts` = source records merged.
CREATE TABLE ref.kk_parcel (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    code         text NOT NULL,
    object_code  text NOT NULL CHECK (object_code ~ '^7'),
    group_code   text,
    area_scale   double precision,
    geom_date    date,                              -- GEOM_ACT_D
    zip_atvk     text NOT NULL,                     -- which city zip it came from
    parts        integer NOT NULL,
    geom         geometry(MultiPolygon, 10306) NOT NULL,
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, code)
);
CREATE INDEX kk_parcel_geom ON ref.kk_parcel USING gist (geom);

CREATE TABLE ref.kk_parcel_part (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    code         text NOT NULL,
    object_code  text NOT NULL CHECK (object_code ~ '^7'),
    parcel_code  text,
    group_code   text,
    area_scale   double precision,
    zip_atvk     text NOT NULL,
    parts        integer NOT NULL,
    geom         geometry(MultiPolygon, 10306) NOT NULL,
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, code)
);
CREATE INDEX kk_parcel_part_geom ON ref.kk_parcel_part USING gist (geom);

-- Buildings (OBJECTCODE 5…, KKBuilding) and engineering structures
-- (OBJECTCODE 6…, KKEngineeringStructurePoly): both have 14-digit designations.
CREATE TABLE ref.kk_building (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    code         text NOT NULL,
    object_code  text NOT NULL,
    object_kind  text NOT NULL CHECK (object_kind IN ('building', 'engineering_structure')),
    parcel_code  text,
    group_code   text,
    area_scale   double precision,
    zip_atvk     text NOT NULL,
    parts        integer NOT NULL,
    geom         geometry(MultiPolygon, 10306) NOT NULL,
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, code),
    CHECK ((object_kind = 'building') = (object_code ~ '^5')),
    CHECK ((object_kind = 'engineering_structure') = (object_code ~ '^6'))
);
CREATE INDEX kk_building_geom ON ref.kk_building USING gist (geom);

-- Servitudes (KKWayRestriction): one servitude spans many parcels, key = CODE + PARCELCODE.
CREATE TABLE ref.kk_servitude (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    code         text NOT NULL,
    parcel_code  text NOT NULL,
    object_code  text NOT NULL CHECK (object_code ~ '^7'),
    group_code   text,
    area_scale   double precision,
    zip_atvk     text NOT NULL,
    parts        integer NOT NULL,
    geom         geometry(MultiPolygon, 10306) NOT NULL,
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, code, parcel_code)
);
CREATE INDEX kk_servitude_geom ON ref.kk_servitude USING gist (geom);

-- --- cadastre_text (pilot members of the national XML zips) ----------------------
CREATE TABLE ref.parcel (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    code         text NOT NULL,
    atvk         text NOT NULL,                     -- ATVKCode
    area_m2      numeric,
    varis_code   text,
    status_kind  text,                              -- ParcelStatusKindName
    land_purposes jsonb NOT NULL DEFAULT '[]',      -- [{id, name, area}]
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, code)
);

CREATE TABLE ref.parcel_part (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    code         text NOT NULL,
    parcel_code  text,
    area_m2      numeric,
    land_purposes jsonb NOT NULL DEFAULT '[]',
    file_atvk    text NOT NULL,
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, code)
);

CREATE TABLE ref.building (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    code         text NOT NULL,
    file_atvk    text NOT NULL,
    name         text,
    use_kind_id  text,
    use_kind_name text,
    building_kind_id text,
    building_kind_name text,
    area_m2      numeric,
    construction_area_m2 numeric,
    ground_floors integer,
    underground_floors integer,
    exploit_year integer,
    acception_years text,
    varis_code   text,
    not_exist    boolean NOT NULL,                  -- NotExist "Būve apvidū nav konstatēta"
    prereg       boolean NOT NULL,                  -- Prereg "Pirmsreģistrēta būve"
    engineering_structure_type text,
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, code)
);

-- Building -> parcel links: ObjectRelation (primary) and ParcelCadastreNrList.
CREATE TABLE ref.building_parcel (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    building_code text NOT NULL,
    parcel_code  text NOT NULL,
    relation     text NOT NULL CHECK (relation IN ('object_relation', 'parcel_list')),
    PRIMARY KEY (dataset_version_id, building_code, parcel_code)
);
CREATE INDEX building_parcel_parcel ON ref.building_parcel (dataset_version_id, parcel_code);

CREATE TABLE ref.property (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    number       text NOT NULL,                     -- ProCadastreNr
    file_atvk    text NOT NULL,
    kind         text,                              -- PropertyKind
    name         text,
    parcel_total_area_m2 numeric,
    premise_group_total_area_m2 numeric,
    share_flat_property text,
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, number)
);

CREATE TABLE ref.property_object (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    property_number text NOT NULL,
    object_code  text NOT NULL,
    object_kind  text NOT NULL,                     -- ObjectKindData
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, property_number, object_code)
);
CREATE INDEX property_object_object ON ref.property_object (dataset_version_id, object_code);

-- --- current views: live text joined with live geometry ------------------------
CREATE VIEW ref.parcel_current AS
SELECT code, t.atvk, t.area_m2, t.varis_code, t.status_kind, t.land_purposes,
       g.geom, g.zip_atvk,
       t.code IS NOT NULL AS in_register, g.geom IS NOT NULL AS has_geometry,
       t.dataset_version_id AS text_version_id, g.dataset_version_id AS geom_version_id
FROM (SELECT * FROM ref.parcel WHERE dataset_version_id = ref.live_version('cadastre_text')) t
FULL JOIN (SELECT * FROM ref.kk_parcel WHERE dataset_version_id = ref.live_version('cadastre_spatial')) g
    USING (code);

CREATE VIEW ref.parcel_part_current AS
SELECT code, coalesce(t.parcel_code, g.parcel_code) AS parcel_code, t.area_m2, t.land_purposes,
       g.geom, t.code IS NOT NULL AS in_register, g.geom IS NOT NULL AS has_geometry,
       t.dataset_version_id AS text_version_id, g.dataset_version_id AS geom_version_id
FROM (SELECT * FROM ref.parcel_part WHERE dataset_version_id = ref.live_version('cadastre_text')) t
FULL JOIN (SELECT * FROM ref.kk_parcel_part WHERE dataset_version_id = ref.live_version('cadastre_spatial')) g
    USING (code);

CREATE VIEW ref.building_current AS
SELECT code, t.name, t.use_kind_id, t.use_kind_name, t.building_kind_id, t.building_kind_name,
       t.area_m2, t.varis_code, t.not_exist, t.prereg, t.engineering_structure_type,
       g.object_kind, g.parcel_code AS map_parcel_code, g.geom,
       t.code IS NOT NULL AS in_register, g.geom IS NOT NULL AS has_geometry,
       t.dataset_version_id AS text_version_id, g.dataset_version_id AS geom_version_id
FROM (SELECT * FROM ref.building WHERE dataset_version_id = ref.live_version('cadastre_text')) t
FULL JOIN (SELECT * FROM ref.kk_building WHERE dataset_version_id = ref.live_version('cadastre_spatial')) g
    USING (code);

CREATE VIEW ref.building_parcel_current AS
SELECT * FROM ref.building_parcel WHERE dataset_version_id = ref.live_version('cadastre_text');

CREATE VIEW ref.property_current AS
SELECT * FROM ref.property WHERE dataset_version_id = ref.live_version('cadastre_text');

CREATE VIEW ref.property_object_current AS
SELECT * FROM ref.property_object WHERE dataset_version_id = ref.live_version('cadastre_text');

CREATE VIEW ref.servitude_current AS
SELECT * FROM ref.kk_servitude WHERE dataset_version_id = ref.live_version('cadastre_spatial');

CREATE VIEW ref.address_current AS
SELECT * FROM ref.address WHERE dataset_version_id = ref.live_version('varis_addresses');

CREATE VIEW ref.address_history_current AS
SELECT * FROM ref.address_history WHERE dataset_version_id = ref.live_version('varis_addresses');

CREATE VIEW ref.admin_area_current AS
SELECT * FROM ref.admin_area WHERE dataset_version_id = ref.live_version('admin_boundaries');

-- migrate:down

DROP SCHEMA ref CASCADE;
ALTER TABLE import_log DROP COLUMN files;
ALTER TABLE dataset_version DROP COLUMN files;
