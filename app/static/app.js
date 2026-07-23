const state = {
  files: [],
  selectedPath: null,
};

const els = {
  status: document.getElementById("status"),
  fitDir: document.getElementById("fitDir"),
  fitList: document.getElementById("fitList"),
  detailTitle: document.getElementById("detailTitle"),
  detailMeta: document.getElementById("detailMeta"),
  summaryGrid: document.getElementById("summaryGrid"),
  stravaSummary: document.getElementById("stravaSummary"),
  reportText: document.getElementById("reportText"),
  log: document.getElementById("log"),
  connectGarminBtn: document.getElementById("connectGarminBtn"),
  downloadCount: document.getElementById("downloadCount"),
  downloadBtn: document.getElementById("downloadBtn"),
  refreshBtn: document.getElementById("refreshBtn"),
  analyzeBtn: document.getElementById("analyzeBtn"),
  viewReportBtn: document.getElementById("viewReportBtn"),
  uploadStravaBtn: document.getElementById("uploadStravaBtn"),
};

function setStatus(text) {
  els.status.textContent = text;
}

function log(message, data) {
  const time = new Date().toLocaleTimeString();
  const suffix = data ? `\n${JSON.stringify(data, null, 2)}` : "";
  els.log.textContent = `[${time}] ${message}${suffix}\n\n${els.log.textContent}`;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text.slice(0, 600)}`);
  }
  return response.json();
}

async function refreshFiles() {
  setStatus("读取本地 FIT");
  const data = await fetchJson("/api/fit-files");
  state.files = data.files || [];
  els.fitDir.textContent = data.fit_dir || "";
  renderList();
  if (state.files.length && !state.files.some((file) => file.path === state.selectedPath)) {
    state.selectedPath = state.files[0].path;
  }
  renderDetail();
  setStatus("准备就绪");
}

function renderList() {
  if (!state.files.length) {
    els.fitList.innerHTML = `<div class="empty">还没有本地 FIT。先连接 Garmin 并下载最近活动。</div>`;
    return;
  }

  els.fitList.innerHTML = state.files
    .map((file) => {
      const display = file.display_summary || {};
      const active = file.path === state.selectedPath ? " active" : "";
      const badge = file.has_summary ? "已分析" : "未分析";
      const label = display.summary_label ? ` · ${display.summary_label}` : "";
      return `
        <button class="fit-item${active}" data-path="${escapeAttr(file.path)}">
          <span class="fit-name">${escapeHtml(file.name)}</span>
          <span class="fit-meta">${escapeHtml(formatDate(display.start_time))} ${formatKm(display.distance_km)} ${formatMin(display.duration_min)}${escapeHtml(label)}</span>
          <span class="badge ${file.has_summary ? "done" : ""}">${badge}</span>
        </button>
      `;
    })
    .join("");

  document.querySelectorAll(".fit-item").forEach((button) => {
    button.addEventListener("click", () => selectFile(button.dataset.path));
  });
}

function selectFile(path) {
  state.selectedPath = path;
  renderList();
  renderDetail();
}

function selectedFile() {
  return state.files.find((file) => file.path === state.selectedPath) || null;
}

function renderDetail() {
  const file = selectedFile();
  if (!file) {
    els.detailTitle.textContent = "选择一个 FIT 文件";
    els.detailMeta.textContent = "";
    els.summaryGrid.innerHTML = "";
    els.stravaSummary.textContent = "分析后会显示。";
    els.reportText.textContent = "点击“查看报告”后显示。";
    setActionButtons(false);
    return;
  }

  const display = file.display_summary || {};
  els.detailTitle.textContent = file.name;
  els.detailMeta.textContent = [
    display.sport_type || "unknown",
    display.sub_sport,
    formatDate(display.start_time),
  ].filter(Boolean).join(" · ");
  els.stravaSummary.textContent = file.strava_summary || display.brief || "还没有分析结果。";
  renderSummary(display, file);
  setActionButtons(true);
}

function renderSummary(display, file) {
  const items = [
    ["状态", file.has_summary ? "已分析" : "未分析"],
    ["开始时间", formatDate(display.start_time)],
    ["距离", formatKm(display.distance_km)],
    ["时长", formatMin(display.duration_min)],
    ["训练刺激", display.main_stimulus || "-"],
    ["训练负荷", display.training_load || "-"],
    ["活动标签", display.summary_label || "-"],
    ["口吻", file.strava_summary_tone?.name || "-"],
  ];
  els.summaryGrid.innerHTML = items
    .map(([label, val]) => `
      <div class="metric">
        <div class="metric-label">${escapeHtml(label)}</div>
        <div class="metric-value">${escapeHtml(val)}</div>
      </div>
    `)
    .join("");
}

function setActionButtons(enabled) {
  els.analyzeBtn.disabled = !enabled;
  els.viewReportBtn.disabled = !enabled;
  els.uploadStravaBtn.disabled = !enabled;
}

async function connectGarmin() {
  setStatus("连接 Garmin");
  try {
    const result = await fetchJson("/api/garmin/connect", { method: "POST", body: "{}" });
    log("Garmin 连接成功", result);
    setStatus("Garmin 已连接");
  } catch (error) {
    log("Garmin 连接失败", { error: error.message });
    setStatus("连接失败");
  }
}

async function downloadRecent() {
  const count = Number(els.downloadCount.value || 5);
  setStatus("下载中");
  try {
    const result = await fetchJson("/api/garmin/download", {
      method: "POST",
      body: JSON.stringify({ count }),
    });
    log("下载完成", result);
    await refreshFiles();
  } catch (error) {
    log("下载失败", { error: error.message });
    setStatus("下载失败");
  }
}

async function analyzeSelected() {
  const file = selectedFile();
  if (!file) return;
  setStatus("大模型分析中");
  try {
    const result = await fetchJson("/api/fit-files/analyze", {
      method: "POST",
      body: JSON.stringify({ path: file.path, history: true, force: true }),
    });
    log("分析完成", {
      summary_path: result.summary_path,
      tone: result.strava_summary_tone,
    });
    await refreshFiles();
    state.selectedPath = file.path;
    renderList();
    renderDetail();
  } catch (error) {
    log("分析失败", { error: error.message });
    setStatus("分析失败");
  }
}

async function viewReport() {
  const file = selectedFile();
  if (!file || !file.summary_path) {
    els.reportText.textContent = "还没有 summary，请先分析。";
    return;
  }
  setStatus("读取报告");
  try {
    const response = await fetch(`/api/summary?path=${encodeURIComponent(file.summary_path)}`);
    if (!response.ok) throw new Error(await response.text());
    const summary = await response.json();
    els.reportText.textContent = summary.markdown_report || "(报告为空)";
    setStatus("准备就绪");
  } catch (error) {
    els.reportText.textContent = error.message;
    setStatus("读取报告失败");
  }
}

async function uploadStrava() {
  const file = selectedFile();
  if (!file || !file.summary_path) {
    log("上传失败", { error: "还没有 summary，请先分析。" });
    return;
  }
  if (!window.confirm("确认上传到 Strava？此操作会创建或更新外部活动。")) {
    return;
  }
  setStatus("上传 Strava");
  try {
    const result = await fetchJson("/api/strava/upload", {
      method: "POST",
      body: JSON.stringify({ summary_path: file.summary_path, wait: false, confirmed: true }),
    });
    log("Strava 上传完成", result);
    setStatus("上传完成");
  } catch (error) {
    log("Strava 上传失败", { error: error.message });
    setStatus("上传失败");
  }
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatKm(value) {
  return value === null || value === undefined ? "-" : `${Number(value).toFixed(2)} km`;
}

function formatMin(value) {
  return value === null || value === undefined ? "-" : `${Number(value).toFixed(1)} min`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

els.connectGarminBtn.addEventListener("click", connectGarmin);
els.downloadBtn.addEventListener("click", downloadRecent);
els.refreshBtn.addEventListener("click", refreshFiles);
els.analyzeBtn.addEventListener("click", analyzeSelected);
els.viewReportBtn.addEventListener("click", viewReport);
els.uploadStravaBtn.addEventListener("click", uploadStrava);

refreshFiles().catch((error) => {
  log("初始化失败", { error: error.message });
  setStatus("初始化失败");
});
