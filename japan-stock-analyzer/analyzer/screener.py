"""ユニバース全体のスクリーニング。

選定条件(ミドルリスク・大型株厳選):
1. テクニカル: トレンドフォロー(上昇トレンド+押し目)を100点満点で採点
2. セクター内厳選: グループ内で売買代金上位N銘柄(既定3)のみ
3. 大型株: 時価総額5000億円以上
4. 財務健全性: 自己資本比率40%以上
5. セクターローテーション: 上昇見込みセクターに加点、下落見込みセクターは除外
"""
from collections import defaultdict

from .config import load_universe
from .data import fetch_universe_history
from .fundamentals import load_fundamentals
from .sectors import analyze_sectors, group_of
from .signals import build_trade_plan, detect_buy_signal, score_stock
from .watchlist import get_watchlist


def run_screening(cfg: dict, market: dict) -> tuple[list[dict], dict]:
    """全ユニバースを採点し、(結果リスト, セクター分析) を返す(スコア降順)。"""
    universe = load_universe()
    meta = {s["code"]: s for s in universe}
    histories = fetch_universe_history(list(meta))

    scored = {}
    for code, df in histories.items():
        s = score_stock(df, cfg)
        if s is not None:
            scored[code] = s

    sector_info = analyze_sectors(histories, meta, market["snapshots"], cfg)

    # セクター(グループ)内で売買代金上位N銘柄に厳選
    by_group = defaultdict(list)
    for code, s in scored.items():
        by_group[group_of(meta[code]["sector"])].append((code, s))
    selected = set()
    for members in by_group.values():
        members.sort(key=lambda x: x[1]["turnover20"], reverse=True)
        selected.update(c for c, _ in members[: cfg["screening"]["sector_top_n"]])

    # ファンダ情報はセクター上位銘柄+ウォッチリスト銘柄のみ取得(API節約)
    wl_codes = {w["code"] for w in get_watchlist()}
    fund_map = load_fundamentals(sorted(selected | (wl_codes & set(scored))), cfg)

    min_mcap = cfg["screening"]["min_market_cap_yen"]
    min_eq = cfg["screening"]["min_equity_ratio_pct"]
    bonus_map = sector_info["bonus_by_group"]

    results = []
    for code, s in scored.items():
        e = s.pop("enriched")
        group = group_of(meta[code]["sector"])
        f = fund_map.get(code, {})
        mcap, eq = f.get("market_cap"), f.get("equity_ratio")
        # 取得済みの値が基準未満なら False。未取得(None)は判定保留
        fund_ok = None
        if mcap is not None or eq is not None:
            fund_ok = not ((mcap is not None and mcap < min_mcap)
                           or (eq is not None and eq < min_eq))
        bonus = bonus_map.get(group, 0)
        signal = detect_buy_signal(e)
        plan = build_trade_plan(e, cfg, signal)
        results.append({
            "code": code,
            "name": meta[code]["name"],
            "sector": meta[code]["sector"],
            "group": group,
            **s,
            "tech_score": s["score"],
            "score": s["score"] + bonus,
            "sector_bonus": bonus,
            "in_sector_top": code in selected,
            "fundamentals": f,
            "fund_ok": fund_ok,
            "signal": signal,
            "plan": plan,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results, sector_info


def pick_candidates(results: list[dict], sector_info: dict, cfg: dict) -> list[dict]:
    """ウォッチリスト追加候補を抽出。

    条件: スコア閾値以上・セクター内売買代金上位・ファンダ基準を満たす
    (未取得は保留で通す)・下落見込みセクターでない。
    """
    sc = cfg["screening"]
    exclude = cfg["sector"]["exclude_score"]
    totals = sector_info["totals"]
    picks = [
        r for r in results
        if r["score"] >= sc["min_score"]
        and r["in_sector_top"]
        and r["fund_ok"] is not False
        and totals.get(r["group"], 0) > exclude
    ]
    return picks[: sc["top_n"]]
