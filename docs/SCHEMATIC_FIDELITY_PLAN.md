# Narrow schematic fidelity iteration

## Evidence and scope

Reviewed the exact descriptions embedded in the latest page-scale11397 IFC and saved final1794 IFC, actual reopened meshes, source images and default/overhead viewer captures. Matched baselines are regenerated with the shared-page-scale generator for both sources, without new extraction.

11397 supplies thickness segments for every described wall, but five rendered walls fall back to an assumed width because a transformed endpoint intersection fails after rotation. Several reference lines also lie on a depicted wall face: centering the strip on that line places half the material on the wrong side and leaves gaps at supported contacts. The oversized1794 kitchen/bath partition already has a supplied .067-page-height thickness segment; it is an extraction error, not a default-width bug, and must not be hidden by an arbitrary cap.

Captured features already exist:11397 has27 feature descriptions and1794 has10. Most exported feature bodies are only .02 display units tall beside1.2-unit walls; the stairs are .025 including level marks. Overhead inspection reveals captured tables/chairs/cabinets/fixtures. Unresolved records have no mesh and currently appear only in source comparison/list views.

## Reviewed implementation sequence

1. **Wall bands:** Validate the supplied thickness cross-segment in original/aspect-correct source coordinates before rotation. Preserve its signed normal offsets relative to the supplied reference line; do not force symmetry. Actual band contacts create supported junctions without endpoint snapping, nearest-wall attachment or gap bridging. Invalid widths retain explicit display assumptions.
2. **Openings:** Retain named hosts, original gap endpoints, along-wall range and source-region checks. Validate normal position against the supported face band. Center the display fill/void normally within that band and cut its full depth, with an explicit display-placement assumption; this is not a measured frame position. Old centered-band acceptance is not authority: source-incompatible cases may remain/become unresolved. Audit actual changed cases against originals.
3. **Feature schematics:** Keep the supplied footprints and IDs. Use simple raised tops/supports, blocks and basin/rim symbols rather than barely visible generic plates. All additions stay within footprints and carry display assumptions. Using the existing assumed wall height H, category display heights are table .30H, chair/bed .20H, sofa/sink/toilet .25H, cabinet .50H, appliance .40H and shower/bath/stairs/other .10H. Support glyphs do not establish real leg counts; no chair-facing inference. Raised stair footprints stay level, without asserted ascent, riser dimensions, travel direction or source step count.
4. **Viewer:** Use a more elevated initial view for derived scenes. Unresolved HTML annotations are source-region markers, not geometry, exported IFC entities or answer highlights. Position precise annotations from original regions and stored transforms; use floor-level badges for coarse/unlocalized records. Clicking shows source evidence and uncertainty. Keep floor filtering, exploded display, independent assumptions and source-only QA intact.

These are hackathon display choices, not physical measurements or completeness guarantees. They introduce no new input caps. Model classifications remain fallible; richer rendering must not disguise known extraction errors.

## Ownership, review and commits

Root owns contracts, integration, verification and commits. Backend owns generator and focused geometry tests, first walls then feature schematics after a wall review checkpoint. Frontend owns viewer/annotation UI and browser regressions. Independent reviewer remains read-only and checks each changed behavior. The user explicitly requested regular suitable progress commits; no push/deployment is authorized. Baseline checkpoint:441044c.

No source/schema/provider changes or extraction calls are planned. No new formats, materials, assets, infrastructure, photorealism or inferred floor alignment.

## Verification

Use unchanged11397 and1794 source images and their saved descriptions. Compare actual reopened IFC wall bands, T/L contacts, positive doorway gaps, void cuts, relative widths and feature footprints/heights with original-page overlays. Test rotations, reversed/one-sided cross-segments, unsupported thickness, off-center void depth, calibrated/relative units, stable IDs, source inverses and portable metadata. Verify unresolved markers never enter meshes/highlights/exports and remain usable with floor filters, separation and assumption controls. Preserve page-scale regressions and original-only QA/refusal checks. Report remaining source omissions, mismatches and unresolved cases explicitly rather than calling successful rendering fidelity acceptance.
