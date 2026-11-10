"""Manufacturing reads: empty tables, the route, work orders (filters, views, sort, detail), summary, dashboard, access.
Rows are synthetic test data written directly (there are no write APIs by owner decision)."""

from datetime import UTC, date, datetime, timedelta

from app.core.context import SYSTEM_PRINCIPAL
from app.database.audit_listener import acting_as
from app.models.manufacturing_model import SalesOrder, WorkOrder, WorkOrderEvent, WorkOrderMaterial, WorkOrderStage, WorkOrderStageRecord
from tests.conftest import auth

API = "/api/v1"
VIEW = ["manufacturing:view", "dashboard:view"]


async def test_empty_tables_answer_with_empty_data(client):
    assert (await client.get(f"{API}/production/work-order-stages", headers=auth(permissions=VIEW))).json() == []
    page = (await client.get(f"{API}/production/work-orders", headers=auth(permissions=VIEW))).json()
    assert page["items"] == [] and page["meta"]["totalItems"] == 0
    summary = (await client.get(f"{API}/production/work-orders/summary", headers=auth(permissions=VIEW))).json()
    assert summary["open"] == 0 and summary["byStage"] == [] and summary["dueWindowDays"] == 14
    dash = (await client.get(f"{API}/dashboard/summary", headers=auth(permissions=VIEW))).json()
    assert dash["kpis"] == {"openOrders": 0, "unitsInProduction": 0, "testsPending": 0, "dispatchesThisWeek": 0} and len(dash["monthlyOutput"]) == 6 and dash["recentOrders"] == []
    assert (await client.get(f"{API}/production/work-orders", headers=auth(permissions=["dashboard:view"]))).status_code == 403
    assert (await client.get(f"{API}/dashboard/summary", headers=auth(permissions=["manufacturing:view"]))).status_code == 403
    assert (await client.get(f"{API}/production/work-orders/nope", headers=auth(permissions=VIEW))).status_code == 404


async def test_work_orders_views_detail_summary_and_dashboard(client, db):
    today = datetime.now(UTC).date()
    with acting_as(SYSTEM_PRINCIPAL):
        stages = [WorkOrderStage(code=c, label=label, sequence=i) for i, (c, label) in enumerate([("core", "Core building"), ("winding", "Winding"), ("testing", "Routine testing")], start=1)]
        db.add_all(stages)
        so = SalesOrder(order_no="SO-T-1", customer_name="Test Utility", rating_kva=1000, quantity=2, status="in_production", due_date=today + timedelta(days=30))
        shipped = SalesOrder(order_no="SO-T-2", customer_name="Other Utility", rating_kva=500, quantity=1, status="dispatched", due_date=today, dispatched_at=datetime.now(UTC))
        db.add_all([so, shipped])
        await db.flush()
        base = dict(sales_order_id=so.id, unit_of=2, rating_kva=1000, voltage_ratio="11/0.433 kV", vector_group="Dyn11", cooling="ONAN", work_centre="Winding Bay",
                    planned_start=today - timedelta(days=20), customer_due_date=today + timedelta(days=30))
        late = WorkOrder(work_order_no="WO-T-1", unit_index=1, status="in_progress", stage_id=stages[1].id, planned_finish=today + timedelta(days=5), schedule_status="delayed", variance_days=6,
                         blocker_type="material", blocker_description="Laminations short", blocker_since=today - timedelta(days=2), next_action_label="Expedite delivery",
                         next_action_owner_id="u-1", next_action_owner_name="Purchase Officer", next_action_owner_role="Purchase", **base)
        testing = WorkOrder(work_order_no="WO-T-2", unit_index=2, status="in_progress", stage_id=stages[2].id, planned_finish=today + timedelta(days=2), schedule_status="on_track", variance_days=0,
                            **{**base, "customer_due_date": today + timedelta(days=7)})
        done = WorkOrder(work_order_no="WO-T-3", unit_index=1, status="completed", stage_id=stages[2].id, planned_finish=today, schedule_status="on_track", variance_days=0,
                         completed_at=datetime.now(UTC), **{**base, "sales_order_id": shipped.id, "unit_of": 1, "rating_kva": 500})
        db.add_all([late, testing, done])
        await db.flush()
        db.add_all([WorkOrderStageRecord(work_order_id=late.id, stage_id=stages[0].id, state="done", started_at=today - timedelta(days=20), completed_at=today - timedelta(days=10)),
                    WorkOrderMaterial(work_order_id=late.id, item="CRGO laminations", required="1.2 t", status="short", expected_date=today + timedelta(days=3)),
                    WorkOrderEvent(work_order_id=late.id, summary="Moved to winding")])
        await db.commit()
    h = auth(permissions=VIEW)
    assert [s["code"] for s in (await client.get(f"{API}/production/work-order-stages", headers=h)).json()] == ["core", "winding", "testing"]
    page = (await client.get(f"{API}/production/work-orders", params={"sort": "schedule"}, headers=h)).json()
    assert page["meta"]["totalItems"] == 3 and page["items"][0]["workOrderNo"] == "WO-T-1", "delayed first"
    first = page["items"][0]
    assert first["schedule"] == {"status": "delayed", "varianceDays": 6} and first["blocker"]["type"] == "material" and first["stageCount"] == 3 and first["unit"] == {"index": 1, "of": 2}
    assert [w["workOrderNo"] for w in (await client.get(f"{API}/production/work-orders", params={"view": "blocked"}, headers=h)).json()["items"]] == ["WO-T-1"]
    assert [w["workOrderNo"] for w in (await client.get(f"{API}/production/work-orders", params={"view": "due_soon"}, headers=h)).json()["items"]] == ["WO-T-2"]
    assert (await client.get(f"{API}/production/work-orders", params={"q": "other util"}, headers=h)).json()["meta"]["totalItems"] == 1
    assert (await client.get(f"{API}/production/work-orders", params={"sort": "price:asc"}, headers=h)).status_code == 400
    detail = (await client.get(f"{API}/production/work-orders/WO-T-1", headers=h)).json()
    assert [s["state"] for s in detail["stages"]] == ["done", "current", "pending"] and detail["materials"][0]["status"] == "short" and detail["history"][0]["summary"] == "Moved to winding"
    assert (await client.get(f"{API}/production/work-orders/{detail['id']}", headers=h)).json()["workOrderNo"] == "WO-T-1"
    summary = (await client.get(f"{API}/production/work-orders/summary", headers=h)).json()
    assert summary["open"] == 2 and summary["delayed"] == 1 and summary["blockedByMaterial"] == 1 and summary["dueSoon"] == 1
    assert {s["code"]: s["count"] for s in summary["byStage"]} == {"core": 0, "winding": 1, "testing": 1}
    dash = (await client.get(f"{API}/dashboard/summary", headers=h)).json()
    assert dash["kpis"] == {"openOrders": 1, "unitsInProduction": 2, "testsPending": 1, "dispatchesThisWeek": 1}
    assert dash["monthlyOutput"][-1] == {"month": today.strftime("%Y-%m"), "unitsCompleted": 1, "mvaCompleted": 0.5}
    assert {o["orderNo"] for o in dash["recentOrders"]} == {"SO-T-1", "SO-T-2"}
