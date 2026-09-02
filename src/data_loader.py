"""Deterministic loading and validation for Phase 2 grounding sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PANELS_PATH = PROJECT_ROOT / "data" / "panels.json"
WORKSTATIONS_PATH = PROJECT_ROOT / "data" / "workstations.json"
SOP_PATH = PROJECT_ROOT / "sop" / "shop_floor_sop.md"

ALLOWED_OPERATIONS = frozenset({"edge_banding", "drilling"})
REQUIRED_SOP_SOURCE_IDS = frozenset(
    {
        "SOP-GENERAL-001",
        "SOP-EDGE-001",
        "SOP-DRILL-001",
        "SOP-MISMATCH-001",
        "SOP-UNSUPPORTED-001",
        "SOP-ESCALATION-001",
    }
)

PANEL_REQUIRED_FIELDS = frozenset(
    {
        "panel_code",
        "cabinet_id",
        "panel_name",
        "dimensions_mm",
        "material",
        "required_operation",
        "required_workstation_id",
    }
)
WORKSTATION_REQUIRED_FIELDS = frozenset(
    {
        "workstation_id",
        "name",
        "supported_operation",
        "description",
        "required_checks",
    }
)
DIMENSION_FIELDS = frozenset({"length", "width", "thickness"})


class DataValidationError(ValueError):
    """Raised when a grounding source violates its data contract."""


def _resolved_path(path: str | Path | None, default: Path) -> Path:
    return default if path is None else Path(path).expanduser().resolve()


def _load_json(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"Required JSON file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as file_handle:
            return json.load(file_handle)
    except json.JSONDecodeError as exc:
        raise DataValidationError(
            f"Invalid JSON in {path} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def _extract_record_list(payload: Any, key: str, source: Path) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise DataValidationError(f"{source} must contain a top-level JSON object.")
    if key not in payload:
        raise DataValidationError(f"{source} is missing the top-level '{key}' field.")

    records = payload[key]
    if not isinstance(records, list):
        raise DataValidationError(f"The '{key}' field in {source} must be an array.")
    return records


def _require_fields(record: dict[str, Any], required: frozenset[str], label: str) -> None:
    missing = sorted(required.difference(record))
    if missing:
        raise DataValidationError(f"{label} is missing required fields: {', '.join(missing)}")


def _require_non_empty_string(record: dict[str, Any], field: str, label: str) -> str:
    value = record[field]
    if not isinstance(value, str) or not value.strip():
        raise DataValidationError(f"{label} field '{field}' must be a non-empty string.")
    return value


def load_panels(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load and validate panel records from JSON."""

    source = _resolved_path(path, PANELS_PATH)
    panels = _extract_record_list(_load_json(source), "panels", source)
    validate_panel_records(panels)
    return panels


def load_workstations(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load and validate workstation records from JSON."""

    source = _resolved_path(path, WORKSTATIONS_PATH)
    workstations = _extract_record_list(_load_json(source), "workstations", source)
    validate_workstation_records(workstations)
    return workstations


def load_sop(path: str | Path | None = None) -> str:
    """Load the SOP Markdown and verify its required stable source IDs."""

    source = _resolved_path(path, SOP_PATH)
    if not source.is_file():
        raise FileNotFoundError(f"Required SOP file not found: {source}")

    text = source.read_text(encoding="utf-8")
    validate_required_sop_source_ids(text)
    return text


def validate_panel_records(panels: Any) -> None:
    """Validate panel schemas, IDs, operations, and dimensions."""

    if not isinstance(panels, list):
        raise DataValidationError("Panel records must be provided as a list.")

    seen_codes: set[str] = set()
    for index, panel in enumerate(panels):
        label = f"Panel record at index {index}"
        if not isinstance(panel, dict):
            raise DataValidationError(f"{label} must be an object.")

        _require_fields(panel, PANEL_REQUIRED_FIELDS, label)
        panel_code = _require_non_empty_string(panel, "panel_code", label)
        for field in (
            "cabinet_id",
            "panel_name",
            "material",
            "required_operation",
            "required_workstation_id",
        ):
            _require_non_empty_string(panel, field, f"Panel {panel_code}")

        if panel_code in seen_codes:
            raise DataValidationError(f"Duplicate panel code: {panel_code}")
        seen_codes.add(panel_code)

        operation = panel["required_operation"]
        if operation not in ALLOWED_OPERATIONS:
            raise DataValidationError(
                f"Panel {panel_code} has unsupported operation '{operation}'."
            )

        dimensions = panel["dimensions_mm"]
        if not isinstance(dimensions, dict):
            raise DataValidationError(
                f"Panel {panel_code} field 'dimensions_mm' must be an object."
            )
        missing_dimensions = sorted(DIMENSION_FIELDS.difference(dimensions))
        if missing_dimensions:
            raise DataValidationError(
                f"Panel {panel_code} is missing dimensions: {', '.join(missing_dimensions)}"
            )
        for dimension_name in sorted(DIMENSION_FIELDS):
            value = dimensions[dimension_name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise DataValidationError(
                    f"Panel {panel_code} dimension '{dimension_name}' must be a positive number."
                )


def validate_workstation_records(workstations: Any) -> None:
    """Validate workstation schemas, IDs, operations, and checks."""

    if not isinstance(workstations, list):
        raise DataValidationError("Workstation records must be provided as a list.")

    seen_ids: set[str] = set()
    for index, workstation in enumerate(workstations):
        label = f"Workstation record at index {index}"
        if not isinstance(workstation, dict):
            raise DataValidationError(f"{label} must be an object.")

        _require_fields(workstation, WORKSTATION_REQUIRED_FIELDS, label)
        workstation_id = _require_non_empty_string(
            workstation, "workstation_id", label
        )
        for field in ("name", "supported_operation", "description"):
            _require_non_empty_string(workstation, field, f"Workstation {workstation_id}")

        if workstation_id in seen_ids:
            raise DataValidationError(f"Duplicate workstation ID: {workstation_id}")
        seen_ids.add(workstation_id)

        operation = workstation["supported_operation"]
        if operation not in ALLOWED_OPERATIONS:
            raise DataValidationError(
                f"Workstation {workstation_id} has unsupported operation '{operation}'."
            )

        required_checks = workstation["required_checks"]
        if not isinstance(required_checks, list) or not required_checks:
            raise DataValidationError(
                f"Workstation {workstation_id} field 'required_checks' must be a non-empty list."
            )
        if any(not isinstance(check, str) or not check.strip() for check in required_checks):
            raise DataValidationError(
                f"Workstation {workstation_id} required checks must be non-empty strings."
            )


def validate_cross_file_relationships(
    panels: list[dict[str, Any]], workstations: list[dict[str, Any]]
) -> None:
    """Validate workstation references and operation compatibility."""

    validate_panel_records(panels)
    validate_workstation_records(workstations)
    workstation_by_id = {
        workstation["workstation_id"]: workstation for workstation in workstations
    }

    for panel in panels:
        panel_code = panel["panel_code"]
        workstation_id = panel["required_workstation_id"]
        if workstation_id not in workstation_by_id:
            raise DataValidationError(
                f"Panel {panel_code} references unknown workstation '{workstation_id}'."
            )

        workstation_operation = workstation_by_id[workstation_id]["supported_operation"]
        if panel["required_operation"] != workstation_operation:
            raise DataValidationError(
                f"Panel {panel_code} operation '{panel['required_operation']}' does not match "
                f"workstation {workstation_id} operation '{workstation_operation}'."
            )


def validate_required_sop_source_ids(sop_text: Any) -> None:
    """Validate that the SOP includes every required stable source ID."""

    if not isinstance(sop_text, str) or not sop_text.strip():
        raise DataValidationError("SOP content must be a non-empty string.")

    missing = sorted(source_id for source_id in REQUIRED_SOP_SOURCE_IDS if source_id not in sop_text)
    if missing:
        raise DataValidationError(f"SOP is missing required source IDs: {', '.join(missing)}")
