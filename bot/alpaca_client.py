"""
Alpaca Trading Client Wrapper — Orders, positions, account.
Extended-hours support via limit orders with extended_hours=True.

NOTE: Alpaca only allows LIMIT orders during extended hours, not market orders.
      All AH buy/sell helpers use limit orders.
"""
import logging
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from bot.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_PAPER

logger = logging.getLogger("ah_bot.alpaca")


def get_trading_client():
    return TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=ALPACA_PAPER)


def get_account():
    client = get_trading_client()
    return client.get_account()


def get_equity():
    account = get_account()
    return float(account.equity)


def get_cash():
    """Get available cash WITHOUT margin. Uses non_marginable_buying_power
    so this bot never borrows, even if margin is enabled on the account
    for other strategies/bots."""
    account = get_account()
    return float(account.non_marginable_buying_power)


def get_all_positions():
    client = get_trading_client()
    return client.get_all_positions()


def get_position(symbol):
    """Get position for a symbol, returns None if no position."""
    client = get_trading_client()
    try:
        return client.get_open_position(symbol)
    except Exception:
        return None


def get_position_qty(symbol):
    """Get quantity of shares held for a symbol."""
    pos = get_position(symbol)
    if pos is None:
        return 0.0
    return float(pos.qty)


def get_position_market_value(symbol):
    """Get current market value of a position."""
    pos = get_position(symbol)
    if pos is None:
        return 0.0
    return float(pos.market_value)


# ═══════════════════════════════════════════════════
# Extended-hours order helpers (limit orders only)
# ═══════════════════════════════════════════════════

def buy_limit_extended(symbol, qty, limit_price):
    """Place a limit BUY order with extended hours enabled."""
    if qty <= 0:
        logger.warning(f"Skipping buy of {symbol}: qty={qty} <= 0")
        return None
    client = get_trading_client()
    order_data = LimitOrderRequest(
        symbol=symbol,
        qty=round(qty, 4),
        limit_price=round(limit_price, 2),
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        extended_hours=True,
    )
    order = client.submit_order(order_data=order_data)
    logger.info(f"BUY {symbol} qty={qty:.4f} limit=${limit_price:.2f} (extended) | order_id={order.id}")
    return order


def sell_limit_extended(symbol, qty, limit_price):
    """Place a limit SELL order with extended hours enabled."""
    if qty <= 0:
        logger.warning(f"Skipping sell of {symbol}: qty={qty} <= 0")
        return None
    client = get_trading_client()
    order_data = LimitOrderRequest(
        symbol=symbol,
        qty=round(qty, 4),
        limit_price=round(limit_price, 2),
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        extended_hours=True,
    )
    order = client.submit_order(order_data=order_data)
    logger.info(f"SELL {symbol} qty={qty:.4f} limit=${limit_price:.2f} (extended) | order_id={order.id}")
    return order


def sell_short_limit_extended(symbol, qty, limit_price):
    """Open a SHORT position via limit order with extended hours.
    Alpaca treats a SELL with no existing long position as a short sale."""
    if qty <= 0:
        logger.warning(f"Skipping short of {symbol}: qty={qty} <= 0")
        return None
    client = get_trading_client()
    order_data = LimitOrderRequest(
        symbol=symbol,
        qty=round(qty, 4),
        limit_price=round(limit_price, 2),
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        extended_hours=True,
    )
    order = client.submit_order(order_data=order_data)
    logger.info(f"SHORT {symbol} qty={qty:.4f} limit=${limit_price:.2f} (extended) | order_id={order.id}")
    return order


# ═══════════════════════════════════════════════════
# Regular-hours order helpers (for 9:30 AM close-out)
# ═══════════════════════════════════════════════════

def buy_notional(symbol, dollar_amount):
    """Buy a dollar amount of a symbol (fractional shares). Regular hours."""
    if dollar_amount < 1.0:
        logger.warning(f"Skipping buy of {symbol}: ${dollar_amount:.2f} < $1 minimum")
        return None
    client = get_trading_client()
    order_data = MarketOrderRequest(
        symbol=symbol,
        notional=round(dollar_amount, 2),
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(order_data=order_data)
    logger.info(f"BUY {symbol} notional=${dollar_amount:.2f} | order_id={order.id}")
    return order


def sell_all(symbol):
    """Sell entire position of a symbol. Regular hours."""
    pos = get_position(symbol)
    if pos is None or float(pos.qty) == 0:
        logger.warning(f"No position in {symbol} to sell")
        return None
    client = get_trading_client()
    qty = float(pos.qty)
    order_data = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(order_data=order_data)
    logger.info(f"SELL {symbol} qty={qty} | order_id={order.id}")
    return order


def close_position(symbol):
    """Close a position using Alpaca's close_position endpoint."""
    client = get_trading_client()
    try:
        client.close_position(symbol)
        logger.info(f"CLOSED position: {symbol}")
        return True
    except Exception as e:
        logger.warning(f"Could not close {symbol}: {e}")
        return False


def buy_to_cover(symbol, qty=None):
    """Buy to cover a short position at market. Regular hours only.
    If qty is None, covers the full short position."""
    if qty is None:
        pos = get_position(symbol)
        if pos is None:
            logger.warning(f"No position in {symbol} to cover")
            return None
        qty = abs(float(pos.qty))
    if qty <= 0:
        logger.warning(f"Skipping cover of {symbol}: qty={qty} <= 0")
        return None
    client = get_trading_client()
    order_data = MarketOrderRequest(
        symbol=symbol,
        qty=round(qty, 4),
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(order_data=order_data)
    logger.info(f"COVER {symbol} qty={qty:.4f} | order_id={order.id}")
    return order


def cancel_order(order_id):
    """Cancel a specific order by ID."""
    client = get_trading_client()
    try:
        client.cancel_order_by_id(order_id)
        logger.info(f"Cancelled order {order_id}")
        return True
    except Exception as e:
        logger.warning(f"Could not cancel order {order_id}: {e}")
        return False


def cancel_all_orders():
    """Cancel all open orders."""
    client = get_trading_client()
    try:
        client.cancel_orders()
        logger.info("Cancelled all open orders")
        return True
    except Exception as e:
        logger.warning(f"Could not cancel orders: {e}")
        return False


def get_open_orders(symbol=None):
    """Get open orders, optionally filtered by symbol."""
    client = get_trading_client()
    request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
    orders = client.get_orders(request)
    if symbol:
        orders = [o for o in orders if o.symbol == symbol]
    return orders


def is_market_open():
    """Check if the market is currently open."""
    client = get_trading_client()
    clock = client.get_clock()
    return clock.is_open


def get_clock():
    """Get the market clock."""
    client = get_trading_client()
    return client.get_clock()
