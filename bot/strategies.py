import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional

# --- Technical Indicator Helpers ---

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculates Average True Range (ATR)"""
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    # Using simple moving average of True Range for ATR
    return tr.rolling(window=period).mean()

def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculates Relative Strength Index (RSI)"""
    close = df['close']
    delta = close.diff()
    
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    # Exponential moving averages for gain/loss
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, num_std: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Calculates Bollinger Bands: (Middle, Upper, Lower)"""
    close = df['close']
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + (num_std * std)
    lower = middle - (num_std * std)
    return middle, upper, lower

def calculate_ema(df: pd.DataFrame, period: int) -> pd.Series:
    """Calculates Exponential Moving Average (EMA)"""
    return df['close'].ewm(span=period, adjust=False).mean()


# --- Strategy Engines ---

def check_volatility_regime(df_m15: pd.DataFrame) -> Tuple[str, float, float]:
    """
    Determines market regime based on M15 ATR.
    Returns: (regime_name, current_atr, atr_sma)
    """
    if len(df_m15) < 65:
        # Not enough data yet to calculate 50-period SMA of 14-ATR
        return "RANGING", 0.0, 0.0
        
    atr = calculate_atr(df_m15, 14)
    atr_sma = atr.rolling(window=50).mean()
    
    current_atr = float(atr.iloc[-1])
    current_sma = float(atr_sma.iloc[-1])
    
    if np.isnan(current_atr) or np.isnan(current_sma):
        return "RANGING", 0.0, 0.0
        
    regime = "TRENDING" if current_atr > current_sma else "RANGING"
    return regime, current_atr, current_sma


def check_ranging_signals(df_m5: pd.DataFrame) -> Tuple[Optional[str], Dict]:
    """
    Ranging Strategy: Mean Reversion using Bollinger Bands and RSI on M5.
    Returns: (signal, metrics) where signal is 'BUY', 'SELL', or None
    """
    if len(df_m5) < 20:
        return None, {}
        
    middle_band, upper_band, lower_band = calculate_bollinger_bands(df_m5, 20, 2.0)
    rsi = calculate_rsi(df_m5, 14)
    
    # Fetch current values
    close = float(df_m5['close'].iloc[-1])
    curr_rsi = float(rsi.iloc[-1])
    curr_upper = float(upper_band.iloc[-1])
    curr_lower = float(lower_band.iloc[-1])
    curr_middle = float(middle_band.iloc[-1])
    
    metrics = {
        "rsi": curr_rsi,
        "upper_band": curr_upper,
        "lower_band": curr_lower,
        "middle_band": curr_middle,
        "close": close
    }
    
    # Buy Trigger: Price below lower band AND RSI oversold
    if close < curr_lower and curr_rsi <= 30:
        return "BUY", metrics
        
    # Sell Trigger: Price above upper band AND RSI overbought
    if close > curr_upper and curr_rsi >= 70:
        return "SELL", metrics
        
    return None, metrics


def check_trending_signals(df_m5: pd.DataFrame) -> Tuple[Optional[str], Dict]:
    """
    Trending Strategy: EMA crossover (9 & 21) on M5 with bullish/bearish candle check.
    Returns: (signal, metrics)
    """
    if len(df_m5) < 25:
        return None, {}
        
    ema9 = calculate_ema(df_m5, 9)
    ema21 = calculate_ema(df_m5, 21)
    atr = calculate_atr(df_m5, 14)
    
    # Current values
    curr_ema9 = float(ema9.iloc[-1])
    curr_ema21 = float(ema21.iloc[-1])
    prev_ema9 = float(ema9.iloc[-2])
    prev_ema21 = float(ema21.iloc[-2])
    curr_atr = float(atr.iloc[-1])
    
    close = float(df_m5['close'].iloc[-1])
    open_p = float(df_m5['open'].iloc[-1])
    
    metrics = {
        "ema9": curr_ema9,
        "ema21": curr_ema21,
        "atr": curr_atr,
        "close": close,
        "open": open_p
    }
    
    # Golden Cross (Bullish): 9 EMA crosses above 21 EMA AND current candle is green
    if (prev_ema9 <= prev_ema21) and (curr_ema9 > curr_ema21) and (close > open_p):
        return "BUY", metrics
        
    # Death Cross (Bearish): 9 EMA crosses below 21 EMA AND current candle is red
    if (prev_ema9 >= prev_ema21) and (curr_ema9 < curr_ema21) and (close < open_p):
        return "SELL", metrics
        
    return None, metrics
