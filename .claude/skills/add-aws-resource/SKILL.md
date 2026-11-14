---
name: add-aws-resource
description: Steps to add a queue, bucket, schedule or other AWS resource to the OMS across the development repo, the service and, rarely, oms-core. Use when a change needs a new AWS resource or changes one.
---
# Add an AWS resource

Rules: `sa-aws-platform`, `sa-resilience-observability`. Up to three repos change; each gets its own PR.

1. **Terraform** (`repos/development/docker/infra/local/main.tf`): the resource, named by the rule in `sa-aws-platform`.
   A queue gets a dead-letter queue and a visibility timeout longer than the slowest handling of one message.
2. **Local stack**: if LocalStack must run a service it does not run yet, add it in `docker/docker-compose.yml`.
3. **Service**: the configuration key with an environment placeholder, the local value in the `localdev` profile, and the
   adapter behind a port in `infrastructure/`. Set timeouts on the client. A consumer says what makes a redelivery safe.
4. **oms-core only if two services need the same client or type** (system rule 6). That means an oms-core release and a
   `coreVersion` bump first (`/release-core`).
5. **Tests**: what happens when the resource is slow or down, and the dead-letter path.
6. **Docs** (oms-workspace): `architecture/integration.md` if another service is on the other end; `open-questions.md`
   for anything deferred.

Rollout: development (resource exists) → oms-core, if any → service.
