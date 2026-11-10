# Manufacturing service: Decisions and Scope

Recorded 2026-11-05. The owner chose **read APIs only**: the contract (`API_CONTRACTS.md`: Dashboard, Production
work orders) specifies no way to create work orders, record stage progress, raise blockers or issue material. The
dashboard's figures also need sales, testing and dispatch modules that do not exist yet.

## Scope: the 5 frontend endpoints

| Endpoint | Permission |
|---|---|
| `GET /production/work-order-stages` | `manufacturing:view` |
| `GET /production/work-orders` (`q`, `stage`, `workCentre`, `view` = delayed, blocked or due_soon; sort `workOrderNo`, `plannedFinish`, `customerDueDate`, `stage`, `schedule`) | `manufacturing:view` |
| `GET /production/work-orders/{id}` (id or work-order number) | `manufacturing:view` |
| `GET /production/work-orders/summary` | `manufacturing:view` |
| `GET /dashboard/summary` | `dashboard:view` |

## Data

The tables are empty until another system or a later module fills them; the APIs then return empty lists and zero counts:
- `work_order_stage`: the route, as configuration;
- `sales_order`;
- `work_order`;
- `work_order_stage_record`;
- `work_order_material`;
- `work_order_event` (append-only).

**No sample data is shipped.** The tests use synthetic rows only.

## Definitions (pending production planning)

| Figure | Built as |
|---|---|
| Schedule status and variance | **Stored as supplied** by production planning. How they are calculated is an open question in the contract, so they are not computed here |
| Open work order | Any status other than `completed` |
| Due soon | Open, with the customer due date within `DUE_WINDOW_DAYS` (default 14, from the contract's example) |
| `byStage` | Open work orders per active stage, in route order |
| Open sales orders | Status other than `draft` and `dispatched` |
| Units in production | Work orders `in_progress` |
| Tests pending | Open work orders currently at the stage `TESTING_STAGE_CODE`. Empty: 0, because the testing stage is not named yet |
| Dispatches this week | Sales orders `dispatched` since Monday of the current week (UTC) |
| Monthly output | Completed work orders per month for the last 6 months; MVA = sum of the units' kVA ÷ 1000 |
| Recent orders | The 10 most recently changed sales orders |

**Pending:** per-plant scoping, owner assignment rules, and whether blockers come automatically from NCRs or material planning (contract open questions).
