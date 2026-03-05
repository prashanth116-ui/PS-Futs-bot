"""
Parity tests for prop firm strategy fork.

Ensures:
1. Prop firm files import from runners.prop_firm.symbol_defaults, not runners.symbol_defaults
2. Prop get_session_v10_kwargs() keys match run_session_v10() signature
3. Prop config has all required prop-specific fields
4. Strategy params are initially identical between personal and prop
5. Mini/micro symbols share strategy params in prop config
"""
import inspect
import re
from pathlib import Path

import pytest

from runners.prop_firm.symbol_defaults import (
    FUTURES_DEFAULTS as PROP_FUTURES_DEFAULTS,
    get_symbol_config as prop_get_symbol_config,
    get_session_v10_kwargs as prop_get_session_v10_kwargs,
    get_live_futures_config as prop_get_live_futures_config,
    get_consec_loss_limit as prop_get_consec_loss_limit,
    get_prop_risk_config,
    is_futures as prop_is_futures,
)
from runners.symbol_defaults import (
    FUTURES_DEFAULTS as PERSONAL_FUTURES_DEFAULTS,
    get_session_v10_kwargs as personal_get_session_v10_kwargs,
)
from runners.prop_firm.run_v10_dual_entry import run_session_v10 as prop_run_session_v10

PROJECT_ROOT = Path(__file__).parent.parent

# Prop firm files that must import from runners.prop_firm, not runners directly
PROP_FILES = [
    'runners/prop_firm/backtest_v10_multiday.py',
    'runners/prop_firm/run_live.py',
    'runners/prop_firm/run_v10_dual_entry.py',
    'runners/prop_firm/risk_manager.py',
]


class TestImportIsolation:
    """Verify prop files import from runners.prop_firm, not runners directly."""

    @pytest.mark.parametrize("filepath", PROP_FILES)
    def test_no_direct_symbol_defaults_import(self, filepath):
        """Prop files must import symbol_defaults from runners.prop_firm, not runners."""
        full_path = PROJECT_ROOT / filepath
        if not full_path.exists():
            pytest.skip(f"{filepath} not found")

        content = full_path.read_text()

        # Look for "from runners.symbol_defaults" (without prop_firm in path)
        # But skip lines that have "prop_firm" in them
        bad_imports = []
        for i, line in enumerate(content.split('\n'), 1):
            if 'from runners.symbol_defaults' in line and 'prop_firm' not in line:
                bad_imports.append(f"  {filepath}:{i} — {line.strip()}")

        if bad_imports:
            pytest.fail(
                f"Prop firm file imports directly from runners.symbol_defaults "
                f"instead of runners.prop_firm.symbol_defaults:\n" +
                "\n".join(bad_imports)
            )

    @pytest.mark.parametrize("filepath", PROP_FILES)
    def test_no_direct_risk_manager_import(self, filepath):
        """Prop files must import risk_manager from runners.prop_firm, not runners."""
        full_path = PROJECT_ROOT / filepath
        if not full_path.exists():
            pytest.skip(f"{filepath} not found")

        content = full_path.read_text()

        bad_imports = []
        for i, line in enumerate(content.split('\n'), 1):
            if 'from runners.risk_manager' in line and 'prop_firm' not in line:
                bad_imports.append(f"  {filepath}:{i} — {line.strip()}")

        # Only check files that should import risk_manager
        if filepath in ['runners/prop_firm/run_live.py'] and bad_imports:
            pytest.fail(
                f"Prop firm file imports directly from runners.risk_manager "
                f"instead of runners.prop_firm.risk_manager:\n" +
                "\n".join(bad_imports)
            )


class TestPropKwargsMatchSignature:
    """Verify prop get_session_v10_kwargs() keys match run_session_v10() parameters."""

    def test_kwargs_are_valid_params(self):
        """Every key from prop get_session_v10_kwargs() must be a valid run_session_v10() parameter."""
        sig = inspect.signature(prop_run_session_v10)
        valid_params = set(sig.parameters.keys())
        valid_params -= {'session_bars', 'all_bars'}

        for symbol in PROP_FUTURES_DEFAULTS:
            kwargs = prop_get_session_v10_kwargs(symbol)
            invalid_keys = set(kwargs.keys()) - valid_params
            assert not invalid_keys, (
                f"prop get_session_v10_kwargs('{symbol}') returns keys not in "
                f"run_session_v10() signature: {invalid_keys}"
            )

    def test_critical_params_present(self):
        """Key strategy params must be present in prop kwargs output."""
        critical_keys = [
            'tick_size', 'tick_value', 'contracts', 'min_risk_pts',
            'max_bos_risk_pts', 'disable_bos_retrace', 't1_r_target',
            'trail_r_trigger', 't2_fixed_r', 'max_consec_losses',
            'opposing_fvg_exit', 'opposing_fvg_min_ticks',
            'symbol',
        ]
        for symbol in PROP_FUTURES_DEFAULTS:
            kwargs = prop_get_session_v10_kwargs(symbol)
            missing = [k for k in critical_keys if k not in kwargs]
            assert not missing, (
                f"prop get_session_v10_kwargs('{symbol}') missing critical keys: {missing}"
            )


class TestPropKwargsCompleteness:
    """Reverse check: every run_session_v10() param must be covered."""

    FUTURES_ALLOWLIST = {
        'session_bars',
        'all_bars',
        'use_opposing_fvg_exit',
        'fvg_mode',
        'opposing_fvg_mode',
        'entry_min_fvg_ticks',
        'post_t1_trail_r',
        'time_decay_bars',
        'time_decay_r',
    }

    def test_futures_kwargs_cover_all_params(self):
        """Every run_session_v10() param must be in kwargs output or allowlist."""
        sig = inspect.signature(prop_run_session_v10)
        all_params = set(sig.parameters.keys())

        kwargs = prop_get_session_v10_kwargs('ES')
        covered = set(kwargs.keys()) | self.FUTURES_ALLOWLIST

        uncovered = all_params - covered
        assert not uncovered, (
            f"run_session_v10() has params not covered by prop "
            f"get_session_v10_kwargs() and not in allowlist: {uncovered}"
        )


class TestPropConfigCompleteness:
    """Verify prop-specific config fields exist."""

    def test_prop_risk_fields_exist(self):
        """All prop firm symbols must have risk limit fields."""
        prop_fields = ['account_size', 'daily_loss_limit', 'trailing_drawdown', 'max_total_contracts']
        for symbol in PROP_FUTURES_DEFAULTS:
            cfg = prop_get_symbol_config(symbol)
            for field in prop_fields:
                assert field in cfg, (
                    f"Prop config for {symbol} missing field: {field}"
                )

    def test_get_prop_risk_config(self):
        """get_prop_risk_config() returns all required fields."""
        for symbol in PROP_FUTURES_DEFAULTS:
            risk_cfg = get_prop_risk_config(symbol)
            assert 'account_size' in risk_cfg
            assert 'daily_loss_limit' in risk_cfg
            assert 'trailing_drawdown' in risk_cfg
            assert 'max_total_contracts' in risk_cfg
            assert risk_cfg['account_size'] > 0
            assert risk_cfg['daily_loss_limit'] > 0
            assert risk_cfg['trailing_drawdown'] > 0


class TestPropPersonalStrategyParity:
    """
    Initially prop and personal strategy params should be IDENTICAL.
    This test ensures the fork starts clean before diverging.
    """

    STRATEGY_KEYS = [
        'tick_size', 'tick_value', 'min_risk', 'max_bos_risk', 'max_retrace_risk',
        'disable_bos', 'max_consec_losses', 't1_r_target', 'trail_r_trigger',
        't2_fixed_r', 'opp_fvg_exit', 'opp_fvg_min_ticks', 'opp_fvg_after_6r',
        'contracts', 'max_open_trades', 'bos_daily_loss_limit',
        'high_displacement_override', 'overnight_retrace_min_adx',
    ]

    @pytest.mark.parametrize("symbol", ['ES', 'NQ', 'MES', 'MNQ'])
    def test_strategy_params_match_personal(self, symbol):
        """Prop strategy params should initially match personal config."""
        personal_kwargs = personal_get_session_v10_kwargs(symbol)
        prop_kwargs = prop_get_session_v10_kwargs(symbol)

        for key in personal_kwargs:
            if key in prop_kwargs:
                assert personal_kwargs[key] == prop_kwargs[key], (
                    f"Mismatch for {symbol}.{key}: "
                    f"personal={personal_kwargs[key]}, prop={prop_kwargs[key]}"
                )


class TestPropMiniMicroParity:
    """ES must match MES on strategy params in prop config. Same for NQ/MNQ."""

    STRATEGY_KEYS = [
        'tick_size', 'min_risk', 'max_bos_risk', 'max_retrace_risk',
        'disable_bos', 'max_consec_losses', 't1_r_target', 'trail_r_trigger',
        't2_fixed_r', 'opp_fvg_exit', 'opp_fvg_min_ticks', 'opp_fvg_after_6r',
        'contracts', 'max_open_trades', 'bos_daily_loss_limit',
        'high_displacement_override', 'overnight_retrace_min_adx',
    ]

    @pytest.mark.parametrize("mini,micro", [("ES", "MES"), ("NQ", "MNQ")])
    def test_strategy_params_match(self, mini, micro):
        """Mini and micro versions must have identical strategy params in prop config."""
        mini_cfg = prop_get_symbol_config(mini)
        micro_cfg = prop_get_symbol_config(micro)

        for key in self.STRATEGY_KEYS:
            assert mini_cfg.get(key) == micro_cfg.get(key), (
                f"Prop {mini} vs {micro} mismatch on '{key}': "
                f"{mini_cfg.get(key)} vs {micro_cfg.get(key)}"
            )

    @pytest.mark.parametrize("mini,micro", [("ES", "MES"), ("NQ", "MNQ")])
    def test_tick_value_differs(self, mini, micro):
        """Mini and micro tick values must be different (10x ratio)."""
        mini_cfg = prop_get_symbol_config(mini)
        micro_cfg = prop_get_symbol_config(micro)
        assert mini_cfg['tick_value'] == micro_cfg['tick_value'] * 10
