"""Tests for deterministic Phase 2 grounding data validation."""

from __future__ import annotations

import copy
import json

import pytest

from src.data_loader import (
    ALLOWED_OPERATIONS,
    PANEL_REQUIRED_FIELDS,
    REQUIRED_SOP_SOURCE_IDS,
    WORKSTATION_REQUIRED_FIELDS,
    DataValidationError,
    load_panels,
    load_sop,
    load_workstations,
    validate_cross_file_relationships,
    validate_panel_records,
    validate_required_sop_source_ids,
    validate_workstation_records,
)


@pytest.fixture(scope="module")
def panels() -> list[dict]:
    return load_panels()


@pytest.fixture(scope="module")
def workstations() -> list[dict]:
    return load_workstations()


def test_real_phase_two_files_load_successfully(panels, workstations):
    sop_text = load_sop()
    validate_cross_file_relationships(panels, workstations)
    assert sop_text


def test_exactly_four_panels_exist(panels):
    assert len(panels) == 4


def test_exactly_two_workstations_exist(workstations):
    assert len(workstations) == 2


def test_panel_codes_are_unique(panels):
    panel_codes = [panel["panel_code"] for panel in panels]
    assert len(panel_codes) == len(set(panel_codes))


def test_workstation_ids_are_unique(workstations):
    workstation_ids = [workstation["workstation_id"] for workstation in workstations]
    assert len(workstation_ids) == len(set(workstation_ids))


def test_every_required_field_is_present_and_non_empty(panels, workstations):
    for panel in panels:
        assert PANEL_REQUIRED_FIELDS <= panel.keys()
        for field in PANEL_REQUIRED_FIELDS - {"dimensions_mm"}:
            assert isinstance(panel[field], str) and panel[field].strip()

    for workstation in workstations:
        assert WORKSTATION_REQUIRED_FIELDS <= workstation.keys()
        for field in WORKSTATION_REQUIRED_FIELDS - {"required_checks"}:
            assert isinstance(workstation[field], str) and workstation[field].strip()
        assert workstation["required_checks"]
        assert all(check.strip() for check in workstation["required_checks"])


def test_all_dimensions_are_positive_numbers(panels):
    for panel in panels:
        for value in panel["dimensions_mm"].values():
            assert isinstance(value, (int, float)) and not isinstance(value, bool)
            assert value > 0


def test_every_panel_references_an_existing_workstation(panels, workstations):
    workstation_ids = {workstation["workstation_id"] for workstation in workstations}
    assert all(panel["required_workstation_id"] in workstation_ids for panel in panels)


def test_every_panel_operation_matches_its_workstation(panels, workstations):
    operations_by_workstation = {
        workstation["workstation_id"]: workstation["supported_operation"]
        for workstation in workstations
    }
    assert all(
        panel["required_operation"]
        == operations_by_workstation[panel["required_workstation_id"]]
        for panel in panels
    )


def test_both_allowed_operations_are_represented(panels, workstations):
    panel_operations = {panel["required_operation"] for panel in panels}
    workstation_operations = {
        workstation["supported_operation"] for workstation in workstations
    }
    assert panel_operations == ALLOWED_OPERATIONS
    assert workstation_operations == ALLOWED_OPERATIONS


def test_all_six_required_sop_source_ids_exist():
    sop_text = load_sop()
    assert len(REQUIRED_SOP_SOURCE_IDS) == 6
    assert all(source_id in sop_text for source_id in REQUIRED_SOP_SOURCE_IDS)


def test_unknown_panel_code_is_absent(panels):
    assert "P-9999" not in {panel["panel_code"] for panel in panels}


def test_duplicate_panel_codes_are_rejected(panels):
    invalid_panels = copy.deepcopy(panels)
    invalid_panels[1]["panel_code"] = invalid_panels[0]["panel_code"]

    with pytest.raises(DataValidationError, match="Duplicate panel code"):
        validate_panel_records(invalid_panels)


def test_duplicate_workstation_ids_are_rejected(workstations):
    invalid_workstations = copy.deepcopy(workstations)
    invalid_workstations[1]["workstation_id"] = invalid_workstations[0]["workstation_id"]

    with pytest.raises(DataValidationError, match="Duplicate workstation ID"):
        validate_workstation_records(invalid_workstations)


@pytest.mark.parametrize(
    ("records_fixture", "validator", "field"),
    [
        ("panels", validate_panel_records, "material"),
        ("workstations", validate_workstation_records, "description"),
    ],
)
def test_missing_required_fields_are_rejected(
    request, records_fixture, validator, field
):
    invalid_records = copy.deepcopy(request.getfixturevalue(records_fixture))
    del invalid_records[0][field]

    with pytest.raises(DataValidationError, match="missing required fields"):
        validator(invalid_records)


@pytest.mark.parametrize("invalid_value", [0, -1, "18", True])
def test_invalid_dimensions_are_rejected(panels, invalid_value):
    invalid_panels = copy.deepcopy(panels)
    invalid_panels[0]["dimensions_mm"]["thickness"] = invalid_value

    with pytest.raises(DataValidationError, match="must be a positive number"):
        validate_panel_records(invalid_panels)


def test_unknown_workstation_references_are_rejected(panels, workstations):
    invalid_panels = copy.deepcopy(panels)
    invalid_panels[0]["required_workstation_id"] = "UNKNOWN-01"

    with pytest.raises(DataValidationError, match="unknown workstation"):
        validate_cross_file_relationships(invalid_panels, workstations)


def test_operation_workstation_mismatches_are_rejected(panels, workstations):
    invalid_panels = copy.deepcopy(panels)
    invalid_panels[0]["required_operation"] = "drilling"

    with pytest.raises(DataValidationError, match="does not match"):
        validate_cross_file_relationships(invalid_panels, workstations)


def test_missing_sop_source_ids_are_rejected():
    incomplete_sop = "# SOP-GENERAL-001\n\nOnly one source is present."

    with pytest.raises(DataValidationError, match="missing required source IDs"):
        validate_required_sop_source_ids(incomplete_sop)


def test_invalid_json_is_rejected(tmp_path):
    invalid_json_path = tmp_path / "panels.json"
    invalid_json_path.write_text('{"panels": [}', encoding="utf-8")

    with pytest.raises(DataValidationError, match="Invalid JSON"):
        load_panels(invalid_json_path)


@pytest.mark.parametrize("loader", [load_panels, load_workstations, load_sop])
def test_missing_files_are_rejected(tmp_path, loader):
    missing_path = tmp_path / "missing-source"

    with pytest.raises(FileNotFoundError, match="not found"):
        loader(missing_path)


def test_invalid_top_level_json_contract_is_rejected(tmp_path):
    invalid_contract_path = tmp_path / "panels.json"
    invalid_contract_path.write_text(json.dumps({"records": []}), encoding="utf-8")

    with pytest.raises(DataValidationError, match="top-level 'panels'"):
        load_panels(invalid_contract_path)
