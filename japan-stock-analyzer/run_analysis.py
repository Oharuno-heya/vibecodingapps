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
from analyzer.portfolio import execute_trades
from analyzer.report import build_report, build_summary, save_report, save_summary
from analyzer.screener import pick_candidates, run_screening
from analyzer.targets import size_position, trading_params
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
    """買いシグナル銘柄から手動発注用の注文案を作る(月次目標の資金配分に基づく)。"""
    params = trading_params(cfg)
    plans = []
    for b in buy_signals:
        plan = b["plan"]
        if not plan.get("actionable"):
            continue
        price = plan["entry"]
        shares = size_position(price, params["budget_per_position"], params)
        if shares == 0:
            continue  # 予算内で購入不可
        order_type = "寄付近辺の成行または指値"
        if params["fractional"] and shares < params["lot_size"]:
            order_type += "(かぶミニ/S株)"
        plans.append({
            "code": b["code"],
            "name": b["name"],
            "order_type": order_type,
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

    print(f"[1/6] セッション: {session} / 市況分析を実行中...")
    market = analyze_market()
    print(f"      市況判定: {market['stance']} (スコア {market['score']:+d})")

    print("[2/6] スクリーニングとセクターローテーション分析を実行中...")
    cfg = load_config()
    results, sector_info = run_screening(cfg, market)
    top_sectors = [e["group"] for e in sector_info["entries"] if e["bonus"] > 0]
    print(f"      {len(results)}銘柄を採点 / 上昇見込みセクター: {', '.join(top_sectors) or 'なし'}")

    print("[3/6] 新規候補をウォッチリストへ追加中...")
    candidates = pick_candidates(results, sector_info, cfg)
    added = add_candidates(candidates, cfg, session)
    for a in added:
        print(f"      追加: {a['code']} {a['name']} (スコア {a['score']:.0f})")

    print("[4/6] ウォッチリストを再評価中...")
    results_by_code = {r["code"]: r for r in results}
    review = review_watchlist(results_by_code, cfg, session)
    for r in review["removed"]:
        print(f"      除外: {r['code']} {r['name']} ({r['reason']})")
    order_plans = build_order_plans(review["buy_signals"], cfg)

    print("[5/6] ペーパートレードを執行中...")
    portfolio = execute_trades(review, results_by_code, cfg, session)
    for ev in portfolio.get("events", []):
        print(f"      {ev}")
    if portfolio.get("enabled"):
        print(f"      総資産: {portfolio['total']:,.0f}円 "
              f"(現金 {portfolio['cash']:,.0f}円 / ポジション {len(portfolio['positions'])}銘柄)")

    print("[6/6] レポートを生成中...")
    content = build_report(session, market, sector_info, candidates, added, review,
                           order_plans, portfolio)
    path = save_report(session, content)
    save_summary(build_summary(session, market, sector_info, review, order_plans, portfolio))
    print(f"      レポート: {path}")
    print(f"      ウォッチリスト: {len(get_watchlist())}銘柄 / "
          f"買いシグナル: {len(review['buy_signals'])}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
