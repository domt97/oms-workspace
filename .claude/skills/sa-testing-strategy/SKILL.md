---
name: sa-testing-strategy
description: What each test level proves and what unit tests miss (SQL, transactions, constraints, JSON, messages). Use when planning the tests of a change or reviewing a diff's tests.
user-invocable: false
---
# Testing strategy

## Rules
1. **Test what can break, at the cheapest level that can catch it.**

   | Level | Proves | Misses |
   |-------|--------|--------|
   | Domain (pure JUnit) | invariants, state transitions, value objects | wiring, SQL |
   | Service (Mockito) | orchestration: what is loaded/saved/published, branches, exceptions; negative assertions `verify(x, never())` | real SQL, transactions, rollbacks |
   | Controller slice (`@WebMvcTest` + MockMvc) | path, JSON, validation → 400, exception → status, response shape | business logic |
   | Repository/SQL (`@DataJpaTest` or Testcontainers Postgres + Flyway) | native queries, guards (row counts), constraints, index use, migration applies | concurrency under load |
   | Messaging (Testcontainers Kafka / LocalStack, or the listener method + error handler config) | deserialisation, idempotency on redelivery, DLQ routing | — |
   | Contract | event payload matches `architecture/contracts/events/*.schema.json` on both producer and consumer | — |

2. **Mocks lie about SQL.** Any change to a native query, a guard `WHERE`, a constraint, a migration or a transaction boundary needs one of:
   - (a) a Testcontainers/`@DataJpaTest` test; or
   - (b) a documented manual check against local Postgres (statement, data, result, EXPLAIN) in the PR description.

   Prefer (a) once the dependency is added.
3. **Transactions are not tested by Mockito.** `@Transactional` on a self-invoked or non-public method is ignored at runtime; a mock-based test passes anyway. Verify boundaries by reading the call path (proxy entry point), or with an integration test that forces a failure after the first write and asserts nothing was committed.
4. **Concurrency claims need a concurrency test or a proof.** Either run two transactions against real Postgres (two threads, a latch), or write the interleaving argument in the plan (guard + row count). Never "it's in a transaction".
5. **Every edge case in the plan has a test**, including negative assertions:
   - "no row written", "no event", "never called";
   - duplicates in input;
   - wrong merchant/store;
   - redelivered message.
6. **Event contracts**: when changing an event payload that a producer and a consumer each declare, test serialisation on the producer and deserialisation of an **old** payload on the consumer (backward compatibility).
7. **Test data** via aggregate builders and fixtures; fix the clock (`Clock` bean, `Clock.fixed`) for time-based logic.
8. **Keep tests fast and deterministic**: no sleeps unless elapsed time is what is tested (use latches or Awaitility with a timeout), no random ports or real AWS, no order dependence.

## Checklist
- [ ] Test list per level, one per edge case, with negative assertions.
- [ ] What unit tests cannot prove here (SQL, constraint, transaction, serialisation, concurrency) and how it is verified instead.
- [ ] Redelivery/idempotency test for consumers; cross-merchant test for lookups.
- [ ] Old-payload compatibility test if an event changed.
- [ ] `./gradlew test` result in the PR (and `integrationTest` for inventory-service when SQL or locking changed); manual verification steps written down if any.

## Current state and known gaps
Not in this file. When you need how the OMS does this today, or which gaps are known, read
`.claude/skills/sa-testing-strategy/references/current-state.md`. It is a snapshot: `architecture/generated/` and the code win.
