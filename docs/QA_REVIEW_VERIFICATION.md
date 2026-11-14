# Reviewed QA verification — 14 November 2026

Live calls used the configured `gemini-flash-latest` answer model and `gemini-decision-1` gate/support reviewer. Reconstruction review used the unchanged `gemini-3.1-pro-preview` default. Original retained artifacts were reopened with their original pages and descriptions; no new image extraction was needed for these QA checks.

## Small live comparison

The baseline uses the same source context and deterministic validation without the extra support review. These are independent live generations, not a controlled statistical evaluation. The latest successful run for each case is shown; earlier failures are retained below.

| Source/question category | Baseline outcome/time | Reviewed outcome/time | Reviewed evidence/highlights |
| --- | --- | --- | --- |
| 1794 room label | Answered, 11.82 s | Answered, 13.66 s | 1 original citation, 1 highlight |
| 1794 actual ceiling height | Insufficient, 10.36 s | Insufficient, 9.30 s | 1 original citation, no highlight |
| 11397 first-floor outdoor label | Answered, 11.86 s | Answered, 10.79 s | 2 original citations, 1 highlight |
| Genuine duplex IFC window count | Answered, 27.33 s | Answered, 24.31 s | 24 original-record citations/highlights; server count |
| Genuine duplex IFC as-built inspection date | Insufficient, 9.72 s | Insufficient, 11.94 s | No fabricated source reference/highlight |

Each pipeline answered 3 of 5 selected questions and refused the two unsupported questions. Source-based label/count spot checks found no error among the three answered questions and no unnecessary refusal. This does **not** establish an accuracy percentage or demonstrate an accuracy improvement from review. Variation between individual latency measurements is not a performance claim.

The successful baseline runs used 513,431 input and 6,816 output tokens; reviewed runs used 774,923 input and 5,219 output tokens. Provider usage is recorded; monetary cost was not calculated. Two reviewed 1794 outputs were reused from the immediately preceding successful live compatibility run. The 11397 rerun followed the narrow exact-name highlight fix.

Initial failures remain part of the evidence:

- One 1794 baseline height generation exceeded its 45-second call deadline. A separately recorded targeted rerun succeeded; no automatic unlimited retry was added.
- Both native inspection-date attempts initially failed operationally. A controlled live gate reproduction confirmed the external 262,144-token input maximum was exceeded. Retrieval had selected 122 unrelated/related records through generic name substrings, producing 1,858,716 bytes of context. The corrected type-relevant selection retained 24 window detail records plus the complete 333-record identity catalog, 235,947 bytes. The unchanged question then passed live in both pipelines. No arbitrary record cap was introduced.
- The initial 11397 answer had source citations but no highlight because an outdoor space and its open edge shared an identical source box. Applying the existing exact-name check before uniqueness restored the correct unique association. Same-name ambiguity still suppresses highlighting.

The native extraction audit also found predefined window/door lining property sets with scalar entity attributes. The extractor now preserves those values and units instead of marking them unsupported. Geometry-less records remain in the native catalog. Available property coverage and geometry coverage remain separate.

## Live reconstruction review compatibility

The original 1794 drawing, its exact saved description and blended overlays from actual reopened IFC geometry reached the reconstruction reviewer successfully: 72.81 seconds, 19,955 input and 10,122 output tokens. It returned three actionable issues and declined to approve the current model. This verifies the hook and demonstrates disagreement; it is not a claim of successful refinement or full fidelity. Integrated refinement and browser acceptance are tracked separately by the orchestrator.

## Deterministic fixtures, not live inference

`test_reviewed_qa.py` injects confidently wrong drafts, contradicted refusals, newly inspected evidence and support judgments. It demonstrates source-bound count correction, one meaningful repair, false-abstention recovery, strict unsupported-claim removal and rejection of mere rephrasing. These fixtures do not measure model behavior.

`test_review_provider.py` uses actual SDK serialization with mocked HTTP transport for original images, actual-IFC overlays, typed patches, the four-way Decisions judgment and deadline clamping. Separate live calls above establish API compatibility. Overlay pixel tests preserve original source strokes; native reasoning tests cover incomplete aggregate inputs, semantic catalog coverage, original property units and disconnected-shell volume rejection.

Local live outputs are under `/tmp/product-live-backend/`: `report.json`, `evaluation-summary.json`, `qa-evaluation/`, `qa-evaluation-fixes/`, and the reconstruction review/overlay. These contain local artifacts and responses and are not committed. They are ephemeral verification evidence, not the persistent demo-building store.
