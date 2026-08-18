# 国外地点检索与骑行算路 Demo

这个独立 Demo 验证两项能力：

- 使用 Google Places Text Search 检索国外城市、车站、景点和 POI。
- 使用 GraphHopper 托管 Directions API 的 `bike` profile 生成骑行路线。

它不下载国外 OSM/PBF，不依赖本地 GraphHopper，也不检查街景。浏览器地图使用 Leaflet 和在线 OpenStreetMap 瓦片；Google 与 GraphHopper Key 只保留在本地 Python 进程。

## 配置

推荐复制根目录配置示例并填写：

```yaml
google_maps:
  api_key: "your-google-maps-api-key"

graphhopper:
  api_key: "your-graphhopper-api-key"
```

Google Cloud 项目需要启用 Places API (New)。也可以在 Demo 目录创建 `.env`：

```bash
cp demo/global_cycling_router/.env.example demo/global_cycling_router/.env
```

## 启动

```bash
demo/global_cycling_router/run_local.sh
```

打开 <http://127.0.0.1:8091>，分别搜索起点和终点，选择结果后点击“生成骑行路线”。地点和路线数据统一使用 WGS-84；GeoJSON 几何坐标顺序为 `longitude, latitude`。

## 本地 API

地点检索：

```bash
curl -G 'http://127.0.0.1:8091/api/places' \
  --data-urlencode 'q=宇治站 日本' \
  --data-urlencode 'limit=5'
```

骑行算路：

```bash
curl -G 'http://127.0.0.1:8091/api/route' \
  --data-urlencode 'point=34.8908,135.8009' \
  --data-urlencode 'point=34.9671,135.7727'
```

第一版只验证地点检索和真实骑行算路，不接 Main Agent、Strava、Google Elevation、GPX 导出或 Rider Tracker。

## 测试

测试不会调用付费服务：

```bash
pytest -q demo/global_cycling_router
node --check demo/global_cycling_router/web/app.js
```
