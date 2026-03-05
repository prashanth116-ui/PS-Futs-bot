"""
Prop Firm Symbol Configuration — Forked from runners/symbol_defaults.py

All per-symbol strategy parameters for prop firm accounts. Initially identical
to the personal strategy (V10.16) with additional prop-specific risk fields.

Prop-specific additions:
  - account_size: Eval account size ($)
  - daily_loss_limit: Max daily loss before stopping ($)
  - trailing_drawdown: Max trailing drawdown from peak ($)
  - max_total_contracts: Max contracts across all open positions

To change a parameter:
  1. Edit the value here
  2. Run tests: python -m pytest tests/test_prop_parity.py
  3. Done — all prop callers pick up the change automatically
"""
import copy


# =============================================================================
# Futures Symbol Defaults (Prop Firm)
# =============================================================================

_FUTURES_BASE = {
    # --- Instrument ---
    'tick_size': 0.25,

    # --- Strategy params ---
    'contracts': 3,
    'max_open_trades': 3,
    'max_losses_per_day': 3,
    't1_r_target': 3,
    'trail_r_trigger': 4,       # V10.16: Lowered from 6R
    'high_displacement_override': 3.0,
    'bos_daily_loss_limit': 1,
    'overnight_retrace_min_adx': 22,
    'displacement_threshold': 1.0,
    'min_adx': 11,              # V10.7: Lowered from 17

    # --- Standard flags ---
    'enable_creation_entry': True,
    'enable_retracement_entry': True,
    'enable_bos_entry': True,
    'retracement_morning_only': False,
    'retracement_trend_aligned': False,
    't1_fixed_4r': True,
    'midday_cutoff': True,
    'pm_cutoff_nq': True,
    'use_hybrid_filters': True,
    'consol_threshold': 0.0,
    'bos_lookback': 10,
    'bos_fvg_window': 5,

    # --- Prop firm risk limits ---
    'account_size': 50000,           # Eval account size ($)
    'daily_loss_limit': 2000,        # Max daily loss ($) before stop
    'trailing_drawdown': 2500,       # Max trailing drawdown from peak ($)
    'max_total_contracts': 5,        # Max contracts across all positions
}

FUTURES_DEFAULTS = {
    'ES': {
        **_FUTURES_BASE,
        'tick_value': 12.50,
        'min_risk': 1.5,
        'max_bos_risk': 8.0,
        'max_retrace_risk': 8.0,
        'disable_bos': True,
        'max_consec_losses': 3,
        't2_fixed_r': 5,           # V10.16: Fixed T2 exit at 5R
        'opp_fvg_exit': True,
        'opp_fvg_min_ticks': 10,   # B2: after 6R, 10 ticks
        'opp_fvg_after_6r': True,
        'tradovate_symbol': 'ESM6',
    },
    'NQ': {
        **_FUTURES_BASE,
        'tick_value': 5.00,
        'min_risk': 6.0,
        'max_bos_risk': 20.0,
        'max_retrace_risk': None,
        'disable_bos': False,
        'max_consec_losses': 3,
        't2_fixed_r': 0,           # NQ: T2 trails, no fixed exit
        'opp_fvg_exit': True,
        'opp_fvg_min_ticks': 5,    # B1: after 6R, 5 ticks
        'opp_fvg_after_6r': True,
        'tradovate_symbol': 'NQM6',
    },
    'MES': {
        **_FUTURES_BASE,
        'tick_value': 1.25,
        'min_risk': 1.5,
        'max_bos_risk': 8.0,
        'max_retrace_risk': 8.0,
        'disable_bos': True,
        'max_consec_losses': 3,
        't2_fixed_r': 5,
        'opp_fvg_exit': True,
        'opp_fvg_min_ticks': 10,
        'opp_fvg_after_6r': True,
        'tradovate_symbol': 'MESM6',
    },
    'MNQ': {
        **_FUTURES_BASE,
        'tick_value': 0.50,
        'min_risk': 6.0,
        'max_bos_risk': 20.0,
        'max_retrace_risk': None,
        'disable_bos': False,
        'max_consec_losses': 3,
        't2_fixed_r': 0,
        'opp_fvg_exit': True,
        'opp_fvg_min_ticks': 5,
        'opp_fvg_after_6r': True,
        'tradovate_symbol': 'MNQM6',
    },
}


# =============================================================================
# Public API
# =============================================================================

def get_symbol_config(symbol):
    """
    Get a copy of the config dict for a symbol.

    Returns a deep copy so callers can modify without affecting defaults.

    Raises KeyError if symbol is not recognized.
    """
    symbol = symbol.upper()
    if symbol in FUTURES_DEFAULTS:
        return copy.deepcopy(FUTURES_DEFAULTS[symbol])
    raise KeyError(f"Unknown prop firm symbol: {symbol}")


def is_futures(symbol):
    """Check if symbol is a futures instrument."""
    return symbol.upper() in FUTURES_DEFAULTS


def get_session_v10_kwargs(symbol, **overrides):
    """
    Build kwargs dict for run_session_v10() from centralized config.

    Maps config keys to run_session_v10() parameter names. CLI overrides
    (e.g., trail_r_trigger=8) replace the default value.

    Args:
        symbol: Trading symbol (ES, NQ, MES, MNQ)
        **overrides: Override any config value (for A/B testing)

    Returns:
        dict ready to be unpacked into run_session_v10(**kwargs)
    """
    cfg = get_symbol_config(symbol)
    cfg.update(overrides)

    return {
        'tick_size': cfg['tick_size'],
        'tick_value': cfg['tick_value'],
        'contracts': cfg['contracts'],
        'max_open_trades': cfg.get('max_open_trades', 3),
        'max_losses_per_day': cfg.get('max_losses_per_day', 3),
        'min_risk_pts': cfg['min_risk'],
        'displacement_threshold': cfg.get('displacement_threshold', 1.0),
        'min_adx': cfg.get('min_adx', 11),
        'enable_creation_entry': cfg.get('enable_creation_entry', True),
        'enable_retracement_entry': cfg.get('enable_retracement_entry', True),
        'enable_bos_entry': cfg.get('enable_bos_entry', True),
        'retracement_morning_only': cfg.get('retracement_morning_only', False),
        'retracement_trend_aligned': cfg.get('retracement_trend_aligned', False),
        'overnight_retrace_min_adx': cfg.get('overnight_retrace_min_adx', 22),
        't1_fixed_4r': cfg.get('t1_fixed_4r', True),
        'midday_cutoff': cfg.get('midday_cutoff', True),
        'pm_cutoff_nq': cfg.get('pm_cutoff_nq', True),
        'max_bos_risk_pts': cfg['max_bos_risk'],
        'max_retrace_risk_pts': cfg.get('max_retrace_risk'),
        'symbol': symbol.upper(),
        'high_displacement_override': cfg.get('high_displacement_override', 3.0),
        'disable_bos_retrace': cfg['disable_bos'],
        'bos_daily_loss_limit': cfg.get('bos_daily_loss_limit', 1),
        'bos_lookback': cfg.get('bos_lookback', 10),
        'bos_fvg_window': cfg.get('bos_fvg_window', 5),
        't1_r_target': cfg.get('t1_r_target', 3),
        'trail_r_trigger': cfg.get('trail_r_trigger', 4),
        't2_fixed_r': cfg.get('t2_fixed_r', 0),
        'consol_threshold': cfg.get('consol_threshold', 0.0),
        'max_consec_losses': cfg.get('max_consec_losses', 0),
        'use_hybrid_filters': cfg.get('use_hybrid_filters', True),
        'opposing_fvg_exit': cfg.get('opp_fvg_exit', False),
        'opposing_fvg_min_ticks': cfg.get('opp_fvg_min_ticks', 5),
        'opposing_fvg_after_6r_only': cfg.get('opp_fvg_after_6r', False),
    }


def get_live_futures_config(symbol):
    """
    Build config dict for LiveTrader._scan_futures_symbol().

    Returns the format expected by run_live.py's FUTURES_SYMBOLS dict.
    """
    cfg = get_symbol_config(symbol)
    return {
        'tradovate_symbol': cfg['tradovate_symbol'],
        'tick_size': cfg['tick_size'],
        'tick_value': cfg['tick_value'],
        'min_risk': cfg['min_risk'],
        'max_bos_risk': cfg['max_bos_risk'],
        'max_retrace_risk': cfg.get('max_retrace_risk'),
        'contracts': cfg['contracts'],
        'type': 'futures',
        'opp_fvg_exit': cfg.get('opp_fvg_exit', False),
        'opp_fvg_min_ticks': cfg.get('opp_fvg_min_ticks', 5),
        'opp_fvg_after_6r': cfg.get('opp_fvg_after_6r', False),
    }


def get_consec_loss_limit(symbol):
    """Per-symbol consecutive loss limit for risk_manager."""
    symbol = symbol.upper()
    if symbol in FUTURES_DEFAULTS:
        return FUTURES_DEFAULTS[symbol].get('max_consec_losses', 0)
    return 0


def get_prop_risk_config(symbol):
    """
    Get prop-firm-specific risk limits for a symbol.

    Returns:
        dict with account_size, daily_loss_limit, trailing_drawdown, max_total_contracts
    """
    cfg = get_symbol_config(symbol)
    return {
        'account_size': cfg.get('account_size', 50000),
        'daily_loss_limit': cfg.get('daily_loss_limit', 2000),
        'trailing_drawdown': cfg.get('trailing_drawdown', 2500),
        'max_total_contracts': cfg.get('max_total_contracts', 5),
    }
