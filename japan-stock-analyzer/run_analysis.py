#!/usr/bin/env python3
"""日本株自動分析ツール エントリーポイント。

使い方:
    python run_analysis.py                     # 現在時刻(JST)からセッション自動判定
    python run_analysis.py --session morning   # 朝・昼・夕を明示指定
    JSA_MOCK=1 python run_analysis.py          # 合成データで動作テスト(オフライン)
"""
import argparse
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from analyzer.config import load_config
from analyzer.market import analyze_market
from analyzer.report import build_report, save_report
from analyzer.screener import pick_candidates, run_screening
from analyzer.watchlist import add_candidates, get_watchlist, review_watchlist

JST = ZoneInfo("Asia/Tokyo")


def detect_session() -> str:
    hour = datetime.now(JST).hour
    if hour < 10:
        return "morning"
    if hour < 15:
        return "noon"
    return "evening"


def build_order_plans(buy_signals: list[dict], cfg: dict) -> list[dict]:
    """買いシグナル銘柄から手動発注用の注文案を作る。"""
    budget = cfg["trading"]["budget_per_position"]
    lot = cfg["trading"]["lot_size"]
    plans = []
    for b in buy_signals:
        plan = b["plan"]
        if not plan.get("actionable"):
            continue
        price = plan["entry"]
        shares = int(budget // (price * lot)) * lot
        if shares == 0:
            continue  # 予算内で単元購入不可
        plans.append({
            "code": b["code"],
            "name": b["name"],
            "order_type": "寄付成行(または前日終値近辺の指値)",
            "shares": shares,
            "amount": shares * price,
            "profit_target": plan["profit_target"],
            "stop_loss": plan["stop_loss"],
        })
    return plans


def main() -> int:
    parser = argparse.ArgumentParser(description="日本株自動分析ツール")
    parser.add_argument("--session", choices=["morning", "noon", "evening"],
                        help="セッション指定(省略時はJST時刻から自動判定)")
    args = parser.parse_args()
    session = args.session or detect_session()

    print(f"[1/5] セッション: {session} / 市況分析を実行中...")
    market = analyze_market()
    print(f"      市況判定: {market['stance']} (スコア {market['score']:+d})")

    print("[2/5] スクリーニングとセクターローテーション分析を実行中...")
    cfg = load_config()
    results, sector_info = run_screening(cfg, market)
    top_sectors = [e["group"] for e in sector_info["entries"] if e["bonus"] > 0]
    print(f"      {len(results)}銘柄を採点 / 上昇見込みセクター: {', '.join(top_sectors) or 'なし'}")

    print("[3/5] 新規候補をウォッチリストへ追加中...")
    candidates = pick_candidates(results, sector_info, cfg)
    added = add_candidates(candidates, cfg, session)
    for a in added:
        print(f"      追加: {a['code']} {a['name']} (スコア {a['score']:.0f})")

    print("[4/5] ウォッチリストを再評価中...")
    results_by_code = {r["code"]: r for r in results}
    review = review_watchlist(results_by_code, cfg, session)
    for r in review["removed"]:
        print(f"      除外: {r['code']} {r['name']} ({r['reason']})")
    order_plans = build_order_plans(review["buy_signals"], cfg)

    print("[5/5] レポートを生成中...")
    content = build_report(session, market, sector_info, candidates, added, review,
                           order_plans)
    path = save_report(session, content)
    print(f"      レポート: {path}")
    print(f"      ウォッチリスト: {len(get_watchlist())}銘柄 / "
          f"買いシグナル: {len(review['buy_signals'])}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
