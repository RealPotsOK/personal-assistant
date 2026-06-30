from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.config import Settings


class UpstreamError(RuntimeError):
    pass


class QwenClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(settings.upstream_timeout, read=None))

    def _headers(self, priority: str = "realtime") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.ai_api_key}",
            "Content-Type": "application/json",
            "X-AI-Priority": priority,
        }

    async def health(self) -> dict:
        try:
            response = await self.http.get(f"{self.settings.qwen_url}/health", timeout=5)
            return {"reachable": True, "http_status": response.status_code, **response.json()}
        except Exception as error:
            return {"reachable": False, "error": type(error).__name__}

    async def stream(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
        cancel,
    ) -> AsyncIterator[dict]:
        payload = {
            "model": self.settings.qwen_model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.9,
        }
        async with self.http.stream(
            "POST",
            f"{self.settings.qwen_url}/v1/chat/completions",
            headers=self._headers(),
            json=payload,
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                detail = body[:300].decode(errors="replace")
                raise UpstreamError(f"Qwen returned {response.status_code}: {detail}")
            async for line in response.aiter_lines():
                if cancel.is_set():
                    return
                if not line.startswith("data: "):
                    continue
                value = line[6:]
                if value == "[DONE]":
                    return
                try:
                    event = json.loads(value)
                except json.JSONDecodeError:
                    continue
                if "error" in event:
                    raise UpstreamError(event["error"].get("message", "Qwen streaming failed"))
                yield event

    async def complete(self, messages: list[dict], *, max_tokens: int = 220) -> str:
        response = await self.http.post(
            f"{self.settings.qwen_url}/v1/chat/completions",
            headers=self._headers("background"),
            json={
                "model": self.settings.qwen_model,
                "messages": messages,
                "stream": False,
                "max_tokens": max_tokens,
                "temperature": 0,
            },
        )
        if response.status_code != 200:
            raise UpstreamError(f"Qwen memory extraction returned {response.status_code}")
        return response.json()["choices"][0]["message"]["content"]

    async def close(self) -> None:
        await self.http.aclose()


class ServiceHealth:
    def __init__(self, settings: Settings, qwen: QwenClient) -> None:
        self.settings = settings
        self.qwen = qwen
        self.http = httpx.AsyncClient(timeout=5)

    async def _get(self, url: str) -> dict:
        try:
            response = await self.http.get(url)
            data = response.json()
            return {"reachable": True, "http_status": response.status_code, **data}
        except Exception as error:
            return {"reachable": False, "error": type(error).__name__}

    async def all(self) -> dict:
        qwen = await self.qwen.health()
        whisper_http = self.settings.whisper_url.replace("ws://", "http://").replace(
            "/ws/transcribe", "/health"
        )
        whisper = await self._get(whisper_http)
        xtts = await self._get(f"{self.settings.xtts_http_url}/health")
        return {"qwen": qwen, "whisper": whisper, "xtts": xtts}

    async def xtts(self) -> dict:
        return await self._get(f"{self.settings.xtts_http_url}/health")

    async def close(self) -> None:
        await self.http.aclose()
