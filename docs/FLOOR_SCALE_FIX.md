# Shared page display scale — narrow reconstruction repair

## Diagnosis and reviewed plan

Inspected the exact description embedded in `/tmp/junction-502-fixed-live/colorful-11397.png.ifc`, its actual stored floor transforms and `_floor_frame`. The source is unchanged 475×650 `colorful-11397.png`; both floors lack physical calibration. Ground bbox is [.043,.016,.498,.984], upper bbox [.52,.134,.924,.984]. Previously each panel independently normalized its longest extent to 10 display units. The resulting original-page Y factors were 10.3305785124 and 11.7647058824: equal drawn spans on the upper floor appeared 13.88% larger.

This confirms a deterministic transform defect, not a new extraction failure. The planner proposed a page-derived unknown scale, an independent reviewer approved it, bounded backend/frontend owners implemented it, and independent implementation review found no remaining blockers. Scope excludes extraction changes, automatic alignment, shape editing, provider changes and legacy migration.

## Change and assumptions

For uncalibrated diagrams, `_floor_frame` now uses `10 / max(page.width / page.height, 1)`. One full page's longest extent maps to 10 arbitrary display units. All uncalibrated diagrams on that page therefore preserve their original relative image sizes. Floor bbox centering still controls translation; orientation still controls rotation. Neither bbox nor outdoor extent determines scale.

This is a presentation convention, not a physical measurement or proof that the diagrams share a drawing scale. Independently resized diagrams retain the proportions visible on the supplied page. Different pages use independent page frames; their physical size/registration relationship remains schematic. The existing supported physical-calibration branch is unchanged and is not propagated to uncalibrated floors. Unknown/mixed projects remain `UNSCALED_DISPLAY_UNIT`/relative; no forced equal footprints or alignment.

New floor provenance uses `page_extent` instead of `panel_extent` and explains this convention. The UI displays the explanation only when every unknown floor has the new marker and none retain the old marker. Calibrated-only, legacy, absent or mixed legacy metadata cannot claim the new behavior. The reader continues to use stored transforms; merely reopening an old IFC does not rescale it.

## Verification from the saved real description

Regenerated the exact embedded Gemini description and original PNG with the same source document identity. No extraction calls, source edits or geometry corrections were made. The original artifact namespace and all object IDs are preserved.

| Actual mesh measurement | Before | Corrected |
| --- | ---: | ---: |
| Ground overall long plan extent, display units |9.66909|9.36000|
| Upper overall long plan extent, display units |9.61176|8.17000|
| Ground original-page Y factor |10.33058|10.00000|
| Upper original-page Y factor |11.76471|10.00000|

These are visualization dimensions, not measured metres. The larger ground terrace now yields a larger overall footprint. All 11 rendered interior-room meshes inverse-map to the same original coordinates as before. A separate regression mutation of the saved description extends only the ground terrace and its floor bbox: the total extent grows to 9.51 display units while every existing interior's dimensions stay unchanged. That test mutation is not included in the corrected artifact.

- 237 backend/native-IFC tests passed. Six new actual-mesh regressions cover differing panel bboxes, outdoor expansion/translation-only change, rotations, nonsquare physical calibration/mixed scale, differently sized PDF pages, source round trips and legacy transform preservation.
- Two focused browser regressions passed, including multi-page export/reopen, source clicking/highlights and new-versus-legacy disclosure. Independent reviewer passed 87 focused tests and reopened the actual old IFC, verifying its old transforms, assumptions and IDs remain unchanged.
- Separate browser verification of the corrected real IFC passed source clicking, the original-coordinate comparison overlay, download/reupload with identical IDs/transforms, and unchanged legacy labeling, with zero provider calls or JavaScript errors.

Corrected artifact: `/tmp/junction-page-scale/colorful-11397-page-scale.ifc`. Reports, verification scripts and screenshots are in `/tmp/junction-page-scale/`. Upload this IFC to review the correction without another Gemini extraction. Existing downloaded/cached IFC geometry stays as saved; this regenerated artifact carries the new transforms.

Previously reported extraction omissions and misplaced features remain outside this scaling fix. Source-only QA, citations, refusals and assumed-height separation are unchanged.
