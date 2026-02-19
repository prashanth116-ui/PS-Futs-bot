from __future__ import annotations

import yaml
from pathlib import Path

from strategies.ict.ict_strategy import ICTStrategy

def load_yaml(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8"))

def build_strategy(config_path: str | Path):
    cfg = load_yaml(config_path)

    instrument = cfg.get("instrument", {})
    cfg.get("risk", {})
    cfg.get("killzones", {})

    # Strategy expects a unified dict config (you already structured it this way)
    strategy = ICTStrategy(
        config=cfg,
        instrument=instrument,
        risk_manager=None,  # we’ll plug in in step 3
    )
    return strategy
