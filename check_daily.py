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


async def check_daily_commission(cookies: dict, webhook_url: str, target_uid: int | None) -> None:
    client = genshin.Client(cookies, lang="ja-jp", region=genshin.types.Region.OVERSEAS)

    # HoYoLAB に紐づくゲームアカウント一覧から ZZZ のアカウントを探す
    accounts = await client.get_game_accounts()
    zzz_accounts = [a for a in accounts if a.game == genshin.types.Game.ZZZ]

    if target_uid is not None:
        # UIDが明示されている場合はそれを優先(1つのHoYoLABアカウントに
        # 複数のZZZキャラクターが紐づいていることがあるため)
        zzz_account = next((a for a in zzz_accounts if a.uid == target_uid), None)
        if zzz_account is None:
            send_discord_message(
                webhook_url,
                f"⚠️ 指定されたUID({target_uid})のZZZキャラクターが見つからなかった。"
                "ZZZ_TARGET_UID の設定かCookieを確認して。",
            )
            sys.exit(1)
    else:
        zzz_account = zzz_accounts[0] if zzz_accounts else None
        if zzz_account is None:
            send_discord_message(
                webhook_url,
                "⚠️ HoYoLABアカウントにZZZ(ゼンレスゾーンゼロ)のキャラクターが見つからなかった。"
                "Cookieやアカウント連携を確認して。",
            )
            sys.exit(1)
        if len(zzz_accounts) > 1:
            print(
                f"[WARN] ZZZアカウントが複数({len(zzz_accounts)}件)見つかったが、"
                f"ZZZ_TARGET_UIDが未設定のため先頭(uid={zzz_account.uid})を使用する。"
            )

    notes = await client.get_zzz_notes(zzz_account.uid)

    engagement = notes.engagement  # デイリー任務(委托)の進捗ポイント

    print(f"デイリー任務: {engagement.current}/{engagement.max}")

    if engagement.current < engagement.max:
        message = (
            f"📋 **本日のデイリー任務が未完了です**\n"
            f"デイリー任務(委托): {engagement.current}/{engagement.max}"
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

    # 任意: HoYoLABアカウントに複数のZZZキャラクターが紐づいている場合に
    # チェック対象を固定するためのUID(未設定なら先頭のアカウントを使う)
    target_uid_str = os.environ.get("ZZZ_TARGET_UID")
    target_uid = int(target_uid_str) if target_uid_str else None

    try:
        await check_daily_commission(cookies, webhook_url, target_uid)
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
