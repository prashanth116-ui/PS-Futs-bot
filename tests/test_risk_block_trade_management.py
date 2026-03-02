"""Regression test: open trades must be managed even when risk manager blocks new entries.

Bug (Mar 2, 2026): 3 consecutive losses triggered RiskStatus.BLOCKED, and the main
trading loop `continue`d past _manage_paper_trades(). An open ES SHORT sat unmanaged
for 3+ hours with no stop checks, trail updates, or exit logic.

Fix: trading_allowed flag only gates new entry scanning, not trade management.
"""

import signal
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest

from runners.risk_manager import RiskManager, RiskLimits, RiskStatus
from runners.run_live import LiveTrader, PaperTrade, PaperTradeStatus

EST = ZoneInfo('America/New_York')


@dataclass
class FakeBar:
    """Minimal bar for stop-check testing."""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0


def _make_blocked_risk_manager() -> RiskManager:
    """Create a risk manager in BLOCKED state (3 consecutive losses)."""
    rm = RiskManager(RiskLimits(max_consecutive_losses=3))
    # Simulate 3 consecutive losses: record_trade_exit(symbol, contracts, pnl, is_win)
    rm.record_trade_exit('ES', 1, -100, False)
    rm.record_trade_exit('ES', 1, -100, False)
    rm.record_trade_exit('NQ', 1, -100, False)
    assert rm.get_status() == RiskStatus.BLOCKED
    assert not rm.is_trading_allowed()
    return rm


def _make_paper_trade(direction='SHORT', entry=6825.25, stop=6827.75) -> PaperTrade:
    """Create a paper trade that should be stopped (price moved past stop)."""
    risk = abs(entry - stop)
    if direction == 'SHORT':
        target_4r = entry - 3 * risk
        target_8r = entry - 6 * risk
    else:
        target_4r = entry + 3 * risk
        target_8r = entry + 6 * risk

    return PaperTrade(
        id='PAPER_ES_5',
        symbol='ES',
        direction=direction,
        entry_type='CREATION',
        entry_price=entry,
        stop_price=stop,
        target_4r=target_4r,
        target_8r=target_8r,
        contracts=3,
        tick_size=0.25,
        tick_value=12.50,
        asset_type='futures',
        status=PaperTradeStatus.OPEN,
        entry_time=datetime(2026, 3, 2, 6, 57, tzinfo=EST),
    )


@pytest.fixture
def blocked_trader():
    """Create a LiveTrader with a blocked risk manager and one open paper trade."""
    rm = _make_blocked_risk_manager()

    # Patch signal handlers to avoid issues in test
    with patch.object(signal, 'signal'):
        trader = LiveTrader(
            paper_mode=True,
            symbols=['ES'],
            risk_manager=rm,
        )

    trade = _make_paper_trade(direction='SHORT', entry=6825.25, stop=6827.75)
    trader.paper_trades[trade.id] = trade
    return trader


def test_risk_blocked_still_manages_paper_trades(blocked_trader):
    """When risk manager is BLOCKED, open paper trades must still be managed.

    Reproduces the Mar 2 bug: ES SHORT open at 6825.25 with stop at 6827.75.
    Price rallied to 6841 but the trade was never stopped because the risk
    block skipped _manage_paper_trades().
    """
    trader = blocked_trader
    trade = trader.paper_trades['PAPER_ES_5']

    # Confirm risk is blocked
    assert not trader.risk_manager.is_trading_allowed()
    assert trade.status == PaperTradeStatus.OPEN

    # Price has rallied well past the stop (6827.75) — bars show high of 6841
    fake_bars = [FakeBar(high=6841.0, low=6835.0, close=6840.0)] * 20

    with patch('runners.run_live.fetch_futures_bars', return_value=fake_bars):
        trader._manage_paper_trades()

    # The trade should have been stopped out
    assert trade.status == PaperTradeStatus.CLOSED
    assert trade.total_pnl < 0  # Loss (short, price went up past stop)


def test_risk_blocked_reason_set_for_consecutive_losses():
    """blocked_reason must be set when consecutive losses trigger BLOCKED.

    Previously logged 'Trading blocked: None' because blocked_reason was
    never assigned for the consecutive losses path.
    """
    rm = _make_blocked_risk_manager()
    summary = rm.get_summary()
    assert summary['blocked_reason'] is not None
    assert 'onsecutive' in summary['blocked_reason']  # "Consecutive losses (3)"


def test_risk_blocked_does_not_allow_new_entries():
    """Verify that the risk manager still blocks new entries when BLOCKED."""
    rm = _make_blocked_risk_manager()
    allowed, reason = rm.can_enter_trade('ES', 'LONG', 'CREATION', 3, 2.5)
    assert not allowed
    assert 'consecutive' in reason.lower()
