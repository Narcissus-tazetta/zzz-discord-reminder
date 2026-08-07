# ZZZ デイリー任務リマインダー

毎日決まった時刻に、ゼンレスゾーンゼロ(ZZZ)のデイリー任務(委托)が
終わってなければ Discord に通知するツール。GitHub Actions 上で動くので、
自分のPCが起動してなくても動く。

## 仕組み

- 毎日 GitHub Actions が起動して `check_daily.py` を実行
- HoYoLAB の Cookie を使ってリアルタイムノートを取得
- デイリー任務(委托)のポイントが上限に達してなければ Discord Webhook に通知
- 認証情報(Cookie)は GitHub Secrets に暗号化保存。リポジトリオーナー以外は見れない

## セットアップ手順

### 1. このリポジトリを **Private** で作る

GitHubで新しいリポジトリを作成し、この中身(`check_daily.py`、
`requirements.txt`、`.github/workflows/reminder.yml`)を配置する。
**必ず Private に設定すること。**(公開してもSecretsの値自体は漏れないが、
念のため)

### 2. HoYoLABのCookieを取得する

1. ブラウザで https://www.hoyolab.com にログイン(ZZZアカウントと同じログイン方法で)
2. ログイン後、ブラウザのDevTools(F12など)を開く
3. `Application`(Chrome)または`ストレージ`(Firefox)タブ → Cookies →
   `https://www.hoyolab.com` を選択
4. 以下の値をコピーしておく
   - `ltuid_v2`
   - `ltoken_v2`
   - `cookie_token_v2` (あれば。無くても基本動くはずだが念のため取得推奨)

Cookieには有効期限がある。数週間〜数ヶ月で失効することがあるので、
通知が来なくなったら再取得が必要(下記トラブルシューティング参照)。

### 3. Discord Webhook URLを取得する

1. 通知を送りたいDiscordチャンネルの設定を開く
2. 「連携サービス」→「ウェブフック」→「新しいウェブフック」
3. 作成されたWebhook URLをコピー

### 4. GitHub Secretsに登録する

リポジトリの `Settings` → `Secrets and variables` → `Actions` →
`New repository secret` から、以下を1つずつ登録:

| Name | 値 |
|---|---|
| `LTUID_V2` | 手順2で取得した値 |
| `LTOKEN_V2` | 手順2で取得した値 |
| `COOKIE_TOKEN_V2` | 手順2で取得した値(任意) |
| `DISCORD_WEBHOOK_URL` | 手順3で取得した値 |

### 5. 動作確認

リポジトリの `Actions` タブ → `ZZZ Daily Reminder` を選択 →
`Run workflow` ボタンで手動実行できる。ログを見て、正しく
デイリー任務の進捗が取得できてるか確認する。

## 通知時刻を変更したいとき

`.github/workflows/reminder.yml` の中の以下の行を編集する:

```yaml
- cron: "30 14 * * *"
```

これは **UTC時刻** なので、日本時間(JST)にするには **UTCに9を足す**。
例:

- JST 23:30に通知したい → UTC 14:30 → `cron: "30 14 * * *"` (デフォルト)
- JST 21:00に通知したい → UTC 12:00 → `cron: "0 12 * * *"`
- JST 7:00に通知したい(日付またぎ注意) → UTC前日22:00 → `cron: "0 22 * * *"`

書式は `分 時 * * *`。編集してコミットすれば次の実行から反映される。

※ GitHub Actionsのscheduled実行は、混雑状況によって数分〜十数分遅れることがある。
正確に秒単位で発火するわけではないので、その前提で運用すること。

## トラブルシューティング

### 通知が来ない/Actionsが失敗する

`Actions` タブでワークフローの実行ログを確認する。よくある原因:

- **Cookie失効**: `get_game_accounts` や `get_zzz_notes` でエラーが出る場合、
  手順2をやり直してSecretsを更新する
- **ZZZアカウントが見つからない**: HoYoLABアカウントにZZZのキャラクターが
  紐づいているか確認する

### 手元でテストしたい場合

```bash
pip install -r requirements.txt
export LTUID_V2="..."
export LTOKEN_V2="..."
export DISCORD_WEBHOOK_URL="..."
python check_daily.py
```

## セキュリティについて

- Cookieは GitHub Secrets に暗号化保存され、ワークフロー実行中のみ
  環境変数として展開される。ログには自動でマスクされる
- リポジトリを Private にしていれば、自分以外はコードにもSecretsにも
  アクセスできない
- 第三者のBotサービス(Hoyo Buddyなど)と違い、Cookieを渡す先は
  「自分が管理するGitHubリポジトリ」のみ
