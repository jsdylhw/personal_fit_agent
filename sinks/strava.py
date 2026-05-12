from __future__ import annotations


class StravaSink:
    name = "strava"

    def upload_fit(self, fit_path: str, *, title: str | None = None) -> dict:
        raise NotImplementedError("Strava 上传后续在这里接入。")

    def update_description(self, activity_id: str, markdown: str) -> dict:
        raise NotImplementedError("Strava 描述更新后续在这里接入。")
