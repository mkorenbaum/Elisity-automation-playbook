# Integration examples

The same single operation — *"create a Policy Group, create a Policy
referencing it, in MONITOR_ONLY mode"* — expressed in every IaC and CI
tool typically deployed in an enterprise.

This directory exists to answer the breadth half of Forrester's question
([Strategy Q19](../README.md#what-this-demo-answers)):

> *"To what extent can the solution be integrated with provisioning,
> automation, orchestration, and/or development pipelines and tooling
> (e.g., Ansible, Terraform, Argo, Jenkins), if at all?"*

Every example below targets the same Elisity REST API. None of them use
a proprietary CLI or SDK. The pattern generalizes to any of the 436
endpoints CCC exposes.

| Tool | File | What it shows |
|---|---|---|
| Ansible (primary) | `../playbooks/` | Full lifecycle — list, create, verify, cleanup |
| Terraform | `../terraform/` | Same operation as a parallel IaC module |
| `curl` | [`curl-one-liner.sh`](curl-one-liner.sh) | The thinnest possible client — a 4-line shell script |
| Python | [`python-direct.py`](python-direct.py) | Stdlib-only Python (no SDK) |
| Argo CD | [`argocd-application.yaml`](argocd-application.yaml) | Argo Application that syncs the YAML → CCC via a Job hook |
| Jenkins | [`Jenkinsfile`](Jenkinsfile) | Declarative pipeline calling `make ci-*` |
| GitLab CI | [`.gitlab-ci.yml`](.gitlab-ci.yml) | The PR / merge / tag pattern in GitLab |

The "library size" question implicit in Forrester's prompt: Elisity's
open API is the library. Anything that can issue an HTTPS request and
parse JSON is a supported client. The seven examples here are
representative, not exhaustive — Bamboo, AWS CodePipeline, Azure DevOps,
Pulumi, Crossplane, and Spinnaker all work the same way.
