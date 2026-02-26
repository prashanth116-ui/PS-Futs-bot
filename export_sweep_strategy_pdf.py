"""Generate ICT Sweep Strategy PDF documentation."""
from fpdf import FPDF


class StrategyPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, 'ICT Liquidity Sweep Strategy', align='R')
        self.ln(4)
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', align='C')

    def section_title(self, title):
        self.set_font('Helvetica', 'B', 14)
        self.set_text_color(20, 60, 120)
        self.ln(4)
        self.cell(0, 10, title)
        self.ln(8)
        self.set_draw_color(20, 60, 120)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def subsection(self, title):
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(40, 40, 40)
        self.ln(2)
        self.cell(0, 8, title)
        self.ln(8)

    def body_text(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 5.5, text)
        self.ln(2)

    def code_block(self, text):
        self.set_font('Courier', '', 9)
        self.set_fill_color(245, 245, 245)
        self.set_text_color(50, 50, 50)
        x = self.get_x()
        self.set_x(x + 4)
        for line in text.strip().split('\n'):
            self.cell(180, 5.5, '  ' + line, fill=True)
            self.ln(5.5)
        self.ln(3)

    def bullet(self, text, indent=0):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(30, 30, 30)
        x = 14 + indent
        self.set_x(x)
        self.cell(4, 5.5, '-')
        self.multi_cell(180 - indent, 5.5, text)
        self.ln(1)

    def table_row(self, cols, widths, bold=False, fill=False):
        style = 'B' if bold else ''
        self.set_font('Helvetica', style, 9)
        if fill:
            self.set_fill_color(230, 240, 250)
        self.set_text_color(30, 30, 30)
        for i, (col, w) in enumerate(zip(cols, widths)):
            self.cell(w, 7, str(col), border=1, fill=fill, align='C' if i > 0 else 'L')
        self.ln(7)


def build_pdf():
    pdf = StrategyPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ===== TITLE PAGE =====
    pdf.add_page()
    pdf.ln(40)
    pdf.set_font('Helvetica', 'B', 28)
    pdf.set_text_color(20, 60, 120)
    pdf.cell(0, 15, 'ICT Liquidity Sweep Strategy', align='C')
    pdf.ln(20)
    pdf.set_font('Helvetica', '', 14)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 10, 'Technical Design Document', align='C')
    pdf.ln(10)
    pdf.cell(0, 10, 'Tradovate Futures Bot', align='C')
    pdf.ln(20)
    pdf.set_draw_color(20, 60, 120)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())
    pdf.ln(15)
    pdf.set_font('Helvetica', '', 11)
    pdf.cell(0, 8, 'Instruments: ES, NQ, MES, MNQ, SPY, QQQ', align='C')
    pdf.ln(8)
    pdf.cell(0, 8, 'Timeframes: HTF 5m (sweep) | MTF 3m (FVG) | LTF 3m (MSS)', align='C')
    pdf.ln(8)
    pdf.cell(0, 8, 'Date: February 2026', align='C')

    # ===== THE ICT CONCEPT =====
    pdf.add_page()
    pdf.section_title('1. The ICT Concept')
    pdf.body_text(
        'Smart money (institutions) hunt stop losses before moving price in the real direction. '
        'Retail traders place stops above swing highs and below swing lows. Institutions push price '
        'through those levels to trigger stops (get liquidity), then reverse.'
    )
    pdf.body_text(
        'The ICT Liquidity Sweep strategy detects these stop hunts in real-time and enters in the '
        'direction of the expected reversal after confirmation via displacement and Fair Value Gap formation.'
    )

    # ===== 5-STEP FLOW =====
    pdf.section_title('2. The 5-Step Entry Flow')
    pdf.code_block(
        'Step 1: LIQUIDITY LEVELS   - Find swing highs/lows where stops cluster\n'
        'Step 2: SWEEP              - Price wicks through a level and rejects\n'
        'Step 3: DISPLACEMENT       - A strong candle confirms institutional intent\n'
        'Step 4: FVG FORMS          - An imbalance zone (gap) appears\n'
        'Step 5: FVG MITIGATION     - Price retraces into the gap -> ENTRY'
    )

    # ===== STEP 1 =====
    pdf.section_title('3. Step 1: Liquidity Levels')
    pdf.subsection('Source: signals/liquidity.py')
    pdf.body_text(
        'Finds swing highs and swing lows on 5m (HTF) bars. These are price levels where retail '
        'stop losses cluster - above swing highs (buy stops) and below swing lows (sell stops).'
    )
    pdf.subsection('Swing Detection Logic')
    pdf.body_text(
        'A swing high requires N bars on each side (swing_strength) with strictly lower highs. '
        'A swing low requires N bars on each side with strictly higher lows. Default swing_strength = 3.'
    )
    pdf.code_block(
        'Swing High Example (strength=3):\n'
        '\n'
        '            * swing high\n'
        '          /   \\\n'
        '        /       \\\n'
        '      /           \\\n'
        '    3 bars left    3 bars right - all lower highs'
    )
    pdf.subsection('Key Functions')
    pdf.bullet('is_swing_high(bars, index, lookback=3) - checks if bar is a swing high')
    pdf.bullet('is_swing_low(bars, index, lookback=3) - checks if bar is a swing low')
    pdf.bullet('find_liquidity_levels(bars, lookback=3, max_levels=5) - returns dict of highs/lows')
    pdf.subsection('Parameters')
    w = [60, 30, 90]
    pdf.table_row(['Parameter', 'Value', 'Description'], w, bold=True, fill=True)
    pdf.table_row(['swing_lookback', '20', 'Bars to search for swing points'], w)
    pdf.table_row(['swing_strength', '3', 'Bars on each side to confirm swing'], w)
    pdf.table_row(['max_levels', '5', 'Max liquidity levels to track per side'], w)

    # ===== STEP 2 =====
    pdf.section_title('4. Step 2: Sweep Detection')
    pdf.subsection('Source: signals/sweep.py')
    pdf.body_text(
        'Checks the last 3 HTF bars against known swing levels. A sweep occurs when price briefly '
        'breaks through a swing level (triggering stops) then closes back on the other side (rejection).'
    )
    pdf.subsection('Bullish Sweep (swept low, expect UP)')
    pdf.bullet("Bar's wick goes BELOW a swing low by at least 2 ticks")
    pdf.bullet('Bar CLOSES ABOVE the swing low (rejection)')
    pdf.bullet('Stops were triggered below, but price reversed upward')
    pdf.subsection('Bearish Sweep (swept high, expect DOWN)')
    pdf.bullet("Bar's wick goes ABOVE a swing high by at least 2 ticks")
    pdf.bullet('Bar CLOSES BELOW the swing high (rejection)')
    pdf.bullet('Stops were triggered above, but price reversed downward')
    pdf.code_block(
        'Bearish Sweep Example:\n'
        '\n'
        '                 wick above swing high (stop hunt)\n'
        '    --------*--- swing high level\n'
        '              |  close below (rejection)\n'
        '              |'
    )
    pdf.subsection('Parameters')
    w = [60, 30, 90]
    pdf.table_row(['Parameter', 'Value', 'Description'], w, bold=True, fill=True)
    pdf.table_row(['min_sweep_ticks', '2', 'Min ticks beyond swing level'], w)
    pdf.table_row(['max_sweep_ticks', '50', 'Max sweep depth (too deep = not a sweep)'], w)
    pdf.table_row(['check_bars', '3', 'Recent bars to check for sweep'], w)

    # ===== STEP 3 =====
    pdf.section_title('5. Step 3: Displacement')
    pdf.subsection('Source: filters/displacement.py')
    pdf.body_text(
        'After a sweep, we need a strong rejection candle to confirm institutional intent. '
        'Displacement measures candle body size relative to the 20-bar average body.'
    )
    pdf.code_block(
        'displacement_ratio = abs(close - open) / avg_body_20\n'
        '\n'
        'Currently requires >= 1.5x average body.'
    )
    pdf.body_text('The code checks displacement on:')
    pdf.bullet('The sweep bar itself')
    pdf.bullet('The bar before the sweep')
    pdf.bullet('Up to 2 bars after the sweep')
    pdf.body_text(
        'Takes the maximum ratio found across all checked bars. If none reach the threshold, '
        'the sweep is discarded.'
    )
    pdf.subsection('Parameters')
    w = [60, 30, 90]
    pdf.table_row(['Parameter', 'Value', 'Description'], w, bold=True, fill=True)
    pdf.table_row(['displacement_multiplier', '1.5', 'Min body size vs 20-bar avg'], w)
    pdf.table_row(['avg_body_lookback', '20', 'Bars for average body calculation'], w)
    pdf.table_row(['high_disp_override', '3.0', '3x+ skips optional hybrid filters'], w)

    # ===== STEP 4 =====
    pdf.add_page()
    pdf.section_title('6. Step 4: FVG Detection')
    pdf.subsection('Source: signals/fvg.py')
    pdf.body_text(
        'A Fair Value Gap (FVG) is a 3-candle pattern where there is no price overlap between '
        'candle 1 and candle 3. The middle candle is the displacement candle.'
    )
    pdf.subsection('Bullish FVG')
    pdf.body_text('bar3.low > bar1.high (gap below - price wants to fill upward)')
    pdf.code_block(
        'bar3  ####\n'
        '      | bar3.low\n'
        '      === GAP ===\n'
        '      | bar1.high\n'
        'bar1  ####'
    )
    pdf.subsection('Bearish FVG')
    pdf.body_text('bar3.high < bar1.low (gap above - price wants to fill downward)')
    pdf.code_block(
        'bar1  ####\n'
        '      | bar1.low\n'
        '      === GAP ===\n'
        '      | bar3.high\n'
        'bar3  ####'
    )
    pdf.subsection('Search Order')
    pdf.bullet('HTF (5m) bars first - up to 10 windows after sweep bar')
    pdf.bullet('MTF (3m) bars second (if enabled) - up to 17 windows, catches smaller gaps')
    pdf.bullet('If no FVG found, sweep is queued as "pending" for up to 15 bars')
    pdf.subsection('Parameters')
    w = [60, 30, 90]
    pdf.table_row(['Parameter', 'Value', 'Description'], w, bold=True, fill=True)
    pdf.table_row(['min_fvg_ticks (ES)', '3', 'Min gap size in ticks'], w)
    pdf.table_row(['min_fvg_ticks (NQ)', '8', 'Min gap size in ticks'], w)
    pdf.table_row(['max_fvg_age_bars', '50', 'Remove FVGs older than this'], w)
    pdf.table_row(['max_fvg_wait_bars', '15', 'Bars to wait for FVG after sweep'], w)
    pdf.table_row(['use_mtf_for_fvg', 'True', 'Also check 3m bars for FVG'], w)

    # ===== STEP 5 =====
    pdf.section_title('7. Step 5: FVG Mitigation & Entry')
    pdf.subsection('Source: strategy.py - check_htf_mitigation()')
    pdf.body_text(
        'Once we have Sweep + Displacement + FVG, we wait for price to retrace into the FVG zone '
        '(mitigation). This is the entry trigger.'
    )
    pdf.subsection('Mitigation Check')
    pdf.bullet('Bullish FVG: bar.low <= fvg.top (wick touches or enters zone from above)')
    pdf.bullet('Bearish FVG: bar.high >= fvg.bottom (wick touches or enters zone from below)')
    pdf.code_block(
        'Bullish Entry Example:\n'
        '\n'
        '         ^ price moved up after sweep\n'
        '         |\n'
        '    -----| FVG top\n'
        '         | <- price retraces into zone = MITIGATION -> ENTRY\n'
        '    -----| FVG bottom (stop goes here - buffer)\n'
    )
    pdf.subsection('Two Entry Paths')
    pdf.body_text(
        'Path A (current): entry_on_mitigation=True - enters immediately when price touches FVG zone. '
        'Faster entries but higher false signal risk.'
    )
    pdf.body_text(
        'Path B (disabled): entry_on_mitigation=False - waits for MSS (Market Structure Shift) '
        'confirmation after mitigation. Slower but more confirmed entries.'
    )
    pdf.subsection('Entry Construction')
    pdf.bullet('Entry price: bar close at mitigation time')
    pdf.bullet('Stop (long): fvg.bottom - 2.0 points buffer')
    pdf.bullet('Stop (short): fvg.top + 2.0 points buffer')
    pdf.bullet('T1 target: entry + 3R (1 contract, fixed exit)')
    pdf.bullet('Trail activation: entry + 6R (structure trail for T2 + Runner)')

    # ===== HYBRID FILTERS =====
    pdf.add_page()
    pdf.section_title('8. Hybrid Filter System')
    pdf.subsection('Source: strategy.py - _check_hybrid_filters()')
    pdf.body_text(
        'Adopted from V10.8. Two mandatory filters must pass, plus 2 of 3 optional filters.'
    )
    pdf.subsection('MANDATORY (must pass)')
    pdf.bullet('DI Direction: +DI > -DI for BULLISH, -DI > +DI for BEARISH')
    pdf.bullet('FVG Size: >= min_fvg_ticks (enforced in FVG detection)')
    pdf.subsection('OPTIONAL (2 of 3 must pass)')
    pdf.bullet('Displacement: >= 1.5x average body')
    pdf.bullet('ADX Strength: >= 11')
    pdf.bullet('EMA Trend: EMA20 > EMA50 for BULLISH, EMA20 < EMA50 for BEARISH')
    pdf.subsection('High Displacement Override')
    pdf.body_text(
        'If displacement ratio >= 3.0x average body, ALL optional filters are skipped. '
        'Only the mandatory DI direction check is required. This captures high-conviction '
        'institutional sweeps that have overwhelming momentum.'
    )

    # ===== EXIT STRUCTURE =====
    pdf.section_title('9. Exit Structure')
    pdf.subsection('Source: run_ict_sweep.py - simulate_trade()')
    pdf.body_text('Hybrid exit with partial profit-taking and structure trailing:')
    pdf.code_block(
        'Entry: Dynamic contracts at bar close\n'
        '  - 1st trade of direction: 3 contracts (T1 + T2 + Runner)\n'
        '  - 2nd+ trade: 2 contracts (T1 + T2, no runner)\n'
        '\n'
        'Pre-T1: FVG-close stop exits ALL contracts\n'
        '  - Candle CLOSE past FVG boundary = stop out\n'
        '  - Safety cap: 100 tick max loss\n'
        '\n'
        'T1 hit (3R): Fixed exit 1 contract - guaranteed profit\n'
        '  - Trail floor set at 3R for remaining contracts\n'
        '\n'
        'Trail activation (6R): Structure trailing begins\n'
        '  - T2: 4-tick buffer from swing structure\n'
        '  - Runner: 6-tick buffer (wider, stays longer)\n'
        '\n'
        'EOD: Exit all remaining at close'
    )
    pdf.subsection('FVG-Close Stop Logic')
    pdf.body_text(
        'Unlike a traditional tick-based stop, this strategy uses a CLOSE-based stop. '
        'If a candle closes past the FVG boundary (not just wicks through), all remaining '
        'contracts are stopped out. This gives more room for wicks while respecting the '
        'FVG as a structural level.'
    )

    # ===== SESSION FILTERS =====
    pdf.section_title('10. Session Filters')
    pdf.subsection('Source: filters/session.py')
    pdf.body_text('Trading is restricted to specific time windows:')
    w = [50, 40, 90]
    pdf.table_row(['Session', 'Time (ET)', 'Status'], w, bold=True, fill=True)
    pdf.table_row(['London', '02:00-05:00', 'Sweep detection only (HTF)'], w)
    pdf.table_row(['Pre-market', '08:00-09:30', 'Sweep detection only (HTF)'], w)
    pdf.table_row(['NY Open', '09:30-11:00', 'Active trading'], w)
    pdf.table_row(['Late Morning', '11:00-12:00', 'Active trading'], w)
    pdf.table_row(['Lunch Lull', '12:00-13:00', 'BLOCKED (allow_lunch=False)'], w)
    pdf.table_row(['NY PM', '13:00-16:00', 'Active trading'], w)

    # ===== DAILY LIMITS =====
    pdf.section_title('11. Risk Management & Daily Limits')
    w = [60, 30, 90]
    pdf.table_row(['Parameter', 'Value', 'Description'], w, bold=True, fill=True)
    pdf.table_row(['max_daily_trades', '5', 'Max trades per day (all directions)'], w)
    pdf.table_row(['max_daily_losses', '3', 'Stop trading after 3 losses (global)'], w)
    pdf.table_row(['loss_cooldown_minutes', '0', 'No cooldown between losses'], w)
    pdf.table_row(['min_risk_ticks (ES)', '12', 'Skip FVGs with tiny risk'], w)
    pdf.table_row(['max_risk_ticks (ES)', '40', 'Skip FVGs with huge risk (10 pts)'], w)
    pdf.table_row(['max_risk_ticks (NQ)', '80', 'NQ wider range (20 pts)'], w)
    pdf.table_row(['stop_buffer_pts', '2.0', 'Points beyond FVG for stop'], w)

    # ===== MSS (OPTIONAL PATH) =====
    pdf.add_page()
    pdf.section_title('12. MSS Confirmation (Optional Path)')
    pdf.subsection('Source: signals/mss.py')
    pdf.body_text(
        'Market Structure Shift (MSS) is a break of structure that confirms reversal. '
        'Currently DISABLED (entry_on_mitigation=True). When enabled, adds a confirmation '
        'step after FVG mitigation.'
    )
    pdf.subsection('MSS Logic')
    pdf.bullet('Bullish MSS: price closes above a recent swing high (confirms upside)')
    pdf.bullet('Bearish MSS: price closes below a recent swing low (confirms downside)')
    pdf.bullet('MSS break level is locked in at FVG mitigation time')
    pdf.bullet('LTF (3m) bars are monitored for the break')
    pdf.subsection('Parameters')
    w = [60, 30, 90]
    pdf.table_row(['Parameter', 'Value', 'Description'], w, bold=True, fill=True)
    pdf.table_row(['mss_lookback', '20', 'Bars back to find swing for MSS'], w)
    pdf.table_row(['mss_swing_strength', '1', 'Very permissive swing detection'], w)

    # ===== ARCHITECTURE =====
    pdf.section_title('13. File Architecture')
    w = [65, 115]
    pdf.table_row(['File', 'Purpose'], w, bold=True, fill=True)
    pdf.table_row(['strategy.py', 'Main strategy class, orchestrates all signals'], w)
    pdf.table_row(['signals/liquidity.py', 'Swing high/low detection (liquidity levels)'], w)
    pdf.table_row(['signals/sweep.py', 'Sweep detection (stop hunt identification)'], w)
    pdf.table_row(['signals/fvg.py', 'FVG detection, mitigation check, price-in-zone'], w)
    pdf.table_row(['signals/mss.py', 'Market Structure Shift detection'], w)
    pdf.table_row(['filters/displacement.py', 'Candle body analysis, displacement ratio'], w)
    pdf.table_row(['filters/session.py', 'Time-of-day filters, session identification'], w)
    pdf.ln(4)
    w = [65, 115]
    pdf.table_row(['Runner File', 'Purpose'], w, bold=True, fill=True)
    pdf.table_row(['run_ict_sweep.py', 'Backtest runner, trade simulation, CLI'], w)
    pdf.table_row(['plot_ict_sweep.py', 'Chart visualization with trade markers'], w)

    # ===== BACKTEST RESULTS =====
    pdf.section_title('14. Backtest Results (ES, 11 Trading Days)')
    pdf.subsection('A/B Test: Baseline vs Improved Defaults')
    w = [45, 35, 35, 35, 35]
    pdf.table_row(['Metric', 'Baseline', 'New', 'Delta', 'Change'], w, bold=True, fill=True)
    pdf.table_row(['Total Trades', '10', '32', '+22', '+220%'], w)
    pdf.table_row(['Wins', '2', '11', '+9', ''], w)
    pdf.table_row(['Losses', '8', '21', '+13', ''], w)
    pdf.table_row(['Win Rate', '20.0%', '34.4%', '+14.4pp', ''], w)
    pdf.table_row(['Avg Win', '$3,994', '$2,719', '-$1,275', ''], w)
    pdf.table_row(['Avg Loss', '-$763', '-$896', '-$133', ''], w)
    pdf.table_row(['Profit Factor', '1.31', '1.59', '+0.28', ''], w)
    pdf.table_row(['Total P/L', '$1,888', '$11,088', '+$9,200', '+487%'], w)

    pdf.ln(4)
    pdf.subsection('Baseline Config (Old)')
    pdf.code_block(
        'max_daily_trades=2  max_daily_losses=1  cooldown=15min\n'
        'displacement=2.0x   fvg_wait=10 bars\n'
        'EMA 10/20 trend filter (no DI, no hybrid)'
    )
    pdf.subsection('New Defaults')
    pdf.code_block(
        'max_daily_trades=5  max_daily_losses=3  cooldown=0\n'
        'displacement=1.5x   fvg_wait=15 bars\n'
        'Hybrid filters: DI mandatory + 2/3 optional (disp/ADX/EMA20-50)\n'
        'High displacement override: 3.0x skips optional filters'
    )

    # ===== CLI REFERENCE =====
    pdf.add_page()
    pdf.section_title('15. CLI Reference')
    pdf.subsection('Basic Usage')
    pdf.code_block(
        '# Run backtest (default: ES, 14 days, 3 contracts)\n'
        'python -m runners.run_ict_sweep ES 18\n'
        'python -m runners.run_ict_sweep NQ 18\n'
        '\n'
        '# Plot results\n'
        'python -m runners.plot_ict_sweep ES\n'
        'python -m runners.plot_ict_sweep ES 2026 2 12'
    )
    pdf.subsection('Parameter Flags')
    w = [50, 25, 105]
    pdf.table_row(['Flag', 'Default', 'Description'], w, bold=True, fill=True)
    pdf.table_row(['--max-trades=N', '5', 'Max daily trades'], w)
    pdf.table_row(['--max-losses=N', '3', 'Max daily losses before shutdown'], w)
    pdf.table_row(['--cooldown=N', '0', 'Minutes cooldown after a loss'], w)
    pdf.table_row(['--disp=N', '1.5', 'Displacement multiplier threshold'], w)
    pdf.table_row(['--fvg-wait=N', '15', 'Max bars to wait for FVG after sweep'], w)
    pdf.table_row(['--t1-r=N', '3', 'R-multiple for T1 fixed exit'], w)
    pdf.table_row(['--trail-r=N', '6', 'R-multiple for trail activation'], w)
    pdf.table_row(['--min-adx=N', '11', 'Min ADX for optional filter'], w)
    pdf.table_row(['--high-disp=N', '3.0', 'High displacement override (0=off)'], w)

    pdf.subsection('Filter Flags')
    w = [55, 25, 100]
    pdf.table_row(['Flag', 'Default', 'Description'], w, bold=True, fill=True)
    pdf.table_row(['--hybrid-filters', 'ON', 'Enable hybrid filter system'], w)
    pdf.table_row(['--no-hybrid-filters', '', 'Disable hybrid filters'], w)
    pdf.table_row(['--use-di-filter', 'ON', 'Enable DI direction filter'], w)
    pdf.table_row(['--no-di-filter', '', 'Disable DI filter'], w)
    pdf.table_row(['--use-trend-filter', 'OFF', 'Enable legacy EMA trend filter'], w)
    pdf.table_row(['--no-trend-filter', '', 'Disable legacy trend filter'], w)

    pdf.subsection('A/B Test Commands')
    pdf.code_block(
        '# Baseline (old settings)\n'
        'python -m runners.run_ict_sweep ES 18 --max-trades=2 --max-losses=1 \\\n'
        '  --cooldown=15 --disp=2.0 --fvg-wait=10 \\\n'
        '  --no-hybrid-filters --no-di-filter --use-trend-filter\n'
        '\n'
        '# New defaults (all improvements)\n'
        'python -m runners.run_ict_sweep ES 18'
    )

    # Save
    output = 'ICT_Sweep_Strategy.pdf'
    pdf.output(output)
    print(f'PDF saved: {output}')


if __name__ == '__main__':
    build_pdf()
