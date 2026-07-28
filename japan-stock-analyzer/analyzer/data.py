"""株価データの取得。

主データソース: Yahoo Finance (yfinance) — 無料・APIキー不要
フォールバック: Stooq (https://stooq.com) — 無料CSV API・日本株対応
JSA_MOCK=1 のときは合成データを生成する(オフライン開発用)。
"""
import hashlib
import io
import time
import urllib.request

import numpy as np
import pandas as pd

from .config import is_mock

# 市況分析に使う指数・為替
MARKET_TICKERS = {
    "^N225": "日経平均",
    "1306.T": "TOPIX連動ETF",
    "2516.T": "東証グロース250ETF",
    "JPY=X": "ドル円",
    "^GSPC": "S&P500",
    "^IXIC": "NASDAQ",
    "^VIX": "VIX(恐怖指数)",
    "^SOX": "SOX(半導体指数)",
    "^TNX": "米10年債利回り",
    "JP10Y": "日本10年債利回り",
    "CL=F": "WTI原油先物",
}

# Yahooにデータがなく、Stooqのみで取得するティッカー
_STOOQ_ONLY = {"JP10Y"}

_REQUIRED = ["Open", "High", "Low", "Close", "Volume"]


def _mock_history(ticker: str, days: int = 300) -> pd.DataFrame:
    """決定的な乱数ウォークで日足を合成(オフライン開発・テスト用)。"""
    seed = int(hashlib.md5(ticker.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    base = float(rng.uniform(500, 15000))
    drift = rng.uniform(-0.0005, 0.0012)
    rets = rng.normal(drift, 0.018, days)
    close = base * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.001, 0.02, days))
    low = close * (1 - rng.uniform(0.001, 0.02, days))
    open_ = low + (high - low) * rng.uniform(0.2, 0.8, days)
    vol = rng.uniform(2e5, 5e6, days)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx
    )


# Yahooティッカー -> Stooqシンボルの対応
_STOOQ_MAP = {
    "^N225": "^nkx",
    "^GSPC": "^spx",
    "^IXIC": "^ndq",
    "JPY=X": "usdjpy",
    "^VIX": "^vix",
    "^SOX": "^sox",
    "^TNX": "10usy.b",
    "JP10Y": "10jpy.b",
    "CL=F": "cl.f",
}


def _to_stooq_symbol(ticker: str) -> str | None:
    if ticker in _STOOQ_MAP:
        return _STOOQ_MAP[ticker]
    if ticker.endswith(".T"):
        return ticker[:-2].lower() + ".jp"
    return None


def _fetch_stooq(ticker: str, max_bars: int = 500) -> pd.DataFrame | None:
    """StooqのCSVエンドポイントから日足を取得(APIキー不要)。"""
    sym = _to_stooq_symbol(ticker)
    if sym is None:
        return None
    url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        if not text.startswith("Date"):
            return None  # "No data" などのエラー応答
        df = pd.read_csv(io.StringIO(text), parse_dates=["Date"], index_col="Date")
        if "Volume" not in df.columns:  # 為替・一部指数には出来高がない
            df["Volume"] = 0.0
        df = df[_REQUIRED].dropna(subset=["Close"])
        return df.tail(max_bars) if len(df) > 0 else None
    except Exception:
        return None


def _fetch_yfinance(ticker: str, period: str, retries: int = 2) -> pd.DataFrame | None:
    import yfinance as yf

    for attempt in range(retries):
        try:
            df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
            if df is not None and len(df) > 0:
                df = df[[c for c in _REQUIRED if c in df.columns]].dropna(subset=["Close"])
                return df if len(df) > 0 else None
            return None
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def fetch_history(ticker: str, period: str = "2y") -> pd.DataFrame | None:
    """1銘柄の日足を取得。Yahoo→Stooqの順に試し、失敗時は None。"""
    if is_mock():
        return _mock_history(ticker)
    if ticker in _STOOQ_ONLY:
        return _fetch_stooq(ticker)
    df = _fetch_yfinance(ticker, period)
    if df is not None:
        return df
    return _fetch_stooq(ticker)


def fetch_universe_history(codes: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """ユニバース全銘柄の日足を一括取得。code(4桁) -> DataFrame。"""
    tickers = [f"{c}.T" for c in codes]
    if is_mock():
        return {c: _mock_history(t) for c, t in zip(codes, tickers)}
    import yfinance as yf

    result: dict[str, pd.DataFrame] = {}
    chunk = 40
    for i in range(0, len(tickers), chunk):
        batch = tickers[i : i + chunk]
        try:
            data = yf.download(
                batch, period=period, auto_adjust=True, group_by="ticker",
                threads=True, progress=False,
            )
        except Exception:
            data = None
        for code, tk in zip(codes[i : i + chunk], batch):
            df = None
            if data is not None and not data.empty:
                try:
                    df = data[tk][_REQUIRED].dropna(subset=["Close"])
                except Exception:
                    df = None
            if df is None or len(df) == 0:
                df = fetch_history(tk, period)
            if df is not None and len(df) > 0:
                result[code] = df
        time.sleep(1)
    return result


def fetch_market_data() -> dict[str, pd.DataFrame]:
    """指数・為替の日足を取得。ticker -> DataFrame。"""
    out = {}
    for tk in MARKET_TICKERS:
        df = fetch_history(tk, period="6mo")
        if df is not None and len(df) >= 2:
            out[tk] = df
    return out


