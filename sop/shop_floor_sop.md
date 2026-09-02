# Shop-Floor SOP — Fictional Assessment Only

This document is fictional and exists only for the Shop-Floor AI Agent assessment. It is not a manufacturer-approved operating or safety manual. Operators must follow their employer's approved procedures and supervisor direction.

## SOP-GENERAL-001 — General Panel Verification

### Purpose

Confirm that a panel has a valid system record before any processing decision is made.

### Operator steps

1. Read the complete panel code from the physical label.
2. Find the matching system record and confirm the cabinet ID, panel name, dimensions, material, required operation, and required workstation.
3. If the panel code is not found, do not invent or infer panel information.
4. Use stable source labels such as `Panel P-1001` when referring to a panel record.

### Stop and escalate when

- The panel code is unknown or unreadable.
- The physical label conflicts with the system record.
- A required production fact is absent or unclear.

## SOP-EDGE-001 — Edge Banding

### Purpose

Verify that a panel assigned to edge banding is presented at the fictional `EDGE-01` workstation.

### Operator steps

1. Complete `SOP-GENERAL-001`.
2. Confirm the panel record lists `edge_banding` as the required operation.
3. Confirm the required workstation is `EDGE-01` and that `Workstation EDGE-01` supports `edge_banding`.
4. Proceed only under the site's approved operating procedures.

### Stop and escalate when

- The panel requires a different operation or workstation.
- The panel or workstation record is incomplete or inconsistent.

## SOP-DRILL-001 — Drilling

### Purpose

Verify that a panel assigned to drilling is presented at the fictional `DRILL-01` workstation.

### Operator steps

1. Complete `SOP-GENERAL-001`.
2. Confirm the panel record lists `drilling` as the required operation.
3. Confirm the required workstation is `DRILL-01` and that `Workstation DRILL-01` supports `drilling`.
4. Proceed only under the site's approved operating procedures.

### Stop and escalate when

- The panel requires a different operation or workstation.
- The panel or workstation record is incomplete or inconsistent.

## SOP-MISMATCH-001 — Wrong Workstation or Data Mismatch

### Purpose

Prevent processing when a selected workstation or physical panel does not agree with the system records.

### Operator steps

1. Compare the selected workstation with the panel's required workstation.
2. Confirm the workstation's supported operation matches the panel's required operation.
3. If either comparison fails, do not process the panel.
4. Record the observed mismatch using the approved site process when one is available.

### Stop and escalate when

- The selected workstation is wrong for the panel.
- The physical panel label conflicts with the system record.
- Panel and workstation records disagree.

## SOP-UNSUPPORTED-001 — Unsupported Machine Parameters

### Purpose

Prevent unsupported machine settings or parameters from being guessed.

### Operator steps

1. Check whether the requested fact exists in an approved source.
2. If a spindle speed, feed rate, tooling parameter, machine setting, or other requested value is unavailable, state that it is not provided.
3. Do not estimate, infer, or invent the missing value.
4. Refer the request to a supervisor or approved manufacturer documentation.

### Stop and escalate when

- A requested machine parameter is unavailable in an approved source.
- Someone asks the operator or system to guess a setting or safety procedure.

## SOP-ESCALATION-001 — Supervisor Escalation

### Purpose

Define when uncertainty or inconsistent information must be referred to a supervisor.

### Operator steps

1. Stop the current decision or processing step.
2. Preserve the panel code, selected workstation, and the specific discrepancy or unsupported request.
3. Contact a supervisor through the site's approved process.
4. Resume only after receiving authorized direction.

### Stop and escalate when

- A panel code is unknown.
- A label, panel record, and workstation record do not agree.
- Required production information is missing.
- Machine parameters or safety procedures are requested but not provided by an approved source.
