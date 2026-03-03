"""
Live vs Backtest Divergence Tracker

Compares live paper trading results with backtest results for the same day.
Tracks divergence over time to distinguish normal real-time vs finalized bar
differences from actual code bugs.

Usage:
    from runners.divergence_tracker import compare_day, save_live_trades

    # Save live trades at EOD
    save_live_trades('ES', date.today(), trades, summary)

    # Run full comparison
    report = compare_day('ES', date.today(), live_trades=trades)
"""
import json
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from runners.bar_storage import load_local_bars
from runners.run_v10_dual_entry import run_session_v10
from runners.symbol_defaults import get_session_v10_kwargs
from version import STRATEGY_VERSION

# Storage directory
_DIVERGENCE_DIR = Path(__file__).parent.parent / 'data' / 'divergence'


def _ensure_dir(symbol: str) -> Path:
    """Ensure divergence directory exists for symbol."""
    d = _DIVERGENCE_DIR / symbol.upper()
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_live_trades(
    symbol: str,
    trade_date: date,
    trades: List[Dict],
    summary: Dict,
) -> Path:
    """
    Save live paper trades to JSON for later comparison.

    Args:
        symbol: Trading symbol (ES, NQ, etc.)
        trade_date: Trading date
        trades: List of trade snapshot dicts from LiveTrader
        summary: {trades, wins, losses, pnl}

    Returns:
        Path to saved JSON file
    """
    d = _ensure_dir(symbol)
    path = d / f'{trade_date.isoformat()}.json'

    data = {
        'symbol': symbol,
        'date': trade_date.isoformat(),
        'version': STRATEGY_VERSION,
        'summary': summary,
        'trades': trades,
    }

    path.write_text(json.dumps(data, indent=2, default=str))
    return path


def load_live_trades(symbol: str, trade_date: date) -> Optional[Dict]:
    """Load saved live trades from JSON."""
    path = _DIVERGENCE_DIR / symbol.upper() / f'{trade_date.isoformat()}.json'
    if not path.exists():
        return None
    return json.loads(path.read_text())


def run_backtest_for_date(
    symbol: str,
    trade_date: date,
    contracts: int = 3,
) -> Tuple[List[Dict], Dict]:
    """
    Run single-day backtest using local stored bars.

    Uses load_local_bars() (no TradingView fetch) with exact same params
    as run_live.py:509-537.

    Returns:
        (trades, summary) where summary = {trades, wins, losses, pnl}
    """
    all_bars = load_local_bars(symbol)
    if not all_bars:
        return [], {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0}

    # Get bars for target date
    day_bars = [b for b in all_bars if b.timestamp.date() == trade_date]

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

    if len(session_bars) < 50:
        return [], {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0}

    # Build kwargs from centralized config (parity with run_live.py)
    try:
        kwargs = get_session_v10_kwargs(symbol)
    except KeyError:
        return [], {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0}

    kwargs['contracts'] = contracts

    results = run_session_v10(
        session_bars,
        all_bars,
        **kwargs,
    )

    bt_trades = results
    bt_wins = sum(1 for r in bt_trades if r['total_dollars'] > 0)
    bt_losses = sum(1 for r in bt_trades if r['total_dollars'] < 0)
    bt_pnl = sum(r['total_dollars'] for r in bt_trades)

    summary = {
        'trades': len(bt_trades),
        'wins': bt_wins,
        'losses': bt_losses,
        'pnl': bt_pnl,
    }

    return bt_trades, summary


def _parse_time(t) -> Optional[datetime]:
    """Parse a time value to naive datetime (strip timezone), handling both datetime and ISO string."""
    if t is None:
        return None
    if isinstance(t, datetime):
        # Strip timezone to avoid naive vs aware comparison errors
        return t.replace(tzinfo=None) if t.tzinfo else t
    if isinstance(t, str):
        try:
            dt = datetime.fromisoformat(t)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except ValueError:
            return None
    return None


def match_trades(
    live_trades: List[Dict],
    backtest_trades: List[Dict],
    tolerance_minutes: int = 5,
) -> Dict:
    """
    Match live trades to backtest trades by time, direction, and entry type.

    Uses greedy nearest-time matching with no double-matching.

    Returns:
        {
            'matched': [(live, bt, gap)],
            'live_only': [live],
            'backtest_only': [bt],
        }
    """
    tolerance = timedelta(minutes=tolerance_minutes)

    # Track which backtest trades have been matched
    bt_used = set()
    matched = []
    live_only = []

    for lt in live_trades:
        lt_time = _parse_time(lt.get('entry_time'))
        lt_dir = lt.get('direction', '')
        lt_type = lt.get('entry_type', '')

        best_idx = None
        best_gap = None
        best_time_diff = timedelta.max

        for i, bt in enumerate(backtest_trades):
            if i in bt_used:
                continue

            bt_time = _parse_time(bt.get('entry_time'))
            bt_dir = bt.get('direction', '')
            bt_type = bt.get('entry_type', '')

            # Must match direction and entry type
            if lt_dir != bt_dir or lt_type != bt_type:
                continue

            if lt_time is None or bt_time is None:
                continue

            time_diff = abs(lt_time - bt_time)
            if time_diff <= tolerance and time_diff < best_time_diff:
                # Normalize P/L field names
                lt_pnl = lt.get('total_pnl', lt.get('total_dollars', 0.0))
                bt_pnl = bt.get('total_dollars', bt.get('total_pnl', 0.0))
                gap = lt_pnl - bt_pnl

                best_idx = i
                best_gap = gap
                best_time_diff = time_diff

        if best_idx is not None:
            bt_used.add(best_idx)
            matched.append((lt, backtest_trades[best_idx], best_gap))
        else:
            live_only.append(lt)

    # Remaining backtest trades are backtest-only
    backtest_only = [bt for i, bt in enumerate(backtest_trades) if i not in bt_used]

    return {
        'matched': matched,
        'live_only': live_only,
        'backtest_only': backtest_only,
    }


def build_comparison_report(
    symbol: str,
    trade_date: date,
    live_summary: Dict,
    bt_summary: Dict,
    matches: Dict,
) -> Dict:
    """Build a structured comparison report."""
    live_pnl = live_summary.get('pnl', 0.0)
    bt_pnl = bt_summary.get('pnl', 0.0)
    gap = live_pnl - bt_pnl
    pct_gap = (abs(gap) / abs(bt_pnl) * 100) if bt_pnl != 0 else (100.0 if gap != 0 else 0.0)

    # Largest individual trade gap
    largest_gap = 0.0
    for lt, bt, g in matches['matched']:
        if abs(g) > abs(largest_gap):
            largest_gap = g

    return {
        'symbol': symbol,
        'date': trade_date.isoformat(),
        'live_pnl': live_pnl,
        'bt_pnl': bt_pnl,
        'gap': gap,
        'pct_gap': pct_gap,
        'live_trades': live_summary.get('trades', 0),
        'bt_trades': bt_summary.get('trades', 0),
        'matched': len(matches['matched']),
        'live_only': len(matches['live_only']),
        'backtest_only': len(matches['backtest_only']),
        'largest_gap': largest_gap,
        'matches': matches,
        'live_summary': live_summary,
        'bt_summary': bt_summary,
    }


def format_console_report(reports: List[Dict]) -> str:
    """Format comparison reports for console output."""
    lines = []
    lines.append('')
    lines.append('=' * 70)
    lines.append('DIVERGENCE REPORT: Live vs Backtest')
    lines.append('=' * 70)

    total_live_pnl = 0.0
    total_bt_pnl = 0.0

    for rpt in reports:
        sym = rpt['symbol']
        lines.append(f'\n  {sym}:')
        lines.append(f'    Live P/L:    ${rpt["live_pnl"]:+,.2f} ({rpt["live_trades"]} trades)')
        lines.append(f'    Backtest:    ${rpt["bt_pnl"]:+,.2f} ({rpt["bt_trades"]} trades)')
        lines.append(f'    Gap:         ${rpt["gap"]:+,.2f} ({rpt["pct_gap"]:.1f}%)')
        lines.append(f'    Matched:     {rpt["matched"]} | Live-only: {rpt["live_only"]} | BT-only: {rpt["backtest_only"]}')

        # Trade-by-trade detail for matched
        matches = rpt['matches']
        if matches['matched']:
            lines.append('    Matched trades:')
            for lt, bt, gap in matches['matched']:
                lt_time = _parse_time(lt.get('entry_time'))
                time_str = lt_time.strftime('%H:%M') if lt_time else '??:??'
                lt_pnl = lt.get('total_pnl', lt.get('total_dollars', 0.0))
                bt_pnl = bt.get('total_dollars', bt.get('total_pnl', 0.0))
                lines.append(f'      {lt["direction"]} {lt["entry_type"]} {time_str} | '
                             f'Live: ${lt_pnl:+,.2f} BT: ${bt_pnl:+,.2f} Gap: ${gap:+,.2f}')

        if matches['live_only']:
            lines.append('    Live-only trades:')
            for lt in matches['live_only']:
                lt_time = _parse_time(lt.get('entry_time'))
                time_str = lt_time.strftime('%H:%M') if lt_time else '??:??'
                lt_pnl = lt.get('total_pnl', lt.get('total_dollars', 0.0))
                lines.append(f'      {lt["direction"]} {lt["entry_type"]} {time_str} | ${lt_pnl:+,.2f}')

        if matches['backtest_only']:
            lines.append('    Backtest-only trades:')
            for bt in matches['backtest_only']:
                bt_time = _parse_time(bt.get('entry_time'))
                time_str = bt_time.strftime('%H:%M') if bt_time else '??:??'
                bt_pnl = bt.get('total_dollars', bt.get('total_pnl', 0.0))
                lines.append(f'      {bt["direction"]} {bt["entry_type"]} {time_str} | ${bt_pnl:+,.2f}')

        total_live_pnl += rpt['live_pnl']
        total_bt_pnl += rpt['bt_pnl']

    if len(reports) > 1:
        total_gap = total_live_pnl - total_bt_pnl
        total_pct = (abs(total_gap) / abs(total_bt_pnl) * 100) if total_bt_pnl != 0 else 0.0
        lines.append(f'\n  TOTAL:')
        lines.append(f'    Live P/L:    ${total_live_pnl:+,.2f}')
        lines.append(f'    Backtest:    ${total_bt_pnl:+,.2f}')
        lines.append(f'    Gap:         ${total_gap:+,.2f} ({total_pct:.1f}%)')

    lines.append('=' * 70)
    return '\n'.join(lines)


def format_telegram_alert(reports: List[Dict]) -> Optional[str]:
    """
    Format divergence alert for Telegram (HTML).

    Returns None if gap is below threshold (no alert needed).
    Threshold: >$1,000 absolute OR >30% relative.
    """
    total_live = sum(r['live_pnl'] for r in reports)
    total_bt = sum(r['bt_pnl'] for r in reports)
    total_gap = total_live - total_bt
    total_pct = (abs(total_gap) / abs(total_bt) * 100) if total_bt != 0 else (100.0 if total_gap != 0 else 0.0)

    # Check threshold
    if abs(total_gap) < 1000 and total_pct < 30:
        return None

    trade_date = reports[0]['date'] if reports else date.today().isoformat()

    lines = []
    lines.append('<b>DIVERGENCE ALERT</b>')
    lines.append('')

    for rpt in reports:
        sym = rpt['symbol']
        lines.append(f'<b>{sym}:</b> Live ${rpt["live_pnl"]:+,.0f} vs BT ${rpt["bt_pnl"]:+,.0f} (gap ${rpt["gap"]:+,.0f})')
        lines.append(f'  Matched: {rpt["matched"]} | Live-only: {rpt["live_only"]} | BT-only: {rpt["backtest_only"]}')

    lines.append('')
    lines.append(f'<b>Total Gap:</b> ${total_gap:+,.0f} ({total_pct:.0f}%)')
    lines.append(f'{trade_date}')

    return '\n'.join(lines)


def compare_day(
    symbol: str,
    trade_date: date,
    live_trades: List[Dict] = None,
    contracts: int = 3,
) -> Dict:
    """
    Full comparison pipeline for a single symbol and date.

    Args:
        symbol: Trading symbol
        trade_date: Date to compare
        live_trades: Live trade list (if None, loads from saved JSON)
        contracts: Contract count for backtest

    Returns:
        Comparison report dict
    """
    # Load live trades
    if live_trades is None:
        saved = load_live_trades(symbol, trade_date)
        if saved is None:
            return build_comparison_report(
                symbol, trade_date,
                {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0},
                {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0},
                {'matched': [], 'live_only': [], 'backtest_only': []},
            )
        live_trades = saved['trades']
        live_summary = saved['summary']
    else:
        live_wins = sum(1 for t in live_trades if t.get('total_pnl', 0) > 0)
        live_losses = sum(1 for t in live_trades if t.get('total_pnl', 0) < 0)
        live_pnl = sum(t.get('total_pnl', 0) for t in live_trades)
        live_summary = {
            'trades': len(live_trades),
            'wins': live_wins,
            'losses': live_losses,
            'pnl': live_pnl,
        }

    # Run backtest
    bt_trades, bt_summary = run_backtest_for_date(symbol, trade_date, contracts)

    # Match trades
    matches = match_trades(live_trades, bt_trades)

    # Build report
    return build_comparison_report(symbol, trade_date, live_summary, bt_summary, matches)
