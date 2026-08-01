"""月次目標(運用資金・利益目標)の管理と、そこから導く売買パラメータ。

config.yaml の targets.monthly を編集すれば目標はいつでも変更できる。
"""
from datetime import date

import pandas as pd


def current_target(cfg: dict, today: date | None = None) -> tuple[dict | None, bool]:
    """今月の目標を返す。(target, 当月ちょうどか)。

    当月の設定がない場合は直近の将来月(先行適用)、それもなければ最後の月を返す。
    """
    today = today or date.today()
    ym = today.strftime("%Y-%m")
    monthly = sorted(cfg.get("targets", {}).get("monthly", []), key=lambda t: t["month"])
    if not monthly:
        return None, False
    for t in monthly:
        if t["month"] == ym:
            return t, True
    upcoming = [t for t in monthly if t["month"] > ym]
    return (upcoming[0], False) if upcoming else (monthly[-1], False)


def trading_params(cfg: dict, today: date | None = None) -> dict:
    """月次目標から運用資金・ポジションサイズを導出する。"""
    t = cfg["trading"]
    target, exact = current_target(cfg, today)
    max_pos = int(cfg.get("targets", {}).get("max_positions", 2))
    capital = float(target["capital"]) if target else float(t.get("initial_capital", 200000))
    return {
        "target": target,
        "target_is_current_month": exact,
        "capital": capital,
        "max_positions": max_pos,
        "budget_per_position": capital / max_pos,
        "fractional": bool(t.get("allow_fractional", True)),
        "lot_size": int(t.get("lot_size", 100)),
    }


def size_position(price: float, budget: float, params: dict) -> int:
    """予算内で買える株数。単元未満株(かぶミニ/S株)前提なら1株単位。"""
    if price <= 0 or budget <= 0:
        return 0
    if params["fractional"]:
        return int(budget // price)
    lot = params["lot_size"]
    return int(budget // (price * lot)) * lot


def biz_days_left_in_month(today: date | None = None) -> int:
    """今日を含む今月の残り営業日数(祝日は考慮しない概算)。"""
    today = today or date.today()
    end = pd.Timestamp(today).to_period("M").end_time.normalize()
    return len(pd.bdate_range(pd.Timestamp(today), end))
