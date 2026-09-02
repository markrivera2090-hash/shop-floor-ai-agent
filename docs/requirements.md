# Approved Project Scope

## Production scope

- Workstations: Edge Banding and Drilling.
- Use three to five fictional panels.
- Store structured production facts in JSON.
- Store the SOP in Markdown.

## Required logical tools

- `get_panel(panel_code)`
- `get_workstation_requirements(workstation_id)`
- `search_sop(query)`
- `record_event(...)`
- `escalate_to_supervisor(...)`

## Agent workflow

Input → Decide → Call Tool → Read Result → Decide Next Step → Respond or Act

The LLM must choose tools rather than follow one hard-coded tool sequence for every scenario. At least one scenario must require multiple tool calls.

## Planned UI

The UI must eventually include workstation selection, panel input, panel details, grounded instructions, AI questions, tool trace, and event history.

## Safety behavior

Do not invent missing production facts, machine settings, speeds, tooling parameters, or safety procedures.

## Required test cases

1. Correct workstation
2. Wrong workstation
3. Unsupported question / no hallucination
4. Unknown panel
5. Supervisor escalation

## Required deliverables

- Source repository
- README
- Test results
- Approximate time spent
- 2–3 minute demo video
- Optional deployment URL
