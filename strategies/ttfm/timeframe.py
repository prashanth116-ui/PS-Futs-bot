"""
Timeframe aggregation for TTFM multi-timeframe analysis.

Converts 3-minute bars into higher timeframes (15m, 1H, 4H).
Daily bars are fetched separately via fetch_futures_bars.
"""

from datetime import datetime, timedelta
from core.types import Bar


def aggregate_bars(bars_3m: list[Bar], target_minutes: int) -> list[Bar]:
    """Aggregate 3m bars into higher timeframe bars.

    Args:
        bars_3m: List of 3-minute Bar objects, sorted chronologically.
        target_minutes: Target timeframe in minutes (15, 60, 240).

    Returns:
        List of aggregated Bar objects.
    """
    if not bars_3m or target_minutes <= 3:
        return list(bars_3m)

    result: list[Bar] = []
    bucket: list[Bar] = []
    bucket_start: datetime | None = None

    for bar in bars_3m:
        # Compute which bucket this bar belongs to
        ts = bar.timestamp
        # Align to target_minutes boundary
        total_minutes = ts.hour * 60 + ts.minute
        aligned_minutes = (total_minutes // target_minutes) * target_minutes
        aligned_ts = ts.replace(
            hour=aligned_minutes // 60,
            minute=aligned_minutes % 60,
            second=0,
            microsecond=0,
        )

        if bucket_start is None:
            bucket_start = aligned_ts

        if aligned_ts != bucket_start:
            # Flush previous bucket
            if bucket:
                result.append(_merge_bucket(bucket, bucket_start, target_minutes))
            bucket = [bar]
            bucket_start = aligned_ts
        else:
            bucket.append(bar)

    # Flush last bucket
    if bucket and bucket_start is not None:
        result.append(_merge_bucket(bucket, bucket_start, target_minutes))

    return result


def _merge_bucket(
    bucket: list[Bar], bucket_start: datetime, target_minutes: int
) -> Bar:
    """Merge a bucket of bars into one aggregated bar."""
    tf_label = f"{target_minutes}m" if target_minutes < 60 else f"{target_minutes // 60}h"
    return Bar(
        timestamp=bucket_start,
        open=bucket[0].open,
        high=max(b.high for b in bucket),
        low=min(b.low for b in bucket),
        close=bucket[-1].close,
        volume=sum(b.volume for b in bucket),
        symbol=bucket[0].symbol,
        timeframe=tf_label,
    )
