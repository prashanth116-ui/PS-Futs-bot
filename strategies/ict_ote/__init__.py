"""
ICT Optimal Trade Entry (OTE) Strategy

Entry conditions:
1. Impulse Leg - Strong directional move (displacement) creating swing high/low
2. OTE Zone - Calculate 62-79% Fibonacci retracement of impulse leg
3. FVG Confluence - Optional: FVG overlaps with OTE zone
4. Retracement Entry - Price retraces into OTE zone with rejection
5. Stop - Below impulse low (longs) / above impulse high (shorts) + buffer
"""
from strategies.ict_ote.strategy import ICTOTEStrategy

__all__ = ['ICTOTEStrategy']
