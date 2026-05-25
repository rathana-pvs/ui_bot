import asyncio
import time
import logging
import pandas as pd
from typing import Dict, List, Optional
from bot.mt5_interface import MT5Interface
from bot.strategies import check_volatility_regime, check_ranging_signals, check_trending_signals

logger = logging.getLogger("BotEngine")

class BotEngine:
    def __init__(self, mt5_interface: MT5Interface):
        self.mt5 = mt5_interface
        self.is_active = False
        self.risk_profile = "safe"  # "safe", "moderate", "risk"
        self.symbols = ["XAUUSD", "XAGUSD"]
        
        # Cooldown management (symbol -> timestamp when allowed to trade again)
        self.cooldowns = {symbol: 0 for symbol in self.symbols}
        
        # In-memory bot states to expose to the dashboard
        self.stats = {
            "is_active": False,
            "risk_profile": "safe",
            "regimes": {symbol: "UNKNOWN" for symbol in self.symbols},
            "metrics": {symbol: {} for symbol in self.symbols},
            "last_tick_time": {symbol: 0 for symbol in self.symbols},
            "logs": []
        }

    def log_message(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {msg}"
        logger.info(log_entry)
        self.stats["logs"].append(log_entry)
        # Keep last 100 log entries
        if len(self.stats["logs"]) > 100:
            self.stats["logs"].pop(0)

    def set_active(self, active: bool):
        self.is_active = active
        self.stats["is_active"] = active
        self.log_message(f"Bot execution set to {'ACTIVE' if active else 'INACTIVE'}")

    def set_risk_profile(self, profile: str):
        if profile in ["safe", "moderate", "risk"]:
            self.risk_profile = profile
            self.stats["risk_profile"] = profile
            self.log_message(f"Risk profile changed to: {profile.upper()}")

    def get_risk_percentage(self) -> float:
        if self.risk_profile == "safe":
            return 0.01  # 1%
        elif self.risk_profile == "moderate":
            return 0.025  # 2.5%
        else:
            return 0.05  # 5%

    def calculate_lot_size(self, symbol: str, balance: float, stop_loss_points: float) -> float:
        """
        Calculates lot size based on account balance, risk %, and stop loss distance.
        """
        risk_pct = self.get_risk_percentage()
        risk_amount = balance * risk_pct
        
        symbol_info = self.mt5.get_symbol_info(symbol)
        if not symbol_info:
            return 0.01
            
        point = symbol_info["point"]
        contract_size = symbol_info["trade_contract_size"]
        
        if stop_loss_points <= 0:
            return 0.01
            
        # Formula: Lot = Risk Amount / (SL_Points * Point * Contract Size)
        # e.g., Gold $5 SL is 500 points on a 0.01 point chart. 500 * 0.01 * 100 = 500.
        denominator = stop_loss_points * point * contract_size
        if denominator == 0:
            return 0.01
            
        raw_lot = risk_amount / denominator
        # Standard retail lot constraints (minimum 0.01, step 0.01)
        lot = max(0.01, round(raw_lot, 2))
        return lot

    async def start_loop(self):
        self.log_message("Starting main bot loop...")
        while True:
            try:
                if self.is_active:
                    await self.process_markets()
            except Exception as e:
                logger.exception("Error in main loop process")
                self.log_message(f"Critical error in loop: {str(e)}")
                
            await asyncio.sleep(5)  # Scan every 5 seconds

    async def process_markets(self):
        account = self.mt5.get_account_info()
        if not account:
            self.log_message("Failed to fetch account info. Skipping this cycle.")
            return

        balance = account.get("balance", 10000.0)
        open_positions = self.mt5.get_open_positions()
        
        for symbol in self.symbols:
            # 1. Fetch M15 rates (65 bars needed for ATR 50-SMA)
            rates_m15 = self.mt5.get_rates(symbol, 15, 70)
            if not rates_m15:
                continue
            df_m15 = pd.DataFrame(rates_m15)
            
            # Check Volatility Regime
            regime, atr_val, atr_sma = check_volatility_regime(df_m15)
            self.stats["regimes"][symbol] = regime
            self.stats["last_tick_time"][symbol] = int(time.time())
            
            # Fetch M5 rates for entry checks
            rates_m5 = self.mt5.get_rates(symbol, 5, 30)
            if not rates_m5:
                continue
            df_m5 = pd.DataFrame(rates_m5)
            
            # 2. Strategy evaluation
            signal = None
            metrics = {}
            
            if regime == "RANGING":
                signal, metrics = check_ranging_signals(df_m5)
                # Append regime info to metrics
                metrics["atr_m15"] = atr_val
                metrics["atr_sma_m15"] = atr_sma
                self.stats["metrics"][symbol] = metrics
            else:  # TRENDING
                signal, metrics = check_trending_signals(df_m5)
                metrics["atr_m15"] = atr_val
                metrics["atr_sma_m15"] = atr_sma
                self.stats["metrics"][symbol] = metrics
                
            # 3. Check for existing trade
            symbol_positions = [pos for pos in open_positions if pos["symbol"] == symbol]
            
            # Close Logic for Ranging (Take profit at Middle Band)
            if regime == "RANGING" and len(symbol_positions) > 0:
                for pos in symbol_positions:
                    middle_band = metrics.get("middle_band")
                    if not middle_band:
                        continue
                        
                    current_price = pos["price_current"]
                    
                    # If BUY and price goes above Middle Bollinger Band
                    if pos["type"] == "BUY" and current_price >= middle_band:
                        self.log_message(f"Ranging TP Target met for {symbol}. Closing BUY trade.")
                        self.mt5.close_position(pos["ticket"])
                        self.cooldowns[symbol] = time.time() + 15 * 60  # 15 mins cooldown (3 bars)
                        
                    # If SELL and price goes below Middle Bollinger Band
                    elif pos["type"] == "SELL" and current_price <= middle_band:
                        self.log_message(f"Ranging TP Target met for {symbol}. Closing SELL trade.")
                        self.mt5.close_position(pos["ticket"])
                        self.cooldowns[symbol] = time.time() + 15 * 60  # 15 mins cooldown
            
            # 4. Entry Logic
            if len(symbol_positions) == 0:
                # Check cooldown
                if time.time() < self.cooldowns[symbol]:
                    continue
                    
                if signal:
                    symbol_info = self.mt5.get_symbol_info(symbol)
                    if not symbol_info:
                        continue
                        
                    point = symbol_info["point"]
                    current_price = symbol_info["ask"] if signal == "BUY" else symbol_info["bid"]
                    
                    sl_price = 0.0
                    tp_price = 0.0
                    stop_loss_points = 0.0
                    
                    if regime == "RANGING":
                        # Ranging SL: Outside Bollinger bands extremes (lower band - 200 points for BUY)
                        offset = 200 * point if symbol == "XAUUSD" else 20 * point
                        sl_price = metrics["lower_band"] - offset if signal == "BUY" else metrics["upper_band"] + offset
                        # TP: Middle Band
                        tp_price = metrics["middle_band"]
                        
                    else:  # TRENDING
                        # Trending SL: 1.5 * M5 ATR
                        m5_atr = metrics.get("atr", 1.0)
                        sl_distance = 1.5 * m5_atr
                        tp_distance = 3.0 * m5_atr
                        
                        sl_price = current_price - sl_distance if signal == "BUY" else current_price + sl_distance
                        tp_price = current_price + tp_distance if signal == "BUY" else current_price - tp_distance
                    
                    # Compute Stop Loss distance in Points
                    sl_diff = abs(current_price - sl_price)
                    stop_loss_points = sl_diff / point
                    
                    # Calculate Lot size
                    lot_size = self.calculate_lot_size(symbol, balance, stop_loss_points)
                    
                    self.log_message(f"Signal Detected: {signal} on {symbol} in {regime} market. SL: {sl_price:.2f}, TP: {tp_price:.2f}. Lot Size: {lot_size}")
                    
                    res = self.mt5.place_market_order(symbol, signal, lot_size, sl_price, tp_price)
                    if res.get("status") == "SUCCESS":
                        self.log_message(f"Order Successful! Ticket: {res.get('ticket')}")
                        self.cooldowns[symbol] = time.time() + 15 * 60  # Cooldown
                    else:
                        self.log_message(f"Order Failed: {res.get('error')}")
