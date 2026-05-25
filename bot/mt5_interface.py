import sys
import os
import random
import time
import logging
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MT5Interface")

# Try importing MT5, fallback to Mock on non-Windows/no-install
MT5_AVAILABLE = False
if sys.platform == "win32":
    try:
        import MetaTrader5 as mt5
        MT5_AVAILABLE = True
    except ImportError:
        logger.warning("MetaTrader5 python package not installed. Falling back to Mock Mode.")
else:
    logger.warning("Not running on Windows. Falling back to Mock Mode.")


def get_env_var(name: str, default: Optional[str] = None) -> Optional[str]:
    # 1. Read from OS Environment variable (highest priority)
    env_val = os.environ.get(name)
    if env_val is not None:
        return env_val
        
    # 2. Check for .env file
    if os.path.exists(".env"):
        try:
            with open(".env", "r") as f:
                for line in f:
                    if line.strip().startswith(f"{name}="):
                        return line.strip().split("=", 1)[1].strip()
        except Exception:
            pass
    return default


def check_dry_run_env() -> bool:
    val = get_env_var("DRY_RUN", "True")
    return val.lower() in ("true", "1")


class MT5Interface:
    def __init__(self, dry_run: Optional[bool] = None):
        if dry_run is None:
            dry_run = check_dry_run_env()
        self.dry_run = dry_run or not MT5_AVAILABLE
        self.mock_balance = 10000.0
        self.mock_equity = 10000.0
        self.mock_positions = []
        self.mock_ticket_counter = 100000
        
        # Simulated live prices for mock mode
        self.mock_prices = {
            "XAUUSD": 2350.00,
            "XAGUSD": 30.50
        }

    def initialize(self) -> bool:
        if self.dry_run:
            logger.info("Initializing MT5 Interface in MOCK/DRY-RUN Mode.")
            return True
        
        # Real MT5 Initialization with custom path and credentials support
        mt5_path = get_env_var("MT5_PATH")
        mt5_login_str = get_env_var("MT5_LOGIN")
        mt5_password = get_env_var("MT5_PASSWORD")
        mt5_server = get_env_var("MT5_SERVER")
        
        init_kwargs = {}
        if mt5_path:
            init_kwargs["path"] = mt5_path
            
        if mt5_login_str:
            try:
                init_kwargs["login"] = int(mt5_login_str)
            except ValueError:
                logger.error(f"Invalid MT5_LOGIN value in environment: {mt5_login_str}. Must be an integer.")
                
        if mt5_password:
            init_kwargs["password"] = mt5_password
            
        if mt5_server:
            init_kwargs["server"] = mt5_server
            
        logger.info(f"Initializing MT5 terminal (Real Mode) with args: { {k: (v if k != 'password' else '***') for k, v in init_kwargs.items()} }")
        
        init_success = mt5.initialize(**init_kwargs)
            
        if not init_success:
            logger.error(f"MT5 Initialization failed. Error code: {mt5.last_error()}")
            logger.info("Falling back to Mock/Dry-Run Mode due to connection failure.")
            self.dry_run = True
            return True
        
        logger.info("Successfully connected to real MetaTrader 5 Terminal.")
        return True

    def shutdown(self):
        if not self.dry_run and MT5_AVAILABLE:
            mt5.shutdown()
            logger.info("MT5 connection closed.")

    def get_account_info(self) -> Dict:
        if self.dry_run:
            # Update equity based on open positions
            floating_pnl = sum(p["profit"] for p in self.mock_positions)
            self.mock_equity = self.mock_balance + floating_pnl
            return {
                "balance": self.mock_balance,
                "equity": self.mock_equity,
                "margin": 0.0,
                "margin_free": self.mock_equity,
                "margin_level": 100.0,
                "profit": floating_pnl,
                "currency": "USD",
                "server": "Exness-MockServer",
                "login": 12345678,
                "mock": True
            }
        
        # Real MT5 Account Info
        info = mt5.account_info()
        if info is None:
            return {}
        return {
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "margin_free": info.margin_free,
            "margin_level": info.margin_level if info.margin > 0 else 100.0,
            "profit": info.profit,
            "currency": info.currency,
            "server": info.server,
            "login": info.login,
            "mock": False
        }

    def get_rates(self, symbol: str, timeframe: int, count: int) -> Optional[List[Dict]]:
        """
        Fetches historical bars. 
        timeframe: mt5.TIMEFRAME_M5, mt5.TIMEFRAME_M15, etc.
        """
        # Mapping timeframe int to name for mock logs
        tf_name = "M5" if timeframe == 5 else "M15"
        
        if self.dry_run:
            # Generate mock rates
            now = time.time()
            base_price = self.mock_prices.get(symbol, 2300.0)
            rates = []
            
            # Walk backwards to generate bars
            for i in range(count):
                bar_time = now - (count - i) * (timeframe * 60)
                # Add some random walk
                change = random.uniform(-2.0, 2.0) if symbol == "XAUUSD" else random.uniform(-0.1, 0.1)
                close_p = base_price + change
                open_p = base_price
                high_p = max(open_p, close_p) + (random.uniform(0, 1.0) if symbol == "XAUUSD" else random.uniform(0, 0.05))
                low_p = min(open_p, close_p) - (random.uniform(0, 1.0) if symbol == "XAUUSD" else random.uniform(0, 0.05))
                
                rates.append({
                    "time": int(bar_time),
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "close": close_p,
                    "tick_volume": random.randint(100, 1000)
                })
                base_price = close_p
            
            # Update simulated live price to the latest close
            self.mock_prices[symbol] = base_price
            return rates

        # Real MT5 Rates
        # Translate simple timeframe (5, 15) to MT5 constants
        mt5_tf = mt5.TIMEFRAME_M5 if timeframe == 5 else mt5.TIMEFRAME_M15
        
        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, count)
        if rates is None or len(rates) == 0:
            logger.error(f"Failed to fetch rates for {symbol}. Error: {mt5.last_error()}")
            return None
        
        # Convert structured numpy array to list of dicts
        return [
            {
                "time": int(rate[0]),
                "open": float(rate[1]),
                "high": float(rate[2]),
                "low": float(rate[3]),
                "close": float(rate[4]),
                "tick_volume": int(rate[5])
            }
            for rate in rates
        ]

    def get_symbol_info(self, symbol: str) -> Dict:
        if self.dry_run:
            return {
                "symbol": symbol,
                "ask": self.mock_prices.get(symbol, 2350.0) + 0.20,
                "bid": self.mock_prices.get(symbol, 2350.0),
                "point": 0.01 if symbol == "XAUUSD" else 0.001,
                "trade_contract_size": 100 if symbol == "XAUUSD" else 5000
            }
            
        info = mt5.symbol_info(symbol)
        if info is None:
            return {}
        return {
            "symbol": info.name,
            "ask": info.ask,
            "bid": info.bid,
            "point": info.point,
            "trade_contract_size": info.trade_contract_size
        }

    def place_market_order(self, symbol: str, order_type: str, volume: float, stop_loss: float = 0.0, take_profit: float = 0.0) -> Dict:
        """
        order_type: 'BUY' or 'SELL'
        """
        symbol_info = self.get_symbol_info(symbol)
        if not symbol_info:
            return {"status": "FAILED", "error": f"Symbol {symbol} not found"}

        price = symbol_info["ask"] if order_type == "BUY" else symbol_info["bid"]

        if self.dry_run:
            self.mock_ticket_counter += 1
            new_pos = {
                "ticket": self.mock_ticket_counter,
                "symbol": symbol,
                "type": order_type,
                "volume": volume,
                "price_open": price,
                "sl": stop_loss,
                "tp": take_profit,
                "price_current": price,
                "profit": 0.0,
                "time": int(time.time())
            }
            self.mock_positions.append(new_pos)
            logger.info(f"[MOCK ORDER] Placed {order_type} on {symbol} - Vol: {volume}, Price: {price}, SL: {stop_loss}, TP: {take_profit}")
            return {"status": "SUCCESS", "ticket": new_pos["ticket"], "price": price}

        # Real MT5 Order
        mt5_order_type = mt5.ORDER_TYPE_BUY if order_type == "BUY" else mt5.ORDER_TYPE_SELL
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": mt5_order_type,
            "price": float(price),
            "sl": float(stop_loss) if stop_loss else 0.0,
            "tp": float(take_profit) if take_profit else 0.0,
            "deviation": 20,
            "magic": 20260525,
            "comment": "Volatility adaptive bot",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }

        result = mt5.order_send(request)
        if result is None:
            return {"status": "FAILED", "error": "Order send failed with None result"}
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Order failed. Retcode: {result.retcode}. Error: {result.comment}")
            return {"status": "FAILED", "error": result.comment, "retcode": result.retcode}

        logger.info(f"[REAL ORDER] Executed {order_type} on {symbol} - Ticket: {result.order}")
        return {"status": "SUCCESS", "ticket": result.order, "price": result.price}

    def close_position(self, ticket: int) -> bool:
        if self.dry_run:
            for i, p in enumerate(self.mock_positions):
                if p["ticket"] == ticket:
                    # Apply profit/loss to mock balance
                    self.mock_balance += p["profit"]
                    self.mock_positions.pop(i)
                    logger.info(f"[MOCK CLOSE] Closed ticket {ticket}. Realized Profit: {p['profit']:.2f}")
                    return True
            return False

        # Real MT5 Close
        positions = mt5.positions_get(ticket=ticket)
        if positions is None or len(positions) == 0:
            return False
        
        pos = positions[0]
        symbol = pos.symbol
        volume = pos.volume
        pos_type = pos.type
        
        symbol_info = self.get_symbol_info(symbol)
        close_price = symbol_info["bid"] if pos_type == mt5.POSITION_TYPE_BUY else symbol_info["ask"]
        close_type = mt5.ORDER_TYPE_SELL if pos_type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": close_type,
            "position": ticket,
            "price": float(close_price),
            "deviation": 20,
            "magic": 20260525,
            "comment": "Close position",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Failed to close position {ticket}. Result: {result}")
            return False
            
        logger.info(f"[REAL CLOSE] Closed position {ticket}")
        return True

    def get_open_positions(self) -> List[Dict]:
        if self.dry_run:
            # Simulate real-time price changes for mock open positions to show dynamic P&L
            for p in self.mock_positions:
                symbol = p["symbol"]
                live_price = self.mock_prices[symbol]
                # Random tick variance
                change = random.uniform(-0.5, 0.5) if symbol == "XAUUSD" else random.uniform(-0.02, 0.02)
                self.mock_prices[symbol] = live_price + change
                
                # Recalculate P&L
                current_price = self.mock_prices[symbol]
                p["price_current"] = current_price
                contract_size = 100 if symbol == "XAUUSD" else 5000
                
                if p["type"] == "BUY":
                    p["profit"] = (current_price - p["price_open"]) * p["volume"] * contract_size
                else:
                    p["profit"] = (p["price_open"] - current_price) * p["volume"] * contract_size
            
            return self.mock_positions

        # Real MT5 Positions
        positions = mt5.positions_get()
        if positions is None:
            return []
            
        output = []
        for pos in positions:
            pos_type = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
            output.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "type": pos_type,
                "volume": pos.volume,
                "price_open": pos.price_open,
                "sl": pos.sl,
                "tp": pos.tp,
                "price_current": pos.price_current,
                "profit": pos.profit,
                "time": pos.time
            })
        return output

    def close_all_positions(self) -> bool:
        if self.dry_run:
            logger.info("Closing all mock positions.")
            # Pop and realize all profits
            while self.mock_positions:
                p = self.mock_positions[0]
                self.close_position(p["ticket"])
            return True
            
        positions = self.get_open_positions()
        success = True
        for pos in positions:
            res = self.close_position(pos["ticket"])
            if not res:
                success = False
        return success
