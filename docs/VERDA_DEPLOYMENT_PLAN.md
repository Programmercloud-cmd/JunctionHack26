# Verda hackathon deployment plan

Status: planning proposal for independent review. No cloud resources have been created. The root orchestrator retains reconstruction, QA, validation, refinement and integration ownership; this deployment task owns only `deploy/verda/**`, `scripts/verda_*.*`, this plan and `docs/VERDA_DEPLOYMENT.md`. Any application access/example guard changes must be assigned by root separately. The UI session owns its isolated worktree and additive action router.

## Scope and deployment shape

Deploy the existing single-process Python3.12/FastAPI application on one on-demand x86_64 CPU VM. Serve its existing HTML/JS and browser-side Three.js; Gemini remains the configured provider. Use a persistent Verda block volume for `BLUEPRINT_STORAGE_ROOT`, systemd for the application and Caddy for HTTPS/reverse proxy. No GPU, database, multi-worker Uvicorn, inference worker service, containers/registry, Vercel, Supabase, or new renderer. Existing background jobs and interrupted-job recovery remain authoritative.

One Uvicorn process is an application requirement, not a new throughput cap: the filesystem store and in-process job runner are not multi-process coordinated. Preserve the existing two-thread worker concurrency, per-call limits and job deadlines. Long jobs return job IDs; ordinary polling survives refresh. Graceful service stop marks active work interrupted and retains usable revisions; never auto-resume paid inference on restart.

## Readiness and memory observations

On2026-11-14, active development app processes used roughly140–310MiBRSS each while working with the saved cases. This is observation, not a peak-memory guarantee. Local `.runtime` is221MiB across several duplicated test stores; the virtualenv is747MiB. The native duplex IFC's saved revision is about17MiB, while drawing revisions are about0.3–1.6MiB. The app caches loaded documents in its one process; PNG/PDF decoding, IFC tessellation and concurrent work need headroom.

Recommend the smallest currently advertised general CPU shape,4vCPU/16GiB (`CPU-TURIN.4V.16G` or `CPU.4V.16G`), with40GiBOS and20GiBdata initially. This sizing is a design choice, not an upload restriction. Current RAM observations support this comfortably; confirm live availability, OS minimum volume size and a representative cold-import/two-job memory checkpoint before launch. Avoid importing all historical runtime/diagnostic files into the deployment. Disk exhaustion remains a recoverable operational risk; retain existing upload bounds and monitor volume usage rather than silently truncating valid sources.

## Cost and lifespan

The user has€200 redeemed credits and authorized availability through Sunday2026-11-15. Use pay-as-you-go, not spot or a long-term contract, and do not enable top-ups. Do not automate deletion during the event.

Official public pricing inspected2026-11-14 currently lists4vCPU/16GiB at€0.04296/hour and NVMe at€0.179/GiB-month. A provisional36-hour estimate for40GiBOS+20GiBdata is:

| Resource | Provisional36h estimate |
|---|---:|
| CPU |€1.54656 |
|60GiBNVMe, using730h/month approximation |€0.52964 |
| Total |€2.08 |

This estimate excludes Gemini API consumption, which is billed by the Gemini account rather than Verda credits. It is not a confirmed account/location quote. API pricing recently added location-specific prices, so authenticated catalog/location availability and `verda cost estimate` must be checked before provisioning. The current CLI cost command does not expose a location flag; inspect the instance type's location-specific prices directly too. Verify actual credit balance and existing project burn; do not infer that all€200 remains available. Record billing currency and exact resource IDs/prices in the private deployment ledger.

At15:57UTC onSaturday, Sunday23:59Europe/Helsinki is about30hours away.36hours includes setup/judging buffer; it is not an automatic shutdown deadline. After judging, export storage and manually tear down. Stopping/deleting the VM does not remove separately billed volumes. The teardown runbook must list OS and data volumes separately and require explicit later deletion after export.

Sources: [current EUR pricing](https://verda.com/pricing?currency=eur), [billing rules](https://docs.verda.com/welcome-to-verda/pricing-and-billing/), [API location pricing](https://api.verda.com/v1/docs), [CLI cost/status](https://docs.verda.com/cli/cost-and-status/).

## Authentication and provisioning gates

Official CLIv1.10.0 was installed locally at `/home/jcb/.local/bin/verda` using the inspected official installer and releaseSHA256 verification. No shell-profile edits and no application dependencies changed. No credentials were present; the read-only CPU catalog command returned the expected `AUTH_ERROR`.

The user must create Cloud API credentials in Console→Credentials and run `/home/jcb/.local/bin/verda auth login` in their local terminal. This is a necessary secure authentication handoff, not an approval request. Never ask for a secret in chat, print credential files, use secret CLI flags, enable `--debug`, or commit credentials. Once the user confirms login, use normal CLI credential resolution for read-only balance/catalog/availability/image/SSH-key queries. Never copy Cloud API credentials to the app server; only local provisioning needs them.

Before creating resources, independent review must clear this plan, the service/proxy/storage configuration, and the access/example contract. Root communicates the actual cost estimate and selected shape. Provision via CLI with an explicit CPU type, location, plainUbuntu24.04 image, on-demand contract and reviewed volume sizes. Use a dedicated SSH key, save cloud resource IDs privately, and deploy a local release archive without pushing GitHub.

Sources: [CLI installation](https://docs.verda.com/cli/), [CLI authentication](https://docs.verda.com/cli/getting-started/), [Cloud API credentials](https://docs.verda.com/welcome-to-verda/api-credentials/), [instance management](https://docs.verda.com/cli/instances/), [persistent volumes](https://docs.verda.com/cli/storage/).

## Public access and shared examples — root/UI contract needed

There is currently no user authentication or per-visitor filesystem isolation. `GET /api/buildings` lists every saved building and questions/refinements can mutate persisted state. Publishing the current app without a control would expose uploads and paid Gemini operations to everyone. The user chose open cached examples with code-gated paid actions. Root owns the narrow application access guard; Caddy will not put a whole-site password in front of examples. The access code gates Gemini actions, visitor uploads and private upload/history retrieval. This is a design choice to bound paid actions and uploaded-data exposure, not a Verda requirement. Code holders share visibility of uploaded files/history; do not claim private visitor workspaces. Anonymous requests see only the nine manifest-pinned prepared examples and their public source/model evidence. Public browsing must never expose the global building/job/conversation catalog.

Shared prepared examples must be immutable at application mutation boundaries, regardless of frontend control state. Root should assign a narrow guard for protected IDs on source append, extraction, reconstruction, refinement and synchronous scene-generation paths, including duplicate/multipart uploads whose initial content matches an example. New visitor uploads remain supported. Code-authenticated source-only QA can inspect immutable examples pinned to the prepared manifest revision, but must not alter their interpretations/geometry. New QA logs remain private to code holders; unrelated visitor jobs/conversations are not public example metadata. The agreed scope has no cloning: prepared-example geometry/source mutation is rejected with a clear read-only error. A supported question on a prepared example remains enabled after code entry. A question does not silently become a mutation.

The UI needs a small “prepared example/read-only model” indication and accurate blocked-edit text, while cached model opening, navigation, citations, export and QA remain enabled. This agent will not edit `app/**`. Proxy controls must not bypass application validation, rewrite question sources or proxy provider keys into browser code.

Domain: the user has no domain and authorized a free IP-derived `sslip.io` or `nip.io` hostname. Use the allocated publicIP hostname with Caddy certificate automation, which needs public80/443reachability. This depends on an external publicDNS service; verify DNS, valid publicTLS and direct browser access before sharing the URL. No domain purchase or local tunnel. If the selected service fails, verify the alternative rather than publishing an insecure URL. Restrict SSH to the operator where practical; FastAPI listens only on127.0.0.1. Server secrets belong in a root-readable service environment file outside the release/static tree, passed to the application process only.

## Nine prepared examples

Reuse the existing Saved buildings selector. There are at least nine distinct usable saved sources across existing stores:3181,34,11397,1794,church22921604,unseen10262,14661814SVG,KITinstitutePDF and native duplexIFC.1732 is another candidate but currently lacks a saved review file. Root must choose final pinned revisions after ongoing fixes and review; a model's presence or status string is not proof of fidelity.

Prepare a manifest with example ID/title, exact original hash, source store/building/revision, kind, saved review status and known limitations. Copy only selected immutable bundle revisions/resources and required provenance files, preserving IDs, original bytes, source interpretations, transforms, user values and assumptions. Keep historical candidate diagnostics, private provider responses, credentials, dataset ground-truth questions and unrelated uploads out of the release. Do not invoke extraction while packaging. Verify hashes and reopen each generatedIFC locally; nativeIFC remains native and drawing-derivedIFC remains derived. Do not relabel missing/unreviewed reviews as reviewed. If fewer than nine suitable reviewed models remain, report the exact gap and do the smallest necessary source/IFC review rather than unnecessary extraction.

Package immutable examples separately from writable application storage. Deployment integration must protect their model revisions while allowing new uploads and source-grounded QA. Seed installation is idempotent, refuses conflicting destination IDs/revisions, and never overwrites visitor state. Application restart must not re-import/re-infer examples. Maintain an offline local export before upload.

## Implementation ownership and sequence

1. Deployment agent: finalize this plan, inspect official CLI, read-only account/catalog/cost checks after authentication, prepare service/proxy templates, source archive/seed/export helpers and teardown documentation in owned paths.
2. Root plus independent reviewer: freeze public-access/example mutation contract and select exact reviewed example revisions. Assign application guards separately; UI session accommodates protected-example status without editing core reliability files.
3. Independent reviewer: review deployment scripts/configuration before provisioning, including one-process semantics, mounted-volume fail-closed behavior, secret handling, no top-up/delete automation, no public raw diagnostics, and accurate example status.
4. Root/deployment agent: provision within verified credits, install OS dependencies+locked Python dependencies, mount data by stable identifier, transfer a clean application archive and verified seeds, install server-only Gemini environment, configure HTTPS and service.
5. Independent reviewer directly uses the public browser; root validates live provider flows and restart/storage behavior. Make focused commits, no push.

## Acceptance ledger

- Public HTTPS opens independently oflocalhost with the chosen access flow; no browser/provider secret exposure.
- Nine pinned examples load cached model geometry with no extraction call. Orbit, floor controls, answer highlights, source clicks/overlays and independent assumptions work; protect shared model revisions against direct API mutation.
- Supported original-source QA and unsupported actual-height refusal pass live with Gemini and citations; no generated geometry promoted to evidence.
- Fresh upload/extraction/optional geometry works through background jobs. Refresh reconnects. Failed/stopped/interrupted jobs retain usable results.
- Application restart preserves source bytes, saved interpretation/current revision, IFC/provenance, assumptions and cached reopening without unnecessary provider calls. Confirm persistent filesystem mount survives service restart and VM reboot where safe.
- Record memory/disk use, latency/token metadata, true review status and fidelity gaps. Distinguish existing cached artifacts, fresh live checks and deterministic tests.
- Export locally before teardown; document manual VM shutdown/delete and separately billed OS/data volume deletion after judging. Nothing deletes automatically during the event.

## Rollback and snapshot verification

Retain the prior application release and an offline source/data snapshot before switching the deployed release. Drain or explicitly stop active jobs and stop the single application process before taking a consistent filesystem snapshot; do not snapshot a changing CURRENT pointer as if it were a transactional backup. Caddy may serve a clear maintenance response while the application is stopped. Verify snapshot hashes and a private restore/reopen test with inference disabled before relying on it.

A normal code rollback changes only the release symlink and restarts against the existing persistent data, after compatibility checks. It must not automatically restore an older data snapshot. A data restore can discard uploads/revisions created after the snapshot, so it requires a separate intentional recovery decision and an export of current state first. Keep both old and new data copies; never overwrite post-snapshot visitor state as part of a routine deployment rollback. Verify the prior release remains available and record exactly which release/data pair was tested.

## Provisioning compatibility update

The reviewed 40-GiB OS + 20-GiB data configuration was rejected by Verda as storage too small. Its CLI wizard and Console default OS disks to 50 GiB; 50+20 was also rejected. The official [CPU tutorial](https://docs.verda.com/containers/tutorials/guide-vector-database/) demonstrates a 50-GiB NVMe data volume. Use 50+50 as the next controlled configuration, not as a claimed proven minimum. Authenticated quote: $0.0754/hour, $2.7144 for 36 hours, against the confirmed €200 credit balance. No top-ups. CLI v1.10.0 rejects the newer CPU-TURIN prefix locally, so the same CPU configuration uses the official API directly. Inventory is checked after each rejection to prevent duplicates. FIN-03 stock replaced unavailable FIN-01; compute remains $0.048/hour.
