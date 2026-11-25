"""Finance HTTP API routes (§3) over :class:`FinanceService`.

Typed request/response schemas (OpenAPI-documented), exact-Decimal money carried as
STRINGS over the wire (no float ever), pagination/date filtering, and structured
HTTP errors instead of fabricated financial results. No SQL or shell is exposed; the
routes only call the finance application service. Enforcement of broader
authorization is layered above this (the independent assurance gateway governs
research answers; finance mutations are scoped to the service instance).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from strix.finance.categorize import DEFAULT_RULES, categorize
from strix.finance.ledger import AccountType, FinanceError
from strix.finance.service import FinanceService
from strix.native.arithmetic import NumericalContractError, as_decimal

# --- request schemas -------------------------------------------------------


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    account_type: str
    owner: str = Field(min_length=1, max_length=200)
    institution: str = Field(default="", max_length=200)
    mask: str = Field(default="", max_length=8)
    currency: str = Field(default="USD", max_length=8)
    #: Decimal as a string (never a JSON float).
    opening_balance: str = "0"


class TransactionCreate(BaseModel):
    account_id: str = Field(min_length=1)
    posted_date: date
    #: Signed Decimal as a string; negative = outflow.
    amount: str
    description: str = Field(default="", max_length=500)


# --- response schemas ------------------------------------------------------


class AccountOut(BaseModel):
    account_id: str
    name: str
    account_type: str
    owner: str
    institution: str
    mask: str
    currency: str
    status: str
    opening_balance: str


class AccountListOut(BaseModel):
    accounts: list[AccountOut]


class TransactionOut(BaseModel):
    txn_id: str
    account_id: str
    posted_date: date
    amount: str
    description: str
    owned: bool
    category: str


class BudgetCreate(BaseModel):
    category: str = Field(min_length=1, max_length=64)
    #: Positive Decimal as a string.
    monthly_limit: str
    period: str = Field(pattern=r"^\d{4}-\d{2}$")


class BudgetOut(BaseModel):
    category: str
    monthly_limit: str
    period: str


class BudgetListOut(BaseModel):
    budgets: list[BudgetOut]


class BudgetVarianceOut(BaseModel):
    category: str
    limit: str
    actual: str
    variance: str
    over_budget: bool


class BudgetVarianceListOut(BaseModel):
    variances: list[BudgetVarianceOut]


class TransactionPageOut(BaseModel):
    items: list[TransactionOut]
    total: int
    limit: int
    offset: int


class AccountBalanceOut(BaseModel):
    account_id: str
    name: str
    account_type: str
    balance: str


class NetWorthOut(BaseModel):
    assets_total: str
    liabilities_total: str
    net_worth: str
    accounts: list[AccountBalanceOut]


class IncomeExpenseOut(BaseModel):
    start: date
    end: date
    inflow: str
    outflow: str
    net: str
    transaction_count: int


# --- helpers ---------------------------------------------------------------


#: Magnitude/precision ceilings for a money value. Bounding at the write boundary
#: prevents an astronomical-but-finite Decimal (e.g. ``1E+2000000``) from being
#: stored and later crashing summation with an uncaught ``decimal.Overflow``, or
#: a multi-megabyte-digit value from exhausting CPU/memory under the service lock.
MAX_MONEY_SIGNIFICANT_DIGITS = 28
MAX_MONEY_ADJUSTED_EXPONENT = 24  # |value| < 1e25


def _money(raw: str, field: str) -> object:
    try:
        value = as_decimal(raw)
    except NumericalContractError as exc:
        raise HTTPException(status_code=400, detail=f"invalid {field}: {exc}") from exc
    _, digits, _ = value.as_tuple()
    too_precise = len(digits) > MAX_MONEY_SIGNIFICANT_DIGITS
    too_large = abs(value.adjusted()) > MAX_MONEY_ADJUSTED_EXPONENT
    if too_precise or too_large:
        raise HTTPException(
            status_code=400,
            detail=f"{field} magnitude/precision out of range for a monetary value",
        )
    return value


def _account_type(raw: str) -> AccountType:
    try:
        return AccountType(raw)
    except ValueError as exc:
        valid = ", ".join(t.value for t in AccountType)
        raise HTTPException(
            status_code=400, detail=f"invalid account_type {raw!r}; expected one of: {valid}"
        ) from exc


def _account_out(record: object) -> AccountOut:
    return AccountOut(
        account_id=record.account_id,  # type: ignore[attr-defined]
        name=record.name,  # type: ignore[attr-defined]
        account_type=record.account_type.value,  # type: ignore[attr-defined]
        owner=record.owner,  # type: ignore[attr-defined]
        institution=record.institution,  # type: ignore[attr-defined]
        mask=record.mask,  # type: ignore[attr-defined]
        currency=record.currency,  # type: ignore[attr-defined]
        status=record.status.value,  # type: ignore[attr-defined]
        opening_balance=str(record.opening_balance),  # type: ignore[attr-defined]
    )


def _txn_out(txn: object) -> TransactionOut:
    return TransactionOut(
        txn_id=txn.txn_id,  # type: ignore[attr-defined]
        account_id=txn.account_id,  # type: ignore[attr-defined]
        posted_date=txn.posted_date,  # type: ignore[attr-defined]
        amount=str(txn.amount),  # type: ignore[attr-defined]
        description=txn.description,  # type: ignore[attr-defined]
        owned=txn.owned,  # type: ignore[attr-defined]
        category=categorize(txn, DEFAULT_RULES).value,  # type: ignore[arg-type]
    )


# --- operations (server-independent; directly unit-testable) ---------------


def create_account_op(service: FinanceService, body: AccountCreate) -> AccountOut:
    try:
        record = service.add_account(
            name=body.name,
            account_type=_account_type(body.account_type),
            owner=body.owner,
            institution=body.institution,
            mask=body.mask,
            currency=body.currency,
            opening_balance=_money(body.opening_balance, "opening_balance"),  # type: ignore[arg-type]
        )
    except FinanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _account_out(record)


def list_accounts_op(service: FinanceService, owner: str | None) -> AccountListOut:
    return AccountListOut(accounts=[_account_out(r) for r in service.list_accounts(owner=owner)])


def get_account_op(service: FinanceService, account_id: str) -> AccountOut:
    try:
        return _account_out(service.get_account(account_id))
    except FinanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def create_transaction_op(service: FinanceService, body: TransactionCreate) -> TransactionOut:
    try:
        txn = service.add_transaction(
            account_id=body.account_id,
            posted_date=body.posted_date,
            amount=_money(body.amount, "amount"),  # type: ignore[arg-type]
            description=body.description,
        )
    except FinanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _txn_out(txn)


def list_transactions_op(
    service: FinanceService,
    *,
    account_id: str | None,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> TransactionPageOut:
    try:
        page = service.list_transactions(
            account_id=account_id, start=start, end=end, limit=limit, offset=offset
        )
    except FinanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TransactionPageOut(
        items=[_txn_out(t) for t in page.items],
        total=page.total, limit=page.limit, offset=page.offset,
    )


def set_budget_op(service: FinanceService, body: BudgetCreate) -> BudgetOut:
    try:
        budget = service.set_budget(
            category=body.category,
            monthly_limit=_money(body.monthly_limit, "monthly_limit"),  # type: ignore[arg-type]
            period=body.period,
        )
    except (FinanceError, ValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BudgetOut(
        category=budget.category, monthly_limit=str(budget.monthly_limit), period=budget.period
    )


def list_budgets_op(service: FinanceService, period: str | None) -> BudgetListOut:
    return BudgetListOut(
        budgets=[
            BudgetOut(category=b.category, monthly_limit=str(b.monthly_limit), period=b.period)
            for b in service.list_budgets(period=period)
        ]
    )


def budget_variance_op(service: FinanceService, period: str) -> BudgetVarianceListOut:
    return BudgetVarianceListOut(
        variances=[
            BudgetVarianceOut(
                category=v.category, limit=str(v.limit), actual=str(v.actual),
                variance=str(v.variance), over_budget=v.over_budget,
            )
            for v in service.budget_variance(period=period)
        ]
    )


def net_worth_op(service: FinanceService) -> NetWorthOut:
    nw = service.net_worth()
    return NetWorthOut(
        assets_total=str(nw.assets_total),
        liabilities_total=str(nw.liabilities_total),
        net_worth=str(nw.net_worth),
        accounts=[
            AccountBalanceOut(
                account_id=a.account_id, name=a.name,
                account_type=a.account_type.value, balance=str(a.balance),
            )
            for a in nw.accounts
        ],
    )


def income_expense_op(
    service: FinanceService, *, start: date, end: date, owner: str | None
) -> IncomeExpenseOut:
    try:
        s = service.income_expense_summary(start=start, end=end, owner=owner)
    except FinanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IncomeExpenseOut(
        start=s.start, end=s.end, inflow=str(s.inflow), outflow=str(s.outflow),
        net=str(s.net), transaction_count=s.transaction_count,
    )


# --- route registration (thin wrappers over the operations) ----------------


def register_finance_routes(app: FastAPI, service: FinanceService) -> None:
    """Attach the ``/api/finance`` routes backed by ``service``."""

    @app.post("/api/finance/accounts", response_model=AccountOut)
    def create_account(body: AccountCreate) -> AccountOut:
        return create_account_op(service, body)

    @app.get("/api/finance/accounts", response_model=AccountListOut)
    def list_accounts(owner: Annotated[str | None, Query()] = None) -> AccountListOut:
        return list_accounts_op(service, owner)

    @app.get("/api/finance/accounts/{account_id}", response_model=AccountOut)
    def get_account(account_id: str) -> AccountOut:
        return get_account_op(service, account_id)

    @app.post("/api/finance/transactions", response_model=TransactionOut)
    def create_transaction(body: TransactionCreate) -> TransactionOut:
        return create_transaction_op(service, body)

    @app.get("/api/finance/transactions", response_model=TransactionPageOut)
    def list_transactions(
        account_id: Annotated[str | None, Query()] = None,
        start: Annotated[date | None, Query()] = None,
        end: Annotated[date | None, Query()] = None,
        limit: Annotated[int, Query(ge=0, le=500)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> TransactionPageOut:
        return list_transactions_op(
            service, account_id=account_id, start=start, end=end, limit=limit, offset=offset
        )

    @app.get("/api/finance/net-worth", response_model=NetWorthOut)
    def net_worth() -> NetWorthOut:
        return net_worth_op(service)

    @app.get("/api/finance/income-expense", response_model=IncomeExpenseOut)
    def income_expense(
        start: Annotated[date, Query()],
        end: Annotated[date, Query()],
        owner: Annotated[str | None, Query()] = None,
    ) -> IncomeExpenseOut:
        return income_expense_op(service, start=start, end=end, owner=owner)

    @app.post("/api/finance/budgets", response_model=BudgetOut)
    def set_budget(body: BudgetCreate) -> BudgetOut:
        return set_budget_op(service, body)

    @app.get("/api/finance/budgets", response_model=BudgetListOut)
    def list_budgets(period: Annotated[str | None, Query()] = None) -> BudgetListOut:
        return list_budgets_op(service, period)

    @app.get("/api/finance/budgets/variance", response_model=BudgetVarianceListOut)
    def budget_variance(period: Annotated[str, Query()]) -> BudgetVarianceListOut:
        return budget_variance_op(service, period)
