from __future__ import annotations

from config.loader import load_yaml
from strategies.ict.ict_strategy import ICTStrategy

def build_ict_from_yaml(config_path: str):
    cfg = load_yaml(config_path)

    instrument_cfg = cfg.get("instrument", {})
    symbol = instrument_cfg.get("symbol", "ES")
    tick_size = float(instrument_cfg.get("tick_size", 0.25))

    # IMPORTANT: ICTStrategy expects instrument as a dict (uses .get)
    instrument = {"symbol": symbol, "tick_size": tick_size}

    strat = ICTStrategy(config=cfg, instrument=instrument, risk_manager=None)
    return strat
