# Elisity Microsegmentation — GitOps Demo

A live, GitHub-hosted demo of Elisity Cloud Control Center being driven
**entirely from outside the UI**, through every step a real customer's
DevSecOps pipeline would take: pull request → preview → merge → apply →
release tag → enforce → continuous drift reconciliation → revert.

Built for analyst demonstrations of Forrester Wave Strategy Q19:

> *"To what extent can the provisioning and on-going operation of the
> solution be automated and orchestrated? How well does it align to
> modern practices such as DevSecOps and GitOps? To what extent can the
> solution be integrated with provisioning, automation, orchestration,
> and/or development pipelines and tooling (e.g., Ansible, Terraform,
> Argo, Jenkins)?"*

## What this demo answers

| Sub-question | How the repo answers it |
|---|---|
| **Provisioning automation** | Merging a PR creates Policy Groups + Policies in CCC from declarative YAML. Zero clicks. |
| **Ongoing operation automation** | Hourly drift check workflow detects out-of-band changes and opens a GitHub issue. Self-healing on the next merge via the reconcile step. |
| **DevSecOps alignment** | Every change is a PR. Every PR gets an automated impact preview. Branch protection means human review *and* automated simulation before any change reaches CCC. |
| **GitOps alignment** | Git is source of truth. Merge = deployment. Tag = production promotion. Drift = issue. Removing a YAML entry deletes from CCC (two-way reconcile). |
| **Integration breadth** | Same single operation expressed in Ansible (primary), Terraform, curl, Python, Argo CD, Jenkins, GitLab CI. None use a proprietary CLI or SDK — every example hits the same open REST API. |
| **Library size** | The library *is* the API: 436 endpoints across 73 categories. Anything that speaks HTTPS+JSON is a supported client. |

---

# Demo Runbook — live analyst session

The exact click-by-click sequence. **Total runtime ≈ 10 minutes.**

Everything below happens in a browser. Two tabs the whole time:

- **Tab A** — GitHub repo: https://github.com/mkorenbaum/Elisity-automation-playbook
- **Tab B** — CCC UI: https://insights-demo.idp01.elisity.io

Open both before walking in.

## Pre-demo prep (do once, ~30 sec before starting)

1. **Tab A** → Actions tab → **`Cleanup demo state`** → **Run workflow** → leave defaults → **Run workflow**.
   Wait ~20 seconds for the green check. This guarantees a clean tenant slate before the analyst sees anything.
2. **Tab B** → log in to CCC → navigate to Policies → Policy Groups view. Should show no `forrester-demo-*` entries.

## Step 1 — Show the source of truth (30 sec)

**Click:** Tab A → repo home.

**Show, in order:**
- `policy-groups.yaml` — open the file. *"This is the source of truth. Two entries, both Dynamic Policy Groups, classified by hostname pattern. Nothing else describes our segmentation state."*
- `policies.yaml` — open. *"And the policies between groups, with monitor mode and security profile."*
- `.github/workflows/` — open the directory listing. *"Five workflows wire this repo to the CCC tenant: preview on PR, apply on merge, promote on release, drift check hourly, manual revert."*
- `examples/` — open the directory. *"And the same operation expressed in Terraform, curl, Python, Argo, Jenkins, GitLab CI — to demonstrate the integration is tooling-agnostic. We'll use Ansible today."*

## Step 2 — Open a PR adding a new Policy Group (90 sec)

**Click:** Tab A → `policy-groups.yaml` → pencil icon (top right).

**Paste at the end of the file** (matching the existing 2-space indent):

```yaml
  - name: forrester-demo-pacs
    description: |
      PACS imaging archive workstations classified by hostname pattern.
      Added via PR to demonstrate the GitOps preview gate.
    type: DYNAMIC
    security_level: 3
    auto_lock_devices: false
    match:
      attribute: core.hostname
      operator: CONTAINS
      match_values:
        - PACS
```

**Click:** **Commit changes...** → in the modal:
- Commit message: `Add forrester-demo-pacs Policy Group`
- Radio: **Create a new branch for this commit and start a pull request**
- Branch name: `add-pacs-pg`
- Click **Propose changes**.

GitHub opens the "Open a pull request" page. **Click Create pull request.**

## Step 3 — Preview comment lands (~45 sec, narrate while waiting)

You're on the PR page. The preview workflow is queued.

**While you wait, talk to:**

- *"This is the DevSecOps gate. Every change to segmentation policy is a PR. The preview workflow is reading the diff between this PR and main, then posting an automated impact analysis."*
- *"It's the same gate enterprises already use for Kubernetes manifests, Terraform plans, application code. Nothing here is Elisity-specific tooling — it's GitHub Actions reading our open YAML schema."*

**Refresh the Conversation tab** when the green check appears. The `github-actions[bot]` comment shows up:

> 🔍 *PR Preview — Elisity Microsegmentation*
> *This PR proposes 1 change. Will create `forrester-demo-pacs` (Dynamic, SL-3, hostname CONTAINS PACS). Mode: MONITOR_ONLY.*

**Talk to:** *"That comment was generated by a 100-line Python script reading both YAML files. The same script could call the CCC simulator API to count exactly how many devices would be affected — that's the next iteration."*

## Step 4 — Merge (30 sec)

**Click:** **Merge pull request** → **Confirm merge** → **Delete branch**.

## Step 5 — Apply runs (~60-90 sec)

**Click:** Tab A → **Actions** tab. The **`Apply to CCC`** workflow is now running.

**Click into the run.** You see the live job log: token acquisition, Ansible play running, reconcile step at the end.

**While you wait, talk to:**

- *"Same Ansible playbook a customer would run from their CI runner. Authentication is OAuth2 client credentials against the CCC IdP. The runner is on Mike's lab so it routes to insights-demo's internal IP — in a real customer this would be their own runner inside their network."*
- *"Apply has two halves: create-if-missing for what's in YAML, then a reconcile step that deletes anything in CCC matching our prefix that's no longer declared. That makes apply two-way."*

When the job finishes (green check), navigate back to the merged PR. A new comment from `github-actions[bot]`:

> 🚀 *Applied to Elisity (`MONITOR_ONLY`)*
> *Source-of-truth: `<commit-sha>`. Tenant: `insights-demo.idp01.elisity.io`*
> *Reconcile: ✅ No orphans. Repo and CCC are aligned.*

## Step 6 — Switch to CCC UI to see live state (30 sec)

**Click:** Tab B → refresh → Policy Groups view.

**Show:**
- `forrester-demo-pacs` is now in the list. Click it.
- Description matches the YAML.
- Security level is SL-3.
- Classification is `core.hostname CONTAINS PACS`.

**Talk to:** *"From the analyst seat: the policy that exists in CCC right now came from a PR they could have reviewed and approved themselves. Git history is the audit trail."*

## Step 7 — Cut a release tag → promote to enforcement (~60 sec)

**Click:** Tab A → repo home → right sidebar **Releases** → **Draft a new release**.

- **Choose a tag** → type `v1.0.0` → "Create new tag: v1.0.0 on publish"
- **Release title:** `Initial enforcement promotion`
- **Description:** *(leave empty)*
- Click **Publish release**.

**Click:** Actions tab → **`Promote to enforcement`** workflow → into the running job.

**While you wait, talk to:** *"Tagging a release is the production-promotion event. The promote workflow walks every policy in `MONITOR_ONLY` and PUTs it back as `MONITOR_AND_ENFORCE`. Idempotent — running it twice is a no-op."*

When it finishes (~30 sec), refresh the release page. The body now has a *🚀 Policy Promotion* appendix listing what was promoted.

**Click:** Tab B → refresh the Policy detail. Mode is now `MONITOR_AND_ENFORCE`.

## Step 8 — Show drift detection (~30 sec)

**Click:** Tab A → Actions tab → **`Drift Check`** in the left sidebar.

**Show:**
- The runs list — runs every hour.
- Click the latest one → "✅ No drift. Repo and CCC are aligned."

**Talk to:** *"This is the continuous reconciliation half. Every hour, the workflow walks CCC's API and diffs against the YAML in main. If a human changed a policy in the UI without a PR, this opens an issue with a field-by-field diff. When the drift is fixed, the issue auto-closes."*

**Optional bonus** *(if analyst is curious)*: Click into Issues → search the `drift` label. *"And here's where any open drift issues would land. Today, none."*

## Step 9 — Revert via the UI (~90 sec)

**Click:** Tab A → Actions tab → **`Revert (remove a Policy Group)`** → **Run workflow** dropdown.

- **`pg_name`:** leave default `forrester-demo-pacs`
- **`reason`:** type `Demo cleanup`
- Click **Run workflow**.

**Click into the running job.** When it finishes (~10 sec) the Summary tab shows:

> 📤 *Revert PR opened*
> *PR: #N Revert: remove `forrester-demo-pacs`*

**Click that PR link.** A new auto-generated PR is open. The diff shows `- forrester-demo-pacs` removed from `policy-groups.yaml`.

The preview comment lands within 30 seconds:

> 🔍 *PR Preview*
> *➖ Removed: `forrester-demo-pacs`*

**Click:** **Merge pull request** → **Confirm merge**.

The apply workflow runs. The reconcile step inside apply detects that `forrester-demo-pacs` is no longer in YAML but still in CCC, and **deletes it from CCC**.

**Click:** Tab B → refresh Policy Groups. `forrester-demo-pacs` is gone.

**Talk to:** *"Pure UI loop. The analyst — or any reviewer — can deprecate any policy without ever touching a terminal or even reading YAML if they don't want to. The revert workflow handles the file edit, opens the PR, and the apply workflow handles the actual CCC deletion."*

## Step 10 — Close (30 sec)

Switch back to the repo home and walk the integration table:

- *"Today we did this in Ansible. The `terraform/` directory has the same operation as Terraform code. The `examples/` directory has the same operation as curl, Python, Argo CD, Jenkins, and GitLab CI. The library is the API: 436 endpoints, JSON over HTTPS. Anything that speaks that talks to Elisity."*

---

## Quick reset between dry-runs

```
Tab A → Actions → "Cleanup demo state" → Run workflow → defaults → Run.
```

That deletes everything matching `forrester-demo-*` from the tenant. Re-run **Step 2** onward.

---

## Workflow cheatsheet (URLs to bookmark)

| Workflow | Trigger | URL |
|---|---|---|
| PR Preview | PR opened/updated | _automatic_ |
| Apply to CCC | Push to main | _automatic_ |
| Promote to enforcement | Release published | _automatic_ |
| Drift Check | Hourly + manual | https://github.com/mkorenbaum/Elisity-automation-playbook/actions/workflows/drift-check.yml |
| Cleanup demo state | Manual | https://github.com/mkorenbaum/Elisity-automation-playbook/actions/workflows/cleanup.yml |
| Revert (remove a PG) | Manual | https://github.com/mkorenbaum/Elisity-automation-playbook/actions/workflows/revert.yml |

---

## Repo layout

```
.
├── README.md                       ← you are here
├── Makefile                        ← contract: make demo / make ci-apply / make cleanup / …
├── creds.yml.example
├── policy-groups.yaml              ← declarative Policy Groups (source of truth)
├── policies.yaml                   ← declarative Policies (source of truth)
├── inventory/group_vars/all.yml    ← tenant-specific IDs + URL normalization
├── playbooks/
│   ├── _auth.yml                   ← OAuth client_credentials → /tmp/.ccc_token
│   ├── 00-list-connectors.yml      ← read-only proof of life
│   ├── 01-policy-groups.yml        ← apply policy-groups.yaml
│   ├── 02-policies.yml             ← apply policies.yaml
│   ├── 03-verify.yml               ← re-fetch live state
│   └── 99-cleanup.yml              ← teardown (Ansible)
├── bin/
│   ├── ccc.py                      ← Python stdlib HTTP helper (urllib + json)
│   ├── preview.py                  ← PR preview report
│   ├── promote.py                  ← MONITOR_ONLY → MONITOR_AND_ENFORCE
│   ├── drift.py                    ← live state vs main YAML diff
│   ├── reconcile.py                ← deletes CCC orphans not in YAML
│   └── cleanup_by_prefix.py        ← prefix-scoped wipe (used by Cleanup workflow)
├── .github/workflows/
│   ├── preview.yml                 ← runs on PR
│   ├── apply.yml                   ← runs on push to main (apply + reconcile)
│   ├── promote.yml                 ← runs on release published
│   ├── drift-check.yml             ← runs hourly
│   ├── cleanup.yml                 ← manual
│   └── revert.yml                  ← manual: opens revert PR
├── terraform/                      ← parallel IaC implementation
└── examples/                       ← curl, python, argo, jenkins, gitlab-ci
```

---

## Local development (Mac, optional)

For development against the same flow CI runs:

```bash
brew install ansible

cp creds.yml.example creds.yml
# edit creds.yml with CCC URL / client id / secret

make demo        # full apply against the live tenant
make cleanup     # tear down
```

`creds.yml` is git-ignored. Trailing slash on `ccc_url` is fine — playbooks normalize it via the `ccc_base` fact in `inventory/group_vars/all.yml`.

---

## Required GitHub configuration (one-time setup)

For the workflows to run, the repo needs:

### Repository secrets (`Settings → Secrets and variables → Actions`)

- `CCC_URL` — Cloud Control Center base URL (e.g., `https://insights-demo.idp01.elisity.io`)
- `CCC_CLIENT_ID` — OAuth2 service-account client ID
- `CCC_CLIENT_SECRET` — OAuth2 service-account client secret

### Environment (`Settings → Environments`)

Create one named **`insights-demo`**. Attach the three secrets above. Optionally add a required reviewer to gate `apply.yml` / `promote.yml` runs on a human approval click.

### Branch protection (`Settings → Branches → main`)

- Require a pull request before merging.
- Require status check `preview` to pass.

### Self-hosted runner

`insights-demo` is on Elisity's internal network and unreachable from GitHub-hosted runners. The CCC-touching workflows (`apply`, `promote`, `drift`, `cleanup`, `revert`) declare `runs-on: self-hosted` and dispatch to a runner registered on Mike's lab host (`elisity-host-10-0-0-175`). The runner is started from `/home/elisity/github-runners/automation-playbook/run.sh` on `10.0.0.175`. After a host reboot, restart with:

```bash
ssh elisity@10.0.0.175 'cd /home/elisity/github-runners/automation-playbook && nohup ./run.sh > runner.log 2>&1 &'
```

---

## What's intentionally scoped out

- **In-place Policy *update***: workflows are create-if-missing on attributes (description / match criteria / security level). Changing those today requires the cleanup → re-apply path. Production-grade PUT-with-diff is one Ansible task away.
- **Multi-environment promotion** (dev/staging/prod tenants): single tenant for clarity. Pattern extends with workflow matrix + per-env secrets.
- **Native Terraform provider**: examples use the generic `Mastercard/restapi` provider against Elisity's REST API. A purpose-built `provider-elisity` would be a productization, not a demo concern.

The plumbing under the demo (`bin/ccc.py`) talks to 436 CCC endpoints without modification — every other capability is API-callable today.
