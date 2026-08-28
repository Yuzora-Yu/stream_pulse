export function formatNumber(value, maximumFractionDigits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return new Intl.NumberFormat("ja-JP", { maximumFractionDigits }).format(Number(value));
}

export function formatObservedAt(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"
  }).format(date);
}

export function formatHour(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit" }).format(date);
}

export function rankingSortKey(period, sort) {
  if (period === "last_24h") return sort === "viewers" ? "viewer_hours" : sort === "density" ? "viewer_hours" : "unique_streamers";
  return sort === "viewers" ? "current_viewers" : sort === "density" ? "viewer_density" : "live_streamers";
}

export function statusPresentation(status) {
  if (status === "live") return { label: "LIVE", className: "is-live", note: "観測パイプラインは正常です。" };
  if (status === "stale") return { label: "LAST GOOD", className: "is-stale", note: "更新に失敗したため、最後に成功したデータを表示しています。" };
  if (status === "demo" || status === "fixture") return { label: "DEMO DATA", className: "is-demo", note: "これは画面確認用データです。実測ランキングではありません。" };
  return { label: "CHECK", className: "is-error", note: "観測状態を確認できません。" };
}

