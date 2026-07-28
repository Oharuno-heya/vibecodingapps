"""ファンダメンタル情報(時価総額・自己資本比率・PER等)の取得とキャッシュ。

Yahoo Financeの info / 貸借対照表から取得する。銘柄ごとのAPI呼び出しが重いため
JSONファイルにキャッシュし、有効期限内は再利用する(既定7日)。
"""
import hashlib
import json
import time
from datetime import date

import numpy as np

from .config import DATA_DIR, is_mock

CACHE_PATH = DATA_DIR / "fundamentals_cache.json"

_EQUITY_KEYS = [
    "Stockholders Equity",
    "Total Stockholder Equity",
    "Common Stock Equity",
    "Total Equity Gross Minority Interest",
]


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _bs_value(bs, keys) -> float | None:
    for key in keys:
        if key in bs.index:
            row = bs.loc[key].dropna()
            if len(row) > 0:
                return float(row.iloc[0])
    return None


def _fetch(code: str) -> dict:
    if is_mock():
        seed = int(hashlib.md5(code.encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        return {
            "market_cap": float(rng.uniform(8e10, 6e12)),
            "equity_ratio": round(float(rng.uniform(15, 80)), 1),
            "per": round(float(rng.uniform(8, 35)), 1),
            "pbr": round(float(rng.uniform(0.6, 4.0)), 2),
            "dividend_yield": round(float(rng.uniform(0, 4.0)), 2),
        }
    import yfinance as yf

    out = {"market_cap": None, "equity_ratio": None, "per": None,
           "pbr": None, "dividend_yield": None}
    try:
        t = yf.Ticker(f"{code}.T")
        info = t.info or {}
        out["market_cap"] = info.get("marketCap")
        per = info.get("trailingPE")
        if per is not None and 0 < per <= 500:
            out["per"] = round(per, 1)
        pbr = info.get("priceToBook")
        if pbr is not None and 0 < pbr <= 100:
            out["pbr"] = round(pbr, 2)
        dy = info.get("dividendYield")
        if dy is not None and dy < 1:  # 比率で返る場合は%へ
            dy = dy * 100
        if dy is not None and 0 <= dy <= 15:  # 異常値は欠損扱い
            out["dividend_yield"] = round(dy, 2)
        try:
            bs = t.balance_sheet
            if bs is not None and not bs.empty:
                total_assets = _bs_value(bs, ["Total Assets"])
                equity = _bs_value(bs, _EQUITY_KEYS)
                if total_assets and equity and total_assets > 0:
                    out["equity_ratio"] = round(equity / total_assets * 100, 1)
        except Exception:
            pass
    except Exception:
        pass
    return out


def load_fundamentals(codes: list[str], cfg: dict) -> dict[str, dict]:
    """指定銘柄のファンダ情報を返す(キャッシュ優先)。code -> dict。"""
    cache = _load_cache()
    max_age = cfg.get("fundamentals", {}).get("cache_days", 7)
    today = date.today()
    out, dirty = {}, False
    for code in codes:
        ent = cache.get(code)
        if ent and "fetched" in ent:
            age = (today - date.fromisoformat(ent["fetched"])).days
            if age < max_age:
                out[code] = ent
                continue
        f = _fetch(code)
        f["fetched"] = today.isoformat()
        cache[code] = f
        out[code] = f
        dirty = True
        if not is_mock():
            time.sleep(0.5)  # API負荷軽減
    if dirty:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
