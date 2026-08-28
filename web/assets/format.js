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

export function formatObservationPoint(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const parts = Object.fromEntries(new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false
  }).formatToParts(date).map(part => [part.type, part.value]));
  return `${parts.month}月${parts.day}日 ${parts.hour}時${parts.minute}分時点`;
}

export function formatCutoff(cutoff = {}) {
  const operator = String(cutoff.operator || "OR").toUpperCase();
  const join = operator === "AND" ? "かつ" : "または";
  return `足切り：登録者${formatNumber(cutoff.min_subscribers)}人以上 ${join} 同接${formatNumber(cutoff.min_concurrent_viewers)}人以上`;
}

export function formatHour(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit" }).format(date);
}

export function rankingSortKey(period, sort) {
  if (period === "last_24h") return sort === "viewers" ? "viewer_hours" : sort === "density" ? "view_delta" : "unique_streamers";
  return sort === "viewers" ? "current_viewers" : sort === "density" ? "viewer_density" : "live_streamers";
}

export function rankingSortKeys(period, sort) {
  if (period === "last_24h") {
    if (sort === "viewers") return ["viewer_hours", "unique_streamers"];
    if (sort === "density") return ["view_delta", "viewer_hours"];
    return ["unique_streamers", "viewer_hours"];
  }
  if (sort === "viewers") return ["current_viewers", "live_streamers"];
  if (sort === "density") return ["viewer_density", "current_viewers"];
  return ["live_streamers", "current_viewers"];
}

export function compareRankingRows(a, b, period, sort) {
  for (const key of rankingSortKeys(period, sort)) {
    const difference = (Number(b[key]) || 0) - (Number(a[key]) || 0);
    if (difference) return difference;
  }
  return String(a.display_name || "").localeCompare(String(b.display_name || ""), "ja");
}

export function statusPresentation(status) {
  if (status === "live") return { label: "LIVE", className: "is-live", note: "観測パイプラインは正常です。" };
  if (status === "probe") return { label: "LIVE PROBE", className: "is-live", note: "実測センサーの単発確認データです。履歴公開はまだ開始していません。" };
  if (status === "stale") return { label: "LAST GOOD", className: "is-stale", note: "更新に失敗したため、最後に成功したデータを表示しています。" };
  if (status === "demo" || status === "fixture") return { label: "DEMO DATA", className: "is-demo", note: "これは画面確認用データです。実測ランキングではありません。" };
  return { label: "CHECK", className: "is-error", note: "観測状態を確認できません。" };
}

