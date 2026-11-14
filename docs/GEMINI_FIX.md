# Gemini structured-output diagnosis — 2026-11-14

The remaining 400 was reproduced with the current `response_json_schema` path, not the older `response_schema` path. The configured model was `gemini-flash-latest`; a successful response identified `gemini-3.8-flash`. SDK: google-genai 3.3.0. No model/provider switch or source-image edit was used.

## Controlled live evidence

The original files went through the app's existing image normalization. Their SHA-256 checksums were unchanged:

- `colorful-1794.png`: `c9547f7c5374a2a26670175fa4825c5d9dc535e8ccb7c8405a04cacbcb99b204`
- `colorful-1732.png`: `bc84828d4de3c7f602cb2355612ec1632b30297f6e07ab593a89f0448bc9b3b7`

| Probe | Result |
| --- | --- |
| Original reconstruction JSON schema, both files | HTTP 400 INVALID_ARGUMENT, generic invalid-argument message |
| Remove only `minItems`, 1794 | Same HTTP 400 |
| Remove only array `maxItems`, 1732 | Accepted, 3 room records validated locally |
| Original structured-answer schema, 1732 | HTTP 400 |
| Remove only array `maxItems`, otherwise identical answer request | Accepted, STOP, answered with one source citation |
| Relaxed reconstruction schema, 1794, original 45 s deadline | Deadline/timeout failures |
| Same 1794 request with 120 s diagnostic deadline, original 8,192-token budget | MAX_TOKENS: 7,864 reasoning tokens and 314 response tokens; incomplete JSON, rejected locally |
| Same source/schema, 16,384-token budget and 120 s deadline | STOP, 6 room records validated locally, 16.57 s in this diagnostic run |
| Larger budget/deadline, full app, default thinking | 1794 succeeded in 126.68 s; 1732 subsequently failed HTTP 502 in 118.9 s; insufficient for the demo |
| Reconstruction-only low thinking, 16,384/120 s | Both accepted: 1732 in 4.95 s, 1794 in 7.98 s |
| Low thinking, original 8,192/45 s | Both accepted and locally valid: 1732 in 7.50 s, 1794 in 5.92 s; temporary budget/deadline increases removed |

The SDK transport was instrumented without logging request bodies or credentials. The schema received by the HTTP transport matched the requested schema. For the 1732 reconstruction baseline/ablation, the serialized body excluding only `responseJsonSchema` had the identical SHA-256 `a8cb621f2276f7b6a21f435444784ef94c15b2b62119aa076050d4e7e5bf179c`. This isolates schema changes from source, prompt, model and generation settings.

These results show that the `maxItems` combination in these schemas triggers rejection on this endpoint. They do not establish that every `maxItems` constraint is unsupported or identify the server's exact internal complexity threshold. Google's [structured-output documentation](https://aistudio.google.com/docs/structured-output#simplifying-complex-schemas) explains that schema compilation can reject combinations of bounds and structure and recommends application-side validation.

## Implemented boundary

`gemini_wire_schema` removes array `maxItems` only from schema nodes, including definitions. It preserves types, required fields, enums, references, `minItems`, additional-property rules, and ordinary data/property names. Full Pydantic bounds and geometry/source validators still run after generation. OpenAI schemas, factual-answer prompts, Decisions, citation rules, refusal behavior and assumption separation are unchanged.

Only Gemini reconstruction gets `thinking_level=low`. The original 8,192-token generation budget and 45-second deadline are retained; temporary diagnostic increases were removed after low-thinking requests passed within the originals. Low thinking is a deliberate latency/geometry-quality tradeoff for approximate display geometry, not an API requirement or input limit. It may spend less effort on difficult boundaries; it does not relax local geometry validation. Factual answering, crop selection and Decisions keep their existing settings. There is no added retry or provider fallback. The configured Gemini 3.8 Flash supports this setting in its [official model documentation](https://aistudio.google.com/docs/models/gemini-3.8-flash).

`MAX_TOKENS` is an operational failure even if the returned JSON happens to parse. It is rejected before scene caching. Generic reconstruction request failures no longer tell the user to replace a supposedly poor-quality image.

Full application testing then exposed a separate local 422 on 1732: one generated 26-vertex polygon had a ring self-intersection, while the other two polygons were valid. The reconstruction prompt now explicitly asks for a simple perimeter traversed once in order, excluding furniture/cabinet/door-swing outlines. This clarifies an existing geometry requirement, not a new input restriction. A later 1794 output contained two overlapping footprints; prompt clarification alone was not sufficient.

The former all-or-nothing visualization policy now retains an explicitly partial model: invalid room footprints are omitted, and every participant in every ambiguous-overlap pair is omitted before rendering (no order-dependent winner). Surviving polygons and original room-index IDs are unchanged. Warnings visibly report the omitted count. No survivors still returns 422 without caching. Whole-response Pydantic bounds stay strict. There is no geometry repair, invented replacement, automatic retry or image edit. Omitted rooms cannot receive highlights; their original source evidence remains available to factual answering.

This policy relaxes whole-model availability, not individual geometry validity or evidence sufficiency. It can omit a usable room when its proposed footprint conflicts with another; the incompleteness warning and source-only answers make that limitation explicit. Generated room counts remain nonfactual.

The existing room/vertex/list limits remain local design choices, not Gemini requirements. This fix neither lowers them nor silently accepts over-limit output. Existing source-reference, bounds, polygon and calculation checks remain unchanged; semantic correctness is not guaranteed.

## Regression checks

New tests exercise actual SDK request serialization/transport and assert that local bounds remain enforced, truncated outputs are rejected, and reconstruction's low-thinking setting does not leak into answer/crop/gate calls. These mocked checks supplement the controlled live tests above; they do not establish API compatibility by themselves.

## Application endpoint verification

The final smoke run uses the real Gemini provider through FastAPI TestClient: multipart upload, POST scene, cached scene reuse, POST question with the actual Decisions gate, and GET scene comparison. It is not a mocked inference run.

Final production-code run completed successfully on both unchanged files:

| Image | POST scene | Supported source question | Missing actual ceiling height |
| --- | --- | --- | --- |
| colorful-1794.png | 200, 6 approximate room objects, 12.20 s | 200, sufficient/answered, 1 citation, 1 validated highlight, 12.29 s | 200, insufficient, 0 highlights, 7.68 s |
| colorful-1732.png | 200, 3 approximate room objects, 15.38 s | 200, sufficient/answered, 1 citation, 1 validated highlight, 7.97 s | 200, insufficient, 0 highlights, 6.45 s |

The real Gemini crop request on 1732 also returned a locally valid CropRequest. Both source checksums remained unchanged. Repeated scene POST/GET calls returned identical cached geometry after answering. These are integration checks, not a general accuracy benchmark. No ground-truth question files were used as runtime context.

Final regression suite: **119 passed, 7 optional browser tests skipped**. Independent final review: **68 focused tests passed**, no code blockers. The new filtering tests verify exact surviving geometry/source references, original-index IDs, omitted highlights, containment and overlap chains, visible warnings, caching, and zero-survivor rejection.

Diagnostic full-app run before low thinking: 1794 returned HTTP 200 with six unscaled room objects (126.68 s), a cited/highlighted answer (8.62 s), and height refusal (9.35 s), but 1732 failed after 118.9 s. This was not accepted as completion. The final low-thinking endpoint run is recorded below.

Room footprints varied between generations. Runtime success and structural validation are not a measurement of footprint accuracy; generated geometry remains approximate and must never supply factual room counts or dimensions. Cached scenes avoid changing geometry between questions.
