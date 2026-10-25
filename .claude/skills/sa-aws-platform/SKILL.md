---
name: sa-aws-platform
description: AWS and local platform in the OMS — S3, DynamoDB, SQS, EventBridge via LocalStack and Terraform, AWS SDK v2 / Spring Cloud AWS client configuration, profiles and naming, credentials, and how to add a new queue, bucket, table or schedule. Use when a change needs AWS resources, touches oms-core cloud config, the development repo (docker-compose, Terraform), or profile-specific settings.
---
# AWS & local platform

## OMS today (verified in code)
**Local infrastructure** (`development/docker/docker-compose.yml`)
- LocalStack 3.8.1 with `SERVICES=s3,dynamodb,sqs,events`.
- Kafka 7.3.0 + ZooKeeper, Schema Registry, Kafka Connect (Debezium) on `:9084`, kafka-ui.
- Postgres 16 with `wal_level=logical`.
- Redis 7 — **no service uses it yet**.

**Terraform** (`development/docker/infra/local/main.tf`; variables `profile` = `localdev`, `region` = `eu-west-1`, `localstack_endpoint`)
- S3 bucket `${profile}-store-products`.
- SQS `${profile}-reservation-expire-queue`, visibility 90 s, **no DLQ**.
- EventBridge rule `${profile}-reservation-expire` with `rate(1 minute)`, targeting that queue, plus the queue policy that allows the rule.
- **No DynamoDB table in Terraform.** `localdev_merchant_info` is created only by scripts outside `development`: `oms-core/localstack/localstack.sh`, `stores-service/localstack/localstack.sh`, `inventory-service/localstack/localstack.sh` (partition key `pk`), and the inventory-service README.
- Those scripts have drifted:
  - they create resources nothing uses (`localdev-product-created-event` and `localdev-store-products-created-queue` queues, an EventBridge bus);
  - `development/localstack/localstack.sh` is a template with test resources only.

**Clients**
- `oms-core` builds the AWS SDK v2 clients:
  - `S3Config` (`aws.region` / `aws.endpoint` / `aws.access-key` / `aws.secret-key` via `AwsProperties`);
  - `DynamoDbConfig` (enhanced client; table from `aws.dynamodb.table.merchant-info`).
- With profile `localdev`, both use LocalStack and static `test`/`test` credentials. **`DynamoDbConfig` hard-codes `http://localhost:4566` and `EU_WEST_1`** for localdev. Otherwise they use the default credential chain, with optional endpoint and static-key overrides.
- inventory-service uses Spring Cloud AWS 3.1.1 for SQS (`spring.cloud.aws.*`, static `test` credentials and the LocalStack endpoint in the **default** `application.yaml`).

**Naming and config drift**
- Queue name is set in `aws.sqs.queues.reservation-expire`, default `localdev-reservation-expire-queue`.
- **The import bucket comes from the request, not from config.**
  - `ProductExcelReader.read(path, fileName)` calls `S3ObjectStorageReader.read(bucket, key)`, so `ImportStoreProductsRequest.path` is used as the **bucket name** and `fileName` as the key.
  - `S3Properties.storeProductBucket` (`aws.s3.store-product-bucket`) is defined but not used.
  - Its localdev value `localdev_store_products` (underscores, not a valid S3 name) also differs from the Terraform bucket `localdev-store-products` (open question 25).
  - Each read also does a `HeadBucket` call first.
- DynamoDB table name defaults differ: stores `merchant_info` (base) / `localdev_merchant_info` (localdev); inventory `localdev_merchant_info`.

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
   - least-privilege IAM per service (its own bucket prefix, its own queues, `GetItem` on `merchant_info`).
6. **Client configuration**:
   - endpoint and region from config, not hard-coded (the localdev branch in `DynamoDbConfig` is a gap);
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
   | Client config | `oms-core` | `master` |
   | Service config | the service | `develop` |
   | Docs | `oms-workspace` (`integration.md`, `system-overview.md`) | — |

## Checklist
- [ ] New resource in Terraform (name pattern, DLQ, visibility, policy) and its output.
- [ ] Config key + env override in the service; localdev value matches Terraform exactly.
- [ ] Credentials via default chain outside localdev; IAM permissions listed.
- [ ] Timeouts/retries for the client; behaviour when the resource is missing or throttled.
- [ ] Merchant scoping of keys/messages; untrusted names/paths validated.
- [ ] Routing table across `development` / `oms-core` / service / workspace.

## Known gaps
- No DynamoDB `merchant_info` table in Terraform; three drifted LocalStack scripts outside `development` (open question 25).
- Import reads from a caller-chosen bucket/key; configured bucket unused and misnamed (open question 25).
- AWS/LocalStack defaults (endpoint, `test` keys) in base `application.yaml` of both services; `DynamoDbConfig` hard-codes the localdev endpoint and region.
- No SQS DLQ (open question 18); Redis provisioned but unused.
