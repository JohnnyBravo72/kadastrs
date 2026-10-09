"""config/etl.yaml, config/schemas.yaml and config/sources.yaml agree."""

from etl.importers import IMPORTERS
from etl.importers.cadastre_text import REQUIRED
from etl.settings import etl_config, schemas
from etl.sources import load_config


def test_etl_resources_are_registered_sources():
    registry = {s.id: s for s in load_config().sources}
    for source_id, roles in etl_config().files.items():
        assert source_id in registry, source_id
        assert set(roles.values()) <= set(registry[source_id].datagov.resource_ids), source_id


def test_every_reference_source_has_an_importer():
    reference = {s.id for s in load_config().sources if s.type == "reference"}
    assert reference == set(IMPORTERS) == set(etl_config().files)


def test_pilot_atvk_are_text():
    assert etl_config().pilot_atvk == ("0002000", "0003000", "0004000")


def test_required_xml_paths_are_expected():
    for role, required in REQUIRED.items():
        assert set(required) <= set(schemas()["xml"][role]["paths"]), role
