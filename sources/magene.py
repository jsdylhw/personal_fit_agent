from __future__ import annotations


class MageneSource:
    name = "magene"

    def sync_latest(self, limit: int = 10) -> list[dict]:
        raise NotImplementedError("迈金下载接入后在这里实现，返回已归档的 activity rows。")
