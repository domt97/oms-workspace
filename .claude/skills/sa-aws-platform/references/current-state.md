# AWS & local platform — how the OMS does it today (snapshot)

Moved out of `SKILL.md` so the rules load without it. This is a hand-written snapshot, not a rule: before relying on
a line, check it against `architecture/generated/<service>.md` and the code — code wins. A gap listed here without an
open-question number is not yet in `architecture/open-questions.md`.

## OMS today (verified in code)
**Local infrastructure** (`development/docker/docker-compose.yml`)
- LocalStack 3.8.1 with `SERVICES=s3,dynamodb,sqs,events`. DynamoDB is still started but **no service uses it** since merchants moved to Postgres (ADR 0003); do not add a dependency on it without a decision.
- Kafka 7.3.0 + ZooKeeper, Schema Registry, Kafka Connect (Debezium) on `:9084`, kafka-ui.
- Postgres 16 with `wal_level=logical`.
- Redis 7 — **no service uses it yet**.

**Terraform** (`development/docker/infra/local/main.tf`; variables `profile` = `localdev`, `region` = `eu-west-1`, `localstack_endpoint`)
- S3 bucket `${profile}-store-products`.
- SQS `${profile}-reservation-expire-queue`, visibility 90 s, **no DLQ**.
- EventBridge rule `${profile}-reservation-expire` with `rate(1 minute)`, targeting that queue, plus the queue policy that allows the rule.
- LocalStack scripts in `oms-core/localstack/` and `stores-service/localstack/` create unused queues and an EventBridge bus (open question 25).
- Those scripts have drifted:
  - they create resources nothing uses (`localdev-product-created-event` and `localdev-store-products-created-queue` queues, an EventBridge bus);
  - `development/localstack/localstack.sh` is a template with test resources only.

**Clients**
- `oms-core` builds the AWS SDK v2 clients:
  - `S3Config` (`aws.region` / `aws.endpoint` / `aws.access-key` / `aws.secret-key` via `AwsProperties`);
- With profile `localdev`, `S3Config` uses LocalStack and static `test`/`test` credentials; otherwise the default credential chain, with optional endpoint and static-key overrides.
- inventory-service uses Spring Cloud AWS 3.1.1 for SQS (`spring.cloud.aws.*`, static `test` credentials and the LocalStack endpoint in the **default** `application.yaml`).

**Naming and config drift**
- Queue name is set in `aws.sqs.queues.reservation-expire`, default `localdev-reservation-expire-queue`.
- **The import bucket comes from the request, not from config.**
  - `ProductExcelReader.read(path, fileName)` calls `S3ObjectStorageReader.read(bucket, key)`, so `ImportStoreProductsRequest.path` is used as the **bucket name** and `fileName` as the key.
  - `S3Properties.storeProductBucket` (`aws.s3.store-product-bucket`) is defined but not used.
  - Its localdev value `localdev_store_products` (underscores, not a valid S3 name) also differs from the Terraform bucket `localdev-store-products` (open question 25).
  - Each read also does a `HeadBucket` call first.

## Known gaps
- Drifted LocalStack scripts outside `development` (open question 25).
- Import reads from a caller-chosen bucket/key; configured bucket unused and misnamed (open question 25).
- AWS/LocalStack defaults (endpoint, `test` keys) in base `application.yaml` of both services.
- No SQS DLQ (open question 18); Redis provisioned but unused.
