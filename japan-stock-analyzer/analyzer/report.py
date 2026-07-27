"""Markdownレポートの生成。"""
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import REPORTS_DIR

JST = ZoneInfo("Asia/Tokyo")

SESSION_LABELS = {"morning": "朝(寄り前)", "noon": "昼(前場終了後)", "evening": "夕(大引け後)"}

SESSION_INTRO = {
    "morning": "前日の海外市場を踏まえた寄り付き前の分析です。買いシグナル銘柄は寄り付きの動きを確認してからのエントリーを推奨します。",
    "noon": "前場までの動きを踏まえた昼休みの分析です。後場に向けたスタンス確認にご利用ください。",
    "evening": "大引け後の本日の総括と、翌営業日に向けたスクリーニング結果です。",
}


def _fmt_num(v, digits=1, suffix=""):
    if v is None:
        return "-"
    return f"{v:,.{digits}f}{suffix}"


def _market_section(market: dict) -> list[str]:
    lines = ["## 1. 市況分析(市場の流れ)", ""]
    lines.append(f"**総合判断: {market['stance']}**(スコア {market['score']:+d})")
    lines.append("")
    lines.append(f"> {market['advice']}")
    lines.append("")
    lines.append("| 指数/為替 | 終値 | 前日比 | 5日騰落 | RSI |")
    lines.append("|---|---:|---:|---:|---:|")
    for tk, name in market["names"].items():
        s = market["snapshots"].get(tk)
        if not s:
            continue
        lines.append(
            f"| {name} | {_fmt_num(s['close'])} | {s['change_pct']:+.2f}% | "
            f"{_fmt_num(s['change_5d_pct'], 2, '%') if s['change_5d_pct'] is not None else '-'} | "
            f"{s['rsi']:.0f} |"
        )
    if market["reasons"]:
        lines.append("")
        lines.append("**ポイント:**")
        for r in market["reasons"]:
            lines.append(f"- {r}")
    lines.append("")
    return lines


def _plan_lines(plan: dict) -> str:
    return (
        f"エントリー {_fmt_num(plan.get('entry'))}円 / "
        f"利確 {_fmt_num(plan.get('profit_target'))}円 ({_fmt_num(plan.get('profit_target_pct'))}%) / "
        f"損切り {_fmt_num(plan.get('stop_loss'))}円 ({_fmt_num(plan.get('stop_loss_pct'))}%) / "
        f"RR比 {_fmt_num(plan.get('risk_reward'), 2)}"
    )


def _candidates_section(candidates: list[dict], added: list[dict]) -> list[str]:
    lines = ["## 2. スクリーニング結果(投資候補)", ""]
    if not candidates:
        lines.append("本日の基準(スコア60点以上)を満たす銘柄はありませんでした。")
        lines.append("")
        return lines
    added_codes = {a["code"] for a in added}
    lines.append("| コード | 銘柄 | セクター | スコア | 株価 | RSI | ATR% | シグナル | PER | 配当利回り |")
    lines.append("|---|---|---|---:|---:|---:|---:|---|---:|---:|")
    for c in candidates:
        f = c.get("fundamentals") or {}
        sig = c["signal"]["type"] if c["signal"] else "-"
        mark = " 🆕" if c["code"] in added_codes else ""
        lines.append(
            f"| {c['code']}{mark} | {c['name']} | {c['sector']} | {c['score']:.0f} | "
            f"{_fmt_num(c['close'])} | {c['rsi']:.0f} | {c['atr_pct']:.1f} | {sig} | "
            f"{_fmt_num(f.get('per'))} | {_fmt_num(f.get('dividend_yield'), 2, '%')} |"
        )
    lines.append("")
    lines.append("🆕 = 今回ウォッチリストに新規追加")
    lines.append("")
    return lines


def _buy_signals_section(buy_signals: list[dict], order_plans: list[dict]) -> list[str]:
    lines = ["## 3. 買いシグナルと売買プラン", ""]
    if not buy_signals:
        lines.append("現在、買いシグナルが点灯している銘柄はありません。押し目・ブレイクを待ちます。")
        lines.append("")
        return lines
    for b in buy_signals:
        plan = b["plan"]
        sig = b["signal"]
        lines.append(f"### {b['code']} {b['name']}({sig['type']} / 強度: {sig['strength']})")
        lines.append("")
        lines.append(f"- 根拠: {sig['note']}")
        lines.append(f"- 現在値: {_fmt_num(b.get('price') or b.get('close'))}円 "
                     f"/ スコア: {b['score']:.0f}点")
        lines.append(f"- **買い**: {_fmt_num(plan['entry'])}円近辺({plan['entry_note']})")
        lines.append(f"- **利確**: {_fmt_num(plan['profit_target'])}円 "
                     f"({plan['profit_target_pct']:+.1f}%)"
                     f" / 代替目標 {_fmt_num(plan['alt_target'])}円(スイング +12%目安)")
        lines.append(f"- **損切り**: {_fmt_num(plan['stop_loss'])}円 "
                     f"({plan['stop_loss_pct']:+.1f}%)— 終値ベースで割れたら翌日成行撤退")
        lines.append(f"- リスクリワード比: {plan['risk_reward']:.2f}"
                     + ("(基準クリア ✅)" if plan.get("actionable") else "(基準未満 ⚠️ 見送り推奨)"))
        if plan.get("long_term_note"):
            lines.append(f"- 長期保有の場合: {plan['long_term_note']}")
        lines.append("")
    if order_plans:
        lines.append("### 発注案(参考)")
        lines.append("")
        lines.append("楽天証券・SBI証券には個人向け発注APIがないため、以下は手動発注用の注文案です。")
        lines.append("")
        lines.append("| コード | 銘柄 | 注文 | 株数 | 概算金額 | 利確(指値目安) | 損切り(逆指値) |")
        lines.append("|---|---|---|---:|---:|---:|---:|")
        for o in order_plans:
            lines.append(
                f"| {o['code']} | {o['name']} | {o['order_type']} | {o['shares']} | "
                f"{o['amount']:,.0f}円 | {_fmt_num(o['profit_target'])}円 | "
                f"{_fmt_num(o['stop_loss'])}円 |"
            )
        lines.append("")
    return lines


def _watchlist_section(review: dict) -> list[str]:
    lines = ["## 4. ウォッチリスト(継続観察銘柄)", ""]
    wl = review["watchlist"]
    if not wl:
        lines.append("ウォッチリストは空です。次回のスクリーニングで候補を追加します。")
        lines.append("")
    else:
        lines.append("| コード | 銘柄 | 追加日 | 観察日数 | スコア | 株価 | 状態 | 売買プラン |")
        lines.append("|---|---|---|---:|---:|---:|---|---|")
        for w in wl:
            status = "🔔 買いシグナル" if w["status"] == "buy_signal" else "👀 観察中"
            if w["low_score_streak"] > 0:
                status += f"(低調{w['low_score_streak']}回)"
            lines.append(
                f"| {w['code']} | {w['name']} | {w['added_date']} | {w['days_watched']}日 | "
                f"{_fmt_num(w['score'], 0)} | {_fmt_num(w['price'])} | {status} | "
                f"{_plan_lines(w['plan'])} |"
            )
        lines.append("")
    if review["removed"]:
        lines.append("**除外した銘柄:**")
        for r in review["removed"]:
            lines.append(f"- {r['code']} {r['name']}: {r['reason']}")
        lines.append("")
    return lines


def build_report(session: str, market: dict, candidates: list[dict], added: list[dict],
                 review: dict, order_plans: list[dict]) -> str:
    now = datetime.now(JST)
    lines = [
        f"# 日本株分析レポート {now.strftime('%Y-%m-%d')} {SESSION_LABELS[session]}",
        "",
        f"生成時刻: {now.strftime('%Y-%m-%d %H:%M JST')}",
        "",
        f"> {SESSION_INTRO[session]}",
        "",
    ]
    lines += _market_section(market)
    lines += _candidates_section(candidates, added)
    lines += _buy_signals_section(review["buy_signals"], order_plans)
    lines += _watchlist_section(review)
    lines += [
        "---",
        "",
        "*免責: 本レポートはテクニカル指標に基づく自動分析であり、投資勧誘ではありません。"
        "最終的な投資判断はご自身の責任で行ってください。*",
        "",
    ]
    return "\n".join(lines)


def save_report(session: str, content: str) -> str:
    now = datetime.now(JST)
    day_dir = REPORTS_DIR / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"{session}.md"
    path.write_text(content, encoding="utf-8")
    shutil.copyfile(path, REPORTS_DIR / "latest.md")
    return str(path)
