# Next Steps: Google Meet

Detailed design and status: `docs/phase2_google_meet.md`.

## Current Position (2026-03-04)

Internal MVP exists:
- Bot join/wait/leave lifecycle implemented.
- Loopback capture path implemented.
- Realtime translation path integrated.

Primary gap is hardening + compliance, not greenfield build.

## Near-Term Priorities

## N1: Runtime Stability

Deliverables:
- Unify meet CLI behavior between `app.py` and `src/meet/main.py`.
- Validate listen-only meet flow with repeatable smoke script.
- Validate clean shutdown across interpreter, audio, and browser tasks.

Exit criteria:
- 30-minute internal run without crash/restart loops.
- Known startup/runtime errors produce actionable diagnostics.

## N2: Audio Path Validation

Deliverables:
- Validate `--meet-mic-device` speak-back path end-to-end.
- Validate ScreenCaptureKit (`--sck`) path on supported macOS versions.
- Add preflight checks for sample-rate/device mismatch.

Exit criteria:
- Documented tested configurations with pass/fail matrix.
- Echo/feedback checklist integrated into runbook.

## N3: Compliance Controls

Deliverables:
- Participant notice/consent procedure.
- Retention and deletion policy for recordings/transcripts.
- Logging redaction requirements for sensitive content.

Exit criteria:
- Security/legal sign-off for internal pilot scope.
- Deployment guardrails documented and reviewed.

## N4: Path A Feasibility (Official Meet API)

Deliverables:
- Capability matrix for official integration availability.
- Admin/policy prerequisites and constraints documented.
- Go/no-go decision on investing in Path A build.

Exit criteria:
- Explicit decision recorded with assumptions and risks.

## Guardrails

- No external production usage without consent and legal approval.
- Do not assume audio injection is supported by official APIs until confirmed.
- Keep meet profile data (`--profile-dir`) treated as sensitive credentials.
