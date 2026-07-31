const map = L.map("map").setView([30.2420, 120.0960], 13);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "© OpenStreetMap contributors",
}).addTo(map);

const statusNode = document.querySelector("#status");
const summaryNode = document.querySelector("#route-summary");
const placesNode = document.querySelector("#places");
const modeNode = document.querySelector("#planner-mode");
const routeHintNode = document.querySelector("#route-hint");
const destinationFieldNode = document.querySelector("#destination-field");
const loopDistanceFieldNode = document.querySelector("#loop-distance-field");
const loopCandidatesNode = document.querySelector("#loop-candidates");
let endpoints = [];
let endpointLayer = L.layerGroup().addTo(map);
let routeLayer = L.geoJSON(null, { style: { color: "#1c7c4a", weight: 5, opacity: .9 } }).addTo(map);
let placeLayer = L.layerGroup().addTo(map);
// FeatureGroup keeps the same layer-management API as LayerGroup and also
// exposes getBounds(), needed to fit all generated loop candidates at once.
let loopLayer = L.featureGroup().addTo(map);
let loopRoutes = [];

function pointText(latlng) { return `${latlng.lat.toFixed(6)},${latlng.lng.toFixed(6)}`; }
function parsePoint(value) {
  const [lat, lon] = value.split(",").map(Number);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) throw new Error("坐标格式应为 纬度,经度");
  return L.latLng(lat, lon);
}
function setStatus(message, type = "") {
  statusNode.textContent = message;
  statusNode.className = `status ${type}`;
}
async function api(path) {
  const response = await fetch(path);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "本地服务请求失败");
  return payload;
}
function setEndpoints(next) {
  endpoints = next;
  endpointLayer.clearLayers();
  document.querySelector("#origin").value = endpoints[0] ? pointText(endpoints[0]) : "";
  document.querySelector("#destination").value = endpoints[1] ? pointText(endpoints[1]) : "";
  if (endpoints[0]) {
    L.marker(endpoints[0], { title: "起点" }).bindTooltip("起点").addTo(endpointLayer);
  }
  if (endpoints[1]) {
    L.marker(endpoints[1], { title: "终点" }).bindTooltip("终点").addTo(endpointLayer);
  }
}
function formatDistance(meters) { return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`; }
function formatDurationMilliseconds(milliseconds) {
  const minutes = Math.round(milliseconds / 60000);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}小时${minutes % 60}分` : `${minutes} 分钟`;
}
function formatDurationSeconds(seconds) { return formatDurationMilliseconds(seconds * 1000); }
function clearLoopRoutes() {
  loopLayer.clearLayers();
  loopRoutes = [];
  loopCandidatesNode.replaceChildren();
}
function clearPointRoute() { routeLayer.clearLayers(); }
function updatePlannerMode(clearSelection = false) {
  const isFreeLoop = modeNode.value === "free-loop";
  destinationFieldNode.hidden = isFreeLoop;
  loopDistanceFieldNode.hidden = !isFreeLoop;
  document.querySelector("#route-button").hidden = isFreeLoop;
  document.querySelector("#free-loop-button").hidden = !isFreeLoop;
  routeHintNode.textContent = isFreeLoop
    ? "在地图上点击一个起点，再生成多条本地自由环线。距离是目标值，结果会按距离误差和差异性筛选。"
    : "在地图上依次点击起点、终点；第三次点击会重设起点。";
  if (clearSelection) setEndpoints([]);
  clearPointRoute();
  clearLoopRoutes();
  summaryNode.textContent = "尚未计算";
}
async function calculateRoute() {
  try {
    const origin = parsePoint(document.querySelector("#origin").value);
    const destination = parsePoint(document.querySelector("#destination").value);
    setEndpoints([origin, destination]);
    setStatus("正在计算路线…");
    const profile = document.querySelector("#profile").value;
    const params = new URLSearchParams({ point: pointText(origin), profile, points_encoded: "false" });
    params.append("point", pointText(destination));
    const data = await api(`/api/route?${params}`);
    const path = data.paths[0];
    clearLoopRoutes();
    routeLayer.clearLayers().addData({ type: "LineString", coordinates: path.points.coordinates });
    map.fitBounds(routeLayer.getBounds(), { padding: [30, 30] });
    summaryNode.textContent = `${formatDistance(path.distance)} · ${formatDurationMilliseconds(path.time)}${path.ascend ? ` · 爬升 ${Math.round(path.ascend)} m` : ""}`;
    setStatus("本地路由已完成", "ready");
  } catch (error) {
    summaryNode.textContent = error.message;
    setStatus("路线请求失败", "error");
  }
}
function selectLoop(index) {
  loopRoutes.forEach(({ layer }, candidateIndex) => {
    layer.setStyle(candidateIndex === index
      ? { color: "#f5a623", weight: 7, opacity: 1 }
      : { color: "#4e9e71", weight: 4, opacity: .55 });
  });
  const candidate = loopRoutes[index].candidate;
  summaryNode.textContent = `候选 ${index + 1} · ${formatDistance(candidate.distance_m)} · ${formatDurationSeconds(candidate.duration_s)} · 距离误差 ${candidate.distance_error_pct}%${candidate.ascend_m ? ` · 爬升 ${Math.round(candidate.ascend_m)} m` : ""}`;
}
function renderFreeLoops(candidates) {
  clearLoopRoutes();
  candidates.forEach((candidate, index) => {
    const layer = L.geoJSON(candidate.geometry, { style: { color: "#4e9e71", weight: 4, opacity: .55 } }).addTo(loopLayer);
    layer.on("click", () => selectLoop(index));
    loopRoutes.push({ candidate, layer });
    const item = document.createElement("li");
    item.className = "loop-candidate";
    item.innerHTML = `<strong>候选 ${index + 1}</strong><small>${formatDistance(candidate.distance_m)} · ${formatDurationSeconds(candidate.duration_s)} · 误差 ${candidate.distance_error_pct}%</small>`;
    item.addEventListener("click", () => selectLoop(index));
    loopCandidatesNode.append(item);
  });
  if (loopRoutes.length) {
    map.fitBounds(loopLayer.getBounds(), { padding: [30, 30] });
    selectLoop(0);
  }
}
async function calculateFreeLoop() {
  try {
    const origin = parsePoint(document.querySelector("#origin").value);
    const distanceKm = Number(document.querySelector("#loop-distance").value);
    if (!Number.isFinite(distanceKm) || distanceKm < 1 || distanceKm > 300) throw new Error("目标距离应在 1–300 km 之间");
    setEndpoints([origin]);
    clearPointRoute();
    setStatus("正在从本地路网生成自由环线…");
    const data = await api(`/api/free-loop?${new URLSearchParams({
      point: pointText(origin), distance_km: String(distanceKm), profile: document.querySelector("#profile").value, count: "3",
    })}`);
    if (!data.candidates.length) throw new Error(`未找到符合 ±${data.distance_tolerance_pct}% 距离容差的环线`);
    renderFreeLoops(data.candidates);
    setStatus(`本地生成 ${data.count} 条自由环线（尝试 ${data.attempts} 个 seed）`, "ready");
  } catch (error) {
    clearLoopRoutes();
    summaryNode.textContent = error.message;
    setStatus("自由环线生成失败", "error");
  }
}
function showPlaces(places) {
  placesNode.replaceChildren();
  placeLayer.clearLayers();
  if (!places.length) {
    placesNode.textContent = "没有匹配的 OSM 风景点。";
    return;
  }
  for (const place of places) {
    const marker = L.circleMarker([place.lat, place.lon], { radius: 7, color: "#d06b31", fillOpacity: .85 })
      .bindPopup(`<b>${place.name}</b><br>${place.category}`)
      .addTo(placeLayer);
    const item = document.createElement("li");
    const distance = place.distance_m == null ? "" : ` · ${formatDistance(place.distance_m)}`;
    item.innerHTML = `<strong>${place.name}</strong><small>${place.category}${distance}</small>`;
    item.addEventListener("click", () => { map.setView([place.lat, place.lon], 15); marker.openPopup(); });
    placesNode.append(item);
  }
}
async function searchPlaces() {
  try {
    const query = document.querySelector("#search-query").value.trim();
    if (!query) throw new Error("请输入地点名称");
    const center = map.getCenter();
    const data = await api(`/api/places/search?${new URLSearchParams({ q: query, near: pointText(center) })}`);
    showPlaces(data.places);
    setStatus(`找到 ${data.places.length} 个本地风景点`, "ready");
  } catch (error) { setStatus(error.message, "error"); }
}
async function nearbyPlaces() {
  try {
    const data = await api(`/api/places/nearby?${new URLSearchParams({ point: pointText(map.getCenter()), radius_m: "5000" })}`);
    showPlaces(data.places);
    setStatus(`找到 ${data.places.length} 个附近风景点`, "ready");
  } catch (error) { setStatus(error.message, "error"); }
}

map.on("click", (event) => {
  if (modeNode.value === "free-loop") {
    setEndpoints([event.latlng]);
    clearPointRoute();
    clearLoopRoutes();
  } else {
    setEndpoints(endpoints.length >= 2 ? [event.latlng] : [...endpoints, event.latlng]);
    clearLoopRoutes();
  }
});
document.querySelector("#route-button").addEventListener("click", calculateRoute);
document.querySelector("#free-loop-button").addEventListener("click", calculateFreeLoop);
modeNode.addEventListener("change", () => updatePlannerMode(true));
document.querySelector("#search-form").addEventListener("submit", (event) => { event.preventDefault(); searchPlaces(); });
document.querySelector("#nearby-button").addEventListener("click", nearbyPlaces);
updatePlannerMode();
api("/health").then(() => setStatus("本地服务已就绪", "ready")).catch(() => setStatus("本地服务不可用", "error"));
