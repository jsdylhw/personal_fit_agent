#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import os
import re
import zipfile
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = "config.yaml"
DEFAULT_OUTPUT_DIR = "garmin_cn_fit_files"
DEFAULT_TOKENSTORE = ".garmin_cn_tokens"
CN_DI_TOKEN_URL = "https://diauth.garmin.cn/di-oauth2-service/oauth/token"


def read_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        return {}
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("Reading config.yaml requires pyyaml: pip install pyyaml") from exc

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a YAML object: {config_path}")
    return data


def cfg_get(config: dict[str, Any], name: str, default: Any = None) -> Any:
    value = config.get(name)
    return default if value in (None, "") else value


def cfg_bool(config: dict[str, Any], name: str, default: bool = False) -> bool:
    value = cfg_get(config, name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def safe_filename(value: Any) -> str:
    text = str(value or "activity").strip()
    text = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", text)
    text = re.sub(r"\s+", " ", text)
    return text[:120] or "activity"


def activity_base_name(activity: dict[str, Any]) -> str:
    activity_id = activity.get("activityId")
    activity_name = activity.get("activityName") or f"activity_{activity_id}"
    start_time = activity.get("startTimeLocal") or "unknown"
    return safe_filename(f"{start_time}_{activity_name}_{activity_id}")


def existing_fit_paths(output_dir: Path, activity: dict[str, Any]) -> list[Path]:
    base_name = activity_base_name(activity)
    if not output_dir.exists():
        return []
    return sorted(output_dir.glob(f"{base_name}*.fit"))


def save_original_as_fit(raw_bytes: bytes, output_dir: Path, activity: dict[str, Any]) -> list[Path]:
    base_name = activity_base_name(activity)

    output_dir.mkdir(parents=True, exist_ok=True)
    if not zipfile.is_zipfile(io.BytesIO(raw_bytes)):
        fit_path = output_dir / f"{base_name}.fit"
        fit_path.write_bytes(raw_bytes)
        return [fit_path]

    saved_paths: list[Path] = []
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
        fit_names = [name for name in zf.namelist() if name.lower().endswith(".fit")]
        if not fit_names:
            zip_path = output_dir / f"{base_name}.zip"
            zip_path.write_bytes(raw_bytes)
            raise RuntimeError(f"No .fit file found in original archive; saved zip to: {zip_path}")

        for index, member in enumerate(fit_names, start=1):
            suffix = "" if len(fit_names) == 1 else f"_{index}"
            fit_path = output_dir / f"{base_name}{suffix}.fit"
            fit_path.write_bytes(zf.read(member))
            saved_paths.append(fit_path)

    return saved_paths


class GarminChinaDownloader:
    def __init__(
        self,
        *,
        username: str,
        password: str,
        tokenstore: str | Path = DEFAULT_TOKENSTORE,
        proxy: str | None = None,
        disable_curl_cffi: bool = False,
    ) -> None:
        self.username = username
        self.password = password
        self.tokenstore = str(tokenstore)
        self.proxy = proxy
        self.disable_curl_cffi = disable_curl_cffi
        self.client = None
        self.Garmin = None

    def login(self) -> None:
        if self.proxy:
            os.environ["HTTP_PROXY"] = self.proxy
            os.environ["HTTPS_PROXY"] = self.proxy
            os.environ["http_proxy"] = self.proxy
            os.environ["https_proxy"] = self.proxy

        from garminconnect import Garmin
        from garminconnect import client as garmin_client

        garmin_client.DI_TOKEN_URL = CN_DI_TOKEN_URL
        if self.disable_curl_cffi:
            garmin_client.HAS_CFFI = False

        self.Garmin = Garmin
        self.client = Garmin(self.username, self.password, is_cn=True)
        self.client.login(self.tokenstore)

    def list_activities(self, count: int) -> list[dict[str, Any]]:
        if self.client is None:
            raise RuntimeError("Downloader is not logged in")
        return self.client.get_activities(0, count)

    def download_original(self, activity_id: Any) -> bytes:
        if self.client is None or self.Garmin is None:
            raise RuntimeError("Downloader is not logged in")
        return self.client.download_activity(
            activity_id,
            self.Garmin.ActivityDownloadFormat.ORIGINAL,
        )


def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download recent Garmin China activities as FIT files.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Config file path.")
    parser.add_argument("--count", type=int, help="Number of recent activities to download.")
    parser.add_argument("--output-dir", help="Directory for downloaded FIT files.")
    return parser.parse_args()


def build_downloader(config: dict[str, Any]) -> GarminChinaDownloader:
    username = cfg_get(config, "garmin_username")
    password = cfg_get(config, "garmin_password")
    if not username or not password:
        raise RuntimeError("Please set garmin_username and garmin_password in config.yaml")

    return GarminChinaDownloader(
        username=str(username),
        password=str(password),
        tokenstore=cfg_get(config, "garmin_tokenstore", DEFAULT_TOKENSTORE),
        proxy=cfg_get(config, "garmin_proxy"),
        disable_curl_cffi=cfg_bool(config, "disable_curl_cffi", default=False),
    )


def main() -> None:
    args = build_args()
    config = read_config(args.config)
    count = args.count or int(cfg_get(config, "download_count", 5))
    output_dir = Path(args.output_dir or cfg_get(config, "output_dir", DEFAULT_OUTPUT_DIR))

    downloader = build_downloader(config)
    print("Logging in to Garmin China...")
    downloader.login()

    print(f"Reading latest {count} activities...")
    activities = downloader.list_activities(count)
    if not activities:
        print("No activities found.")
        return

    print(f"Downloading FIT files to: {output_dir}")
    for index, activity in enumerate(activities, start=1):
        activity_id = activity.get("activityId")
        name = activity.get("activityName") or f"activity_{activity_id}"
        start_time = activity.get("startTimeLocal") or "unknown"
        print(f"[{index}/{len(activities)}] {name} | {start_time} | {activity_id}")

        existing_paths = existing_fit_paths(output_dir, activity)
        if existing_paths:
            for path in existing_paths:
                print(f"  skipped existing: {path}")
            continue

        raw_bytes = downloader.download_original(activity_id)
        for path in save_original_as_fit(raw_bytes, output_dir, activity):
            print(f"  saved: {path}")

    print("Download complete.")


if __name__ == "__main__":
    main()
