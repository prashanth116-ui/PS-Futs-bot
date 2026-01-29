# Session Notes - 2026-01-29

## TradingView Pro Connection

**Status**: Working

### What was done:
1. Tested TradingView connection - cached session from Jan 28 is still valid
2. Fixed `runners/run_tv_live.py` to use cached session instead of username/password (avoids CAPTCHA)
3. Added retry logic for intermittent websocket drops
4. Successfully ran live ICT strategy monitor

### Latest scan results (16:31):
- **ES**: 6988.50 | 14 signals found
- **NQ**: 25977.75 | 26 signals found

### Commands to resume:

```bash
# Run TradingView live monitor (scans every 3 minutes)
PYTHONPATH=. python runners/run_tv_live.py

# If session expires, re-authenticate via browser:
python runners/tv_login.py

# Quick connection test:
python -c "from tvDatafeed import TvDatafeed, Interval; tv = TvDatafeed(); df = tv.get_hist('ES1!', 'CME_MINI', Interval.in_5_minute, n_bars=3); print(df)"
```

### Files modified:
- `runners/run_tv_live.py` - Updated to use cached session with retry logic

### Notes:
- TradingView websocket connection can be flaky - retry logic handles this
- Session cached at `~/.tvdatafeed/` (cookies.json, tv_session.json)
- Credentials stored in `config/tradingview.env`
