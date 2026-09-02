# Phase 2 Data Contracts

## Panel records

`data/panels.json` contains a top-level `panels` array. Each panel requires:

- `panel_code`: non-empty unique string
- `cabinet_id`: non-empty string
- `panel_name`: non-empty string
- `dimensions_mm`: object with positive numeric `length`, `width`, and `thickness`
- `material`: non-empty string
- `required_operation`: non-empty string from the allowed operations
- `required_workstation_id`: non-empty workstation reference

## Workstation records

`data/workstations.json` contains a top-level `workstations` array. Each workstation requires:

- `workstation_id`: non-empty unique string
- `name`: non-empty string
- `supported_operation`: non-empty string from the allowed operations
- `description`: non-empty string
- `required_checks`: non-empty array of non-empty strings

## Allowed operations

- `edge_banding`
- `drilling`

## Referential integrity

Every panel's `required_workstation_id` must reference an existing workstation. Its `required_operation` must equal that workstation's `supported_operation`. Panel codes and workstation IDs must each be unique.

Operator-entered panel codes are case-insensitive and may omit the hyphen. Inputs matching `P-1234` or `P1234` are normalized to canonical uppercase `P-1234`; other formats are rejected rather than guessed.

## SOP contract

`sop/shop_floor_sop.md` must contain these stable source IDs:

- `SOP-GENERAL-001`
- `SOP-EDGE-001`
- `SOP-DRILL-001`
- `SOP-MISMATCH-001`
- `SOP-UNSUPPORTED-001`
- `SOP-ESCALATION-001`

## Grounding and safety boundaries

Production facts must come from the JSON records, and procedural guidance must come from the Markdown SOP. Missing facts, machine settings, speeds, tooling parameters, and safety procedures must never be invented. Unknown records, conflicts, and unsupported parameter requests require a stop-and-escalate response. This dataset and SOP are fictional and assessment-only.

## Assessment scenario mapping

| Scenario | Supporting records |
| --- | --- |
| Correct workstation | `Panel P-1001`, `Workstation EDGE-01`, `SOP-EDGE-001` |
| Wrong workstation | `Panel P-1003` at `Workstation EDGE-01`, `SOP-MISMATCH-001` |
| Unsupported question / no hallucination | `SOP-UNSUPPORTED-001` |
| Unknown panel | Absent `Panel P-9999`, `SOP-GENERAL-001` |
| Supervisor escalation | `SOP-ESCALATION-001` |
