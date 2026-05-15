# Elisity Microsegmentation: GitOps Lifecycle Demo

Declarative healthcare microsegmentation for the Elisity `insights-demo`
tenant, Hospital site. Four YAML files define 8 Policy Groups, 36 Policies,
6 custom Security Profiles, and a dedicated Policy Set. Eight replayable
lifecycle scenarios demonstrate the full GitOps loop: bootstrap, add, update,
profile swap, drift detection, promote, revert, cleanup.

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

The demo replays eight named lifecycle scenarios, each independently triggerable:

1. **Bootstrap** the policy set, PG label, and security profiles from scratch
2. **Add** a new multi-source Policy Group via PR
3. **Update** match criteria on an existing Policy Group via PR
4. **Attach** a security profile to a policy via PR
5. **Detect** configuration drift between CCC live state and the YAML source of truth
6. **Promote** policies from monitor-only to enforcement via release tag
7. **Revert** a single Policy Group declaratively
8. **Clean up** all demo objects, proving pre-existing tenant content is untouched

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
|  cleanup.yml ----- workflow_dispatch --- bin/cleanup_demo.py    |
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
| `VERIFIED-PCS` | 1 | `core.normalizedClass EQ "PC"` | `core.trustAttributes CONTAINS "Known in Microsoft Defender"` | `core.label EQ "VERIFIED-PCS"` |
| `VERIFIED-SERVERS` | 2 | `core.normalizedClass EQ "Server Appliance and Storage"` | `core.trustAttributes CONTAINS "Known in CrowdStrike"` | `core.label EQ "VERIFIED-SERVERS"` |
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
EHR        .     .     .    self  ANY*  DENY  DENY  DENY
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
| Trusted-zone permit | 2 | `Allow All` |
| Deny-all | 23 | `Deny All` |
| **Total** | **36** | **23 Deny All + 8 Allow All + 5 custom** |

The CCC policy list renders these profile names verbatim. An analyst scanning
the security-profile column reads the matrix intent at a glance: clinical
workflows get protocol-specific profiles, trusted infrastructure gets
permit-all, and everything else is deny-all.

All 36 policies deploy in `MONITOR_ONLY`. Tagging a release flips them to
`MONITOR_AND_ENFORCE` via `promote.yml`.

### The 5 permitted lateral paths

Only 5 of 28 inter-PG pairs allow traffic. The remaining 23 are explicit
deny-all:

1. **Infusion pumps to EHR servers** (HL7, TCP 2575)
2. **Patient monitors to EHR servers** (HL7, TCP 2575)
3. **Imaging to EHR servers** (DICOM, TCP 104/11112/11113)
4. **EHR servers to verified servers** (Allow All, trusted zone)
5. **Verified servers to verified PCs** (Allow All, trusted zone)

Paths 1-3 are clinical workflows restricted to a single protocol. Paths 4-5
are the trusted-infrastructure lane between EHR servers, CrowdStrike-verified
servers, and Defender-onboarded PCs. `EHR-SERVERS` to `VERIFIED-PCS` is
deliberately deny-all in the baseline — open that lane explicitly with a
follow-up PR if a clinical-workstation-to-EHR workflow is approved.

---

## Quick start: zero to working demo

Follow these steps in order. When you finish, the full 8-PG, 36-policy demo
is running in CCC, ready for lifecycle scenario walkthroughs.

### Prerequisites

Before starting, confirm all of the following:

- [ ] Repo cloned locally or forked into a GitHub org with Actions enabled
- [ ] Self-hosted GitHub Actions runner registered and online (see [Self-hosted runner](#self-hosted-runner))
- [ ] Repository secrets configured: `CCC_URL`, `CCC_CLIENT_ID`, `CCC_CLIENT_SECRET` (see [Required GitHub configuration](#required-github-configuration))
- [ ] Workflow permissions: **Allow GitHub Actions to create and approve pull requests** enabled (`Settings` > `Actions` > `General` > `Workflow permissions`)
- [ ] Target CCC tenant has a `Hospital` site label already provisioned

### If the tenant has prior demo state, run cleanup

Skip this sub-section if you are starting with a fresh tenant.

1. Open the repository on GitHub. Click the **Actions** tab.
2. In the left sidebar, click **Cleanup demo state**.
3. Click **Run workflow** (top right). Select branch `main`.
4. In the `confirm` field, type `CLEANUP-FORRESTER-DEMO` exactly. Any other
   value causes the job to skip.
5. Click **Run workflow**.

The workflow job summary will show:

```
## 🧹 Cleanup -- Forrester demo teardown
**Scope:** PG label `FORRESTER-DEMO` + name prefix `FRSTR-*` + policy set `FRSTR-HOSPITAL`
Deleted N object(s):
- Policy   `INFUSION-PUMPS > EHR-SERVERS`
  ... (one line per primary policy)
- PolicySet `FRSTR-HOSPITAL`
- PG       `INFUSION-PUMPS`
  ... (one line per PG)
- SP       `FRSTR-ALLOW-DICOM`
  ... (one line per custom SP)
- PGLabel  `FORRESTER-DEMO`
```

The script deletes in dependency order:

1. All non-reflection policies inside `FRSTR-HOSPITAL` (CCC auto-deletes
   reflection pairs when their parent policy is removed)
2. The `FRSTR-HOSPITAL` policy set (after clearing its scope via PUT)
3. Every Policy Group carrying the `FORRESTER-DEMO` label
4. Every Security Profile whose name starts with `FRSTR-` (skips
   CCC-managed reflection SPs)
5. The `FORRESTER-DEMO` PG label

**Verify cleanup worked:**

- CCC UI > Policy > Policy Sets: no `FRSTR-HOSPITAL`
- CCC UI > Policy > Policy Groups: filter for `FORRESTER-DEMO` label, expect 0 results
- Existing CORK and Default content: untouched

### Bootstrap the demo

1. Click the **Actions** tab. In the left sidebar, click **Bootstrap Forrester Demo**.
2. Click **Run workflow**. Select branch `main`.
3. In the `confirm` field, type `BOOTSTRAP-FORRESTER-DEMO`.
4. Leave `target_branch` as `main` (the default).
5. Click **Run workflow**.

The job creates these objects in CCC:

- PG label `FORRESTER-DEMO`
- Policy set `FRSTR-HOSPITAL` (Hospital site, `MONITOR_ONLY`)
- 6 custom security profiles: `FRSTR-ALLOW-DICOM`, `FRSTR-ALLOW-HL7`,
  `FRSTR-ALLOW-HTTPS`, `FRSTR-CLINICAL-IOT`, `FRSTR-BMS-MODBUS`,
  `FRSTR-QUARANTINE`

When the job finishes, it opens an auto-PR against `main` that caches the
resolved CCC object IDs into `inventory/group_vars/all.yml`. **Merge that PR.**

**Verify bootstrap worked:**

- CCC UI > Policy > Policy Sets: `FRSTR-HOSPITAL` visible (Hospital site, MONITOR_ONLY)
- CCC UI > Policy > Policy Groups: no `FORRESTER-DEMO`-labelled PGs yet (those come from `apply.yml`)

### Apply the PG and policy YAML to CCC

Merging the bootstrap cache PR in the previous step triggers `apply.yml`
automatically (it runs on every push to `main` that touches YAML or tooling
files).

1. Click the **Actions** tab. Click the most recent **Apply to CCC** run.
2. Expand the job steps. The apply log shows 8 PGs created and 36 policies
   created. The reconcile step confirms no orphans.
3. Wait for the run to complete (typically under 60 seconds).

**Verify apply worked:**

- CCC UI > Policy > Policy Groups: 8 demo PGs visible: `INFUSION-PUMPS`,
  `PATIENT-MONITORS`, `IMAGING`, `EHR-SERVERS`, `VERIFIED-SERVERS`,
  `VERIFIED-PCS`, `BUILDING-MANAGEMENT`, `ISOLATION`
- CCC UI > Policy > Policy Sets > `FRSTR-HOSPITAL`: 36 primary policies
  plus 28 reflection policies
- Click any policy: the securityProfileName column shows `Allow All`,
  `Deny All`, `FRSTR-ALLOW-HL7`, `FRSTR-ALLOW-DICOM`, `FRSTR-BMS-MODBUS`,
  or `FRSTR-QUARANTINE`

### Demo is live

The full demo is running in CCC. Continue to
[Lifecycle scenarios](#lifecycle-scenarios) for the eight walkthroughs an
analyst can demonstrate.

---

## Lifecycle scenarios

Eight independently replayable scenarios. Run them in order for a full
walkthrough, or pick any single scenario to demonstrate a specific lifecycle
operation. Each scenario includes the goal, numbered steps, expected outcome,
CCC verification, and reset instructions.

### Scenario 1: Bootstrap

See [Quick start, step 3: Bootstrap the demo](#bootstrap-the-demo) and
[The bootstrap step](#the-bootstrap-step) for the complete click-by-click
walkthrough and technical detail.

---

### Scenario 2: Add a multi-source Policy Group via PR

**Goal:** Add a new PG `PACS-ARCHIVES` to demonstrate the multi-source-OR
classification model.

**Steps (GitHub web UI, no terminal needed):**

1. Open `policy-groups.yaml` in the browser:
   `https://github.com/<owner>/<repo>/blob/main/policy-groups.yaml`

2. Click the pencil icon (top-right of the file view) to open the web editor.

3. Scroll to the end of the `policy_groups:` list. Place the cursor on a fresh blank line, then copy and paste the block at the bottom of this scenario (the un-indented block immediately under "**Block to paste**" below).

> **Indentation matters.** The dash before `name:` should land at column 3 (2 spaces). Field keys (`description:`, `type:`, etc.) should land at column 5 (4 spaces). If GitHub's web editor flattens leading whitespace on paste, eyeball the existing PGs in the file — every field after the first PG (`INFUSION-PUMPS`) shows the correct depth. If your pasted block looks shallower than the existing entries, select the field lines and add 2 more leading spaces.

4. Click **Commit changes...** (top-right). In the dialog:
   - Commit message: `Add PACS-ARCHIVES PG`
   - Extended description (optional): `Multi-source PG for PACS imaging archives.`
   - Select **Create a new branch for this commit and start a pull request**
   - Branch name: `add-pacs-archives`
   - Click **Propose changes**

5. The PR creation page opens. Confirm the title and click **Create pull
   request**.

6. Watch the PR. The **PR Preview** workflow runs and posts a sticky comment
   showing the new PG, its 3 OR condition blocks, and security level.

5. Merge the PR.

6. `apply.yml` runs automatically on the merge. Click the **Actions** tab to
   confirm the run completes with a green check.

**Expected result:** 1 new PG `PACS-ARCHIVES` in CCC, carrying the
`FORRESTER-DEMO` label.

**Verify in CCC:** Policy > Policy Groups list now shows 9 demo PGs
including `PACS-ARCHIVES`.

**Reset:** Run the revert workflow (Scenario 7) with PG name `PACS-ARCHIVES`.

**Block to paste** (everything between the fences, exactly as shown):

```yaml
  - name: PACS-ARCHIVES
    description: |
      Picture Archiving and Communication Servers, DICOM image stores.
    type: DYNAMIC
    genre: IT
    security_level: 3
    auto_lock_devices: false
    labels: [FORRESTER-DEMO]
    match:
      condition_blocks:
        - conditions:
            - { attribute: core.normalizedClass, operator: EQ, values: ["Server Appliance and Storage"] }
        - conditions:
            - { attribute: medigate.deviceClass, operator: EQ, values: ["Imaging"] }
        - conditions:
            - { attribute: core.label, operator: EQ, values: ["PACS-ARCHIVES"] }
```

---

### Scenario 3: Update PG match criteria via PR

**Goal:** Tighten classification on `EHR-SERVERS` by adding a second connector
signal (CrowdStrike trust) to Block 2.

**Steps (GitHub web UI, no terminal needed):**

1. Open `policy-groups.yaml` in the browser:
   `https://github.com/<owner>/<repo>/blob/main/policy-groups.yaml`

2. Click the pencil icon (top-right) to open the web editor. Find the `EHR-SERVERS` entry, locate Block 2 (the single `core.trustAttributes CONTAINS "Known in ServiceNow"` condition), and add a second `core.trustAttributes` condition for `"Known in CrowdStrike"` inside the same conditions list. The before/after snippets are at the bottom of this scenario.

> **Indentation matters.** The dash before `conditions:` should land at column 9 (8 spaces), and the dash before `{ attribute: ... }` at column 13 (12 spaces). Match what's already there for the other PGs.

3. Click **Commit changes...** (top-right). In the dialog:
   - Commit message: `Tighten EHR-SERVERS: require ServiceNow AND CrowdStrike trust`
   - Extended description (optional): `Block 2 now requires both ServiceNow and CrowdStrike trust attributes.`
   - Select **Create a new branch for this commit and start a pull request**
   - Branch name: `ehr-tighten-trust`
   - Click **Propose changes**

4. The PR creation page opens. Click **Create pull request**. The preview
   comment shows the criteria diff: one new condition added to `EHR-SERVERS`
   Block 2.

5. Click **Merge pull request** > **Confirm merge**. `apply.yml` runs on the
   merge and updates the PG in CCC.

**Expected result:** `EHR-SERVERS` PG now requires BOTH trust attributes when
the connector signal is the discriminator.

**Verify in CCC:** Policy > Policy Groups > click `EHR-SERVERS` > Match
Criteria > Block 2 shows two AND-ed conditions.

**Reset:** Revert the merge commit, or push a follow-up PR restoring Block 2
to the original single ServiceNow condition.

**Before** (the existing Block 2 in `EHR-SERVERS`):

```yaml
        - conditions:
            - { attribute: core.trustAttributes, operator: CONTAINS, values: ["Known in ServiceNow"] }
```

**After** (add the second condition inside the same conditions list, AND-ed):

```yaml
        - conditions:
            - { attribute: core.trustAttributes, operator: CONTAINS, values: ["Known in ServiceNow"] }
            - { attribute: core.trustAttributes, operator: CONTAINS, values: ["Known in CrowdStrike"] }
```

---

### Scenario 4: Attach a security profile to a policy via PR

**Goal:** Change the `IMAGING > EHR-SERVERS` policy from `FRSTR-ALLOW-DICOM`
to `FRSTR-ALLOW-HTTPS` (e.g., the imaging system migrated to a web-based
PACS).

**Steps (GitHub web UI, no terminal needed):**

1. Open `policies.yaml` in the browser:
   `https://github.com/<owner>/<repo>/blob/main/policies.yaml`

2. Click the pencil icon (top-right) to open the web editor. Find the
   `IMAGING-to-EHR-SERVERS` entry and change:

   ```yaml
   security_profile: FRSTR-ALLOW-DICOM
   ```

   to:

   ```yaml
   security_profile: FRSTR-ALLOW-HTTPS
   ```

3. Click **Commit changes...** (top-right). In the dialog:
   - Commit message: `IMAGING>EHR-SERVERS: swap DICOM for HTTPS`
   - Extended description (optional): `Imaging migrated to web-based PACS; switch from DICOM to HTTPS profile.`
   - Select **Create a new branch for this commit and start a pull request**
   - Branch name: `imaging-ehr-https`
   - Click **Propose changes**

4. The PR creation page opens. Click **Create pull request**. The preview
   comment shows the security_profile diff with before/after profile names
   and port differences.

5. Click **Merge pull request** > **Confirm merge**. `apply.yml` runs and
   updates the policy in CCC.

**Expected result:** The `IMAGING > EHR-SERVERS` policy now references
`FRSTR-ALLOW-HTTPS` instead of `FRSTR-ALLOW-DICOM`.

**Verify in CCC:** Policy > Policy Sets > `FRSTR-HOSPITAL` > click
`IMAGING > EHR-SERVERS` > securityProfileName = `FRSTR-ALLOW-HTTPS`.

**Reset:** Revert the merge commit or push a follow-up PR changing the
profile back to `FRSTR-ALLOW-DICOM`.

---

### Scenario 5: Drift detection, manual and scheduled

**Goal:** Show that drift between CCC live state and the YAML source of truth
is detected hourly and on demand. Demonstrate by manually editing a PG in the
CCC UI, then triggering the drift check.

**Steps:**

1. In the CCC UI, navigate to Policy > Policy Groups. Click `IMAGING`.
   Click **Edit**. Change the description to anything (e.g., append
   "DRIFT TEST"). Click **Save**.

   This introduces drift: CCC now differs from the YAML in this repo.

2. In GitHub, click the **Actions** tab. In the left sidebar, click
   **Drift Check**.

3. Click **Run workflow** (branch `main`, no inputs needed). Click
   **Run workflow**.

4. Watch the run. `drift.py` compares every declared object against CCC live
   state and reports the divergence.

5. When drift is found, the workflow opens (or updates) a GitHub issue titled
   "CCC drift detected" with the `drift` label. The issue body shows the
   specific fields that differ.

6. Fix the drift by either:
   - **(a)** Reverting the manual change in the CCC UI (edit `IMAGING` back
     to its original description), or
   - **(b)** Updating `policy-groups.yaml` in a PR to match the new CCC state.

7. Re-run the **Drift Check** workflow. If CCC and YAML now match, the
   workflow closes the drift issue automatically with a comment.

**Expected result:** Drift issue opened after step 3, closed after step 7.

**Verify:** GitHub Issues tab shows the drift issue created and then closed.

**Reset:** No reset needed. Either option in step 6 restores sync.

> **Note:** `drift-check.yml` also runs on a cron schedule (every hour at
> minute 17). In production, the hourly run catches out-of-band changes
> without manual intervention.

---

### Scenario 6: Promote to enforcement (release tag)

**Goal:** Show the GitOps audit trail of moving all policies from
`MONITOR_ONLY` to `MONITOR_AND_ENFORCE`.

**Steps (GitHub web UI, no terminal needed):**

1. From the repo home page, click the **Releases** link in the right sidebar
   (or navigate to `https://github.com/<owner>/<repo>/releases`).

2. Click **Draft a new release**.

3. **Choose a tag** dropdown > type `v1.0.0` > select **Create new tag:
   v1.0.0 on publish**.

4. **Target** dropdown: confirm `main`.

5. **Release title**: `Promote to enforcement`

6. Description (optional): `Flip all 36 policies in FRSTR-HOSPITAL from MONITOR_ONLY to MONITOR_AND_ENFORCE.`

7. Click **Publish release**.

8. The **Promote to enforcement** workflow (`promote.yml`) fires automatically
   on the publish event. Click the **Actions** tab and watch the run. When
   the job finishes, the workflow appends a promotion summary to the release
   body (visible back on the Releases page).

**Expected result:** All 36 policies in `FRSTR-HOSPITAL` flip from
`MONITOR_ONLY` to `MONITOR_AND_ENFORCE`.

**Verify in CCC:** Policy > Policy Sets > `FRSTR-HOSPITAL` > policies show
`MONITOR_AND_ENFORCE` state.

**Reset:** No built-in demote workflow exists yet. To revert, manually edit
each policy back to `MONITOR_ONLY` in the CCC UI, or write a demote script
as future work.

---

### Scenario 7: Revert a single Policy Group

**Goal:** Remove a single PG declaratively without tearing down the whole demo.

**Steps:**

1. Click the **Actions** tab. In the left sidebar, click
   **Revert (remove a Policy Group)**.
2. Click **Run workflow**.
3. In the `pg_name` field, type the PG name (e.g., `PACS-ARCHIVES`).
4. In the `reason` field, type a reason (e.g., `Demo cleanup`).
5. Click **Run workflow**.

The workflow opens a PR against `main` that removes the named PG from
`policy-groups.yaml` and removes any policies referencing it from
`policies.yaml`.

6. Wait for the **PR Preview** comment to land on the PR. Review the diff.
7. Merge the PR.
8. `apply.yml` runs on the merge. The reconcile step detects the YAML-to-CCC
   delta and deletes the PG (and its policies) from CCC.

**Expected result:** PG removed from both YAML files and from CCC.

**Verify in CCC:** Policy > Policy Groups > the removed PG is no longer
listed.

**Reset:** Add the PG back via Scenario 2.

---

### Scenario 8: Full cleanup

**Goal:** Tear down ALL demo objects to leave the tenant clean. CORK and
Default content survives.

**Steps:**

1. Click the **Actions** tab. In the left sidebar, click
   **Cleanup demo state**.
2. Click **Run workflow**. Select branch `main`.
3. In the `confirm` field, type `CLEANUP-FORRESTER-DEMO` exactly.
4. Click **Run workflow**.

The cleanup script (`bin/cleanup_demo.py`) deletes in dependency order:

1. All non-reflection policies inside `FRSTR-HOSPITAL` (CCC auto-deletes
   reflection pairs when their parent policy is removed)
2. The `FRSTR-HOSPITAL` policy set (after clearing its scope via PUT)
3. Every Policy Group carrying the `FORRESTER-DEMO` label
4. Every Security Profile whose name starts with `FRSTR-` (skips
   CCC-managed reflection SPs)
5. The `FORRESTER-DEMO` PG label

**Expected log output** (visible in the workflow job summary):

```
## 🧹 Cleanup -- Forrester demo teardown
**Scope:** PG label `FORRESTER-DEMO` + name prefix `FRSTR-*` + policy set `FRSTR-HOSPITAL`
Deleted N object(s):
- Policy   `INFUSION-PUMPS > EHR-SERVERS`
  ... (one line per primary policy)
- PolicySet `FRSTR-HOSPITAL`
- PG       `INFUSION-PUMPS`
  ... (one line per PG)
- SP       `FRSTR-ALLOW-DICOM`
  ... (one line per custom SP)
- PGLabel  `FORRESTER-DEMO`
```

**Verify in CCC:**

- Policy > Policy Sets: no `FRSTR-HOSPITAL`
- Policy > Policy Groups: no PGs with the `FORRESTER-DEMO` label
- CORK PGs (9 of them): still present
- Default policy set: untouched

**Reset:** Run Scenario 1 (bootstrap), merge the cache PR, and let
`apply.yml` run to recreate the full demo from scratch.

---

## The bootstrap step

Detailed walkthrough of the one-time setup. Run this before any other
scenario. For the click-by-click steps, see
[Quick start: Bootstrap the demo](#bootstrap-the-demo).

**Prerequisites:**

- Repository secrets configured: `CCC_URL`, `CCC_CLIENT_ID`,
  `CCC_CLIENT_SECRET` (see [Required GitHub configuration](#required-github-configuration))
- Self-hosted runner online (see [Self-hosted runner](#self-hosted-runner))

**What bootstrap does internally:**

1. Authenticates to CCC via OAuth2 client credentials
2. Looks up the PG label `FORRESTER-DEMO` by name; creates it if missing
3. Looks up the policy set `FRSTR-HOSPITAL` by name; creates it if missing,
   with `state: MONITOR_ONLY` and `site_labels: [Hospital]`
4. For each of the 6 security profiles in `security-profiles.yaml`: looks
   up by name, creates if missing
5. Opens an auto-PR that writes the resolved CCC object IDs into
   `inventory/group_vars/all.yml`

When the job finishes (green check), merge the auto-PR. This caches the
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
3 clinical-specific workflows (HL7/DICOM), 2 trusted-zone permit-all pairs,
and 23 explicit deny-all pairs. See [The policy matrix](#the-policy-matrix)
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
│   └── cleanup_demo.py             <- full demo teardown (v2)
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

### Repository secrets (`Settings` > `Secrets and variables` > `Actions`)

- `CCC_URL`: Cloud Control Center base URL
  (e.g., `https://insights-demo.idp01.elisity.io`)
- `CCC_CLIENT_ID`: OAuth2 service-account client ID
- `CCC_CLIENT_SECRET`: OAuth2 service-account client secret

### Workflow permissions (`Settings` > `Actions` > `General`)

Under **Workflow permissions**, enable:

- **Read and write permissions** (so workflows can push branches and open PRs)
- **Allow GitHub Actions to create and approve pull requests** (required by
  `bootstrap.yml` and `revert.yml`, which open auto-PRs)

### Environment (`Settings` > `Environments`)

Create one named **`insights-demo`**. Attach the three secrets above.
Optionally add a required reviewer to gate `apply.yml` and `promote.yml`
runs on a human approval click.

### Branch protection (`Settings` > `Branches` > `main`)

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
prefix. `cleanup_demo.py` uses this prefix as its deletion filter for
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
