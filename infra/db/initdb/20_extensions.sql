-- Runs once, on an empty data directory, after the base image's 10_postgis.sh.
-- The migrations also create these (IF NOT EXISTS), so they are the source of truth.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
