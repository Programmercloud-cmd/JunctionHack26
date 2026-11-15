# Separate agentic public deployment — 2026-11-15

Status: **live at https://agentic.95.133.254.90.sslip.io/**. The final creator-plus-two-parallel-reviewers implementation, Buildings/shared-drawings UI, branding and deployment fixes are included. Trusted public HTTPS, access controls, live inference, actual generated-model browsing and restart persistence passed.

The existing `blueprint-qa-isolated` demo at `https://95.133.254.90.sslip.io/` remains running. The agentic worktree is `feat/agentic-chat` at `/tmp/junction-agentic-chat`. The user-authorized implementation commits through `706aa5c` are pushed to that branch.

## Current manual-slicing release

Source `090850d79bf238ffba0a158c8a088d42364365ce`, frozen under `/tmp/junction-agentic-publish/release-v13/source`; content identity `c7ff072fe23e1e5538829ef5d873e8be3084489af95f16bddc8a0d889e46542b`; archive SHA256 `c89463d5d1a9407ed50ee8f8fe03980d48986fc51641ad16f6f3e4763e30cf94`. All 75 production hashes match. The sole production changes from V12 are workspace-controls.js and workspace-drawers.css; renderer, Python, credentials and access configuration are unchanged.

The original Visible height range/output is now in **View settings below Floor** for usable 3D Model/Concept views, with its original listener and clipping semantics. The slider synchronizes with viewer state and is hidden/disabled for Drawings or unavailable geometry. Eighteen focused frozen browser checks passed in 75.20 seconds; independent slicing review passed its relevant public-controls/drawer suite. Actual live saved generated and native IFC models clipped at 40%, preserved that setting in Concept, fit mobile and restored unclipped geometry at 100%, with identical saved scene/revision JSON and no script errors, API mutations or inference calls. Reports/screenshots: `/tmp/junction-slicing-live/`.

Publication passed the active-job gate and retained all 834 runtime hashes. The old demo's process/release/configuration and 1,154 recorded hashes remain unchanged. Shared ElevenLabs readiness and the timed access policy remain unchanged. V12 below remains the full backend-suite baseline for the unchanged server code.

## Current voice-output release

Source `0cc2f2ebf7f83353edc026b3e2b06f6f78ba9e33`, frozen under `/tmp/junction-agentic-publish/release-v12/source`; content identity `19e6b706028578e194a9a25740c78a5a155a7c641c9ed28220d3781cdd0566b5`; archive SHA256 `b8c21c6648250eb1bc6a6212bd982a503c1e109786b4cb8d0f06e9f017d65573`. All 75 deployed production hashes match. Frozen checks passed **1,134 default tests / 143 optional skipped** and **28 browser checks**. Independent implementation review additionally passed focused voice/context/format checks and all six current product speech browser cases.

ElevenLabs output is restored using the user's explicitly authorized shared key and existing voice, configured only in the root-owned agentic environment (0600) and the feature worktree's ignored local environment. The original app environment is untouched. Credentials never enter public config or the production archive; readiness exposes booleans only. Normal and source-free chats, technical answers and clarification questions use the existing opt-in speaker toggle, captured session guards, deterministic technical formatter and cancellation/autoplay behavior. [Contract](VOICE_CONTRACT.md) and [verification](VOICE_VERIFICATION.md).

The guarded code update retained all **832 runtime hashes**. Actual public chat-to-speech returned one HTTP 200, no-store MPEG response (33,061 bytes), with Chromium playback advancing and successful toggle-off; zero script errors. The temporary metadata-only verification Building was then hidden without deleting its history or any original source. Independent live GET-only checks confirmed speech_ready, enabled/default-off speaker controls in existing empty and drawing chats, no history replay and unchanged 09:30–14:30 Helsinki policy. The original demo retained its process/release/configuration and all 1,154 recorded hashes. The idle local 8012 restart retained all 125 hashes and now has speech readiness too.

Private artifacts are under `/tmp/junction-voice-restore/` and `/tmp/junction-agentic-diagnostics/independent-v12-voice/`. The real provider/decoded/playback observations are distinct from injected speech fixtures. No general answer-accuracy or speech-pronunciation claim is made.

## Published composer focus follow-up

Current code release: `30c374fd00c03bef62cbc5cbc062520318f81e77232db82163586a712164ab49`, source commit `1533900885ccf510f99054fb0a634d289573060e`, archive SHA256 `bf8ab8e93839050576c4e668cc68112ae69b581c7e5444305e48eea8becf6f1c`. Compared with V10 below, the sole production difference is `app/static/styles.css`: the explicitly requested composer-only `textarea:focus{outline:none}` rule. This adopts the previously preserved local CSS edit; it is no longer pending work.

Independent actual-app checks confirmed no composer outline/shadow on click and Tab focus in both themes, while other keyboard-focused controls retain their solid 3px outline. The live trusted-HTTPS stylesheet hash matches the frozen file; both sites return 200. Publication passed the idle-job guard and retained all 830 runtime hashes. The access schedule and Python/rendering/source configuration are unchanged. Focus verification evidence is private under `/tmp/junction-agentic-diagnostics/composer-focus/`; V10's full suites below are the unchanged-behavior baseline.

## Current published release: Buildings and shared drawings

- Source commit `706aa5c40d70b3beee84bd13c534501583a45041`, from a clean detached checkout, frozen under `/tmp/junction-agentic-publish/release-v10/source`. The unrelated concurrent local `styles.css` edit remains preserved and excluded.
- Content identity: `96084b01f2747cd6424bf93b53f3c22f3fa139350abfb48c13799063fdc1197b`; archive SHA256: `06067507601955f70dd8fa7bcd8e15db4bafc9d2d371ee0c670714735d9a9bb8`. All **75 deployed production files** match this exact tested archive.
- Frozen verification: **1,120 passed / 137 optional skipped** in 104.55 seconds, plus **52 Chromium checks passed** in 226.71 seconds. Independent implementation review additionally cleared 23 backend/access and 17 browser checks. Tests cover [shared Building scope and legacy preservation](BUILDINGS_SHARED_DRAWINGS.md), uploads, chats, source/model marks, task origins, voice lifecycle, public controls and timed access.
- Buildings replaces the Project UI without another hierarchy level. The overview exposes Drawings, Chats and Upload drawings; new uploads join the Building's shared source group. Visualizer drops capture the current Building; composer Attach and visualizer Import are removed. Picker and wide arrows change only the visible drawing, preserving the current chat and draft.
- The user-selected legacy representation is explicit separate Building entries for independently uploaded groups. Original conversation owners, sessions, source/model revisions, annotations and historical references are retained. Native IFC remains separate. Older bundles linked to multiple owners reject source append with an explanation; their inspection/chats stay usable. New Buildings isolate identical original uploads rather than adopting another group's appended sources/model/history.
- Publication passed the active-job gate and retained **all 830 runtime files byte-for-byte**. The previous V9 code release remains installed. No source/model/history restore, merge or deletion occurred.
- Actual authenticated HTTPS browser acceptance opened an existing owned chat and two existing drawing files. File switching preserved that chat and an unsent draft; overview upload, absent Attach/Import, mobile arrows and fit passed with zero script errors, browser mutations or inference requests. Independent GET-only public review passed both trusted HTTPS URLs, nine pinned read-only examples/scopes, the new overview/picker/arrows, exact selected-source pin and mobile layout.
- The original demo retained its process/release/configuration and **all 1,154 recorded runtime hashes**, with its original Caddy host block intact. The persisted **09:30–14:30 Helsinki** access policy hash is unchanged. The idle local 8012 preview was also restarted with all **125 runtime hashes unchanged**; active work was checked before restart.

Private results are under `/tmp/junction-buildings-verification/checks/`, including frozen logs, actual saved-artifact screenshots, live existing-chat navigation and local restart checks. Independent public evidence is under `/tmp/junction-agentic-diagnostics/independent-v10-public/`. These are UI/ownership/preservation checks; no new live inference or general model-fidelity claim is made.

## Previous release V9: drawing navigation and attributed measurements

- Source: clean committed snapshot `0b4f9ba671b8a95ca7fe57ddf88c17977d94a0f5`, frozen under `/tmp/junction-agentic-publish/release-v9/source`. Its release metadata records a detached checkout. An unrelated concurrent local `styles.css` edit was preserved and excluded.
- Content identity: `0c41d0ef9e7de4eedeb9dc41f7af6cadcf4c7b88b29dee52d925c897007e427d`; archive SHA256: `a17c753d3f1f635245443b74a0c6265bd6f4a1cd2a9800546980706af48f529b`. All **75 installed production files** match the tested snapshot.
- Final frozen checks: **1,109 passed / 132 optional skipped** in 98.52 seconds, plus **29 Chromium checks passed** in 115.37 seconds. Independent backend and browser review cleared changed-behavior blockers.
- [Drawing navigation](DRAWING_FILE_NAVIGATION.md): Drawings expands a project file picker downward; wide previous/next chevrons above/below the drawing switch files. The live authenticated browser used two existing originals in a temporary metadata-only project and verified file-owned chats, return-to-file session restoration, exact source/revision, mobile target sizes and no overflow or script errors. No new upload or paid request was made; only the test project's metadata was hidden afterward, retaining originals/models.
- [Measurement scope](MEASUREMENT_SCOPE_268.md): the exact colorful-268 question now retains both selected 3 m values. A real isolated production-path replay returned calibration clarification in 3.876-second routing plus 24.007-second advanced answering, without claiming the dimensions were absent or inventing an area. The conflicting implied scales still require a choice or assumption; this is not a validated footprint result.
- Activation waited for the live render to finish, then changed only the agentic code pointer. **All 688 runtime files were byte-identical across the update.** The previous V6 release remains available. Subsequent intentional test metadata and visitor activity may change mutable history; no source/model migration or data rollback occurred.
- The original app retained its process, release, environment, unit, public pins and **all 1,154 recorded runtime hashes**. Its Caddy host block remains byte-for-byte intact. The peer-review policy file hash is unchanged by this update.

Independent GET-only public acceptance also passed trusted HTTPS on both sites, nine exact pinned examples, actual dropdown/arrow visibility, source pinning and mobile fit, with zero script errors or mutation attempts. Its report is under `/tmp/junction-agentic-diagnostics/independent-v9-public/`. The observed 14:30 Helsinki closing time was explicitly confirmed by the user; no policy change was needed.

Live navigation screenshots/results are private under `/tmp/junction-measurement-268/checks/live-drawings/`; frozen-suite logs and isolated measurement replay evidence are under `/tmp/junction-measurement-268/`. The public verification did not run further paid inference or claim general reconstruction fidelity.

## Earlier release checkpoints

- Frozen source: `/tmp/junction-agentic-publish/release-v6/source`; branch `feat/agentic-chat`, Git base `a350690b424a0159649ab38e60b79e62fb85aa09`. This is a worktree snapshot including uncommitted/untracked files, not an archive of Git HEAD.
- Content identity: `0fa281b79164b5955abb0db3ccb8f2a93b3fd6716f344d6544d2c23440472d04`.
- Production archive SHA256: `38a1dc39312e43e8a53c0fcc00bf8b50229f540455544567583e412ba335b8e5`. All 75 installed production files match their frozen hashes, including the user-supplied brand PNG.
- Latest frozen-source checks: **1,012 passed / 126 optional skipped** in 85.91 seconds; **15 focused Chromium checks passed** in 57.13 seconds against matching production bytes. The measurement/render release previously passed 941 backend checks and nine selected Chromium checks. The preceding UI release passed 44 selected Chromium checks in 183.34 seconds. Tests cover the latest projects/sessions, tasks, microphone lifecycle, marks/editor, drawers, source/model/concept, shared UI and parallel render behavior. Offline fixture/intercept tests are not live-provider claims.
- Public checks: trusted TLS; exactly nine manifest-pinned public scenes; no anonymous jobs/history/private uploads; paid requests blocked before provider construction; secure host-only sessions; the existing access code unlocks the separate site.
- Independent final public Chromium review passed all eight drawing examples plus a targeted native IFC rerun: exact source/revision links, orbit, same-revision Concept, visible saved-floor filtering/restoration, and loaded original records. The settled native Evidence drawer is opaque/readable and scrolls. Zero script errors or mutation attempts; nine public examples only, private history denied, original URL/access HTTP 200 and no mobile page overflow. Reports distinguish the initial eight-example pass from the native rerun after fixing a test-only network wait.
- Actual public Gemini checks: an empty project requests sources instead of inheriting another file. A new synthetic original was uploaded/interpreted, then its render completed in one round with **exactly three Hydrogen calls**: creator `DescriptionPatch` (26.061 seconds), reviewer 1 `RenderReview` (6.133 seconds), reviewer 2 `RenderReview` (5.285 seconds). Both reviews ran in the parallel-review phase; reviewer 2 finished first, both final support/satisfaction votes referenced one exact candidate digest. These per-call timings are observed samples, not a general latency benchmark. Upload interpretation and chat routing are separate from those three render calls.
- The real generated IFC reopened with consistent saved/exported revision metadata and unchanged source bytes. Actual Chromium checks verified one canvas, mouse orbit, Concept on the same saved revision, reload, and zero script errors. A source-only question returned the synthetic printed label with one citation, `gate:null`, and supported answer review.
- New-service restart was performed only after its jobs were terminal. **All 476 new runtime-file hashes were identical afterward**, including sources, project/session history, jobs and the accepted model. Original demo release/PID/environment and **all 1,154 pre-existing runtime files** remained unchanged; its original Caddy host block is retained byte-for-byte.

The later live QA adds messages to the synthetic verification session as expected; it does not rewrite its source/model or public examples. The synthetic verification project remains private to code holders and clearly labeled. No original private uploads/chats were copied between sites. The local 8011/8012 preview processes were not restarted or interrupted by this deployment.

The earlier UI follow-up restores the saved-floor selector inside View, opens anonymous native IFC records in the visible Evidence drawer, and preserves native IFC meshes in Concept when no drawing transform exists. Five dedicated browser regressions passed independent review. That UI follow-up retained the Python backend and parallel-render code from the initial live-provider-tested release; no additional paid rendering was needed for those static fixes. All 476 runtime files were also byte-identical across this update. Application pages/modules now require cache revalidation and carry current Last-Modified dates; API responses retain no-store. The previous release is retained for code rollback.

The latest deployed follow-up implements the [colorful-355 measurement/output-limit fixes](COLORFUL_355_RELIABILITY.md): a larger advanced-answer allowance, exact user-value arithmetic with unit conversion, explicit calibration clarification, compact incremental render patches and safe failed-call telemetry. Independent review cleared these changes. An isolated real QA retry with the same configured advanced model correctly requested a choice between conflicting horizontal/vertical calibration, rather than inventing an area. The isolated actual colorful-355 Hydrogen rerender completed in three rounds/nine successful calls, with both final reviewers approving one exact digest. Its IFC contains nonempty room polygons and explicit boundaries/openings on both floors; reopening, revision ancestry, embedded-original preservation and browser orbit/floor/Concept/reload checks passed. This resolves the reported empty-geometry failure in that run without establishing general geometric fidelity. The code-only public update preserved all 476 runtime file hashes and retained the previous release.

Deployment review also fixed portable lineage after an unsupported private candidate: generation now pins the next candidate's revision number/parent to the last published revision before writing IFC bytes. Independent reproduction and regression checks verify bundle, reopened IFC, manifest and real saved ancestry agree. The fixed creator/parallel-review policy and unbounded retry/Stop semantics are unchanged.

Detailed runtime/browser reports and screenshots are local under `/tmp/junction-agentic-publish/public-verification/`; root-only preparation/rollback records remain on the VM. These live synthetic checks establish the deployed flow, not general complex-plan fidelity or engineering accuracy.

## Peer-review access window

The user initially requested 09:30–14:00, confirmed an extension to 14:30, then extended peer review until 22:00 tonight. The current one-time window is **Sunday 15 November 2026, 09:30–22:00 Europe/Helsinki** (07:30–20:00 UTC): code-free shared-workspace access opens at 09:30 inclusive, and the access code is required again at 22:00. Any visitor during the window has the existing code-holder visibility/actions, including saved uploads and chats. The nine pinned examples remain read-only. Existing code-holder cookies remain valid after the window; previously accepted jobs continue under their normal Stop/consensus policy.

**22:00 extension verified (15 November, 11:20 UTC).** The persisted policy and anonymous public HTTPS status both report the original 07:30 UTC opening and new 20:00 UTC closing/next transition. The existing policy evaluator requires the code at exactly 22:00 Helsinki. Both application processes retained their PIDs; no restart or paid inference was needed. Earlier verification timestamps below describe the previous schedules.

The operator-owned `/etc/blueprint-agentic/access-mode` policy is read on requests, so opening and closing need no app restart, cron job or running assistant. The one-time JSON policy has aware opening/closing timestamps. A missing, unreadable or invalid configured file requires the code. `BLUEPRINT_PUBLIC_DEMO=1` stays enabled so source pins, read-only guards and same-origin checks remain active. The code verifier and session secret are retained.

From this checkout, inspect or manage the separate agentic site:

```bash
bash scripts/peer-review-access.sh status
bash scripts/peer-review-access.sh schedule 2026-11-15 09:30 22:00
bash scripts/peer-review-access.sh require-code
```

`require-code` cancels the window and immediately requires the code. `open` is also available as an explicit indefinite override; it cancels the timed window. The wrapper uses the existing dedicated SSH key/known-host file; `BLUEPRINT_DEMO_SSH_KEY` and `BLUEPRINT_DEMO_KNOWN_HOSTS` override their locations. The VM equivalent is `/opt/blueprint-agentic/current/.venv/bin/python /opt/blueprint-agentic/current/deploy/verda-agentic/access_mode.py status` (or `schedule --date 2026-11-15 --start 09:30 --end 22:00`, `require-code`, `open`).

Only the fixed agentic policy file is replaced atomically; the command checks the live API and restores previous bytes if verification fails. Policy-file reads also run as the application user during deployment to check directory traversal/readability. The config directory and policy are root-owned, the policy is readable but not writable by the app, and `application.env` remains root-only. No credentials or runtime bundles are changed by the switch. Browser access refreshes at the server-reported boundaries; API enforcement remains authoritative if a browser is asleep.

**Activated and verified on the public agentic site.** At 05:37 UTC (07:37 Helsinki), fresh public status reported the exact 07:30–12:00 UTC window, code required and the opening as the next transition. Anonymous paid chat returned 401; nine pinned examples and no private jobs were visible. Independent trusted-HTTPS/Chromium review found the code form present and its automatic opening refresh scheduled, with zero script errors or browser mutations. The application Unix user successfully read and evaluated the deployed policy at before/start/inside/end test times; this did not alter the server clock or open public access early.

The code-only release retained all **519 current runtime files**, including user work added since the earlier 476-file checkpoint. All 75 production hashes match the tested archive. The original demo retained its release, process, configuration and all 1,154 recorded runtime hashes. Independent review cleared the policy, unit conversions, atomic operator rollback and timed UI; 132 focused backend/operator checks and five targeted timing-browser checks passed in addition to the integrated suites. The window is enforced by persisted application policy rather than an assistant or cron callback.

## Isolated target

| Resource | New app |
| --- | --- |
| HTTPS hostname | `agentic.95.133.254.90.sslip.io` (DNS verified) |
| Internal listener | `127.0.0.1:8001`, one FastAPI worker |
| System service / Unix user | `blueprint-agentic` |
| Release directory | `/opt/blueprint-agentic/releases/<content_id>` |
| Current pointer | `/opt/blueprint-agentic/current` |
| Locked dependency environment | `/opt/blueprint-agentic/dependencies/.venv` |
| Server configuration | `/etc/blueprint-agentic/application.env`, root-only |
| Persistent runtime | `/srv/blueprint-data/agentic/runtime` |
| Exact public example pins | `/srv/blueprint-data/agentic/public-examples.json` |

This uses the existing CPU VM and mounted data volume, with no additional VM, GPU, top-up, or automatic deletion. Separate host-only cookies and a new session secret isolate the sites' sessions. The existing shared access-code verifier is reused so the familiar access code works; the clear code is neither printed nor embedded in application files. New application data is independent of the existing demo's private uploads, jobs, chats, and revisions.

Only the nine already approved exact public example revisions are seeded. All 436 prepared seed files were hash-verified; all eight drawing-derived IFCs reopened under the new application reader, and the native IFC remained native. No provider call or source/model repair was used to seed or reopen these examples. Their existing negative reviews and fidelity limitations remain applicable.

## Freeze and release

Do not run the original `deploy/verda/install-server.sh` for this target: it replaces the old app's Caddy configuration, service, and current pointer. The historical Git-archive helper omits uncommitted/untracked changes. To release committed changes only, freeze a clean checkout of the selected commit, as with V9 above.

After the side work is complete, use `scripts/verda_agentic_release.py --source-root /tmp/junction-agentic-chat --output CHOSEN_RELEASE_DIRECTORY`. The helper creates `source/`, `application.tar`, and `release.json`. It records the branch/base commit, every source file's hash, content identity, and archive hash. Production includes the actual current `app`, locked requirements, and new deployment templates; the local validation tree separately includes tests/scripts/docs. Secrets, runtime, datasets, caches, and symlinks are excluded. Before/after inventories reject changing input, and `--verify RELEASE_DIRECTORY` checks frozen files against the production archive.

Run required backend and focused browser checks against `source/`, then deploy the exact verified archive, not a later live worktree read. The rendering version must retain a fixed Hydrogen creator followed by two independent reviews launched in parallel against the same reopened candidate; Stop and revision interruption prevent late publication. There is no new total/round/cost cap.

The new system service retains the persistent-mount guard and permits writes only in its own runtime. A reviewed additive Caddy fragment routes only the new hostname to port 8001. Validate the candidate configuration and gracefully reload Caddy while retaining the original host block byte-for-byte. The original app service, release pointer, environment, and runtime are not replaced or restarted.

## Review and preparation evidence

The planner and independent reviewer approved the separate-host/service/runtime design. Six deployment packaging/template tests passed. Independent public/project/session/access tests passed. Review reproduced and fixed a read-only chat authorization error: attempts to render/refine a pinned example now preserve the intended HTTP 409 instead of being wrapped as a provider HTTP 502, without scheduling jobs or changing original evidence. Dedicated regressions cover these denials, allowed pinned-source QA, and anonymous rejection before provider construction.

Server preparation installed the new locked dependencies, independent example seed, and private environment without changing the old service. The original release, process ID, configuration hashes, and runtime hashes are recorded privately under `/root/blueprint-agentic-preparation` for activation verification. This directory contains deployment records and must not be exposed through HTTP.

## Activation acceptance and rollback

Before sharing the new URL, verify trusted public TLS, exact source/archive identity, all nine pinned cached examples, locked paid/private routes, authenticated projects/chats/source QA, immutable-example denials, and the final parallel render behavior. Verify new-service restart persistence using only the new store, and recheck the old public page, process/release/environment and pre-existing data hashes. Distinguish deterministic provider fixtures from any actual live Gemini calls.

A failed new deployment is rolled back by removing only its Caddy fragment and stopping/switching only `blueprint-agentic.service`. Retain its runtime and source files. The existing demo's service, storage, and release remain unchanged. Future updates change only the agentic release pointer after compatibility checks; they do not reseed or restore older data automatically.
