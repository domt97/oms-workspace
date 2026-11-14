---
name: sa-aws-platform
description: AWS and local platform rules — S3, SQS, EventBridge, Terraform, LocalStack, SDK clients, naming, credentials. Use when a change needs an AWS resource or touches oms-core cloud config or the development repo.
user-invocable: false
---
# AWS & local platform

## Rules
1. **Infrastructure as code**: every queue, bucket, table, rule and policy is added to Terraform in `development/docker/infra/local` (and later to the real environment's Terraform). No click-ops, no ad-hoc `awslocal` commands that only live in a README.
2. **Naming**: `${profile}-<purpose>` with lowercase and hyphens (valid for S3/SQS/EventBridge). The service reads the name from config with an env override, e.g. `${AWS_SQS_..._QUEUE:localdev-...}`.
3. **Every queue gets a DLQ** (`redrive_policy` with `maxReceiveCount`). Set the visibility timeout above the consumer's maximum processing time, and keep it in one place (if the listener overrides it, say so in both).
4. **Schedules** (EventBridge → SQS) are signals, not work items:
   - consumers re-read state and are idempotent;
   - a tick that arrives late or twice is harmless;
   - the inventory-service#28 pattern applies.
5. **Credentials**:
   - real environments use the default credential chain (IAM role);
   - static keys only for LocalStack and only in the `localdev` profile;
   - never commit real keys;
   - least-privilege IAM per service (its own bucket prefix, its own queues).
6. **Client configuration**:
   - endpoint and region from config, not hard-coded;
   - timeouts and retries set explicitly (see `sa-resilience-observability`);
   - one client bean per AWS service, shared.
7. **Profiles**:
   - the base `application.yaml` must work for a real environment with only env vars;
   - LocalStack endpoints and `test` credentials belong in `application-localdev.yaml`.
8. **S3 layout**: merchant-scoped key prefix (`<merchantId>/<storeId>/...`). Validate the requested key stays inside the caller's prefix. Use lifecycle rules for temporary import files.
9. **Cross-repo change routing**:

   | Change | Repo | Branch |
   |--------|------|--------|
   | Terraform / compose | `development` | `master` only, per workspace CLAUDE.md |
   | Client config | `oms-core` | `master` with a `version` bump (auto-published), then a `coreVersion` bump in the service |
   | Service config | the service | `develop` |
   | Docs | `oms-workspace` (`integration.md`, `system-overview.md`) | — |

## Checklist
- [ ] New resource in Terraform (name pattern, DLQ, visibility, policy) and its output.
- [ ] Config key + env override in the service; localdev value matches Terraform exactly.
- [ ] Credentials via default chain outside localdev; IAM permissions listed.
- [ ] Timeouts/retries for the client; behaviour when the resource is missing or throttled.
- [ ] Merchant scoping of keys/messages; untrusted names/paths validated.
- [ ] Routing table across `development` / `oms-core` / service / workspace.

## Current state and known gaps
Not in this file. When you need how the OMS does this today, or which gaps are known, read
`.claude/skills/sa-aws-platform/references/current-state.md`. It is a snapshot: `architecture/generated/` and the code win.
