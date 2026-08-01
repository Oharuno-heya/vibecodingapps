#!/usr/bin/env python3
"""分析結果の通知。

- GitHub Issue(月ごとに1つ)へコメント投稿。オーナーを@メンションするため、
  GitHubの通知設定に応じてメール・スマホアプリのプッシュ通知が届く。
- DISCORD_WEBHOOK_URL 環境変数(GitHub Secrets)が設定されていればDiscordにも通知。

GitHub Actions から実行される想定(GITHUB_TOKEN / GITHUB_REPOSITORY を使用)。
通知対象セッションは config.yaml の notify.sessions で制御する。
"""
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyzer.config import REPORTS_DIR, load_config  # noqa: E402
from run_analysis import detect_session  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")


def _gh_api(path: str, token: str, data: dict | None = None):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=json.dumps(data).encode() if data is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "japan-stock-analyzer",
            "Content-Type": "application/json",
        },
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode() or "{}")


def main() -> int:
    session = os.environ.get("SESSION") or detect_session()
    cfg = load_config()
    allowed = cfg.get("notify", {}).get("sessions", ["morning", "noon"])
    if session not in allowed and os.environ.get("NOTIFY_FORCE") != "1":
        print(f"セッション {session} は通知対象外のためスキップ")
        return 0

    summary_path = REPORTS_DIR / "latest_summary.md"
    if not summary_path.exists():
        print("サマリーファイルがないためスキップ")
        return 0
    body = summary_path.read_text(encoding="utf-8")

    now = datetime.now(JST)
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    branch = os.environ.get("GITHUB_REF_NAME", "master")
    if repo:
        body += (f"\n[📄 詳細レポートを見る](https://github.com/{repo}/blob/{branch}/"
                 f"japan-stock-analyzer/reports/{now:%Y-%m-%d}/{session}.md)\n")

    ok = False

    token = os.environ.get("GITHUB_TOKEN")
    if token and repo:
        try:
            owner = repo.split("/")[0]
            title = f"📈 日本株分析通知 {now:%Y-%m}"
            issues = _gh_api(f"/repos/{repo}/issues?state=open&per_page=100", token)
            number = next((i["number"] for i in issues if i.get("title") == title), None)
            if number is None:
                created = _gh_api(f"/repos/{repo}/issues", token=token, data={
                    "title": title,
                    "body": f"@{owner} 毎営業日の朝8:30・昼12:30に自動分析の結果を"
                            "このIssueのコメントで通知します。\n"
                            "(通知を止めたい場合はこのIssueをUnsubscribe/Closeしてください)",
                })
                number = created["number"]
            _gh_api(f"/repos/{repo}/issues/{number}/comments", token=token,
                    data={"body": f"@{owner}\n\n{body}"})
            print(f"GitHub Issue #{number} に通知しました")
            ok = True
        except Exception as e:
            print(f"GitHub Issue通知に失敗: {e}")

    hook = os.environ.get("DISCORD_WEBHOOK_URL")
    if hook:
        try:
            for i in range(0, len(body), 1900):  # Discordの2000字制限対応
                req = urllib.request.Request(
                    hook,
                    data=json.dumps({"content": body[i:i + 1900]}).encode(),
                    headers={"Content-Type": "application/json",
                             "User-Agent": "japan-stock-analyzer"},
                )
                urllib.request.urlopen(req, timeout=30)
            print("Discordに通知しました")
            ok = True
        except Exception as e:
            print(f"Discord通知に失敗: {e}")

    if not ok:
        print("有効な通知先がありません(GITHUB_TOKEN / DISCORD_WEBHOOK_URL 未設定)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
