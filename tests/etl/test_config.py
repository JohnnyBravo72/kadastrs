"""config/etl.yaml, config/schemas.yaml and config/sources.yaml agree."""

from etl.importers import IMPORTERS
from etl.importers.cadastre_text import REQUIRED
from etl.importers.encumbrances import REQUIRED as ENCUMBRANCE_REQUIRED
from etl.importers.ownership import REQUIRED as OWNERSHIP_REQUIRED
from etl.settings import etl_config, schemas
from etl.sources import load_config


def test_etl_resources_are_registered_sources():
    registry = {s.id: s for s in load_config().sources}
    for source_id, roles in etl_config().files.items():
        assert source_id in registry, source_id
        assert set(roles.values()) <= set(registry[source_id].datagov.resource_ids), source_id


def test_every_imported_source_is_registered_and_configured():
    registry = {s.id: s for s in load_config().sources}
    assert set(IMPORTERS) == set(etl_config().files)
    assert set(IMPORTERS) <= set(registry)
    assert {sid for sid, s in registry.items() if s.type == "reference"} <= set(IMPORTERS)


def test_flood_layers_come_from_d1_e7():
    e7 = next(e for e in load_config().allowed_external_resources if e.id == "E7")
    roles = {int(k): v for k, v in e7.model_extra["layer_roles"].items()}
    assert roles == {0: "finding", 1: "finding", 3: "coverage_mask"}
    assert sorted(roles) == e7.model_extra["layers"]


def test_zoning_layers_come_from_d1_e4():
    e4 = next(e for e in load_config().allowed_external_resources if e.id == "E4")
    layers = e4.model_extra["wfs_layers"]
    assert layers == {
        "finding": "tapis_apvienotie:funkcionalais_zonejums",
        "coverage_mask": "tapis_apvienotie:speka_esosu_planojumu_teritorijas",
    }
    assert e4.model_extra.get("access") == "snapshot"


def test_pilot_atvk_are_text():
    assert etl_config().pilot_atvk == ("0002000", "0003000", "0004000")


def test_import_scope_defaults_to_pilot(monkeypatch):
    monkeypatch.delenv("KADASTRS_IMPORT_SCOPE", raising=False)
    etl_config.cache_clear()
    cfg = etl_config()
    assert cfg.import_scope == "pilot"
    assert cfg.is_pilot
    assert cfg.scope_atvk() == cfg.pilot_atvk
    assert cfg.scope_territories() == set(cfg.pilot_cadastral_territory.values())
    etl_config.cache_clear()


def test_import_scope_country_clears_filters(monkeypatch):
    monkeypatch.setenv("KADASTRS_IMPORT_SCOPE", "country")
    etl_config.cache_clear()
    cfg = etl_config()
    assert cfg.import_scope == "country"
    assert not cfg.is_pilot
    assert cfg.scope_atvk() is None
    assert cfg.scope_territories() is None
    etl_config.cache_clear()
    monkeypatch.delenv("KADASTRS_IMPORT_SCOPE", raising=False)


def test_required_xml_paths_are_expected():
    for role, required in REQUIRED.items():
        assert set(required) <= set(schemas()["xml"][role]["paths"]), role
    assert set(ENCUMBRANCE_REQUIRED) <= set(schemas()["xml"]["encumbrance"]["paths"])
    assert set(OWNERSHIP_REQUIRED) <= set(schemas()["xml"]["ownership"]["paths"])


def test_pilot_cadastral_territory_per_city():
    assert etl_config().pilot_cadastral_territory == {
        "0002000": "0500",
        "0003000": "0900",
        "0004000": "1300",
    }
