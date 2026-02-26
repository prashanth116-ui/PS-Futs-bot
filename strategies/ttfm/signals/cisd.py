"""
CISD (Change in State of Delivery) detection for TTFM.

Per TTrades: CISD tracks the OPENING PRICES of consecutive same-direction
candle series. When price closes through that opening price, the state of
delivery has changed — confirming an order block and trend shift.

Bearish CISD: A series of consecutive bullish (up-close) candles creates a
high. When a candle closes below the OPENING of that bullish series, bearish
CISD is confirmed.

Bullish CISD: A series of consecutive bearish (down-close) candles creates a
low. When a candle closes above the OPENING of that bearish series, bullish
CISD is confirmed.

The candles that formed the series become the "order block" zone. The swing
created by that series becomes a "protected swing" — used for stop placement.
"""

from core.types import Bar
from strategies.ttfm.types import CISD, SwingPoint


def detect_cisd(
    bars: list[Bar],
    swings: list[SwingPoint],
    lookback: int = 10,
) -> list[CISD]:
    """Detect CISD events using consecutive candle series openings.

    For each swing, identifies the consecutive same-direction candle series
    that created the swing, tracks the series opening price, and looks for
    a bar that closes through it.

    Args:
        bars: Chronologically ordered bars.
        swings: Pre-computed swing points from find_swings().
        lookback: Max bars after swing to look for CISD confirmation.

    Returns:
        List of CISD events sorted by bar_index.
    """
    cisds: list[CISD] = []

    for swing in swings:
        idx = swing.bar_index
        if idx < 1 or idx >= len(bars):
            continue

        if swing.swing_type == "HIGH":
            # Bearish CISD: find the bullish candle series that made the high,
            # then look for a close below that series' opening price.

            # Walk backwards to find the consecutive bullish (up-close) series
            series_start = idx
            for k in range(idx, max(idx - 10, 0) - 1, -1):
                if bars[k].close >= bars[k].open:  # bullish candle
                    series_start = k
                else:
                    break

            # The series opening = open of the first bullish candle in the series
            series_open = bars[series_start].open
            # OB zone = from series open to the high of the swing
            ob_low = min(bars[series_start].low, series_open)
            ob_high = swing.price  # the swing high

            # Look forward for a candle that closes below the series opening
            end = min(idx + lookback + 1, len(bars))
            for j in range(idx + 1, end):
                if bars[j].close < series_open:
                    cisds.append(CISD(
                        direction="BEARISH",
                        bar_index=j,
                        timestamp=bars[j].timestamp,
                        price=bars[j].close,
                        swing_price=swing.price,
                        ob_high=ob_high,
                        ob_low=ob_low,
                    ))
                    break
                # Invalidate if price makes a significant new high
                if bars[j].high > swing.price + (swing.price - series_open) * 0.5:
                    break

        elif swing.swing_type == "LOW":
            # Bullish CISD: find the bearish candle series that made the low,
            # then look for a close above that series' opening price.

            # Walk backwards to find the consecutive bearish (down-close) series
            series_start = idx
            for k in range(idx, max(idx - 10, 0) - 1, -1):
                if bars[k].close <= bars[k].open:  # bearish candle
                    series_start = k
                else:
                    break

            # The series opening = open of the first bearish candle in the series
            series_open = bars[series_start].open
            # OB zone = from the low to the series open
            ob_low = swing.price  # the swing low
            ob_high = max(bars[series_start].high, series_open)

            # Look forward for a candle that closes above the series opening
            end = min(idx + lookback + 1, len(bars))
            for j in range(idx + 1, end):
                if bars[j].close > series_open:
                    cisds.append(CISD(
                        direction="BULLISH",
                        bar_index=j,
                        timestamp=bars[j].timestamp,
                        price=bars[j].close,
                        swing_price=swing.price,
                        ob_high=ob_high,
                        ob_low=ob_low,
                    ))
                    break
                # Invalidate if price makes a significant new low
                if bars[j].low < swing.price - (series_open - swing.price) * 0.5:
                    break

    cisds.sort(key=lambda c: c.bar_index)
    return cisds
