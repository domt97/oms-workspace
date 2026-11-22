# ADR 0007 — Checkout placement: PlaceCheckout over Kafka, unlock by tombstone, confirm re-send

Status: Accepted (2026-11-15), amended 2026-11-22 (*Amendments* below). Built in order-service: intake (pre-reserve
checks, stored rejections) and placement with the stock saga, the reserve timeout and the confirm/release re-send. Not built: cart-service, `by-key/expire`, accept/reject, cancel,
delivery (Cart + Order MVP, roadmap phase 1). Rules: BR-CRT-01..06, BR-ORD-01..16, BR-STO-04/05/07/08, BR-FUL-01..03, BR-PRC-01/03, BR-PAY-01/03/04,
BR-MER-05. Flow: `flows/checkout-placement.md`; stock side: ADR 0006 and `flows/order-stock-reservation.md`.

## Context
A checkout spans two new services and inventory. cart-service locks the cart and asks order-service to place it;
order-service re-validates and re-prices everything, creates one order per store and runs the stock saga of ADR 0006.
The outcome is asynchronous in any case: inventory answers the reserve and confirm commands with events.

Two failure modes drive this design:
- a placement whose reply is lost or late must never leave the cart locked for ever, **and** unlocking must never let a
  late placement create orders for a cart the customer can edit again (that would duplicate orders on the next checkout);
- a confirm without a reply must not leave an order stuck, and must not cancel an order whose
  stock inventory did confirm.

Alternatives considered: a synchronous `POST` from cart to order for the placement (simpler to follow, but locking the
cart and sending are then not one transaction, and the outcome must still be polled); unlocking a stuck cart after a
fixed wait (relies on clocks and transaction durations, which nothing bounds — rejected in review); an `ExpireCheckout`
command instead of the synchronous expire call (a second asynchronous loop for a call that needs an answer).

System rule 2 said "cross-service writes go through events". The product owner clarified (2026-11-15) that sync or
async is chosen per case; the rule now reads: state changes that must happen together with a local commit go through
the outbox, and a synchronous call is allowed when it is idempotent, retried and safe to lose.

## Decision
**Transport (system rules 2, 8).**
- `PlaceCheckout` is a **command** written by cart-service through its outbox in the same transaction that sets the cart
  `CHECKING_OUT` (topic `PlaceCheckout`, key `cartId`). order-service consumes it (group `order-place-checkout`).
- The replies `CheckoutPlaced` and `CheckoutRejected` are events from order-service's outbox (key `cartId`, with
  `causationId` = the command's `eventId`). cart-service applies a reply only with
  `WHERE id = :cartId AND version = :cartVersion AND status = 'CHECKING_OUT'`, so a late reply after an unlock is a no-op.
- Schemas: `contracts/events/PlaceCheckout`, `CheckoutPlaced`, `CheckoutRejected`. The command carries no prices;
  order-service reads store state and SKU prices from stores-service (internal `order-quote`, synchronous, before its
  transaction, with `X-Request-Id` from oms-core 1.2.0's `RequestIdClientConfig`).

**One outcome per checkout key (BR-ORD-05).** order-service keeps one `checkouts` row per key, `UNIQUE (cart_id,
cart_version)`, with a content hash and a status. The hash covers `customerId`, `delivery` and `stores` (normalised:
stores and lines sorted by id), never `eventId`, `occurredAt` or `requestedAt`, so a re-send of the same command matches.
Every path that decides the outcome **inserts or finds that row**:
- *placement:* the handler first reads the key. Same hash → re-publish the stored outcome (nothing while `PENDING`).
  Different hash → `CheckoutRejected{CONTENT_MISMATCH}`; the stored checkout is untouched. No row → if `requestedAt`
  is older than **10 minutes** (shorter than the 15-minute hold, BR-INV-02), insert the row as `STALE`
  (`ON CONFLICT DO NOTHING`; on 0 rows re-read it) and reply with the stored outcome; otherwise run the stores-service calls (outside any transaction).
  **A pre-reserve rejection is stored too** (decided 2026-11-16): any failed check inserts the row as `REJECTED` with its
  reasons, in the same transaction as its `CheckoutRejected` (`ON CONFLICT DO NOTHING`; on 0 rows re-read it), so a
  later copy never re-runs the checks and places what the customer already saw rejected. If every check passes, open the placement
  transaction, whose **first statement** is `INSERT … ON CONFLICT DO NOTHING` of the `PENDING` row. If that insert
  affects 0 rows (another copy or an expiry won), the transaction writes nothing else and rolls back; the handler
  re-reads the row and answers as for an existing key. Only the winner writes the orders and the `ReserveStock` commands,
  in that same transaction.
- *unlock:* cart-service never unlocks on a timer alone. It re-sends the command at 1, 2 and 4 minutes (same
  `requestedAt`); **11 minutes** after `requestedAt` (past the 10-minute STALE window) its job calls order-service's
  internal, idempotent `POST /internal/v1/order/customers/{customerId}/checkouts/by-key/expire` with `cartId` and
  `cartVersion`. order-service runs the same `INSERT … ON CONFLICT DO NOTHING`, this time as `EXPIRED` with the path's
  `customerId`; on 0 rows it re-reads the row, and a row of another customer answers 404. It answers the stored outcome, and cart-service applies **any final outcome**: `PLACED` →
  `CHECKED_OUT`; `REJECTED`, `STALE` or `EXPIRED` → `ACTIVE` (version + 1). `PENDING`, an error or a timeout never
  unlock: the job asks again (every minute, then every 5 minutes) and alerts after 15 minutes.
- Because placement and expiry both insert under the same unique key, **exactly one of them wins**, whatever the clocks
  or transaction durations. A copy of the command that arrives later finds the `EXPIRED` or `STALE` row and only
  re-publishes it; the cart ignores it (its version has moved on).
- cart-service **ignores `CONTENT_MISMATCH`** (it is not an outcome of its checkout) and alerts; the real outcome
  arrives by its own reply or through `by-key/expire`.
- The insert runs with `SET LOCAL lock_timeout` and `statement_timeout`.
- The synchronous `by-key/expire` call is allowed by system rule 2: it is idempotent, the caller retries it, and losing
  it leaves both sides consistent (the cart stays locked and asks again). Delivering `PlaceCheckout` must go together with
  the cart's commit, so that one goes through the outbox.

**Counters.** One row per `(store_id, local_date)`, taken in `store_id` order. `local_date` is the store's local day
(BR-STO-03 time zone) **at placement**; it is stored on the order and every later step uses that stored date, never the
clock:
- *daily-cap slot* (BR-STO-07), in the placement transaction: `INSERT … (placed_count) VALUES (1) ON CONFLICT (store_id,
  local_date) DO UPDATE SET placed_count = placed_count + 1 WHERE :max IS NULL OR placed_count < :max RETURNING …`;
  no row returned → `DAILY_CAP_REACHED`. The first order of a day creates the row.
- *order number* (BR-ORD-10), in the transaction that sets the order `PLACED`: `UPDATE … SET last_seq = last_seq + 1
  WHERE store_id = :storeId AND local_date = :orderLocalDate RETURNING last_seq` (the row exists: the cap upsert of the
  same order created it). 0 rows is an error, never skipped. Rejected checkouts use no numbers, and `{yyMMdd}` is the
  stored `local_date`, so an order placed at 23:59 and `PLACED` after midnight keeps its placement day.
- a rejected or cancelled order gives its slot back on its stored `local_date`, with a guarded decrement **in the same
  transaction as its guarded status change**, so a redelivery cannot give a slot back twice.

**Stock confirm (Q42, BR-ORD-16).** After every order of a checkout is reserved, order-service sets
them `PLACED` and sends `ConfirmStockReservation` (saga state `CONFIRM_SENT`). The reserve itself times out after
**150 s** without a reply (above inventory's ≈ 105 s retry window for one command) → the checkout is rejected
(`RESERVE_TIMEOUT`). With no confirm reply after 150 s, order-service **re-sends** the confirm (new `eventId`; inventory
decides from its order header, ADR 0006), doubling the interval up to 10 minutes with no limit and alerting from the
third re-send (see *Amendments*). It never cancels because a reply is missing. Obligation 3 of ADR 0006 is met by the **first** reply to
any copy: inventory's header makes later copies change no stock. A `StockReservationConfirmationFailed` cancels and
releases the order **only while its saga state is `CONFIRM_SENT`**; a failure for a copy of a saga already confirmed or
released changes nothing. A cancel that arrives while a confirm is in flight sets `release_pending` with a guarded
`UPDATE … SET release_pending = true WHERE stock_state = 'CONFIRM_SENT'`. The confirm's reply handler runs
`UPDATE … SET stock_state = :next, release_pending = false WHERE stock_state = 'CONFIRM_SENT' RETURNING release_pending`
and sends the release only when that returns `true`. When the cancel's UPDATE hits 0 rows, the reply was already handled,
and the cancel sends the release itself. The cancel itself is a guarded status change (`UPDATE … SET status =
'CANCELLED' WHERE status = :from`), in the same transaction as its `release_pending` update, and a confirmation failure releases only while `CONFIRM_SENT`, so a repeated cancel
or a cancel after a failure sends nothing more. A duplicate release would still be harmless: inventory answers it from
its order header (ADR 0006). The store sees the order only after `StockReservationConfirmed`.

**Amendments (2026-11-22, placement built; decisions D1–D8 confirmed by the product owner 2026-11-21).**
- *Complete reasons (D3):* a checkout is decided only when every order has a reserve reply or its 150 s deadline has
  passed; then all RESERVED → placed, anything else → rejected with every reason. At the deadline every order still
  waiting for its reserve is released too (inventory applies a release before the reserve, ADR 0006).
- *Re-send:* the release is re-sent like the confirm (150 s doubling to 10 min, never given up); ERROR and the alert
  metric from the **third** attempt. A reply counts by the order's state, not by which copy it answers (ADR 0006
  obligation 4 as amended). A `StockReservationConfirmationFailed` cancels the order with reason `STOCK_NOT_CONFIRMED`
  (D5); the checkout stays `PLACED`.
- *Counters:* "`store_id` order" is Postgres's uuid order, which is the order of the uuid's text form (not Java's
  `UUID.compareTo`). A cap ≤ 0 means no slot (D6); the day is the order quote's `localDate` (D8).
- *Not yet:* `release_pending` comes with the customer cancel; until then no Release is sent while an order is
  `CONFIRM_SENT`. The delivery fee stays null until delivery quotes exist (D2). `PlaceCheckout` stays off until
  acceptance and cancel, delivery quotes, `by-key/expire` and cart-service are built (D1).
- *Startup:* the reserve-timeout job does nothing for 150 s after the service starts, so replies queued while it was
  down are read first.

**Timeouts are database rows.** Reserve, confirm, accept (5 minutes, BR-ORD-08), booking retries and checkout expiry
are due-time columns read by `@Scheduled` jobs with `SELECT … FOR UPDATE SKIP LOCKED LIMIT n` and a guarded `UPDATE …
WHERE status = :expected`. These are row locks; N instances split the work. No scheduler service or AWS resource.

**Delivery partner.** A port in order-service; the MVP adapter is a mock partner inside order-service (profile
`mock-delivery`): quotes, booking at `ACCEPTED` (BR-FUL-03), simulated callbacks and a settlement report for the COD
reconciliation (BR-PAY-04).

**Infrastructure.** New databases `cart` and `orders` (created by `development` `docker/postgres/init/01-databases.sh`),
each with `outbox_events` and its own Debezium connector, slot and publication (ADR 0001); each connector is added with
its service, once the service's outbox table exists. The message topics (the three above and, with their contracts, the
order events) are created with partitions by `development` `docker/kafka/create-topics.sh` before the connectors are
registered; dead-letter topics are created by the consuming service (open question 30).

## Consequences
- Correctness of "one outcome per checkout" rests on a unique constraint, not on time: a stuck cart can always be
  unlocked, and a late placement can never produce orders for an unlocked cart.
- order-service gains an internal endpoint (`by-key/expire`) that only cart-service may call; internal routes are not
  exposed publicly (`sa-multitenancy-security`).
- A confirm or a release can be re-sent many times; inventory is idempotent for both (ADR 0006). Because no
  release is sent while a confirm has no reply (obligation 3), a release never overtakes a confirm.
- Stuck states are visible only through alerts (carts `CHECKING_OUT`; the saga state `CONFIRM_SENT` and the booking
  state `BOOKING_FAILED`, which are not order statuses of BR-ORD-06); the services need metrics before production.
- cart-service computes the BR-CRT-03 flags when the cart is read (from stores-service and stock status) and refuses
  checkout while a line is flagged; oms-web only displays them. order-service's per-line reasons stay the final check.
