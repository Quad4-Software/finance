"""Assemble the content of the two downloadable documents.

This module gathers data; it draws nothing. Every number comes from the
same services the app surfaces use (reports, dashboard, goals, budgets,
recurring schedules), so a downloaded document cannot drift into telling a
different story from the screens the user already sees.

Both documents share one structure - a title block plus a list of sections,
each section a list of typed blocks (kpis, line, bars, table, note). The
renderers in document_render walk that structure, which keeps the PDF and
the HTML output visually identical by construction.
"""
import calendar
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_clock import app_today
from app.core.config import get_settings
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.document import DocumentGenerateRequest
from app.services import (
    budget_service,
    dashboard_service,
    goal_service,
    recurring_transaction_service,
    report_service,
    transaction_service,
)
from app.services.fx_rate_service import convert, convert_or_none

REPORT_SECTIONS = (
    "net_worth",
    "income_expenses",
    "account_balances",
    "large_transactions",
    "recurring_obligations",
)
PLAN_SECTIONS = (
    "goals",
    "budgets",
    "recurring_forecast",
    "savings_suggestion",
)

#: Section titles are fixed product copy, not user data: a document that
#: renamed its own sections per request would read inconsistently with the
#: Reports page it is generated from.
REPORT_SECTION_TITLES = {
    "net_worth": "Net worth",
    "income_expenses": "Income vs expenses",
    "account_balances": "Account balances by type",
    "large_transactions": "Recent large transactions",
    "recurring_obligations": "Recurring obligations",
}
PLAN_SECTION_TITLES = {
    "goals": "Goals",
    "budgets": "Budgets vs actuals",
    "recurring_forecast": "Recurring transaction forecast",
    "savings_suggestion": "Suggested monthly savings",
}

_TOP_CATEGORIES = 8
_LARGE_TRANSACTIONS = 10
_FORECAST_MONTHS = 3
_TRAILING_MONTHS = 3

#: Rough month-length factors for normalizing recurring schedules to a
#: monthly figure. Honest enough for a summary table; the per-month forecast
#: section uses real occurrence expansion instead.
_MONTHLY_FACTORS = {
    "weekly": Decimal("4.345"),
    "biweekly": Decimal("2.1725"),
    "monthly": Decimal("1"),
    "quarterly": Decimal("0.3333"),
    "semiannual": Decimal("0.1667"),
    "yearly": Decimal("0.0833"),
}


@dataclass
class DocumentSection:
    key: str
    title: str
    blocks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FinanceDocument:
    kind: str  # "report" or "plan"
    title: str
    subtitle: str
    currency: str
    generated_on: date
    period_label: str
    sections: list[DocumentSection] = field(default_factory=list)


def resolve_window(
    period: str,
    start_date: Optional[date],
    end_date: Optional[date],
    today: date,
    financial_year_start_month: int = 1,
) -> tuple[date, date]:
    """Resolve the requested period selector to a concrete [start, end] range.

    Raises ValueError for a malformed custom range - the API layer turns it
    into a 422.
    """
    first_of_month = today.replace(day=1)

    if period == "last_month":
        end = first_of_month - timedelta(days=1)
        return end.replace(day=1), end

    if period == "last_quarter":
        # The previous whole calendar quarter, e.g. Q1 when today is in Q2.
        quarter_first_month = ((today.month - 1) // 3) * 3 + 1
        quarter_start = date(today.year, quarter_first_month, 1)
        end = quarter_start - timedelta(days=1)
        return end.replace(day=1), end

    if period == "ytd":
        if not 1 <= financial_year_start_month <= 12:
            raise ValueError("financial_year_start_month must be between 1 and 12")
        year = today.year - (today.month < financial_year_start_month)
        return date(year, financial_year_start_month, 1), today

    if period == "custom":
        if start_date is None or end_date is None:
            raise ValueError("start_date and end_date are required for a custom period")
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        if end_date > today:
            raise ValueError("end_date must be on or before today")
        if end_date > start_date.replace(year=start_date.year + 10):
            raise ValueError("Custom range is too wide (max 10 years)")
        return start_date, end_date

    raise ValueError(f"Unknown period: {period}")


def _interval_for(start: date, end: date) -> str:
    # Weekly stays out: the report service buckets it with extract('isoyear'),
    # which not every database can compile, and a download endpoint cannot
    # afford a window-dependent failure.
    span = (end - start).days
    if span <= 45:
        return "daily"
    return "monthly"


_PERIOD_LABELS = {
    "last_month": "Last month",
    "last_quarter": "Last quarter",
    "ytd": "Year to date",
}


def _section_enabled(request: DocumentGenerateRequest, key: str) -> bool:
    return request.sections is None or key in request.sections


def _money(value: float, currency: str) -> str:
    return f"{currency} {value:,.2f}"


def _signed_money(value: float, currency: str) -> str:
    sign = "+" if value > 0 else "-" if value < 0 else ""
    return f"{sign}{currency} {abs(value):,.2f}"


def _pct(value: float) -> str:
    return f"{value:.0f}%"


def _month_label(month_start: date) -> str:
    return f"{calendar.month_abbr[month_start.month]} {month_start.year}"


class _Display:
    """Convert primary-currency floats into the document's display currency.

    One rate for the whole document, resolved at the period end. When the
    workspace has no rate for the pair the display currency falls back to
    primary, so numbers are never dressed up in the wrong code.
    """

    def __init__(self, currency: str, factor: float):
        self.currency = currency
        self.factor = factor

    def amount(self, value: float) -> float:
        return value * self.factor

    def money(self, value: float) -> str:
        return _money(self.amount(value), self.currency)

    def signed_money(self, value: float) -> str:
        return _signed_money(self.amount(value), self.currency)


async def _display(session: AsyncSession, primary: str, requested: Optional[str], at: date) -> _Display:
    if not requested or requested == primary:
        return _Display(primary, 1.0)
    _, rate = await convert_or_none(session, Decimal("1"), primary, requested, at)
    if rate is None:
        return _Display(primary, 1.0)
    return _Display(requested, float(rate))


async def _primary_currency(session: AsyncSession, user_id: uuid.UUID) -> str:
    user = await session.get(User, user_id)
    return user.primary_currency if user else get_settings().default_currency


# ---------------------------------------------------------------------------
# Shared section builders
# ---------------------------------------------------------------------------
async def _recurring_rows(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    display: _Display,
) -> tuple[list[list[str]], float, float]:
    """Active schedules as table rows plus monthly-normalized totals."""
    recurring = await recurring_transaction_service.get_recurring_transactions(
        session, workspace_id
    )
    today = app_today()
    monthly_in = 0.0
    monthly_out = 0.0
    rows: list[list[str]] = []
    for rec in recurring:
        if not rec.is_active:
            continue
        factor = _MONTHLY_FACTORS.get(rec.frequency, Decimal("1"))
        monthly = Decimal(rec.amount) * factor
        converted, _ = await convert(
            session, monthly, rec.currency, display.currency, today
        )
        value = float(converted)
        if rec.type == "credit":
            monthly_in += value
            signed = value
        else:
            monthly_out += value
            signed = -value
        rows.append([
            rec.description,
            rec.frequency,
            rec.next_occurrence.isoformat(),
            _signed_money(signed, display.currency) + " /mo",
        ])
    return rows, monthly_in, monthly_out


def _recurring_section(rows: list[list[str]], monthly_in: float, monthly_out: float, display: _Display) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [{
        "type": "kpis",
        "items": [
            {"label": "Expected in / month", "value": _money(monthly_in, display.currency), "hint": None},
            {"label": "Obligations / month", "value": _money(monthly_out, display.currency), "hint": None},
            {"label": "Net / month", "value": _signed_money(monthly_in - monthly_out, display.currency), "hint": None},
        ],
    }]
    if rows:
        blocks.append({
            "type": "table",
            "columns": [
                {"label": "Description", "align": "left"},
                {"label": "Frequency", "align": "left"},
                {"label": "Next", "align": "left"},
                {"label": "Monthly estimate", "align": "right"},
            ],
            "rows": rows,
        })
    else:
        blocks.append({"type": "note", "text": "No active recurring transactions."})
    blocks.append({
        "type": "note",
        "text": "Monthly figures are estimates: irregular schedules are averaged over the year.",
    })
    return blocks


# ---------------------------------------------------------------------------
# Financial report
# ---------------------------------------------------------------------------
async def build_report_document(
    session: AsyncSession,
    workspace: Workspace,
    user_id: uuid.UUID,
    request: DocumentGenerateRequest,
    financial_year_start_month: int = 1,
) -> FinanceDocument:
    today = app_today()
    start, end = resolve_window(
        request.period, request.start_date, request.end_date, today, financial_year_start_month
    )
    interval = _interval_for(start, end)
    primary = await _primary_currency(session, user_id)
    display = await _display(session, primary, request.currency, end)

    document = FinanceDocument(
        kind="report",
        title=request.title or "Financial report",
        subtitle=request.subtitle or f"{workspace.name} - {_PERIOD_LABELS.get(request.period, 'Custom period')}",
        currency=display.currency,
        generated_on=today,
        period_label=f"{start.isoformat()} to {end.isoformat()}",
    )

    if _section_enabled(request, "net_worth"):
        report = await report_service.get_net_worth_report(
            session, workspace.id, user_id, months=12, interval=interval,
            currency=primary, start_date=start, end_date=end,
        )
        summary = report.summary
        breakdown = {b.key: b.value for b in summary.breakdowns}
        change_hint = (
            f"{summary.change_percent:+.1f}% over the period"
            if summary.change_percent is not None
            else None
        )
        blocks: list[dict[str, Any]] = [{
            "type": "kpis",
            "items": [
                {"label": "Net worth", "value": display.money(summary.primary_value), "hint": None},
                {"label": "Change", "value": display.signed_money(summary.change_amount), "hint": change_hint},
                {"label": "Accounts", "value": display.money(breakdown.get("accounts", 0.0)), "hint": None},
                {"label": "Assets", "value": display.money(breakdown.get("assets", 0.0)), "hint": None},
                {"label": "Liabilities", "value": display.money(breakdown.get("liabilities", 0.0)), "hint": None},
            ],
        }]
        if report.trend:
            blocks.append({
                "type": "line",
                "series": [{
                    "name": "Net worth",
                    "points": [{"label": p.date, "value": display.amount(p.value)} for p in report.trend],
                }],
            })
        document.sections.append(DocumentSection(
            key="net_worth", title=REPORT_SECTION_TITLES["net_worth"], blocks=blocks,
        ))

    if _section_enabled(request, "income_expenses"):
        report = await report_service.get_income_expenses_report(
            session, workspace.id, user_id, months=12, interval=interval,
            currency=primary, start_date=start, end_date=end,
        )
        breakdown = {b.key: b.value for b in report.summary.breakdowns}
        blocks = [{
            "type": "kpis",
            "items": [
                {"label": "Income", "value": display.money(breakdown.get("income", 0.0)), "hint": None},
                {"label": "Expenses", "value": display.money(breakdown.get("expenses", 0.0)), "hint": None},
                {"label": "Net income", "value": display.signed_money(breakdown.get("netIncome", 0.0)), "hint": None},
            ],
        }]
        if report.trend:
            blocks.append({
                "type": "line",
                "series": [
                    {
                        "name": "Income",
                        "points": [
                            {"label": p.date, "value": display.amount(p.breakdowns.get("income", 0.0))}
                            for p in report.trend
                        ],
                    },
                    {
                        "name": "Expenses",
                        "points": [
                            {"label": p.date, "value": display.amount(p.breakdowns.get("expenses", 0.0))}
                            for p in report.trend
                        ],
                    },
                ],
            })
        spending = [c for c in report.composition if c.group == "expenses"]
        spending.sort(key=lambda c: c.value, reverse=True)
        top = spending[:_TOP_CATEGORIES]
        if top:
            blocks.append({
                "type": "bars",
                "label": "Top spending categories",
                "items": [
                    {"label": c.label, "value": display.amount(c.value), "display": display.money(c.value)}
                    for c in top
                ],
            })
        document.sections.append(DocumentSection(
            key="income_expenses", title=REPORT_SECTION_TITLES["income_expenses"], blocks=blocks,
        ))

    if _section_enabled(request, "account_balances"):
        accounts = await dashboard_service._get_open_accounts(session, workspace.id)
        totals: dict[str, tuple[int, float]] = {}
        for account in accounts:
            balance = await dashboard_service._account_balance_at(session, account, end)
            converted, _ = await convert(
                session, Decimal(str(balance)), account.currency, display.currency, end
            )
            value = float(converted)
            if account.type == "credit_card":
                value = -value
            count, total = totals.get(account.type, (0, 0.0))
            totals[account.type] = (count + 1, total + value)
        rows = []
        items = []
        for account_type in sorted(totals, key=lambda t: -abs(totals[t][1])):
            count, total = totals[account_type]
            label = account_type.replace("_", " ").capitalize()
            rows.append([label, str(count), _signed_money(total, display.currency)])
            items.append({
                "label": label,
                "value": abs(total),
                "display": _signed_money(total, display.currency),
            })
        blocks = []
        if items:
            blocks.append({"type": "bars", "items": items})
            blocks.append({
                "type": "table",
                "columns": [
                    {"label": "Account type", "align": "left"},
                    {"label": "Accounts", "align": "right"},
                    {"label": "Balance", "align": "right"},
                ],
                "rows": rows,
            })
            blocks.append({
                "type": "note",
                "text": "Credit card figures are amounts owed, shown as negative.",
            })
        else:
            blocks.append({"type": "note", "text": "No open accounts."})
        document.sections.append(DocumentSection(
            key="account_balances", title=REPORT_SECTION_TITLES["account_balances"], blocks=blocks,
        ))

    if _section_enabled(request, "large_transactions"):
        transactions, _, _ = await transaction_service.get_transactions(
            session, workspace.id, user_id,
            from_date=start, to_date=end,
            sort_by="amount", sort_dir="desc",
            limit=_LARGE_TRANSACTIONS,
            exclude_transfers=True,
            status="posted",
        )
        rows = []
        for tx in transactions:
            if tx.amount_primary is not None:
                amount = float(tx.amount_primary)
                code = display.currency
                amount = display.amount(amount)
            else:
                converted, rate = await convert_or_none(
                    session, tx.amount, tx.currency, display.currency, tx.date
                )
                if converted is None:
                    amount = float(tx.amount)
                    code = tx.currency
                else:
                    amount = float(converted)
                    code = display.currency
            signed = amount if tx.type == "credit" else -amount
            name = tx.payee_name or tx.description
            rows.append([
                tx.date.isoformat(),
                name,
                tx.account.name if tx.account else "",
                _signed_money(signed, code),
            ])
        blocks = []
        if rows:
            blocks.append({
                "type": "table",
                "columns": [
                    {"label": "Date", "align": "left"},
                    {"label": "Description", "align": "left"},
                    {"label": "Account", "align": "left"},
                    {"label": "Amount", "align": "right"},
                ],
                "rows": rows,
            })
            blocks.append({
                "type": "note",
                "text": f"The {_LARGE_TRANSACTIONS} largest posted transactions in the period.",
            })
        else:
            blocks.append({"type": "note", "text": "No transactions in the period."})
        document.sections.append(DocumentSection(
            key="large_transactions", title=REPORT_SECTION_TITLES["large_transactions"], blocks=blocks,
        ))

    if _section_enabled(request, "recurring_obligations"):
        rows, monthly_in, monthly_out = await _recurring_rows(session, workspace.id, display)
        document.sections.append(DocumentSection(
            key="recurring_obligations",
            title=REPORT_SECTION_TITLES["recurring_obligations"],
            blocks=_recurring_section(rows, monthly_in, monthly_out, display),
        ))

    return document


# ---------------------------------------------------------------------------
# Financial plan
# ---------------------------------------------------------------------------
async def build_plan_document(
    session: AsyncSession,
    workspace: Workspace,
    user_id: uuid.UUID,
    request: DocumentGenerateRequest,
    financial_year_start_month: int = 1,
) -> FinanceDocument:
    today = app_today()
    start, end = resolve_window(
        request.period, request.start_date, request.end_date, today, financial_year_start_month
    )
    primary = await _primary_currency(session, user_id)
    display = await _display(session, primary, request.currency, end)

    document = FinanceDocument(
        kind="plan",
        title=request.title or "Financial plan",
        subtitle=request.subtitle or f"{workspace.name} - generated {today.isoformat()}",
        currency=display.currency,
        generated_on=today,
        period_label=f"{start.isoformat()} to {end.isoformat()}",
    )

    if _section_enabled(request, "goals"):
        goals = await goal_service.get_goals(session, workspace.id, user_id)
        active = [g for g in goals if g.status in ("active", "paused")]
        rows = []
        items = []
        for goal in active:
            current = float(goal.current_amount_primary or goal.current_amount)
            target = float(goal.target_amount_primary or goal.target_amount)
            remaining = max(0.0, target - current)
            if goal.on_track == "achieved" or remaining == 0:
                estimate = "Done"
            elif goal.monthly_contribution and goal.monthly_contribution > 0:
                months_left = remaining / goal.monthly_contribution
                completion = today + timedelta(days=months_left * 30.44)
                estimate = f"{_month_label(completion)} (estimate)"
            elif goal.target_date:
                estimate = "No tracked contribution rate"
            else:
                estimate = "No estimate"
            rows.append([
                goal.name,
                display.money(current),
                display.money(target),
                _pct(goal.percentage),
                goal.target_date.isoformat() if goal.target_date else "-",
                estimate,
            ])
            items.append({"label": goal.name, "value": min(goal.percentage, 100.0), "display": _pct(goal.percentage)})
        blocks: list[dict[str, Any]] = []
        if rows:
            if items:
                blocks.append({"type": "bars", "label": "Progress", "items": items})
            blocks.append({
                "type": "table",
                "columns": [
                    {"label": "Goal", "align": "left"},
                    {"label": "Current", "align": "right"},
                    {"label": "Target", "align": "right"},
                    {"label": "Done", "align": "right"},
                    {"label": "Target date", "align": "left"},
                    {"label": "Projected completion", "align": "left"},
                ],
                "rows": rows,
            })
        else:
            blocks.append({"type": "note", "text": "No active goals."})
        blocks.append({
            "type": "note",
            "text": "Projected completion is an estimate from the tracked contribution rate; it is not a commitment.",
        })
        document.sections.append(DocumentSection(
            key="goals", title=PLAN_SECTION_TITLES["goals"], blocks=blocks,
        ))

    if _section_enabled(request, "budgets"):
        vs_actual = await budget_service.get_budget_vs_actual(session, workspace.id, user_id)
        rows = []
        total_budget = 0.0
        total_actual = 0.0
        for row in vs_actual:
            if row.budget_amount is None:
                continue
            budget = display.amount(float(row.budget_amount))
            actual = display.amount(float(row.actual_amount))
            total_budget += budget
            total_actual += actual
            used = (actual / budget * 100) if budget > 0 else None
            rows.append([
                row.category_name,
                _money(budget, display.currency),
                _money(actual, display.currency),
                _pct(used) if used is not None else "-",
            ])
        blocks = []
        if rows:
            month_label = _month_label(today.replace(day=1))
            blocks.append({
                "type": "kpis",
                "items": [
                    {"label": f"Budgeted ({month_label})", "value": _money(total_budget, display.currency), "hint": None},
                    {"label": "Spent so far", "value": _money(total_actual, display.currency), "hint": None},
                    {"label": "Remaining", "value": _signed_money(total_budget - total_actual, display.currency), "hint": None},
                ],
            })
            blocks.append({
                "type": "table",
                "columns": [
                    {"label": "Category", "align": "left"},
                    {"label": "Budget", "align": "right"},
                    {"label": "Actual", "align": "right"},
                    {"label": "Used", "align": "right"},
                ],
                "rows": rows,
            })
        else:
            blocks.append({"type": "note", "text": "No budgets set for this month."})
        document.sections.append(DocumentSection(
            key="budgets", title=PLAN_SECTION_TITLES["budgets"], blocks=blocks,
        ))

    if _section_enabled(request, "recurring_forecast"):
        months: list[tuple[str, float, float]] = []
        cursor = today.replace(day=1)
        for _ in range(_FORECAST_MONTHS):
            # _month_range returns the exclusive end: the first of next month.
            month_start, month_end = dashboard_service._month_range(cursor)
            projections = await dashboard_service._get_recurring_projections(
                session, workspace.id, month_start, month_end
            )
            month_in = 0.0
            month_out = 0.0
            for proj in projections:
                converted, _ = await convert(
                    session, Decimal(str(proj["amount"])), proj["currency"], display.currency, today
                )
                if proj["type"] == "credit":
                    month_in += float(converted)
                else:
                    month_out += float(converted)
            months.append((_month_label(month_start), month_in, month_out))
            if cursor.month == 12:
                cursor = date(cursor.year + 1, 1, 1)
            else:
                cursor = date(cursor.year, cursor.month + 1, 1)
        blocks = []
        if any(month_in or month_out for _, month_in, month_out in months):
            blocks.append({
                "type": "table",
                "columns": [
                    {"label": "Month", "align": "left"},
                    {"label": "Projected in", "align": "right"},
                    {"label": "Projected out", "align": "right"},
                    {"label": "Net", "align": "right"},
                ],
                "rows": [
                    [
                        label,
                        _money(month_in, display.currency),
                        _money(month_out, display.currency),
                        _signed_money(month_in - month_out, display.currency),
                    ]
                    for label, month_in, month_out in months
                ],
            })
        else:
            blocks.append({"type": "note", "text": "No active recurring transactions."})
        blocks.append({
            "type": "note",
            "text": "Projections assume every active schedule repeats as configured; they are estimates, not guarantees.",
        })
        document.sections.append(DocumentSection(
            key="recurring_forecast", title=PLAN_SECTION_TITLES["recurring_forecast"], blocks=blocks,
        ))

    if _section_enabled(request, "savings_suggestion"):
        trailing_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        for _ in range(_TRAILING_MONTHS - 1):
            trailing_start = (trailing_start - timedelta(days=1)).replace(day=1)
        report = await report_service.get_income_expenses_report(
            session, workspace.id, user_id, months=_TRAILING_MONTHS, interval="monthly",
            currency=primary, start_date=trailing_start, end_date=today,
        )
        points = report.trend[-_TRAILING_MONTHS:]
        if points:
            avg_income = sum(p.breakdowns.get("income", 0.0) for p in points) / len(points)
            avg_expenses = sum(p.breakdowns.get("expenses", 0.0) for p in points) / len(points)
        else:
            avg_income = avg_expenses = 0.0
        avg_net = avg_income - avg_expenses
        suggested = max(0.0, avg_net)
        blocks = [{
            "type": "kpis",
            "items": [
                {"label": "Avg monthly income", "value": display.money(avg_income), "hint": f"last {len(points) or _TRAILING_MONTHS} months"},
                {"label": "Avg monthly expenses", "value": display.money(avg_expenses), "hint": f"last {len(points) or _TRAILING_MONTHS} months"},
                {"label": "Avg monthly net", "value": display.signed_money(avg_net), "hint": None},
                {"label": "Suggested monthly savings", "value": display.money(suggested), "hint": "estimate"},
            ],
        }]
        if avg_net > 0:
            text = (
                "The trailing average leaves a monthly surplus. Directing it at "
                "goals or savings would move them forward at roughly that rate."
            )
        else:
            text = (
                "The trailing average leaves no monthly surplus. Closing the gap "
                "between income and expenses comes before a savings target."
            )
        blocks.append({
            "type": "note",
            "text": text + " Estimates from recent history, not advice or a guarantee.",
        })
        document.sections.append(DocumentSection(
            key="savings_suggestion", title=PLAN_SECTION_TITLES["savings_suggestion"], blocks=blocks,
        ))

    return document
