"""Strava API 集成:OAuth 认证,FIT 上传,活动描述更新.

Token 管理策略:
- 优先用 client_id/secret/refresh_token 自动刷新短期 access_token.
- 其次直接用 access_token(手动配置).
- 每次实例化都会刷新 token,如果调用频繁建议复用实例.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from core.config import load_config

STRAVA_API_BASE = "https://www.strava.com/api/v3"
STRAVA_OAUTH_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_OAUTH_TOKEN_URL = "https://www.strava.com/oauth/token"


class StravaSink:
    """Strava v3 API 封装:上传,状态轮询,运动员信息,描述更新.

    Activity:write 权限是必需的——如果 token 缺少此权限,会在 API 报错时
    给出明确的重授权指引.
    """

    name = "strava"

    def __init__(self, config: dict[str, Any] | None = None):
        root_config = config if config is not None else load_config()
        self.config = root_config.get("strava", root_config)
        self.access_token = self._access_token()

    def upload_fit(
        self, fit_path: str, *,
        title: str | None = None, description: str | None = None,
        trainer: bool = False, commute: bool = False,
        external_id: str | None = None,
    ) -> dict[str, Any]:
        """上传 FIT 文件到 Strava,返回 upload 对象(含 upload_id 用于轮询)."""
        path = Path(fit_path)
        if not path.exists():
            raise FileNotFoundError(path)
        if path.suffix.lower() != ".fit":
            raise ValueError(f"Only .fit uploads are supported: {path}")

        data = {
            "data_type": "fit",
            "trainer": int(bool(trainer)),
            "commute": int(bool(commute)),
        }
        if title:
            data["name"] = title
        if description:
            data["description"] = description
        if external_id:
            # 用于去重:同一 external_id 不会重复创建活动
            data["external_id"] = external_id

        with path.open("rb") as f:
            response = requests.post(
                f"{STRAVA_API_BASE}/uploads",
                headers=self._headers(),
                data=data,
                files={"file": (path.name, f, "application/octet-stream")},
                timeout=float(self.config.get("timeout_seconds", 120)),
            )
        return self._json_or_raise(response)

    def get_upload(self, upload_id: int | str) -> dict[str, Any]:
        """查询上传处理状态."""
        response = requests.get(
            f"{STRAVA_API_BASE}/uploads/{upload_id}",
            headers=self._headers(),
            timeout=float(self.config.get("timeout_seconds", 120)),
        )
        return self._json_or_raise(response)

    def wait_for_upload(
        self, upload_id: int | str, *,
        timeout_seconds: int = 180, interval_seconds: int = 5,
    ) -> dict[str, Any]:
        """轮询直到上传处理完成(有 activity_id 或 error),或超时."""
        deadline = time.time() + timeout_seconds
        last = self.get_upload(upload_id)
        while time.time() < deadline:
            if last.get("activity_id") or last.get("error"):
                return last
            time.sleep(interval_seconds)
            last = self.get_upload(upload_id)
        return last

    def get_athlete(self) -> dict[str, Any]:
        """获取当前授权用户的信息(用于验证 token 是否有效)."""
        response = requests.get(
            f"{STRAVA_API_BASE}/athlete",
            headers=self._headers(),
            timeout=float(self.config.get("timeout_seconds", 120)),
        )
        return self._json_or_raise(response)

    def update_description(self, activity_id: str, markdown: str) -> dict[str, Any]:
        """更新已有 Strava 活动的描述."""
        response = requests.put(
            f"{STRAVA_API_BASE}/activities/{activity_id}",
            headers=self._headers(),
            data={"description": markdown},
            timeout=float(self.config.get("timeout_seconds", 120)),
        )
        return self._json_or_raise(response)

    def build_authorize_url(
        self, *, redirect_uri: str = "http://localhost",
        scope: str = "activity:read_all,activity:write",
        approval_prompt: str = "force",
    ) -> str:
        """生成 Strava OAuth 授权 URL,用户在浏览器中打开以授权应用."""
        client_id = self.config.get("client_id")
        if not client_id:
            raise RuntimeError("Please configure strava.client_id in config.yaml")
        query = urlencode({
            "client_id": client_id, "redirect_uri": redirect_uri,
            "response_type": "code", "approval_prompt": approval_prompt,
            "scope": scope,
        })
        return f"{STRAVA_OAUTH_AUTHORIZE_URL}?{query}"

    def exchange_authorization_code(self, code: str) -> dict[str, Any]:
        """用 OAuth 回调返回的 code 换取 refresh_token 和 access_token."""
        client_id = self.config.get("client_id")
        client_secret = self.config.get("client_secret")
        if not client_id or not client_secret:
            raise RuntimeError("Please configure strava.client_id and strava.client_secret in config.yaml")
        response = requests.post(
            STRAVA_OAUTH_TOKEN_URL,
            data={
                "client_id": client_id, "client_secret": client_secret,
                "code": code, "grant_type": "authorization_code",
            },
            timeout=float(self.config.get("timeout_seconds", 120)),
        )
        return self._json_or_raise(response)

    def _access_token(self) -> str:
        """获取 access_token:优先 refresh_token 刷新,其次直接配置的 token."""
        client_id = self.config.get("client_id")
        client_secret = self.config.get("client_secret")
        refresh_token = self.config.get("refresh_token")

        if client_id and client_secret and refresh_token:
            return self._refresh_access_token(client_id, client_secret, refresh_token)

        access_token = self.config.get("access_token")
        if access_token:
            return str(access_token)

        raise RuntimeError(
            "Please configure strava.access_token or "
            "strava.client_id/client_secret/refresh_token in config.yaml"
        )

    def _refresh_access_token(self, client_id: str, client_secret: str, refresh_token: str) -> str:
        response = requests.post(
            STRAVA_OAUTH_TOKEN_URL,
            data={
                "client_id": client_id, "client_secret": client_secret,
                "refresh_token": refresh_token, "grant_type": "refresh_token",
            },
            timeout=float(self.config.get("timeout_seconds", 120)),
        )
        data = self._json_or_raise(response)
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"Strava token refresh did not return access_token: {data}")
        return str(token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    @staticmethod
    def _json_or_raise(response: requests.Response) -> dict[str, Any]:
        """解析 JSON 响应,非 2xx 时抛出带上下文的 RuntimeError.

        特别处理 activity:write_permission missing 错误,
        给出清晰的重授权指引.
        """
        try:
            data = response.json()
        except ValueError:
            data = {"text": response.text[:1000]}
        if not response.ok:
            if _missing_activity_write(data):
                raise RuntimeError(
                    "Strava API failed: token is missing activity:write permission. "
                    "Generate a new Strava authorization URL with scope "
                    "'activity:read_all,activity:write', authorize it, exchange the returned code, "
                    "and update strava.refresh_token in config.yaml."
                )
            raise RuntimeError(f"Strava API failed: HTTP {response.status_code}; body={data}")
        return data if isinstance(data, dict) else {"data": data}


def _missing_activity_write(data: dict[str, Any]) -> bool:
    """检测 Strava 返回的错误中是否包含 activity:write 权限缺失."""
    errors = data.get("errors")
    if not isinstance(errors, list):
        return False
    for error in errors:
        if not isinstance(error, dict):
            continue
        if (
            error.get("resource") == "AccessToken"
            and error.get("field") == "activity:write_permission"
            and error.get("code") == "missing"
        ):
            return True
    return False
