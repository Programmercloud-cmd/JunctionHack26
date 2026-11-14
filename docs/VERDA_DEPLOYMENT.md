# Verda deployment runbook

The initial reviewed release is publicly deployed; final browser/live workflow acceptance remains in progress. Read [VERDA_DEPLOYMENT_PLAN.md](VERDA_DEPLOYMENT_PLAN.md) and [PUBLIC_DEMO_PLAN.md](PUBLIC_DEMO_PLAN.md). Use one CPU VM, one FastAPI process, a separate persistent NVMe data volume and Caddy HTTPS. Gemini credentials remain server-side. Cloud credentials stay on the operator's machine.

## Confirmed preflight

Official Verda CLI v1.10.0 is installed at `/home/jcb/.local/bin/verda`; its release archive's SHA256 was verified. Authenticated preflight confirmed €200 of redeemed credits and no existing instance burn. The deployed server is `CPU-TURIN.4V.16G` in FIN-03, running plain Ubuntu 24.04 (`24.04.base`), with 4 vCPU, 16 GiB RAM, a 50-GiB OS volume and a separate 50-GiB persistent data volume.

Actual resource records report EUR billing: €0.043/hour for compute and €0.012261575/hour for each volume. The combined cost is approximately **€0.06752315/hour, or €2.43084 for 36 hours**. The earlier USD catalog estimate for this same 50+50-GiB configuration was $0.0754/hour ($2.7144/36 hours); use the actual EUR resource records when reporting this deployment. Gemini API charges are separate. No paid top-up was enabled.

Earlier 40+20-GiB and 50+20-GiB configurations were rejected as storage too small and created no resources. The final 50+50-GiB configuration follows the official OS default and demonstrated CPU data-volume size and succeeded. These outcomes establish compatibility of the deployed sizes, not an exact provider minimum. FIN-01 lost CPU stock before provisioning, so the same CPU shape was deployed in FIN-03. Recheck account balance, prices and stock before creating any additional resource; no additional server is needed for this demo.

The CLI's SDK omits the new API `location_prices` field. Read the officialAPI directly if needed, loading local credentials only in process memory; never use debug logs or print tokens/credential files. Primary references: [CLI](https://docs.verda.com/cli/), [instance docs](https://docs.verda.com/cli/instances/), [API](https://api.verda.com/v1/docs), [pricing](https://verda.com/pricing?currency=eur).

## Freeze release and examples locally

After root integrates and reviews application/UI/access changes, make focused commits without pushing. Archive the exact integrated commit:

```bash
.venv/bin/python scripts/verda_release.py --ref HEAD --output /tmp/junction-verda/release-COMMIT
```

The archive includes only committed `app`, locked requirements and deployment templates. It deliberately excludes `.env*`, runtime/uploads, datasets, provider diagnostics and Git metadata. The releaseJSON records the commit and archive hash. A working-tree change is not in this archive; confirm the intended integrated commit before deploying.

Create a private selectionJSON with nine explicit `{root,building_id,revision_id,title,known_limitations}` entries. Use saved immutable revisions, not CURRENT at transfer time. Select the final reviewed SVG/KIT revisions from `.runtime/verda-example-review`, and preserve negative reviews/known gaps. NativeIFC is supplied evidence, not a Gemini-reviewed reconstruction. Then:

```bash
.venv/bin/python scripts/verda_prepare_examples.py --selection /tmp/junction-verda/selection.json --output /tmp/junction-verda/prepared-examples
```

This copies original bytes/pages, all ancestors of each selected revision, used source resources, interpretations, IFCs, identities, frames, user values and review records. It excludes jobs, conversations, failed candidates and private provider diagnostics. It validates hashes and reopens each drawing-derivedIFC without provider calls. It writes a public pinned manifest and a separate review ledger; it never changes review outcomes. Inspect the nine examples and ledger before publication. A failed preparation leaves only a private incomplete staging folder; choose a new output path after diagnosis, never deploy it.

## Private service configuration

Generate a strong random demo code and session secret locally using the application's verifier helper. This copies only allowlisted Gemini/configuration values, not the whole development environment:

```bash
.venv/bin/python scripts/verda_prepare_secrets.py --source-env .env.local --output /tmp/junction-verda/private-deployment
```

The directory is0700 and files0600. It prints paths only. Read `demo-access-code.txt` locally when needed; never paste it into chat. Transfer only `application.env` overSSH to `/etc/blueprint/application.env` owned root:root0600. Keep the clear demo-code file on the operator's machine. The Verda Cloud API credential file must not be copied to the VM.

Public examples require no code. GeminiQA, uploads and private work require the demo code. Code holders share the privileged workspace; there is no per-user data isolation. Prepared source/model revisions remain read-only, including for code holders. ExampleQA uses the exact manifest revision and keeps its operational history private. The service refuses to start if public-mode configuration/manifest validation fails.

## Provision after reviewed configuration and cost disclosure

Use a dedicated SSH key. Save its private half outside the repository with0600permissions; upload only its public half with `verda ssh-key add`. Record the returned keyID privately. Recheck the CPU's stock. The reviewed shape is:

```text
verda vm create --agent --kind cpu --instance-type CPU-TURIN.4V.16G
  --location FIN-03 --os 24.04.base --contract pay_as_go --pricing FIXED_PRICE
  --os-volume-size 50 --os-volume-name blueprint-demo-os
  --storage-size 50 --storage-name blueprint-demo-data --storage-type NVMe
  --hostname blueprint-junction-demo --ssh-key REVIEWED_KEY_ID --wait
```

CLI v1.10.0 incorrectly rejects `CPU-TURIN` with `--kind cpu`. Do not mislabel it as GPU. Use the official `POST /v1/instances` API with the same configuration, `contract: PAY_AS_YOU_GO`, `is_spot: false`, `image: 24.04.base`, `os_volume: {name: blueprint-demo-os, size: 50}`, and one `NVMe` data volume of 50 GiB. Load credentials and OAuth tokens only in memory. Save the returned instance ID immediately; after a timeout or rejection, inspect instance/volume inventory before any retry. The first CLI rejection and 40+20 and 50+20-GiB API rejections created no resources.

Run the creation request only after root communicates the actual reviewed quote and independent implementation review clears provisioning. Do not request spot, long-term contracts or auto-topup. Save the VMID, publicIP, OSvolumeID and datavolumeID in the private deployment ledger. Credentials never belong in command arguments. Use CLI/API directly; MCP is unnecessary.

Inspect the new VM's block devices and cloud volume identity before formatting. Format only the freshly created, positively identified empty data volume; refuse an existing filesystem or ambiguous disk. Mount it at `/srv/blueprint-data` by stable filesystemUUID through `/etc/fstab`. Do not format the OSdisk. Keep the app stopped during initialseed installation. The service has both `RequiresMountsFor` and a mountpoint check, so a missing persistent mount cannot silently send uploads to the OSdisk.

Transfer the application archive, selected seed, installer helpers and private environment overSSH/SCP. Verify local/remoteSHA256before extraction. Extract the release under `/opt/blueprint/releases/COMMIT`. Install the seed with `scripts/verda_install_seed.py --seed SEED_DIRECTORY --data /srv/blueprint-data`. It checks every file before copying and refuses all destination conflicts; repeated identical installation leaves existing files untouched. Never use `rsync --delete` on live application storage.

The free hostname is `PUBLIC_IP.sslip.io` (or the correspondingnip.iohostname if verified). This is an external publicDNS dependency, authorized because the user has no domain. Verify the name resolves to the VM. Permit inbound80/443; restrictSSH to the operator where practical. FastAPI must bind only127.0.0.1:8000. No other app/admin port is public.

Run the reviewed `deploy/verda/install-server.sh /opt/blueprint/releases/COMMIT HOSTNAME` as root. It installs locked dependencies and officialCaddy, configures the service, stops the previous app before switching release, and starts one worker. The installer does not create/format volumes, create cloud resources, delete data or install teardown timers. Caddy obtains and renews publicTLS; verify certificate and browser behavior before sharing theURL.

## Updating application code while retaining live data

Package only the exact integrated commit approved by the orchestrator with `scripts/verda_release.py`. Transfer its application archive, verify its SHA256 on the VM, and extract it to a new `/opt/blueprint/releases/COMMIT` directory. Keep the existing private environment, pinned example manifest and entire `/srv/blueprint-data` volume. **Do not reseed or replace runtime files during a code update.**

Coordinate the brief restart with the orchestrator. Confirm there are no active jobs before stopping the service; do not interrupt live verification or visitors' paid processing. Record hashes of the current persistent files, including private uploads, original sources, revisions, CURRENT pointers and completed job records. Run the reviewed installer against the new release, then verify the previous release remains available for rollback, all recorded data hashes remain unchanged, private upload/current-revision/job counts agree, and no inference job was implicitly created. Repeat public HTTPS, access controls and the affected browser flow. A code rollback changes only the release symlink and retains current storage.

## Verification and restart

An independent reviewer must directly use the publicHTTPSURL, both logged out and with the code. Verify all nine cached examples, orbit/floor/overlay controls, object-source links, assumptions and export. Anonymous paid/private calls must fail before provider use. Shared examples must resist direct API mutation, grouped/identical uploads and mutating chat actions. Public listings and example details must not expose private jobs/history/uploads.

Run live Gemini supportedQA and a genuinely unsupported actual-height question; verify citations and refusal despite visible extrusions. Upload a fresh nonsensitive blueprint, watch background stages, refresh and recover the job/result. Keep all source/geometry fidelity gaps visible; successfulAPI responses are not accuracy evidence.

Record current revision/source/IFC hashes, stop or drain jobs and restart `blueprint-qa`. Verify the same sources/current revisions and cached models load with no unnecessary inference. A restart may mark unfinished jobs interrupted; usable revisions must remain. The volume must still be mounted. Inspect memory/disk with `systemctl show blueprint-qa -p MemoryCurrent` and `df -h /srv/blueprint-data`, without printing service environment. A VMreboot test is useful after the app test if no active demo is being served.

## Export, rollback and teardown after judging

Before a consistent data export, drain or explicitly stop jobs and stop the application; do not copy a movingCURRENTpointer as a verified snapshot. Archive `/srv/blueprint-data` to a separate path with restricted permissions, transfer it locally, verify itsSHA256and test a private restore/reopen with inference disabled. Restart the app when export finishes if the event is ongoing. There is no automatic deletion or shutdown timer.

Keep the previous release path recorded in `/opt/blueprint/previous-release.txt`. Code rollback stops the app, switches the release symlink to the verified previous commit, checks data compatibility and restarts against the current volume. It does not restore an older data snapshot. Intentional data restore requires a separate recovery decision and an export of post-snapshot visitor state first; keep both copies.

After judging and verified export, explicitly shut down/delete the named VM using its recordedID. Then inspect and separately delete the recordedOS and data volumes only when the user no longer needs them. Detached/OS/data volumes continue billing until deleted; CLIsoft-delete moves them to recoverabletrash for96hours. Recheck running costs and volume inventory afterward. Do not use bulk `--all`, permanently delete, removeSSHkeys used elsewhere or assumeVMdeletion includes storage. [Storage deletion behavior](https://docs.verda.com/cli/storage/) and [billing](https://docs.verda.com/welcome-to-verda/pricing-and-billing/) explain the separate charges.

## Created resource ledger (2026-11-14)

The 50+50-GiB request succeeded. Exactly one on-demand CPU VM was created at 16:28 UTC in FIN-03, with zero GPUs. The data disk was matched to the cloud volume's serial suffix before formatting and mounted by UUID. The API's successful creation response was a plain-text ID despite its JSON schema; inventory was used to resolve it without repeating creation.

- VM: `94ac2a5f-56e7-4cfc-8770-55fbcf07b2b2` (`95.133.254.90`).
- OS volume: `acc93d78-ea7a-4e50-8da8-d9b44a071bc1` (50 GiB).
- Data volume: `477dacf2-ed37-4aa9-8d7b-3ae2e4aea4eb` (50 GiB).
- HTTPS hostname: `95.133.254.90.sslip.io`; DNS resolved to the VM before deployment. Certificate/public acceptance remains to be recorded below.
- Actual resource records: compute €0.043/hour; each volume €0.012261575/hour. Total approximately €0.06752315/hour or €2.43084 for 36 hours. No paid top-up was enabled.
- Dedicated operator SSH key: `/home/jcb/.ssh/junction-verda-demo-20261114`; cloud key ID `b96846c3-2397-42a8-bb39-76c4f768ea23`. The private key stays local.
- Prepared seed: nine exact revisions, 52,239,746 bytes before archive compression; eight derived IFCs reopened and one supplied IFC retained, zero provider calls. Loading all cached models in an isolated local process peaked at 116.8 MiB RSS; this is not a concurrent inference/tessellation peak guarantee.
- Independent implementation review cleared the mount check, one local worker, secret handling, seed integrity/conflict refusal and rollback design. Four focused deployment tests passed.

These identifiers support explicit export and teardown after judging; no automatic deletion is scheduled. The shared SVG and KIT examples retain negative review findings and must remain visibly partial, not described as accepted accurate reconstructions.

The initial release `9a001f3da55ca292f079362333bdb36ebd328479` serves valid public HTTPS. Anonymous `/api/access` reports public demo with paid work locked. FastAPI listens only on loopback; Caddy owns public ports 80/443. A coordinated application restart verified all 436 seed-file hashes unchanged, nine public examples, zero jobs before/after, and the persistent data mount present. No provider calls were made for deployment/seed/restart. Initial app memory was about 117 MiB. The installer readiness probe was updated to retry connection refusal for up to 60 seconds after systemd start; this only bounds deployment verification, not user work or model processing. Fresh upload, paid QA/refusal and independent public browser acceptance still require the orchestrator’s final integrated checks.
