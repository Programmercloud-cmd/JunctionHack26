# Reconstruction 502: line-shaped boundary citations

## Confirmed cause

The unchanged user attachment and repository `colorful-11397.png` have identical SHA-256 `e40c1b2314ae3a21e2e9fedab0222efe24fbd61c40fff805c6a17bf431472859`.

A controlled live request reproduced the reported generic 502 failure. Gemini reconstruction (`gemini-3.1-pro-preview`) completed with STOP in 98.67 seconds and 20,152 output tokens. The JSON was valid. Local Pydantic validation rejected five `boundaries[*].source` records: three terrace and two balcony open edges whose boxes had zero width or height, exactly matching their horizontal/vertical segments. The error was “Source region must be normalized with positive area.” It was not an API 400, timeout, truncation or poor-quality-image judgment.

The raw captured response is retained locally under `/tmp/junction-502-repro/`; it is not committed or printed. Only safe schema/request hashes, finish status and structural error locations were reported. The request hash matched the previous production request (`333c99a7be85dab665f8f8af7e2a745c3b68d85d7cc8c13cf7656c3e99a7dbe6`). Earlier discarded responses cannot retrospectively establish their exact failure causes, but this failure is now captured and reproducible.

## Smallest functional fix

BoundaryDescription uses a separate BoundaryRegion that accepts a normalized, positive-length line as well as an area. PageRegion for floors/measurements and factual QA/SourceRef validators still require positive area. Point, reversed and out-of-bounds boundary regions remain invalid.

The generator accepts a line association only when the original segment points lie on that exact citation, in the assigned floor and on the same page. It then expands only the zero dimension by one original normalized-image pixel on each available side, clamped to the page. This is an explicitly labeled clickable-selection choice, not a physical width or measurement. The original line citation remains unchanged in the embedded description. Boundary axes/meshes and IDs are unaffected by selection padding. Inconsistent segments stay unresolved.

Independent review caught a potential thickness loophole: width endpoints must validate against the original citation, never the padded display region. This is fixed and regression-tested; unsupported thickness stays an explicit display assumption. No new input caps, model changes, retries, dependencies or provider fallback were added.

## Diagnostics

Unexpected reconstruction failures now retain a safe phase/category and random reference in the existing API detail string and server log. Categories distinguish provider rejection/auth/quota/timeout, invalid JSON, structural validation, IFC generation and artifact reopening. Logs contain only allowlisted structural field names, numeric indices, error types and HTTP status. They exclude exception text, input/context, source names, URLs, request/response bodies and tracebacks. Existing trusted application error messages/statuses remain unchanged. Failed operations do not cache a model.

## Verification

- Replayed the exact previously rejected response without altering its content: two floors, 96 model records, all five padded edge records rendered, exact description preserved through generated IFC reopening. Five other geometry associations remain unresolved; they are unrelated to the parser failure.
- Fresh real production endpoint request: HTTP 200 in 90.84 seconds, two floors, 85 records with nine explicitly unresolved geometry associations. These are generated inventory counts, not source facts or fidelity scores.
- Live supported floor-specific QA answered with an original-region citation and validated highlight. Actual-height QA returned insufficient with no highlights. Fresh-store IFC reopening restored the original page, all stable IDs and relative units; real QA after reopening again returned the matching highlight. Full local report: `/tmp/junction-502-fixed-live/report.json`.
- 231 backend/native-IFC tests passed; four targeted Chromium V2/V3 checks passed. Independent read-only review passed 68 focused tests with no remaining code blockers.
- Regression coverage includes horizontal/vertical/page-border line citations, original-coordinate preservation, mesh/ID invariance, mismatches inside the eventual padding remaining unresolved, strict floor/QA regions, unsupported thickness, sanitized malicious exception data, SDK HTTP/timeout errors and atomic caching.

This fixes the captured line-citation failure. Earlier visual reconstruction limitations remain a separate issue; successful generation does not establish faithful or complete feature coverage.
