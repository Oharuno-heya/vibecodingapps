"""設定と共通パスの読み込み。"""
import json
import os
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "watchlist.db"


def load_config() -> dict:
    with open(BASE_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_universe() -> list[dict]:
    with open(DATA_DIR / "universe.json", encoding="utf-8") as f:
        return json.load(f)["stocks"]


def is_mock() -> bool:
    """ネットワークが使えない環境向けの合成データモード。"""
    return os.environ.get("JSA_MOCK", "") == "1"
