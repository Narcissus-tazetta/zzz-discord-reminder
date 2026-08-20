"""
ZZZ(ゼンレスゾーンゼロ)の未消化コンテンツをチェックし、
未完了なら Discord Webhook に通知するスクリプト。

チェック対象は環境変数 ZZZ_CHECK_MODE で切り替える:
  - daily  : デイリー任務(委托)         … 毎日 23:30 JST・1:00 JST 想定
             ついでに式輿防衛戦・危局強襲戦のシーズン未着手チェックも行う
             (リセットまで残り3日・1日を切ったタイミングで通知)
  - weekly : 0号ホロウの懸賞依頼(週間)  … 日曜 23:00 JST 想定(月曜5:00にリセット)
  - both   : 両方

GitHub Actions から cron で実行される想定。
Cookie は GitHub Secrets 経由で環境変数として渡す。
"""

import asyncio
import datetime
import os
import sys

import genshin
import requests

JST = datetime.timezone(datetime.timedelta(hours=9), "JST")

VALID_MODES = ("daily", "weekly", "both")

# 式輿防衛戦・危局強襲戦はリセット周期がゲーム側の運用次第(必ずしも毎週固定ではない)
# なので、特定の曜日cronに頼らず「リセットまで残りこのくらいになったら通知する」
# という形で判定する。毎日23:30JST・1:00JSTに実行されるdailyチェックに相乗りさせ、
# 各チェックポイント(3日前・1日前)を1回ずつ確実に捕まえられるように、
# cronの実行間隔(最大約22.5時間)より広い26時間の猶予を持たせている。
CHALLENGE_REMINDER_CHECKPOINTS: tuple[tuple[datetime.timedelta, str], ...] = (
    (datetime.timedelta(days=3), "3日前"),
    (datetime.timedelta(days=1), "1日前"),
)
CHALLENGE_REMINDER_MARGIN = datetime.timedelta(hours=26)


def get_env_or_exit(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"環境変数 {name} が設定されていません。GitHub Secrets を確認してください。", file=sys.stderr)
        sys.exit(1)
    return value


def send_discord_message(webhook_url: str, content: str) -> None:
    resp = requests.post(webhook_url, json={"content": content}, timeout=10)
    resp.raise_for_status()


def format_timedelta(td: datetime.timedelta) -> str:
    """timedelta を「3時間15分」のような日本語表記にする。"""
    total_minutes = max(int(td.total_seconds()) // 60, 0)
    hours, minutes = divmod(total_minutes, 60)
    days, hours = divmod(hours, 24)

    if days:
        return f"{days}日{hours}時間{minutes}分"
    if hours:
        return f"{hours}時間{minutes}分"
    return f"{minutes}分"


async def resolve_zzz_account(
    client: genshin.Client, webhook_url: str, target_uid: int | None
) -> genshin.models.GenshinAccount:
    """HoYoLAB に紐づくゲームアカウント一覧から、チェック対象の ZZZ アカウントを特定する。"""
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
        return zzz_account

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
    return zzz_account


def build_daily_message(notes) -> str | None:
    """デイリー任務(委托)が未完了ならメッセージを返す。完了済みなら None。"""
    engagement = notes.engagement  # デイリー任務(委托)の進捗ポイント

    print(f"デイリー任務: {engagement.current}/{engagement.max}")

    if engagement.current >= engagement.max:
        print("デイリー任務は完了済み。通知なし。")
        return None

    return (
        f"📋 **本日のデイリー任務が未完了です**\n"
        f"デイリー任務(委托): {engagement.current}/{engagement.max}"
    )


def build_weekly_message(notes) -> str | None:
    """0号ホロウの懸賞依頼(週間)が未完了ならメッセージを返す。完了済みなら None。

    懸賞依頼の進捗はサーバー側で集計されるため、0号ホロウを自分で周回しても
    特派調査などの代替手段で消化しても同じカウンタに加算される。
    このスクリプトは達成手段を区別せず、進捗が上限に達しているかだけを見る。
    """
    bounty = notes.hollow_zero.bounty_commission

    if bounty is None:
        # 取得できない = 静かに通知が止まる状態なので、気づけるように警告を送る
        print("[WARN] 懸賞依頼(bounty_commission)の情報がAPIから取得できなかった。", file=sys.stderr)
        return (
            "⚠️ 0号ホロウの懸賞依頼の進捗がHoYoLAB APIから取得できなかった。\n"
            "ゲーム側の仕様変更か、genshin.py の更新が必要かもしれない。"
        )

    if bounty.unlock is False:
        print("0号ホロウ(懸賞依頼)が未解放。通知なし。")
        return None

    print(f"懸賞依頼: {bounty.cur_completed}/{bounty.total}")

    if bounty.cur_completed >= bounty.total:
        print("懸賞依頼は完了済み。通知なし。")
        return None

    reset_at = bounty.reset_datetime.astimezone(JST)
    return (
        f"🕳️ **0号ホロウの週間任務(懸賞依頼)が未完了です**\n"
        f"懸賞依頼: {bounty.cur_completed}/{bounty.total}\n"
        f"リセットまで: あと{format_timedelta(bounty.refresh_time)}"
        f"({reset_at:%m/%d %H:%M} JST)"
    )


def _reminder_checkpoint(
    end_time: datetime.datetime | None,
) -> tuple[datetime.timedelta, str] | None:
    """end_timeまでの残り時間が、リマインドのチェックポイント(3日前・1日前)の
    いずれかに該当すれば (残り時間, ラベル) を返す。該当しなければNone。
    """
    if end_time is None:
        return None
    remaining = end_time.astimezone(JST) - datetime.datetime.now(JST)
    for checkpoint, label in CHALLENGE_REMINDER_CHECKPOINTS:
        lower = max(checkpoint - CHALLENGE_REMINDER_MARGIN, datetime.timedelta(0))
        if lower <= remaining <= checkpoint:
            return remaining, label
    return None


def _shiyu_attempted_this_season(shiyu) -> bool:
    """今シーズン式輿防衛戦に挑戦済みかどうかを判定する。

    get_shiyu_defense() は API のレスポンス形式次第で ShiyuDefenseV1
    (has_data フィールドあり) と ShiyuDefenseV2 (has_data が無く、
    代わりに brief_info の有無で判断する) のどちらかを返すため、
    両対応させる必要がある。
    """
    has_data = getattr(shiyu, "has_data", None)
    if has_data is not None:
        return has_data
    return getattr(shiyu, "brief_info", None) is not None


async def build_shiyu_message(client: genshin.Client, uid: int) -> str | None:
    """式輿防衛戦(Shiyu Defense)がシーズン内で未着手かつリセットが近ければメッセージを返す。

    genshin.pyにはデイリー任務のような単純なcurrent/maxカウンタが無いため、
    ここでは「このシーズン一度も挑戦していないか」だけを判定する
    (部分的にしかクリアしていない場合は検知できない)。
    """
    try:
        shiyu = await client.get_shiyu_defense(uid)
    except Exception as exc:
        print(f"[WARN] 式輿防衛戦の情報取得に失敗した: {exc}", file=sys.stderr)
        return None

    checkpoint = _reminder_checkpoint(shiyu.end_time)
    if checkpoint is None:
        return None
    remaining, label = checkpoint

    if _shiyu_attempted_this_season(shiyu):
        print("式輿防衛戦は今シーズン挑戦済み。通知なし。")
        return None

    reset_at = shiyu.end_time.astimezone(JST)
    return (
        f"🏯 **式輿防衛戦が今シーズン未挑戦です(リセット{label})**\n"
        f"リセットまで: あと{format_timedelta(remaining)}({reset_at:%m/%d %H:%M} JST)"
    )


async def build_assault_message(client: genshin.Client, uid: int) -> str | None:
    """危局強襲戦(Deadly Assault)がシーズン内で未着手かつリセットが近ければメッセージを返す。

    build_shiyu_message同様、判定は「今シーズン一度も挑戦していないか」のみ。
    """
    try:
        assault = await client.get_deadly_assault(uid)
    except Exception as exc:
        print(f"[WARN] 危局強襲戦の情報取得に失敗した: {exc}", file=sys.stderr)
        return None

    checkpoint = _reminder_checkpoint(assault.end_time)
    if checkpoint is None:
        return None
    remaining, label = checkpoint

    if assault.has_data:
        print("危局強襲戦は今シーズン挑戦済み。通知なし。")
        return None

    reset_at = assault.end_time.astimezone(JST)
    return (
        f"⚔️ **危局強襲戦が今シーズン未挑戦です(リセット{label})**\n"
        f"リセットまで: あと{format_timedelta(remaining)}({reset_at:%m/%d %H:%M} JST)"
    )


async def run_checks(cookies: dict, webhook_url: str, target_uid: int | None, mode: str) -> None:
    client = genshin.Client(cookies, lang="ja-jp", region=genshin.types.Region.OVERSEAS)

    zzz_account = await resolve_zzz_account(client, webhook_url, target_uid)
    notes = await client.get_zzz_notes(zzz_account.uid)

    messages: list[str] = []
    if mode in ("daily", "both"):
        messages.append(build_daily_message(notes))
        messages.append(await build_shiyu_message(client, zzz_account.uid))
        messages.append(await build_assault_message(client, zzz_account.uid))
    if mode in ("weekly", "both"):
        messages.append(build_weekly_message(notes))

    messages = [m for m in messages if m]
    if not messages:
        print("通知すべきものはなかった。")
        return

    send_discord_message(webhook_url, "\n\n".join(messages))
    print(f"{len(messages)}件の通知を送った。")


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

    mode = (os.environ.get("ZZZ_CHECK_MODE") or "daily").strip().lower()
    if mode not in VALID_MODES:
        print(
            f"ZZZ_CHECK_MODE の値が不正です: {mode!r}(有効な値: {', '.join(VALID_MODES)})",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"チェック対象: {mode}")

    try:
        await run_checks(cookies, webhook_url, target_uid, mode)
    except Exception as exc:
        print(f"予期しないエラーが発生した: {exc}", file=sys.stderr)
        send_discord_message(
            webhook_url,
            f"⚠️ ZZZのチェック({mode})の実行中にエラーが発生した。Cookie失効の可能性がある。\n"
            f"```{exc}```",
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
