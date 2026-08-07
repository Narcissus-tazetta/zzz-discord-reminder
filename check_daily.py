"""
ZZZ(ゼンレスゾーンゼロ)のデイリー任務(委托)が完了しているかチェックし、
未完了なら Discord Webhook に通知するスクリプト。

GitHub Actions から毎日決まった時刻(cron)に実行される想定。
Cookie は GitHub Secrets 経由で環境変数として渡す。
"""

import asyncio
import os
import sys

import genshin
import requests

def get_env_or_exit(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"環境変数 {name} が設定されていません。GitHub Secrets を確認してください。", file=sys.stderr)
        sys.exit(1)
    return value


def send_discord_message(webhook_url: str, content: str) -> None:
    resp = requests.post(webhook_url, json={"content": content}, timeout=10)
    resp.raise_for_status()


async def check_daily_commission(cookies: dict, webhook_url: str) -> None:
    client = genshin.Client(cookies, lang="ja-jp", region=genshin.types.Region.OVERSEAS)

    # HoYoLAB に紐づくゲームアカウント一覧から ZZZ のアカウントを探す
    accounts = await client.get_game_accounts()
    zzz_account = next((a for a in accounts if a.game == genshin.types.Game.ZZZ), None)

    if zzz_account is None:
        send_discord_message(
            webhook_url,
            "⚠️ HoYoLABアカウントにZZZ(ゼンレスゾーンゼロ)のキャラクターが見つからなかった。"
            "Cookieやアカウント連携を確認して。",
        )
        sys.exit(1)

    notes = await client.get_zzz_notes(zzz_account.uid)

    engagement = notes.engagement  # デイリー任務(委托)の進捗ポイント
    battery = notes.battery_charge  # バッテリー(スタミナ)

    print(f"デイリー任務: {engagement.current}/{engagement.max}")
    print(f"バッテリー: {battery.current}/{battery.max}")

    if engagement.current < engagement.max:
        message = (
            f"⚠️ **ゼンゼロのデイリー任務がまだ終わってないよ**\n"
            f"デイリー任務(委托): {engagement.current}/{engagement.max}\n"
            f"バッテリー残量: {battery.current}/{battery.max}"
        )
        send_discord_message(webhook_url, message)
        print("未完了だったので通知を送った。")
    else:
        print("デイリー任務は完了済み。通知なし。")


async def main() -> None:
    ltuid_v2 = get_env_or_exit("LTUID_V2")
    ltoken_v2 = get_env_or_exit("LTOKEN_V2")
    webhook_url = get_env_or_exit("DISCORD_WEBHOOK_URL")

    cookies = {
        "ltuid_v2": ltuid_v2,
        "ltoken_v2": ltoken_v2,
    }

    # 任意: cookie_token_v2 があれば追加(一部エンドポイントで必要になる場合がある)
    cookie_token_v2 = os.environ.get("COOKIE_TOKEN_V2")
    if cookie_token_v2:
        cookies["cookie_token_v2"] = cookie_token_v2

    try:
        await check_daily_commission(cookies, webhook_url)
    except Exception as exc:
        print(f"予期しないエラーが発生した: {exc}", file=sys.stderr)
        send_discord_message(
            webhook_url,
            "⚠️ ZZZデイリーチェックの実行中にエラーが発生した。Cookie失効の可能性がある。\n"
            f"```{exc}```",
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
