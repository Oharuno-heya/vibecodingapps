"""テクニカル指標の計算。入力は日足OHLCVのDataFrame(列: Open High Low Close Volume)。"""
import numpy as np
import pandas as pd


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """指標列を付加したコピーを返す。"""
    out = df.copy()
    close = out["Close"]
    out["sma5"] = sma(close, 5)
    out["sma25"] = sma(close, 25)
    out["sma75"] = sma(close, 75)
    out["rsi14"] = rsi(close)
    out["macd"], out["macd_sig"], out["macd_hist"] = macd(close)
    out["atr14"] = atr(out)
    out["atr_pct"] = out["atr14"] / close * 100
    out["turnover"] = close * out["Volume"]
    out["vol_ratio"] = out["Volume"].rolling(5).mean() / out["Volume"].rolling(25).mean()
    out["high52w"] = out["High"].rolling(250, min_periods=60).max()
    out["low52w"] = out["Low"].rolling(250, min_periods=60).min()
    return out
