from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.config import resolve_path
from app.core.scenic_catalog import (
    attraction_media,
    get_scenic_entry,
    list_scenic_catalog,
    scenic_slug_from_name,
)
from app.rag.fact_agent import ScenicFactAgent
from app.rag.recommendation_agent import PROFILE_LABELS, ScenicRecommendationAgent
from app.rag.sql_agent import TouristAnalyticsAgent


router = APIRouter()
DB_PATH = resolve_path("data/processed/tourist_behavior.db")

_fact_agent_cache: Optional[ScenicFactAgent] = None
_analytics_agent_cache: Optional[TouristAnalyticsAgent] = None
_recommendation_agent_cache: Optional[ScenicRecommendationAgent] = None


PLANNER_DURATION_LABELS = {
    "short": "轻量半日",
    "half-day": "半日游",
    "full-day": "整日游",
    "night-tour": "夜游",
}
PLANNER_VISITOR_LABELS = {
    "solo": "独自出行",
    "couple": "情侣同游",
    "family": "亲子家庭",
    "elder": "长辈同行",
    "friends": "朋友结伴",
}
PLANNER_PACE_LABELS = {
    "compact": "紧凑",
    "balanced": "均衡",
    "relaxed": "舒缓",
}


class ScenicPlannerRequest(BaseModel):
    scenicSlug: str
    interestLabel: str
    durationBand: str = "half-day"
    visitorType: str = "solo"
    pace: str = "balanced"


def get_fact_agent() -> ScenicFactAgent:
    global _fact_agent_cache
    if _fact_agent_cache is None:
        _fact_agent_cache = ScenicFactAgent()
    return _fact_agent_cache


def get_analytics_agent() -> TouristAnalyticsAgent:
    global _analytics_agent_cache
    if _analytics_agent_cache is None:
        _analytics_agent_cache = TouristAnalyticsAgent()
    return _analytics_agent_cache


def get_recommendation_agent() -> ScenicRecommendationAgent:
    global _recommendation_agent_cache
    if _recommendation_agent_cache is None:
        _recommendation_agent_cache = ScenicRecommendationAgent(
            fact_agent=get_fact_agent(),
            analytics_agent=get_analytics_agent(),
    )
    return _recommendation_agent_cache


def clear_runtime_cache() -> None:
    global _fact_agent_cache, _analytics_agent_cache, _recommendation_agent_cache
    _fact_agent_cache = None
    _analytics_agent_cache = None
    _recommendation_agent_cache = None


def scenic_db_rows(scenic_slug: Optional[str] = None) -> List[Dict[str, Any]]:
    if not os.path.exists(DB_PATH):
        return []
    query = (
        "select scenic_name, attraction_id, attraction_name, location, architecture_params, "
        "core_function, cultural_meaning, description, highlights, open_info, remarks "
        "from attractions"
    )
    params: list[Any] = []
    scenic_entry = get_scenic_entry(scenic_slug)
    if scenic_entry:
        query += " where scenic_name = ?"
        params.append(scenic_entry["scenic_name"])
    query += " order by attraction_id"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        return [dict(row) for row in cursor.execute(query, params).fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def scenic_db_row_by_attraction_id(attraction_id: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        row = cursor.execute(
            "select scenic_name, attraction_id, attraction_name, location, architecture_params, "
            "core_function, cultural_meaning, description, highlights, open_info, remarks "
            "from attractions where attraction_id = ?",
            [attraction_id],
        ).fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def build_guide_prompts(attraction_name: str, scenic_name: str) -> List[str]:
    return [
        f"{attraction_name}为什么值得看？",
        f"{attraction_name}在{scenic_name}里承担什么讲解作用？",
        f"如果我从{attraction_name}继续逛，下一站推荐去哪里？",
    ]


def build_attraction_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    scenic_slug = scenic_slug_from_name(row["scenic_name"])
    scenic_entry = get_scenic_entry(scenic_slug)
    gallery = attraction_media(row["attraction_id"], scenic_slug)
    primary_image = gallery[0]["path"] if gallery else ""
    return {
        "scenicSlug": scenic_slug,
        "scenicName": row["scenic_name"],
        "attractionId": row["attraction_id"],
        "attractionName": row["attraction_name"],
        "location": row["location"],
        "architectureParams": row["architecture_params"],
        "coreFunction": row["core_function"],
        "culturalMeaning": row["cultural_meaning"],
        "description": row["description"],
        "highlights": row["highlights"],
        "openInfo": row["open_info"],
        "remarks": row["remarks"],
        "image": primary_image,
        "gallery": gallery,
        "recommendedQuestions": build_guide_prompts(row["attraction_name"], row["scenic_name"]),
        "theme": scenic_entry.get("theme_tokens") if scenic_entry else {},
    }


def build_area_payload(entry: Dict[str, Any]) -> Dict[str, Any]:
    scenic_rows = scenic_db_rows(entry["slug"])
    row_map = {row["attraction_id"]: row for row in scenic_rows}
    featured_attractions = [
        build_attraction_payload(row_map[attraction_id])
        for attraction_id in entry.get("featured_attractions", [])
        if attraction_id in row_map
    ]
    hero_assets = entry.get("hero_assets") or []
    return {
        "slug": entry["slug"],
        "name": entry["scenic_name"],
        "shortName": entry["short_name"],
        "tagline": entry["tagline"],
        "summary": entry["summary"],
        "heroCopy": entry["hero_copy"],
        "heroImage": hero_assets[0]["path"] if hero_assets else "",
        "heroAssets": hero_assets,
        "theme": entry.get("theme_tokens") or {},
        "featuredAttractions": featured_attractions,
        "recommendedAudiences": entry.get("recommended_audiences") or [],
        "signatureExperiences": entry.get("signature_experiences") or [],
        "officialSourceUrls": entry.get("official_source_urls") or [],
        "attractionCount": len(scenic_rows),
    }


@router.get("/areas")
async def scenic_areas():
    payload = [build_area_payload(entry) for entry in list_scenic_catalog()]
    return JSONResponse(content=payload)


@router.get("/areas/{scenic_slug}")
async def scenic_area_detail(scenic_slug: str):
    entry = get_scenic_entry(scenic_slug)
    if not entry:
        raise HTTPException(status_code=404, detail="Unknown scenic area")
    return JSONResponse(content=build_area_payload(entry))


@router.get("/areas/{scenic_slug}/attractions")
async def scenic_area_attractions(scenic_slug: str):
    entry = get_scenic_entry(scenic_slug)
    if not entry:
        raise HTTPException(status_code=404, detail="Unknown scenic area")
    rows = scenic_db_rows(scenic_slug)
    return JSONResponse(content=[build_attraction_payload(row) for row in rows])


@router.get("/attractions/{attraction_id}")
async def scenic_attraction_detail(attraction_id: str):
    row = scenic_db_row_by_attraction_id(attraction_id)
    if not row:
        raise HTTPException(status_code=404, detail="Unknown attraction")
    payload = build_attraction_payload(row)
    payload["area"] = build_area_payload(get_scenic_entry(payload["scenicSlug"]))
    return JSONResponse(content=payload)


@router.post("/planner")
async def scenic_planner(request: ScenicPlannerRequest):
    scenic_entry = get_scenic_entry(request.scenicSlug)
    if not scenic_entry:
        raise HTTPException(status_code=404, detail="Unknown scenic area")

    recommendation = get_recommendation_agent().plan_route(
        scenic_slug=request.scenicSlug,
        interest_label=request.interestLabel,
        duration_band=request.durationBand,
        visitor_type=request.visitorType,
        pace=request.pace,
    )
    recommendation["interestLabelDisplay"] = PROFILE_LABELS.get(
        recommendation["profileKey"],
        recommendation["profileKey"],
    )
    recommendation["durationLabel"] = PLANNER_DURATION_LABELS.get(request.durationBand, request.durationBand)
    recommendation["visitorTypeLabel"] = PLANNER_VISITOR_LABELS.get(request.visitorType, request.visitorType)
    recommendation["paceLabel"] = PLANNER_PACE_LABELS.get(request.pace, request.pace)
    recommendation["area"] = {
        "slug": scenic_entry["slug"],
        "name": scenic_entry["scenic_name"],
        "heroImage": scenic_entry["hero_assets"][0]["path"] if scenic_entry.get("hero_assets") else "",
        "theme": scenic_entry.get("theme_tokens") or {},
    }
    return JSONResponse(content=recommendation)
