"""市場全体の流れ(市況)の分析。"""
import pandas as pd

from .data import MARKET_TICKERS, fetch_market_data
from .indicators import enrich


def _snapshot(df: pd.DataFrame) -> dict:
    e = enrich(df)
    last = e.iloc[-1]
    prev = e.iloc[-2]
    chg = (last["Close"] / prev["Close"] - 1) * 100
    chg5 = (last["Close"] / e["Close"].iloc[-6] - 1) * 100 if len(e) > 6 else None
    chg5_abs = last["Close"] - e["Close"].iloc[-6] if len(e) > 6 else None
    return {
        "close": float(last["Close"]),
        "change_pct": float(chg),
        "change_5d_pct": float(chg5) if chg5 is not None else None,
        "change_5d_abs": float(chg5_abs) if chg5_abs is not None else None,  # 金利用(%pt)
        "above_sma25": bool(last["Close"] > last["sma25"]) if pd.notna(last["sma25"]) else None,
        "rsi": float(last["rsi14"]),
    }


def analyze_market() -> dict:
    """指数・為替のスナップショットと、ルールベースの市況判定を返す。"""
    raw = fetch_market_data()
    snaps = {tk: _snapshot(df) for tk, df in raw.items()}

    score = 0  # リスクオン(+) / リスクオフ(-) の集計
    reasons = []

    n225 = snaps.get("^N225")
    if n225:
        score += 1 if n225["change_pct"] > 0 else -1
        if n225["above_sma25"] is True:
            score += 1
            reasons.append("日経平均は25日線の上で推移(上昇トレンド維持)")
        elif n225["above_sma25"] is False:
            score -= 1
            reasons.append("日経平均は25日線を下回っており調整局面")
        if n225["rsi"] >= 70:
            reasons.append("日経平均のRSIが70超で短期的な過熱感あり")
        elif n225["rsi"] <= 30:
            reasons.append("日経平均のRSIが30以下で売られすぎ水準")

    spx = snaps.get("^GSPC")
    if spx:
        score += 1 if spx["change_pct"] > 0 else -1
        reasons.append(
            f"前日の米国市場はS&P500が{spx['change_pct']:+.2f}%"
            + ("と堅調で、東京市場の追い風" if spx["change_pct"] > 0.3
               else "と軟調で、東京市場の重し" if spx["change_pct"] < -0.3 else "")
        )

    vix = snaps.get("^VIX")
    if vix:
        if vix["close"] >= 25:
            score -= 2
            reasons.append(f"VIXが{vix['close']:.1f}と高く、リスクオフ警戒")
        elif vix["close"] <= 15:
            score += 1
            reasons.append(f"VIXは{vix['close']:.1f}と低位で市場は落ち着いている")

    jpy = snaps.get("JPY=X")
    if jpy:
        if jpy["change_pct"] > 0.3:
            reasons.append(f"ドル円は{jpy['close']:.1f}円へ円安進行、輸出株に追い風")
            score += 1
        elif jpy["change_pct"] < -0.3:
            reasons.append(f"ドル円は{jpy['close']:.1f}円へ円高進行、輸出株の重し")
            score -= 1

    jp10 = snaps.get("JP10Y")
    if jp10 and jp10.get("change_5d_abs") is not None:
        bp = jp10["change_5d_abs"] * 100  # %ポイント→bp
        if bp >= 5:
            reasons.append(
                f"国内10年債利回りが5日で{bp:+.0f}bp上昇({jp10['close']:.2f}%)。"
                "利上げ・金利上昇局面は銀行など金融株の追い風"
            )
        elif bp <= -5:
            reasons.append(
                f"国内10年債利回りが5日で{bp:+.0f}bp低下({jp10['close']:.2f}%)。"
                "金融株の利ざやには逆風"
            )

    sox = snaps.get("^SOX")
    if sox and abs(sox["change_pct"]) > 1.5:
        reasons.append(
            f"SOX指数が{sox['change_pct']:+.2f}%と大きく動いており、半導体関連株は要注目"
        )

    if score >= 3:
        stance = "リスクオン"
        advice = "地合いは良好。押し目買い・ブレイクアウトとも仕掛けやすい環境。"
    elif score >= 1:
        stance = "やや強気"
        advice = "地合いは悪くないが過信は禁物。シグナルの出た銘柄に絞ってエントリー。"
    elif score >= -1:
        stance = "中立"
        advice = "方向感に欠ける。新規は小さめのロットで、損切りラインを厳守。"
    elif score >= -3:
        stance = "やや弱気"
        advice = "新規買いは慎重に。ウォッチリストの監視を中心に、打診買いに留める。"
    else:
        stance = "リスクオフ"
        advice = "新規買いは見送り推奨。保有銘柄の損切りライン割れに注意。"

    return {
        "snapshots": snaps,
        "names": MARKET_TICKERS,
        "score": score,
        "stance": stance,
        "advice": advice,
        "reasons": reasons,
    }
