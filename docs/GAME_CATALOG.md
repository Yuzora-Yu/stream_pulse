# game_catalog 連携

ゲーム実体のマスタは別repository `game_catalog` へ分離し、stream_pulse は観測センサーとして動作します。

## 週次の流れ

1. `catalog-sync.yml` がprivate R2の直近24時間raw snapshotを読む。
2. `src.catalog_sync` がゲーム別活動と未知aliasだけをコンパクトなbundleにする。
3. `game_catalog` をcheckoutし、bundleを `incoming/stream_pulse/latest.json` に保存する。
4. `catalog.import_observations` が集約値と最新5配信を更新する。
5. `game_catalog` にPRを作る。raw snapshot全量はGitへ移さない。
6. `catalog-refresh.yml` が確定済み `dist/game_master.json` / `dist/aliases.json` を取り込み、stream_pulse側へPRする。

## 未知ゲームの扱い

`config/config.json` の `dictionary_learning.promote_game_candidates` は `false` にします。

これにより、複数チャンネルで未知語が観測されても `learned_games` へ自動昇格せず、`game_candidates` に残ります。既存ゲームと確定している配信から得た新aliasの学習は従来通り動作します。

## GitHub設定

Repository secret:

- `GAME_CATALOG_TOKEN`: `game_catalog` に対して Contents / Pull requests のread-write権限を持つfine-grained PAT、または同等のGitHub App token。

Repository variable:

- `GAME_CATALOG_REPO`: 例 `Yuzora-Yu/game_catalog`

既存のR2 secrets/variableも `catalog-sync.yml` が使用します。
