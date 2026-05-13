const state = {
  activities: [],
  selectedId: null,
  detail: null,
  tab: "quality",
};

const els = {
  activityList: document.getElementById("activityList"),
  activityTitle: document.getElementById("activityTitle"),
  activityMeta: document.getElementById("activityMeta"),
  summaryGrid: document.getElementById("summaryGrid"),
  tabContent: document.getElementById("tabContent"),
  status: document.getElementById("status"),
  refreshBtn: document.getElementById("refreshBtn"),
  analyzeBtn: document.getElementById("analyzeBtn"),
  chatLog: document.getElementById("chatLog"),
  chatForm: document.getElementById("chatForm"),
  questionInput: document.getElementById("questionInput"),
  saveReport: document.getElementById("saveReport"),
};

function setStatus(text) {
  els.status.textContent = text;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text.slice(0, 300)}`);
  }
  return response.json();
}

async function loadActivities() {
  setStatus("loading activities");
  const data = await fetchJson("/api/activities?limit=50");
  state.activities = data.activities || [];
  renderActivityList();
  if (!state.selectedId && state.activities.length) {
    await selectActivity(state.activities[0].id);
  }
  setStatus("ready");
}

function renderActivityList() {
  if (!state.activities.length) {
    els.activityList.innerHTML = `<div class="empty">还没有活动。先用 CLI 导入 FIT。</div>`;
    return;
  }
  els.activityList.innerHTML = state.activities
    .map((activity) => {
      const active = Number(activity.id) === Number(state.selectedId) ? " active" : "";
      const distance = activity.distance_m ? `${(activity.distance_m / 1000).toFixed(2)} km` : "无距离";
      const duration = activity.duration_s ? `${Math.round(activity.duration_s / 60)} min` : "无时长";
      return `
        <button class="activity-item${active}" data-id="${activity.id}">
          <div class="activity-name">${escapeHtml(activity.file_name || `Activity ${activity.id}`)}</div>
          <div class="activity-detail">#${activity.id} · ${escapeHtml(activity.sport_type || "unknown")} · ${distance} · ${duration}</div>
          <div class="activity-detail">${escapeHtml(activity.start_time || "")}</div>
        </button>
      `;
    })
    .join("");
  document.querySelectorAll(".activity-item").forEach((button) => {
    button.addEventListener("click", () => selectActivity(button.dataset.id));
  });
}

async function selectActivity(id) {
  state.selectedId = id;
  renderActivityList();
  setStatus(`loading activity ${id}`);
  state.detail = await fetchJson(`/api/activities/${id}`);
  renderDetail();
  setStatus("ready");
}

function renderDetail() {
  const detail = state.detail;
  if (!detail) return;
  const activity = detail.activity;
  const summary = detail.summary || {};
  els.activityTitle.textContent = activity.file_name || `Activity ${activity.id}`;
  els.activityMeta.textContent = `#${activity.id} · ${activity.sport_type || "unknown"} · ${activity.start_time || ""}`;
  renderSummary(summary);
  renderTab();
}

function renderSummary(summary) {
  const items = [
    ["时间", summary.duration_min ? `${summary.duration_min} min` : "-"],
    ["距离", summary.distance_km ? `${summary.distance_km} km` : "-"],
    ["均速", summary.average_speed_kmh ? `${summary.average_speed_kmh} km/h` : "-"],
    ["功率", summary.average_power ? `${summary.average_power} W` : "-"],
    ["NP", summary.normalized_power ? `${summary.normalized_power} W` : "-"],
    ["心率", summary.average_heart_rate ? `${summary.average_heart_rate} bpm` : "-"],
    ["IF", summary.intensity_factor ?? "-"],
    ["TSS", summary.tss ?? "-"],
  ];
  els.summaryGrid.innerHTML = items
    .map(([label, value]) => `
      <div class="metric">
        <div class="metric-label">${label}</div>
        <div class="metric-value">${value}</div>
      </div>
    `)
    .join("");
}

function renderTab() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === state.tab);
  });
  const detail = state.detail || {};
  if (state.tab === "quality") {
    renderQuality(detail.data_quality);
  } else if (state.tab === "intensity") {
    renderIntensity(detail.intensity_distribution);
  } else if (state.tab === "segments") {
    renderSegments(detail.workout_segments);
  } else if (state.tab === "fatigue") {
    renderFatigue(detail.fatigue_and_stability);
  } else if (state.tab === "reports") {
    renderReports(detail.reports || []);
  } else {
    renderRaw(detail);
  }
}

function renderQuality(data = {}) {
  const rows = [
    ["质量评分", data.quality_score],
    ["置信度", data.confidence],
    ["功率", yesNo(data.has_power)],
    ["心率", yesNo(data.has_heart_rate)],
    ["速度", yesNo(data.has_speed)],
    ["踏频", yesNo(data.has_cadence)],
    ["GPS", yesNo(data.has_gps)],
    ["采样间隔", data.sampling ? `${data.sampling.median_interval_seconds}s / max ${data.sampling.max_gap_seconds}s` : "-"],
  ];
  els.tabContent.innerHTML = table(rows) + issuesBlock(data.issues || []);
}

function renderIntensity(data = {}) {
  const power = data.power_zones?.fractions || {};
  const hr = data.heart_rate_zones?.fractions || {};
  const rows = [
    ["主要刺激", data.main_stimulus],
    ["强度标签", data.intensity_label],
    ["FTP", data.thresholds?.functional_threshold_power],
    ["最大心率", data.thresholds?.max_heart_rate],
  ];
  els.tabContent.innerHTML = `
    ${table(rows)}
    <h3>功率区间</h3>
    ${zoneTable(power, data.power_zones?.seconds_estimate)}
    <h3>心率区间</h3>
    ${zoneTable(hr, data.heart_rate_zones?.seconds_estimate)}
  `;
}

function renderSegments(data = {}) {
  const segments = data.segments || [];
  if (!segments.length) {
    els.tabContent.innerHTML = `<div class="empty">没有分段数据。</div>`;
    return;
  }
  const rows = segments.map((s) => [
    `${s.start_min}-${s.end_min} min`,
    s.type,
    `${s.duration_seconds}s`,
    valueWithUnit(s.avg_power, "W"),
    valueWithUnit(s.avg_heart_rate, "bpm"),
    valueWithUnit(s.avg_cadence, "rpm"),
  ]);
  els.tabContent.innerHTML = `<p>${escapeHtml(data.structure_label || "")}</p>` + table(rows, ["时间", "类型", "时长", "功率", "心率", "踏频"]);
}

function renderFatigue(data = {}) {
  const metrics = data.metrics || {};
  const rows = [
    ["功率变化", percent(metrics.power_change_percent)],
    ["速度变化", percent(metrics.speed_change_percent)],
    ["心率变化", valueWithUnit(metrics.heart_rate_change_bpm, "bpm")],
    ["踏频变化", valueWithUnit(metrics.cadence_change_rpm, "rpm")],
    ["HR/功率解耦", percent(metrics.hr_power_decoupling_percent)],
    ["VI", metrics.variability_index],
  ];
  els.tabContent.innerHTML = `
    ${table(rows)}
    <h3>解释限制</h3>
    ${(data.caveats || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("") || "<p>无</p>"}
  `;
}

function renderReports(reports) {
  if (!reports.length) {
    els.tabContent.innerHTML = `<div class="empty">还没有保存的大模型报告。勾选“保存报告”后发起对话可写入这里。</div>`;
    return;
  }
  els.tabContent.innerHTML = reports
    .map((report) => `
      <div class="report-block">
        <h3>#${report.id} · ${escapeHtml(report.report_type)} · ${escapeHtml(report.created_at)}</h3>
        <pre class="report-block">${escapeHtml(report.markdown || "")}</pre>
      </div>
    `)
    .join("");
}

function renderRaw(detail) {
  els.tabContent.innerHTML = `<pre class="code-block">${escapeHtml(JSON.stringify(detail, null, 2))}</pre>`;
}

async function analyzeSelected() {
  if (!state.selectedId) return;
  setStatus("analyzing");
  await fetchJson(`/api/activities/${state.selectedId}/analyze`, { method: "POST", body: "{}" });
  await selectActivity(state.selectedId);
  setStatus("analysis updated");
}

async function sendQuestion(event) {
  event.preventDefault();
  if (!state.selectedId) return;
  const question = els.questionInput.value.trim();
  if (!question) return;
  appendMessage(question, "user");
  els.questionInput.value = "";
  setStatus("chatting");
  try {
    const result = await fetchJson("/api/chat/activity", {
      method: "POST",
      body: JSON.stringify({
        question,
        activity_id: state.selectedId,
        history_days: 30,
        save_report: els.saveReport.checked,
      }),
    });
    appendMessage(result.answer || "(empty)", "assistant");
    if (els.saveReport.checked) {
      await selectActivity(state.selectedId);
    }
    setStatus("ready");
  } catch (error) {
    appendMessage(error.message, "error");
    setStatus("error");
  }
}

function appendMessage(text, type) {
  const div = document.createElement("div");
  div.className = `message ${type}`;
  div.textContent = text;
  els.chatLog.appendChild(div);
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
}

function table(rows, headers = ["项目", "值"]) {
  const head = headers.map((item) => `<th>${escapeHtml(item)}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(format(cell))}</td>`).join("")}</tr>`)
    .join("");
  return `<table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function zoneTable(fractions = {}, seconds = {}) {
  const rows = Object.keys(fractions).map((key) => [
    key,
    `${(Number(fractions[key]) * 100).toFixed(1)}%`,
    seconds?.[key] ? `${seconds[key]}s` : "-",
  ]);
  return table(rows, ["区间", "比例", "估算时长"]);
}

function issuesBlock(issues) {
  if (!issues.length) return "";
  return `<h3>问题</h3>` + issues.map((item) => `<p>${escapeHtml(item.severity)} · ${escapeHtml(item.message)}</p>`).join("");
}

function yesNo(value) {
  return value ? "有" : "无";
}

function valueWithUnit(value, unit) {
  return value === null || value === undefined ? "-" : `${value} ${unit}`;
}

function percent(value) {
  return value === null || value === undefined ? "-" : `${value}%`;
}

function format(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

els.refreshBtn.addEventListener("click", loadActivities);
els.analyzeBtn.addEventListener("click", analyzeSelected);
els.chatForm.addEventListener("submit", sendQuestion);
document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    state.tab = button.dataset.tab;
    renderTab();
  });
});

loadActivities().catch((error) => {
  setStatus("error");
  els.activityList.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
});
