-- migrate:up

-- Phase 9: indexes and live views for whole-country performance and Martin tiles.
-- Search already uses prefix / trgm indexes (20261010200000). These help batch
-- joins and tile queries when import_scope=country.

CREATE INDEX IF NOT EXISTS parcel_atvk ON ref.parcel (dataset_version_id, atvk);
CREATE INDEX IF NOT EXISTS building_atvk ON ref.building (dataset_version_id, file_atvk);
CREATE INDEX IF NOT EXISTS kk_parcel_object ON ref.kk_parcel (dataset_version_id, object_code);
CREATE INDEX IF NOT EXISTS kk_building_object ON ref.kk_building (dataset_version_id, object_code);

-- Live cadastre geometry for Martin (always the live cadastre_spatial version).
CREATE OR REPLACE VIEW ref.kk_parcel_live AS
SELECT code, object_code, geom
FROM ref.kk_parcel
WHERE dataset_version_id = ref.live_version('cadastre_spatial');

CREATE OR REPLACE VIEW ref.kk_building_live AS
SELECT code, object_code, geom
FROM ref.kk_building
WHERE dataset_version_id = ref.live_version('cadastre_spatial');

-- migrate:down

DROP VIEW IF EXISTS ref.kk_building_live, ref.kk_parcel_live;
DROP INDEX IF EXISTS ref.kk_building_object, ref.kk_parcel_object,
                     ref.building_atvk, ref.parcel_atvk;
