# ZZZ 任務リマインダー

決まった時刻に、ゼンレスゾーンゼロ(ZZZ)の任務が終わってなければ
Discord に通知するツール。Cloudflare Workers の Cron Triggers で動くので、
自分のPCが起動してなくても動く。

チェックするのは以下の4つ:

| 種類 | 内容 | 通知タイミング | リセット |
|---|---|---|---|
| デイリー | デイリー任務(委托) | 毎日 22:00 JST | 毎日 5:00 JST |
| ウィークリー | 0号ホロウの懸賞依頼 | 日曜 22:00 JST | 月曜 5:00 JST |
| 式輿防衛戦 | シーズン内で未挑戦か | 毎日 22:00 JST(リセット3日前・1日前を切ったら) | シーズンごと(ゲーム側の運用に依存) |
| 危局強襲戦 | シーズン内で未挑戦か | 毎日 22:00 JST(リセット3日前・1日前を切ったら) | シーズンごと(ゲーム側の運用に依存) |

## 仕組み

- Cloudflare Workers が毎日 22:00 JST に起動する(cron は1つだけで、日曜の実行時にウィークリーも一緒にチェックする)
- HoYoLAB の Cookie を使ってリアルタイムノート等を取得
- 進捗が上限に達してなければ Discord Webhook に通知
- 認証情報(Cookie)は Workers の Secrets に暗号化保存

懸賞依頼の進捗はサーバー側で集計されるので、0号ホロウを自分で周回しても
特派調査などの代替手段で消化しても、同じカウンタに加算される。
このツールは達成手段を区別せず、進捗が上限に達しているかだけを見る。

式輿防衛戦・危局強襲戦はデイリー任務のような単純な current/max カウンタが
APIから取れないため、「このシーズン一度も挑戦していないか」だけを判定する
(部分的にしかクリアしていない場合は検知できない)。リセット日が固定されていないため、
毎日のチェックで「リセットまで残り3日・1日を切ったか」を見て通知する。

## セットアップ

### 1. HoYoLABのCookieを取得する

1. ブラウザで https://www.hoyolab.com にログイン(ZZZアカウントと同じログイン方法で)
2. DevTools(F12など)を開く
3. `Application`(Chrome)または`ストレージ`(Firefox)タブ → Cookies → `https://www.hoyolab.com`
4. 以下の値をコピーしておく
   - `ltuid_v2`
   - `ltoken_v2`
   - `cookie_token_v2`(あれば)

Cookieは数週間〜数ヶ月で失効することがある。失効するとエラー通知が Discord に届くので、再取得して Secrets を更新する。

### 2. Discord Webhook URLを取得する

チャンネル設定 →「連携サービス」→「ウェブフック」→「新しいウェブフック」で作成し、URLをコピーする。

### 3. デプロイと Secrets の登録

```bash
bun install
bunx wrangler deploy
bunx wrangler secret put LTUID_V2
bunx wrangler secret put LTOKEN_V2
bunx wrangler secret put COOKIE_TOKEN_V2       # 任意
bunx wrangler secret put DISCORD_WEBHOOK_URL
bunx wrangler secret put ZZZ_TARGET_UID        # 任意。1つのHoYoLABアカウントに複数のZZZキャラがいる場合に指定
```

## 動作確認

`.dev.vars` に Secrets と同じキーを書いて、ローカルで cron を手動発火できる。

```bash
bun run dev
curl "http://localhost:8787/__scheduled?cron=0+13+*+*+*"
```

本番の実行ログは Cloudflare ダッシュボードの Workers → `zzz-reminder` → Logs で見られる。

## 通知時刻を変更したいとき

`wrangler.toml` の `crons` を編集して `bunx wrangler deploy` する。**UTC で指定する**(JST = UTC + 9)。

- JST 22:00 → UTC 13:00 → `"0 13 * * *"`(デフォルト)
- JST 21:00 → UTC 12:00 → `"0 12 * * *"`

ウィークリーは「実行時刻が JST で日曜かどうか」で判定しているので、日付をまたぐ時刻(JST 0:00〜8:59)に変えると日曜の判定がずれる点に注意。

Cloudflare 無料プランは cron トリガーがアカウント全体で5個まで。

## トラブルシューティング

### 「懸賞依頼の進捗が取得できなかった」と通知が来る

ゲーム側のアップデートで API のレスポンスが変わった可能性がある。

### 式輿防衛戦・危局強襲戦の通知が来ない

ログに `式輿防衛戦の情報取得に失敗した` / `危局強襲戦の情報取得に失敗した` と出る場合、
コンテンツが未解放か、API の仕様変更の可能性がある。警告が出ても他のチェックは継続される。
