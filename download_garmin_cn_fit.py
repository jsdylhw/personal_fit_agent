#!/usr/bin/env python3
import argparse
import io
import json
import os
import re
import time
import zipfile
from pathlib import Path

import requests


CONNECT_WEB = "https://connect.garmin.cn"
CONNECT_API = "https://connectapi.garmin.cn"
DEFAULT_OUTPUT_DIR = "garmin_cn_fit_files"
DEFAULT_TOKENSTORE = ".garmin_cn_tokens"


def read_config(path):
    if not path or not Path(path).exists():
        return {}
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("读取 config.yaml 需要安装 pyyaml: pip install pyyaml") from exc
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def cfg_get(config, *names, default=None):
    for name in names:
        value = config.get(name)
        if value not in (None, ""):
            return value
    return default


def normalize_cookie(cookie):
    cookie = (cookie or "").strip()
    if not cookie or cookie in ("JWT_WEB", "JWT_WEB="):
        return ""
    if "=" not in cookie:
        return f"JWT_WEB={cookie}"
    return cookie


def load_cookie_file(path):
    if not path:
        return ""
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return ""

    if text.startswith("[") or text.startswith("{"):
        data = json.loads(text)
        if isinstance(data, dict):
            if "cookies" in data:
                data = data["cookies"]
            else:
                return "; ".join(f"{name}={value}" for name, value in data.items())
        if isinstance(data, list):
            pairs = []
            for item in data:
                domain = str(item.get("domain", ""))
                if "garmin.cn" not in domain:
                    continue
                name = item.get("name")
                value = item.get("value")
                if name and value is not None:
                    pairs.append(f"{name}={value}")
            return "; ".join(pairs)

    pairs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            domain, _, _, _, _, name, value = parts[:7]
            if "garmin.cn" in domain:
                pairs.append(f"{name}={value}")
        elif "=" in line and "Cookie:" not in line:
            pairs.append(line)
    return "; ".join(pairs)


def load_headers(path):
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {
            item["name"]: item["value"]
            for item in data
            if "name" in item and "value" in item
        }
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    raise ValueError("headers 文件只支持 JSON object 或 Chrome headers array")


def safe_filename(value):
    value = str(value or "activity").strip()
    value = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", value)
    value = re.sub(r"\s+", " ", value)
    return value[:120] or "activity"


def save_original_as_fit(raw_bytes, output_dir, activity):
    activity_id = activity.get("activityId")
    activity_name = activity.get("activityName") or f"activity_{activity_id}"
    start_time = activity.get("startTimeLocal") or "unknown"
    base_name = safe_filename(f"{start_time}_{activity_name}_{activity_id}")

    output_dir.mkdir(parents=True, exist_ok=True)
    if not zipfile.is_zipfile(io.BytesIO(raw_bytes)):
        fit_path = output_dir / f"{base_name}.fit"
        fit_path.write_bytes(raw_bytes)
        return [fit_path]

    saved = []
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
        fit_names = [name for name in zf.namelist() if name.lower().endswith(".fit")]
        if not fit_names:
            zip_path = output_dir / f"{base_name}.zip"
            zip_path.write_bytes(raw_bytes)
            raise RuntimeError(f"原始包里没有 .fit 文件，已保存 zip: {zip_path}")
        for index, member in enumerate(fit_names, start=1):
            suffix = "" if len(fit_names) == 1 else f"_{index}"
            fit_path = output_dir / f"{base_name}{suffix}.fit"
            fit_path.write_bytes(zf.read(member))
            saved.append(fit_path)
    return saved


class GarminConnectPasswordDownloader:
    name = "账号密码"

    def __init__(self, username, password, tokenstore, proxy=None, disable_curl_cffi=True):
        self.username = username
        self.password = password
        self.tokenstore = tokenstore
        self.proxy = proxy
        self.disable_curl_cffi = disable_curl_cffi
        self.client = None
        self.Garmin = None

    def login(self):
        if self.proxy:
            os.environ["HTTP_PROXY"] = self.proxy
            os.environ["HTTPS_PROXY"] = self.proxy
            os.environ["http_proxy"] = self.proxy
            os.environ["https_proxy"] = self.proxy

        from garminconnect import Garmin
        from garminconnect import client as garmin_client

        cn_di_url = "https://diauth.garmin.cn/di-oauth2-service/oauth/token"
        if getattr(garmin_client, "DI_TOKEN_URL", None) != cn_di_url:
            garmin_client.DI_TOKEN_URL = cn_di_url
        if self.disable_curl_cffi:
            garmin_client.HAS_CFFI = False

        self.Garmin = Garmin
        self.client = Garmin(self.username, self.password, is_cn=True)
        self.client.login(self.tokenstore)

    def list_activities(self, count):
        return self.client.get_activities(0, count)

    def download_original(self, activity_id):
        return self.client.download_activity(
            activity_id,
            self.Garmin.ActivityDownloadFormat.ORIGINAL,
        )


class BrowserCookieDownloader:
    name = "浏览器 Cookie"

    def __init__(
        self,
        cookie,
        proxy=None,
        api_mode="web_proxy",
        retries=3,
        extra_headers=None,
        debug=False,
    ):
        self.cookie = normalize_cookie(cookie)
        if not self.cookie:
            raise ValueError("缺少 Garmin 中国区 Cookie")
        self.proxy = proxy
        self.api_mode = api_mode
        self.retries = max(1, int(retries))
        self.extra_headers = extra_headers or {}
        self.debug = debug
        self.session = requests.Session()
        self.proxies = {"http": proxy, "https": proxy} if proxy else None

    def login(self):
        return None

    def headers(self, accept="application/json"):
        headers = {
            "Accept": accept,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cookie": self.cookie,
            "DI-Backend": "connectapi.garmin.cn",
            "NK": "NT",
            "Origin": CONNECT_WEB,
            "Referer": f"{CONNECT_WEB}/app/",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        }
        headers.update(self.extra_headers)
        headers["Accept"] = accept
        headers["Cookie"] = self.cookie
        return headers

    def candidate_urls(self, path):
        path = path.lstrip("/")
        app_proxy = f"{CONNECT_WEB}/app/proxy/{path}"
        modern_proxy = f"{CONNECT_WEB}/modern/proxy/{path}"
        connectapi = f"{CONNECT_API}/{path}"
        if self.api_mode == "connectapi":
            return [connectapi, app_proxy, modern_proxy]
        return [app_proxy, modern_proxy, connectapi]

    def get(self, path, params=None, accept="application/json", timeout=40):
        last_response = None
        last_error = None
        for url in self.candidate_urls(path):
            for attempt in range(1, self.retries + 1):
                try:
                    response = self.session.get(
                        url,
                        params=params,
                        headers=self.headers(accept),
                        proxies=self.proxies,
                        timeout=timeout,
                    )
                    if response.ok:
                        if self.debug:
                            print(f"DEBUG ok {response.status_code}: {response.url}")
                        return response
                    if self.debug:
                        body = response.text[:200].replace("\n", " ")
                        print(f"DEBUG fail {response.status_code}: {response.url}; body={body}")
                    last_response = response
                    if response.status_code in (401, 403):
                        break
                    if response.status_code != 429:
                        break
                except requests.RequestException as exc:
                    last_error = exc
                if attempt < self.retries:
                    time.sleep(attempt)

        if last_response is not None:
            body = last_response.text[:500].replace("\n", " ")
            raise RuntimeError(
                f"Garmin 请求失败: HTTP {last_response.status_code} {last_response.url}; body={body}"
            )
        raise RuntimeError(f"Garmin 网络请求失败: {last_error}") from last_error

    def list_activities(self, count):
        response = self.get(
            "/activitylist-service/activities/search/activities",
            params={"start": "0", "limit": str(count)},
        )
        try:
            data = response.json()
        except ValueError as exc:
            content_type = response.headers.get("content-type", "")
            body = response.text[:500].replace("\n", " ")
            raise RuntimeError(
                f"活动列表返回的不是 JSON: HTTP {response.status_code} {response.url}; "
                f"content-type={content_type}; body={body}"
            ) from exc
        if not isinstance(data, list):
            raise RuntimeError(f"活动列表返回格式异常: {json.dumps(data, ensure_ascii=False)[:500]}")
        return data

    def download_original(self, activity_id):
        response = self.get(
            f"/download-service/files/activity/{activity_id}",
            accept="*/*",
            timeout=90,
        )
        return response.content


def build_args():
    parser = argparse.ArgumentParser(description="从 Garmin 中国区下载最近活动 FIT 文件")
    parser.add_argument("--config", default="config.yaml", help="配置文件，默认 ./config.yaml")
    parser.add_argument("--username", help="Garmin 中国区账号")
    parser.add_argument("--password", help="Garmin 中国区密码")
    parser.add_argument("--cookie", help="浏览器 Cookie，支持整段 Cookie 或单独 JWT_WEB 值")
    parser.add_argument("--cookie-file", help="浏览器导出的 cookies.txt 或 JSON cookies 文件")
    parser.add_argument("--headers", help="从浏览器 Network 复制出的请求头 JSON 文件")
    parser.add_argument("--count", type=int, help="下载最近几条活动")
    parser.add_argument("--output-dir", help="FIT 输出目录")
    parser.add_argument("--proxy", help="HTTP 代理，例如 http://127.0.0.1:7897")
    parser.add_argument("--tokenstore", help="账号密码登录 token 缓存目录")
    parser.add_argument("--api-mode", choices=("web_proxy", "connectapi"), help="Cookie 模式 API 路径")
    parser.add_argument("--retries", type=int, help="Cookie 模式请求重试次数")
    parser.add_argument("--debug", action="store_true", help="打印 Garmin 请求 URL、状态码和截断响应")
    return parser.parse_args()


def choose_downloader(args, config):
    proxy = args.proxy or os.getenv("GARMIN_PROXY") or cfg_get(config, "garmin_proxy")
    username = (
        args.username
        or os.getenv("GARMIN_USERNAME")
        or cfg_get(config, "garmin_username", "username")
    )
    password = (
        args.password
        or os.getenv("GARMIN_PASSWORD")
        or cfg_get(config, "garmin_password", "password")
    )
    tokenstore = (
        args.tokenstore
        or cfg_get(config, "garmin_tokenstore", "tokenstore")
        or DEFAULT_TOKENSTORE
    )
    disable_curl_cffi = bool(cfg_get(config, "disable_curl_cffi", default=True))

    extra_headers = load_headers(args.headers or cfg_get(config, "garmin_headers_file"))
    cookie = (
        args.cookie
        or load_cookie_file(args.cookie_file or cfg_get(config, "garmin_cookie_file"))
        or os.getenv("GARMIN_CN_COOKIE")
        or cfg_get(config, "garmin_auth_cookie", "garmin_jwt_web")
        or extra_headers.get("Cookie")
    )

    strategies = []
    if username and password:
        strategies.append(
            GarminConnectPasswordDownloader(
                username=username,
                password=password,
                tokenstore=tokenstore,
                proxy=proxy,
                disable_curl_cffi=disable_curl_cffi,
            )
        )
    if cookie:
        strategies.append(
            BrowserCookieDownloader(
                cookie=cookie,
                proxy=proxy,
                api_mode=args.api_mode or cfg_get(config, "garmin_api_mode", default="web_proxy"),
                retries=args.retries or int(cfg_get(config, "garmin_retry_count", default=3)),
                extra_headers=extra_headers,
                debug=bool(args.debug or cfg_get(config, "debug", default=False)),
            )
        )

    if not strategies:
        raise RuntimeError("请在 config.yaml 配置 garmin_username/garmin_password，或 garmin_auth_cookie")
    return strategies


def main():
    args = build_args()
    config = read_config(args.config)
    count = args.count or int(cfg_get(config, "download_count", default=5))
    output_dir = Path(args.output_dir or cfg_get(config, "output_dir", default=DEFAULT_OUTPUT_DIR))

    last_error = None
    activities = None
    downloader = None
    for strategy in choose_downloader(args, config):
        try:
            print(f"尝试使用{strategy.name}登录 Garmin 中国区...")
            strategy.login()
            print(f"读取 Garmin 中国区最近 {count} 条活动...")
            activities = strategy.list_activities(count)
            downloader = strategy
            print(f"{strategy.name}方式可用。")
            break
        except Exception as exc:
            last_error = exc
            print(f"{strategy.name}方式失败: {exc}")

    if downloader is None:
        raise RuntimeError(f"所有登录方式都失败: {last_error}") from last_error
    if not activities:
        print("没有找到活动。")
        return

    print(f"开始下载 FIT，输出目录: {output_dir}")
    for index, activity in enumerate(activities, start=1):
        activity_id = activity.get("activityId")
        name = activity.get("activityName") or f"activity_{activity_id}"
        start_time = activity.get("startTimeLocal") or "unknown"
        print(f"[{index}/{len(activities)}] {name} | {start_time} | {activity_id}")
        raw_bytes = downloader.download_original(activity_id)
        saved_paths = save_original_as_fit(raw_bytes, output_dir, activity)
        for path in saved_paths:
            print(f"  已保存: {path}")

    print("下载完成。")


if __name__ == "__main__":
    main()
