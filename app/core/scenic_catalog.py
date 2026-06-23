from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Optional


SCENIC_CATALOG: Dict[str, Dict[str, Any]] = {
    "lingshan-shengjing": {
        "slug": "lingshan-shengjing",
        "scenic_name": "灵山胜境",
        "short_name": "灵山",
        "tagline": "太湖佛国的朝圣主轴，把佛教文化、建筑艺术和数字导览连成一条完整游线。",
        "summary": (
            "灵山胜境以佛教文化朝圣和建筑艺术体验为核心，游客通常会沿中轴线完成"
            "大照壁、五明桥、九龙灌浴、祥符禅寺、灵山大佛、灵山梵宫等核心节点的游览。"
        ),
        "hero_copy": (
            "从入口礼佛轴线到梵宫艺术殿堂，灵山胜境更适合做结构化讲解、路线规划和"
            "弱 GPS 多轮导览。"
        ),
        "theme_tokens": {
            "accent": "#cf8f3c",
            "surface": "#f5efe5",
            "text": "#2e261d",
            "chip": "#6a4d2f",
        },
        "hero_assets": [
            {
                "slot": "home-card",
                "path": "/media/scenic/lingshan-shengjing/lingshan-card.png",
                "alt": "灵山胜境官方卡片图",
                "source_url": "https://www.chinalingshan.com/member/scenic",
            },
            {
                "slot": "hero-primary",
                "path": "/media/scenic/lingshan-shengjing/lingshan-hero-1.jpg",
                "alt": "灵山胜境官方主视觉",
                "source_url": "https://www.chinalingshan.com/member/scenic/1",
            },
            {
                "slot": "gallery-1",
                "path": "/media/scenic/lingshan-shengjing/lingshan-hero-2.png",
                "alt": "灵山胜境官方景区图",
                "source_url": "https://www.chinalingshan.com/member/scenic/1",
            },
            {
                "slot": "gallery-2",
                "path": "/media/scenic/lingshan-shengjing/lingshan-hero-3.jpg",
                "alt": "灵山胜境官方景区图",
                "source_url": "https://www.chinalingshan.com/member/scenic/1",
            },
            {
                "slot": "gallery-3",
                "path": "/media/scenic/lingshan-shengjing/lingshan-hero-4.png",
                "alt": "灵山胜境官方景区图",
                "source_url": "https://www.chinalingshan.com/member/scenic/1",
            },
        ],
        "featured_attractions": [
            "LS-006",
            "LS-010",
            "LS-011",
            "LS-013",
            "LS-014",
        ],
        "recommended_audiences": [
            "历史文化爱好者",
            "首次到访游客",
            "建筑艺术关注者",
            "需要稳定演示的比赛评委",
        ],
        "signature_experiences": [
            "中轴线礼佛讲解",
            "灵山大佛高辨识度打卡",
            "梵宫佛教艺术沉浸式讲解",
            "弱 GPS 场景导航演示",
        ],
        "official_source_urls": [
            "https://www.cnsoftbei.com/content-3-1245-1.html",
            "https://www.chinalingshan.com/member/scenic",
            "https://www.chinalingshan.com/member/scenic/1",
        ],
        "aliases": ["灵山", "灵山胜境", "小灵山"],
    },
    "nianhuawan": {
        "slug": "nianhuawan",
        "scenic_name": "拈花湾禅意小镇",
        "short_name": "拈花湾",
        "tagline": "一条更偏慢游与夜游的禅意休闲动线，把花海、水岸、街区和灯影体验串在一起。",
        "summary": (
            "拈花湾禅意小镇以禅意休闲、夜游氛围和慢节奏漫游为核心，适合用更生活化的"
            "路线包装数字人讲解和公开产品首页。"
        ),
        "hero_copy": (
            "这里更适合做夜游、情侣、慢游、亲子放松等叙事，与灵山胜境形成明显分工。"
        ),
        "theme_tokens": {
            "accent": "#4a9f8a",
            "surface": "#edf6f3",
            "text": "#1d312c",
            "chip": "#2f6c5e",
        },
        "hero_assets": [
            {
                "slot": "home-card",
                "path": "/media/scenic/nianhuawan/nianhuawan-card.png",
                "alt": "拈花湾官方卡片图",
                "source_url": "https://www.chinalingshan.com/member/scenic",
            },
            {
                "slot": "hero-primary",
                "path": "/media/scenic/nianhuawan/nianhuawan-hero-1.jpg",
                "alt": "拈花湾官方轮播图",
                "source_url": "https://www.nianhuawan.com/scenery-introduction/",
            },
            {
                "slot": "gallery-1",
                "path": "/media/scenic/nianhuawan/nianhuawan-hero-2.jpg",
                "alt": "拈花湾官方轮播图",
                "source_url": "https://www.nianhuawan.com/scenery-introduction/",
            },
            {
                "slot": "gallery-2",
                "path": "/media/scenic/nianhuawan/nianhuawan-hero-3.jpg",
                "alt": "拈花湾官方轮播图",
                "source_url": "https://www.nianhuawan.com/scenery-introduction/",
            },
            {
                "slot": "gallery-3",
                "path": "/media/scenic/nianhuawan/nianhuawan-flower-sea.png",
                "alt": "拈花湾官方梵天花海图",
                "source_url": "https://www.nianhuawan.com/scenery-introduction/",
            },
        ],
        "featured_attractions": [
            "NH-002",
            "NH-003",
            "NH-004",
            "NH-005",
            "NH-006",
        ],
        "recommended_audiences": [
            "夜游与慢游游客",
            "情侣与周末短住人群",
            "亲子放松游客",
            "偏生活方式场景的体验型用户",
        ],
        "signature_experiences": [
            "香月花街漫游",
            "五灯湖夜游与灯影氛围",
            "梵天花海取景",
            "鹿鸣谷静修与慢游",
        ],
        "official_source_urls": [
            "https://www.cnsoftbei.com/content-3-1245-1.html",
            "https://www.chinalingshan.com/member/scenic",
            "https://www.chinalingshan.com/member/scenic/2",
            "https://www.nianhuawan.com/scenery-introduction/",
        ],
        "aliases": ["拈花湾", "拈花湾禅意小镇"],
    },
}


SCENIC_ROUTE_PROFILES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "lingshan-shengjing": {
        "history": {
            "title": "历史文化深度路线",
            "reason": "适合希望系统了解灵山佛教文化、建筑寓意和核心讲解脉络的游客。",
            "attractions": ["灵山大照壁", "祥符禅寺", "灵山大佛", "灵山梵宫", "五印坛城"],
            "highlights": "重点覆盖玄奘渊源、千年古刹、五方五佛、梵宫艺术与藏式建筑补充。",
            "estimated_duration": "约 2.5 到 3.5 小时",
            "analytics_types": ["历史文化", "博物馆与展馆"],
        },
        "nature": {
            "title": "景观打卡舒展路线",
            "reason": "适合偏爱空间景观、太湖视野和拍照取景的游客。",
            "attractions": ["灵山大照壁", "五明桥", "菩提大道", "灵山大佛", "五印坛城"],
            "highlights": "重点看中轴线礼佛空间、桥面取景、佛像远景和坛城外观。",
            "estimated_duration": "约 2 到 3 小时",
            "analytics_types": ["风景名胜与休闲度假"],
        },
        "family": {
            "title": "亲子友好路线",
            "reason": "适合家庭同行，路线以易理解、可互动和停留舒适为主。",
            "attractions": ["百子戏弥勒", "九龙灌浴", "佛教文化博览馆", "灵山大佛"],
            "highlights": "重点讲弥勒吉祥寓意、九龙灌浴动态表演和适合孩子理解的佛教常识。",
            "estimated_duration": "约 2.5 到 3.5 小时",
            "analytics_types": ["历史文化", "风景名胜与休闲度假"],
        },
        "architecture": {
            "title": "建筑艺术主题路线",
            "reason": "适合关注建筑尺度、材料工艺和佛教艺术空间的游客。",
            "attractions": ["阿育王柱", "灵山大佛", "灵山梵宫", "五印坛城", "曼飞龙塔"],
            "highlights": "重点看佛教建筑工艺、轴线布局、材质变化与多语系建筑风格对比。",
            "estimated_duration": "约 2 到 3 小时",
            "analytics_types": ["现代地标", "博物馆与展馆"],
        },
        "relaxed": {
            "title": "轻松慢游路线",
            "reason": "适合不想太赶路、希望边走边听讲解的游客。",
            "attractions": ["灵山大照壁", "五明桥", "菩提大道", "九龙灌浴", "祥符禅寺"],
            "highlights": "重点保留步行体验和核心讲解节点，减少高强度折返。",
            "estimated_duration": "约 2.5 到 3 小时",
            "analytics_types": ["风景名胜与休闲度假"],
        },
        "general": {
            "title": "经典首游路线",
            "reason": "适合第一次来到灵山胜境，优先覆盖最具代表性的核心景点。",
            "attractions": ["灵山大照壁", "九龙灌浴", "祥符禅寺", "灵山大佛", "灵山梵宫"],
            "highlights": "覆盖入口礼佛、动态表演、古刹、大佛和梵宫五个核心节点。",
            "estimated_duration": "约 3 到 4 小时",
            "analytics_types": ["风景名胜与休闲度假", "历史文化"],
        },
    },
    "nianhuawan": {
        "history": {
            "title": "禅意文化体验路线",
            "reason": "适合想把拈花湾当作文化体验空间而不是单纯拍照街区来游玩的游客。",
            "attractions": ["拈花广场", "香月花街", "拈花堂", "五灯湖"],
            "highlights": "重点讲唐风宋韵街区、禅意建筑、夜间演艺与生活方式体验。",
            "estimated_duration": "约 2 到 3 小时",
            "analytics_types": ["历史文化", "风景名胜与休闲度假"],
        },
        "nature": {
            "title": "花海水岸取景路线",
            "reason": "适合偏爱自然景观、花海、水岸和柔和夜景的游客。",
            "attractions": ["梵天花海", "五灯湖", "鹿鸣谷", "香月花街"],
            "highlights": "重点看花海、湖面灯影、山谷静境和夜间街区氛围。",
            "estimated_duration": "约 2 到 3 小时",
            "analytics_types": ["风景名胜与休闲度假"],
        },
        "family": {
            "title": "亲子轻松漫游路线",
            "reason": "适合带孩子散步、拍照、慢慢体验夜景和互动空间的游客。",
            "attractions": ["拈花广场", "梵天花海", "五灯湖", "香月花街"],
            "highlights": "重点保留开阔场地、花海、湖边活动和餐饮休息带。",
            "estimated_duration": "约 2 到 3 小时",
            "analytics_types": ["风景名胜与休闲度假", "主题乐园"],
        },
        "architecture": {
            "title": "唐风建筑与街区路线",
            "reason": "适合关注建筑风格、街区立面和禅意空间设计的游客。",
            "attractions": ["拈花广场", "香月花街", "拈花堂", "五灯湖"],
            "highlights": "重点讲唐风木构佛塔语汇、街区尺度、建筑灯光与禅修空间。",
            "estimated_duration": "约 2 到 3 小时",
            "analytics_types": ["现代地标", "风景名胜与休闲度假"],
        },
        "relaxed": {
            "title": "慢游夜享路线",
            "reason": "适合周末放松、住店度假和不赶行程的游客。",
            "attractions": ["香月花街", "五灯湖", "鹿鸣谷"],
            "highlights": "重点保留散步、夜景、轻餐饮和湖边停留体验。",
            "estimated_duration": "约 1.5 到 2.5 小时",
            "analytics_types": ["风景名胜与休闲度假"],
        },
        "general": {
            "title": "拈花湾首游路线",
            "reason": "适合第一次来到拈花湾，先覆盖最有辨识度的慢游场景。",
            "attractions": ["拈花广场", "香月花街", "拈花堂", "五灯湖", "鹿鸣谷"],
            "highlights": "覆盖入口、主街、禅意空间、夜景湖面和山谷静修氛围。",
            "estimated_duration": "约 2.5 到 3.5 小时",
            "analytics_types": ["风景名胜与休闲度假", "历史文化"],
        },
    },
}


ATTRACTION_MEDIA: Dict[str, Dict[str, list[Dict[str, str]]]] = {
    "LS-001": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-dazhaobi.jpg",
                "alt": "灵山大照壁图片",
                "source_url": "https://www.vcg.com/creative/1387156400.html",
            }
        ]
    },
    "LS-002": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-wuming-bridge.jpg",
                "alt": "五明桥图片",
                "source_url": "https://k.sina.cn/article_5840118030_15c19210e00100h5bs.html",
            }
        ]
    },
    "LS-003": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-fozutan.jpg",
                "alt": "佛足坛图片",
                "source_url": "https://www.vcg.com/creative/1499604550.html",
            }
        ]
    },
    "LS-004": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-wuzhimen.jpg",
                "alt": "五智门图片",
                "source_url": "https://www.vcg.com/creative/1387469440.html",
            }
        ]
    },
    "LS-005": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-bodhi-avenue.jpg",
                "alt": "菩提大道图片",
                "source_url": "https://k.sina.cn/article_5840118030_15c19210e00100h5bs.html",
            }
        ]
    },
    "LS-006": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-hero-2.png",
                "alt": "灵山胜境官方景区图",
                "source_url": "https://www.chinalingshan.com/member/scenic/1",
            }
        ]
    },
    "LS-007": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-jiangmo-relief.jpg",
                "alt": "降魔浮雕图片",
                "source_url": "https://www.vcg.com/creative/1523368563.html",
            }
        ]
    },
    "LS-008": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-ashoka-pillar.jpg",
                "alt": "阿育王柱图片",
                "source_url": "https://www.vcg.com/creative/1635003058.html",
            }
        ]
    },
    "LS-009": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-baizi-mile.jpg",
                "alt": "百子戏弥勒图片",
                "source_url": "https://www.vcg.com/creative/1532307151.html",
            }
        ]
    },
    "LS-010": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-hero-1.jpg",
                "alt": "灵山胜境官方景区图",
                "source_url": "https://www.chinalingshan.com/member/scenic/1",
            }
        ]
    },
    "LS-011": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-hero-3.jpg",
                "alt": "灵山胜境官方景区图",
                "source_url": "https://www.chinalingshan.com/member/scenic/1",
            }
        ]
    },
    "LS-012": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-buddhist-museum.jpg",
                "alt": "佛教文化博览馆图片",
                "source_url": "https://www.vcg.com/creative/1629741848.html",
            }
        ]
    },
    "LS-013": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-hero-4.png",
                "alt": "灵山胜境官方景区图",
                "source_url": "https://www.chinalingshan.com/member/scenic/1",
            }
        ]
    },
    "LS-014": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-card.png",
                "alt": "灵山胜境官方景区图",
                "source_url": "https://www.chinalingshan.com/member/scenic",
            }
        ]
    },
    "LS-015": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-manfeilong-tower.jpg",
                "alt": "曼飞龙塔图片",
                "source_url": "https://www.vcg.com/creative/1387158673.html",
            }
        ]
    },
    "LS-016": {
        "gallery": [
            {
                "path": "/media/scenic/lingshan-shengjing/lingshan-wujinyi-zhai.jpg",
                "alt": "无尽意斋图片",
                "source_url": "https://www.mj.org.cn/wzt/2020mjqghsgzh/zypc/202008/t20200818_230754.htm",
            }
        ]
    },
    "NH-001": {
        "gallery": [
            {
                "path": "/media/scenic/nianhuawan/nianhuawan-nianhua-square.jpg",
                "alt": "拈花广场图片",
                "source_url": "https://www.vcg.com/creative/1362784681.html",
            }
        ]
    },
    "NH-002": {
        "gallery": [
            {
                "path": "/media/scenic/nianhuawan/nianhuawan-flower-sea.png",
                "alt": "梵天花海官方图",
                "source_url": "https://www.nianhuawan.com/scenery-introduction/",
            }
        ]
    },
    "NH-003": {
        "gallery": [
            {
                "path": "/media/scenic/nianhuawan/nianhuawan-fragrant-moon.jpg",
                "alt": "香月花街官方图",
                "source_url": "https://www.nianhuawan.com/scenery-introduction/",
            }
        ]
    },
    "NH-004": {
        "gallery": [
            {
                "path": "/media/scenic/nianhuawan/nianhuawan-nianhua-hall.jpg",
                "alt": "拈花堂图片",
                "source_url": "https://www.vcg.com/creative/1562054330.html",
            }
        ]
    },
    "NH-005": {
        "gallery": [
            {
                "path": "/media/scenic/nianhuawan/nianhuawan-five-lakes.jpg",
                "alt": "五灯湖官方图",
                "source_url": "https://www.nianhuawan.com/scenery-introduction/",
            }
        ]
    },
    "NH-006": {
        "gallery": [
            {
                "path": "/media/scenic/nianhuawan/nianhuawan-deer-valley.jpg",
                "alt": "鹿鸣谷官方图",
                "source_url": "https://www.nianhuawan.com/scenery-introduction/",
            }
        ]
    },
}


def list_scenic_catalog() -> list[Dict[str, Any]]:
    return [deepcopy(entry) for entry in SCENIC_CATALOG.values()]


def get_scenic_entry(slug: Optional[str]) -> Optional[Dict[str, Any]]:
    if not slug:
        return None
    entry = SCENIC_CATALOG.get(str(slug).strip())
    return deepcopy(entry) if entry else None


def scenic_slug_from_name(name: Optional[str]) -> Optional[str]:
    normalized = str(name or "").strip()
    for slug, entry in SCENIC_CATALOG.items():
        if normalized == entry["scenic_name"]:
            return slug
    return None


def scenic_name_from_slug(slug: Optional[str]) -> Optional[str]:
    entry = get_scenic_entry(slug)
    return entry["scenic_name"] if entry else None


def infer_scenic_slug_from_text(text: Optional[str]) -> Optional[str]:
    query = str(text or "").strip()
    if not query:
        return None
    for slug, entry in SCENIC_CATALOG.items():
        aliases: Iterable[str] = entry.get("aliases") or []
        if any(alias in query for alias in aliases):
            return slug
    return None


def scenic_theme(slug: Optional[str]) -> Dict[str, str]:
    entry = get_scenic_entry(slug)
    if not entry:
        return {}
    return deepcopy(entry.get("theme_tokens") or {})


def attraction_media(attraction_id: Optional[str], scenic_slug: Optional[str]) -> list[Dict[str, str]]:
    attraction_assets = ATTRACTION_MEDIA.get(str(attraction_id or "").strip())
    if attraction_assets:
        return deepcopy(attraction_assets.get("gallery") or [])

    scenic_entry = get_scenic_entry(scenic_slug)
    if not scenic_entry:
        return []
    hero_assets = scenic_entry.get("hero_assets") or []
    fallback = [asset for asset in hero_assets if asset.get("slot") in {"hero-primary", "gallery-1"}]
    return deepcopy(fallback[:2])
