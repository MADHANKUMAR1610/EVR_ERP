"""Module 8: rating scales and setup, cycles and phases, goals and progress, reviews and the manager assessment,
development plans, the summary, access. Every scale, competency and option below is a test value entered as HR would."""

from datetime import timedelta

from app.services.employee_support import company_today
from tests.conftest import auth
from tests.employee_fixtures import create, details, org  # noqa: F401
from tests.test_attendance_corrections_workflow import team

PERF = "/api/v1/hr/performance"
SETUP = "/api/v1/hr/setup"
HR = ["hr.performance:view", "hr.performance-cycles:manage", "hr.goals:manage", "hr.development-plans:manage"]


def hr(perms=HR):
    return auth(list(perms), roles=["test-hr-all"], name="Pooja HR")


def manager_headers(m, perms=("hr.performance:view", "hr.performance-reviews:assess")):
    return auth(list(perms), employee_id=m["id"], user_id=m["id"], roles=["test-manager"], name=m["display"]["fullName"])


async def setup_lists(client):
    scale = await client.post(f"{SETUP}/rating-scales", json={"name": "Five levels", "levels": [{"value": v, "label": f"Level {v}", "description": ""} for v in range(1, 6)]}, headers=hr())
    assert scale.status_code == 201, scale.text
    comp = await client.post(f"{SETUP}/competencies", json={"name": "Quality focus", "description": "Right first time"}, headers=hr())
    assert comp.status_code == 201, comp.text
    rec = await client.post(f"{SETUP}/performance-recommendations", json={"code": "retain", "label": "Retain in role"}, headers=hr())
    assert rec.status_code == 201, rec.text
    return scale.json(), comp.json(), rec.json()


async def make_cycle(client, scale=None, comps=(), name="FY cycle"):
    today = company_today()
    body = {"name": name, "periodFrom": (today - timedelta(days=60)).isoformat(), "periodTo": (today + timedelta(days=300)).isoformat(),
            "goalSettingDue": (today + timedelta(days=10)).isoformat(), "selfAssessmentDue": (today + timedelta(days=200)).isoformat(),
            "managerReviewDue": (today + timedelta(days=280)).isoformat(), "ratingScaleId": scale["id"] if scale else None, "competencyIds": [c["id"] for c in comps]}
    r = await client.post(f"{PERF}/cycles", json=body, headers=hr())
    assert r.status_code == 201, r.text
    return r.json()


async def advance(client, cycle):
    r = await client.post(f"{PERF}/cycles/{cycle['id']}/advance", json={"version": cycle["version"]}, headers=hr())
    return r


async def test_setup_scales_and_nothing_prefilled(client, org):
    assert (await client.get(f"{PERF}/configuration", headers=hr())).json() == {"ratingScales": [], "competencies": []}
    bad = await client.post(f"{SETUP}/rating-scales", json={"name": "One", "levels": [{"value": 1, "label": "A"}]}, headers=hr())
    assert bad.status_code == 422 and "at least two" in details(bad)["levels"]
    scale, comp, rec = await setup_lists(client)
    cfg = (await client.get(f"{PERF}/configuration", headers=hr())).json()
    assert [lv["value"] for lv in cfg["ratingScales"][0]["levels"]] == [1, 2, 3, 4, 5] and cfg["competencies"][0]["name"] == "Quality focus"
    await make_cycle(client, scale, [comp])
    change = await client.put(f"{SETUP}/rating-scales/{scale['id']}", json={"name": "Five levels", "levels": [{"value": 1, "label": "Low"}, {"value": 2, "label": "High"}], "version": scale["version"]}, headers=hr())
    assert change.status_code == 422 and "cannot change" in details(change)["levels"], "levels are fixed once a cycle uses the scale"
    assert (await client.post(f"{SETUP}/rating-scales", json={"name": "X", "levels": []}, headers=auth(["hr.performance:view"]))).status_code == 403


async def test_cycle_goals_review_and_assessment(client, org):
    manager, employee = await team(client, org)
    scale, comp, rec = await setup_lists(client)
    cycle = await make_cycle(client, scale, [comp])
    assert cycle["status"] == "draft" and cycle["recommendationOptions"] == [{"code": "retain", "label": "Retain in role"}] and cycle["participants"] == 0

    r = await advance(client, cycle)
    assert r.status_code == 200, r.text
    cycle = r.json()
    assert cycle["status"] == "goal_setting" and cycle["participants"] == 2, "one review per employee"
    other = await make_cycle(client, name="Second cycle")
    assert (await advance(client, other)).status_code == 409, "only one cycle runs at a time"

    # Goals: weight total <= 100, due date within the cycle, completed means 100%.
    def goal_body(**over):
        return {"employeeId": employee["id"], "cycleId": cycle["id"], "title": "Reduce rework", "description": "",
                "kpi": {"metric": "Rework", "unit": "%", "baseline": 6, "target": 3, "direction": "decrease"}, "weight": 60,
                "dueDate": (company_today() + timedelta(days=100)).isoformat(), **over}
    g = await client.post(f"{PERF}/goals", json=goal_body(), headers=hr())
    assert g.status_code == 201, g.text
    goal = g.json()
    over = await client.post(f"{PERF}/goals", json=goal_body(title="Second goal", weight=50), headers=hr())
    assert over.status_code == 422 and "cannot exceed 100%" in details(over)["weight"]
    late = await client.post(f"{PERF}/goals", json=goal_body(title="Late goal", weight=None, dueDate=(company_today() + timedelta(days=400)).isoformat()), headers=hr())
    assert late.status_code == 422 and "within the cycle" in details(late)["dueDate"]
    bad = await client.post(f"{PERF}/goals/{goal['id']}/progress", json={"progress": 80, "status": "completed", "value": 4, "note": "", "version": goal["version"]}, headers=hr())
    assert bad.status_code == 422 and details(bad)["progress"] == "A completed goal must be at 100%."
    p = await client.post(f"{PERF}/goals/{goal['id']}/progress", json={"progress": 40, "status": "at_risk", "value": 5, "note": "Supplier issue", "version": goal["version"]}, headers=hr())
    assert p.status_code == 200, p.text
    goal = p.json()
    assert goal["kpi"]["current"] == 5 and goal["updates"][0]["note"] == "Supplier issue" and goal["status"] == "at_risk"
    summary = (await client.get(f"{PERF}/summary", headers=hr())).json()
    assert summary["activeCycle"]["id"] == cycle["id"] and summary["goals"]["atRisk"] == 1 and summary["goalsAtRisk"][0]["id"] == goal["id"]
    assert summary["reviewsByStatus"] == {"not_started": 2, "self_assessment": 0, "manager_review": 0, "completed": 0}

    # Reviews: the reporting manager assesses, only in the manager-review phase.
    reviews = (await client.get(f"{PERF}/reviews", params={"assignedToMe": "true"}, headers=manager_headers(manager))).json()
    assert reviews["meta"]["totalItems"] == 1 and reviews["items"][0]["employee"]["id"] == employee["id"]
    review = (await client.get(f"{PERF}/reviews/{reviews['items'][0]['id']}", headers=manager_headers(manager))).json()
    assert review["canAssess"] is False and review["reviewer"]["id"] == manager["id"] and review["goals"][0]["title"] == "Reduce rework"
    hr_view = (await client.get(f"{PERF}/reviews", params={"cycleId": cycle["id"]}, headers=hr())).json()
    no_manager = next(i for i in hr_view["items"] if i["employee"]["id"] == manager["id"])
    assert no_manager["reviewer"] == {"id": "", "name": "Not assigned"}

    def assessment(**over):
        return {"assessment": {"overallRating": 4, "competencyRatings": [{"competencyId": comp["id"], "rating": 4, "comment": "Consistent"}],
                               "strengths": "Ownership", "improvements": "Delegation", "comments": ""}, "recommendation": "retain", "submit": True, "version": review["version"], **over}
    early = await client.put(f"{PERF}/reviews/{review['id']}/manager-assessment", json=assessment(), headers=manager_headers(manager))
    assert early.status_code == 409, "not in manager review yet"
    for _ in range(2):
        cycle = (await advance(client, cycle)).json()
    assert cycle["status"] == "manager_review"
    review = (await client.get(f"{PERF}/reviews/{review['id']}", headers=manager_headers(manager))).json()
    assert review["canAssess"] is True and review["status"] == "manager_review"
    assert (await client.put(f"{PERF}/reviews/{review['id']}/manager-assessment", json=assessment(), headers=auth(["hr.performance-reviews:assess", "hr.performance:view"],
                                                                                                                        employee_id=employee["id"], user_id=employee["id"], roles=["test-hr-all"]))).status_code == 403
    draft = await client.put(f"{PERF}/reviews/{review['id']}/manager-assessment", json=assessment(submit=False, assessment={"overallRating": None, "competencyRatings": [], "strengths": "Ownership",
                                                                                                                         "improvements": "", "comments": ""}, recommendation=None), headers=manager_headers(manager))
    assert draft.status_code == 200 and draft.json()["status"] == "manager_review" and draft.json()["manager"]["strengths"] == "Ownership", "a draft may be incomplete"
    review = draft.json()
    incomplete = await client.put(f"{PERF}/reviews/{review['id']}/manager-assessment", json=assessment(assessment={"overallRating": 9, "competencyRatings": [], "strengths": "", "improvements": "",
                                                                                                                    "comments": ""}), headers=manager_headers(manager))
    assert incomplete.status_code == 422 and {"assessment.overallRating", "assessment.competencyRatings", "assessment.strengths", "assessment.improvements"} <= set(details(incomplete))
    done = await client.put(f"{PERF}/reviews/{review['id']}/manager-assessment", json=assessment(), headers=manager_headers(manager))
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed" and done.json()["manager"]["submittedAt"] and [h["action"] for h in done.json()["history"]] == ["updated", "submitted"]
    listed = (await client.get(f"{PERF}/reviews", params={"assignedToMe": "true"}, headers=manager_headers(manager))).json()["items"][0]
    assert listed["managerRatingLabel"] == "Level 4" and listed["recommendation"] == "retain"
    assert (await client.put(f"{PERF}/reviews/{review['id']}/manager-assessment", json=assessment(version=done.json()["version"]), headers=manager_headers(manager))).status_code == 409

    cycle = (await advance(client, cycle)).json()
    assert cycle["status"] == "closed" and cycle["completedReviews"] == 1
    assert (await advance(client, cycle)).status_code == 409


async def test_development_plan_completes_when_every_action_is_done(client, org):
    e = await create(client, org, "EVR-1")
    due = (company_today() - timedelta(days=1)).isoformat()
    r = await client.post(f"{PERF}/development-plans", json={"employeeId": e["id"], "title": "Lead auditor path", "focus": "Quality systems",
                                                             "actions": [{"title": "ISO 9001 lead auditor course", "type": "certification", "dueDate": due},
                                                                         {"title": "Shadow two audits", "type": "mentoring", "dueDate": due}]}, headers=hr())
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["status"] == "active" and plan["owner"] == "Pooja HR" and [a["status"] for a in plan["actions"]] == ["planned", "planned"]
    assert (await client.get(f"{PERF}/summary", headers=hr())).json()["overdueDevelopmentActions"] == 2
    for a in plan["actions"]:
        r = await client.patch(f"{PERF}/development-plans/{plan['id']}/actions/{a['id']}", json={"status": "done", "version": plan["version"]}, headers=hr())
        assert r.status_code == 200, r.text
        plan = r.json()
    assert plan["status"] == "completed" and all(a["completedAt"] for a in plan["actions"])
    r = await client.patch(f"{PERF}/development-plans/{plan['id']}/actions/{plan['actions'][0]['id']}", json={"status": "in_progress", "version": plan["version"]}, headers=hr())
    assert r.json()["status"] == "active" and r.json()["actions"][0]["completedAt"] is None
    stale = await client.patch(f"{PERF}/development-plans/{plan['id']}/actions/{plan['actions'][0]['id']}", json={"status": "done", "version": plan["version"]}, headers=hr())
    assert stale.status_code == 409
    assert (await client.get(f"{PERF}/development-plans", params={"status": "active"}, headers=hr())).json()["meta"]["totalItems"] == 1
    assert (await client.post(f"{PERF}/development-plans", json={"employeeId": e["id"], "title": "x", "actions": []}, headers=auth(["hr.performance:view"]))).status_code == 403


async def test_scope_limits_lists(client, org):
    qa = await create(client, org, "EVR-1")
    other = await create(client, org, "EVR-2", dept="PRD")
    cycle = await make_cycle(client)
    await advance(client, cycle)
    qa_hr = auth(["hr.performance:view"], roles=["test-hr-qa"])
    items = (await client.get(f"{PERF}/reviews", headers=qa_hr)).json()["items"]
    assert [i["employee"]["id"] for i in items] == [qa["id"]], "a QA-scoped HR user sees only QA reviews"
    assert len((await client.get(f"{PERF}/reviews", headers=hr())).json()["items"]) == 2
    plan = await client.post(f"{PERF}/development-plans", json={"employeeId": other["id"], "title": "Out of scope", "actions": [{"title": "Course", "type": "training", "dueDate": "2030-01-01"}]},
                             headers=auth(["hr.development-plans:manage"], roles=["test-hr-qa"]))
    assert plan.status_code == 422 and "scope" in details(plan)["employeeId"]
    assert (await client.get(f"{PERF}/summary", headers=auth(["hr.self:view"]))).status_code == 403
