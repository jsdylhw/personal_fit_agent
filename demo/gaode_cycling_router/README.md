# 高德骑行路线 Demo

这是与 `demo/osm_cycling_router/` 并行的国内地图验证实验：

- 底图与两点连接段使用高德；连接段调用 **高德 Web Service 骑行路径规划**。
- 路线组合算法不重写：继续复用已有的主路段顺序、正反方向、回头路惩罚、候选排序和 Strava 骨架拼接逻辑。
- 原始 FIT、OSM、Strava 几何一律保持 WGS‑84；仅在高德调用/显示边界转换为 GCJ‑02，避免污染已有数据。

高德骑行 Web API 只接受一对起终点，因此旧算法中“经走廊锚点”的候选会被拆成多条相邻的高德骑行连接段再拼接；每一段仍是真实的高德骑行导航，不退化成汽车导航。

## 启动

1. 在高德开放平台申请 **Web 服务 API Key** 与 **JS API Key**，并为 JS Key 配置本地 Referer 限制。
2. 推荐直接在仓库根目录 `config.yaml` 填写 `amap.web_service_key`、`amap.js_key`、`amap.security_js_code`（该文件已忽略）。也可复制并填写 Demo 内的本地配置：

   ```bash
   cd demo/gaode_cycling_router
   cp .env.example .env
   ```

3. 启动：

   ```bash
   ./run_local.sh
   # 浏览器打开 http://127.0.0.1:8090
   ```

Demo 默认读取自身 `data/` 下已生成的高德探针。可用 `ROUTE_PROBE_DIR=../osm_cycling_router/data/route-probes` 改为读取旧 OSM Demo 的路线探针；读取时会自动把 WGS‑84 几何转换为 GCJ‑02，因此能正确叠加到高德底图。

## 以高德骑行重组已确认骨架

对已从 Strava 确认顺序的路段，可以直接使用高德替代原有 GraphHopper 连接段。输入保持 WGS‑84，输出是可直接显示在高德底图上的 GCJ‑02 GeoJSON：

```bash
python -m demo.gaode_cycling_router.compose_segments \
  --input demo/osm_cycling_router/data/jiangxinzhou-via-jiajiang-bridge.geojson \
  --segment-id 14356032 --segment-id 11875601 --segment-id 17544798 \
  --start '32.022624,118.783559' --target-km 55 --near-handoff-m 100 \
  --start-name '夫子庙' \
  --output demo/gaode_cycling_router/data/fuzimiao-jiangxinzhou-amap.geojson
```

该命令调用现有 `plan_ordered_segment_route`：路段顺序、短接缝核验标记、距离/回头路评分保持不变，只有每个连接段改为高德骑行导航。输出文件默认可在网页中直接载入。

## 安全与范围

- `AMAP_WEB_SERVICE_KEY` 仅在本地 Python 服务中使用，浏览器不会收到它。
- JS API Key 必须发送给浏览器；Demo 为方便本地测试，`securityJsCode` 也走浏览器直配。生产环境应按高德文档改为 `serviceHost` 反向代理，并限制 Key 的 Referer/IP。
- 目前是验证 Demo，不接入 Main Agent，也不替换原 OSM/GraphHopper 版本。
