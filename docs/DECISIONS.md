# Architecture decisions

## 2026-08-28: Publish guard keeps last-good data

Status: accepted

The collector may persist raw evidence even when every candidate is unknown, excluded, or below the cutoff. It must not replace `summary/latest.json` when the current public ranking is empty. This separates evidence retention from publication and makes an empty dashboard an explicit failure rather than a valid update.

## 2026-08-28: Select history by timestamp, not record count

Status: accepted

The 24-hour window is selected from the UTC timestamp encoded in raw object keys. The pipeline lists only the current and cutoff UTC dates, filters to the exact interval, and sorts chronologically. Missed or delayed runs therefore do not stretch “24h” into an older fixed number of snapshots.

## 2026-08-28: API-key-only operation is a sensor probe

Status: accepted

Until R2 credentials exist, the scheduled workflow performs one real YouTube collection and retains the single-snapshot result as a short-lived GitHub Actions artifact. It is labeled `probe`, is not presented as 24-hour production data, and does not replace the public demo. Once all R2 settings exist, the same workflow switches to raw persistence and last-good publication.

Classification diagnostics are retained as a separate short-lived artifact on every run, including blocked publications. The report contains public stream metadata needed to tune aliases, but never credentials or environment values.

## 2026-08-28: Discover broadly, verify the gaming category after enrichment

Status: accepted

The live search requests the documented `snippet` part without a category constraint, using one OR query for Japanese/English gaming and streaming terms. It then verifies each candidate's `snippet.categoryId` from `videos.list`. Non-gaming candidates remain in raw evidence and diagnostics as explicitly excluded rows, but can never enter public rankings. This avoids treating an empty unqualified or category-filtered search result as proof that no gaming streams are live while preserving the two-search-requests-per-run quota budget.

## 2026-08-28: Public data source is injected at build time

Status: accepted

The checked-in site remains a clearly labeled deterministic demo. A deployment may set `R2_PUBLIC_BASE_URL`; the build then injects the HTTPS `summary/latest.json` URL into the generated `dist/index.html`. Credentials are never embedded in the browser bundle.

## 2026-08-28: GitHub Pages deploys only the built dashboard

Status: accepted

Pages deployment uploads `dist/`, not the repository root. This keeps Python, tests, configuration, and raw fixtures outside the public site and guarantees that the same build validation used locally controls the deployed artifact.

The production Pages build exports the validated last-good summary from private R2 and bundles it under `dist/data/latest.json`. A successful collection triggers a new Pages deployment. R2 credentials remain server-side in Actions, and the bucket does not require a public URL or browser CORS policy.

## 2026-08-28: The classification dictionary learns with multi-channel evidence

Status: accepted

The checked-in catalog is a broad seed, not a closed list. Production observations retain title hashtags in private R2. A new hashtag co-occurring with a confidently classified game becomes a learned alias after three distinct channels agree. A hashtag from otherwise unclassified gaming streams becomes a learned game after five distinct channels agree. Single-channel terms remain review candidates, generic streaming tags are rejected, and all learned state is auditable in `dictionary/state.json`.

## 2026-08-28: Live ranking rows deep-link to the leading stream

Status: accepted

Each live game carries up to five eligible stream references ordered by concurrent viewers. The dashboard ranking row links to the current highest-viewed YouTube stream; historical 24-hour rows remain non-clickable. When one channel has multiple videos for the same game, only its highest-viewed video contributes to the snapshot so streamer and viewer totals share the same deduplication unit.

## 2026-08-29: Half-hour slots use redundant scheduling

Status: accepted

GitHub scheduled the first `:00/:30` observation 18 minutes late and dropped other expected events. Primary cron events remain at `:00` and `:30`, with idempotent backups at `:08` and `:38`. Every event maps to its intended half-hour R2 key; an existing key is skipped before any YouTube request. Records retain the actual API completion time in `collected_at` while `observed_at` represents the canonical half-hour slot.

## 2026-08-29: Indie discovery favors gaming-specific metadata

Status: accepted

The live query targets `ゲーム実況` and `ゲーム配信` instead of generic live-stream terms, reducing non-game competition in the 100-result discovery ceiling. The seed catalog includes Japanese and international indie staples. For an unknown stream, a useful leading bracket label that is repeated in its description hashtag or YouTube tags is strong enough to create an auditable learned game from one channel; otherwise the existing five-channel threshold applies.

## Format compatibility

The current public document uses `schema_version: 1`. Any future incompatible change requires an explicit reader/migration path. Unknown versions must not be silently rewritten or treated as version 1.
