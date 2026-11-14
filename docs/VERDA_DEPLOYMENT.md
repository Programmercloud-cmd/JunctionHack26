# Verda deployment runbook

Deployment is not yet live. Read [VERDA_DEPLOYMENT_PLAN.md](VERDA_DEPLOYMENT_PLAN.md) and [PUBLIC_DEMO_PLAN.md](PUBLIC_DEMO_PLAN.md). Use one CPU VM, one FastAPI process, a separate persistent NVMe data volume and Caddy HTTPS. Gemini credentials remain server-side. Cloud credentials stay on the operator's machine.

## Confirmed preflight

Official Verda CLIv1.10.0 is installed at `/home/jcb/.local/bin/verda`; the release archive's SHA256 was verified. Authentication is now working. Authenticated checks found€200credit balance and no existing instance burn. FIN-01 stock disappeared before provisioning. FIN-03 lists `CPU-TURIN.4V.16G`; stock must be rechecked immediately before creating it. PlainUbuntu24.04 uses API image slug `24.04.base`.

For 4 vCPU/16 GiB, the initial 40-GiB OS + 20-GiB data quote was $0.0645/hour. The API rejected 40 GiB as too small. Both the official CLI wizard and Verda Console use a 50-GiB OS default; the revised 50+20-GiB quote is $0.0672/hour: $0.048 compute, $0.0137 OS, $0.0055 data. The catalog explicitly reportsUSD; CLI estimate omits its currency, so do not call this aEURquote. The direct API's FIN-03 `location_prices` confirmed$0.048/hour compute.36 hours totals $2.7144, approximately €2.43 using Verda's separately displayed currentEURrates; actual billing conversion can differ. This is far below the confirmed€200credit balance. Recheck balance, active resources, prices and availability before provisioning; never enable paid top-ups. Gemini API charges are separate.

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

## Verification and restart

An independent reviewer must directly use the publicHTTPSURL, both logged out and with the code. Verify all nine cached examples, orbit/floor/overlay controls, object-source links, assumptions and export. Anonymous paid/private calls must fail before provider use. Shared examples must resist direct API mutation, grouped/identical uploads and mutating chat actions. Public listings and example details must not expose private jobs/history/uploads.

Run live Gemini supportedQA and a genuinely unsupported actual-height question; verify citations and refusal despite visible extrusions. Upload a fresh nonsensitive blueprint, watch background stages, refresh and recover the job/result. Keep all source/geometry fidelity gaps visible; successfulAPI responses are not accuracy evidence.

Record current revision/source/IFC hashes, stop or drain jobs and restart `blueprint-qa`. Verify the same sources/current revisions and cached models load with no unnecessary inference. A restart may mark unfinished jobs interrupted; usable revisions must remain. The volume must still be mounted. Inspect memory/disk with `systemctl show blueprint-qa -p MemoryCurrent` and `df -h /srv/blueprint-data`, without printing service environment. A VMreboot test is useful after the app test if no active demo is being served.

## Export, rollback and teardown after judging

Before a consistent data export, drain or explicitly stop jobs and stop the application; do not copy a movingCURRENTpointer as a verified snapshot. Archive `/srv/blueprint-data` to a separate path with restricted permissions, transfer it locally, verify itsSHA256and test a private restore/reopen with inference disabled. Restart the app when export finishes if the event is ongoing. There is no automatic deletion or shutdown timer.

Keep the previous release path recorded in `/opt/blueprint/previous-release.txt`. Code rollback stops the app, switches the release symlink to the verified previous commit, checks data compatibility and restarts against the current volume. It does not restore an older data snapshot. Intentional data restore requires a separate recovery decision and an export of post-snapshot visitor state first; keep both copies.

After judging and verified export, explicitly shut down/delete the named VM using its recordedID. Then inspect and separately delete the recordedOS and data volumes only when the user no longer needs them. Detached/OS/data volumes continue billing until deleted; CLIsoft-delete moves them to recoverabletrash for96hours. Recheck running costs and volume inventory afterward. Do not use bulk `--all`, permanently delete, removeSSHkeys used elsewhere or assumeVMdeletion includes storage. [Storage deletion behavior](https://docs.verda.com/cli/storage/) and [billing](https://docs.verda.com/welcome-to-verda/pricing-and-billing/) explain the separate charges.
