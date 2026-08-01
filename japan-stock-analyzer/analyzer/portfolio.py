"""ペーパートレード(自動売買シミュレーション)。

買いシグナルに従って仮想的に売買を執行し、ポジションと損益をSQLiteで管理する。
約定は分析時点の終値ベース。実際の証券口座への発注は行わない
(楽天証券・SBI証券に個人向け発注APIが存在しないため)。

決済ルール:
- 損切りライン到達 → 売却
- 利確ライン到達 → 売却
- 75日線割れ(トレンド崩れ)→ 売却
- 保有期間上限(既定45日)→ 売却
"""
import sqlite3
from datetime import date

from .config import DB_PATH
from .data import fetch_history
from .targets import biz_days_left_in_month, size_position, trading_params


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT,
            status TEXT NOT NULL DEFAULT 'open',  -- open / closed
            entry_date TEXT,
            entry_price REAL,
            shares INTEGER,
            stop_loss REAL,
            profit_target REAL,
            exit_date TEXT,
            exit_price REAL,
            exit_reason TEXT,
            pnl REAL,
            mode TEXT DEFAULT 'paper'
        );
        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cash REAL NOT NULL,
            initial_capital REAL NOT NULL,
            base_capital REAL
        );
        """
    )
    try:  # 旧スキーマからの移行
        conn.execute("ALTER TABLE account ADD COLUMN base_capital REAL")
    except sqlite3.OperationalError:
        pass
    return conn


def _price_of(code: str, results_by_code: dict) -> float | None:
    res = results_by_code.get(code)
    if res is not None:
        return float(res["close"])
    df = fetch_history(f"{code}.T", period="3mo")
    if df is not None and len(df) > 0:
        return float(df["Close"].iloc[-1])
    return None


def execute_trades(review: dict, results_by_code: dict, cfg: dict, session: str) -> dict:
    """保有ポジションの決済判定と、買いシグナルに基づく新規買付を執行する。"""
    t = cfg["trading"]
    if t.get("mode") != "paper":
        return {"enabled": False}

    params = trading_params(cfg)
    capital = params["capital"]
    today = date.today().isoformat()
    events = []
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO account (id, cash, initial_capital, base_capital) "
            "VALUES (1, ?, ?, ?)",
            (capital, capital, capital),
        )
        acct = conn.execute("SELECT * FROM account WHERE id=1").fetchone()
        cash = float(acct["cash"])
        base = float(acct["base_capital"] if acct["base_capital"] is not None
                     else acct["initial_capital"])
        # 月次目標の運用資金が変わったら入出金として現金を調整
        if abs(capital - base) >= 1:
            cash += capital - base
            conn.execute("UPDATE account SET base_capital=? WHERE id=1", (capital,))
            events.append(f"資金調整 {capital - base:+,.0f}円(今月の運用資金 {capital:,.0f}円)")

        # --- 決済判定 ---
        open_rows = conn.execute("SELECT * FROM positions WHERE status='open'").fetchall()
        held = {r["code"] for r in open_rows}
        for r in open_rows:
            price = _price_of(r["code"], results_by_code)
            if price is None:
                continue
            reason = None
            if price <= r["stop_loss"]:
                reason = "損切り"
            elif price >= r["profit_target"]:
                reason = "利益確定"
            else:
                res = results_by_code.get(r["code"])
                lt = (res["plan"].get("long_term_exit") if res else None)
                if lt and price < lt:
                    reason = "トレンド崩れ(75日線割れ)"
                elif (date.today() - date.fromisoformat(r["entry_date"])).days \
                        > t.get("max_hold_days", 45):
                    reason = "保有期間上限"
            if reason:
                pnl = (price - r["entry_price"]) * r["shares"]
                conn.execute(
                    "UPDATE positions SET status='closed', exit_date=?, exit_price=?, "
                    "exit_reason=?, pnl=? WHERE id=?",
                    (today, price, reason, pnl, r["id"]),
                )
                cash += price * r["shares"]
                held.discard(r["code"])
                events.append(
                    f"売却 {r['code']} {r['name']} {r['shares']}株 @{price:,.1f}円 "
                    f"({reason} / 損益 {pnl:+,.0f}円)"
                )

        # --- 新規買付(スコアの高い買いシグナルから) ---
        n_open = len(held)
        signals = sorted(review["buy_signals"], key=lambda x: x["score"] or 0, reverse=True)
        for b in signals:
            if n_open >= params["max_positions"]:
                break
            if b["code"] in held:
                continue
            plan = b["plan"]
            if not plan.get("actionable"):
                continue
            price = float(b.get("price") or plan["entry"])
            shares = size_position(price, min(params["budget_per_position"], cash), params)
            if shares <= 0:
                continue
            conn.execute(
                "INSERT INTO positions (code, name, status, entry_date, entry_price, "
                "shares, stop_loss, profit_target, mode) "
                "VALUES (?, ?, 'open', ?, ?, ?, ?, ?, 'paper')",
                (b["code"], b["name"], today, price, shares,
                 plan["stop_loss"], plan["profit_target"]),
            )
            cash -= shares * price
            held.add(b["code"])
            n_open += 1
            events.append(
                f"買付 {b['code']} {b['name']} {shares}株 @{price:,.1f}円 "
                f"({b['signal']['type']} / 損切 {plan['stop_loss']:,.1f} "
                f"/ 利確 {plan['profit_target']:,.1f})"
            )

        conn.execute("UPDATE account SET cash=? WHERE id=1", (cash,))

        # --- サマリ ---
        positions = []
        pos_value = 0.0
        for r in conn.execute(
                "SELECT * FROM positions WHERE status='open' ORDER BY entry_date").fetchall():
            price = _price_of(r["code"], results_by_code) or float(r["entry_price"])
            value = price * r["shares"]
            pos_value += value
            positions.append({
                "code": r["code"], "name": r["name"], "entry_date": r["entry_date"],
                "entry_price": r["entry_price"], "shares": r["shares"],
                "current": price, "value": value,
                "unrealized": (price - r["entry_price"]) * r["shares"],
                "unrealized_pct": (price / r["entry_price"] - 1) * 100,
                "stop_loss": r["stop_loss"], "profit_target": r["profit_target"],
            })
        closed = [dict(r) for r in conn.execute(
            "SELECT * FROM positions WHERE status='closed' "
            "ORDER BY exit_date DESC, id DESC LIMIT 5").fetchall()]
        agg = conn.execute(
            "SELECT COALESCE(SUM(pnl),0) s, COUNT(*) n, "
            "SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) w "
            "FROM positions WHERE status='closed'").fetchone()
        month_realized = float(conn.execute(
            "SELECT COALESCE(SUM(pnl),0) FROM positions "
            "WHERE status='closed' AND exit_date LIKE ?",
            (today[:7] + "%",)).fetchone()[0])

    unrealized = sum(p["unrealized"] for p in positions)
    month = None
    tgt = params["target"]
    if tgt:
        month_total = month_realized + unrealized
        remaining = max(float(tgt["profit_min"]) - month_total, 0)
        days_left = biz_days_left_in_month()
        month = {
            "month": tgt["month"],
            "is_current": params["target_is_current_month"],
            "capital": capital,
            "profit_min": float(tgt["profit_min"]),
            "profit_max": float(tgt["profit_max"]),
            "realized": month_realized,
            "unrealized": unrealized,
            "total": month_total,
            "progress_pct": month_total / float(tgt["profit_min"]) * 100,
            "biz_days_left": days_left,
            "remaining_to_min": remaining,
            "daily_pace": remaining / days_left if days_left > 0 else remaining,
        }

    return {
        "enabled": True,
        "cash": cash,
        "pos_value": pos_value,
        "total": cash + pos_value,
        "capital": capital,
        "fractional": params["fractional"],
        "realized": float(agg["s"]),
        "closed_count": int(agg["n"]),
        "wins": int(agg["w"] or 0),
        "positions": positions,
        "closed_recent": closed,
        "events": events,
        "month": month,
    }
