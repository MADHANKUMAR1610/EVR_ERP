"""The payroll calculation for one employee and one period. Pure functions on Decimal, no database.

Formula types (decision Q3; every rate, cap and slab is HR-entered):
- fixed:            the monthly amount on the employee's salary record; prorated when `prorate` is on.
- percent:          rate % of a base. Base `GROSS` is the employee's monthly gross for earnings (prorated
                    when `prorate` is on) and the period's total earnings for deductions and employer
                    contributions. Other base codes are the period amounts of components calculated
                    earlier in the structure (already prorated, so not prorated again). `base_cap` caps
                    the base; `max_amount` caps the result.
- balance_of_gross: monthly gross minus the full-month amounts of the other earnings (overtime excluded); prorated when
                    `prorate` is on; never negative.
- overtime_rate:    rate per approved overtime hour (the employee's own rate, else the component's), only
                    when overtime is payable for the employee.
- slab:             the slab whose range holds the base (same bases as percent) gives an amount, or a rate
                    applied to the base.
Every line is rounded to 2 decimals, half up (pending Finance). net = earnings - deductions; employer
contributions are reported, not deducted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
GROSS = "GROSS"


def money(v) -> Decimal:
    return Decimal(str(v)).quantize(CENT, rounding=ROUND_HALF_UP)


def dec(v) -> Decimal | None:
    return None if v is None else Decimal(str(v))


@dataclass(frozen=True)
class ComponentDef:
    id: str
    code: str
    name: str
    type: str  # earning | deduction | employer_contribution
    formula: str
    rate: Decimal | None = None
    base: tuple[str, ...] = ()
    base_cap: Decimal | None = None
    max_amount: Decimal | None = None
    slabs: tuple[dict, ...] = ()
    prorate: bool = False


@dataclass
class Line:
    component: ComponentDef
    amount: Decimal


@dataclass
class Outcome:
    lines: list[Line] = field(default_factory=list)
    gross: Decimal = Decimal("0.00")
    deductions: Decimal = Decimal("0.00")
    employer_contributions: Decimal = Decimal("0.00")
    issues: list[str] = field(default_factory=list)

    @property
    def net(self) -> Decimal:
        return self.gross - self.deductions


def incomplete(c: ComponentDef) -> str | None:
    """Why a component cannot be calculated as configured, or None."""
    if c.formula == "percent" and (c.rate is None or not c.base):
        return f"{c.code}: a percentage component needs a rate and a base"
    if c.formula == "slab" and (not c.slabs or not c.base):
        return f"{c.code}: a slab component needs a base and at least one slab"
    if c.formula == "balance_of_gross" and c.type != "earning":
        return f"{c.code}: balance of gross can only be an earning"
    return None


def _slab(c: ComponentDef, base: Decimal) -> Decimal:
    for s in c.slabs:
        lo = Decimal(str(s["from"]))
        hi = Decimal(str(s["to"])) if s.get("to") is not None else None
        if base >= lo and (hi is None or base <= hi):
            if s.get("amount") is not None:
                return Decimal(str(s["amount"]))
            if s.get("rate") is not None:
                return base * Decimal(str(s["rate"])) / 100
            return Decimal("0")
    return Decimal("0")


def calculate(components: list[ComponentDef], values: dict[str, dict], *, monthly_gross: Decimal | None, factor: Decimal, overtime_hours: Decimal, overtime_payable: bool) -> Outcome:
    """`components` in structure order; `values` = {component_id: {"amount", "rate"}} from the salary
    record; `factor` = paid days / days in period (0..1)."""
    out = Outcome()
    period_amounts: dict[str, Decimal] = {}
    full_amounts: dict[str, Decimal] = {}

    def base_of(c: ComponentDef, for_earning: bool, amounts: dict[str, Decimal]) -> tuple[Decimal, bool]:
        """(base amount, is the monthly gross) for percent and slab components, from `amounts` (the period
        amounts, or the full-month amounts)."""
        total, monthly = Decimal("0"), False
        for code in c.base:
            if code == GROSS:
                if for_earning:
                    total += monthly_gross or Decimal("0")
                    monthly = True
                else:
                    total += sum((v for k, v in amounts.items() if comp_type[k] == "earning"), Decimal("0"))
            else:
                total += amounts.get(code, Decimal("0"))
        if c.base_cap is not None:
            total = min(total, c.base_cap)
        return total, monthly

    comp_type = {c.code: c.type for c in components}
    comp_formula = {c.code: c.formula for c in components}
    order = [c for c in components if c.type == "earning" and c.formula != "balance_of_gross"]
    order += [c for c in components if c.type == "earning" and c.formula == "balance_of_gross"]
    order += [c for c in components if c.type != "earning"]
    for c in order:
        problem = incomplete(c)
        if problem:
            out.issues.append(problem)
            continue
        v = values.get(c.id, {})
        if c.formula == "fixed":
            full = dec(v.get("amount")) or Decimal("0")
            amount = full * factor if c.prorate else full
        elif c.formula == "percent":
            base, monthly = base_of(c, c.type == "earning", period_amounts)
            full_base, _ = base_of(c, c.type == "earning", full_amounts)
            full = full_base * c.rate / 100
            amount = base * c.rate / 100
            if monthly and c.prorate:
                amount = amount * factor
        elif c.formula == "balance_of_gross":
            # Overtime is paid on top of the monthly gross, so it never reduces the balance.
            others = sum((a for k, a in full_amounts.items() if comp_type[k] == "earning" and comp_formula[k] != "overtime_rate"), Decimal("0"))
            full = max((monthly_gross or Decimal("0")) - others, Decimal("0"))
            amount = full * factor if c.prorate else full
        elif c.formula == "overtime_rate":
            rate = dec(v.get("rate")) if v.get("rate") is not None else c.rate
            if overtime_payable and rate is None and overtime_hours > 0:
                out.issues.append(f"{c.code}: no overtime rate for this employee")
            full = amount = (rate or Decimal("0")) * overtime_hours if overtime_payable else Decimal("0")
        else:  # slab
            base, _ = base_of(c, c.type == "earning", period_amounts)
            full_base, _ = base_of(c, c.type == "earning", full_amounts)
            amount, full = _slab(c, base), _slab(c, full_base)
        if c.max_amount is not None:
            amount = min(amount, c.max_amount)
            full = min(full, c.max_amount)
        amount = money(amount)
        full_amounts[c.code] = full
        period_amounts[c.code] = amount
        out.lines.append(Line(c, amount))
        if c.type == "earning":
            out.gross += amount
        elif c.type == "deduction":
            out.deductions += amount
        else:
            out.employer_contributions += amount
    # Lines in structure order for display.
    position = {c.id: i for i, c in enumerate(components)}
    out.lines.sort(key=lambda line: position[line.component.id])
    return out


def describe(c: ComponentDef, names: dict[str, str] | None = None) -> str:
    """Human-readable rule (the contract's `rule` text)."""
    names = names or {}
    base = " + ".join("gross" if b == GROSS else names.get(b, b) for b in c.base) or "—"
    cap = f", base capped at {c.base_cap:,.2f}" if c.base_cap is not None else ""
    mx = f", at most {c.max_amount:,.2f}" if c.max_amount is not None else ""
    pr = ", prorated by paid days" if c.prorate and c.formula in ("fixed", "balance_of_gross", "percent") else ""
    if c.formula == "fixed":
        return f"Fixed monthly amount per employee{pr}{mx}"
    if c.formula == "percent":
        return (f"{c.rate:g}% of {base}{cap}{pr}{mx}" if c.rate is not None else f"Percentage of {base} (rate not set){cap}")
    if c.formula == "balance_of_gross":
        return f"Monthly gross minus the other earnings{pr}"
    if c.formula == "overtime_rate":
        return f"{c.rate:,.2f} per approved overtime hour (or the employee's own rate)" if c.rate is not None else "Employee's rate per approved overtime hour"
    slabs = "; ".join(f"{Decimal(str(s['from'])):,.2f}–{'' if s.get('to') is None else format(Decimal(str(s['to'])), ',.2f')}: "
                      f"{format(Decimal(str(s['amount'])), ',.2f') if s.get('amount') is not None else str(s.get('rate')) + '%'}" for s in c.slabs)
    return f"Slab on {base}{cap}: {slabs or 'no slabs set'}{mx}"
