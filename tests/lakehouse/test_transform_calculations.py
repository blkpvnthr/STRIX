"""Calculation-contract registry tests: identifiers, pinned methodology version,
and documented required fields."""

from __future__ import annotations

import pytest

from strix.agent.calculations import CALC_VERSION
from strix.lakehouse.transform.calculations import (
    CALCULATION_CONTRACTS,
    contract,
)


def test_all_contracts_pin_the_shared_methodology_version() -> None:
    assert CALCULATION_CONTRACTS
    for c in CALCULATION_CONTRACTS.values():
        assert c.methodology_version == CALC_VERSION


@pytest.mark.parametrize(
    "ident",
    ["period_return", "cumulative_return", "max_drawdown", "realized_volatility",
     "correlation", "gross_profit_margin", "operating_margin", "net_profit_margin"],
)
def test_contract_present_and_complete(ident: str) -> None:
    c = contract(ident)
    assert c.identifier == ident
    assert c.formula and c.output_unit and c.precision_policy
    assert c.min_sample_size >= 1
    assert c.evidence_lineage and c.historical_availability


def test_unknown_contract_raises() -> None:
    with pytest.raises(KeyError):
        contract("does_not_exist")
