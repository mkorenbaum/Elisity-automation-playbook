# Elisity Microsegmentation: GitOps Lifecycle Demo

Declarative healthcare microsegmentation for the Elisity `insights-demo`
tenant, Hospital site. Four YAML files define 8 Policy Groups, 36 Policies,
6 custom Security Profiles, and a dedicated Policy Set. Six replayable
lifecycle scenarios demonstrate the full GitOps loop: bootstrap, add, update,
profile swap, site scope, revert.

Built for analyst demonstrations of Forrester Wave Strategy Q19:

> *"To what extent can the provisioning and on-going operation of the solution
> be automated and orchestrated? How well does it align to modern practices
> such as DevSecOps and GitOps? To what extent can the solution be integrated
> with provisioning, automation, orchestration, and/or development pipelines
> and tooling (e.g., Ansible, Terraform, Argo, Jenkins)?"*

---

## The story

Hospital networks put infusion pumps, patient monitors, imaging modalities,
EHR servers, clinician workstations, and building-management controllers on
the same physical fabric. Segmenting these device classes by hand through a
UI does not scale. The combinatorial policy matrix alone (8 groups producing
36 directional pairs) makes click-driven operations error-prone, unreviewable,
and impossible to audit after the fact.

This repo replaces UI clicks with Git commits. The source of truth is four
YAML files checked into this repository. Every change is a pull request. Every
PR gets an automated preview comment showing exactly what will change in the
Elisity Cloud Control Center (CCC) before anything touches the tenant. Merging
the PR applies the change. Tagging a release promotes policies from
monitor-only simulation to enforcement. An hourly drift check detects
out-of-band edits and opens a GitHub issue. Reverting is a one-click workflow
that opens a removal PR.

The demo replays six named lifecycle scenarios, each independently triggerable:

1. **Bootstrap** the policy set, PG label, and security profiles from scratch
2. **Add** a new multi-source Policy Group via PR
3. **Update** match criteria on an existing Policy Group via PR
4. **Attach** a security profile to a policy via PR
5. **Scope** VE-to-site assignment as declarative config
6. **Revert** and clean up, proving pre-existing tenant objects are untouched

Safety is structural, not procedural. Three independent guards (PG label,
SP name prefix, policy set boundary) ensure that reconciliation only touches
demo objects. Pre-existing Policy Groups in the tenant (including all CORK
content) carry none of these markers and are never candidates for modification
or deletion. See [Safety story](#safety-story) for the full breakdown.

---

## Architecture at a glance

```
+-----------------------------------------------------------------+
|  Git Repository (source of truth)                               |
|                                                                 |
|  policy-set.yaml ---------- Policy Set + PG label + site scope  |
|  security-profiles.yaml --- 6 custom L4 security profiles       |
|  policy-groups.yaml ------- 8 Policy Groups (match criteria)    |
|  policies.yaml ------------ 36 Policies (8x8 matrix)           |
+--------------------------+--------------------------------------+
                           |  PR / merge / tag / dispatch
                           v
+-----------------------------------------------------------------+
|  GitHub Actions (self-hosted runner, 10.0.0.175)                |
|                                                                 |
|  bootstrap.yml --- workflow_dispatch --- bin/bootstrap.py        |
|  preview.yml ----- PR open/update ------ bin/preview.py         |
|  apply.yml ------- push to main -------- playbooks/ + reconcile |
|  promote.yml ----- release published --- bin/promote.py         |
|  drift-check.yml - hourly + manual ----- bin/drift.py           |
|  revert.yml ------ workflow_dispatch --- opens removal PR       |
|  cleanup.yml ----- workflow_dispatch --- bin/cleanup_by_prefix  |
+--------------------------+--------------------------------------+
                           |  HTTPS + OAuth2 client credentials
                           v
+-----------------------------------------------------------------+
|  Elisity CCC -- insights-demo.idp01.elisity.io -- Hospital     |
+-----------------------------------------------------------------+
```

### Declarative object layers

| Layer | Object | Count | Governed by |
|:---:|---|:---:|---|
| 1 | Policy Set (`FRSTR-HOSPITAL`) | 1 | `policy-set.yaml` |
| 2 | PG Label (`FORRESTER-DEMO`) | 1 | `policy-set.yaml` |
| 3 | Security Profiles (custom, `FRSTR-` prefixed) | 6 | `security-profiles.yaml` |
| 4 | Policy Groups | 8 | `policy-groups.yaml` |
| 5 | Policies | 36 | `policies.yaml` |
| 6 | Site scope (`Hospital`) | 1 | `policy-set.yaml` (`site_labels`) |

Pure permit-all and deny-all matrix cells reference the CCC system built-in
profiles `Allow All` and `Deny All` directly. These are not created by
bootstrap and do not appear in `security-profiles.yaml`.

### Workflow cheatsheet

| Workflow | Trigger | What it does |
|---|---|---|
| `bootstrap.yml` | `workflow_dispatch` | Creates policy set, PG label, 6 custom security profiles. Idempotent. |
| `preview.yml` | PR opened / updated | Posts preview comment with impact diff. |
| `apply.yml` | Push to main | Applies YAML state to CCC, then runs reconcile. |
| `promote.yml` | Release published | Flips all policies from `MONITOR_ONLY` to `MONITOR_AND_ENFORCE`. |
| `drift-check.yml` | Hourly + manual | Diffs CCC live state against main YAML. Opens issue on drift. |
| `revert.yml` | `workflow_dispatch` | Opens a PR removing a named PG from YAML. |
| `cleanup.yml` | `workflow_dispatch` | Deletes all demo objects scoped by PG label + SP prefix + policy set. |

---

## The 8 Policy Groups

Each Policy Group classifies devices using multiple condition blocks OR-ed
together. Within each block, conditions are AND-ed. Every PG carries the
`FORRESTER-DEMO` label (an invisible cleanup tag, separate from the PG name).

Seven of the eight PGs follow the same three-block classification pattern:

1. **Block 1 (core anchor):** A `core.normalizedClass` match that places the
   device in the right asset class.
2. **Block 2 (connector signal):** A high-fidelity attribute from an
   IdentityGraph connector (Armis, Medigate, ServiceNow, CrowdStrike, or
   Microsoft Defender).
3. **Block 3 (manual fallback):** A `core.label` match so operators can
   manually tag devices that no connector has catalogued yet.

The ISOLATION PG is the exception: Block 3 only (manual label). A device
lands in ISOLATION only when an analyst or SOAR action explicitly tags it.

| Policy Group | SL | Block 1 (core anchor) | Block 2 (connector signal) | Block 3 (manual label) |
|---|:---:|---|---|---|
| `INFUSION-PUMPS` | 3 | `core.normalizedClass EQ "Medical Device"` | `armis.deviceType EQ "Infusion Pump"` | `core.label EQ "INFUSION-PUMPS"` |
| `PATIENT-MONITORS` | 3 | `core.normalizedClass EQ "Medical Device"` | `medigate.deviceClass EQ "Patient Devices"` | `core.label EQ "PATIENT-MONITORS"` |
| `IMAGING` | 3 | `core.normalizedClass EQ "Medical Device"` | `medigate.deviceClass EQ "Imaging"` | `core.label EQ "IMAGING"` |
| `EHR-SERVERS` | 3 | `core.normalizedClass EQ "Server Appliance and Storage"` | `core.trustAttributes CONTAINS "Known in ServiceNow"` | `core.label EQ "EHR-SERVERS"` |
| `VERIFIED-SERVERS` | 2 | `core.normalizedClass EQ "Server Appliance and Storage"` | `core.trustAttributes CONTAINS "Known in CrowdStrike"` | `core.label EQ "VERIFIED-SERVERS"` |
| `VERIFIED-PCS` | 1 | `core.normalizedClass EQ "PC"` | `core.trustAttributes CONTAINS "Known in Microsoft Defender"` | `core.label EQ "VERIFIED-PCS"` |
| `BUILDING-MANAGEMENT` | 3 | `core.normalizedClass EQ "Building Management"` | `armis.deviceType EQ "BMS Controller"` | `core.label EQ "BUILDING-MANAGEMENT"` |
| `ISOLATION` | 1 | _(none)_ | _(none)_ | `core.label EQ "QUARANTINE"` |

**SL** = IEC 62443 Security Level. Five connector partners are represented:
Armis, Medigate, Microsoft Defender for Endpoint, CrowdStrike, ServiceNow.

The multi-source model means classification degrades gracefully. If a
connector goes offline, devices still match through the remaining blocks.
The manual-label block is the escape hatch for devices that no connector
has catalogued yet. For ISOLATION, the `QUARANTINE` label value (distinct
from the PG name) supports analyst incident-response tagging.

---

## The policy matrix

36 policies form the 8x8 segmentation matrix inside the `FRSTR-HOSPITAL`
policy set. All inter-PG policies are BIDIRECTIONAL, so the lower triangle
mirrors the upper and is shown as `.` below.

```
          INF   PAT   IMG   EHR   VRF-S VRF-P BMS   ISO
INF       self  DENY  DENY  HL7   DENY  DENY  DENY  DENY
PAT        .    self  DENY  HL7   DENY  DENY  DENY  DENY
IMG        .     .    self  DCM   DENY  DENY  DENY  DENY
EHR        .     .     .    self  ANY*  ANY*  DENY  DENY
VRF-S      .     .     .     .    self  ANY*  DENY  DENY
VRF-P      .     .     .     .     .    self  DENY  DENY
BMS        .     .     .     .     .     .    self  DENY
ISO        .     .     .     .     .     .     .    self
```

**Abbreviations:**
`INF` = INFUSION-PUMPS, `PAT` = PATIENT-MONITORS, `IMG` = IMAGING,
`EHR` = EHR-SERVERS, `VRF-S` = VERIFIED-SERVERS, `VRF-P` = VERIFIED-PCS,
`BMS` = BUILDING-MANAGEMENT, `ISO` = ISOLATION.

**Cell legend:**

| Code | Security Profile | Ports | Final Action |
|---|---|---|---|
| `self` | `Allow All` (system) | any | PERMIT (intra-PG); see exceptions below |
| `HL7` | `FRSTR-ALLOW-HL7` | TCP 2575 | DENY (only HL7 permitted) |
| `DCM` | `FRSTR-ALLOW-DICOM` | TCP 104, 11112, 11113 | DENY (only DICOM permitted) |
| `ANY*` | `Allow All` (system) | any | PERMIT (trusted-zone full mesh) |
| `DENY` | `Deny All` (system) | any | DENY |
| `.` | Bidirectional; covered by the symmetric entry above | | |

**Self-policy exceptions:** Six of eight self-policies use the system
`Allow All` profile. Two exceptions: BUILDING-MANAGEMENT self uses
`FRSTR-BMS-MODBUS` (Modbus TCP 502 only, final action DENY), and ISOLATION
self uses `FRSTR-QUARANTINE` (DNS UDP 53 permit, then deny all, final action
DENY).

### Matrix breakdown

| Category | Count | Security Profile shown in CCC UI |
|---|:---:|---|
| Self (Allow All) | 6 | `Allow All` |
| Self (custom) | 2 | `FRSTR-BMS-MODBUS`, `FRSTR-QUARANTINE` |
| Clinical-specific | 3 | `FRSTR-ALLOW-HL7` x2, `FRSTR-ALLOW-DICOM` x1 |
| Trusted-zone permit | 3 | `Allow All` |
| Deny-all | 22 | `Deny All` |
| **Total** | **36** | **22 Deny All + 9 Allow All + 5 custom** |

The CCC policy list renders these profile names verbatim. An analyst scanning
the security-profile column reads the matrix intent at a glance: clinical
workflows get protocol-specific profiles, trusted infrastructure gets
permit-all, and everything else is deny-all.

All 36 policies deploy in `MONITOR_ONLY`. Tagging a release flips them to
`MONITOR_AND_ENFORCE` via `promote.yml`.

### The 6 permitted lateral paths

Only 6 of 28 inter-PG pairs allow traffic. The remaining 22 are explicit
deny-all:

1. **Infusion pumps to EHR servers** (HL7, TCP 2575)
2. **Patient monitors to EHR servers** (HL7, TCP 2575)
3. **Imaging to EHR servers** (DICOM, TCP 104/11112/11113)
4. **EHR servers to verified servers** (Allow All, trusted zone)
5. **EHR servers to verified PCs** (Allow All, trusted zone)
6. **Verified servers to verified PCs** (Allow All, trusted zone)

Paths 1-3 are clinical workflows restricted to a single protocol. Paths 4-6
are trusted-infrastructure full mesh between EHR servers, CrowdStrike-verified
servers, and Defender-onboarded PCs.

---

## Lifecycle scenarios

Six independently replayable scenarios. Run them in order for a full
walkthrough, or pick any single scenario to demonstrate a specific lifecycle
operation.

### Scenario 1: Bootstrap

Stand up the foundational objects in one click.

**Goal:** Create the policy set, PG label, and all 6 custom security profiles
in CCC from scratch. The analyst sees a single workflow run produce the
infrastructure that every subsequent scenario depends on.

**Trigger:** `workflow_dispatch` on `bootstrap.yml` from the GitHub Actions UI.
Required inputs: `confirm` = `BOOTSTRAP-FORRESTER-DEMO`,
`target_branch` = `main`.

**Expected outcome:**

- 1 policy set (`FRSTR-HOSPITAL`) created in CCC
- 1 PG label (`FORRESTER-DEMO`) created
- 6 custom security profiles created (names match `security-profiles.yaml`)
- Auto-PR opened that writes the resolved CCC object IDs into
  `inventory/group_vars/all.yml` so subsequent CI runs reference them by ID

**Reset:** Run `cleanup.yml` to delete all demo objects, then re-run
`bootstrap.yml`. Bootstrap is idempotent; re-running without cleanup
is a no-op.

See [The bootstrap step](#the-bootstrap-step) for the detailed walkthrough.

---

### Scenario 2: Add a multi-source Policy Group

Add a new PG through a pull request, demonstrating multi-source classification
and the automated preview gate.

**Goal:** The analyst opens a PR that adds a Policy Group with multiple
condition blocks (connector-driven plus manual-label fallback). The preview
workflow posts a comment showing the new PG's OR criteria. Merging creates
the PG in CCC.

**Trigger:** Edit `policy-groups.yaml` in the GitHub UI (or locally), adding
a new entry at the end of the `policy_groups:` list. Open a PR.

**Example entry to paste** (matching the existing 2-space indent):

```yaml
  - name: PACS-ARCHIVES
    description: |
      PACS imaging archive workstations. Multi-source classification:
      Medigate device-class primary, normalized class plus hostname
      secondary, manual label fallback.
    type: DYNAMIC
    security_level: 3
    auto_lock_devices: false
    labels: [FORRESTER-DEMO]
    match:
      condition_blocks:
        - conditions:
            - { attribute: medigate.deviceClass, operator: EQ, values: ["PACS"] }
        - conditions:
            - { attribute: core.normalizedClass, operator: EQ, values: ["Medical Device"] }
            - { attribute: core.hostname, operator: CONTAINS, values: ["PACS"] }
        - conditions:
            - { attribute: core.label, operator: EQ, values: ["PACS-ARCHIVES"] }
```

**Expected outcome:**

- Preview comment from `github-actions[bot]` showing the new PG, its 3 OR
  condition blocks, and security level
- After merge, `apply.yml` runs and creates the PG in CCC
- Reconcile step confirms no orphans

**Reset:** Run `revert.yml` with `pg_name=PACS-ARCHIVES` to open a removal
PR. Merge that PR. The reconcile step in apply deletes the PG from CCC.

---

### Scenario 3: Update PG match criteria

Tighten or loosen classification on an existing Policy Group through a PR.

**Goal:** The analyst edits the match criteria of an existing PG and sees a
pure criteria diff in the preview comment. This demonstrates that
classification changes go through the same review gate as any other change.

**Trigger:** Edit `policy-groups.yaml` in the GitHub UI. Modify the
`condition_blocks` of an existing PG entry. Open a PR.

**Example edit on `VERIFIED-SERVERS`:** The PG currently matches on
`core.normalizedClass EQ "Server Appliance and Storage"` (Block 1),
`core.trustAttributes CONTAINS "Known in CrowdStrike"` (Block 2), and
`core.label EQ "VERIFIED-SERVERS"` (Block 3). To add a fourth block
recognizing Armis-corroborated servers, insert after Block 2:

```yaml
        - conditions:
            - { attribute: core.trustAttributes, operator: CONTAINS, values: ["Known in Armis"] }
```

**Expected outcome:**

- Preview comment shows the criteria diff: one new condition block added to
  `VERIFIED-SERVERS`
- After merge, `apply.yml` updates the PG's `matchingCriteria` in CCC

**Reset:** Open a follow-up PR that removes the added block, or revert the
merge commit. Merge to restore the original 3-block criteria.

---

### Scenario 4: Attach a security profile to a policy

Change which L4 security profile governs a specific policy through a PR.

**Goal:** The analyst changes one field in `policies.yaml` to swap the profile
on a policy. The preview comment shows the before/after. This demonstrates
that policy-level access control changes are reviewable, auditable, and
version-controlled.

**Trigger:** Edit `policies.yaml` in the GitHub UI. Change the
`security_profile` field on an existing policy entry. Open a PR.

**Example edit on IMAGING to EHR-SERVERS:** Swap from `FRSTR-ALLOW-DICOM`
to `FRSTR-ALLOW-HTTPS`:

```yaml
  # Before
  security_profile: FRSTR-ALLOW-DICOM

  # After
  security_profile: FRSTR-ALLOW-HTTPS
```

This changes the permitted traffic between imaging and EHR servers from DICOM
(TCP 104, 11112, 11113) to HTTPS only (TCP 443).

**Expected outcome:**

- Preview comment shows the profile swap with before/after profile names and
  port differences
- After merge, `apply.yml` updates the policy in CCC with the new profile
  reference

**Reset:** Open a follow-up PR that reverts the `security_profile` field back
to `FRSTR-ALLOW-DICOM`. Merge to restore.

---

### Scenario 5: VE-to-site assignment (declarative scope)

The Virtual Edge (VE) to site relationship determines where policies take
effect. This scenario documents the declarative scope.

**Goal:** The analyst sees that the policy set is scoped to the `Hospital`
site via `site_labels` in `policy-set.yaml`. When a VE is assigned to the
Hospital site, all policies in the `FRSTR-HOSPITAL` policy set automatically
take effect for devices behind that VE.

**Trigger:** Manual configuration. VE-to-site assignment is configured in the
CCC UI or via the CCC API. The demo does not automate this step; VE lifecycle
management is out of band for this release.

**What to show:**

- Open `policy-set.yaml` and point to `site_labels: [Hospital]`
- In the CCC UI, navigate to the Hospital site and show its assigned VEs
- Explain: the policy set binds to the site label, not to individual VEs.
  Adding or removing a VE from the Hospital site automatically changes which
  devices fall under demo policies.

**Expected outcome:** The analyst understands that the declarative model
extends to site scoping. The YAML declares *which* site the policies target.
The VE-to-site binding is the operational step that activates enforcement
for a given network segment.

**Reset:** N/A. This scenario is read-only.

---

### Scenario 6: Revert and cleanup

Tear down all demo objects and verify that pre-existing tenant content is
untouched.

**Goal:** The analyst runs the cleanup workflow and confirms that only demo
objects are removed. Pre-existing Policy Groups in the tenant (including all
CORK content) survive. This is the safety proof.

**Trigger:** `workflow_dispatch` on `cleanup.yml` from the GitHub Actions UI.
Leave defaults.

**Expected outcome:**

- All Policy Groups carrying the `FORRESTER-DEMO` label are deleted
- All Security Profiles with the `FRSTR-` name prefix are deleted
- All Policies inside the `FRSTR-HOSPITAL` policy set are deleted
- The policy set and PG label themselves are deleted
- The cleanup log lists each deletion with object name and type
- Pre-existing Policy Groups that do not carry the `FORRESTER-DEMO` label, do
  not have the `FRSTR-` name prefix, and are not in the `FRSTR-HOSPITAL`
  policy set remain untouched
- Navigate to Policy Groups in the CCC UI to confirm: demo PGs gone,
  CORK PGs and production PGs present

**Reset:** Run `bootstrap.yml` followed by a push to main (or `apply.yml`
manually) to re-create the full demo state from scratch.

**For individual PG removal** without a full cleanup, use `revert.yml`:

1. Navigate to Actions, select **Revert (remove a Policy Group)**.
2. Enter the PG name (e.g., `PACS-ARCHIVES`) and a reason.
3. The workflow opens a PR removing that PG from `policy-groups.yaml`.
4. Merge the PR. The reconcile step in apply deletes the PG from CCC.

---

## The bootstrap step

Detailed walkthrough of the one-time setup. Run this before any other
scenario.

**Prerequisites:**

- Repository secrets configured: `CCC_URL`, `CCC_CLIENT_ID`,
  `CCC_CLIENT_SECRET` (see [Required GitHub configuration](#required-github-configuration))
- Self-hosted runner online (see [Self-hosted runner](#self-hosted-runner))

**Steps:**

1. Open the repository on GitHub. Navigate to **Actions** > **Bootstrap**
   in the left sidebar.
2. Click **Run workflow**. Set `confirm` to `BOOTSTRAP-FORRESTER-DEMO` and
   `target_branch` to `main`.
3. Click **Run workflow** to start the job.
4. Watch the job log. Bootstrap performs these operations in order:
   - Authenticates to CCC via OAuth2 client credentials
   - Looks up the policy set `FRSTR-HOSPITAL` by name; creates it if missing,
     with `state: MONITOR_ONLY` and `site_labels: [Hospital]`
   - Looks up the PG label `FORRESTER-DEMO`; creates it if missing
   - For each of the 6 security profiles in `security-profiles.yaml`: looks
     up by name, creates if missing
   - Opens an auto-PR that writes the resolved CCC object IDs into
     `inventory/group_vars/all.yml`
5. When the job finishes (green check), merge the auto-PR. This caches the
   CCC IDs so that `apply.yml`, `promote.yml`, and `drift-check.yml` can
   reference objects by ID instead of querying by name on every run.

**Idempotency:** Running bootstrap a second time without cleanup is a no-op.
Every create operation checks for existence by name first.

**Objects created:**

| Type | Name | Source |
|---|---|---|
| Policy Set | `FRSTR-HOSPITAL` | `policy-set.yaml` |
| PG Label | `FORRESTER-DEMO` | `policy-set.yaml` |
| Security Profile | `FRSTR-ALLOW-DICOM` | `security-profiles.yaml` |
| Security Profile | `FRSTR-ALLOW-HL7` | `security-profiles.yaml` |
| Security Profile | `FRSTR-ALLOW-HTTPS` | `security-profiles.yaml` |
| Security Profile | `FRSTR-CLINICAL-IOT` | `security-profiles.yaml` |
| Security Profile | `FRSTR-BMS-MODBUS` | `security-profiles.yaml` |
| Security Profile | `FRSTR-QUARANTINE` | `security-profiles.yaml` |

---

## The 4 YAML files

These four files are the entire declarative surface of the demo. Nothing
else describes the segmentation state.

### `policy-set.yaml`

Defines the dedicated policy set, its enforcement mode, the PG label used
for scoping, and the target site.

```yaml
policy_set:
  name: FRSTR-HOSPITAL
  state: MONITOR_ONLY
  policy_group_labels:
    - FORRESTER-DEMO
  site_labels:
    - Hospital
```

The policy set is the isolation boundary. Policies inside this set only
target Policy Groups carrying the `FORRESTER-DEMO` label and only apply to
VEs assigned to the Hospital site. The `MONITOR_ONLY` state means all
policies simulate by default; `promote.yml` flips to `MONITOR_AND_ENFORCE`
when a release is tagged.

This file also defines the PG label itself:

```yaml
policy_group_labels:
  - name: FORRESTER-DEMO
    description: |
      Marker label for Policy Groups owned by the Forrester GitOps
      demo. Used both as the policy-set scoping boundary and as the
      reconcile.py safety tag. Any PG without this label is never
      considered for deletion.
```

### `security-profiles.yaml`

Defines 6 custom L4 security profiles, each a named set of
protocol/port/action rules. All custom profile names carry the `FRSTR-`
prefix (the cleanup boundary for SPs).

| Profile | Ports | Use |
|---|---|---|
| `FRSTR-ALLOW-DICOM` | TCP 104, 11112, 11113 | Imaging modality to archive |
| `FRSTR-ALLOW-HL7` | TCP 2575 | Clinical messaging (ADT, orders, results) |
| `FRSTR-ALLOW-HTTPS` | TCP 443 | Management plane, clinician thick-client access |
| `FRSTR-CLINICAL-IOT` | UDP 53, UDP 123, TCP 443 | Locked-down IoT egress: DNS + NTP + HTTPS |
| `FRSTR-BMS-MODBUS` | TCP 502 | Building automation control (Modbus TCP) |
| `FRSTR-QUARANTINE` | UDP 53 permit, then deny all | Incident-response DNS-only lockdown |

Pure permit-all and deny-all matrix cells reference the CCC system built-in
profiles `Allow All` and `Deny All` directly. These system profiles are not
defined in this file and are not created by bootstrap. Using the system names
means the CCC UI renders "Allow All" and "Deny All" verbatim in the policy
list, making matrix intent visible at a glance.

### `policy-groups.yaml`

Defines 8 Policy Groups with multi-source `matchingCriteria`. Each PG's
`condition_blocks` list contains OR-ed blocks; within each block, conditions
are AND-ed. See [The 8 Policy Groups](#the-8-policy-groups) for the full
classification table.

Key schema fields per entry:

- `name` (string): clean functional name (no prefix; the PG label is the
  scoping mechanism)
- `type`: `DYNAMIC`
- `security_level` (int): IEC 62443 Security Level (1, 2, or 3)
- `auto_lock_devices` (bool): `true` only for ISOLATION
- `labels` (list): must include `FORRESTER-DEMO`
- `match.condition_blocks` (list of lists): the OR-of-AND classification
  logic, using attributes from `core.*`, `armis.*`, and `medigate.*`
  namespaces

### `policies.yaml`

Defines the 36-policy segmentation matrix: 8 self-policies (intra-PG),
3 clinical-specific workflows (HL7/DICOM), 3 trusted-zone permit-all pairs,
and 22 explicit deny-all pairs. See [The policy matrix](#the-policy-matrix)
for the full grid.

Key schema fields per entry:

- `direction`: `BIDIRECTIONAL` or `SELF`
- `source_pg`, `destination_pg`: PG names (resolved to CCC IDs at apply time)
- `security_profile`: profile name; one of the 6 custom `FRSTR-` profiles or
  system `Allow All` / `Deny All`
- `final_action`: `PERMIT` or `DENY`
- `policy_set`: `FRSTR-HOSPITAL`
- `state`: `MONITOR_ONLY` (flipped by `promote.yml` on release tag)

---

## Repo layout

```
.
├── README.md                       <- you are here
├── policy-set.yaml                 <- policy set + PG label + site scope
├── security-profiles.yaml          <- 6 custom L4 security profiles
├── policy-groups.yaml              <- 8 Policy Groups (match criteria)
├── policies.yaml                   <- 36 Policies (8x8 matrix)
├── inventory/group_vars/all.yml    <- tenant-specific IDs (auto-updated by bootstrap)
├── playbooks/
│   ├── _auth.yml                   <- OAuth client_credentials flow
│   ├── 00-list-connectors.yml      <- read-only proof of life
│   ├── 01-policy-groups.yml        <- apply policy-groups.yaml
│   ├── 02-policies.yml             <- apply policies.yaml
│   ├── 03-verify.yml               <- re-fetch live state
│   └── 99-cleanup.yml              <- teardown (Ansible)
├── bin/
│   ├── ccc.py                      <- Python stdlib HTTP helper (urllib + json)
│   ├── bootstrap.py                <- creates policy set + label + profiles
│   ├── preview.py                  <- PR preview report
│   ├── promote.py                  <- MONITOR_ONLY -> MONITOR_AND_ENFORCE
│   ├── drift.py                    <- live state vs main YAML diff
│   ├── reconcile.py                <- deletes CCC orphans not in YAML
│   └── cleanup_by_prefix.py        <- prefix-scoped wipe
├── .github/workflows/
│   ├── bootstrap.yml               <- workflow_dispatch: one-time setup
│   ├── preview.yml                 <- runs on PR
│   ├── apply.yml                   <- runs on push to main
│   ├── promote.yml                 <- runs on release published
│   ├── drift-check.yml             <- runs hourly
│   ├── cleanup.yml                 <- manual
│   └── revert.yml                  <- manual: opens revert PR
├── terraform/                      <- parallel IaC implementation
└── examples/                       <- curl, python, argo, jenkins, gitlab-ci
```

---

## Required GitHub configuration

One-time setup for the workflows to run.

### Repository secrets (`Settings > Secrets and variables > Actions`)

- `CCC_URL`: Cloud Control Center base URL
  (e.g., `https://insights-demo.idp01.elisity.io`)
- `CCC_CLIENT_ID`: OAuth2 service-account client ID
- `CCC_CLIENT_SECRET`: OAuth2 service-account client secret

### Environment (`Settings > Environments`)

Create one named **`insights-demo`**. Attach the three secrets above.
Optionally add a required reviewer to gate `apply.yml` and `promote.yml`
runs on a human approval click.

### Branch protection (`Settings > Branches > main`)

- Require a pull request before merging.
- Require status check `preview` to pass.

---

## Self-hosted runner

`insights-demo` is on Elisity's internal network and unreachable from
GitHub-hosted runners. All CCC-touching workflows (`bootstrap`, `apply`,
`promote`, `drift-check`, `cleanup`, `revert`) declare `runs-on: self-hosted`
and dispatch to a runner registered on Mike's lab host
(`elisity-host-10-0-0-175`).

The runner process lives at
`/home/elisity/github-runners/automation-playbook/run.sh` on `10.0.0.175`.

To verify the runner is up: check the repository **Settings > Actions >
Runners** page. The runner should show as `Idle` or `Active`.

After a host reboot, restart with:

```bash
ssh elisity@10.0.0.175 'cd /home/elisity/github-runners/automation-playbook && nohup ./run.sh > runner.log 2>&1 &'
```

---

## Safety story

Three independent guards protect pre-existing tenant content from
modification or deletion by the demo's reconcile and cleanup operations.
Each guard operates on a different object type, and all three are independent
of any existing CORK or Default content in the tenant.

### Guard 1: PG label (`FORRESTER-DEMO`)

Every Policy Group managed by this demo carries the `FORRESTER-DEMO` label.
This label is a separate field from the PG name; PG names are clean
functional identifiers (`INFUSION-PUMPS`, `IMAGING`, etc.) with no prefix
and no risk of name collision. The policy set is scoped to this label.
`reconcile.py` only considers PGs with the `FORRESTER-DEMO` label when
computing the delete set. Pre-existing Policy Groups (including all CORK PGs)
do not carry this label and are invisible to reconciliation.

### Guard 2: Security profile name prefix (`FRSTR-`)

Every custom Security Profile created by this demo uses the `FRSTR-` name
prefix. `cleanup_by_prefix.py` uses this prefix as its deletion filter for
profiles. CCC has no labelling mechanism for Security Profiles, so the name
prefix is the only safety boundary. CORK Security Profiles do not carry the
`FRSTR-` prefix and are never candidates for deletion.

### Guard 3: Policy set boundary (`FRSTR-HOSPITAL`)

All demo policies live in a dedicated policy set (`FRSTR-HOSPITAL`), separate
from the Default policy set where production policies reside. `reconcile.py`
only deletes policies within the `FRSTR-HOSPITAL` policy set. Policies in
other sets are out of scope.

### How the guards interact

Before `reconcile.py` will delete an object, all applicable conditions must
be true:

1. For Policy Groups: the PG carries the `FORRESTER-DEMO` label AND is not
   declared in the current YAML files
2. For Security Profiles: the SP name starts with `FRSTR-` AND is not
   declared in the current YAML files
3. For Policies: the policy belongs to the `FRSTR-HOSPITAL` policy set AND
   is not declared in the current YAML files

Pre-existing tenant content fails every guard. CORK Policy Groups do not
carry the `FORRESTER-DEMO` label, CORK Security Profiles do not have the
`FRSTR-` name prefix, and CORK Policies are not in the `FRSTR-HOSPITAL`
policy set. The demo can bootstrap, apply, promote, revert, and clean up
repeatedly without any risk to existing tenant content.

---

## Open API hook

Every operation in this demo calls the same CCC REST API that any external
system can call. The `bin/` scripts use Python's `urllib` and `json` (stdlib
only); no proprietary SDK or CLI is involved. The same YAML-to-API pattern
drops into SOAR playbooks that quarantine a device on alert, CMDB sync jobs
that update PG membership when ServiceNow records change, and ITSM workflows
that open a segmentation change request as a pull request. This directly
addresses the Forrester Wave criteria around API-driven integration and
tooling breadth (Q15, Q16) using the same open API surface demonstrated
throughout this repo.
