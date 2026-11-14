# Public demo access plan

Status: independently approved after restoring authenticated QA on pinned examples. The access module and 54 focused tests are implemented; root route/UI integration and independent browser verification remain required. Work on `blueprint-qa-isolated`; no push. This plan covers public browsing of nine curated examples and shared-code access to paid/private work. Deployment is separately owned. No database, per-user accounts, new inference limits or architectural subsystem.

## Confirmed behavior and risks

`app/main.py` currently exposes every building, current scene, original source, conversation and job without access checks. Upload, extraction, reconstruction, refinement and both QA endpoints can invoke providers or mutate stored state. The newly integrated chat/action routes must receive the same protection, including paths that invoke tools indirectly.

`BuildingStore` has no fork/clone operation. `add()` uses original-byte SHA256 as the building ID; reuploading a curated source selects its shared building rather than creating a private copy. `add_many()` may append sources and `_alias()` can update shared source metadata. Merely blocking example reconstruction URLs is insufficient. `prepare()` creates another revision of the same building, not a workspace. `commit()` rewrites scene building/revision URLs; blindly copying a directory or exporting/reimporting its derived IFC is not a proven independent copy operation.

Existing QA appends operational job/conversation records and answers from a document snapshot; it does not commit source, interpretation, geometry or user-input revisions. Authenticated QA on curated examples is therefore allowed without a workspace copy. These conversations/jobs remain private to all shared-code holders. Public unversioned scene/page/export endpoints currently follow CURRENT. A building-only allowlist would therefore expose a later unreviewed revision. Building detail also includes jobs; conversation/job responses can contain private prompts, inputs and diagnostics. Resource storage is shared across buildings, so knowing a source hash must never grant public access.

## Smallest server control

Add `app/public_access.py` plus dedicated tests; root integrates its helpers into `app/main.py` and the new chat routes. Keep local development unchanged when explicit public-demo mode is disabled. In public mode, missing/invalid access configuration or manifest fails closed at startup, not open to all data.

Suggested configuration:

- `BLUEPRINT_PUBLIC_DEMO=1` explicitly enables the controls.
- `BLUEPRINT_PUBLIC_EXAMPLES_FILE` points to a deployment-local JSON manifest of curated `{building_id, revision_id, title}` records. The selected nine entries are content choices, not a new general application limit. Validate unique IDs, exact existing immutable revisions and their sources when opening the server. Do not scan all storage and auto-publish it.
- `BLUEPRINT_DEMO_ACCESS_CODE_HASH` contains a salted stdlib scrypt verifier produced locally from hidden terminal input. Never request the code in chat, put it in command arguments, commit it, or include it in logs. A small local administrative setup command can print only a deployment-file location, not the credential.
- `BLUEPRINT_DEMO_SESSION_SECRET` is a random server secret supplied through the protected deployment environment. Rotate it to invalidate shared-code sessions. Deployment owns secure provisioning and HTTPS.

Use a signed host-only session cookie (`HttpOnly`, `Secure` in public HTTPS mode, `SameSite=Strict`, `Path=/`, no Domain). The browser-session cookie avoids introducing an arbitrary session-duration cap for this hackathon. The signature binds the editor scope and a random nonce; include verifier version/digest in signing context so changing the access code invalidates existing sessions. Do not store the code itself in cookies, localStorage or JavaScript. Shared-code holders intentionally share the privileged workspace; this is not per-user isolation.

Suggested module interfaces, subject to root approval:

- `PublicAccess.from_environment()` validates mode/configuration and loads exact example IDs/revisions.
- `access.is_editor(request)` verifies the cookie without reading request-body secrets into logs.
- `access.require_editor(request)` rejects unauthorized paid/mutating calls before body processing/provider construction where possible.
- `access.document(store, request, building_id, revision_id=None)` resolves a public example to its pinned revision, rejects other revision IDs and private IDs uniformly, and permits code holders to read private work. Curated example reads remain pinned for both audiences.
- `access.require_editable(request, building_id)` rejects source/model/interpretation mutations of shared examples even for editors. It does not prohibit code-gated QA or stopping its operational jobs. `access.question_document(...)` forces exact manifest-revision snapshots for example QA and rejects a conflicting supplied revision; private work retains existing revision checks.
- `access.public_buildings(store)` returns only curated pinned public descriptors, without jobs/history/conversation. Root keeps code-holder private lists separate or filters appropriately for the chosen view.
- A default-deny API middleware guards every non-read request and rejects public reads outside the exact listed routes. Root invokes editable/document helpers for identity-bearing requests after validated parsing. Neither UI-hidden buttons nor possession of an ID authorize an operation.

Add `GET /api/access` returning only `{public_demo, can_work}`; `POST /api/access/unlock` accepts the code in a JSON body and returns an empty success with cookie; `POST /api/access/lock` removes the cookie. Unlock necessarily accepts a missing session; it invokes no inference. Do not reveal whether a private building/job exists in unauthorized responses. Restrict browser state-changing requests to same-origin using Origin/Fetch-Metadata checks in addition to SameSite; keep explicitly configured local test clients working without weakening deployed cross-origin rejection. No permissive CORS.

## Route policy and pinned content

| Existing/new surface | Public visitor | Shared-code holder |
| --- | --- | --- |
| `/`, `/chat`, `/static/*`, minimal health/access status | Public application assets/status | Same |
| `GET /api/buildings` | Nine manifest-selected pinned examples only | Private work plus curated entries, clearly distinguished |
| Example building detail / assumptions | Pinned approved revision; no jobs, history or conversation | Same public snapshot for curated ID; private workspace detail permitted |
| Document page / scene / `model.ifc` | Resolve allowlisted building to pinned revision | Same pinned example or selected private workspace |
| Revision page / native IFC evidence | Exact manifest building+revision pair only | Other revisions only for private work |
| Original-source download / arbitrary source resource | Not public | Only validated membership in accessible private workspace or explicitly authenticated example source access |
| Conversation and QA job detail | Not public, including examples | Shared privileged history, including example QA; never included in anonymous building responses |
| Internal diagnostics/history artifact paths | Not public | No new raw diagnostic-serving endpoint |
| Upload/source append, extraction, reconstruction, legacy POST scene, refinement | Requires code; no provider call before authorization | Private work only; shared example source/model revisions remain immutable |
| Both QA routes and QA chat actions | Requires code | Allowed on exact pinned examples and private work; only operational history/jobs are appended |
| Chat/actions that modify source/model/inputs | Requires code | Same immutable-model guard as direct mutation endpoints, applied before action execution |
| Stop QA job | Requires code | Allowed for private or example QA jobs; never grants reconstruction/mutation authority |
| Unrecognized API path/method | Deny | Normal routed behavior after editor check; future paid APIs inherit protection |

For example export, the existing derived IFC embeds original pages, source files, assumptions and user-value provenance. Manifest curation therefore approves those embedded artifacts too; hiding a raw-source URL does not make data inside an approved export private. Inspect selected artifacts for unrelated uploads, user messages or private filenames before listing them. Do not redact geometry provenance or silently strip original-source evidence to claim privacy.

Any new public route needs an explicit policy entry. OpenAPI/docs may remain editor-only; they are not needed for public browsing. Public health should not include storage contents, secrets or exception values. All sensitive responses and access responses use no-store. No uploaded storage path is mounted as static content.

## Immutable examples without workspace copies

Define immutability narrowly: the curated example's sources, interpretation, supplied geometric values and model revisions cannot change through the demo. Authenticated users may ask new questions against its exact pinned originals. The existing question flow appends private operational conversation and job records; those are allowed and visible only to shared-code holders. A QA answer or clarification must never trigger refinement or persist user-provided dimensions as source facts. Model-changing chat actions call the same immutable guard as the direct API.

No clone operation is needed for this milestone. Geometry/source edit attempts return a precise `409`: “This shared example model is read-only. Upload another blueprint to edit.” Do not suggest a nonexistent copy action or block paid QA behind a copy requirement. Shared-code holders intentionally share these conversations and private uploads; disclose that there is no account isolation.

Guard all uploaded multipart parts before invoking `add_many`, `_resource`, `_alias` or extraction. A curated source at any position may select or alias the existing resource; a multipart group beginning with it can otherwise append private sources to the public bundle. Code holders may select the existing read-only example or receive the explicit immutable result, but the request cannot mutate shared source metadata, trigger extraction, or create a misleading editable duplicate. A distinct private original remains uploadable.

Pin example QA at the snapshot boundary, not only by overwriting the request's revision string: `JobRunner.question()` currently loads CURRENT and rejects mismatches, and `_question()` rechecks highlights against CURRENT. Root must pass/resolve the exact manifest revision for both source inference and displayed model/highlight comparison. The synchronous `/api/ask` and new chat dispatch use the same pinned document helper. Source citations and answer revision IDs continue pointing to the original pinned revision even if CURRENT differs. A client-supplied conflicting revision must fail rather than select hidden data. Read-only source QA remains operationally separate from immutable model edits.

The existing store lacks a safe clone primitive: new independent bundle identity, metadata creation and portable IFC lineage require additional testing. Defer all copy UI/API/store work. Keep source hashes/object IDs/coordinates/assumptions untouched for public examples and existing private work.

## Ownership and integration

- Backend implementer: `app/public_access.py`, `tests/test_public_access.py`, and this plan only after review. No edits to `main.py`, jobs, providers or bundles until explicitly assigned.
- Root: minimal route registration/pinned-read/immutable guards in `main.py`, new chat/actions integration, UI access controls and public/private presentation. Root owns the minimal jobs snapshot/highlight pinning needed for authenticated example QA; copying remains deferred.
- Deployment agent: Verda service/HTTPS/env provisioning and curated artifact transfer; coordinate exact environment/manifest names before writing commands. No credentials in repository or chat.
- Independent reviewer: read-only review of server enforcement and direct browser checks, including logged-out navigation and code-holder flows. Review cannot rely on UI hiding alone.

## Acceptance before enabling public access

1. Anonymous browser lists only manifest examples; orbit/floor/overlay/object evidence/export work against pinned revisions. New private uploads never appear in public list, detail, guessed page/source/job/conversation URLs, exported example data or browser cache.
2. Test every existing paid/mutating path plus new chat/action paths without credentials. Provider fakes record zero calls and filesystem snapshots remain unchanged. Test alternate methods, encoded paths, direct API requests and a new unclassified route against default-deny policy.
3. Public reads cannot select arbitrary revisions. Changing an example's CURRENT in a temporary fixture does not change public scene/pages/export. Building detail does not leak `jobs`; job IDs remain inaccessible anonymously.
4. Valid/invalid code and signed-cookie tampering tests; no credential/request-body logging; cookie flags, same-origin enforcement and logout tested. Code rotation invalidates sessions. Public mode missing verifier/secret/manifest fails startup safely. Local mode regression tests pass.
5. Code-holder upload/QA/refinement works on a private fixture with source citations and refusal behavior intact. A curated example source/model cannot be altered via direct endpoint, legacy POST scene, mutating chat action, identical upload, grouped upload in any multipart position, source append or stop-job indirection. Authenticated fresh QA and follow-ups on that example must succeed against pinned originals, appending only private operational records.
6. Example QA preserves immutable revision/source/IFC hashes, survives restart as private operational history, and never promotes conversation claims into source evidence. Force a different CURRENT in a temporary fixture: code-gated QA still inspects the manifest revision, highlights its saved model and cites its original pages. Stopping a QA job is permitted; reopening the public example exposes none of its conversation/job data. No copy button is shown.
7. Independent browser reviewer verifies public example browsing, access entry, private work, source evidence, refusal and immutable example behavior. Root records actual anonymous versus privileged results before deployment; passing mocked tests alone is not deployment verification.
