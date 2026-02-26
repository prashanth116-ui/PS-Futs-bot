"""
Multi-timeframe alignment filter for TTFM.

Checks that HTF bias, MTF swing structure, and LTF CISD all agree
on direction before allowing an entry.
"""

from strategies.ttfm.types import Bias, CISD, CandleLabel, SwingPoint, POI


def check_alignment(
    htf_bias: Bias,
    mtf_swings: list[SwingPoint],
    ltf_cisd: CISD | None,
    candle_label: CandleLabel | None,
    mtf_pois: list[POI] | None = None,
) -> bool:
    """Check if all three timeframes align for a trade.

    Requirements:
    1. HTF bias must not be NEUTRAL
    2. LTF CISD must be confirmed and agree with HTF direction
    3. Candle label must be C3 or C4 (continuation/expansion)
    4. MTF must have a recent swing in the opposing direction (C2)
       near a POI (if POIs are provided)

    Args:
        htf_bias: Daily bias.
        mtf_swings: MTF swing points.
        ltf_cisd: LTF CISD event (None if no CISD found).
        candle_label: Current candle label (C3/C4 expected).
        mtf_pois: Optional MTF POIs to check swing location.

    Returns:
        True if all timeframes align.
    """
    if htf_bias.direction == "NEUTRAL":
        return False

    if ltf_cisd is None:
        return False

    if ltf_cisd.direction != htf_bias.direction:
        return False

    if candle_label is None:
        return False

    if candle_label.label not in ("C3", "C4"):
        return False

    if candle_label.direction != htf_bias.direction:
        return False

    # Check MTF has an opposing swing (the C2 that marks the reversal point)
    target_swing_type = "HIGH" if htf_bias.direction == "BEARISH" else "LOW"
    has_mtf_swing = any(s.swing_type == target_swing_type for s in mtf_swings)
    if not has_mtf_swing:
        return False

    # Optional: check if MTF swing is at a POI
    if mtf_pois:
        recent_mtf_swings = [s for s in mtf_swings if s.swing_type == target_swing_type]
        if recent_mtf_swings:
            latest_swing = recent_mtf_swings[-1]
            at_poi = _swing_at_poi(latest_swing, mtf_pois)
            if not at_poi:
                return False

    return True


def _swing_at_poi(swing: SwingPoint, pois: list[POI], tolerance: float = 0.0) -> bool:
    """Check if a swing point is at or near a POI zone."""
    for poi in pois:
        # Swing price should be within or near the POI zone
        if poi.low - tolerance <= swing.price <= poi.high + tolerance:
            return True
    return False
