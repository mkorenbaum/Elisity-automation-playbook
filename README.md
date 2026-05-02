# Elisity — Forrester Wave Q19 demo (Ansible)

A small Ansible repo that demonstrates Elisity Cloud Control Center being
driven from outside the UI. Designed to run on a Mac in front of an
analyst.

The demo answers the Forrester Wave Strategy Q19 prompt:

> *"Show an administrative operation initiated from a third-party tool
> (i.e., outside of the solution's admin console/UI)."*

It also exercises the surrounding capabilities — open API, GitOps-style
policy-as-code, idempotent reapply, and clean teardown.

---

## What it does

| Step | Playbook | Action |
|------|----------|--------|
| 1 | `00-list-connectors.yml` | Authenticates to CCC and lists every configured connector — proof the open API works in both directions |
| 2 | `01-policy-groups.yml`   | Reads `policy-groups.yaml` and creates each Policy Group as a Dynamic group with classification rules |
| 3 | `02-policies.yml`        | Reads `policies.yaml` and creates each Policy in **simulation mode** (no enforcement) in the Default Policy Set |
| 4 | `03-verify.yml`          | Re-fetches everything from CCC and prints the live state |
| 99| `99-cleanup.yml`         | Deletes every object the demo created. Run between demos. |

State (object IDs created during the run) is persisted in `.state.json`
between plays and used by cleanup so we never delete anything we didn't
create.

The "GitOps moment" is the YAML files: `policy-groups.yaml` and
`policies.yaml` are the source of truth — open them, edit them in front
of the analyst, re-run `make demo`, switch to the CCC UI, see the
changes.

---

## Mac setup (one-time, ~2 minutes)

```bash
# 1. Install Homebrew (skip if you already have it)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Install Ansible
brew install ansible

# 3. Verify
ansible-playbook --version | head -1
# Should print:  ansible-playbook [core 2.16.x or newer]
```

That's it. No pip, no virtualenv, no Python config required.

---

## Configure the demo (one-time)

```bash
cd ~/forrester-demo-ansible       # or wherever you unzipped the repo
cp creds.yml.example creds.yml
```

Open `creds.yml` and fill in:

```yaml
ccc_url:           "https://your-tenant.elisity.io"
ccc_client_id:     "<your-api-client-id>"
ccc_client_secret: "<your-api-client-secret>"
```

`creds.yml` is gitignored — keep secrets out of source control.

> **zsh users:** the secret contains `!`. Single-quote the value as shown.
> Inside YAML this is fine; only watch out if you ever paste it onto the
> shell command line directly.

---

## Run the demo

### Full happy path
```bash
make demo
```

That runs all four steps in order and ends with verified state. Switch
to the CCC UI (`Policies → Policy Sets → Default`) — the new Policy
Group and Policy will be there.

### Step-by-step (good for an analyst walk-through)
```bash
make connectors      # 1. Open API — list every connector
make policy-groups   # 2. Apply policy-groups.yaml
make policies        # 3. Apply policies.yaml
make verify          # 4. Re-read live state from CCC
```

### Tear down between demos
```bash
make cleanup
```

### List all targets
```bash
make
```

---

## What the analyst should see

1. **Connectors output** lists every connector configured on the tenant
   (Claroty, Armis, CrowdStrike, Defender, ServiceNow, Tenable,
   Microsoft Intune, NetBox, Nozomi, Dragos, Palo Alto, ORDR,
   SentinelOne, SureMDM, plus a Custom Connector). This proves the
   inbound REST API works.

2. **Policy Group create** creates `forrester-demo-imaging` as a
   Dynamic group classified by hostname pattern. The analyst can refresh
   the CCC UI and see it with security level SL-3, the description that
   came from `policy-groups.yaml`, and the live "matched devices" count.

3. **Policy create** creates an allow-all policy from the new group to
   `Unverified Servers Storage` in **simulation mode**. The analyst
   sees a real, evaluable policy — without the risk of an enforcement
   action because `monitorMode: MONITOR_ONLY`.

4. **Verify output** prints live state (IDs, names, types) re-read from
   CCC, so the analyst sees the round-trip succeed end-to-end.

5. **Source of truth is YAML.** Open `policy-groups.yaml` in front of
   the analyst — change the description, change the hostname pattern,
   add a second Policy Group entry. Run `make policy-groups` again.
   That's GitOps for segmentation.

---

## What's deliberately scoped out

This is an analyst demo, not a production deployment harness:

- **Update / drift reconciliation** — playbooks are create-if-missing.
  To change a description you currently `make cleanup` then `make demo`.
  Production-grade Ansible would do PUT-with-diff on every run.
- **Vault / secret management** — `creds.yml` is plaintext. Production
  runs would use `ansible-vault` or pull from a secret store.
- **Multi-tenant** — single CCC URL hard-coded in `creds.yml`.

The same code paths used here scale to the full topology (Sites → DZs →
VE Groups → VEs → VENs) and to bulk policy operations against the same
REST API. None of this requires a proprietary CLI or SDK.

---

## Repo layout

```
forrester-demo-ansible/
├── README.md                      ← you are here
├── Makefile                       ← `make demo` / `make cleanup` / etc.
├── ansible.cfg
├── creds.yml.example              ← copy to creds.yml
├── policy-groups.yaml             ← Git-tracked PG definitions
├── policies.yaml                  ← Git-tracked Policy definitions
├── inventory/
│   ├── hosts.ini                  ← runs everything on localhost
│   └── group_vars/all.yml         ← tenant-specific IDs (PG, PS, SP)
└── playbooks/
    ├── _auth.yml                  ← OAuth client_credentials flow
    ├── 00-list-connectors.yml
    ├── 01-policy-groups.yml
    ├── 02-policies.yml
    ├── 03-verify.yml
    └── 99-cleanup.yml
```

---

## Troubleshooting

### `ansible-playbook: command not found`
Install Ansible: `brew install ansible`

### `Error: 'ccc_validate_certs' is undefined`
You're running plays from the wrong directory. Run from the repo root:
`cd ~/forrester-demo-ansible && make demo`.

### 401 from the token endpoint
- `creds.yml` has the wrong client ID / secret.
- The secret has special chars and was shell-mangled. Make sure the
  value in `creds.yml` is wrapped in double quotes.

### `Policy name "..." has different format than expected.`
Policy names follow the pattern `<source-PG-name> > <destination-PG-name>`
when `isCustomName: false`. If you change the PG name in
`policy-groups.yaml`, also update the policy name in `policies.yaml` to
match.

### Demo objects didn't get cleaned up
Run `make cleanup`. If the `.state.json` file was deleted, you can also
clean up by hand from the CCC UI — every demo object is prefixed
`forrester-demo-`.

---

## How to re-target a different CCC tenant

The IDs in `inventory/group_vars/all.yml` (destination Policy Group,
Policy Set, Security Profile, default label) are tenant-specific. To
point at a different tenant:

1. Update `creds.yml` with the new CCC URL + API client.
2. Pick equivalent objects in the new tenant — any existing PG, the
   Default Policy Set, the built-in Allow All security profile, the
   default PG label.
3. Replace the four IDs in `inventory/group_vars/all.yml`.

A `discover` task that pulls those IDs automatically would be a
straightforward extension if Mike wants it.
