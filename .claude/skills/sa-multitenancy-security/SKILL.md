---
name: sa-multitenancy-security
description: Merchant isolation and security rules — scoping of data, queries, APIs and events, internal endpoints, secrets, PII in logs. Use when a change reads or writes merchant data, adds an endpoint or event, or logs request data.
user-invocable: false
---
# Multi-tenancy & security

## Rules
1. **Where the merchant lives** (hierarchical tenancy):
   - A **top-level root** (e.g. `stores`) has `merchant_id NOT NULL`; per-merchant uniqueness includes it (`UNIQUE (merchant_id, code)`).
   - A **table owned by a merchant-scoped parent** (store products, collections, availability…) may rely on the parent key (`store_id`), as long as that parent never moves to another merchant. Do not duplicate `merchant_id` there.
   - A table in **another service** has no parent to join to, so it carries its own `merchant_id` (inventory does).
   - **Two owners**: merchant-owned data (merchant, store, catalog, inventory, order) is filtered by merchant (or a merchant-checked parent); customer-owned, platform-level data (customer, cart, checkout, payment) by customer. A checkout spans several merchants; each order it creates belongs to one merchant/store.
   - Add `merchant_id` to child tables only when needed: Postgres row-level security, merchant-wide queries/exports/deletion without the parent, or partitioning by merchant.
2. **Every query is scoped — never by id alone.**
   - Load the root by `(merchant_id, id)` (`findByMerchantIdAndStoreId`).
   - Load children by the checked parent: `WHERE store_id = :storeId AND id = :id`, and `WHERE store_id = :storeId AND id IN (:ids)` for lists of ids from the request (verify all were found).
   - Another merchant's or store's record → **404**, nothing written (don't leak existence with 403).
   - **Fixing a scoping gap also means checking the data.** The bug may already have written cross-merchant or cross-store rows, and the fix does not remove them. Write a query that finds rows breaking the invariant (e.g. a link whose child belongs to another store than its parent), run it, and ask the user what to do with any hits (migration, one-off script, or accept). Put the query in the PR body.
3. **Merchant in every event** (`merchantId` in the payload). Consumers validate it against the data they touch (e.g. inventory checks the store belongs to the same merchant).
4. **Merchant lifecycle**: decide what a non-active merchant can do (read-only? nothing?) and enforce it in one place. Until auth exists, that place is the use case that loads the `Merchant`; other services need a `MerchantStatusChanged` event (open question 32).
5. **Trust boundary (until auth is built)**: assume the caller is trusted, but design so it can be added without changing use cases:
   - `MerchantId` flows in the command object;
   - controllers take it from the path;
   - later, a filter will check the path merchant against the token claim.
   - Do not add new endpoints without a merchant.
6. **Internal endpoints** must be reachable only inside the network: a different port, network policy or gateway rule, plus service authentication when deployed. `@Hidden` is documentation, not protection.
7. **Secrets**:
   - never in code or committed YAML defaults for non-local profiles;
   - read from the environment or a secret manager;
   - local defaults only in the `localdev` profile.
   - In chat, never ask for tokens or keys (see `sa-analysis-checklist`).
8. **Logs**:
   - no secrets, tokens or full request bodies with PII (customer name, phone, address);
   - log ids, not personal data;
   - extend the filter's redaction list when adding a header.
9. **Excel/S3 input is untrusted**: validate size, row count and content. A path or filename from the request must stay inside the merchant's prefix (key layout: `sa-aws-platform` rule 8).

## Checklist
- [ ] Every query in the change scoped by merchant (directly or through a merchant-scoped root)? Show the line.
- [ ] Cross-merchant test: an id that exists in another merchant → 404, nothing written.
- [ ] Ids in the request body (lists) checked to belong to the same store/merchant.
- [ ] Fixing a scoping gap: query for rows that already break the invariant, result shown, cleanup decided with the user.
- [ ] New table: top-level → `merchant_id NOT NULL` (in unique constraints and indexes); child of a merchant-scoped parent → parent key, or `merchant_id` if rule 1 says so.
- [ ] Event payload carries `merchantId`; consumer validates it.
- [ ] Merchant status handled (or explicitly out of scope).
- [ ] No secrets or PII in code, YAML defaults, logs, or event payloads beyond what the consumer needs.
- [ ] Internal endpoint? How is it kept internal?

## Current state and known gaps
Not in this file. When you need how the OMS does this today, or which gaps are known, read
`.claude/skills/sa-multitenancy-security/references/current-state.md`. It is a snapshot: `architecture/generated/` and the code win.
