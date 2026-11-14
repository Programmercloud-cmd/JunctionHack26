# Schematic fidelity iteration — 2026-11-14

## Method and diagnosis

Reused the exact descriptions embedded in `/tmp/junction-page-scale/colorful-11397-page-scale.ifc` and `/tmp/junction-v3/final/colorful-1794.png.ifc`. Both were replayed with unchanged original PNGs and the same artifact namespace. No new Gemini extraction, manual cropping, source correction or fixture substitution was used. Matched baseline and updated artifacts are under `/tmp/junction-fidelity-v4/`; the baseline generator comes from commit `441044c` and therefore already includes shared-page scaling.

Actual reopened meshes and original-coordinate overlays established two deterministic problems: five valid 11397 width segments failed after rotation, and supplied reference lines on wall faces were treated as centerlines. The latter left gaps where the depicted wall bands should touch. Most captured furniture was only .02 display units tall beside 1.2-unit walls; elevated views exposed existing geometry, distinguishing visibility from extraction omissions.

11397 already contains 27 feature descriptions across two floors; 1794 contains 10. Rendering these more clearly cannot recover unextracted items or correct mistaken source classifications.

## Wall checkpoint

Committed as `db5988a` after independent review. The reviewer found an additional rotated full-span opening rejection caused by approximately −1.8e−18 longitudinal projection values. Moving projection into the original aspect-correct source plane fixed it without snapping or extending endpoints. Focused tests include reversed axes/gaps, all quarter-turn orientations, source-face offsets, real IFC void sections, deliberate positive gaps, unsupported widths and physical calibration.

The original-page section gap between 11397 ground-floor “Exterior wall top” and “Interior wall horizontal 1” changed from .008526315789 page width to zero. Their original axes were not moved. Actual bands now meet at x=.062. Sample source→display→source round trips remain within 1e−12.

| Exact saved description | Baseline | Wall correction |
|---|---:|---:|
| 11397 rendered / unresolved | 76 / 9 | 78 / 7 |
| 11397 rendered walls using default width | 5 | 0 |
| 11397 reconstructed windows | 6 | 8 |
| 1794 rendered / unresolved | 34 / 2 | 36 / 0 |
| 1794 reconstructed windows / doors | 1 / 4 | 2 / 5 |

No previously reconstructed opening was lost. Exact descriptions, original source pixels, artifact IDs and all element IDs survive generation/reopening. Unknown units remain relative. Counts describe inventory status, not source completeness.

## Remaining source-fidelity limitations

- 1794's thick kitchen/bath partition comes from a supplied .067-page-height cross-segment. The new generator preserves it rather than silently substituting a cap. It is visibly too thick against the source.
- 1794 still has an extracted wall through its balcony and sink/hob classification problems. Zero unresolved records does not mean a correct model.
- 11397 still has conflicting upper-floor wall/open-edge descriptions and associated unresolved openings. No proximity rule or arbitrary winner resolves them.
- Furniture schemes cannot establish actual heights, support counts, facing or stair rise. Some meshes remain occluded by walls at some orbit angles; source overlays remain necessary. Generic beds/appliances/bench blocks need source-linked labels for identification. Dense unresolved annotations can cover small features in some views.
- Completely omitted source features are not automatically discovered by this deterministic pass. The inventory accounts for supplied entries only; full original-image fidelity acceptance remains unmet.

## Feature and viewer verification

Final artifacts are `/tmp/junction-fidelity-v4/schematics/11397.ifc` and `1794.ifc`. Every one of the 27 and 10 actual reopened feature mesh projections has zero source-area difference from the corresponding wall-checkpoint projection. Floor transforms, element IDs, source references and representation statuses are identical. Non-feature meshes are unchanged by the feature phase. Assumed relative heights now range from .12 (level stairs/shower symbols) to .60 (cabinets), with table .36, chairs/bed .24 and sink/toilet .30. These are display units, not measured metres.

Original-page comparisons and default/elevated model captures for every floor are in `/tmp/junction-fidelity-v4/{baseline,walls,schematics}/captures/`. The independent reviewer also launched their own server/browser and personally inspected originals and captures in `/tmp/reviewer-feature-browser/`. They performed real mouse drag-orbit on all three floors, switched floor filters, clicked an unresolved annotation on each 11397 floor, inspected original-region evidence, and toggled actual-IFC source overlays. Highlights and 10% surrounding opacity were checked using an explicitly injected review fixture answer, not real inference. Assumption toggles remained independent; no JavaScript errors or scoped implementation blockers were found.

Tables with surrounding chairs, cabinet runs, recessed sanitary glyphs and level stair marks are more legible. Browser inspection also confirmed the extraction limitations above; successful model display is not full-fidelity acceptance. Coarse floor badges and all-unresolved behavior were checked with fixtures because these exact artifacts do not exercise every annotation case.

Verification on the final implementation:

- `bash scripts/test.sh`: **344 passed**, 14 opt-in checks skipped (13 browser checks plus the external IFC sample check).
- All five browser suites with `RUN_BROWSER_TESTS=1`: **13 passed**. Includes native IFC orbit/selection, derived export/reopen, source citations, unsupported-height refusal with fake providers, independent assumptions/highlights and unresolved annotations.
- Independent reviewer: 98 wall/scale/boundary and 78 feature/generator/comparison tests passed, plus their own actual-artifact browser interactions.
- Doctor passes; configured credentials were not exercised. No new Gemini compatibility or live QA claim is made in this deterministic iteration.
- Exact-description replay checks original embedded PNG bytes, stable artifact/object IDs, unknown units and portable reopening. Feature tests also cover physical calibration, concave footprints, actual cavity geometry, level stair marks and fresh-store source-context exclusion of generated assumptions.

Commits: baseline `441044c`, wall correction `db5988a`, source annotation viewer `6ba092d`, feature schematics `82bc8cf`. No push or deployment. Old cached/exported IFCs retain their stored geometry; import the final artifacts above for this saved-description demo, or generate a new model normally.
