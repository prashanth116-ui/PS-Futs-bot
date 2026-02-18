"""
FVG Detection for OTE Strategy - Re-exports from ict_sweep.

Keeps DRY by importing the existing FVG detection logic.
"""
from strategies.ict_sweep.signals.fvg import (
    FVG,
    detect_fvg,
    detect_fvg_in_range,
    check_fvg_mitigation,
    is_price_in_fvg,
    get_fvg_entry_price,
    update_fvg_list,
)

__all__ = [
    'FVG',
    'detect_fvg',
    'detect_fvg_in_range',
    'check_fvg_mitigation',
    'is_price_in_fvg',
    'get_fvg_entry_price',
    'update_fvg_list',
]
