-- migrate:up

-- Input resolution (PLAN.md §5, Phase 3): normalised address text for
-- diacritic-, case- and typo-tolerant matching, and prefix indexes for
-- type-ahead on designations. Both the API's queries and these indexes call
-- ref.addr_norm(), so the input and the stored text are always normalised the
-- same way.

-- unaccent() with an explicit dictionary is safe to declare IMMUTABLE (the
-- one-argument form is STABLE because it looks the dictionary up by name).
CREATE FUNCTION ref.unaccent_imm(t text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS $$
    SELECT public.unaccent('public.unaccent'::regdictionary, t)
$$;

-- Normalised address text:
--   lower case, no diacritics; postcode (LV-1234) dropped; every run of
--   non-alphanumerics becomes one space; common abbreviations expanded
--   (ie. → iela, pr./prosp. → prospekts, nov. → novads, pag. → pagasts,
--   bulv. → bulvaris); a house-number letter written apart is joined
--   ("11 a" → "11a"). Example: 'Tautas iela 11A, Daugavpils, LV-5404'
--   → 'tautas iela 11a daugavpils'.
CREATE FUNCTION ref.addr_norm(t text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS $$
    SELECT btrim(regexp_replace(
        regexp_replace(
        regexp_replace(
        regexp_replace(
        regexp_replace(
        regexp_replace(
        regexp_replace(
        regexp_replace(
            ' ' || regexp_replace(
                       regexp_replace(lower(ref.unaccent_imm(t)), 'lv[- ]?[0-9]{4}', ' ', 'g'),
                       '[^a-z0-9]+', ' ', 'g') || ' ',
            ' ie ', ' iela ', 'g'),
            ' (pr|prosp) ', ' prospekts ', 'g'),
            ' nov ', ' novads ', 'g'),
            ' pag ', ' pagasts ', 'g'),
            ' bulv ', ' bulvaris ', 'g'),
            ' ([0-9]+) ([a-z]) ', ' \1\2 ', 'g'),
            ' ([0-9]+) ([a-z]) ', ' \1\2 ', 'g'),
        ' +', ' ', 'g'))
$$;

-- Search key: the normalised text without street-type words. "iela" is in
-- almost every address, so its trigrams would make every row a candidate
-- (e.g. 'liela' shares half its trigrams with 'iela'). The words list is
-- also in engine/resolve/address.py (STREET_WORDS); a test keeps them equal.
CREATE FUNCTION ref.addr_key(t text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS $$
    SELECT btrim(regexp_replace(
        regexp_replace(ref.addr_norm(t),
            '\m(iela|prospekts|bulvaris|laukums|gatve|cels|soseja|aleja|krastmala|dambis|novads|pagasts)\M',
            ' ', 'g'),
        ' +', ' ', 'g'))
$$;

-- Stored, so a trigram search never re-runs the regexes on candidate rows.
-- The ETL lists its columns explicitly, so it never writes these.
ALTER TABLE ref.address
    ADD COLUMN norm text GENERATED ALWAYS AS (ref.addr_norm(full_text)) STORED,
    ADD COLUMN norm_key text GENERATED ALWAYS AS (ref.addr_key(full_text)) STORED;
ALTER TABLE ref.address_history
    ADD COLUMN norm text GENERATED ALWAYS AS (ref.addr_norm(full_text)) STORED,
    ADD COLUMN norm_key text GENERATED ALWAYS AS (ref.addr_key(full_text)) STORED;
CREATE INDEX address_key_trgm ON ref.address USING gin (norm_key gin_trgm_ops);
CREATE INDEX address_history_key_trgm ON ref.address_history USING gin (norm_key gin_trgm_ops);

-- Prefix search on designations (LIKE 'prefix%' needs text_pattern_ops).
CREATE INDEX property_number_prefix ON ref.property (dataset_version_id, number text_pattern_ops);
CREATE INDEX parcel_code_prefix ON ref.parcel (dataset_version_id, code text_pattern_ops);
CREATE INDEX parcel_part_code_prefix ON ref.parcel_part (dataset_version_id, code text_pattern_ops);
CREATE INDEX building_code_prefix ON ref.building (dataset_version_id, code text_pattern_ops);
CREATE INDEX property_object_code_prefix
    ON ref.property_object (dataset_version_id, object_code text_pattern_ops);
CREATE INDEX kk_parcel_code_prefix ON ref.kk_parcel (dataset_version_id, code text_pattern_ops);
CREATE INDEX kk_building_code_prefix ON ref.kk_building (dataset_version_id, code text_pattern_ops);
-- Objects at an address (cadastre text carries the VARIS code).
CREATE INDEX parcel_part_parcel ON ref.parcel_part (dataset_version_id, parcel_code);

-- migrate:down

DROP INDEX ref.parcel_part_parcel, ref.kk_building_code_prefix, ref.kk_parcel_code_prefix,
           ref.property_object_code_prefix, ref.building_code_prefix,
           ref.parcel_part_code_prefix, ref.parcel_code_prefix, ref.property_number_prefix,
           ref.address_history_key_trgm, ref.address_key_trgm;
ALTER TABLE ref.address_history DROP COLUMN norm_key, DROP COLUMN norm;
ALTER TABLE ref.address DROP COLUMN norm_key, DROP COLUMN norm;
DROP FUNCTION ref.addr_key(text);
DROP FUNCTION ref.addr_norm(text);
DROP FUNCTION ref.unaccent_imm(text);
