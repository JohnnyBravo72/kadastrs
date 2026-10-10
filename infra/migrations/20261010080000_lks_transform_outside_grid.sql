-- migrate:up

-- The LĢIA grid (EPSG:10838) covers Latvia's land area. DAP marine protected
-- areas and habitats reach into the Baltic Sea and the Gulf of Riga, where the
-- strict lks92_to_lks2020() raises PROJ error 2052 "Coordinate to transform
-- falls outside grid" (found 2026-10-10, docs/data-sources.md §6.4).
--
-- lks92_to_lks2020_checked() tries the strict function first. Only on that
-- error it uses the same pipeline with the grid chain
-- `lv_lgia_lks92to2020.tif,@null`: the LĢIA grid where it has values, a zero
-- shift outside it (error at most the datum shift itself, ~10 cm, offshore
-- only), and reports outside_grid = true so importers can flag the object.
-- The LĢIA grid stays mandatory: a missing grid still raises (any other error
-- is re-raised), so the silent null-shift problem of D9 cannot come back.

CREATE TYPE lks_transform AS (geom geometry, outside_grid boolean);

CREATE FUNCTION lks92_to_lks2020_checked(geom geometry)
RETURNS lks_transform
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
AS $$
BEGIN
    RETURN ROW(lks92_to_lks2020(geom), false)::lks_transform;
EXCEPTION WHEN internal_error THEN
    IF SQLERRM NOT LIKE '%outside grid%' THEN
        RAISE;
    END IF;
    RETURN ROW(ST_TransformPipeline(
        geom,
        '+proj=pipeline'
        ' +step +inv +proj=tmerc +lat_0=0 +lon_0=24 +k=0.9996 +x_0=500000 +y_0=-6000000 +ellps=GRS80'
        ' +step +proj=hgridshift +grids=lv_lgia_lks92to2020.tif,@null'
        ' +step +proj=tmerc +lat_0=0 +lon_0=24 +k=0.9996 +x_0=500000 +y_0=-6000000 +ellps=GRS80',
        10306), true)::lks_transform;
END;
$$;

COMMENT ON FUNCTION lks92_to_lks2020_checked(geometry) IS
    'EPSG:3059 -> 10306 via EPSG:10838; vertices outside the LĢIA grid get a zero shift and outside_grid = true; a missing grid raises.';

-- migrate:down

DROP FUNCTION lks92_to_lks2020_checked(geometry);
DROP TYPE lks_transform;
