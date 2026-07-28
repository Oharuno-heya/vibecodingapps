"""セクターローテーション分析。

セクター(グループ)ごとの株価モメンタムと、マクロ経済要因(円相場・原油・
米金利・VIX・SOX)によるルールベースの評価を合成し、「上昇見込みセクター」を
判定してスクリーニングのスコアに反映する。
"""
from collections import defaultdict

# universe.json の細かい sector を、ローテーション分析用のグループに集約
SECTOR_GROUPS = {
    "自動車": "自動車・輸送機器", "自動車部品": "自動車・輸送機器", "輸送用機器": "自動車・輸送機器",
    "電気機器": "電機・精密", "電子部品": "電機・精密", "精密機器": "電機・精密",
    "半導体製造装置": "半導体", "半導体": "半導体",
    "機械": "機械・重工", "重工": "機械・重工",
    "化学": "素材・化学", "化学・日用品": "素材・化学", "ゴム製品": "素材・化学",
    "鉄鋼": "素材・化学", "非鉄金属": "素材・化学",
    "医薬品": "医薬品・医療", "医療機器": "医薬品・医療",
    "化粧品": "消費・小売", "小売": "消費・小売", "小売・EC": "消費・小売",
    "食品": "食品",
    "商社": "商社",
    "銀行": "金融", "保険": "金融", "証券": "金融", "その他金融": "金融",
    "通信": "通信・IT", "情報通信": "通信・IT", "投資・通信": "通信・IT",
    "サービス": "サービス", "広告": "サービス",
    "ゲーム": "ゲーム・エンタメ", "ゲーム・玩具": "ゲーム・エンタメ",
    "空運": "運輸", "陸運": "運輸", "海運": "運輸",
    "不動産": "不動産・建設", "建設": "不動産・建設", "建設・住宅": "不動産・建設",
    "石油": "エネルギー", "鉱業": "エネルギー",
    "電力": "公益", "ガス": "公益",
}

EXPORTERS = ["自動車・輸送機器", "電機・精密", "機械・重工", "半導体"]
DOMESTIC = ["食品", "消費・小売", "サービス", "公益"]
DEFENSIVE = ["食品", "医薬品・医療", "公益", "通信・IT"]
CYCLICAL = ["半導体", "機械・重工", "素材・化学", "運輸"]


def group_of(sector: str) -> str:
    return SECTOR_GROUPS.get(sector, sector)


def _macro_tilts(snaps: dict) -> tuple[dict, dict]:
    """マクロ指標からグループ別の評価点(±)と根拠メモを作る。"""
    tilt: dict = defaultdict(int)
    notes: dict = defaultdict(list)

    def add(groups, pts, note):
        for g in groups:
            tilt[g] += pts
            notes[g].append(note)

    jpy = snaps.get("JPY=X")
    if jpy and jpy.get("change_5d_pct") is not None:
        ch = jpy["change_5d_pct"]
        if ch > 1.0:
            add(EXPORTERS, 1, "円安が輸出セクターの追い風")
        elif ch < -1.0:
            add(EXPORTERS, -1, "円高が輸出セクターの逆風")
            add(DOMESTIC, 1, "円高で内需セクターが相対優位")

    oil = snaps.get("CL=F")
    if oil and oil.get("change_5d_pct") is not None:
        ch = oil["change_5d_pct"]
        if ch > 3.0:
            add(["エネルギー", "商社"], 1, "原油高メリット")
            add(["運輸", "公益"], -1, "燃料コスト増が逆風")
        elif ch < -3.0:
            add(["エネルギー", "商社"], -1, "原油安が逆風")
            add(["運輸", "公益"], 1, "燃料コスト減がメリット")

    tnx = snaps.get("^TNX")
    if tnx and tnx.get("change_5d_pct") is not None:
        ch = tnx["change_5d_pct"]
        if ch > 4.0:
            add(["金融"], 1, "米金利上昇で利ざや改善期待")
            add(["不動産・建設"], -1, "金利上昇が逆風")
        elif ch < -4.0:
            add(["金融"], -1, "米金利低下が逆風")
            add(["不動産・建設"], 1, "金利低下がメリット")

    vix = snaps.get("^VIX")
    if vix and vix.get("close") is not None and vix["close"] >= 25:
        add(DEFENSIVE, 1, "リスクオフ局面でディフェンシブ選好")
        add(CYCLICAL, -1, "リスクオフ局面で景気敏感が売られやすい")

    sox = snaps.get("^SOX")
    if sox and sox.get("change_5d_pct") is not None:
        ch = sox["change_5d_pct"]
        if ch > 3.0:
            add(["半導体", "電機・精密"], 1, "SOX指数の上昇が追い風")
        elif ch < -3.0:
            add(["半導体", "電機・精密"], -1, "SOX指数の下落が逆風")

    return tilt, notes


def analyze_sectors(histories: dict, meta: dict, snaps: dict, cfg: dict) -> dict:
    """グループ別のモメンタム+マクロ評価を集計し、加点マップを返す。"""
    rets: dict = defaultdict(list)
    all_r5, all_r20 = [], []
    for code, df in histories.items():
        c = df["Close"]
        if len(c) < 21 or code not in meta:
            continue
        r5 = float(c.iloc[-1] / c.iloc[-6] - 1) * 100
        r20 = float(c.iloc[-1] / c.iloc[-21] - 1) * 100
        rets[group_of(meta[code]["sector"])].append((r5, r20))
        all_r5.append(r5)
        all_r20.append(r20)

    u5 = sum(all_r5) / len(all_r5) if all_r5 else 0.0
    u20 = sum(all_r20) / len(all_r20) if all_r20 else 0.0
    tilts, notes = _macro_tilts(snaps)

    entries = []
    for g, pairs in rets.items():
        g5 = sum(p[0] for p in pairs) / len(pairs)
        g20 = sum(p[1] for p in pairs) / len(pairs)
        mom = 0
        d20, d5 = g20 - u20, g5 - u5
        if d20 > 3:
            mom += 2
        elif d20 > 1:
            mom += 1
        elif d20 < -3:
            mom -= 2
        elif d20 < -1:
            mom -= 1
        if d5 > 1.5:
            mom += 1
        elif d5 < -1.5:
            mom -= 1
        total = mom + tilts.get(g, 0)
        entries.append({
            "group": g, "ret5": round(g5, 2), "ret20": round(g20, 2),
            "momentum": mom, "macro": tilts.get(g, 0), "total": total,
            "notes": notes.get(g, []), "count": len(pairs),
        })

    entries.sort(key=lambda x: (x["total"], x["ret20"]), reverse=True)

    s = cfg["sector"]
    bonus_by_group = {}
    for rank, e in enumerate(entries):
        if e["total"] < 0:
            bonus = 0
        elif rank < 3:
            bonus = s["bonus_top"]
        elif rank < 6:
            bonus = s["bonus_second"]
        else:
            bonus = 0
        e["bonus"] = bonus
        bonus_by_group[e["group"]] = bonus

    return {
        "entries": entries,
        "bonus_by_group": bonus_by_group,
        "totals": {e["group"]: e["total"] for e in entries},
        "universe_ret20": round(u20, 2),
    }
