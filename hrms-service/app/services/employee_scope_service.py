"""Organizational scope: which employee records the caller may reach (decision Q12).

Scopes are assigned to Identity roles in HRMS configuration (/hr/setup/employee-access-scopes).
The caller's reach is the union of the active scopes of their roles. No assignment means no
employee records; there are no built-in defaults and no permission bypasses scope.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Principal
from app.models.department_model import Department
from app.models.employee_model import Employee
from app.repositories.employee_access_scope_repository import EmployeeAccessScopeRepository


def caller_employee_id(principal: Principal) -> uuid.UUID | None:
    """The caller's own employee record, from the token's employeeId claim (an HRMS employee ID)."""
    if not principal.employee_id:
        return None
    try:
        return uuid.UUID(str(principal.employee_id))
    except ValueError:
        return None


@dataclass(frozen=True)
class EmployeeScope:
    everyone: bool = False
    department_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    tree_root: uuid.UUID | None = None  # the caller, whose direct and indirect reports are visible
    own_id: uuid.UUID | None = None

    @property
    def empty(self) -> bool:
        return not (self.everyone or self.department_ids or self.tree_root or self.own_id)


def reports_of(root: uuid.UUID):
    """Recursive query of everyone below `root` in the reporting tree (not including root)."""
    tree = select(Employee.id).where(Employee.reporting_manager_id == root).cte("reports", recursive=True)
    tree = tree.union(select(Employee.id).where(Employee.reporting_manager_id == tree.c.id))
    return select(tree.c.id)


class EmployeeScopeService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def resolve(self, principal: Principal) -> EmployeeScope:
        assignments = await EmployeeAccessScopeRepository(self.session).active_for_roles(principal.roles)
        me = caller_employee_id(principal)
        everyone = False
        departments: set[uuid.UUID] = set()
        tree_root = own_id = None
        for a in assignments:
            if a.scope_type == "all":
                everyone = True
            elif a.scope_type == "departments":
                departments.update(a.department_ids)
            elif a.scope_type == "headed_departments" and me:
                departments.update((await self.session.scalars(select(Department.id).where(Department.head_employee_id == me))).all())
            elif a.scope_type == "reporting_tree" and me:
                tree_root = me
            elif a.scope_type == "own_record" and me:
                own_id = me
        return EmployeeScope(everyone, frozenset(departments), tree_root, own_id)

    @staticmethod
    def clause(scope: EmployeeScope) -> ColumnElement[bool]:
        """WHERE clause limiting Employee rows to the scope."""
        if scope.everyone:
            return true()
        parts: list[ColumnElement[bool]] = []
        if scope.department_ids:
            parts.append(Employee.department_id.in_(scope.department_ids))
        if scope.tree_root:
            parts.append(Employee.id.in_(reports_of(scope.tree_root)))
        if scope.own_id:
            parts.append(Employee.id == scope.own_id)
        return or_(*parts) if parts else false()

    async def covers(self, scope: EmployeeScope, *, employee_id: uuid.UUID | None, department_id: uuid.UUID, manager_id: uuid.UUID | None) -> bool:
        """Whether a record with these values would be inside the scope (used before create/edit)."""
        if scope.everyone or department_id in scope.department_ids:
            return True
        if scope.own_id and employee_id == scope.own_id:
            return True
        if scope.tree_root and manager_id:
            return manager_id == scope.tree_root or await self.is_report(scope.tree_root, manager_id)
        return False

    async def is_report(self, root: uuid.UUID, candidate: uuid.UUID) -> bool:
        """True when `candidate` is a direct or indirect report of `root`."""
        reports = reports_of(root).subquery()
        return await self.session.scalar(select(reports.c.id).where(reports.c.id == candidate).limit(1)) is not None
