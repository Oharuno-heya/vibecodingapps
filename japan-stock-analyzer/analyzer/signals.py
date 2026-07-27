"""個別銘柄のスコアリングと売買タイミング(エントリー/利確/損切り)の算出。"""
import pandas as pd

from .indicators import enrich


def score_stock(df: pd.DataFrame, cfg: dict) -> dict | None:
    """テクニカル面から100点満点でスコアリング。フィルタ落ちは None。"""
    sc = cfg["screening"]
    if len(df) < sc["min_bars"]:
        return None
    e = enrich(df)
    last = e.iloc[-1]
    close = float(last["Close"])

    # --- ハードフィルタ(流動性・価格帯・ボラティリティ = ミドルリスク条件) ---
    turnover20 = float(e["turnover"].tail(20).mean())
    if turnover20 < sc["min_turnover_yen"]:
        return None
    if not (sc["price_min"] <= close <= sc["price_max"]):
        return None
    atr_pct = float(last["atr_pct"])
    if pd.isna(atr_pct):
        return None

    score = 0.0
    parts = {}

    # トレンド (30点)
    t = 0
    if close > last["sma25"]:
        t += 10
    if last["sma25"] > last["sma75"]:
        t += 10
    sma75_slope = e["sma75"].iloc[-1] - e["sma75"].iloc[-6] if len(e) > 80 else 0
    if sma75_slope > 0:
        t += 10
    parts["trend"] = t

    # モメンタム (20点)
    m = 0
    rsi = float(last["rsi14"])
    if 40 <= rsi <= 65:
        m += 10
    elif 30 <= rsi < 40 or 65 < rsi <= 70:
        m += 5
    if last["macd_hist"] > e["macd_hist"].iloc[-2]:
        m += 10
    parts["momentum"] = m

    # ボラティリティ適性 (15点) — ミドルリスク帯に収まっているか
    v = 0
    if sc["atr_pct_min"] <= atr_pct <= sc["atr_pct_max"]:
        v = 15
    elif atr_pct < sc["atr_pct_min"] * 1.5 or atr_pct <= sc["atr_pct_max"] * 1.2:
        v = 7
    parts["volatility"] = v

    # 出来高動向 (10点)
    vol = 10 if float(last["vol_ratio"]) > 1.0 else 0
    parts["volume"] = vol

    # 52週レンジ内の位置 (10点) — 高値圏だが過熱していない位置を評価
    pos = (close - last["low52w"]) / max(last["high52w"] - last["low52w"], 1e-9)
    r = 10 if 0.6 <= pos <= 0.95 else (5 if 0.4 <= pos < 0.6 else 0)
    parts["range_pos"] = r

    # 押し目ボーナス (15点) — 上昇トレンド中の25日線近辺への押し
    p = 0
    uptrend = close > last["sma75"] and last["sma25"] > last["sma75"]
    dist_atr = (close - last["sma25"]) / max(float(last["atr14"]), 1e-9)
    if uptrend and -1.0 <= dist_atr <= 0.7:
        p = 15
    parts["pullback"] = p

    score = sum(parts.values())
    return {
        "score": round(score, 1),
        "parts": parts,
        "close": close,
        "rsi": round(rsi, 1),
        "atr": round(float(last["atr14"]), 1),
        "atr_pct": round(atr_pct, 2),
        "turnover20": turnover20,
        "enriched": e,
    }


def detect_buy_signal(e: pd.DataFrame) -> dict | None:
    """買いタイミングの検出。シグナルなしは None。"""
    last, prev = e.iloc[-1], e.iloc[-2]
    close = float(last["Close"])
    uptrend = close > last["sma75"] and last["sma25"] > last["sma75"]

    # 1) 押し目買い: 上昇トレンド中、25日線±1ATRまで押して陽転
    dist_atr = (close - last["sma25"]) / max(float(last["atr14"]), 1e-9)
    if uptrend and -1.0 <= dist_atr <= 0.7 and 35 <= last["rsi14"] <= 55 \
            and close > prev["Close"]:
        return {"type": "押し目買い", "strength": "中",
                "note": "上昇トレンド中の25日線近辺への押し目から反発の初動"}

    # 2) ブレイクアウト: 直近60日高値を出来高を伴って更新
    if len(e) > 61:
        prior_high = float(e["High"].iloc[-61:-1].max())
        if close > prior_high and float(last["vol_ratio"]) > 1.3:
            return {"type": "ブレイクアウト", "strength": "強",
                    "note": "直近60日高値を出来高増を伴い更新。初押しでの追随も可"}

    # 3) ゴールデンクロス: 5日線が25日線を直近2日以内に上抜け(トレンド初動)
    if len(e) > 30:
        gc_now = last["sma5"] > last["sma25"]
        gc_before = e["sma5"].iloc[-3] <= e["sma25"].iloc[-3]
        if gc_now and gc_before and close > last["sma75"]:
            return {"type": "ゴールデンクロス", "strength": "中",
                    "note": "5日線が25日線を上抜け。トレンド転換の初動を捉える形"}

    return None


def build_trade_plan(e: pd.DataFrame, cfg: dict, signal: dict | None) -> dict:
    """エントリー・利確・損切りの具体的な価格プランを算出。"""
    r = cfg["risk"]
    last = e.iloc[-1]
    close = float(last["Close"])
    atr = float(last["atr14"])

    entry = close
    # 損切り: 直近10日安値 or エントリー − 1.5ATR の高い方、ただし最大 -8%
    recent_low = float(e["Low"].tail(10).min())
    stop = max(recent_low * 0.995, entry - r["stop_loss_atr"] * atr)
    stop = max(stop, entry * (1 - r["max_stop_loss_pct"] / 100))
    # 利確: エントリー + 2.5ATR(スイング)
    target = entry + r["profit_target_atr"] * atr
    alt_target = entry * (1 + r["swing_alt_target_pct"] / 100)

    risk = entry - stop
    reward = target - entry
    rr = reward / risk if risk > 0 else 0

    ma_exit = float(last[f"sma{r['long_term_exit_ma']}"]) if pd.notna(
        last[f"sma{r['long_term_exit_ma']}"]) else None

    return {
        "entry": round(entry, 1),
        "entry_note": "翌営業日寄り付き近辺での成行 or 25日線への指値",
        "stop_loss": round(stop, 1),
        "stop_loss_pct": round((stop / entry - 1) * 100, 1),
        "profit_target": round(target, 1),
        "profit_target_pct": round((target / entry - 1) * 100, 1),
        "alt_target": round(alt_target, 1),
        "risk_reward": round(rr, 2),
        "long_term_exit": round(ma_exit, 1) if ma_exit else None,
        "long_term_note": f"終値が{r['long_term_exit_ma']}日線"
                          f"({round(ma_exit, 1) if ma_exit else '-'}円)を明確に割れたら撤退",
        "actionable": rr >= r["min_risk_reward"] and signal is not None,
    }
