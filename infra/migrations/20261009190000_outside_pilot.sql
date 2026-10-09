-- migrate:up

-- Map objects outside the pilot cities (docs/data-sources.md §5.2).
-- The Daugavpils map zip also carries the neighbouring cadastral group 4460…;
-- the group list (CadGroups_AT_0002000) includes it, so it cannot decide.
-- A map object is `outside_pilot` when BOTH hold:
--   * it has no record in the pilot cadastre text (for servitudes: their
--     parcel has none), and
--   * its interior point (ST_PointOnSurface) lies outside its city's boundary
--     (VARIS Pilsetas, live admin_boundaries version).
-- Registered objects are never excluded (a registered Jūrmala parcel lies
-- outside the VARIS boundary), nor are unregistered ones inside the city.
-- *_current_all keep every row with the flag; *_current are the pilot views.

DROP VIEW ref.parcel_current, ref.parcel_part_current, ref.building_current,
          ref.servitude_current;

CREATE VIEW ref.pilot_city AS
SELECT atvk, varis_code, name, geom FROM ref.admin_area_current WHERE level = 'pilseta';

CREATE VIEW ref.parcel_current_all AS
SELECT code, t.atvk, t.area_m2, t.varis_code, t.status_kind, t.land_purposes,
       g.geom, g.zip_atvk,
       t.code IS NOT NULL AS in_register, g.geom IS NOT NULL AS has_geometry,
       t.dataset_version_id AS text_version_id, g.dataset_version_id AS geom_version_id,
       (t.code IS NULL AND c.geom IS NOT NULL
        AND NOT ST_Within(ST_PointOnSurface(g.geom), c.geom)) AS outside_pilot
FROM (SELECT * FROM ref.parcel WHERE dataset_version_id = ref.live_version('cadastre_text')) t
FULL JOIN (SELECT * FROM ref.kk_parcel WHERE dataset_version_id = ref.live_version('cadastre_spatial')) g
    USING (code)
LEFT JOIN ref.pilot_city c ON c.atvk = g.zip_atvk;

CREATE VIEW ref.parcel_part_current_all AS
SELECT code, coalesce(t.parcel_code, g.parcel_code) AS parcel_code, t.area_m2, t.land_purposes,
       g.geom, g.zip_atvk, t.code IS NOT NULL AS in_register, g.geom IS NOT NULL AS has_geometry,
       t.dataset_version_id AS text_version_id, g.dataset_version_id AS geom_version_id,
       (t.code IS NULL AND c.geom IS NOT NULL
        AND NOT ST_Within(ST_PointOnSurface(g.geom), c.geom)) AS outside_pilot
FROM (SELECT * FROM ref.parcel_part WHERE dataset_version_id = ref.live_version('cadastre_text')) t
FULL JOIN (SELECT * FROM ref.kk_parcel_part WHERE dataset_version_id = ref.live_version('cadastre_spatial')) g
    USING (code)
LEFT JOIN ref.pilot_city c ON c.atvk = g.zip_atvk;

CREATE VIEW ref.building_current_all AS
SELECT code, t.name, t.use_kind_id, t.use_kind_name, t.building_kind_id, t.building_kind_name,
       t.area_m2, t.varis_code, t.not_exist, t.prereg, t.engineering_structure_type,
       g.object_kind, g.parcel_code AS map_parcel_code, g.geom, g.zip_atvk,
       t.code IS NOT NULL AS in_register, g.geom IS NOT NULL AS has_geometry,
       t.dataset_version_id AS text_version_id, g.dataset_version_id AS geom_version_id,
       (t.code IS NULL AND c.geom IS NOT NULL
        AND NOT ST_Within(ST_PointOnSurface(g.geom), c.geom)) AS outside_pilot
FROM (SELECT * FROM ref.building WHERE dataset_version_id = ref.live_version('cadastre_text')) t
FULL JOIN (SELECT * FROM ref.kk_building WHERE dataset_version_id = ref.live_version('cadastre_spatial')) g
    USING (code)
LEFT JOIN ref.pilot_city c ON c.atvk = g.zip_atvk;

CREATE VIEW ref.servitude_current_all AS
SELECT s.*,
       (NOT EXISTS (SELECT 1 FROM ref.parcel p
                    WHERE p.dataset_version_id = ref.live_version('cadastre_text')
                      AND p.code = s.parcel_code)
        AND c.geom IS NOT NULL
        AND NOT ST_Within(ST_PointOnSurface(s.geom), c.geom)) AS outside_pilot
FROM ref.kk_servitude s
LEFT JOIN ref.pilot_city c ON c.atvk = s.zip_atvk
WHERE s.dataset_version_id = ref.live_version('cadastre_spatial');

-- Pilot views (same names and columns as before, plus zip_atvk where missing).
CREATE VIEW ref.parcel_current AS
SELECT * FROM ref.parcel_current_all WHERE NOT outside_pilot;
CREATE VIEW ref.parcel_part_current AS
SELECT * FROM ref.parcel_part_current_all WHERE NOT outside_pilot;
CREATE VIEW ref.building_current AS
SELECT * FROM ref.building_current_all WHERE NOT outside_pilot;
CREATE VIEW ref.servitude_current AS
SELECT * FROM ref.servitude_current_all WHERE NOT outside_pilot;

-- What the pilot views leave out, for transparency.
CREATE VIEW ref.map_outside_pilot AS
SELECT 'parcel' AS kind, code, NULL::text AS parcel_code, zip_atvk, geom
FROM ref.parcel_current_all WHERE outside_pilot
UNION ALL
SELECT 'parcel_part', code, parcel_code, zip_atvk, geom
FROM ref.parcel_part_current_all WHERE outside_pilot
UNION ALL
SELECT 'building', code, map_parcel_code, zip_atvk, geom
FROM ref.building_current_all WHERE outside_pilot
UNION ALL
SELECT 'servitude', code, parcel_code, zip_atvk, geom
FROM ref.servitude_current_all WHERE outside_pilot;

-- migrate:down

DROP VIEW ref.map_outside_pilot, ref.parcel_current, ref.parcel_part_current,
          ref.building_current, ref.servitude_current, ref.parcel_current_all,
          ref.parcel_part_current_all, ref.building_current_all, ref.servitude_current_all,
          ref.pilot_city;

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

CREATE VIEW ref.servitude_current AS
SELECT * FROM ref.kk_servitude WHERE dataset_version_id = ref.live_version('cadastre_spatial');
