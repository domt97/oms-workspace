# Flow: Checkout placement (cart → order → stock)

Status: **partly built** (ADR 0007). order-service consumes `PlaceCheckout` and answers every pre-reserve failure with
`CheckoutRejected` (listener off by default); placement, the stock commands and cart-service are not built.
Inventory's side is built (ADR 0006, `order-stock-reservation.md`). Rules: BR-CRT-03/04, BR-ORD-01..05, 08, 10, 14..16, BR-MER-05,
BR-STO-04/05/07, BR-PRC-01/03, BR-FUL-03.

## Happy path

```mermaid
sequenceDiagram
    participant W as oms-web
    participant K as cart-service
    participant O as order-service
    participant S as stores-service
    participant I as inventory-service
    W->>O: delivery quotes per store (fee shown, BR-PRC-03)
    W->>K: POST checkout (If-Match: cart version; address typed, BR-ORD-15)
    K->>K: tx: cart CHECKING_OUT + outbox PlaceCheckout (key cartId)
    K-->>O: PlaceCheckout
    O->>O: look up checkout by (cartId, cartVersion)
    O->>S: order-quote per store (store snapshot and config, merchant status, open + reasons, local date, SKU prices) — outside the tx
    O->>O: tx: insert checkout PENDING (unique key), one order per store PENDING, daily-cap slots, fees; outbox ReserveStock × N
    I-->>O: StockReserved × N
    O->>O: tx: every order PLACED, order numbers; outbox ConfirmStockReservation × N + CheckoutPlaced
    O-->>K: CheckoutPlaced → cart CHECKED_OUT
    I-->>O: StockReservationConfirmed → the store sees the order (BR-ORD-16)
    O->>O: auto-accept, or staff accept / reject within 5 minutes (BR-STO-05, BR-ORD-08)
```

## One outcome per checkout key

The `checkouts` row is unique on `(cart_id, cart_version)`. Whoever inserts it first decides the outcome.

| Case | order-service | Reply |
|---|---|---|
| Key exists, same content | nothing new | the stored outcome again (nothing while `PENDING`) |
| Key exists, different content | nothing | `CheckoutRejected{CONTENT_MISMATCH}` (not an outcome for the cart) |
| No key, `requestedAt` too old | insert `STALE` | `CheckoutRejected{STALE}` |
| No key | insert `PENDING`, place | `CheckoutPlaced` or `CheckoutRejected` with reasons |
| cart calls `by-key/expire` (11 min after `requestedAt`), no key | insert `EXPIRED` | `EXPIRED` → cart `ACTIVE` (version + 1) |
| cart calls `by-key/expire`, key exists | nothing | the stored outcome: `PLACED` → `CHECKED_OUT`; `REJECTED` / `STALE` / `EXPIRED` → `ACTIVE`; `PENDING` → the cart asks again later |

Placement and expiry insert under the same unique key (`INSERT … ON CONFLICT DO NOTHING`; the loser writes nothing and re-reads the row), so they never both succeed (ADR 0007). The cart ignores `CONTENT_MISMATCH` and alerts.

## Rejections and timeouts

- Any store or line fails a check (merchant suspended, store not `ACTIVE` or closed, daily cap, SKU, currency, fee
  changed, stores-service unavailable) → nothing is reserved; `CheckoutRejected` with a reason per store or line.
- Any `StockReservationRejected`, or no reserve reply in time → every order of the checkout is rejected and every
  reservation released (all-or-nothing, BR-ORD-14); daily-cap slots are freed.
- No `ConfirmStockReservation` reply → re-sent with a doubling interval up to 10 minutes, never cancelled for silence
  (BR-ORD-16); `StockReservationConfirmationFailed` → cancel and release, only while the saga state is `CONFIRM_SENT`.
- No reserve reply within 150 s → `RESERVE_TIMEOUT` for the whole checkout.
- No reply to the cart → re-send `PlaceCheckout` at 1, 2, 4 minutes (same `requestedAt`), then the synchronous, idempotent `by-key/expire` 11 minutes after `requestedAt`.
