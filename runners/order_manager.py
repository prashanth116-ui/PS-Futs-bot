"""
Order Manager for V10.4 Strategy

Handles trade execution, position tracking, and order management
for the V10.4 Quad Entry strategy.
"""
import sys
sys.path.insert(0, '.')

from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from enum import Enum

from runners.tradovate_client import (
    TradovateClient,
    OrderAction,
    OrderType,
    Order,
)


class TradeStatus(Enum):
    PENDING = "pending"           # Signal generated, not yet entered
    ENTRY_SENT = "entry_sent"     # Entry order placed
    ACTIVE = "active"             # Position open
    T1_HIT = "t1_hit"            # T1 target hit
    T2_HIT = "t2_hit"            # T2 target hit
    STOPPED = "stopped"           # Hit stop loss
    CLOSED = "closed"            # Fully closed


@dataclass
class ManagedTrade:
    """Represents a trade being managed by the order manager."""
    id: str                       # Unique trade ID
    symbol: str                   # ES, NQ
    direction: str                # LONG, SHORT
    entry_type: str               # CREATION, RETRACEMENT, etc.

    # Entry
    entry_price: float
    entry_time: datetime
    contracts: int = 3

    # Risk/Reward
    stop_price: float = 0.0
    target_4r: float = 0.0
    target_8r: float = 0.0
    risk_pts: float = 0.0

    # Position tracking
    contracts_remaining: int = 0
    t1_contracts: int = 1
    t2_contracts: int = 1
    runner_contracts: int = 1

    # Order IDs
    entry_order_id: Optional[int] = None
    stop_order_id: Optional[int] = None
    t1_order_id: Optional[int] = None
    t2_order_id: Optional[int] = None
    runner_order_id: Optional[int] = None

    # Trail stops
    t1_trail_stop: float = 0.0
    t2_trail_stop: float = 0.0
    runner_trail_stop: float = 0.0

    # Status
    status: TradeStatus = TradeStatus.PENDING
    touched_4r: bool = False
    touched_8r: bool = False
    t1_exited: bool = False
    t2_exited: bool = False

    # P/L tracking
    realized_pnl: float = 0.0
    exits: List[Dict] = field(default_factory=list)

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


class OrderManager:
    """
    Manages order execution for V10.4 strategy.

    Handles:
    - Entry order placement with bracket orders
    - T1 fixed profit at 4R (hybrid exit)
    - T2/Runner structure trailing stops
    - Position tracking and P/L calculation
    """

    # Tick values for P/L calculation
    TICK_VALUES = {
        'ES': 12.50,
        'NQ': 5.00,
        'MES': 1.25,
        'MNQ': 0.50,
    }

    TICK_SIZES = {
        'ES': 0.25,
        'NQ': 0.25,
        'MES': 0.25,
        'MNQ': 0.25,
    }

    def __init__(self, client: TradovateClient):
        """Initialize order manager with Tradovate client."""
        self.client = client
        self.trades: Dict[str, ManagedTrade] = {}
        self.trade_counter = 0

    def _generate_trade_id(self) -> str:
        """Generate unique trade ID."""
        self.trade_counter += 1
        return f"T{datetime.now().strftime('%Y%m%d%H%M%S')}_{self.trade_counter}"

    def _get_tick_value(self, symbol: str) -> float:
        """Get tick value for symbol."""
        base_symbol = symbol[:2] if len(symbol) > 2 else symbol
        return self.TICK_VALUES.get(base_symbol, 12.50)

    def _get_tick_size(self, symbol: str) -> float:
        """Get tick size for symbol."""
        base_symbol = symbol[:2] if len(symbol) > 2 else symbol
        return self.TICK_SIZES.get(base_symbol, 0.25)

    def create_trade_from_signal(
        self,
        symbol: str,
        direction: str,
        entry_type: str,
        entry_price: float,
        stop_price: float,
        contracts: int = 3,
        target_4r: float = None,
        target_8r: float = None,
    ) -> ManagedTrade:
        """
        Create a managed trade from a strategy signal.

        Args:
            symbol: Contract symbol (ES, NQ)
            direction: LONG or SHORT
            entry_type: CREATION, RETRACEMENT, BOS_RETRACE, INTRADAY_RETRACE
            entry_price: Entry price (FVG midpoint)
            stop_price: Stop loss price
            contracts: Number of contracts (default 3)
            target_4r: Pre-calculated T1 target (V10.9: 3R). If None, calculates at 3R.
            target_8r: Pre-calculated trail trigger (V10.9: 6R). If None, calculates at 6R.

        Returns:
            ManagedTrade object ready for execution.
        """
        is_long = direction == 'LONG'
        risk = abs(entry_price - stop_price)

        # V10.9: Use pre-calculated targets or default to 3R/6R
        if target_4r is None:
            target_4r = entry_price + (3 * risk) if is_long else entry_price - (3 * risk)
        if target_8r is None:
            target_8r = entry_price + (6 * risk) if is_long else entry_price - (6 * risk)

        # Split contracts: T1, T2, Runner
        t1_contracts = 1
        t2_contracts = 1
        runner_contracts = contracts - t1_contracts - t2_contracts

        trade = ManagedTrade(
            id=self._generate_trade_id(),
            symbol=symbol,
            direction=direction,
            entry_type=entry_type,
            entry_price=entry_price,
            entry_time=datetime.now(),
            contracts=contracts,
            stop_price=stop_price,
            target_4r=target_4r,
            target_8r=target_8r,
            risk_pts=risk,
            contracts_remaining=contracts,
            t1_contracts=t1_contracts,
            t2_contracts=t2_contracts,
            runner_contracts=runner_contracts,
            t1_trail_stop=stop_price,
            t2_trail_stop=target_4r,  # Starts at 4R after 8R hit
            runner_trail_stop=target_4r,
            status=TradeStatus.PENDING,
        )

        self.trades[trade.id] = trade
        return trade

    def execute_entry(self, trade: ManagedTrade) -> bool:
        """
        Execute entry order for a trade.

        Places a limit order at entry price with bracket stop.
        T1 target is handled separately (hybrid exit).

        Args:
            trade: ManagedTrade to execute

        Returns:
            True if order placed successfully.
        """
        if trade.status != TradeStatus.PENDING:
            print(f"Trade {trade.id} not in PENDING status")
            return False

        action = OrderAction.BUY if trade.direction == 'LONG' else OrderAction.SELL

        # Place entry order with stop loss bracket
        order = self.client.place_bracket_order(
            symbol=trade.symbol,
            action=action,
            quantity=trade.contracts,
            entry_price=trade.entry_price,
            stop_loss=trade.stop_price,
            take_profit=None,  # T1 handled separately for hybrid exit
            order_type=OrderType.LIMIT,
        )

        if order:
            trade.entry_order_id = order.id
            trade.status = TradeStatus.ENTRY_SENT
            trade.updated_at = datetime.now()
            print(f"Entry order placed: {trade.id} - {trade.direction} {trade.contracts} {trade.symbol} @ {trade.entry_price}")
            return True

        return False

    def execute_market_entry(self, trade: ManagedTrade) -> bool:
        """
        Execute market entry order for a trade.

        Use when price has already reached entry level.
        """
        if trade.status != TradeStatus.PENDING:
            return False

        action = OrderAction.BUY if trade.direction == 'LONG' else OrderAction.SELL

        # Place market order
        order = self.client.place_order(
            symbol=trade.symbol,
            action=action,
            quantity=trade.contracts,
            order_type=OrderType.MARKET,
        )

        if order:
            trade.entry_order_id = order.id
            trade.status = TradeStatus.ACTIVE
            trade.contracts_remaining = trade.contracts
            trade.updated_at = datetime.now()

            # Place stop loss order
            stop_action = OrderAction.SELL if trade.direction == 'LONG' else OrderAction.BUY
            stop_order = self.client.place_order(
                symbol=trade.symbol,
                action=stop_action,
                quantity=trade.contracts,
                order_type=OrderType.STOP,
                stop_price=trade.stop_price,
            )
            if stop_order:
                trade.stop_order_id = stop_order.id

            print(f"Market entry: {trade.id} - {trade.direction} {trade.contracts} {trade.symbol}")
            return True

        return False

    def check_and_execute_t1(self, trade: ManagedTrade, current_price: float) -> bool:
        """
        Check if T1 target hit and execute fixed 4R profit.

        This is the HYBRID exit - T1 takes profit at exactly 4R.

        Args:
            trade: Active trade
            current_price: Current market price

        Returns:
            True if T1 was executed.
        """
        if trade.status != TradeStatus.ACTIVE:
            return False

        if trade.t1_exited:
            return False

        is_long = trade.direction == 'LONG'
        t1_hit = current_price >= trade.target_4r if is_long else current_price <= trade.target_4r

        if t1_hit and not trade.touched_4r:
            trade.touched_4r = True
            trade.t1_trail_stop = trade.entry_price  # Move to breakeven

            # Execute T1 exit at 4R
            exit_action = OrderAction.SELL if is_long else OrderAction.BUY

            order = self.client.place_order(
                symbol=trade.symbol,
                action=exit_action,
                quantity=trade.t1_contracts,
                order_type=OrderType.LIMIT,
                price=trade.target_4r,
            )

            if order:
                trade.t1_order_id = order.id
                trade.t1_exited = True
                trade.contracts_remaining -= trade.t1_contracts
                trade.status = TradeStatus.T1_HIT

                # Calculate P/L (use actual target distance, not hardcoded 4R)
                pnl_pts = abs(trade.target_4r - trade.entry_price)
                pnl_dollars = (pnl_pts / self._get_tick_size(trade.symbol)) * self._get_tick_value(trade.symbol) * trade.t1_contracts
                trade.realized_pnl += pnl_dollars
                trade.exits.append({
                    'type': 'T1_4R',
                    'contracts': trade.t1_contracts,
                    'price': trade.target_4r,
                    'pnl_dollars': pnl_dollars,
                    'time': datetime.now(),
                })

                print(f"T1 hit: {trade.id} - +${pnl_dollars:,.2f}")

                # Update stop for remaining contracts
                self._update_stop_order(trade, trade.entry_price)

                return True

        return False

    def check_and_execute_t2(self, trade: ManagedTrade, current_price: float) -> bool:
        """
        Check if T2 trail stop hit and execute.

        T2 uses structure trailing after 8R hit.
        """
        if not trade.t1_exited or trade.t2_exited:
            return False

        is_long = trade.direction == 'LONG'

        # Check for 8R touch to start T2 trail
        t8r_hit = current_price >= trade.target_8r if is_long else current_price <= trade.target_8r
        if t8r_hit and not trade.touched_8r:
            trade.touched_8r = True
            trade.t2_trail_stop = trade.target_4r  # Trail starts at +4R
            trade.runner_trail_stop = trade.target_4r
            trade.status = TradeStatus.T2_HIT
            print(f"8R touched: {trade.id} - trailing active")

        # Check T2 trail stop
        if trade.touched_8r:
            t2_stopped = current_price <= trade.t2_trail_stop if is_long else current_price >= trade.t2_trail_stop

            if t2_stopped:
                exit_action = OrderAction.SELL if is_long else OrderAction.BUY

                order = self.client.place_order(
                    symbol=trade.symbol,
                    action=exit_action,
                    quantity=trade.t2_contracts,
                    order_type=OrderType.MARKET,
                )

                if order:
                    trade.t2_exited = True
                    trade.contracts_remaining -= trade.t2_contracts

                    # Calculate P/L
                    pnl_pts = abs(trade.t2_trail_stop - trade.entry_price)
                    if not is_long:
                        pnl_pts = -pnl_pts if trade.t2_trail_stop > trade.entry_price else pnl_pts
                    pnl_dollars = (pnl_pts / self._get_tick_size(trade.symbol)) * self._get_tick_value(trade.symbol) * trade.t2_contracts
                    trade.realized_pnl += pnl_dollars
                    trade.exits.append({
                        'type': 'T2_TRAIL',
                        'contracts': trade.t2_contracts,
                        'price': trade.t2_trail_stop,
                        'pnl_dollars': pnl_dollars,
                        'time': datetime.now(),
                    })

                    print(f"T2 trail exit: {trade.id} - ${pnl_dollars:+,.2f}")
                    return True

        return False

    def check_and_execute_runner(self, trade: ManagedTrade, current_price: float) -> bool:
        """Check if runner trail stop hit and execute."""
        if not trade.t1_exited or not trade.t2_exited:
            return False

        if trade.contracts_remaining <= 0:
            return False

        is_long = trade.direction == 'LONG'
        runner_stopped = current_price <= trade.runner_trail_stop if is_long else current_price >= trade.runner_trail_stop

        if runner_stopped:
            exit_action = OrderAction.SELL if is_long else OrderAction.BUY

            order = self.client.place_order(
                symbol=trade.symbol,
                action=exit_action,
                quantity=trade.contracts_remaining,
                order_type=OrderType.MARKET,
            )

            if order:
                # Calculate P/L
                pnl_pts = abs(trade.runner_trail_stop - trade.entry_price)
                if not is_long:
                    pnl_pts = -pnl_pts if trade.runner_trail_stop > trade.entry_price else pnl_pts
                pnl_dollars = (pnl_pts / self._get_tick_size(trade.symbol)) * self._get_tick_value(trade.symbol) * trade.contracts_remaining
                trade.realized_pnl += pnl_dollars
                trade.exits.append({
                    'type': 'RUNNER_TRAIL',
                    'contracts': trade.contracts_remaining,
                    'price': trade.runner_trail_stop,
                    'pnl_dollars': pnl_dollars,
                    'time': datetime.now(),
                })

                trade.contracts_remaining = 0
                trade.status = TradeStatus.CLOSED

                print(f"Runner exit: {trade.id} - ${pnl_dollars:+,.2f}")
                print(f"Trade closed: {trade.id} - Total P/L: ${trade.realized_pnl:+,.2f}")
                return True

        return False

    def update_trail_stops(
        self,
        trade: ManagedTrade,
        swing_high: Optional[float] = None,
        swing_low: Optional[float] = None,
    ):
        """
        Update trail stops based on structure (swing highs/lows).

        Args:
            trade: Active trade
            swing_high: New confirmed swing high
            swing_low: New confirmed swing low
        """
        is_long = trade.direction == 'LONG'
        tick_size = self._get_tick_size(trade.symbol)

        if trade.touched_4r and not trade.t1_exited:
            # T1 trail (2 tick buffer)
            if is_long and swing_low and swing_low > trade.t1_trail_stop:
                new_trail = swing_low - (2 * tick_size)
                if new_trail > trade.t1_trail_stop:
                    trade.t1_trail_stop = new_trail
            elif not is_long and swing_high and swing_high < trade.t1_trail_stop:
                new_trail = swing_high + (2 * tick_size)
                if new_trail < trade.t1_trail_stop:
                    trade.t1_trail_stop = new_trail

        if trade.touched_8r:
            # T2 trail (4 tick buffer)
            if is_long and swing_low and swing_low > trade.t2_trail_stop:
                new_trail = swing_low - (4 * tick_size)
                if new_trail > trade.t2_trail_stop:
                    trade.t2_trail_stop = new_trail
                    self._update_stop_order(trade, new_trail)
            elif not is_long and swing_high and swing_high < trade.t2_trail_stop:
                new_trail = swing_high + (4 * tick_size)
                if new_trail < trade.t2_trail_stop:
                    trade.t2_trail_stop = new_trail
                    self._update_stop_order(trade, new_trail)

            # Runner trail (6 tick buffer)
            if is_long and swing_low and swing_low > trade.runner_trail_stop:
                new_trail = swing_low - (6 * tick_size)
                if new_trail > trade.runner_trail_stop:
                    trade.runner_trail_stop = new_trail
            elif not is_long and swing_high and swing_high < trade.runner_trail_stop:
                new_trail = swing_high + (6 * tick_size)
                if new_trail < trade.runner_trail_stop:
                    trade.runner_trail_stop = new_trail

        trade.updated_at = datetime.now()

    def _update_stop_order(self, trade: ManagedTrade, new_stop: float):
        """Update stop order price."""
        if trade.stop_order_id:
            self.client.modify_order(trade.stop_order_id, stop_price=new_stop)

    def check_stop_hit(self, trade: ManagedTrade, current_price: float) -> bool:
        """Check if initial stop was hit (before 4R)."""
        if trade.touched_4r:
            return False  # After 4R, use trail stops

        is_long = trade.direction == 'LONG'
        stopped = current_price <= trade.stop_price if is_long else current_price >= trade.stop_price

        if stopped:
            # Full stop loss
            pnl_pts = trade.risk_pts * (-1)
            pnl_dollars = (abs(pnl_pts) / self._get_tick_size(trade.symbol)) * self._get_tick_value(trade.symbol) * trade.contracts_remaining * (-1)
            trade.realized_pnl = pnl_dollars
            trade.exits.append({
                'type': 'STOP',
                'contracts': trade.contracts_remaining,
                'price': trade.stop_price,
                'pnl_dollars': pnl_dollars,
                'time': datetime.now(),
            })
            trade.contracts_remaining = 0
            trade.status = TradeStatus.STOPPED

            print(f"STOPPED: {trade.id} - ${pnl_dollars:,.2f}")
            return True

        return False

    def close_trade_eod(self, trade: ManagedTrade, current_price: float):
        """Close remaining position at end of day."""
        if trade.contracts_remaining <= 0:
            return

        exit_action = OrderAction.SELL if trade.direction == 'LONG' else OrderAction.BUY

        order = self.client.place_order(
            symbol=trade.symbol,
            action=exit_action,
            quantity=trade.contracts_remaining,
            order_type=OrderType.MARKET,
        )

        if order:
            is_long = trade.direction == 'LONG'
            pnl_pts = current_price - trade.entry_price if is_long else trade.entry_price - current_price
            pnl_dollars = (pnl_pts / self._get_tick_size(trade.symbol)) * self._get_tick_value(trade.symbol) * trade.contracts_remaining
            trade.realized_pnl += pnl_dollars
            trade.exits.append({
                'type': 'EOD',
                'contracts': trade.contracts_remaining,
                'price': current_price,
                'pnl_dollars': pnl_dollars,
                'time': datetime.now(),
            })
            trade.contracts_remaining = 0
            trade.status = TradeStatus.CLOSED

            print(f"EOD close: {trade.id} - ${pnl_dollars:+,.2f}")

    def get_active_trades(self) -> List[ManagedTrade]:
        """Get all active trades."""
        return [t for t in self.trades.values()
                if t.status in [TradeStatus.ACTIVE, TradeStatus.ENTRY_SENT, TradeStatus.T1_HIT, TradeStatus.T2_HIT]]

    def get_open_position_count(self) -> int:
        """Get count of open positions."""
        return len(self.get_active_trades())

    def get_daily_pnl(self) -> float:
        """Get total P/L for today's trades."""
        today = datetime.now().date()
        return sum(
            t.realized_pnl for t in self.trades.values()
            if t.created_at.date() == today
        )

    def get_trade_summary(self) -> Dict:
        """Get summary of all trades."""
        today = datetime.now().date()
        today_trades = [t for t in self.trades.values() if t.created_at.date() == today]

        return {
            'total_trades': len(today_trades),
            'active': len([t for t in today_trades if t.status in [TradeStatus.ACTIVE, TradeStatus.T1_HIT, TradeStatus.T2_HIT]]),
            'closed': len([t for t in today_trades if t.status == TradeStatus.CLOSED]),
            'stopped': len([t for t in today_trades if t.status == TradeStatus.STOPPED]),
            'daily_pnl': self.get_daily_pnl(),
        }


if __name__ == '__main__':
    print("Order Manager Test")
    print("=" * 50)

    # Create mock client for testing
    class MockClient:
        def place_order(self, **kwargs):
            print(f"  Mock order: {kwargs}")
            return Order(id=1)

        def place_bracket_order(self, **kwargs):
            print(f"  Mock bracket order: {kwargs}")
            return Order(id=1)

        def modify_order(self, order_id, **kwargs):
            print(f"  Mock modify order {order_id}: {kwargs}")
            return True

    client = MockClient()
    manager = OrderManager(client)

    # Create test trade
    trade = manager.create_trade_from_signal(
        symbol='ES',
        direction='LONG',
        entry_type='CREATION',
        entry_price=6000.00,
        stop_price=5998.00,  # 2 pt risk
        contracts=3,
    )

    print(f"\nTrade created: {trade.id}")
    print(f"  Entry: {trade.entry_price}")
    print(f"  Stop: {trade.stop_price}")
    print(f"  Risk: {trade.risk_pts} pts")
    print(f"  4R Target: {trade.target_4r}")
    print(f"  8R Target: {trade.target_8r}")

    # Simulate entry
    print("\nExecuting entry...")
    manager.execute_entry(trade)

    # Simulate T1 hit
    trade.status = TradeStatus.ACTIVE
    print("\nSimulating T1 hit at 4R...")
    manager.check_and_execute_t1(trade, trade.target_4r)

    print(f"\nTrade summary: {manager.get_trade_summary()}")
