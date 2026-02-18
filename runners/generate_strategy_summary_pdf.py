"""Generate ICT FVG V10.10 Strategy Summary PDF."""
import sys
sys.path.insert(0, '.')

from fpdf import FPDF


class StrategyPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, 'ICT FVG V10.10 Strategy Summary', align='R')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', align='C')

    def section_title(self, title):
        self.set_font('Helvetica', 'B', 14)
        self.set_text_color(25, 118, 210)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(25, 118, 210)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def sub_title(self, title):
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(50, 50, 50)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body_text(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 5.5, text)
        self.ln(2)

    def code_block(self, text):
        self.set_font('Courier', '', 9)
        self.set_fill_color(240, 240, 240)
        self.set_text_color(30, 30, 30)
        x = self.get_x()
        self.set_x(x + 5)
        self.multi_cell(180, 5, text, fill=True)
        self.ln(3)

    def add_table(self, headers, data, col_widths=None, highlight_rows=None):
        if col_widths is None:
            col_widths = [190 / len(headers)] * len(headers)

        # Header
        self.set_font('Helvetica', 'B', 9)
        self.set_fill_color(25, 118, 210)
        self.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, h, border=1, fill=True, align='C')
        self.ln()

        # Data rows
        self.set_font('Helvetica', '', 9)
        for row_idx, row in enumerate(data):
            if highlight_rows and row_idx in highlight_rows:
                self.set_font('Helvetica', 'B', 9)
                self.set_fill_color(200, 230, 201)
            else:
                self.set_font('Helvetica', '', 9)
                self.set_fill_color(255, 255, 255)
            self.set_text_color(30, 30, 30)
            for i, cell in enumerate(row):
                self.cell(col_widths[i], 6.5, str(cell), border=1, fill=True, align='C')
            self.ln()
        self.ln(3)

    def bullet(self, text, bold_prefix=None):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(30, 30, 30)
        x = self.get_x()
        self.set_x(x + 5)
        self.cell(5, 5.5, '-')
        if bold_prefix:
            self.set_font('Helvetica', 'B', 10)
            self.cell(self.get_string_width(bold_prefix) + 2, 5.5, bold_prefix)
            self.set_font('Helvetica', '', 10)
            self.multi_cell(0, 5.5, text)
        else:
            self.multi_cell(170, 5.5, text)
        self.ln(1)


def generate_pdf():
    pdf = StrategyPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ==================== PAGE 1: Title + Core Concept ====================
    pdf.add_page()

    # Title
    pdf.set_font('Helvetica', 'B', 24)
    pdf.set_text_color(25, 118, 210)
    pdf.cell(0, 15, 'ICT FVG V10.10', align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.set_font('Helvetica', '', 14)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 10, 'Fair Value Gap Trading Strategy', align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.set_font('Helvetica', 'I', 10)
    pdf.cell(0, 8, 'February 17, 2026', align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)

    # Core Concept
    pdf.section_title('Core Concept')
    pdf.body_text(
        'The strategy trades Fair Value Gaps (FVGs) - price gaps left when a strong candle '
        'skips over a price range. These gaps act as magnets where price tends to return and '
        'bounce, giving high-probability entries.'
    )

    pdf.sub_title('How an FVG Forms')
    pdf.code_block(
        'Bar 1: Close at 6830\n'
        'Bar 2: Strong bullish candle (6830 -> 6840)  <- displacement\n'
        'Bar 3: Opens at 6838\n'
        '\n'
        'Gap = Bar 1 High to Bar 3 Low (e.g., 6832-6836)\n'
        'This 4-point gap is the FVG - price "skipped" this zone'
    )

    # ==================== Entry Types ====================
    pdf.section_title('Entry Types')
    pdf.body_text('The strategy has 4 ways to enter a trade, each exploiting FVGs differently:')

    pdf.add_table(
        ['Type', 'Name', 'Description'],
        [
            ['A', 'Creation', 'Enter immediately when FVG forms with displacement'],
            ['B1', 'Overnight Retrace', 'Price retraces into overnight FVG + rejection (ADX >= 22)'],
            ['B2', 'Intraday Retrace', 'Price retraces into session FVG (2+ bars old) + rejection'],
            ['C', 'BOS Retrace', 'Price retraces into FVG after Break of Structure'],
        ],
        col_widths=[15, 40, 135],
    )

    pdf.body_text(
        'Creation entries dominate (85-100% of trades). BOS entries are disabled for ES/MES '
        '(20-38% win rate) and enabled for NQ/MNQ with a 1 loss/day limit.'
    )

    # ==================== Entry Filters ====================
    pdf.section_title('Entry Filters')

    pdf.sub_title('Mandatory (must pass both)')
    pdf.bullet('DI Direction - +DI > -DI for LONG, -DI > +DI for SHORT', 'DI Direction: ')
    pdf.bullet('At least 5 ticks (futures) or min size (equities)', 'FVG Size: ')

    pdf.sub_title('Optional (must pass 2 of 3)')
    pdf.bullet('Candle body >= 1.0x average body (3x override skips ADX)', 'Displacement: ')
    pdf.bullet('>= 11 (trend strength filter)', 'ADX: ')
    pdf.bullet('EMA20 > EMA50 for LONG, EMA20 < EMA50 for SHORT', 'EMA Trend: ')

    pdf.sub_title('Time Filters')
    pdf.bullet('No entries 12:00-14:00 ET (lunch lull)')
    pdf.bullet('No NQ/MNQ entries after 14:00 ET')
    pdf.bullet('Max 3 open trades per direction')
    pdf.bullet('3 losses per direction per day (direction-aware circuit breaker)')
    pdf.bullet('Overnight retrace: morning only (9:30-12:00), requires ADX >= 22')

    # ==================== Position Sizing + Exits ====================
    pdf.section_title('Position Sizing')
    pdf.code_block(
        '1st trade of direction:  3 contracts (1 T1 + 1 T2 + 1 Runner)\n'
        '2nd/3rd trade:           2 contracts (1 T1 + 1 T2, no runner)\n'
        'Max exposure:            6 contracts total'
    )

    pdf.section_title('Exit Structure')
    pdf.body_text(
        'The hybrid exit system combines fixed profit-taking with structure-based trailing:'
    )
    pdf.code_block(
        'Entry at FVG midpoint\n'
        'Stop at FVG boundary + 2 tick buffer\n'
        '  |\n'
        '  +-- Price hits 3R -> T1 exits (1 ct) = guaranteed locked profit\n'
        '  |\n'
        '  +-- Price hits 6R -> Trail activates for T2 and Runner\n'
        '  |     T2: structure trail, 4-tick buffer, floor at 3R\n'
        '  |     Runner: structure trail, 6-tick buffer, floor at 3R\n'
        '  |\n'
        '  +-- Swing pullback or EOD -> T2/Runner exit on trail stop'
    )

    pdf.body_text(
        'Key insight: The 3R T1 locks profit before most pullbacks. The narrow gap between '
        'T1 (3R) and trail activation (6R) prevents trades from giving back gains in the '
        '"dead zone" where they used to reverse.'
    )

    # ==================== Per-Symbol Rules ====================
    pdf.section_title('Per-Symbol Configuration')

    pdf.add_table(
        ['Symbol', 'Type', 'Tick Value', 'BOS', 'PM Cutoff', 'Circuit Breaker'],
        [
            ['ES', 'E-mini S&P', '$12.50', 'OFF', 'No', '3/dir/day'],
            ['NQ', 'E-mini Nasdaq', '$5.00', 'ON (1 loss)', 'After 14:00', '3/dir/day'],
            ['MES', 'Micro S&P', '$1.25', 'OFF', 'No', '3/dir/day'],
            ['MNQ', 'Micro Nasdaq', '$0.50', 'ON (1 loss)', 'After 14:00', '3/dir/day'],
            ['SPY', 'S&P 500 ETF', 'per share', 'OFF', 'No', '3/dir/day'],
            ['QQQ', 'Nasdaq ETF', 'per share', 'ON (1 loss)', 'After 14:00', '3/dir/day'],
        ],
        col_widths=[20, 35, 25, 30, 35, 30],
    )

    # ==================== Filter Summary Table ====================
    pdf.section_title('Complete Filter Reference')

    pdf.add_table(
        ['Filter', 'Value', 'Purpose'],
        [
            ['Min FVG', '5 ticks', 'Filter tiny gaps'],
            ['Min Risk', 'ES:1.5, NQ:6.0 pts', 'Skip tight FVGs'],
            ['Max BOS Risk', 'ES:8, NQ:20 pts', 'Cap oversized BOS entries'],
            ['Displacement', '>= 1.0x avg body', 'Confirm momentum'],
            ['3x Displacement', '>= 3.0x avg body', 'Skip ADX for strong moves'],
            ['ADX', '>= 11', 'Trend strength'],
            ['B1 ADX', '>= 22', 'Strong trend for overnight'],
            ['DI Direction', '+DI/-DI', 'Trade with momentum'],
            ['EMA Trend', 'EMA 20/50', 'Higher TF alignment'],
            ['Rejection Wick', '>= 0.85x body', 'Confirm bounce (retrace)'],
            ['FVG Age (B2)', '2+ bars', 'Quick intraday retrace'],
            ['Midday Cutoff', '12:00-14:00', 'Avoid lunch lull'],
            ['PM Cutoff', 'NQ/MNQ/QQQ', 'No entries after 14:00'],
            ['Max Losses', '3/direction/day', 'Direction-aware breaker'],
            ['Max Open', '3 per direction', 'Position limit'],
            ['Sizing', 'Dynamic 3->2 cts', '1st trade: 3, 2nd+: 2'],
        ],
        col_widths=[40, 45, 105],
    )

    # ==================== Performance + Insights ====================
    pdf.section_title('12-Day Backtest Results (Feb 2-17, 2026)')

    pdf.add_table(
        ['Symbol', 'Trades', 'Wins', 'Losses', 'Win Rate', 'Total P/L', 'Avg Daily', 'Day WR'],
        [
            ['ES', '126', '113', '13', '89.7%', '+$124,881', '+$10,407', '100%'],
            ['NQ', '102', '82', '20', '80.4%', '+$225,295', '+$18,775', '91.7%'],
            ['Combined', '228', '195', '33', '85.5%', '+$350,176', '+$29,181', '-'],
        ],
        col_widths=[25, 20, 18, 20, 22, 28, 28, 22],
        highlight_rows=[2],
    )

    pdf.sub_title('ES Daily Breakdown')
    pdf.add_table(
        ['Date', 'Trades', 'Wins', 'Losses', 'Win%', 'P/L', 'Cumulative'],
        [
            ['Feb 02', '9', '8', '1', '88.9%', '+$11,888', '+$11,888'],
            ['Feb 03', '5', '5', '0', '100%', '+$17,919', '+$29,806'],
            ['Feb 04', '12', '11', '1', '91.7%', '+$6,712', '+$36,519'],
            ['Feb 05', '18', '18', '0', '100%', '+$26,725', '+$63,244'],
            ['Feb 06', '15', '12', '3', '80.0%', '+$11,419', '+$74,662'],
            ['Feb 09', '11', '10', '1', '90.9%', '+$7,694', '+$82,356'],
            ['Feb 10', '6', '5', '1', '83.3%', '+$3,481', '+$85,838'],
            ['Feb 11', '10', '8', '2', '80.0%', '+$5,394', '+$91,231'],
            ['Feb 12', '9', '9', '0', '100%', '+$17,806', '+$109,038'],
            ['Feb 13', '11', '9', '2', '81.8%', '+$4,931', '+$113,969'],
            ['Feb 16', '7', '6', '1', '85.7%', '+$1,800', '+$115,769'],
            ['Feb 17', '13', '12', '1', '92.3%', '+$9,112', '+$124,881'],
        ],
        col_widths=[22, 20, 18, 20, 20, 30, 30],
    )

    # ==================== BOS Validation ====================
    pdf.section_title('BOS A/B Validation (ES, 12 Days)')

    pdf.add_table(
        ['Config', 'Trades', 'Wins', 'Losses', 'Win Rate', 'Total P/L'],
        [
            ['BOS OFF', '126', '113', '13', '89.7%', '+$124,881'],
            ['BOS ON', '135', '111', '24', '82.2%', '+$118,406'],
        ],
        col_widths=[30, 25, 25, 25, 25, 35],
        highlight_rows=[0],
    )

    pdf.body_text(
        'BOS ON added 15 BOS trades over 12 days. Those trades were net -$6,475 and '
        'dragged win rate down 7.5%. BOS OFF confirmed superior for ES.'
    )

    # ==================== Key Insights ====================
    pdf.section_title('Key Insights')

    pdf.bullet('Direction-aware circuit breaker prevents short losses from blocking long entries')
    pdf.bullet('Removing entries_taken lifetime cap allows more trades after early positions close')
    pdf.bullet('ES BOS OFF validated: 15 BOS trades over 12 days were net -$6,475 drag')
    pdf.bullet('ES: 100% winning days (12/12), zero drawdown, $10.4k avg daily')
    pdf.bullet('NQ: 91.7% winning days (11/12), $778 max drawdown, $18.8k avg daily')
    pdf.bullet('Creation entries dominate: ES 100%, NQ 85.3%')
    pdf.bullet('3R T1 locks profit before most pullbacks - key to 85%+ win rate')
    pdf.bullet('Best hours: ES 10:00 (95.8% WR, $32.9k), NQ 9:00 (78.9% WR, $97k)')
    pdf.bullet('Afternoon chop correctly filtered by hybrid filter system')

    # ==================== Why It Works ====================
    pdf.section_title('Why It Works')

    pdf.bullet('FVGs identify institutional order flow - big players leave gaps that get revisited')
    pdf.bullet('Hybrid filters ensure you only trade in the direction of momentum')
    pdf.bullet('Quick T1 profit lock (3R) converts most trades into winners before pullbacks')
    pdf.bullet('Direction-aware circuit breaker prevents one bad direction from killing the other')
    pdf.bullet('Time filters avoid low-quality setups (lunch lull, late-day chop)')
    pdf.bullet('Dynamic sizing (3 cts first, 2 cts subsequent) maximizes early trade exposure')

    # ==================== Strategy Evolution ====================
    pdf.section_title('Strategy Evolution')

    pdf.add_table(
        ['Version', 'Key Feature'],
        [
            ['V10.10', 'Entry cap fix + direction-aware breaker + BOS parity'],
            ['V10.9', 'R-target tuning: T1=3R, Trail=6R (+31% P/L)'],
            ['V10.8', 'Hybrid filter system (2 mandatory + 2/3 optional)'],
            ['V10.7', 'Dynamic sizing (3->2 cts) + ADX>=11 + 3 trades/dir'],
            ['V10.6', 'BOS per-symbol control + 1 loss/day limit'],
            ['V10.5', 'High displacement override (3x skips ADX)'],
            ['V10.4', 'ATR buffer for equities (ATR x 0.5)'],
            ['V10.3', 'BOS risk cap (ES:8, NQ:20) + Disable SPY intraday'],
            ['V10.2', 'Midday cutoff (12-14) + NQ PM cutoff'],
            ['V10.1', 'ADX >= 22 filter for Overnight Retrace'],
            ['V10', 'Quad Entry + Hybrid Exit'],
            ['V9', 'Min Risk Filter + Opposing FVG Exit'],
            ['V8', 'Independent 2nd Entry + Position Limit'],
            ['V7', 'Profit-Protected 2nd Entry'],
            ['V6', 'Aggressive FVG Creation Entry'],
        ],
        col_widths=[25, 165],
    )

    # Save
    output = 'ICT_FVG_V10.10_Strategy_Summary.pdf'
    pdf.output(output)
    print(f'Saved: {output}')
    return output


if __name__ == '__main__':
    generate_pdf()
