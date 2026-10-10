-- migrate:up

-- BIS case objects are kept as published, including exact duplicate rows
-- (docs/data-sources.md §7.1). Links and every user-facing count work on
-- distinct cases: one link row per case and target, with the source rows that
-- give it in row_nos (evidence). Still deterministic per version pair (PLAN §6.5).
DROP VIEW ref.bis_object_link_current;
DROP FUNCTION ref.bis_object_best_match(bigint, bigint);
DROP FUNCTION ref.bis_links(bigint, bigint);

CREATE FUNCTION ref.bis_links(p_bis_version bigint, p_cadastre_text_version bigint)
RETURNS TABLE (
    case_number text, route text, match_type text,
    building_code text, parcel_code text, row_nos integer[]
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
    ), l (row_no, case_number, route, match_type, building_code, parcel_code) AS (
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
    )
    SELECT case_number, route, match_type, building_code, parcel_code,
           array_agg(row_no ORDER BY row_no)
    FROM l
    GROUP BY case_number, route, match_type, building_code, parcel_code
    ORDER BY case_number, route, match_type, building_code NULLS FIRST, parcel_code NULLS FIRST
$$;

-- Best match per distinct pilot case: exact > probable > address only > none,
-- taken over all of the case's objects.
CREATE FUNCTION ref.bis_case_best_match(p_bis_version bigint, p_cadastre_text_version bigint)
RETURNS TABLE (case_number text, best_match text, has_designation boolean)
LANGUAGE sql STABLE AS $$
    WITH links AS (
        SELECT case_number, bool_or(route = 'building_link') AS exact,
               bool_or(route = 'designation_prefix') AS probable,
               bool_or(route = 'address_code') AS address
        FROM ref.bis_links(p_bis_version, p_cadastre_text_version)
        GROUP BY case_number
    ), objects AS (
        SELECT case_number, bool_or(building_code IS NOT NULL) AS has_designation
        FROM ref.bis_object WHERE dataset_version_id = p_bis_version
        GROUP BY case_number
    )
    SELECT o.case_number,
           CASE WHEN l.exact THEN 'exact' WHEN l.probable THEN 'probable'
                WHEN l.address THEN 'address_only' ELSE 'none' END,
           o.has_designation
    FROM objects o LEFT JOIN links l USING (case_number)
    ORDER BY o.case_number
$$;

CREATE VIEW ref.bis_object_link_current AS
SELECT l.*, ref.live_version('bis_cases') AS bis_version_id,
       ref.live_version('cadastre_text') AS cadastre_text_version_id
FROM ref.bis_links(ref.live_version('bis_cases'), ref.live_version('cadastre_text')) l;

-- migrate:down

DROP VIEW ref.bis_object_link_current;
DROP FUNCTION ref.bis_case_best_match(bigint, bigint);
DROP FUNCTION ref.bis_links(bigint, bigint);

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

CREATE VIEW ref.bis_object_link_current AS
SELECT l.*, ref.live_version('bis_cases') AS bis_version_id,
       ref.live_version('cadastre_text') AS cadastre_text_version_id
FROM ref.bis_links(ref.live_version('bis_cases'), ref.live_version('cadastre_text')) l;
