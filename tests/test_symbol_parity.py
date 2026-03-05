"""
Parity tests for centralized symbol configuration.

Ensures:
1. No hardcoded per-symbol patterns remain in critical files
2. get_session_v10_kwargs() keys match run_session_v10() signature
3. Mini/micro symbols share strategy params (only tick_value differs)
"""
import inspect
import re
from pathlib import Path

import pytest

from runners.symbol_defaults import (
    FUTURES_DEFAULTS,
    EQUITY_DEFAULTS,
    get_symbol_config,
    get_session_v10_kwargs,
    get_session_v10_equity_kwargs,
    get_live_futures_config,
    get_consec_loss_limit,
    is_futures,
    is_equity,
)
from runners.run_v10_dual_entry import run_session_v10
from runners.run_v10_equity import run_session_v10_equity


# Critical files that MUST use centralized config (no inline ternaries)
CRITICAL_FILES = [
    'runners/backtest_v10_multiday.py',
    'runners/run_live.py',
    'runners/run_v10_dual_entry.py',
    'runners/plot_v10.py',
    'runners/plot_v10_date.py',
    'runners/divergence_tracker.py',
    'runners/risk_manager.py',
]

PROJECT_ROOT = Path(__file__).parent.parent

# Patterns that indicate hardcoded per-symbol config (should use symbol_defaults instead)
# Each pattern is (regex, description)
HARDCODED_PATTERNS = [
    # tick_value ternaries
    (r"tick_value\s*=\s*12\.50\s+if\s+symbol", "Hardcoded tick_value ternary"),
    # min_risk ternaries
    (r"min_risk(?:_pts)?\s*=\s*1\.5\s+if\s+symbol\s+in", "Hardcoded min_risk ternary"),
    # max_bos_risk ternaries
    (r"max_bos_risk(?:_pts)?\s*=\s*8\.0\s+if\s+symbol\s+in", "Hardcoded max_bos_risk ternary"),
    # max_retrace_risk ternaries
    (r"max_retrace_risk(?:_pts)?\s*=\s*8\.0\s+if\s+symbol\s+in", "Hardcoded max_retrace_risk ternary"),
    # disable_bos ternaries
    (r"disable_bos\s*=\s*symbol\s+in\s+\[", "Hardcoded disable_bos ternary"),
    # t2_fixed_r ternaries (both forms: symbol in [...] and trade.symbol in (...))
    (r"t2_fixed_r\s*=\s*5\s+if\s+(?:symbol|trade\.symbol)\s+in", "Hardcoded t2_fixed_r ternary"),
    # consec_limits dict
    (r"consec_limits\s*=\s*\{", "Hardcoded consec_limits dict"),
    # opp_fvg_configs dict
    (r"opp_fvg_configs\s*=\s*\{", "Hardcoded opp_fvg_configs dict"),
    # max_consec_losses ternary
    (r"max_consec_losses\s*=\s*2\s+if\s+symbol", "Hardcoded max_consec_losses ternary"),
]


class TestNoHardcodedPatterns:
    """Verify no hardcoded per-symbol patterns remain in critical files."""

    @pytest.mark.parametrize("filepath", CRITICAL_FILES)
    def test_no_inline_ternaries(self, filepath):
        """Critical files should not have inline per-symbol parameter ternaries."""
        full_path = PROJECT_ROOT / filepath
        if not full_path.exists():
            pytest.skip(f"{filepath} not found")

        content = full_path.read_text()
        violations = []

        for pattern, description in HARDCODED_PATTERNS:
            matches = list(re.finditer(pattern, content))
            for match in matches:
                # Get line number
                line_num = content[:match.start()].count('\n') + 1
                violations.append(f"  {filepath}:{line_num} — {description}")

        if violations:
            pytest.fail(
                f"Found {len(violations)} hardcoded pattern(s) in {filepath}. "
                f"Use symbol_defaults.py instead:\n" + "\n".join(violations)
            )


class TestKwargsMatchSignature:
    """Verify get_session_v10_kwargs() keys match run_session_v10() parameters."""

    def test_kwargs_are_valid_params(self):
        """Every key from get_session_v10_kwargs() must be a valid run_session_v10() parameter."""
        sig = inspect.signature(run_session_v10)
        valid_params = set(sig.parameters.keys())
        # session_bars and all_bars are positional, not in kwargs
        valid_params -= {'session_bars', 'all_bars'}

        for symbol in FUTURES_DEFAULTS:
            kwargs = get_session_v10_kwargs(symbol)
            invalid_keys = set(kwargs.keys()) - valid_params
            assert not invalid_keys, (
                f"get_session_v10_kwargs('{symbol}') returns keys not in "
                f"run_session_v10() signature: {invalid_keys}"
            )

    def test_critical_params_present(self):
        """Key strategy params must be present in kwargs output."""
        critical_keys = [
            'tick_size', 'tick_value', 'contracts', 'min_risk_pts',
            'max_bos_risk_pts', 'disable_bos_retrace', 't1_r_target',
            'trail_r_trigger', 't2_fixed_r', 'max_consec_losses',
            'opposing_fvg_exit', 'opposing_fvg_min_ticks',
            'symbol',
        ]
        for symbol in FUTURES_DEFAULTS:
            kwargs = get_session_v10_kwargs(symbol)
            missing = [k for k in critical_keys if k not in kwargs]
            assert not missing, (
                f"get_session_v10_kwargs('{symbol}') missing critical keys: {missing}"
            )


class TestEquityKwargsMatchSignature:
    """Verify get_session_v10_equity_kwargs() keys match run_session_v10_equity() parameters."""

    def test_kwargs_are_valid_params(self):
        """Every key from get_session_v10_equity_kwargs() must be a valid run_session_v10_equity() parameter."""
        sig = inspect.signature(run_session_v10_equity)
        valid_params = set(sig.parameters.keys())
        valid_params -= {'session_bars', 'all_bars'}

        for symbol in EQUITY_DEFAULTS:
            kwargs = get_session_v10_equity_kwargs(symbol)
            invalid_keys = set(kwargs.keys()) - valid_params
            assert not invalid_keys, (
                f"get_session_v10_equity_kwargs('{symbol}') returns keys not in "
                f"run_session_v10_equity() signature: {invalid_keys}"
            )

    def test_critical_equity_params_present(self):
        """Key equity strategy params must be present in kwargs output."""
        critical_keys = [
            'symbol', 'risk_per_trade', 'max_open_trades',
            'disable_bos_retrace', 'bos_daily_loss_limit',
            't1_r_target', 'trail_r_trigger', 'use_hybrid_filters',
            'atr_buffer_multiplier', 'disable_intraday_spy',
        ]
        for symbol in EQUITY_DEFAULTS:
            kwargs = get_session_v10_equity_kwargs(symbol)
            missing = [k for k in critical_keys if k not in kwargs]
            assert not missing, (
                f"get_session_v10_equity_kwargs('{symbol}') missing critical keys: {missing}"
            )

    def test_equity_overrides_work(self):
        """CLI overrides should replace default values."""
        kwargs = get_session_v10_equity_kwargs('SPY', trail_r_trigger=8)
        assert kwargs['trail_r_trigger'] == 8

    def test_spy_bos_disabled(self):
        """SPY should have BOS disabled."""
        kwargs = get_session_v10_equity_kwargs('SPY')
        assert kwargs['disable_bos_retrace'] is True

    def test_qqq_bos_enabled(self):
        """QQQ should have BOS enabled with loss limit."""
        kwargs = get_session_v10_equity_kwargs('QQQ')
        assert kwargs['disable_bos_retrace'] is False
        assert kwargs['bos_daily_loss_limit'] == 1


class TestKwargsCompleteness:
    """
    REVERSE CHECK: every run_session_v10() parameter must be covered by
    get_session_v10_kwargs() OR explicitly listed in the allowlist below.

    If you add a new param to run_session_v10() or run_session_v10_equity(),
    this test will FAIL until you either:
      1. Add it to the kwargs builder in symbol_defaults.py, OR
      2. Add it to the allowlist here with a comment explaining why.
    """

    # Params intentionally NOT centralized (CLI-only flags, A/B testing, deprecated)
    FUTURES_ALLOWLIST = {
        'session_bars',           # positional arg
        'all_bars',               # positional arg
        'use_opposing_fvg_exit',  # deprecated — replaced by opposing_fvg_exit
        'fvg_mode',               # runtime CLI flag (--fvg-mode=body), not per-symbol
        'opposing_fvg_mode',      # runtime CLI flag, not per-symbol
        'entry_min_fvg_ticks',    # A/B testing CLI flag
        'post_t1_trail_r',        # A/B testing CLI flag (trail improvement option B)
        'time_decay_bars',        # A/B testing CLI flag (trail improvement option D)
        'time_decay_r',           # A/B testing CLI flag (trail improvement option D)
    }

    EQUITY_ALLOWLIST = {
        'session_bars',           # positional arg
        'all_bars',               # positional arg
    }

    def test_futures_kwargs_cover_all_params(self):
        """Every run_session_v10() param must be in kwargs output or allowlist."""
        sig = inspect.signature(run_session_v10)
        all_params = set(sig.parameters.keys())

        kwargs = get_session_v10_kwargs('ES')
        covered = set(kwargs.keys()) | self.FUTURES_ALLOWLIST

        uncovered = all_params - covered
        assert not uncovered, (
            f"run_session_v10() has params not covered by get_session_v10_kwargs() "
            f"and not in allowlist: {uncovered}\n"
            f"Either add them to get_session_v10_kwargs() in symbol_defaults.py, "
            f"or add them to FUTURES_ALLOWLIST in this test with a comment."
        )

    def test_equity_kwargs_cover_all_params(self):
        """Every run_session_v10_equity() param must be in kwargs output or allowlist."""
        sig = inspect.signature(run_session_v10_equity)
        all_params = set(sig.parameters.keys())

        kwargs = get_session_v10_equity_kwargs('SPY')
        covered = set(kwargs.keys()) | self.EQUITY_ALLOWLIST

        uncovered = all_params - covered
        assert not uncovered, (
            f"run_session_v10_equity() has params not covered by "
            f"get_session_v10_equity_kwargs() and not in allowlist: {uncovered}\n"
            f"Either add them to get_session_v10_equity_kwargs() in symbol_defaults.py, "
            f"or add them to EQUITY_ALLOWLIST in this test with a comment."
        )

    def test_futures_allowlist_is_minimal(self):
        """Allowlist entries must actually exist in the function signature (no stale entries)."""
        sig = inspect.signature(run_session_v10)
        all_params = set(sig.parameters.keys())

        stale = self.FUTURES_ALLOWLIST - all_params
        assert not stale, (
            f"FUTURES_ALLOWLIST contains params that no longer exist in "
            f"run_session_v10(): {stale}. Remove them."
        )

    def test_equity_allowlist_is_minimal(self):
        """Allowlist entries must actually exist in the function signature (no stale entries)."""
        sig = inspect.signature(run_session_v10_equity)
        all_params = set(sig.parameters.keys())

        stale = self.EQUITY_ALLOWLIST - all_params
        assert not stale, (
            f"EQUITY_ALLOWLIST contains params that no longer exist in "
            f"run_session_v10_equity(): {stale}. Remove them."
        )


class TestMiniMicroParity:
    """ES must match MES on all strategy params (only tick_value differs). Same for NQ/MNQ."""

    STRATEGY_KEYS = [
        'tick_size', 'min_risk', 'max_bos_risk', 'max_retrace_risk',
        'disable_bos', 'max_consec_losses', 't1_r_target', 'trail_r_trigger',
        't2_fixed_r', 'opp_fvg_exit', 'opp_fvg_min_ticks', 'opp_fvg_after_6r',
        'contracts', 'max_open_trades', 'bos_daily_loss_limit',
        'high_displacement_override', 'overnight_retrace_min_adx',
    ]

    @pytest.mark.parametrize("mini,micro", [("ES", "MES"), ("NQ", "MNQ")])
    def test_strategy_params_match(self, mini, micro):
        """Mini and micro versions must have identical strategy params."""
        mini_cfg = get_symbol_config(mini)
        micro_cfg = get_symbol_config(micro)

        mismatches = []
        for key in self.STRATEGY_KEYS:
            mini_val = mini_cfg.get(key)
            micro_val = micro_cfg.get(key)
            if mini_val != micro_val:
                mismatches.append(f"  {key}: {mini}={mini_val}, {micro}={micro_val}")

        assert not mismatches, (
            f"{mini} and {micro} strategy params differ:\n" + "\n".join(mismatches)
        )

    @pytest.mark.parametrize("mini,micro", [("ES", "MES"), ("NQ", "MNQ")])
    def test_tick_value_differs(self, mini, micro):
        """Mini tick_value should be 10x micro tick_value."""
        mini_cfg = get_symbol_config(mini)
        micro_cfg = get_symbol_config(micro)
        assert mini_cfg['tick_value'] == micro_cfg['tick_value'] * 10, (
            f"{mini} tick_value ({mini_cfg['tick_value']}) should be "
            f"10x {micro} tick_value ({micro_cfg['tick_value']})"
        )


class TestSymbolConfigAPI:
    """Test the public API of symbol_defaults module."""

    def test_get_symbol_config_returns_copy(self):
        """Config should be a copy — mutations don't affect defaults."""
        cfg1 = get_symbol_config('ES')
        cfg1['tick_value'] = 999
        cfg2 = get_symbol_config('ES')
        assert cfg2['tick_value'] == 12.50

    def test_unknown_symbol_raises(self):
        """Unknown symbol should raise KeyError."""
        with pytest.raises(KeyError):
            get_symbol_config('UNKNOWN')

    def test_is_futures(self):
        assert is_futures('ES')
        assert is_futures('MES')
        assert not is_futures('SPY')

    def test_is_equity(self):
        assert is_equity('SPY')
        assert is_equity('QQQ')
        assert not is_equity('ES')

    def test_overrides_work(self):
        """CLI overrides should replace default values."""
        kwargs = get_session_v10_kwargs('ES', trail_r_trigger=8)
        assert kwargs['trail_r_trigger'] == 8

    def test_consec_loss_limit(self):
        assert get_consec_loss_limit('ES') == 3
        assert get_consec_loss_limit('MES') == 3
        assert get_consec_loss_limit('NQ') == 3
        assert get_consec_loss_limit('MNQ') == 3
        assert get_consec_loss_limit('SPY') == 0

    def test_live_futures_config_format(self):
        """get_live_futures_config should return dict with expected keys."""
        cfg = get_live_futures_config('ES')
        required_keys = ['tradovate_symbol', 'tick_size', 'tick_value',
                         'min_risk', 'max_bos_risk', 'contracts', 'type']
        for key in required_keys:
            assert key in cfg, f"Missing key: {key}"
        assert cfg['type'] == 'futures'

    def test_es_values(self):
        """Verify ES has correct V10.16 values."""
        cfg = get_symbol_config('ES')
        assert cfg['tick_value'] == 12.50
        assert cfg['min_risk'] == 1.5
        assert cfg['max_bos_risk'] == 8.0
        assert cfg['max_retrace_risk'] == 8.0
        assert cfg['disable_bos'] is True
        assert cfg['max_consec_losses'] == 3
        assert cfg['t1_r_target'] == 3
        assert cfg['trail_r_trigger'] == 4
        assert cfg['t2_fixed_r'] == 5
        assert cfg['opp_fvg_exit'] is True
        assert cfg['opp_fvg_min_ticks'] == 10

    def test_nq_values(self):
        """Verify NQ has correct V10.16 values."""
        cfg = get_symbol_config('NQ')
        assert cfg['tick_value'] == 5.00
        assert cfg['min_risk'] == 6.0
        assert cfg['max_bos_risk'] == 20.0
        assert cfg['max_retrace_risk'] is None
        assert cfg['disable_bos'] is False
        assert cfg['max_consec_losses'] == 3
        assert cfg['t2_fixed_r'] == 0
        assert cfg['opp_fvg_min_ticks'] == 5
