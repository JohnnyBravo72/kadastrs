-- migrate:up

-- Flood polygons subdivided into small pieces (ST_Subdivide, at most 256
-- vertices each), built once per version by the flood importer. Some flood
-- polygons have over a million vertices; intersections and distances against
-- the pieces take seconds instead of minutes (docs/data-sources.md §6.3).
-- ref.flood_zone stays the source of truth (areas, report geometry).
CREATE TABLE ref.flood_zone_part (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    layer        integer NOT NULL,
    role         text NOT NULL CHECK (role IN ('finding', 'coverage_mask')),
    object_id    text NOT NULL,
    part_no      integer NOT NULL,
    geom         geometry(Polygon, 10306) NOT NULL,
    PRIMARY KEY (dataset_version_id, layer, object_id, part_no)
);
CREATE INDEX flood_zone_part_geom ON ref.flood_zone_part USING gist (geom);

CREATE VIEW ref.flood_10y_part_current AS
SELECT * FROM ref.flood_zone_part
WHERE dataset_version_id = ref.live_version('flood_10y') AND role = 'finding';

CREATE VIEW ref.flood_coverage_part_current AS
SELECT * FROM ref.flood_zone_part
WHERE dataset_version_id = ref.live_version('flood_10y') AND role = 'coverage_mask';

-- migrate:down

DROP VIEW ref.flood_coverage_part_current, ref.flood_10y_part_current;
DROP TABLE ref.flood_zone_part;
