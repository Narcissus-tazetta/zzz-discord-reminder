type Env = {
    LTUID_V2: string;
    LTOKEN_V2: string;
    COOKIE_TOKEN_V2?: string;
    DISCORD_WEBHOOK_URL: string;
    ZZZ_TARGET_UID?: string;
};

type Mode = "daily" | "weekly";

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;
const JST_OFFSET_HOURS = 9;

// 式輿防衛戦・危局強襲戦のリセット周期はゲーム側の運用次第で曜日が固定されないため、
// 毎日の daily チェックに相乗りして「リセットまで残り3日・1日を切ったか」で判定する。
// cron 間隔(24時間)より広い26時間の猶予を持たせ、各チェックポイントを必ず1回は捕まえる。
const CHALLENGE_REMINDER_CHECKPOINTS: ReadonlyArray<[number, string]> = [
    [3 * DAY_MS, "3日前"],
    [1 * DAY_MS, "1日前"],
];
const CHALLENGE_REMINDER_MARGIN_MS = 26 * HOUR_MS;

// genshin.py の実装に合わせた HoYoLAB(海外版)の DS 署名用ソルト
const DS_SALT = "6s25p5ox5y14umn1p61aqyyvbvvl3lrt";
const LANG = "ja-jp";
const USER_AGENT =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36";
const ACCOUNTS_URL = "https://api-os-takumi.mihoyo.com/binding/api/getUserGameRolesByCookie";
const ZZZ_RECORD_URL = "https://sg-act-public-api.hoyolab.com/event/game_record_zzz/api/zzz";

const ZZZ_SERVERS: Record<string, { server: string; tzHours: number }> = {
    "10": { server: "prod_gf_us", tzHours: -5 },
    "15": { server: "prod_gf_eu", tzHours: 1 },
    "13": { server: "prod_gf_jp", tzHours: 8 },
    "17": { server: "prod_gf_sg", tzHours: 8 },
};

type ServerDateTime = { year: number; month: number; day: number; hour: number; minute: number; second: number };

type ZZZAccount = { game_biz: string; game_uid: string };

type ZZZNotes = {
    vitality: { current: number; max: number };
    bounty_commission?: { num: number; total: number; refresh_time: number; unlock?: boolean } | null;
};

type ShiyuResponse = {
    hadal_ver: "v1" | "v2";
    hadal_info_v1?: { hadal_end_time?: ServerDateTime | null; has_data: boolean };
    hadal_info_v2?: { hadal_end_time?: ServerDateTime | null; brief?: unknown };
};

type AssaultResponse = { end_time?: ServerDateTime | null; has_data: boolean };

class HoyolabClient {
    private readonly cookie: string;

    constructor(env: Env) {
        const cookies = [`ltuid_v2=${env.LTUID_V2}`, `ltoken_v2=${env.LTOKEN_V2}`];
        if (env.COOKIE_TOKEN_V2) cookies.push(`cookie_token_v2=${env.COOKIE_TOKEN_V2}`);
        this.cookie = cookies.join("; ");
    }

    async get<T>(url: string, params: Record<string, string | number> = {}): Promise<T> {
        const u = new URL(url);
        for (const [k, v] of Object.entries(params)) u.searchParams.set(k, String(v));

        const res = await fetch(u, {
            headers: {
                Cookie: this.cookie,
                "User-Agent": USER_AGENT,
                "x-rpc-app_version": "1.5.0",
                "x-rpc-client_type": "5",
                "x-rpc-language": LANG,
                "x-rpc-lang": LANG,
                ds: await generateDynamicSecret(),
            },
        });
        if (!res.ok) throw new Error(`HoYoLAB ${u.pathname} が HTTP ${res.status} を返した`);

        const body = (await res.json()) as { retcode: number; message: string; data: T };
        if (body.retcode !== 0) {
            throw new Error(`HoYoLAB ${u.pathname} がエラーを返した: retcode=${body.retcode} ${body.message}`);
        }
        return body.data;
    }
}

async function generateDynamicSecret(): Promise<string> {
    const t = Math.floor(Date.now() / 1000);
    const letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
    const r = Array.from({ length: 6 }, () => letters[Math.floor(Math.random() * letters.length)]).join("");
    const digest = await crypto.subtle.digest("MD5", new TextEncoder().encode(`salt=${DS_SALT}&t=${t}&r=${r}`));
    const h = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
    return `${t},${r},${h}`;
}

function recognizeServer(uid: string): { server: string; tzHours: number } {
    const info = ZZZ_SERVERS[uid.slice(0, -8)];
    if (!info) throw new Error(`UID ${uid} のサーバーを判別できない`);
    return info;
}

function serverDateTimeToDate(dt: ServerDateTime | null | undefined, tzHours: number): Date | null {
    // 空オブジェクトで返ってくることがある(シーズン情報なし)
    if (!dt || dt.year === undefined) return null;
    return new Date(Date.UTC(dt.year, dt.month - 1, dt.day, dt.hour, dt.minute, dt.second) - tzHours * HOUR_MS);
}

async function sendDiscordMessage(webhookUrl: string, content: string): Promise<void> {
    const res = await fetch(webhookUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
    });
    if (!res.ok) throw new Error(`Discord Webhook が HTTP ${res.status} を返した: ${await res.text()}`);
}

function formatDuration(ms: number): string {
    const totalMinutes = Math.max(Math.floor(ms / 60000), 0);
    const minutes = totalMinutes % 60;
    const hours = Math.floor(totalMinutes / 60) % 24;
    const days = Math.floor(totalMinutes / 60 / 24);
    if (days) return `${days}日${hours}時間${minutes}分`;
    if (hours) return `${hours}時間${minutes}分`;
    return `${minutes}分`;
}

function formatJst(date: Date): string {
    const d = new Date(date.getTime() + JST_OFFSET_HOURS * HOUR_MS);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${pad(d.getUTCMonth() + 1)}/${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} JST`;
}

async function resolveZzzUid(client: HoyolabClient, env: Env): Promise<string> {
    const { list } = await client.get<{ list: ZZZAccount[] }>(ACCOUNTS_URL);
    const zzzAccounts = list.filter((a) => a.game_biz.includes("nap"));

    if (env.ZZZ_TARGET_UID) {
        // 1つの HoYoLAB アカウントに複数の ZZZ キャラクターが紐づいていることがある
        if (!zzzAccounts.some((a) => a.game_uid === env.ZZZ_TARGET_UID)) {
            throw new Error(`指定されたUID(${env.ZZZ_TARGET_UID})のZZZキャラクターが見つからなかった。`);
        }
        return env.ZZZ_TARGET_UID;
    }

    if (zzzAccounts.length === 0) {
        throw new Error("HoYoLABアカウントにZZZのキャラクターが見つからなかった。");
    }
    if (zzzAccounts.length > 1) {
        console.warn(`ZZZアカウントが${zzzAccounts.length}件あるが、ZZZ_TARGET_UID未設定のため先頭を使う`);
    }
    return zzzAccounts[0].game_uid;
}

function buildDailyMessage(notes: ZZZNotes): string | null {
    const { current, max } = notes.vitality;
    console.log(`デイリー任務: ${current}/${max}`);
    if (current >= max) return null;
    return `📋 **本日のデイリー任務が未完了です**\nデイリー任務(委托): ${current}/${max}`;
}

// 懸賞依頼の進捗はサーバー側で集計されるので、0号ホロウ周回でも特派調査でも同じカウンタに加算される
function buildWeeklyMessage(notes: ZZZNotes): string | null {
    const bounty = notes.bounty_commission;
    if (!bounty) {
        // 取得できないと通知が静かに止まるので、気づけるように警告を送る
        return "⚠️ 0号ホロウの懸賞依頼の進捗がHoYoLAB APIから取得できなかった。\nゲーム側の仕様変更かもしれない。";
    }
    if (bounty.unlock === false) return null;

    console.log(`懸賞依頼: ${bounty.num}/${bounty.total}`);
    if (bounty.num >= bounty.total) return null;

    const refreshMs = bounty.refresh_time * 1000;
    return (
        `🕳️ **0号ホロウの週間任務(懸賞依頼)が未完了です**\n` +
        `懸賞依頼: ${bounty.num}/${bounty.total}\n` +
        `リセットまで: あと${formatDuration(refreshMs)}(${formatJst(new Date(Date.now() + refreshMs))})`
    );
}

function reminderCheckpoint(endTime: Date | null): { remainingMs: number; label: string } | null {
    if (!endTime) return null;
    const remainingMs = endTime.getTime() - Date.now();
    for (const [checkpoint, label] of CHALLENGE_REMINDER_CHECKPOINTS) {
        const lower = Math.max(checkpoint - CHALLENGE_REMINDER_MARGIN_MS, 0);
        if (lower <= remainingMs && remainingMs <= checkpoint) return { remainingMs, label };
    }
    return null;
}

// 式輿防衛戦・危局強襲戦は current/max のカウンタが取れないので「今シーズン一度も挑戦していないか」だけを見る
function buildChallengeMessage(
    icon: string,
    name: string,
    endTime: Date | null,
    attempted: boolean,
): string | null {
    const checkpoint = reminderCheckpoint(endTime);
    if (!checkpoint || !endTime) return null;
    if (attempted) {
        console.log(`${name}は今シーズン挑戦済み`);
        return null;
    }
    return (
        `${icon} **${name}が今シーズン未挑戦です(リセット${checkpoint.label})**\n` +
        `リセットまで: あと${formatDuration(checkpoint.remainingMs)}(${formatJst(endTime)})`
    );
}

async function buildShiyuMessage(client: HoyolabClient, uid: string): Promise<string | null> {
    const { server, tzHours } = recognizeServer(uid);
    const data = await client.get<ShiyuResponse>(`${ZZZ_RECORD_URL}/hadal_info_v2`, {
        role_id: uid,
        server,
        schedule_type: 1,
    });

    // レスポンス形式が v1(has_data あり)と v2(brief の有無で判定)の2通りある
    if (data.hadal_ver === "v1") {
        const info = data.hadal_info_v1!;
        return buildChallengeMessage("🏯", "式輿防衛戦", serverDateTimeToDate(info.hadal_end_time, tzHours), info.has_data);
    }
    const info = data.hadal_info_v2!;
    return buildChallengeMessage("🏯", "式輿防衛戦", serverDateTimeToDate(info.hadal_end_time, tzHours), info.brief != null);
}

async function buildAssaultMessage(client: HoyolabClient, uid: string): Promise<string | null> {
    const { server, tzHours } = recognizeServer(uid);
    const data = await client.get<AssaultResponse>(`${ZZZ_RECORD_URL}/hadal_mem_detail_v2`, {
        uid,
        region: server,
        schedule_type: 1,
    });
    return buildChallengeMessage("⚔️", "危局強襲戦", serverDateTimeToDate(data.end_time, tzHours), data.has_data);
}

// 未解放や API 仕様変更で取れなくても、デイリー任務の通知は止めたくない
async function optional(name: string, fn: () => Promise<string | null>): Promise<string | null> {
    try {
        return await fn();
    } catch (err) {
        console.warn(`${name}の情報取得に失敗した:`, err);
        return null;
    }
}

async function runChecks(env: Env, modes: Mode[]): Promise<void> {
    const client = new HoyolabClient(env);
    const uid = await resolveZzzUid(client, env);
    const { server } = recognizeServer(uid);
    const notes = await client.get<ZZZNotes>(`${ZZZ_RECORD_URL}/note`, { role_id: uid, server });

    const messages: (string | null)[] = [];
    if (modes.includes("daily")) {
        messages.push(
            buildDailyMessage(notes),
            await optional("式輿防衛戦", () => buildShiyuMessage(client, uid)),
            await optional("危局強襲戦", () => buildAssaultMessage(client, uid)),
        );
    }
    if (modes.includes("weekly")) messages.push(buildWeeklyMessage(notes));

    const content = messages.filter((m): m is string => m !== null);
    if (content.length === 0) {
        console.log("通知すべきものはなかった");
        return;
    }
    await sendDiscordMessage(env.DISCORD_WEBHOOK_URL, content.join("\n\n"));
    console.log(`${content.length}件の通知を送った`);
}

export default {
    async scheduled(controller: ScheduledController, env: Env): Promise<void> {
        // 懸賞依頼は月曜 5:00 JST リセットなので、日曜(JST)の実行時だけ週間チェックも行う
        const jstDay = new Date(controller.scheduledTime + JST_OFFSET_HOURS * HOUR_MS).getUTCDay();
        const modes: Mode[] = jstDay === 0 ? ["daily", "weekly"] : ["daily"];
        console.log(`チェック対象: ${modes.join(", ")}`);
        try {
            await runChecks(env, modes);
        } catch (err) {
            const message = err instanceof Error ? err.message : String(err);
            await sendDiscordMessage(
                env.DISCORD_WEBHOOK_URL,
                `⚠️ ZZZのチェック(${modes.join(", ")})の実行中にエラーが発生した。Cookie失効の可能性がある。\n\`\`\`${message}\`\`\``,
            );
            throw err;
        }
    },
} satisfies ExportedHandler<Env>;
