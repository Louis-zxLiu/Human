from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import threading
from typing import Any, Callable, Dict, Optional

from app.core.config import resolve_path, settings
from app.services.asr_tts import get_tts_service


STATIC_TEMP_ROOT = resolve_path("SoulX-FlashHead/data/temp")
PRESET_CACHE_DIR = os.path.join(STATIC_TEMP_ROOT, "preset_cache")

PRESET_ROUTE_DEFINITIONS: list[Dict[str, str]] = [
    {
        "key": "lingshan-history",
        "profile_key": "history",
        "scenic_slug": "lingshan-shengjing",
        "title": "历史文化深度路线",
        "prompt": "我是历史文化爱好者，请给我一条灵山胜境深度讲解路线，并说明每个节点讲什么。",
    },
    {
        "key": "lingshan-family",
        "profile_key": "family",
        "scenic_slug": "lingshan-shengjing",
        "title": "亲子友好路线",
        "prompt": "我们带孩子来玩，请推荐一条亲子友好的路线，要有互动点和讲解重点。",
    },
    {
        "key": "lingshan-nature",
        "profile_key": "nature",
        "scenic_slug": "lingshan-shengjing",
        "title": "自然风光路线",
        "prompt": "我喜欢自然风光和拍照打卡，请推荐一条适合拍照的路线，并说明为什么适合多数游客。",
    },
    {
        "key": "nianhuawan-night",
        "profile_key": "relaxed",
        "scenic_slug": "nianhuawan",
        "title": "夜游慢行路线",
        "prompt": "我想在拈花湾慢慢逛，请给我一条适合夜游和放松的路线，并说明每一站看什么。",
    },
    {
        "key": "nianhuawan-culture",
        "profile_key": "history",
        "scenic_slug": "nianhuawan",
        "title": "禅意文化路线",
        "prompt": "我更想感受拈花湾的禅意文化和建筑氛围，请推荐一条路线并说明讲解重点。",
    },
    {
        "key": "nianhuawan-family",
        "profile_key": "family",
        "scenic_slug": "nianhuawan",
        "title": "花海亲子路线",
        "prompt": "我们带孩子来拈花湾放松，请推荐一条轻松好走、适合拍照和休息的路线。",
    },
]

PRESET_REPLY_DEFINITIONS: list[Dict[str, str]] = [
    {
        "key": "gps-awaiting-landmarks",
        "title": "GPS 弱信号补充地标提示",
        "response_kind": "gps:awaiting_landmarks",
        "assistant_text": (
            "当前 GPS 信号较弱，我先不能准确定位您。"
            "请描述一下您附近最明显的佛像、桥、广场、宫殿、塔、花海、湖面或街区，"
            "我再结合景点资料继续帮您判断。"
        ),
    },
    {
        "key": "refused-insufficient-fact-evidence",
        "title": "事实证据不足提示",
        "response_kind": "refused",
        "assistant_text": (
            "抱歉，我暂时没有在灵山胜境知识资料中找到足够证据来回答这个问题。"
            "您可以补充具体景点名称，或者改问位置、开放信息、历史背景、亮点和游览建议。"
        ),
    },
]


def _normalize_text(value: Optional[str]) -> str:
    return " ".join(str(value or "").strip().split())


class PresetRouteCacheManager:
    def __init__(self) -> None:
        self.cache_dir = PRESET_CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)
        self._lock_guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._route_by_key = {route["key"]: route for route in PRESET_ROUTE_DEFINITIONS}
        self._reply_by_key = {reply["key"]: reply for reply in PRESET_REPLY_DEFINITIONS}

    def list_routes(self) -> list[Dict[str, str]]:
        return [copy.deepcopy(route) for route in PRESET_ROUTE_DEFINITIONS]

    def list_replies(self) -> list[Dict[str, str]]:
        return [copy.deepcopy(reply) for reply in PRESET_REPLY_DEFINITIONS]

    def resolve_route(
        self,
        user_text: Optional[str],
        scenic_slug: Optional[str] = None,
        preset_route_key: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        if preset_route_key:
            route = self._route_by_key.get(str(preset_route_key).strip())
            if route and (not scenic_slug or scenic_slug == route["scenic_slug"]):
                return copy.deepcopy(route)
        return None

    def resolve_reply(
        self,
        assistant_text: Optional[str],
        response_kind: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        normalized_text = _normalize_text(assistant_text)
        normalized_kind = str(response_kind or "").strip()
        if not normalized_text:
            return None

        for reply in PRESET_REPLY_DEFINITIONS:
            if normalized_kind and normalized_kind != reply["response_kind"]:
                continue
            if normalized_text == _normalize_text(reply["assistant_text"]):
                return copy.deepcopy(reply)
        return None

    def get_or_create_payload(
        self,
        route: Dict[str, str],
        build_payload: Callable[[Dict[str, str]], Dict[str, Any]],
    ) -> Dict[str, Any]:
        cached = self._read_cached_payload(route)
        if cached:
            cached["cache_hit"] = True
            return cached

        cache_lock = self._lock_for(route["key"])
        with cache_lock:
            cached = self._read_cached_payload(route)
            if cached:
                cached["cache_hit"] = True
                return cached

            fresh_payload = build_payload(route)
            stored_payload = self._store_payload(route, fresh_payload)
            if stored_payload:
                stored_payload["cache_hit"] = False
                return stored_payload

            fresh_payload["cache_hit"] = False
            return fresh_payload

    def clear_all(self) -> int:
        removed = 0
        if not os.path.exists(self.cache_dir):
            return removed

        for name in os.listdir(self.cache_dir):
            path = os.path.join(self.cache_dir, name)
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                removed += 1
            except OSError:
                continue
        return removed

    def build_cache_context(self) -> Dict[str, str]:
        voice_id = get_tts_service().get_current_voice()
        return {
            "avatar_signature": self._build_avatar_signature(),
            "voice_id": voice_id,
            "torch_dtype": str(settings.AVATAR_TORCH_DTYPE).lower(),
            "warmup_seconds": str(settings.AVATAR_WARMUP_SECONDS),
            "response_format_version": "compact-v1",
        }

    def _lock_for(self, route_key: str) -> threading.Lock:
        with self._lock_guard:
            if route_key not in self._locks:
                self._locks[route_key] = threading.Lock()
            return self._locks[route_key]

    def _build_avatar_signature(self) -> str:
        avatar_path = resolve_path(settings.AVATAR_DEFAULT_IMAGE_PATH)
        if not os.path.exists(avatar_path):
            return "missing-avatar"

        digest = hashlib.sha256()
        with open(avatar_path, "rb") as file_obj:
            while True:
                chunk = file_obj.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)

        stat = os.stat(avatar_path)
        digest.update(str(stat.st_size).encode("utf-8"))
        digest.update(str(int(stat.st_mtime)).encode("utf-8"))
        return digest.hexdigest()[:16]

    def _build_cache_stem(self, route: Dict[str, str]) -> str:
        context = self.build_cache_context()
        content_identity = route.get("assistant_text") or route.get("prompt") or ""
        identity = "|".join(
            [
                route["key"],
                _normalize_text(content_identity),
                context["avatar_signature"],
                context["voice_id"],
                context["torch_dtype"],
                context["warmup_seconds"],
                context["response_format_version"],
            ]
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return f"{route['key']}-{digest}"

    def _metadata_path(self, route: Dict[str, str]) -> str:
        return os.path.join(self.cache_dir, f"{self._build_cache_stem(route)}.json")

    def _media_paths(self, route: Dict[str, str]) -> Dict[str, str]:
        stem = self._build_cache_stem(route)
        return {
            "audio": os.path.join(self.cache_dir, f"{stem}.mp3"),
            "video": os.path.join(self.cache_dir, f"{stem}.mp4"),
        }

    def _read_cached_payload(self, route: Dict[str, str]) -> Optional[Dict[str, Any]]:
        metadata_path = self._metadata_path(route)
        media_paths = self._media_paths(route)
        if not os.path.exists(metadata_path):
            return None
        if not os.path.exists(media_paths["audio"]) or not os.path.exists(media_paths["video"]):
            return None

        try:
            with open(metadata_path, "r", encoding="utf-8") as file_obj:
                payload = json.load(file_obj)
        except (OSError, json.JSONDecodeError):
            return None

        audio_name = os.path.basename(media_paths["audio"])
        video_name = os.path.basename(media_paths["video"])
        rag_metadata = payload.get("rag_metadata") or {}
        rag_metadata["preset_route_key"] = route["key"]
        rag_metadata["preset_route_title"] = route["title"]
        if route.get("response_kind"):
            rag_metadata["preset_reply_key"] = route["key"]
            rag_metadata["preset_reply_title"] = route["title"]
        rag_metadata["cache_status"] = "hit"
        return {
            "assistant_text": payload.get("assistant_text", ""),
            "audio_url": f"/static/temp/preset_cache/{audio_name}",
            "video_stream_url": f"/static/temp/preset_cache/{video_name}",
            "rag_metadata": rag_metadata,
        }

    def _store_payload(self, route: Dict[str, str], payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        source_audio = self._static_url_to_path(payload.get("audio_url"))
        source_video = self._static_url_to_path(payload.get("video_stream_url"))
        if not source_audio or not source_video:
            return None
        if not os.path.exists(source_audio) or not os.path.exists(source_video):
            return None

        media_paths = self._media_paths(route)
        metadata_path = self._metadata_path(route)
        os.makedirs(self.cache_dir, exist_ok=True)
        shutil.copy2(source_audio, media_paths["audio"])
        shutil.copy2(source_video, media_paths["video"])

        rag_metadata = copy.deepcopy(payload.get("rag_metadata") or {})
        rag_metadata["preset_route_key"] = route["key"]
        rag_metadata["preset_route_title"] = route["title"]
        if route.get("response_kind"):
            rag_metadata["preset_reply_key"] = route["key"]
            rag_metadata["preset_reply_title"] = route["title"]
        rag_metadata["cache_status"] = "generated"

        metadata_payload = {
            "preset_route_key": route["key"],
            "preset_route_title": route["title"],
            "scenic_slug": route.get("scenic_slug"),
            "preset_reply_key": route.get("key") if route.get("response_kind") else None,
            "assistant_text": payload.get("assistant_text", ""),
            "rag_metadata": rag_metadata,
            "cache_context": self.build_cache_context(),
        }
        with open(metadata_path, "w", encoding="utf-8") as file_obj:
            json.dump(metadata_payload, file_obj, ensure_ascii=False, indent=2)

        audio_name = os.path.basename(media_paths["audio"])
        video_name = os.path.basename(media_paths["video"])
        return {
            "assistant_text": metadata_payload["assistant_text"],
            "audio_url": f"/static/temp/preset_cache/{audio_name}",
            "video_stream_url": f"/static/temp/preset_cache/{video_name}",
            "rag_metadata": rag_metadata,
        }

    @staticmethod
    def _static_url_to_path(url: Optional[str]) -> Optional[str]:
        normalized = str(url or "").strip()
        if not normalized.startswith("/static/temp/"):
            return None
        relative_path = normalized.split("?", 1)[0].replace("/static/temp/", "", 1)
        return os.path.join(STATIC_TEMP_ROOT, relative_path.replace("/", os.sep))


preset_route_cache = PresetRouteCacheManager()
