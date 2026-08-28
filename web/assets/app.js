import { formatHour, formatNumber, formatObservedAt, rankingSortKey, statusPresentation } from "./format.js";

const state = { data: null, period: "live", sort: "streamers", query: "" };
const $ = selector => document.querySelector(selector);

async function load() {
  const source = document.body.dataset.source || "./data/latest.json";
  try {
    const response = await fetch(source, { headers: { Accept: "application/json" }, cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
    render();
  } catch (error) {
    const status = statusPresentation("error");
    $("#status-label").textContent = status.label;
    $("#status-note").textContent = `データを読み込めませんでした。${error instanceof Error ? ` (${error.message})` : ""}`;
    $(".pulse-status").classList.add(status.className);
    $("#ranking-empty").hidden = false;
    $("#chart-empty").hidden = false;
  }
}

function render() {
  renderStatus();
  renderMetrics();
  renderPeaks();
  renderRanking();
  drawChart();
}

function renderStatus() {
  const meta = state.data.meta || {};
  const view = statusPresentation(meta.status);
  const panel = $(".pulse-status");
  panel.className = `pulse-status ${view.className}`;
  $("#status-label").textContent = view.label;
  $("#status-note").textContent = view.note;
  $("#observed-at").textContent = formatObservedAt(meta.observed_at);
  $("#last-success-at").textContent = formatObservedAt(meta.last_success_at);
  $("#interval").textContent = `${formatNumber(meta.observation_interval_minutes)}分`;
  const cutoff = meta.cutoff || {};
  $("#cutoff-label").textContent = `登録者${formatNumber(cutoff.min_subscribers)}以上 ${cutoff.operator || "OR"} 同接${formatNumber(cutoff.min_concurrent_viewers)}以上`;
}

function renderMetrics() {
  const totals = state.data.totals || {};
  $("#metric-streamers").textContent = formatNumber(totals.live_streamers);
  $("#metric-viewers").textContent = formatNumber(totals.current_viewers);
  $("#metric-density").textContent = formatNumber(totals.viewer_density, 1);
  $("#metric-hours").textContent = formatNumber(totals.viewer_hours_24h, 1);
}

function renderPeaks() {
  const peaks = state.data.peaks || {};
  const definitions = [
    ["STREAMER PEAK", "配信者数", peaks.live_streamers],
    ["VIEWER PEAK", "視聴者数", peaks.current_viewers],
    ["DENSITY PEAK", "視聴者密度", peaks.viewer_density]
  ];
  const root = $("#peak-grid");
  root.replaceChildren(...definitions.map(([label, title, value]) => {
    const article = document.createElement("article");
    article.className = "peak-card";
    const labelEl = document.createElement("span"); labelEl.textContent = label;
    const strong = document.createElement("strong"); strong.textContent = formatNumber(value?.value, title === "視聴者密度" ? 1 : 0);
    const time = document.createElement("time"); time.dateTime = value?.at || ""; time.textContent = `${title}のピーク / ${formatHour(value?.at)}`;
    article.append(labelEl, strong, time);
    return article;
  }));
}

function rankingRows() {
  const rows = [...(state.data.rankings?.[state.period] || [])];
  const key = rankingSortKey(state.period, state.sort);
  return rows
    .filter(item => !state.query || `${item.display_name} ${item.game_id}`.toLowerCase().includes(state.query))
    .sort((a, b) => (Number(b[key]) || 0) - (Number(a[key]) || 0) || a.display_name.localeCompare(b.display_name, "ja"));
}

function renderRanking() {
  const isLive = state.period === "live";
  $("#column-a-label").textContent = isLive ? "配信者" : "24h配信者";
  $("#column-b-label").textContent = isLive ? "視聴者" : "Viewer Hours";
  $("#column-c-label").textContent = isLive ? "密度" : "再生増分";
  const list = $("#ranking-list");
  const rows = rankingRows();
  list.replaceChildren(...rows.map((item, index) => rankingItem(item, index, isLive)));
  $("#ranking-empty").hidden = rows.length > 0;
}

function rankingItem(item, index, isLive) {
  const li = document.createElement("li"); li.className = "ranking-item";
  const identity = document.createElement("div"); identity.className = "game-identity";
  const rank = document.createElement("span"); rank.className = "rank-no"; rank.textContent = String(index + 1).padStart(2, "0");
  const nameWrap = document.createElement("div");
  const name = document.createElement("strong"); name.textContent = item.display_name;
  const id = document.createElement("small"); id.textContent = item.game_id;
  nameWrap.append(name, id); identity.append(rank, nameWrap);
  const values = isLive
    ? [[item.live_streamers, "STREAMERS", 0], [item.current_viewers, "VIEWERS", 0], [item.viewer_density, "PER STREAMER", 1]]
    : [[item.unique_streamers, "UNIQUE", 0], [item.viewer_hours, "HOURS", 1], [item.view_delta, "VIEWS", 0]];
  li.append(identity, ...values.map(([value, label, digits]) => {
    const wrap = document.createElement("div"); wrap.className = "ranking-value";
    const strong = document.createElement("strong"); strong.textContent = formatNumber(value, digits);
    const span = document.createElement("span"); span.textContent = label;
    wrap.append(strong, span); return wrap;
  }));
  return li;
}

function drawChart() {
  const canvas = $("#trend-chart");
  const data = state.data.timeseries || [];
  $("#chart-empty").hidden = data.length > 1;
  canvas.hidden = data.length <= 1;
  if (data.length <= 1) return;
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.max(600, Math.round(rect.width * dpr));
  canvas.height = Math.round(rect.height * dpr);
  const ctx = canvas.getContext("2d"); ctx.scale(dpr, dpr);
  const width = canvas.width / dpr; const height = canvas.height / dpr;
  const pad = { left: 42, right: 46, top: 24, bottom: 38 };
  const plotW = width - pad.left - pad.right; const plotH = height - pad.top - pad.bottom;
  const maxS = Math.max(1, ...data.map(row => Number(row.live_streamers) || 0));
  const maxV = Math.max(1, ...data.map(row => Number(row.current_viewers) || 0));
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(151,180,199,.14)"; ctx.fillStyle = "#62778a"; ctx.font = "10px ui-monospace, monospace";
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + plotH * i / 4;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    ctx.fillText(formatNumber(maxS * (1 - i / 4)), 2, y + 3);
    const label = formatNumber(maxV * (1 - i / 4)); const measure = ctx.measureText(label).width;
    ctx.fillText(label, width - measure - 2, y + 3);
  }
  const drawLine = (key, max, color) => {
    ctx.beginPath(); ctx.lineWidth = 2; ctx.strokeStyle = color; ctx.lineJoin = "round"; ctx.lineCap = "round";
    data.forEach((row, i) => {
      const x = pad.left + plotW * i / Math.max(1, data.length - 1);
      const y = pad.top + plotH * (1 - (Number(row[key]) || 0) / max);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
  };
  drawLine("live_streamers", maxS, "#46dce6"); drawLine("current_viewers", maxV, "#8b87ff");
  const labelIndexes = [...new Set([0, Math.floor((data.length - 1) / 2), data.length - 1])];
  ctx.fillStyle = "#62778a";
  labelIndexes.forEach((index, position) => {
    const label = formatHour(data[index].at); const measure = ctx.measureText(label).width;
    const x = pad.left + plotW * index / Math.max(1, data.length - 1) - (position === 0 ? 0 : position === labelIndexes.length - 1 ? measure : measure / 2);
    ctx.fillText(label, x, height - 10);
  });
}

document.querySelectorAll("[data-period]").forEach(button => button.addEventListener("click", () => {
  state.period = button.dataset.period;
  document.querySelectorAll("[data-period]").forEach(item => { const active = item === button; item.classList.toggle("is-active", active); item.setAttribute("aria-pressed", String(active)); });
  renderRanking();
}));
$("#game-search").addEventListener("input", event => { state.query = event.target.value.trim().toLowerCase(); renderRanking(); });
$("#sort-select").addEventListener("change", event => { state.sort = event.target.value; renderRanking(); });
new ResizeObserver(() => { if (state.data) drawChart(); }).observe($("#trend-chart"));
load();

