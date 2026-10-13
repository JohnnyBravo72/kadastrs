-- migrate:up

-- Module 8 zoning (TAPIS WFS, D1 E4; docs/data-sources.md §3.7).
-- Findings: funkcionalais_zonejums. Coverage mask: speka_esosu_planojumu_teritorijas.
-- Geometry: EPSG:3059 -> lks92_to_lks2020() on import. Codes are text (rule 8).

CREATE TABLE ref.zoning_zone (
    dataset_version_id bigint NOT NULL REFERENCES dataset_version (id),
    role         text NOT NULL CHECK (role IN ('finding', 'coverage_mask')),
    object_id    text NOT NULL,                    -- tapis_id (finding) or dok_id:atvk (mask)
    group_code   text,                             -- grupa_kods (finding)
    group_name   text,                             -- grupa_nos / veids
    zone_code    text,                             -- kods
    zone_index   text,                             -- indekss (DzS, JC, …)
    zone_name    text,                             -- nosaukums (often empty)
    atvk         text,
    dok_id       text,
    dok_name     text,
    parts        integer NOT NULL,
    geom         geometry(MultiPolygon, 10306) NOT NULL,
    flags        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_version_id, role, object_id)
);
CREATE INDEX zoning_zone_geom ON ref.zoning_zone USING gist (geom);
CREATE INDEX zoning_zone_role ON ref.zoning_zone (dataset_version_id, role);

-- Subdivided parts for fast spatial queries (same pattern as flood_zone_part).
CREATE TABLE ref.zoning_zone_part (
    dataset_version_id bigint NOT NULL,
    role         text NOT NULL,
    object_id    text NOT NULL,
    part_no      integer NOT NULL,
    geom         geometry(Polygon, 10306) NOT NULL,
    PRIMARY KEY (dataset_version_id, role, object_id, part_no),
    FOREIGN KEY (dataset_version_id, role, object_id)
        REFERENCES ref.zoning_zone (dataset_version_id, role, object_id) ON DELETE CASCADE
);
CREATE INDEX zoning_zone_part_geom ON ref.zoning_zone_part USING gist (geom);

CREATE VIEW ref.zoning_finding_current AS
SELECT * FROM ref.zoning_zone
WHERE dataset_version_id = ref.live_version('tapis_zoning') AND role = 'finding';

CREATE VIEW ref.zoning_coverage_current AS
SELECT * FROM ref.zoning_zone
WHERE dataset_version_id = ref.live_version('tapis_zoning') AND role = 'coverage_mask';

-- migrate:down

DROP VIEW ref.zoning_coverage_current, ref.zoning_finding_current;
DROP TABLE ref.zoning_zone_part, ref.zoning_zone;
