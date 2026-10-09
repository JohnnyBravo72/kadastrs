-- migrate:up

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- PostGIS 3.6.4's spatial_ref_sys predates LKS-2020. ST_Transform resolves CRSs
-- through auth_name/auth_srid (PROJ 9.8.1 knows both codes); srtext and proj4text
-- are informational. Generated with PROJ 9.8.1 (pyproj 3.8.0), WKT1_GDAL.
-- ON CONFLICT DO NOTHING: if a later PostGIS ships the rows, its rows win.
INSERT INTO spatial_ref_sys (srid, auth_name, auth_srid, srtext, proj4text) VALUES
(10305, 'EPSG', 10305,
 'GEOGCS["LKS-2020",DATUM["Latvian_coordinate_system_2020",SPHEROID["GRS 1980",6378137,298.257222101,AUTHORITY["EPSG","7019"]],AUTHORITY["EPSG","1356"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","10305"]]',
 '+proj=longlat +ellps=GRS80 +no_defs'),
(10306, 'EPSG', 10306,
 'PROJCS["LKS-2020 / Latvia TM",GEOGCS["LKS-2020",DATUM["Latvian_coordinate_system_2020",SPHEROID["GRS 1980",6378137,298.257222101,AUTHORITY["EPSG","7019"]],AUTHORITY["EPSG","1356"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","10305"]],PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",24],PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],PARAMETER["false_northing",-6000000],UNIT["metre",1,AUTHORITY["EPSG","9001"]],AUTHORITY["EPSG","10306"]]',
 '+proj=tmerc +lat_0=0 +lon_0=24 +k=0.9996 +x_0=500000 +y_0=-6000000 +ellps=GRS80 +units=m +no_defs')
ON CONFLICT (srid) DO NOTHING;

-- The one way imports transform LKS-92 / Latvia TM (EPSG:3059) to LKS-2020 /
-- Latvia TM (EPSG:10306): EPSG:10838 with its NTv2 grid, as an explicit pipeline.
-- Plain ST_Transform(geom, 10306) silently falls back to a null shift (~9.5 cm
-- error) when the grid is missing; this function raises an error instead.
-- Pipeline = PROJ 9.8.1's definition of "Inverse of Latvian Transverse Mercator
-- + LKS-92 to LKS-2020 (1) + Latvian Transverse Mercator".
CREATE FUNCTION lks92_to_lks2020(geom geometry)
RETURNS geometry
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
AS $$
BEGIN
    IF ST_SRID(geom) <> 3059 THEN
        RAISE EXCEPTION 'lks92_to_lks2020 expects SRID 3059, got %', ST_SRID(geom);
    END IF;
    RETURN ST_TransformPipeline(
        geom,
        '+proj=pipeline'
        ' +step +inv +proj=tmerc +lat_0=0 +lon_0=24 +k=0.9996 +x_0=500000 +y_0=-6000000 +ellps=GRS80'
        ' +step +proj=hgridshift +grids=lv_lgia_lks92to2020.tif'
        ' +step +proj=tmerc +lat_0=0 +lon_0=24 +k=0.9996 +x_0=500000 +y_0=-6000000 +ellps=GRS80',
        10306);
END;
$$;

COMMENT ON FUNCTION lks92_to_lks2020(geometry) IS
    'EPSG:3059 -> EPSG:10306 via EPSG:10838 (grid lv_lgia_lks92to2020.tif); errors if the grid is missing. Decision D9.';

-- migrate:down

DROP FUNCTION IF EXISTS lks92_to_lks2020(geometry);
DELETE FROM spatial_ref_sys WHERE srid IN (10305, 10306);
