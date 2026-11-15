# Separate agentic public deployment — 2026-11-15

Status: **live at https://agentic.95.133.254.90.sslip.io/**. The final creator-plus-two-parallel-reviewers implementation, project/session UI, branding and deployment fixes are included. Trusted public HTTPS, access controls, live inference, actual generated-model browsing and restart persistence passed.

The existing `blueprint-qa-isolated` demo at `https://95.133.254.90.sslip.io/` remains running. The agentic worktree is `feat/agentic-chat` at `/tmp/junction-agentic-chat`, including its uncommitted project/session, marks, branding, and rendering changes. No commit or push is required to publish a verified content-addressed snapshot.

## Published release and results

- Frozen source: `/tmp/junction-agentic-publish/release-v5/source`; branch `feat/agentic-chat`, Git base `46099464d3b0dc1405fae3f1d33398d0475a4962`. This is a worktree snapshot including uncommitted/untracked files, not an archive of Git HEAD.
- Content identity: `0ae8f14448f4aa2aa962fba0fab92f72bc6175b5802541fc4bbfe8c47fab316a`.
- Production archive SHA256: `1cb51b39f8767a30841f147de552a6e4ac7873c3f087cfe4b8d23ed9d29c0224`. All 73 installed production files match their frozen hashes, including the user-supplied brand PNG.
- Latest frozen-source checks: **941 passed / 121 optional skipped** in 86.04 seconds; **nine focused Chromium checks passed** in 39.04 seconds against matching production bytes. The preceding UI release passed 44 selected Chromium checks in 183.34 seconds. Tests cover the latest projects/sessions, tasks, microphone lifecycle, marks/editor, drawers, source/model/concept, shared UI and parallel render behavior. Offline fixture/intercept tests are not live-provider claims.
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

Do not run the original `deploy/verda/install-server.sh` for this target: it replaces the old app's Caddy configuration, service, and current pointer. Do not package `HEAD` with the historical Git-archive helper: the agentic changes are uncommitted/untracked and would be omitted.

After the side work is complete, use `scripts/verda_agentic_release.py --source-root /tmp/junction-agentic-chat --output CHOSEN_RELEASE_DIRECTORY`. The helper creates `source/`, `application.tar`, and `release.json`. It records the branch/base commit, every source file's hash, content identity, and archive hash. Production includes the actual current `app`, locked requirements, and new deployment templates; the local validation tree separately includes tests/scripts/docs. Secrets, runtime, datasets, caches, and symlinks are excluded. Before/after inventories reject changing input, and `--verify RELEASE_DIRECTORY` checks frozen files against the production archive.

Run required backend and focused browser checks against `source/`, then deploy the exact verified archive, not a later live worktree read. The rendering version must retain a fixed Hydrogen creator followed by two independent reviews launched in parallel against the same reopened candidate; Stop and revision interruption prevent late publication. There is no new total/round/cost cap.

The new system service retains the persistent-mount guard and permits writes only in its own runtime. A reviewed additive Caddy fragment routes only the new hostname to port 8001. Validate the candidate configuration and gracefully reload Caddy while retaining the original host block byte-for-byte. The original app service, release pointer, environment, and runtime are not replaced or restarted.

## Review and preparation evidence

The planner and independent reviewer approved the separate-host/service/runtime design. Six deployment packaging/template tests passed. Independent public/project/session/access tests passed. Review reproduced and fixed a read-only chat authorization error: attempts to render/refine a pinned example now preserve the intended HTTP 409 instead of being wrapped as a provider HTTP 502, without scheduling jobs or changing original evidence. Dedicated regressions cover these denials, allowed pinned-source QA, and anonymous rejection before provider construction.

Server preparation installed the new locked dependencies, independent example seed, and private environment without changing the old service. The original release, process ID, configuration hashes, and runtime hashes are recorded privately under `/root/blueprint-agentic-preparation` for activation verification. This directory contains deployment records and must not be exposed through HTTP.

## Activation acceptance and rollback

Before sharing the new URL, verify trusted public TLS, exact source/archive identity, all nine pinned cached examples, locked paid/private routes, authenticated projects/chats/source QA, immutable-example denials, and the final parallel render behavior. Verify new-service restart persistence using only the new store, and recheck the old public page, process/release/environment and pre-existing data hashes. Distinguish deterministic provider fixtures from any actual live Gemini calls.

A failed new deployment is rolled back by removing only its Caddy fragment and stopping/switching only `blueprint-agentic.service`. Retain its runtime and source files. The existing demo's service, storage, and release remain unchanged. Future updates change only the agentic release pointer after compatibility checks; they do not reseed or restore older data automatically.
