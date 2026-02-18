"""Generate ICT Liquidity Sweep Strategy summary PDF."""
from fpdf import FPDF


class StrategyPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 16)
        self.cell(0, 10, 'ICT Liquidity Sweep Strategy', new_x="LMARGIN", new_y="NEXT", align='C')
        self.set_font('Helvetica', '', 10)
        self.cell(0, 6, 'ES Futures | February 2026', new_x="LMARGIN", new_y="NEXT", align='C')
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

    def section_title(self, title):
        self.set_font('Helvetica', 'B', 13)
        self.set_fill_color(30, 60, 120)
        self.set_text_color(255, 255, 255)
        self.cell(0, 8, f'  {title}', new_x="LMARGIN", new_y="NEXT", fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(3)

    def sub_title(self, title):
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(30, 60, 120)
        self.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def body_text(self, text):
        self.set_font('Helvetica', '', 10)
        self.multi_cell(0, 5, text)
        self.ln(2)

    def bullet(self, text, indent=10):
        self.set_font('Helvetica', '', 10)
        self.set_x(self.l_margin + indent)
        self.multi_cell(0, 5, f'-  {text}')
        self.ln(1)

    def numbered(self, num, text, indent=10):
        self.set_font('Helvetica', '', 10)
        self.set_x(self.l_margin + indent)
        self.multi_cell(0, 5, f'{num}.  {text}')
        self.ln(1)

    def table_header(self, cols, widths):
        self.set_font('Helvetica', 'B', 9)
        self.set_fill_color(220, 230, 245)
        for col, w in zip(cols, widths):
            self.cell(w, 6, col, border=1, fill=True, align='C')
        self.ln()

    def table_row(self, cols, widths, bold=False):
        self.set_font('Helvetica', 'B' if bold else '', 9)
        for col, w in zip(cols, widths):
            self.cell(w, 6, str(col), border=1, align='C')
        self.ln()

    def code_block(self, text):
        self.set_font('Courier', '', 9)
        self.set_fill_color(245, 245, 245)
        for line in text.split('\n'):
            self.cell(0, 5, f'  {line}', new_x="LMARGIN", new_y="NEXT", fill=True)
        self.ln(3)


def generate():
    pdf = StrategyPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # --- HOW IT WORKS ---
    pdf.section_title('How It Works (5-Step Pipeline)')

    steps = [
        ('1. SWEEP (5m)', 'Price wicks past a swing high/low (stop hunt). Swing strength=3, min 2 ticks, max 50 ticks.'),
        ('2. DISPLACEMENT', 'Large candle body >=2x average on the sweep bar or up to 2 bars after it.'),
        ('3. FVG FORMS', 'Fair Value Gap detected on 5m or 3m timeframe (>=3 ticks minimum).'),
        ('4. MITIGATION', 'Price retraces back into the FVG zone. Setup stays alive if filters block entry.'),
        ('5. ENTRY', 'Tap entry at FVG touch on the bar close. No MSS confirmation needed.'),
    ]
    for title, desc in steps:
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(35, 5, title)
        pdf.set_font('Helvetica', '', 10)
        pdf.multi_cell(0, 5, desc)
        pdf.ln(1)

    pdf.ln(2)
    pdf.sub_title('Exit Logic')
    pdf.bullet('Stop: FVG-close stop -- only exits if candle CLOSES past FVG boundary. Wicks tolerated. Safety cap at 100 ticks.')
    pdf.bullet('T1: 2R target (partial exit)')
    pdf.bullet('T2: 4R target (full exit)')
    pdf.bullet('EOD: Close at end of day if neither target hit')

    # --- TIMEFRAMES ---
    pdf.ln(2)
    pdf.section_title('Timeframes')
    w = [25, 25, 140]
    pdf.table_header(['Role', 'TF', 'Purpose'], w)
    pdf.table_row(['HTF', '5m', 'Sweep detection, swing highs/lows'], w)
    pdf.table_row(['MTF', '3m', 'FVG detection (catches gaps 5m misses)'], w)
    pdf.table_row(['LTF', '3m', 'Trade simulation bars'], w)
    pdf.table_row(['Trend', '2m', 'EMA 10/20 for faster trend detection'], w)

    # --- FILTERS ---
    pdf.ln(4)
    pdf.section_title('Current Filters')
    w = [45, 30, 115]
    pdf.table_header(['Filter', 'Value', 'Purpose'], w)
    pdf.table_row(['EMA 10/20 on 2m', 'Trend', 'Fast trend alignment -- catches reversals earlier'], w)
    pdf.table_row(['Min risk', '12 ticks', 'Skip tiny FVGs that always get stop-hunted'], w)
    pdf.table_row(['Max risk', '80 ticks', 'Cap oversized entries'], w)
    pdf.table_row(['Loss cooldown', '15 min', 'No re-entry within 15 min of a loss'], w)
    pdf.table_row(['Max daily trades', '2', 'Cap exposure per day'], w)
    pdf.table_row(['Max daily losses', '1', 'Circuit breaker -- stop trading after 1 loss'], w)
    pdf.table_row(['Displacement', '>=2x body', 'Confirm strong rejection after sweep'], w)
    pdf.table_row(['Min FVG', '3 ticks', 'Filter noise gaps'], w)
    pdf.table_row(['FVG age', '50 bars', 'Remove stale setups'], w)

    # --- IMPROVEMENTS THIS SESSION ---
    pdf.add_page()
    pdf.section_title('Improvements Made (Feb 15, 2026)')
    w = [42, 68, 80]
    pdf.table_header(['Fix', 'What Changed', 'Impact'], w)
    pdf.table_row(['Displacement fix', 'Check +2 bars after sweep', 'Catches post-sweep displacement'], w)
    pdf.table_row(['EMA 10/20 on 2m', 'Faster trend on lower TF', 'Earlier entries on reversals'], w)
    pdf.table_row(['Mitigation retry', 'Retry entry next bar if blocked', 'Allows entry when trend catches up'], w)
    pdf.table_row(['FVG-close stop', 'Stop on CLOSE not wick', 'Survives liquidity grabs'], w)

    # --- RESULTS ---
    pdf.ln(4)
    pdf.section_title('Backtest Results (15 Trading Days)')
    w = [55, 20, 15, 15, 15, 15, 30]
    pdf.table_header(['Version', 'Trades', 'Wins', 'Loss', 'WR', 'PF', 'P/L'], w)
    pdf.table_row(['Baseline', '8', '4', '4', '50%', '3.52', '+$16,725'], w)
    pdf.table_row(['+ Disp/EMA/Retry', '14', '8', '6', '57%', '2.85', '+$21,938'], w)
    pdf.table_row(['+ FVG-close stop', '15', '10', '5', '67%', '3.02', '+$26,400'], w, bold=True)

    pdf.ln(3)
    pdf.sub_title('Key Trade: Feb 11, 2026')
    pdf.body_text(
        'Sweep at 09:30 (high 7011.50 sweeps prior swing). '
        'Displacement on 09:35 bar (8pt bearish body, 3.2x average). '
        'FVG formed on 5m: top=7000.00, bottom=6998.50 (6 ticks). '
        'EMA 10/20 flips bearish at 09:45. Entry at 6996.50, stop at 7002.00 (FVG top + 2pts). '
        'Hit 2R target at 6974.50 for +$3,300.'
    )

    # --- POTENTIAL IMPROVEMENTS ---
    pdf.add_page()
    pdf.section_title('Potential Improvements & Filters')

    pdf.sub_title('Entry Improvements')
    pdf.numbered(1, 'Displacement direction check -- Verify displacement candle direction matches expected move (bearish body after sweep high, bullish after sweep low). Currently only checks body size.')
    pdf.numbered(2, 'Multi-FVG stacking -- Enter on the nearest unmitigated FVG when multiple form in the same direction. Better entry, tighter stop.')
    pdf.numbered(3, 'Swing strength adaptation -- Lower swing_strength during high-volatility sessions; raise during low-vol to reduce noise.')
    pdf.numbered(4, 'HTF bias filter -- Only take trades aligned with the daily/4H trend (e.g., SHORT only if daily close < daily open).')

    pdf.sub_title('Stop & Exit Improvements')
    pdf.numbered(5, 'Partial FVG-close stop -- After T1 hit, tighten stop to breakeven or FVG midpoint instead of full boundary.')
    pdf.numbered(6, 'Trail stop after T1 -- Trail using structure (swing lows for longs, swing highs for shorts) instead of fixed T2.')
    pdf.numbered(7, 'R-target tuning -- Test 3R/6R targets (like V10.9). Lower T1 locks profit before pullbacks.')
    pdf.numbered(8, 'Time-based exit -- Exit if T1 not hit within 30 bars (~90 min). Stale trades tend to mean-revert.')

    pdf.sub_title('Filter Improvements')
    pdf.numbered(9, 'Volume confirmation -- Require above-average volume on sweep or displacement bar.')
    pdf.numbered(10, 'Session filter -- Restrict entries to kill zones (9:30-11:00, 14:00-15:30). Filter midday chop.')
    pdf.numbered(11, 'ADX filter -- Only enter when ADX >= threshold to confirm trending conditions.')
    pdf.numbered(12, 'Consecutive loss protection -- After 2 consecutive losses across days, reduce size or pause.')
    pdf.numbered(13, 'FVG age filter -- Only enter FVGs <= N bars old. Stale FVGs more likely invalidated.')
    pdf.numbered(14, 'Opposing FVG exit -- Exit early if an FVG forms in the opposite direction (reversal signal).')

    pdf.sub_title('Architecture Improvements')
    pdf.numbered(15, 'Dynamic position sizing -- 3 contracts on first trade, 2 on subsequent (like V10.7).')
    pdf.numbered(16, 'Per-direction limits -- Allow 1 long + 1 short simultaneously instead of 2 max total.')
    pdf.numbered(17, 'BOS entry type -- Add Break of Structure entry alongside FVG mitigation.')
    pdf.numbered(18, 'Multi-symbol -- Run on NQ simultaneously with NQ-specific parameters (min risk 6pts, tick value $5).')

    # Save
    out = 'ICT_Sweep_Strategy_Summary.pdf'
    pdf.output(out)
    print(f'PDF saved to {out}')


if __name__ == '__main__':
    generate()
