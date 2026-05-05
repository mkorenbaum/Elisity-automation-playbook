# Elisity Microsegmentation — GitOps Demo

A live, GitHub-hosted demo of Elisity Cloud Control Center being driven
**entirely from outside the UI**, through every step a real customer's
DevSecOps pipeline would take: pull request → preview → merge → apply →
release tag → enforce → continuous drift reconciliation.

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
| **Provisioning automation** | `make demo` (or merge a PR) creates Policy Groups + Policies in CCC from declarative YAML. Zero clicks. |
| **Ongoing operation automation** | Hourly drift check workflow detects out-of-band changes and opens an issue. Self-healing on next merge. |
| **DevSecOps alignment** | Every change is a PR. Every PR gets an automated impact preview. Branch protection means human review *and* automated simulation before any change reaches CCC. |
| **GitOps alignment** | Git is source of truth. Merge = deployment. Tag = production promotion. Drift = issue. The same loop GitOps tools (Argo, Flux) provide for Kubernetes — applied to network segmentation. |
| **Integration breadth** | Same single operation expressed in Ansible (primary), Terraform (parallel module), curl, Python, Argo CD, Jenkins, GitLab CI. None use a proprietary CLI or SDK — every example hits the same open REST API. |
| **Library size** | The library *is* the API: 436 endpoints across 73 categories. Anything that speaks HTTPS+JSON is a supported client. |

## The 10-minute demo (browser only)

> All of these happen in a browser. No terminal, no SSH, no laptop env
> setup. The Forrester analyst sees real-world DevSecOps in action.

### 1 — Open a pull request

Edit `policies.yaml` to add a new policy. Push to a branch. Open a PR
against `main`.

### 2 — `preview.yml` runs automatically

GitHub Actions:
- Diffs the PR's YAML against `main`.
- Posts a sticky comment on the PR:
  > 🔍 *This PR proposes 1 change. Will create `forrester-demo-pacs`
  > Policy Group with hostname pattern `PACS`. Mode: `MONITOR_ONLY`.*

The reviewer sees exactly what the change will do *before* the merge
button is even available.

### 3 — Merge

Branch protection requires the PR review and the preview check to pass.
Once merged, `apply.yml` runs:

- Renders `creds.yml` from repository secrets.
- Calls `make ci-apply` — the same `make demo` Ansible workflow that
  runs locally.
- Posts a comment on the merged PR:
  > 🚀 *Applied to insights-demo. Created Policy Group `xyz-uuid` and
  > Policy `abc-uuid` in `MONITOR_ONLY`.*

Switch tabs to the CCC UI. The new objects are there.

### 4 — Tag a release

Cut release `v1.2.0`. `promote.yml` runs:

- Reads `policies.yaml`.
- For every policy in `MONITOR_ONLY`, PUTs it back as `MONITOR_AND_ENFORCE`.
- Appends a summary to the GitHub release body.

The release page is now the audit trail of *what was promoted to
enforcement and when, by whom*. Roll back? Re-tag the previous version
and re-run the workflow.

### 5 — Continuous reconciliation

`drift-check.yml` runs hourly. If the CCC live state drifts from the
declared YAML in `main` — somebody changed a policy in the UI, or a PG
got deleted out-of-band — the workflow opens (or updates) an issue
titled "🔁 CCC drift detected" with a field-by-field diff. When the
drift is resolved, the issue closes itself with a comment.

### 6 — Tooling tour (15 seconds each)

Open these from the GitHub UI to show the analyst that **the integration
is tooling-agnostic** — Ansible is just one option:

- [`terraform/`](terraform/) — Same operation as a parallel Terraform
  module using the Mastercard/restapi provider.
- [`examples/curl-one-liner.sh`](examples/curl-one-liner.sh) — The
  thinnest possible client: 4 lines of shell.
- [`examples/python-direct.py`](examples/python-direct.py) — Pure stdlib
  Python (no SDK, no requests).
- [`examples/argocd-application.yaml`](examples/argocd-application.yaml) —
  Argo CD Application + Job hook.
- [`examples/Jenkinsfile`](examples/Jenkinsfile) — Declarative Jenkins
  pipeline using the same `make ci-*` targets.
- [`examples/.gitlab-ci.yml`](examples/.gitlab-ci.yml) — GitLab CI
  mirror of the GitHub Actions workflows.

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
│   └── 99-cleanup.yml              ← teardown
├── bin/
│   ├── ccc.py                      ← Python stdlib HTTP helper (urllib + json)
│   ├── preview.py                  ← PR preview report
│   ├── promote.py                  ← MONITOR_ONLY → MONITOR_AND_ENFORCE
│   └── drift.py                    ← live state vs main YAML diff
├── .github/workflows/
│   ├── preview.yml                 ← runs on PR
│   ├── apply.yml                   ← runs on push to main
│   ├── promote.yml                 ← runs on release published
│   └── drift-check.yml             ← runs hourly
├── terraform/                      ← parallel IaC implementation
└── examples/                       ← curl, python, argo, jenkins, gitlab-ci
```

---

## Local development (Mac)

For development against the same flow CI runs:

```bash
brew install ansible

cp creds.yml.example creds.yml
# edit creds.yml with CCC URL / client id / secret

make demo        # the analyst-facing run
make cleanup     # tear down between demos
```

`creds.yml` is git-ignored. The trailing slash on `ccc_url` is fine —
the playbooks normalize it via the `ccc_base` fact in
`inventory/group_vars/all.yml`.

---

## Required GitHub configuration

For the four workflows to run against your tenant, the repo must have:

### Repository secrets (`Settings → Secrets and variables → Actions`)

- `CCC_URL` — Cloud Control Center base URL (e.g., `https://insights-demo.idp01.elisity.io`)
- `CCC_CLIENT_ID` — OAuth2 service-account client ID
- `CCC_CLIENT_SECRET` — OAuth2 service-account client secret

### Environment (`Settings → Environments → New environment`)

Create one named **`insights-demo`**. Optionally add a required reviewer
to gate `apply.yml` / `promote.yml` runs on a human approval. The same
secrets above can be scoped to the environment for tighter blast radius.

### Branch protection (`Settings → Branches → main`)

- Require a pull request before merging.
- Require status check `preview` to pass.
- Optionally require a CODEOWNER review for `policies.yaml` /
  `policy-groups.yaml`.

---

## Why this is the right shape for the question

The Forrester prompt is multi-part — Provisioning, Operation, DevSecOps,
GitOps, Integration breadth, Library size. A single `curl` command (the
literal "show an admin operation from a third-party tool" demo) only
answers two of those.

This repo answers all six in one ~10-minute live walkthrough, using
GitHub as the only surface and Elisity's open API as the substrate.
Every demo step maps to the same loop a customer would run on their
real production fleet — there's nothing show-only here.

---

## What's intentionally scoped out

- Policy *updates*: workflows create-if-missing today. Production-grade
  reconciliation (PUT-with-diff on every reapply) is one Ansible task
  away — same REST API, same auth.
- Multi-environment promotion (dev/staging/prod tenants): single tenant
  for clarity. The pattern extends with workflow matrix + per-env
  secrets.
- Native Terraform provider: examples use the generic
  `Mastercard/restapi` provider against Elisity's REST API. A purpose-built
  `provider-elisity` would be a productization, not a demo concern.

The plumbing under the demo (`bin/ccc.py`) talks to 436 CCC endpoints
without modification — every other capability is API-callable today.
