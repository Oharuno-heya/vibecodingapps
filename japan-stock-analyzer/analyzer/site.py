"""スマホ向けダッシュボード(静的HTML)の生成。

毎回の分析実行時に site/index.html を生成し、GitHub Pages で公開する。
自己完結の1ファイル(CSSインライン・外部リソースなし)。
"""
import html
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import BASE_DIR, REPORTS_DIR

JST = ZoneInfo("Asia/Tokyo")
SITE_DIR = BASE_DIR / "site"

SESSION_LABELS = {"morning": "朝(寄り前)", "noon": "昼(前場終了後)", "evening": "夕(大引け後)"}

_CSS = """
:root { color-scheme: light;
  --surface: #f4f4f2; --card: #fcfcfb; --border: #e2e1dd;
  --text: #0b0b0b; --text-2: #52514e; --text-3: #8a8983;
  --accent: #2a78d6; --track: #e7e6e2;
  --pos: #d13c30; --neg: #2a78d6; --good: #008300;
  --chip-on: #dff0df; --chip-on-t: #005c00; --chip-off: #fbe3e1; --chip-off-t: #9c1f16;
  --chip-mid: #ecebe7; --chip-mid-t: #52514e; }
@media (prefers-color-scheme: dark) { :root {
  color-scheme: dark;
  --surface: #111110; --card: #1a1a19; --border: #333330;
  --text: #ffffff; --text-2: #c3c2b7; --text-3: #8a897f;
  --accent: #3987e5; --track: #2c2c2a;
  --pos: #e66767; --neg: #3987e5; --good: #35a835;
  --chip-on: #143b14; --chip-on-t: #8fd48f; --chip-off: #4a1512; --chip-off-t: #f0a09a;
  --chip-mid: #2c2c2a; --chip-mid-t: #c3c2b7; } }
* { box-sizing: border-box; margin: 0; }
body { background: var(--surface); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Noto Sans JP", Meiryo, sans-serif;
  font-size: 15px; line-height: 1.6; padding: 12px 12px 40px; }
main { max-width: 640px; margin: 0 auto; display: grid; gap: 12px; }
header { max-width: 640px; margin: 4px auto 12px; }
h1 { font-size: 20px; }
.ts { color: var(--text-3); font-size: 12px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px; }
.card h2 { font-size: 15px; margin-bottom: 8px; color: var(--text-2); }
.chip { display: inline-block; border-radius: 999px; padding: 2px 10px; font-size: 13px; font-weight: 600; }
.chip.on  { background: var(--chip-on);  color: var(--chip-on-t); }
.chip.off { background: var(--chip-off); color: var(--chip-off-t); }
.chip.mid { background: var(--chip-mid); color: var(--chip-mid-t); }
.advice { color: var(--text-2); font-size: 13px; margin-top: 6px; }
.tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
.tile { background: var(--surface); border-radius: 10px; padding: 8px 10px; }
.tile .k { font-size: 11px; color: var(--text-3); }
.tile .v { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
.bar { height: 10px; background: var(--track); border-radius: 5px; overflow: hidden; margin: 8px 0 4px; }
.bar > div { height: 100%; background: var(--accent); border-radius: 5px; }
.bar > div.done { background: var(--good); }
.pos { color: var(--pos); } .neg { color: var(--neg); }
.num { font-variant-numeric: tabular-nums; }
.sig { border-top: 1px solid var(--border); padding: 10px 0; }
.sig:first-of-type { border-top: none; padding-top: 4px; }
.sig .head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.sig .nm { font-weight: 700; }
.sig .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-top: 6px; font-size: 13px; }
.sig .grid .k { color: var(--text-3); font-size: 11px; display: block; }
.sig .qty { margin-top: 6px; font-size: 13px; color: var(--text-2); }
.tablewrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
table { border-collapse: collapse; width: 100%; font-size: 13px; white-space: nowrap; }
th { color: var(--text-3); font-weight: 600; text-align: left; padding: 4px 8px 4px 0; border-bottom: 1px solid var(--border); }
td { padding: 5px 8px 5px 0; border-bottom: 1px solid var(--border); }
tr:last-child td { border-bottom: none; }
td.r, th.r { text-align: right; }
.links a { display: inline-block; margin: 2px 8px 2px 0; font-size: 13px; }
a { color: var(--accent); text-decoration: none; }
.empty { color: var(--text-3); font-size: 13px; }
footer { max-width: 640px; margin: 16px auto 0; color: var(--text-3); font-size: 11px; }
"""


def _esc(v) -> str:
    return html.escape(str(v))


def _yen(v) -> str:
    return f"{v:,.0f}円"


def _signed(v, pct=False) -> str:
    """符号と色クラス付きの損益表示(±記号を必ず併記し色だけに頼らない)。"""
    cls = "pos" if v > 0 else ("neg" if v < 0 else "")
    txt = f"{v:+,.1f}%" if pct else f"{v:+,.0f}円"
    return f'<span class="{cls} num">{txt}</span>'


def _stance_chip(stance: str) -> str:
    cls = "on" if "リスクオン" in stance or "強気" in stance else (
        "off" if "リスクオフ" in stance or "弱気" in stance else "mid")
    return f'<span class="chip {cls}">{_esc(stance)}</span>'


def _market_section(market: dict) -> str:
    rows = []
    for tk, name in market["names"].items():
        s = market["snapshots"].get(tk)
        if not s:
            continue
        rows.append(
            f"<tr><td>{_esc(name)}</td>"
            f'<td class="r num">{s["close"]:,.1f}</td>'
            f'<td class="r">{_signed(s["change_pct"], pct=True)}</td></tr>'
        )
    reasons = "".join(f"<li>{_esc(r)}</li>" for r in market["reasons"])
    return f"""<section class="card">
<h2>市況 {_stance_chip(market["stance"])}</h2>
<div class="advice">{_esc(market["advice"])}</div>
<div class="tablewrap"><table>
<tr><th>指数/為替</th><th class="r">終値</th><th class="r">前日比</th></tr>
{"".join(rows)}
</table></div>
{f'<ul class="advice" style="padding-left:18px">{reasons}</ul>' if reasons else ""}
</section>"""


def _month_section(pf: dict) -> str:
    m = pf.get("month")
    if not pf.get("enabled") or not m:
        return ""
    goal = (_yen(m["profit_min"]) if m["profit_min"] == m["profit_max"]
            else f'{m["profit_min"]:,.0f}〜{m["profit_max"]:,.0f}円')
    pct = max(0.0, min(m["progress_pct"], 100.0))
    done = ' class="done"' if m["progress_pct"] >= 100 else ""
    pace = ("目標下限を達成済み 🎉" if m["remaining_to_min"] <= 0 else
            f'残り約{m["biz_days_left"]}営業日・1日あたり約{m["daily_pace"]:,.0f}円ペース')
    return f"""<section class="card">
<h2>月次目標の進捗({_esc(m["month"])})</h2>
<div class="bar"><div{done} style="width:{pct:.0f}%"></div></div>
<div class="advice num">達成率 {m["progress_pct"]:.0f}%(目標 {goal})— {_esc(pace)}</div>
<div class="tiles">
<div class="tile"><span class="k">今月の損益(実現+含み)</span><span class="v">{_signed(m["total"])}</span></div>
<div class="tile"><span class="k">運用資金</span><span class="v num">{_yen(m["capital"])}</span></div>
</div>
</section>"""


def _signals_section(review: dict, order_plans: list[dict]) -> str:
    buys = review["buy_signals"]
    if not buys:
        body = '<div class="empty">現在シグナルはありません。押し目・ブレイク待ちです。</div>'
    else:
        plan_by_code = {o["code"]: o for o in order_plans}
        items = []
        for b in buys:
            p = b["plan"]
            o = plan_by_code.get(b["code"])
            qty = (f'<div class="qty">目安: {o["shares"]}株 ≒ {_yen(o["amount"])}'
                   f'({_esc(o["order_type"])})</div>' if o else "")
            items.append(f"""<div class="sig">
<div class="head"><span class="nm">{_esc(b["code"])} {_esc(b["name"])}</span>
<span class="chip mid">{_esc(b["signal"]["type"])}</span></div>
<div class="grid">
<span><span class="k">買い</span><span class="num">{p["entry"]:,.1f}円</span></span>
<span><span class="k">利確 ({p["profit_target_pct"]:+.1f}%)</span><span class="num">{p["profit_target"]:,.1f}円</span></span>
<span><span class="k">損切 ({p["stop_loss_pct"]:+.1f}%)</span><span class="num">{p["stop_loss"]:,.1f}円</span></span>
</div>{qty}</div>""")
        body = "".join(items)
    return f'<section class="card"><h2>🔔 買いシグナル({len(buys)}件)</h2>{body}</section>'


def _portfolio_section(pf: dict) -> str:
    if not pf.get("enabled"):
        return ""
    rows = []
    for p in pf["positions"]:
        rows.append(
            f'<tr><td>{_esc(p["code"])} {_esc(p["name"])}</td>'
            f'<td class="r num">{p["entry_price"]:,.1f}</td>'
            f'<td class="r num">{p["shares"]}</td>'
            f'<td class="r num">{p["current"]:,.1f}</td>'
            f'<td class="r">{_signed(p["unrealized"])}<br>'
            f'{_signed(p["unrealized_pct"], pct=True)}</td></tr>'
        )
    table = (f"""<div class="tablewrap"><table>
<tr><th>銘柄</th><th class="r">取得</th><th class="r">株数</th><th class="r">現在値</th><th class="r">評価損益</th></tr>
{"".join(rows)}</table></div>""" if rows else
             '<div class="empty">保有ポジションはありません。</div>')
    closed = ""
    if pf["closed_recent"]:
        items = "".join(
            f'<li>{_esc(c["exit_date"])} {_esc(c["code"])} {_esc(c["name"])}: '
            f'{_esc(c["exit_reason"])} {_signed(c["pnl"])}</li>'
            for c in pf["closed_recent"])
        closed = f'<div class="advice">直近の決済:</div><ul class="advice" style="padding-left:18px">{items}</ul>'
    win = (f' / 勝率 {pf["wins"] / pf["closed_count"] * 100:.0f}%'
           f'({pf["wins"]}/{pf["closed_count"]})' if pf["closed_count"] else "")
    return f"""<section class="card">
<h2>ポートフォリオ(ペーパートレード)</h2>
<div class="tiles">
<div class="tile"><span class="k">総資産</span><span class="v num">{_yen(pf["total"])}</span></div>
<div class="tile"><span class="k">累計実現損益{_esc(win)}</span><span class="v">{_signed(pf["realized"])}</span></div>
</div>
<div style="height:8px"></div>
{table}
{closed}
<div class="advice">※ 終値ベースのシミュレーションです。実際の発注は行われません。</div>
</section>"""


def _watchlist_section(review: dict) -> str:
    wl = review["watchlist"]
    if not wl:
        return ""
    rows = []
    for w in wl:
        status = "🔔 シグナル" if w["status"] == "buy_signal" else "👀 観察中"
        score = f'{w["score"]:.0f}' if w["score"] is not None else "-"
        price = f'{w["price"]:,.1f}' if w["price"] is not None else "-"
        rows.append(
            f'<tr><td>{_esc(w["code"])} {_esc(w["name"])}</td>'
            f'<td class="r num">{score}</td><td class="r num">{price}</td>'
            f'<td>{status}</td><td class="r num">{w["days_watched"]}日</td></tr>'
        )
    return f"""<section class="card">
<h2>ウォッチリスト({len(wl)}銘柄)</h2>
<div class="tablewrap"><table>
<tr><th>銘柄</th><th class="r">スコア</th><th class="r">株価</th><th>状態</th><th class="r">観察</th></tr>
{"".join(rows)}</table></div>
</section>"""


def _sector_section(sector_info: dict) -> str:
    rows = []
    for e in sector_info["entries"]:
        label = ("📈 上昇見込み" if e["bonus"] > 0 else
                 ("📉 弱い" if e["total"] < 0 else "→ 中立"))
        rows.append(
            f'<tr><td>{_esc(e["group"])}</td>'
            f'<td class="r">{_signed(e["ret20"], pct=True)}</td>'
            f'<td class="r num">{e["total"]:+d}</td><td>{label}</td></tr>'
        )
    return f"""<section class="card">
<h2>セクターローテーション</h2>
<div class="tablewrap"><table>
<tr><th>セクター</th><th class="r">20日騰落</th><th class="r">総合</th><th>評価</th></tr>
{"".join(rows)}</table></div>
</section>"""


def _reports_section() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "Oharuno-heya/vibecodingapps")
    branch = os.environ.get("GITHUB_REF_NAME", "master")
    days = sorted((d for d in REPORTS_DIR.iterdir() if d.is_dir()), reverse=True)[:10]
    links = []
    for d in days:
        for s in ("morning", "noon", "evening"):
            if (d / f"{s}.md").exists():
                url = (f"https://github.com/{repo}/blob/{branch}/"
                       f"japan-stock-analyzer/reports/{d.name}/{s}.md")
                links.append(f'<a href="{_esc(url)}">{_esc(d.name)} '
                             f'{SESSION_LABELS[s].split("(")[0]}</a>')
    if not links:
        return ""
    return (f'<section class="card"><h2>過去の詳細レポート</h2>'
            f'<div class="links">{"".join(links)}</div></section>')


def build_site(session: str, market: dict, sector_info: dict, review: dict,
               order_plans: list[dict], portfolio: dict) -> str:
    now = datetime.now(JST)
    parts = [
        _market_section(market),
        _month_section(portfolio),
        _signals_section(review, order_plans),
        _portfolio_section(portfolio),
        _watchlist_section(review),
        _sector_section(sector_info),
        _reports_section(),
    ]
    page = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>日本株分析ダッシュボード</title>
<style>{_CSS}</style>
</head>
<body>
<header>
<h1>📈 日本株分析ダッシュボード</h1>
<div class="ts">更新: {now.strftime("%Y-%m-%d %H:%M JST")} — {SESSION_LABELS.get(session, session)}</div>
</header>
<main>
{"".join(p for p in parts if p)}
</main>
<footer>本ページはテクニカル指標に基づく自動分析であり、投資勧誘ではありません。投資判断はご自身の責任で行ってください。</footer>
</body>
</html>"""
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    path = SITE_DIR / "index.html"
    path.write_text(page, encoding="utf-8")
    return str(path)
