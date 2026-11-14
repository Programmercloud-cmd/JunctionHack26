# Public demo verification — 2026-11-14

The application is deployed at https://95.133.254.90.sslip.io on one Verda CPU VM with persistent storage. This report distinguishes public live verification, cached-artifact inspection and deterministic tests. Deployment details, resource IDs and manual export/teardown instructions are in [VERDA_DEPLOYMENT.md](VERDA_DEPLOYMENT.md). No push was performed.

## Access and examples

Nine pinned examples are public. A shared code unlocks paid Gemini QA, uploads and private work. Code holders share a workspace; these are not private per-user accounts. The prepared example sources/model revisions remain immutable even after unlocking. Their original-source QA is allowed against the pinned revision.

The operator's code is stored locally in `/tmp/junction-verda/private-deployment/demo-access-code.txt`; it is not committed or sent to browser storage. The service receives only a salted verifier and session secret, with Gemini credentials kept server-side. Cloud credentials remain on the operator's machine.

The selection contains 3181, 34, 11397, 1794, church 22921604, unseen 10262, religious SVG 14661814, KIT institute PDF and the original duplex IFC. Eight are derived models; the duplex is supplied native IFC evidence. Saved review failures/findings were preserved. “Reviewed” does not mean accurate or complete.

Independent Chromium review used normal certificate validation against the public hostname, not localhost. All nine examples loaded the exact selected revision, could be orbited and supported source clicks. Floor controls, separate assumptions and original-coordinate overlays worked. Native object evidence returned the original GlobalId record. No unexpected browser mutation calls or JavaScript errors were recorded.

Access verification confirmed anonymous QA/chat rejection, hidden private history and unknown revisions, and rejected reconstruction/extraction of shared examples even after unlocking. The session cookie is Secure, HttpOnly and SameSite Strict. The code was absent from local/session storage. Locking reloads the app and clears the private selection/model. A five-second observer initially timed out during network reload; a longer observation confirmed the reload completed, without an application change.

## Live public Gemini checks

These used the deployed UI, real intent routing and the existing source-based QA pipeline; no fake provider or cached answer was substituted. Token usage below is the QA answer's recorded usage; end-to-end duration also includes routing and polling and must not be treated as provider-only latency.

| Original | Check | Result | End-to-end time | QA input/output tokens |
| --- | --- | --- | --- | --- |
| 1794 | Identify the balcony's original label | Answered, two page-region citations, one validated object highlight; citation opened original source | 33.31 s | 60,344 / 1,051 |
| 11397 | Actual first-floor clear ceiling height from original only | Insufficient; one source citation, no invented height or highlight despite visible extrusion | 30.40 s | 56,646 / 724 |

On updated release `a470a11`, unchanged 1732 was uploaded as a new private building. Its extraction job was observed queued, the browser was refreshed, and the saved building was reopened. Interpretation completed in 19.29 seconds (1,943 input / 2,271 output tokens). A source-only entrance-label question then answered in 29.25 seconds (34,728 input / 1,686 output tokens), before optional geometry.

Optional geometry took 331.44 seconds (73,504 input / 57,616 output tokens across its recorded calls). It generated a usable preview, then source review rejected the proposed correction: the job finished `needs_attention` with that preview retained. This is an accurately reported partial outcome, not completed model review. No blind retry or model substitution followed.

Independent public browser inspection of retained revision `d009e9abbb494136ab8d38780d7dd24a` verified orbit, original-revision source clicks, eight assumption rows and saved source-only QA. It has 29 semantic records, 24 meshes and five unresolved openings. All labeled spaces and seven schematic furnishings/fixtures are represented, but the two windows and three doors lack hosts; walls remain solid at those openings. The fridge/freezer and bathroom shaft are missing. Initial 30-second reopen observations expired with the document already set and the UI busy; later traced requests all returned 200 and the model opened. The exact delay cause remains unisolated.

The actual public 1732 IFC download reopened locally, then was reimported through the public browser. All 29 object IDs, source references, assumptions and relative units matched; one original page remained embedded. Identical original reupload reused the saved interpretation/model without another job. These operations issued only authentication/upload requests, with zero provider calls and zero browser errors. Separately, the public 11397 IFC download reopened with all 22 IDs, source references, assumptions and relative units preserved.

Post-upload server restart passed: all 516 persistent file hashes, all CURRENT pointers and five jobs were unchanged across 11 saved buildings (nine examples plus the private original/reimport). All 436 seed files remained intact, persistent storage stayed mounted and no inference job was created. Anonymous users still saw exactly nine examples; both private buildings returned 404. A subsequent trusted-HTTPS browser session reopened the original's retained model in 8.77 seconds and the imported IFC in 2.15 seconds, each with 29 records/24 meshes, matching revisions and relative units. Only authentication was posted; no provider calls or JavaScript errors occurred.

## Fidelity limitations

Actual reopened IFC overlays still expose missing or misplaced geometry. The 3181 model retains a wall crossing the bed/bedroom. 11397 has sparse interior geometry. The religious SVG lacks curved features and columns; the institute model misses facade windows. The institute's legacy IFC retains relative display units despite a description calibration; it must not be represented as measured geometry. The unseen 10262 model fills an upper open volume as a room floor. Church full geometry recovery still fails strict checks; a previous usable partial model remains available.

Zero unresolved records is not a completeness score. Generated geometry, assumed heights and user inputs remain distinct from original evidence. This deployment does not claim that every reconstructed building is faithful or that the earlier church recovery acceptance has passed.

The fresh-building browser review also found presentation defects: the workspace header retains the revision's `preview reviewing` label after the job has finished `needs_attention`; a pending-model note remains alongside the accurate terminal job message; reopening can duplicate the single persisted answer card without another QA call. These were routed with reproduction evidence to the separate UI corrective worktree. They are not claimed fixed in `a470a11`. The exact history deduplication defect is missing job/request identity on restored answer cards, allowing the next job poll to append a second card.

## Reliability checkpoint

Independent review cleared the bounded chat fixes in `37c4dd1`: wait for an in-flight completed-model fetch, retain navigation staleness checks, show submitted input scope/reason and attribution, disclose unmapped/off-floor answers, and toggle comparison layers independently. No provider, geometry or sufficiency behavior changed. Browser fixtures exercise UI contracts; they do not establish live extraction fidelity.

The full browser-enabled regression suite passed **760 tests with one optional test skipped** in 288.61 seconds. The environment doctor passed. The independent reviewer separately passed 17 focused tests and directly rechecked deployed `a470a11`: the restored 1794 answer highlights one object while 37 surroundings fade to 10% opacity; the 11397 refusal has no invented highlights. Turning off the spaces comparison layer preserves wall overlays and the overall comparison.

The initial server restart preserved all 436 prepared seed-file hashes and all nine examples with zero provider calls. The code-only update to `a470a11` then preserved all 440 persistent files, including both live QA jobs and history, without reseeding or replacing credentials. The installer now waits for readiness for up to 60 seconds after service start; that is an operator verification timeout, not a new limit on uploaded drawings or inference jobs. Existing application processing budgets remain unchanged.

Private verification artifacts are under `/tmp/junction-verda/public-browser-review` and `/tmp/junction-verda/public-acceptance`; these include source imagery and generated responses and are not committed.
