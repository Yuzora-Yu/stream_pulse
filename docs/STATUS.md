# Development status

基準日: 2026-08-28

## MVP 完成条件との対応

| 企画書の完成条件 | 状態 | 現状 |
| --- | --- | --- |
| 30分スナップショットを R2 保存し最終成功時刻を公開 | 部分 | 保存・集計コードと cron は実装済み。R2 secrets/variable の登録待ち。 |
| 同一 channel × game の長時間配信を重複計上しない | 完了 | スナップショット・24h とも distinct 集計。全体配信者数もゲーム跨ぎで重複除去。 |
| 配信者数順・現在視聴者数順を切替 | 完了 | LIVE/24h、検索、3種類の並び替えを実装。 |
| 24hユニーク配信者数と Viewer Hours | 完了 | 実時刻の24時間窓、全体 distinct、ゲーム別集計を実装。 |
| 全体ピークタイム | 完了 | 配信者数・視聴者数・密度を表示。 |
| 未知ゲームを review_queue で確定し再利用 | 部分 | hold/conflict 判定と R2 review JSON は実装。Sheets/Spark 往復は未実装。 |
| 設定変更に旧値・新値・根拠・日時を保存 | 未着手 | Sheets の `audit_log` 想定のみ。 |
| API障害時に空データで上書きせず last-good 表示 | 完了 | raw 保存後公開、空ランキング publication guard、UI stale 表示を実装。 |
| 追加課金ほぼ0円で継続 | 検証待ち | 無料枠前提の構成。実運用後に Actions/R2 使用量を確認する。 |

GitHub Pages のルートが 404 になっていたため、`dist/` を Pages artifact として配信する専用ワークフローを追加済みです。反映には変更の push と Pages workflow の成功が必要です。

## 次の優先順位

1. R2 secrets と `R2_BUCKET` を設定し、30分収集を24時間連続で検証する。
2. R2 公開 URL/CORS を設定し、公開サイトを DEMO から LIVE へ切り替える。
3. `review_queue` と Google Sheets の同期、`audit_log` の追記を実装する。
4. ゲーム詳細ページにゲーム別時系列・ピークを追加する。
5. 7日/30日、曜日×時間帯、日次集約と保持期限を実装する。
