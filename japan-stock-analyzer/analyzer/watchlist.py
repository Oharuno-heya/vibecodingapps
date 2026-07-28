"""ウォッチリストの永続化(SQLite)と観察・削除ロジック。"""
import json
import sqlite3
from datetime import date, datetime

from .config import DB_PATH


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS watchlist (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            sector TEXT,
            added_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'watching',  -- watching / buy_signal
            score REAL,
            last_price REAL,
            plan_json TEXT,
            low_score_streak INTEGER DEFAULT 0,
            streak_date TEXT,
            last_review TEXT
        );
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            ts TEXT NOT NULL,
            session TEXT,
            price REAL,
            score REAL,
            signal TEXT,
            action TEXT NOT NULL  -- added / reviewed / buy_signal / removed
        );
        """
    )
    try:  # 旧スキーマからの移行
        conn.execute("ALTER TABLE watchlist ADD COLUMN streak_date TEXT")
    except sqlite3.OperationalError:
        pass
    return conn


def get_watchlist() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM watchlist ORDER BY score DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["plan"] = json.loads(d.pop("plan_json") or "{}")
        out.append(d)
    return out


def _log(conn, code: str, session: str, action: str, price=None, score=None, signal=None):
    conn.execute(
        "INSERT INTO history (code, ts, session, price, score, signal, action) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (code, datetime.now().isoformat(timespec="seconds"), session, price, score, signal, action),
    )


def add_candidates(candidates: list[dict], cfg: dict, session: str) -> list[dict]:
    """スクリーニング候補をウォッチリストに追加(既存はスキップ)。追加分を返す。"""
    max_size = cfg["watchlist"]["max_size"]
    added = []
    with _conn() as conn:
        existing = {r["code"] for r in conn.execute("SELECT code FROM watchlist")}
        count = len(existing)
        for c in candidates:
            if c["code"] in existing or count >= max_size:
                continue
            conn.execute(
                "INSERT INTO watchlist (code, name, sector, added_date, status, score, "
                "last_price, plan_json, last_review) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    c["code"], c["name"], c["sector"], date.today().isoformat(),
                    "buy_signal" if c["signal"] else "watching",
                    c["score"], c["close"], json.dumps(c["plan"], ensure_ascii=False),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            _log(conn, c["code"], session, "added", c["close"], c["score"],
                 c["signal"]["type"] if c["signal"] else None)
            added.append(c)
            count += 1
    return added


def review_watchlist(results_by_code: dict[str, dict], cfg: dict, session: str) -> dict:
    """ウォッチリスト全銘柄を再評価し、更新・削除を行う。

    results_by_code: スクリーニング結果(code -> 結果dict)。フィルタ落ちで
    結果がない銘柄は None 扱い(スコア悪化とみなす)。
    """
    wl_cfg = cfg["watchlist"]
    today = date.today().isoformat()
    updated, removed, buy_signals = [], [], []
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM watchlist").fetchall()
        for row in rows:
            code = row["code"]
            res = results_by_code.get(code)
            days_watched = (date.today() - date.fromisoformat(row["added_date"])).days

            if res is None:
                low = True  # データ取得不可 or ハードフィルタ落ち
                score, price, signal = None, row["last_price"], None
            else:
                score, price, signal = res["score"], res["close"], res["signal"]
                # 低スコア or ファンダ基準未達(時価総額・自己資本比率)は低調扱い
                low = score < wl_cfg["remove_score"] or res.get("fund_ok") is False

            # 低調カウントは1日1回のみ加算(1日3回実行のため)
            streak_date = row["streak_date"]
            if low:
                if streak_date == today:
                    streak = row["low_score_streak"]
                else:
                    streak = row["low_score_streak"] + 1
                    streak_date = today
            else:
                streak, streak_date = 0, None

            # 削除判定: 低調が連続 or 観察期間超過
            reason = None
            if streak >= wl_cfg["low_score_streak"]:
                reason = (f"低スコア・ファンダ基準未達・フィルタ落ちのいずれかが"
                          f"{streak}日連続")
            elif days_watched > wl_cfg["max_watch_days"]:
                reason = f"観察{days_watched}日でシグナル不発(上限{wl_cfg['max_watch_days']}日)"

            if reason:
                conn.execute("DELETE FROM watchlist WHERE code = ?", (code,))
                _log(conn, code, session, "removed", price, score)
                removed.append({"code": code, "name": row["name"], "reason": reason})
                continue

            status = "buy_signal" if signal else "watching"
            plan_json = json.dumps(res["plan"], ensure_ascii=False) if res else row["plan_json"]
            conn.execute(
                "UPDATE watchlist SET status=?, score=?, last_price=?, plan_json=?, "
                "low_score_streak=?, streak_date=?, last_review=? WHERE code=?",
                (status, score if score is not None else row["score"], price, plan_json,
                 streak, streak_date, datetime.now().isoformat(timespec="seconds"), code),
            )
            _log(conn, code, session, "buy_signal" if signal else "reviewed",
                 price, score, signal["type"] if signal else None)
            item = {"code": code, "name": row["name"], "sector": row["sector"],
                    "added_date": row["added_date"], "days_watched": days_watched,
                    "score": score, "price": price, "status": status,
                    "signal": signal, "plan": res["plan"] if res else json.loads(row["plan_json"] or "{}"),
                    "low_score_streak": streak}
            updated.append(item)
            if signal:
                buy_signals.append(item)

    updated.sort(key=lambda x: (x["score"] is not None, x["score"]), reverse=True)
    return {"watchlist": updated, "removed": removed, "buy_signals": buy_signals}
