"""
TTrades Fractal Model (TTFM) - Standalone Strategy Package.

A multi-timeframe mechanical trading system built on the principle that
price cannot reverse without forming a swing point. Uses candle numbering
(C1-C4), CISD confirmation, and daily bias alignment.

Usage:
    python -m ttfm.runners.run_ttfm ES 3
    python -m ttfm.runners.backtest_longrange ES 60
    python -m ttfm.runners.plot_ttfm ES 3
"""
