# Module 8 (Performance): Decisions and Scope

Recorded 2026-11-05, before implementation. The owner asked for Module 8 to start. The design follows contract
**E5** and the owner's standing rules: **no invented business rules; scales, competencies and recommendation options
are HR-entered; unresolved items marked pending.**

## Scope: the 15 frontend endpoints (contract E5)

- `summary`, `configuration`;
- cycles: list, create, advance;
- goals: list, detail, create, record progress;
- reviews: list, detail, manager assessment (draft or submit);
- development plans: list, create, update an action.

**Additions** (no frontend screen to enter them, as in Modules 1–7). HR setup under `/hr/setup`, with `hr.performance-cycles:manage`:
- `rating-scales` (GET, POST, PUT);
- `competencies` (GET, POST, PUT);
- `performance-recommendations` (GET, POST, PUT).

**Nothing is pre-filled:**
- no rating scale, level, competency or recommendation option exists until HR enters it;
- a cycle may have no scale, and then collects written feedback only (E5).

## Rules from the contract

- **No score is ever computed.** Every rating is a level a person chose on the cycle's scale.
- **Cycle phases:** `draft → goal_setting → self_assessment → manager_review → closed`.
  - `advance` moves one phase forward;
  - leaving `draft` gives **409 while another cycle is running** (not draft and not closed);
  - `closed` is final.
- **Goals:**
  - the optional KPI is `{metric, unit, baseline, target, direction}`;
  - `current` is the latest recorded value;
  - the optional weight is refused with 422 when the employee's goals in the cycle total more than 100% (cancelled goals not counted);
  - the due date must fall inside the cycle period.
- **Progress:**
  - progress is 0–100; a completed goal must be at 100%;
  - each update is appended to `updates[]` and never edited.
- **Manager assessment:**
  - a draft may be incomplete;
  - submit requires the overall rating, every competency rating (when the cycle has a scale), strengths, improvements and a recommendation;
  - submit completes the review;
  - only the **assigned reviewer** with `hr.performance-reviews:assess` may assess (`canAssess` is computed by the backend).
- **Development plans:**
  - action types are `training, mentoring, project, certification, other`;
  - action status is `planned / in_progress / done`;
  - the plan completes when every action is done.

## Choices where the contract is silent (pending HR, `HR_CONFIRMATION_PENDING.md` items 118–124)

| # | Question | Built behaviour |
|---|---|---|
| 118 | Who takes part in a cycle | When the cycle leaves `draft`, every employee who joined on or before the period end and is not in an "employment ended" status gets one review (unique per cycle and employee). No tenure or category rule is applied |
| 119 | Who reviews | The employee's reporting manager. Reviews are created with the current manager; when the cycle enters `manager_review`, reviews whose manager assessment has not started take the current reporting manager. An employee without a reporting manager has no reviewer (`reviewer` = `{id: "", name: "Not assigned"}`) until HR sets one |
| 120 | Self-assessment | Not built: no employee self-service screen exists (E-Q7). `self` is null |
| 121 | Review status | Follows the cycle: `not_started`, then `self_assessment` and `manager_review` with the cycle phases; `completed` when the manager submits. Assessment is possible only while the cycle is in `manager_review` |
| 122 | When goals may be created or updated | While the cycle is not closed |
| 123 | Recommendation options of a cycle | The active options when the cycle is created, kept with the cycle |
| 124 | Changing a rating scale | Its levels cannot change once a cycle uses it; name and active flag can |

## Access

| Permission | Allows |
|---|---|
| `hr.performance:view` | Summary, configuration, cycles, goals, reviews and plans, in organizational scope. A reviewer always sees the reviews assigned to them |
| `hr.performance-cycles:manage` | Cycles; scales, competencies and recommendation options (setup) |
| `hr.goals:manage` | Goals and progress (employees in scope) |
| `hr.performance-reviews:assess` | The manager assessment, by the assigned reviewer only |
| `hr.development-plans:manage` | Plans and their actions (employees in scope) |

Every change is written to the audit log. Cycle and review history uses the WorkflowEvent shape.
