"""config/sources.yaml validation and the registry loader."""

import copy
import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from etl.sources import SourcesConfig, load_config, main, sync_registry

ROOT = Path(__file__).resolve().parents[1]
SOURCES_YAML = ROOT / "config" / "sources.yaml"

# Shaped like the commented example in sources.yaml; values are test fixtures,
# not verified data.gov.lv ids.
EXAMPLE_SOURCE = {
    "id": "test_flood_10y",
    "names": {"lv": "Plūdi (10 gadu)", "en": "Flood (10-year)"},
    "owner": "LVĢMC",
    "group": "Plūdi",
    "order": 40,
    "type": "check",
    "subject_kinds": ["object"],
    "default_selected": True,
    "coverage_lv": "Tikai noteiktās plūdu riska teritorijas",
    "processing_lv": ["Testa piezīme."],
    "max_age": "P1M",
    "external_resources": ["E7"],
    "licence": "CC0-1.0",
}


def _repo_config_dict() -> dict:
    return yaml.safe_load(SOURCES_YAML.read_text(encoding="utf-8"))


def _with_source(**overrides) -> dict:
    data = _repo_config_dict()
    data["sources"] = [{**copy.deepcopy(EXAMPLE_SOURCE), **overrides}]
    return data


# --- the real file -----------------------------------------------------------


def test_repo_sources_yaml_validates():
    cfg = load_config(SOURCES_YAML)
    assert {e.id for e in cfg.allowed_external_resources} >= {"E1", "E7"}


def test_cli_validate_ok(capsys):
    assert main(["validate", "--config", str(SOURCES_YAML)]) == 0
    assert "valid" in capsys.readouterr().out


def test_d1_list_matches_decisions_md():
    """sources.yaml says: same ids and same list as the D1 table; keep both in sync."""
    text = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
    d1 = text.split("## D1", 1)[1].split("\n## ", 1)[0]
    rows = re.findall(r"^\| (E\d+) \|.*\| ([^|]+) \|\s*$", d1, re.MULTILINE)
    assert rows, "no E* rows found in the D1 table of docs/decisions.md"
    decided = {
        rid: ("allowed" if "allowed" in status.lower() else status.strip()) for rid, status in rows
    }
    yaml_status = {e.id: e.status for e in load_config(SOURCES_YAML).allowed_external_resources}
    assert yaml_status == decided


# --- validation catches mistakes ---------------------------------------------


def test_example_source_validates():
    cfg = SourcesConfig.model_validate(_with_source())
    assert cfg.sources[0].id == "test_flood_10y"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"max_age": "1 month"}, "ISO 8601"),
        ({"max_age": "P"}, "ISO 8601"),
        ({"type": "map"}, "type"),
        ({"type": "reference", "default_selected": False}, "must be default_selected"),
        ({"subject_kinds": []}, "subject_kinds"),
        ({"subject_kinds": ["person"]}, "subject_kinds"),
        ({"id": "Flood-10y"}, "id"),
        ({"externl_resources": ["E7"]}, "externl_resources"),  # typo = unknown key
        ({"external_resources": ["E99"]}, "E99 is not listed"),
        ({"external_resources": []}, "needs datagov.dataset_id or external_resources"),
        # Codes are text (CLAUDE.md rule 8): an unquoted number is rejected, not coerced.
        ({"datagov": {"dataset_id": 123, "resource_ids": []}}, "dataset_id"),
    ],
)
def test_invalid_source_rejected(overrides, message):
    with pytest.raises(ValidationError, match=re.escape(message)):
        SourcesConfig.model_validate(_with_source(**overrides))


def test_duplicate_source_ids_rejected():
    data = _with_source()
    data["sources"].append(copy.deepcopy(data["sources"][0]))
    with pytest.raises(ValidationError, match="duplicate source ids: test_flood_10y"):
        SourcesConfig.model_validate(data)


def test_withdrawn_external_resource_cannot_be_used():
    data = _with_source()
    next(e for e in data["allowed_external_resources"] if e["id"] == "E7")["status"] = "withdrawn"
    with pytest.raises(ValidationError, match="E7 is withdrawn"):
        SourcesConfig.model_validate(data)


def test_external_url_must_be_on_its_host():
    data = _repo_config_dict()
    data["allowed_external_resources"][0]["url"] = "https://example.com/export.csv"
    with pytest.raises(ValidationError, match="is not on host"):
        SourcesConfig.model_validate(data)


def test_every_source_has_a_latvian_coverage_note():
    """Avoti shows coverage and processing in Latvian (sources.yaml coverage_lv,
    processing_lv); a source without coverage_lv does not load."""
    cfg = load_config()
    for src in cfg.sources:
        assert src.coverage_lv.strip(), src.id
        assert all(n.strip() for n in src.processing_lv), src.id
    data = _with_source()
    del data["sources"][0]["coverage_lv"]
    with pytest.raises(ValidationError, match="coverage_lv"):
        SourcesConfig.model_validate(data)


def test_cli_validate_reports_invalid_file(tmp_path, capsys):
    bad = tmp_path / "sources.yaml"
    bad.write_text(yaml.safe_dump(_with_source(max_age="monthly")), encoding="utf-8")
    assert main(["validate", "--config", str(bad)]) == 1
    assert "ISO 8601" in capsys.readouterr().err


# --- loading into the DB (rolled back) ----------------------------------------


def _registry_rows(conn) -> list[tuple]:
    sources = conn.execute(
        "SELECT id, name_lv, name_en, owner, source_group, display_order, type, subject_kinds,"
        " default_selected, coverage, max_age::text, datagov_dataset_ids, datagov_resource_ids,"
        " external_resource_ids, licence, config, active FROM source ORDER BY id"
    ).fetchall()
    external = conn.execute(
        "SELECT id, name, urls, host, datagov_datasets, status, config, active"
        " FROM allowed_external_resource ORDER BY id"
    ).fetchall()
    return sources + external


@pytest.mark.stack
def test_load_is_idempotent(db_conn):
    cfg = SourcesConfig.model_validate(_with_source())
    with db_conn.transaction(force_rollback=True):
        sync_registry(db_conn, cfg)
        first = _registry_rows(db_conn)
        counts = sync_registry(db_conn, cfg)
        assert _registry_rows(db_conn) == first
        assert counts["sources_deactivated"] == 0


@pytest.mark.stack
def test_load_stores_source_fields(db_conn):
    cfg = SourcesConfig.model_validate(_with_source())
    with db_conn.transaction(force_rollback=True):
        sync_registry(db_conn, cfg)
        row = db_conn.execute(
            "SELECT name_lv, source_group, max_age::text, subject_kinds, external_resource_ids,"
            " config->>'id', active FROM source WHERE id = 'test_flood_10y'"
        ).fetchone()
        ext = db_conn.execute(
            "SELECT urls, status, config->>'licence' FROM allowed_external_resource WHERE id = 'E7'"
        ).fetchone()
    name_lv, group, max_age, kinds, ext_ids, cfg_id, active = row
    assert (name_lv, group, kinds, ext_ids, cfg_id, active) == (
        "Plūdi (10 gadu)",
        "Plūdi",
        ["object"],
        ["E7"],
        "test_flood_10y",
        True,
    )
    assert max_age == "1 mon"  # ISO 8601 P1M stored as a PostgreSQL interval
    assert ext[1] == "allowed"
    assert ext[2] == "CC0-1.0"
    assert ext[0][0].startswith("https://geodata.lvgmc.lv/")


@pytest.mark.stack
def test_removed_entry_is_deactivated_not_deleted(db_conn):
    with db_conn.transaction(force_rollback=True):
        sync_registry(db_conn, SourcesConfig.model_validate(_with_source()))
        counts = sync_registry(db_conn, SourcesConfig.model_validate(_repo_config_dict()))
        active = db_conn.execute("SELECT active FROM source WHERE id = 'test_flood_10y'").fetchone()
    assert active == (False,)
    assert counts["sources_deactivated"] >= 1


@pytest.mark.stack
def test_reference_source_is_not_user_selectable(db_conn):
    cfg = SourcesConfig.model_validate(_with_source(type="reference"))
    with db_conn.transaction(force_rollback=True):
        sync_registry(db_conn, cfg)
        row = db_conn.execute(
            "SELECT type, user_selectable FROM source WHERE id = 'test_flood_10y'"
        ).fetchone()
    assert row == ("reference", False)
