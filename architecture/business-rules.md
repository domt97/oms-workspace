# Business Rules

> **How to read this file.** Each rule has an id and a status:
> - ✅ **In code**: true today; reference given. Code wins if this file disagrees.
> - 🟢 **Decided**: confirmed by the product owner (date in brackets). Build on it; if code differs, the code has a gap.
> - 🟡 **Proposed**: solution-architect recommendation. **Not decided**; the product owner must confirm or change it.
> - ❓ **Open**: needs a decision; see the question at the end.
>
> **Agents:** design only on ✅ and 🟢 rules, and on 🟡 rules the user has confirmed in the conversation.
> For ❓ items, ask the user (quote the question id). Never invent a rule. When the user decides, update
> the status here in the same piece of work.

## Platform & merchant

| Id | Rule | Status |
|----|------|--------|
| BR-MER-01 | The platform serves **one market** (Vietnam) with **one currency** (VND, 0 decimals); every store, price, checkout and payment uses it. More markets are out of scope. | 🟢 Q32, Q33 (2026-10-25) |
| BR-MER-02 | **Merchant = tenant**: a merchant is one seller company and owns one or more **stores** (branches). Merchants are isolated from each other. A store belongs to exactly one merchant and never moves. | ✅ store → `tenant_id` (`V4`); 🟢 Q32 (2026-10-25). **Gap:** the code calls the merchant *tenant*; rename planned (open question 28) |
| BR-MER-03 | A group with several brands is one merchant per legal entity (contract), with the brand as a store attribute. | 🟡 ❓ Q34 |

## Channels & users

| Id | Rule | Status |
|----|------|--------|
| BR-USR-01 | Customers order through the **customer app**; POS / staff-entered orders are out of scope for now. | 🟢 Q2 (2026-10-25) |
| BR-USR-02 | A **customer account is required** to build a cart and order; no guest orders. Customers are **platform users**: one account works across all merchants. | 🟢 Q15, Q20b, Q32 (2026-10-25) |
| BR-USR-04 | The platform is a **multi-merchant marketplace**: one customer app shows stores of all merchants. | 🟢 Q20b (2026-10-25) |
| BR-USR-05 | Customers can **search products across all stores and merchants** (read model fed by catalog events). | 🟢 Q30 (2026-10-25), later phase |
| BR-USR-03 | Merchant users have one of three roles:<br/>- **owner**: all stores of the merchant;<br/>- **manager**: one (or assigned) store(s);<br/>- **staff**: accept, prepare and hand over orders of their store. | 🟢 Q16 (2026-10-25) |

## Tenant & store

| Id | Rule | Status |
|----|------|--------|
| BR-STO-01 | A store belongs to one merchant (BR-MER-02). Store `code` is unique per merchant. | ✅ `UNIQUE (tenant_id, code)` (`V4`; `tenant_id` = merchant) |
| BR-STO-02 | Store status is `ACTIVE`, `INACTIVE`, `SUSPENDED` or `CLOSED`; only `ACTIVE` stores take orders. | ✅ statuses (`StoreStatus`); 🟡 order rule |
| BR-STO-03 | A store has its own time zone; its currency is the **platform currency** VND (BR-MER-01). Every SKU price is in that currency. | ✅ fields `StoreConfig.timeZone`/`currency`; 🟢 Q9, Q33 (2026-10-25). **Gap:** `StoreConfig.currency` and `ProductSku.currency` are free fields; nothing checks they equal VND |
| BR-STO-04 | A store is open when the current local time is within that day's business hours **and** no active availability window (closure, holiday, maintenance, staff shortage, inventory) covers now. | ✅ hours check `Store.isOpen` (opening < closing, so no overnight hours); 🟡 combining with `StoreAvailability` (not done anywhere today) |
| BR-STO-05 | `autoAcceptOrder`: orders are accepted without staff action; otherwise staff must accept or reject. | ✅ setting exists, unused; 🟡 behaviour, see BR-ORD-08 |
| BR-STO-06 | `allowPreOrder`: when on, customers may order for a later time (e.g. tonight for tomorrow 7:00, or while the store is closed), choosing a time slot inside future opening hours. Stock is held at placement (BR-INV-02). | ✅ setting exists, unused; 🟢 pre-order supported, at most until the next day (Q7, Q27, 2026-10-25); 🟡 15-min slots |
| BR-STO-07 | `maxOrdersPerDay`: the store stops taking orders when the day's count (store local day) is reached. | ✅ setting exists, unused; 🟡 counted at placement, cancelled orders free a slot |
| BR-STO-08 | `preparationTimeMinutes`: default promised ready time = accepted time + preparation time. | ✅ setting exists, unused; 🟡 |

## Catalog

| Id | Rule | Status |
|----|------|--------|
| BR-CAT-01 | A product is `DRAFT`, `ACTIVE` or `INACTIVE`; only `ACTIVE` products with `ACTIVE` SKUs can be ordered. | ✅ statuses; 🟡 order rule |
| BR-CAT-02 | A SKU is unique **within a store**. | 🟢 Q10 (2026-10-25). **Gap:** stores-service only enforces unique per product (open question 26). |
| BR-CAT-03 | A product created in the catalog gets an inventory record per SKU with quantity 0. | ✅ `ProductCreated` → `CreateInventoryService` |
| BR-CAT-04 | Price changes never affect placed orders (orders keep a snapshot, BR-ORD-03). | 🟡 |
| BR-CAT-05 | Merchants sell both made-to-order items (food & beverage) and stocked retail goods. | 🟢 Q1 (2026-10-25) |

## Inventory

| Id | Rule | Status |
|----|------|--------|
| BR-INV-01 | Stock is tracked per (store, SKU): `available = quantity − reserved`; neither may go negative. | ✅ guarded SQL (`SpringDataInventoryRepository`) |
| BR-INV-02 | Stock is held **at order placement** (before payment), one reservation per order line; the hold expires after a TTL if the order is not confirmed. | 🟢 hold at placement (Q4, 2026-10-25); ✅ TTL is 30 min in code (`StockReservation.reserve`); 🟡 TTL 15 min with a 10-min payment window (BR-ORD-07) |
| BR-INV-03 | A reservation moves only from `RESERVED` to `CONFIRMED`, `RELEASED`, `EXPIRED` (or `CANCELLED`). Confirm and expire are mutually exclusive. | ✅ guarded transitions (inventory-service#27) |
| BR-INV-04 | Confirming a reservation reduces `quantity` (sale); releasing/expiring only frees the hold. | ✅ `confirm` / `release` SQL; 🟡 must write a `SALE` stock movement (open question 14) |
| BR-INV-05 | Every stock change is auditable: a stock movement with type, quantity and the business reference (order, adjustment…). | ✅ for manual adjustment only; 🟡 for all (open question 14) |
| BR-INV-06 | A SKU has a `trackStock` flag. When it is off (made-to-order items), the SKU is always available and no reservation is made. | 🟢 Q11 (2026-10-25) — **nice to have**, not required for the MVP. Modifiers/toppings: later. |
| BR-INV-07 | The same order line can never reserve twice (replays are no-ops). | 🟡 (open question 13) |

## Cart *(nothing built yet)*

| Id | Rule | Status |
|----|------|--------|
| BR-CRT-01 | A cart belongs to one logged-in customer (platform level, no merchant). A customer has **one active cart**, which may hold items from **several stores of different merchants**; checkout splits it into one order per store. | 🟢 Q3, Q15, Q20, Q20b (2026-10-25) |
| BR-CRT-02 | A cart line references store, product and SKU with a quantity (> 0, ≤ a per-line maximum). Adding the same SKU again increases the quantity. Lines are shown grouped by store. | 🟡 |
| BR-CRT-03 | Adding to the cart **never holds stock** and never creates a payment. Prices and availability are **indicative**, refreshed when the cart is viewed; unavailable lines are flagged, not silently removed. | 🟢 no stock hold (Q18, 2026-10-25); 🟡 indicative prices / flagging |
| BR-CRT-04 | Checkout sends **one** request to order-service with all lines grouped by store and idempotency key = cart id + cart version. Order-service creates **one order per store** (BR-ORD-01). The cart is locked (`CHECKING_OUT`) during the call. Retrying returns the same result. On success the cart becomes `CHECKED_OUT`; on rejection it returns to `ACTIVE` with reasons per line. | 🟢 split per store (Q3), all-or-nothing (Q21) (2026-10-25); 🟡 mechanics |
| BR-CRT-05 | Carts are stored on the server (they follow the customer across devices) and become `ABANDONED` after **7 days** without activity. | 🟢 Q17 (2026-10-25) |
| BR-CRT-06 | Cart data is stored in Postgres; Redis is added only if load requires it. | 🟢 Q19 (2026-10-25) |

## Ordering *(nothing built yet)*

| Id | Rule | Status |
|----|------|--------|
| BR-ORD-01 | An order belongs to exactly **one store** (hence one merchant). A checkout with items from N stores creates **N orders**, linked by one `checkoutId`. | 🟢 Q3 (2026-10-25) |
| BR-ORD-02 | An order can be placed only if all of these hold, checked at placement time; otherwise it is rejected with a reason per line:<br/>- the store is `ACTIVE`;<br/>- the store is open, or pre-order is allowed for the requested slot;<br/>- the products and SKUs are `ACTIVE`;<br/>- the stock reservation succeeds;<br/>- the daily cap is not reached. | 🟡 |
| BR-ORD-03 | Each order line **snapshots** SKU, product name, unit price and currency at placement. Totals are computed by the server from the snapshots; client-sent prices are ignored. | 🟡 |
| BR-ORD-04 | Money = amount + ISO-4217 currency; amounts are rounded to the currency's minor unit with HALF_UP, at line level then summed. | 🟡 (currency per store is 🟢, BR-STO-03) |
| BR-ORD-05 | Placing a checkout is idempotent: the caller (cart-service, BR-CRT-04) sends an idempotency key; the same key returns the same orders. | 🟡 |
| BR-ORD-06 | Order statuses (with third-party delivery, BR-FUL-01):<br/>`PENDING` (validating/reserving) → `AWAITING_PAYMENT` (online payment only) → `PLACED` → `ACCEPTED` → `PREPARING` → `READY` → `DELIVERING` (handed to the driver) → `DELIVERED` → `COMPLETED`.<br/>Terminal: `REJECTED`, `CANCELLED`, `EXPIRED`, `DELIVERY_FAILED`.<br/>Each transition is guarded and records actor + reason + time. | 🟡 (payment Q5 and delivery Q8 are 🟢; the state list itself needs your review) |
| BR-ORD-07 | Unpaid online orders expire when the stock reservation expires; expiry releases stock and cancels the order. The payment window (10 min) is shorter than the reservation TTL (15 min). | 🟡 |
| BR-ORD-14 | A multi-store checkout is **all-or-nothing at placement**: every order is validated and reserved; if any order fails, all reservations are released, no order is placed, and the customer sees the reasons per store/line. | 🟢 Q21 (2026-10-25) |
| BR-ORD-08 | With `autoAcceptOrder` the order goes `PLACED → ACCEPTED` immediately. Otherwise staff must accept within **5 minutes** or the order is rejected automatically (stock released, payment refunded). | 🟢 Q12 (2026-10-25) |
| BR-ORD-09 | Cancellation:<br/>- the customer may cancel until the order is `ACCEPTED`;<br/>- after that, only the store can cancel (with a reason);<br/>- cancelling releases unconfirmed stock and refunds a captured payment in full;<br/>- confirmed stock is returned only if the store marks the goods reusable. | 🟢 Q13 (2026-10-25) |
| BR-ORD-10 | An order has a human-readable number unique per store (e.g. `S01-000123`), separate from its UUID. | 🟡 |
| BR-ORD-11 | Placed orders are never edited (lines, prices). Changes are cancel + re-order, until a modification feature is designed. | 🟡 |
| BR-ORD-12 | order-service **orchestrates** the order saga (reserve, payment, delivery booking, timeouts, compensations); other services execute commands and report back with events. | 🟢 Q6 (2026-10-25) |
| BR-ORD-13 | After placement, each order of a checkout lives on its own: each store accepts, rejects, prepares and cancels its own order; refunds are per order. | 🟡 |

## Pricing & promotion

| Id | Rule | Status |
|----|------|--------|
| BR-PRC-01 | Prices are **tax-inclusive**. No service fee or tips in the MVP. Line price = SKU price at placement × quantity. | 🟢 Q14 (2026-10-25) |
| BR-PRC-03 | Each order has a **delivery fee** = the delivery partner's quote for that order, paid by the customer, shown at checkout and snapshotted on the order. Checkout total = Σ (order items + delivery fee). | 🟢 Q14, Q23, Q28 (2026-10-25) |
| BR-PRC-02 | A promotion/voucher is validated when quoting and again at placement; the applied discount is snapshotted on the order and redeemed only when the order is placed (released if cancelled). | 🟡 (phase 3) |
| BR-PRC-04 | Two kinds of vouchers: **platform vouchers** (funded by the platform, valid across merchants, split across the orders of a checkout) and **shop vouchers** (funded by one merchant, valid on its orders). Who funds a discount is recorded for settlement. | 🟢 Q31 (2026-10-25), phase 3 |

## Payment

| Id | Rule | Status |
|----|------|--------|
| BR-PAY-01 | Two payment methods: **cash on delivery (COD)** and **online**. The OMS does not integrate a real gateway: online payment goes through a **mock payment provider** behind the payment ACL, so a real gateway can replace it later without changes outside payment. | 🟢 Q5, Q24 (2026-10-25) |
| BR-PAY-02 | The order is the source of truth for "what is owed"; payment owns "what was paid". Payment results arrive as events and are idempotent per gateway transaction id. | 🟡 |
| BR-PAY-03 | Refunds are full on cancellation (BR-ORD-09); partial refunds only via an explicit store action. | 🟢 Q13 (2026-10-25) |
| BR-PAY-04 | COD: the delivery driver collects the cash. The amount to collect is sent to the delivery partner with the booking and reconciled from the partner's settlement. | 🟡 |
| BR-PAY-05 | A multi-store checkout paid online is **one payment** for the checkout total, collected by the **platform** for all merchants of the checkout; refunds are made per order. | 🟢 Q22, Q20b (2026-10-25) |
| BR-PAY-06 | The platform owes each merchant the value of its completed orders minus a commission, paid out on a schedule (payouts mocked). | 🟢 in scope, later phase (Q29, 2026-10-25); 🟡 commission % per merchant, balance per merchant |

## Fulfillment

| Id | Rule | Status |
|----|------|--------|
| BR-FUL-01 | Orders are delivered by a **third-party delivery partner**, one delivery booking per order (per store). Delivery first; **pickup** later. | 🟢 Q8, Q25, Q26 (2026-10-25): the delivery partner is a **mock** behind the delivery ACL (simulated quotes and status callbacks) |
| BR-FUL-02 | The promised ready time is shown to the customer at acceptance (BR-STO-08) and updated if the store delays. | 🟡 |
| BR-FUL-03 | The delivery booking is created when the order is `ACCEPTED` (or `READY`, depending on the partner's driver lead time). Partner status updates (driver assigned, picked up, delivered, failed) arrive as callbacks, are translated in an ACL and drive `DELIVERING` / `DELIVERED` / `DELIVERY_FAILED`. | 🟡 |

---

## Decided (2026-10-25)

| Id | Decision |
|----|----------|
| Q1 | Both made-to-order (F&B) and stocked retail goods. |
| Q2 | Customer app. |
| Q3 | One checkout may contain several stores; it is split automatically into one order per store. |
| Q4 | Stock is held at order placement. |
| Q5 | Both COD and online payment. |
| Q6 | Orchestration by order-service. |
| Q8 | Third-party delivery. |
| Q9 | One currency per store — refined by Q33: one currency (VND) for the whole platform. |
| Q10 | SKU unique within a store. |
| Q11 | `trackStock` flag per SKU — nice to have. |
| Q13 | Customer cancels until accepted; then store only; full refund; stock returned only if reusable. |
| Q7 | Pre-order is supported. |
| Q12 | Manual acceptance timeout: 5 minutes, then auto-reject. |
| Q14 / Q23 | Tax-inclusive prices; no service fee or tips in the MVP; delivery fee = delivery partner's quote per order. |
| Q15 | Customer account required (no guest orders). |
| Q16 | Roles: owner, manager, staff. |
| Q17 | Carts on the server; abandoned after 7 days of inactivity. |
| Q18 | Adding to the cart never holds stock. |
| Q19 | Postgres for carts; Redis only if load requires. |
| Q20 | A checkout may contain several stores; the system splits it into one order per store. |
| Q20b | Marketplace across merchants: one customer app, one cart across merchants. |
| Q21 | If one store's order fails at placement, the whole checkout fails with errors (all-or-nothing). |
| Q22 | One payment for the whole checkout. |
| Q24 | No real payment gateway: a mock payment provider; the platform covers the OMS only. |
| Q25 | Delivery first; pickup later. |
| Q26 | All third parties (payment, delivery) are mocked. |
| Q27 | Pre-order at most until the next day. |
| Q28 | The customer pays the delivery fee. |
| Q29 | Settlement (commission, merchant balances, mocked payouts) is in scope, later. |
| Q30 | Search across all stores, later. |
| Q31 | Platform vouchers and shop vouchers, phase 3. |
| Q32 | Tenant = merchant; one market (Vietnam) only; customers are platform users. The code's `tenant` will be renamed to `merchant`. |
| Q33 | One currency (VND) for the platform. |

## Open business questions

| Id | Question | Why it matters | Proposed default |
|----|----------|----------------|------------------|
| Q34 | A group with several brands (e.g. one company owning three restaurant brands): one merchant, or one merchant per brand? | Users/roles, settlement, reporting | One merchant per legal entity; brand is a store attribute (not blocking) |
