"""ユニバース全体のスクリーニング。"""
from .config import load_universe
from .data import fetch_fundamentals, fetch_universe_history
from .signals import build_trade_plan, detect_buy_signal, score_stock


def run_screening(cfg: dict) -> list[dict]:
    """全ユニバースを採点し、スコア上位の候補リストを返す(スコア降順)。"""
    universe = load_universe()
    meta = {s["code"]: s for s in universe}
    histories = fetch_universe_history([s["code"] for s in universe])

    results = []
    for code, df in histories.items():
        scored = score_stock(df, cfg)
        if scored is None:
            continue
        e = scored.pop("enriched")
        signal = detect_buy_signal(e)
        plan = build_trade_plan(e, cfg, signal)
        results.append({
            "code": code,
            "name": meta[code]["name"],
            "sector": meta[code]["sector"],
            **scored,
            "signal": signal,
            "plan": plan,
        })

    results.sort(key=lambda x: x["score"], reverse=True)

    # スコア上位のみファンダ情報を補完(API呼び出し削減)
    top_n = cfg["screening"]["top_n"]
    min_score = cfg["screening"]["min_score"]
    for r in results[: top_n * 2]:
        if r["score"] >= min_score:
            r["fundamentals"] = fetch_fundamentals(r["code"])
    return results


def pick_candidates(results: list[dict], cfg: dict) -> list[dict]:
    """ウォッチリスト追加候補(スコア閾値以上・上位N件)を抽出。"""
    sc = cfg["screening"]
    picks = [r for r in results if r["score"] >= sc["min_score"]]
    return picks[: sc["top_n"]]
