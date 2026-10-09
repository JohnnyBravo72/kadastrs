-- migrate:up

-- Processing notes recorded with a version (e.g. E7: 1 cm simplification,
-- make_valid, reprojection, coverage mask), with this import's counts.
ALTER TABLE dataset_version ADD COLUMN processing jsonb NOT NULL DEFAULT '[]';

-- flood_10y (D1 E7): pilot extent + 1 km. Layers 0 and 1 are findings (10-year
-- spring flood); layer 3 (200-year extent) is the coverage mask only, never a
-- finding (docs/decisions.md, E7). Geometry: EPSG:3059 -> lks92_to_lks2020().
CREATE TABLE ref.flood_zone (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    layer        integer NOT NULL,
    role         text NOT NULL CHECK (role IN ('finding', 'coverage_mask')),
    layer_name   text NOT NULL,
    object_id    text NOT NULL,                    -- ArcGIS objectid, as text
    source_area  double precision,                 -- st_area(shape) as published (EPSG:3059)
    parts        integer NOT NULL,
    geom         geometry(MultiPolygon, 10306) NOT NULL,
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, layer, object_id)
);
CREATE INDEX flood_zone_geom ON ref.flood_zone USING gist (geom);

CREATE VIEW ref.flood_10y_current AS
SELECT * FROM ref.flood_zone
WHERE dataset_version_id = ref.live_version('flood_10y') AND role = 'finding';

CREATE VIEW ref.flood_coverage_current AS
SELECT * FROM ref.flood_zone
WHERE dataset_version_id = ref.live_version('flood_10y') AND role = 'coverage_mask';

-- DAP nature (four sources, national). Key: GlobalID (unique in every layer).
CREATE TABLE ref.nature_area (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    global_id    text NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('protected_area', 'protected_area_zone',
                                               'microreserve', 'microreserve_buffer',
                                               'nature_monument', 'habitat')),
    source_layer text NOT NULL,
    dap_id       text,                             -- ID (not unique for habitats)
    mrcode       text,                             -- MRCODE (microreserves, buffer zones)
    name         text,
    category     text,
    atis_code    text,
    atis_description text,
    attributes   jsonb NOT NULL DEFAULT '{}',      -- the other DBF fields as published
    parts        integer NOT NULL,
    geom         geometry(MultiPolygon, 10306) NOT NULL,
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, global_id)
);
CREATE INDEX nature_area_geom ON ref.nature_area USING gist (geom);
CREATE INDEX nature_area_kind ON ref.nature_area (dataset_version_id, kind);

CREATE VIEW ref.nature_area_current AS
SELECT n.*, v.source_id
FROM ref.nature_area n
JOIN dataset_version v ON v.id = n.dataset_version_id AND v.status = 'live'
WHERE v.source_id IN ('nature_protected_areas', 'nature_microreserves',
                      'nature_monuments', 'nature_habitats');

-- migrate:down

DROP VIEW ref.nature_area_current, ref.flood_coverage_current, ref.flood_10y_current;
DROP TABLE ref.nature_area, ref.flood_zone;
ALTER TABLE dataset_version DROP COLUMN processing;
