# YU-ZORA STREAM PULSE

YouTube Gaming の上位ライブ候補を30分ごとに観測し、配信者数と視聴量を別々に可視化する静的 Web ダッシュボードです。

## 現在の段階

- ローカルの収集・正規化・LIVE/24h集計、デモ UI、Methodology、GitHub Actions の品質ゲートは実装済みです。
- `YOUTUBE_API_KEY` だけでも、定期ワークフローが実測センサーを検証し、`stream-pulse-live-probe` artifact を7日間保存します。
- 30分履歴と last-good `latest.json` は private R2 に保存し、成功した収集後に GitHub Pages へ実測JSONを同梱します。
- Google Sheets / Spark の監査台帳は接続確認コードまでで、review queue の自動同期と監査履歴 UI は未実装です。

詳しい完成度は [docs/STATUS.md](docs/STATUS.md) を参照してください。

## ローカル確認

Python 3.11+ と Node.js 20+ を使用します。

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
npm run typecheck
npm test
npm run lint
npm run build
npm run preview
```

API を呼ばずに集計結果を作る場合:

```powershell
python -m src.pipeline --fixture tests/fixtures/raw_records.json --output runtime/fixture-summary.json
```

実測センサーを単発確認する場合:

```powershell
$env:YOUTUBE_API_KEY = "..."
python -m src.pipeline --output runtime/live-probe.json
```

## 本番用 GitHub 設定

Repository secret:

- `YOUTUBE_API_KEY`
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`

Repository variable:

- `R2_BUCKET`

GitHub Pages のデプロイは資格情報をブラウザへ渡さず、private R2 の last-good データをビルド時に取得します。単独のローカルビルドは、実測値と誤認させない `DEMO DATA` を同梱します。外部ホスティングで `R2_PUBLIC_BASE_URL` を明示した場合だけ、HTTPS の公開R2 URLを参照できます。

## データ保全

- raw スナップショットの保存完了後にだけ集計・公開します。
- 現在ランキングが空になった実行は公開を中止し、既存の last-good を保持します。
- 24時間集計は raw 全履歴の「最後の48件」ではなく、UTC 時刻で実際の24時間窓を選びます。
- `schema_version` の未知バージョンは、将来の明示的な移行なしに上書きしません。
