"""
Candle numbering system for TTFM (C1/C2/C3/C4).

Per TTrades Fractal Model:
C1 = Pre-swing candle(s) — establishes the range, builds liquidity
C2 = Swing point — sweeps C1's extreme, closes back inside C1's range
C3 = Continuation — closes beyond C2's BODY (not wick), engulfs it
C4 = Expansion — wick forms in appropriate half of C3's range, expands further

Validation rules:
- C2 must sweep C1's high/low AND close back inside C1's range
- C3 must close beyond C2's BODY (max/min of open,close), not C2's wick
- C4 wick should form in upper half of C3 (bullish) or lower half (bearish)
- C2 wick size determines aggressiveness: small wick = trade C2, large = wait C3

Wick size assessment:
- Measure C2's wick as % of C2's total range
- Small wick (<40% of range): price has room to expand — trade C2 directly
- Large wick (>=40%): price used fuel creating the wick — wait for C3
"""

from core.types import Bar
from strategies.ttfm.types import CandleLabel, SwingPoint


def label_candles(
    bars: list[Bar],
    swings: list[SwingPoint],
    wick_threshold: float = 0.4,
) -> list[CandleLabel]:
    """Label bars relative to swing points using C1/C2/C3/C4 system.

    For each swing point (C2), validates the closure, assesses wick size,
    labels the preceding bar as C1, and looks forward for C3/C4.

    C3 must close beyond C2's BODY (not wick) per TTrades rules.

    Args:
        bars: Chronologically ordered bars.
        swings: Pre-computed swing points.
        wick_threshold: Wick ratio threshold for C2 assessment.
            Below this = small wick (can trade C2 directly).
            Above this = large wick (wait for C3).

    Returns:
        List of CandleLabel objects.
    """
    labels: list[CandleLabel] = []
    used_indices: set[int] = set()

    for swing in swings:
        idx = swing.bar_index
        if idx < 1 or idx >= len(bars) - 1:
            continue

        c2_bar = bars[idx]
        prev_bar = bars[idx - 1]  # C1

        if swing.swing_type == "HIGH":
            # Bearish reversal: C2 is a swing high
            direction = "BEARISH"

            # Validate C2: must sweep C1's high and close back inside C1's range
            if c2_bar.high <= prev_bar.high:
                continue  # Didn't sweep
            if c2_bar.close > prev_bar.high:
                continue  # Didn't close back inside

            # C2's body bottom (for C3 check — C3 must close below C2's body)
            c2_body_bottom = min(c2_bar.open, c2_bar.close)

            # Assess wick size: upper wick relative to total range
            c2_range = c2_bar.range
            c2_wick_ratio = c2_bar.upper_wick / c2_range if c2_range > 0 else 0
            small_wick = c2_wick_ratio < wick_threshold

            # C1
            if idx - 1 not in used_indices:
                labels.append(CandleLabel(
                    bar_index=idx - 1, label="C1",
                    direction=direction, swing_point=None,
                ))
                used_indices.add(idx - 1)

            # C2 — mark with small_wick info for entry decisions
            if idx not in used_indices:
                lbl = CandleLabel(
                    bar_index=idx, label="C2",
                    direction=direction, swing_point=swing,
                )
                labels.append(lbl)
                used_indices.add(idx)

            # C3: first bar that closes below C2's BODY bottom (engulfs C2 body)
            for j in range(idx + 1, min(idx + 6, len(bars))):
                if bars[j].close < c2_body_bottom:
                    if j not in used_indices:
                        labels.append(CandleLabel(
                            bar_index=j, label="C3",
                            direction=direction, swing_point=swing,
                        ))
                        used_indices.add(j)

                    # C4: wick in lower half of C3's range, expands lower
                    c3_bar = bars[j]
                    c3_mid = (c3_bar.high + c3_bar.low) / 2
                    for k in range(j + 1, min(j + 4, len(bars))):
                        # C4 wick should form in lower half of C3
                        if bars[k].high <= c3_mid and bars[k].close < c3_bar.low:
                            if k not in used_indices:
                                labels.append(CandleLabel(
                                    bar_index=k, label="C4",
                                    direction=direction, swing_point=swing,
                                ))
                                used_indices.add(k)
                            break
                    break

        elif swing.swing_type == "LOW":
            # Bullish reversal: C2 is a swing low
            direction = "BULLISH"

            # Validate C2: must sweep C1's low and close back inside C1's range
            if c2_bar.low >= prev_bar.low:
                continue
            if c2_bar.close < prev_bar.low:
                continue  # Didn't close back inside

            # C2's body top (for C3 check — C3 must close above C2's body)
            c2_body_top = max(c2_bar.open, c2_bar.close)

            # Assess wick size: lower wick relative to total range
            c2_range = c2_bar.range
            c2_wick_ratio = c2_bar.lower_wick / c2_range if c2_range > 0 else 0
            small_wick = c2_wick_ratio < wick_threshold

            # C1
            if idx - 1 not in used_indices:
                labels.append(CandleLabel(
                    bar_index=idx - 1, label="C1",
                    direction=direction, swing_point=None,
                ))
                used_indices.add(idx - 1)

            # C2
            if idx not in used_indices:
                lbl = CandleLabel(
                    bar_index=idx, label="C2",
                    direction=direction, swing_point=swing,
                )
                labels.append(lbl)
                used_indices.add(idx)

            # C3: first bar that closes above C2's BODY top (engulfs C2 body)
            for j in range(idx + 1, min(idx + 6, len(bars))):
                if bars[j].close > c2_body_top:
                    if j not in used_indices:
                        labels.append(CandleLabel(
                            bar_index=j, label="C3",
                            direction=direction, swing_point=swing,
                        ))
                        used_indices.add(j)

                    # C4: wick in upper half of C3's range, expands higher
                    c3_bar = bars[j]
                    c3_mid = (c3_bar.high + c3_bar.low) / 2
                    for k in range(j + 1, min(j + 4, len(bars))):
                        # C4 wick should form in upper half of C3
                        if bars[k].low >= c3_mid and bars[k].close > c3_bar.high:
                            if k not in used_indices:
                                labels.append(CandleLabel(
                                    bar_index=k, label="C4",
                                    direction=direction, swing_point=swing,
                                ))
                                used_indices.add(k)
                            break
                    break

    labels.sort(key=lambda l: l.bar_index)
    return labels
