# Next Steps: Google Meet Listener Execution Plan

Detailed technical design lives in `docs/phase2_google_meet.md`.

This file is the execution-oriented roadmap for Phase 2.

## Current Status

- Phase 1 local mic realtime interpreter: complete and working.
- Phase 2 Google Meet Listener: planned.

## Decision Gate: Path Selection

Choose one primary path after discovery:

- Path A: official/compliant media integration (availability may depend on access and admin policy).
- Path B: bot participant + loopback capture (internal MVP only; legal review required before production).

## Milestones

## M1: Discovery + Compliance Gate

Deliverables:
- Capability matrix validated with internal assumptions clearly marked.
- Consent and participant notification requirements documented.
- Retention and logging redaction policy approved.

Exit criteria:
- Clear go/no-go for Path A feasibility.
- Legal/compliance sign-off for allowed prototype scope.

## M2: Architecture Freeze

Deliverables:
- `AudioInput` contract approved.
- `MeetInput` lifecycle and state machine documented.
- Failure/retry policy documented.

Exit criteria:
- Engineering sign-off on architecture and operational constraints.

## M3: Internal MVP Build (Path B or Path A if available)

Deliverables:
- Meeting audio can be ingested into the existing realtime translation pipeline.
- Basic runbook for join failures, no-audio, and reconnect.
- Echo prevention checklist enforced.

Exit criteria:
- Stable 30-minute internal test with acceptable latency and no crash.

## M4: Controlled Pilot Readiness

Deliverables:
- Observability metrics and incident playbook.
- Transcript handling and storage controls implemented.
- Deployment guardrails documented.

Exit criteria:
- Pilot-ready package approved by engineering + legal + security stakeholders.

## Operational Guardrails

- Do not claim audio injection/send into Meet is supported unless explicitly confirmed for our access level.
- Do not run in production without participant consent and legal approval.
- Default to receive-only architecture until capability confirmation is documented.
