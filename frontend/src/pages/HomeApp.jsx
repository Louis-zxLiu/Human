import React, { useEffect, useState, useRef, useCallback } from "react";

import { ProductFooter } from "../components/ProductFooter";
import { ProductHeader } from "../components/ProductHeader";
import { fetchScenicAreas, fetchScenicAttractions } from "../lib/api";
import { useStableReveal } from "../lib/reveal";
import {
  buildGuideHref,
  buildPlannerHref,
  buildScenicHref,
} from "../lib/routes";

function imagePath(asset) {
  if (!asset) return "";
  if (typeof asset === "string") return asset;
  return asset.path || asset.url || asset.src || "";
}

function attractionLabel(attraction) {
  if (!attraction) return "";
  if (typeof attraction === "string") return attraction;
  return attraction.attractionName || attraction.name || attraction.title || attraction.attractionId || "";
}

function assetForSlot(scenic, slots = []) {
  const preferredSlots = Array.isArray(slots) ? slots : [slots];
  const assets = scenic?.heroAssets || [];
  return (
    preferredSlots.map((slot) => assets.find((asset) => asset.slot === slot)).find(Boolean) ||
    assets.find((asset) => imagePath(asset)) ||
    scenic?.heroImage ||
    ""
  );
}

function scenicImage(scenic, slots = ["hero-primary", "home-card"]) {
  return imagePath(assetForSlot(scenic, slots));
}

function galleryImagesFromAreas(areas, attractionsBySlug = {}) {
  const images = [];
  areas.forEach((area) => {
    (area.heroAssets || []).forEach((asset) => {
      const src = imagePath(asset);
      if (src) images.push({ src, alt: asset.alt || area.name, height: "auto" });
    });
    (area.featuredAttractions || []).forEach((attraction) => {
      const src = imagePath(attraction.gallery?.[0] || attraction.image);
      if (src) images.push({ src, alt: attractionLabel(attraction) || area.name, height: "auto" });
    });
    (attractionsBySlug[area.slug] || []).forEach((attraction) => {
      const gallery = Array.isArray(attraction.gallery) && attraction.gallery.length ? attraction.gallery : [attraction.image];
      gallery.forEach((asset) => {
        const src = imagePath(asset);
        if (src) images.push({ src, alt: attractionLabel(attraction) || area.name, height: "auto" });
      });
    });
  });
  const seen = new Set();
  return images.filter((image) => {
    if (!image.src || seen.has(image.src)) return false;
    seen.add(image.src);
    return true;
  });
}

function galleryFlowRows(images, rowCount = 3) {
  const rows = Array.from({ length: rowCount }, () => []);
  images.forEach((image, index) => {
    rows[index % rowCount].push(image);
  });
  return rows.map((row) => (row.length ? row : images)).filter((row) => row.length);
}

/* ───────── constants ───────── */

const CAPABILITIES = [
  "多模态数字人问答",
  "本地景区知识库",
  "双园区路线规划",
  "弱 GPS 多轮导览",
  "游客洞察驾驶舱",
  "统一评测支撑",
];

const STATS = [
  { value: 5, suffix: "", label: "大核心景区", dataCount: "5" },
  { value: 20, suffix: "", label: "精选景点", dataCount: "20" },
  { value: null, text: "AI", label: "智慧导览系统", dataCount: "" },
  { value: null, text: "24h", label: "实时互动服务", dataCount: "" },
];

const GALLERY_IMAGES = [
  { src: "/media/scenic/lingshan-shengjing/lingshan-hero-1.jpg", alt: "灵山胜境官方主视觉", height: "auto" },
  { src: "/media/scenic/lingshan-shengjing/lingshan-hero-2.png", alt: "灵山胜境官方景区图", height: "220px" },
  { src: "/media/scenic/lingshan-shengjing/lingshan-hero-3.jpg", alt: "灵山胜境官方景区图", height: "280px" },
  { src: "/media/scenic/nianhuawan/nianhuawan-hero-1.jpg", alt: "拈花湾官方轮播图", height: "auto" },
  { src: "/media/scenic/nianhuawan/nianhuawan-flower-sea.png", alt: "拈花湾梵天花海", height: "200px" },
  { src: "/media/scenic/nianhuawan/nianhuawan-five-lakes.jpg", alt: "拈花湾五灯湖", height: "250px" },
];

const MARQUEE_ITEMS = [
  { icon: "fas fa-mountain-sun", color: "#f59e0b", text: "灵山大佛" },
  { icon: "fas fa-torii-gate", color: "#14b8a6", text: "梵宫" },
  { icon: "fas fa-spa", color: "#f97316", text: "五印坛城" },
  { icon: "fas fa-water", color: "#ef4444", text: "九龙灌浴" },
  { icon: "fas fa-moon", color: "#f59e0b", text: "拈花湾" },
  { icon: "fas fa-cloud-sun", color: "#14b8a6", text: "灵山小镇" },
  { icon: "fas fa-sun", color: "#f97316", text: "梵天花海" },
  { icon: "fas fa-star", color: "#ef4444", text: "禅意灯光秀" },
];

const FEATURES = [
  {
    icon: "fas fa-robot",
    color: "#f59e0b",
    barColor: "#f59e0b",
    title: "AI数字人导游",
    desc: "智能数字人24小时在线，为您讲解景点背后的故事与文化内涵，支持多语言对话，让每一次游览都充满收获。",
  },
  {
    icon: "fas fa-route",
    color: "#14b8a6",
    barColor: "#14b8a6",
    title: "智能路线规划",
    desc: "根据您的兴趣偏好、时间安排和体力状况，AI智能规划最优游览路线，确保不错过任何精彩景点。",
  },
  {
    icon: "fas fa-microphone",
    color: "#f97316",
    barColor: "#f97316",
    title: "语音实时互动",
    desc: "支持语音对话的自然交互方式，解放双手，让游览更加轻松自在。实时语音识别，秒级响应。",
  },
];

const TESTIMONIALS = [
  {
    stars: 5,
    text: "灵山胜境真的太震撼了！灵山大佛的壮观程度远超想象，AI导游的讲解也非常专业，让我对佛教文化有了更深的了解。强烈推荐！",
    avatar: "王",
    avatarColor: "#f59e0b",
    name: "王女士",
    role: "文化爱好者",
  },
  {
    stars: 5,
    text: "拈花湾的夜景太美了，禅意灯光秀让人仿佛置身仙境。带着孩子来的，智能路线规划帮我们合理安排了时间，体验非常好。",
    avatar: "李",
    avatarColor: "#14b8a6",
    name: "李先生",
    role: "亲子游游客",
  },
  {
    stars: 4.5,
    text: "作为摄影爱好者，灵山的每一个角落都是绝佳的取景地。AI导游推荐的拍照点位非常专业，帮我拍到了很多满意的作品。",
    avatar: "张",
    avatarColor: "#ef4444",
    name: "张先生",
    role: "摄影爱好者",
  },
];

const ABOUT_CARDS = [
  { icon: "fas fa-landmark", color: "#f59e0b", title: "佛教文化", desc: "千年佛教圣地，感受东方禅意之美" },
  { icon: "fas fa-mountain", color: "#14b8a6", title: "自然山水", desc: "太湖之滨，山水相依的绝美风光" },
  { icon: "fas fa-torii-gate", color: "#f97316", title: "建筑艺术", desc: "梵宫、五印坛城，建筑瑰宝荟萃" },
  { icon: "fas fa-spa", color: "#ef4444", title: "禅意度假", desc: "拈花湾小镇，沉浸式禅意生活体验" },
];

const SCENIC_HOME_PROFILES = {
  "lingshan-shengjing": {
    kicker: "佛教文化主线",
    focus: "朝圣轴线、灵山大佛、梵宫建筑艺术",
    summary: "适合系统了解佛教文化、建筑寓意和核心讲解脉络，游览节奏更偏结构化、仪式感和地标打卡。",
    chips: ["88米灵山大佛", "九龙灌浴", "梵宫艺术", "中轴线导览"],
  },
  nianhuawan: {
    kicker: "禅意休闲主线",
    focus: "慢游街区、夜游灯影、花海水岸体验",
    summary: "适合夜游、亲子放松和周末慢游，游览节奏更偏生活方式、沉浸氛围和轻松停留。",
    chips: ["香月花街", "五灯湖夜景", "梵天花海", "禅意慢游"],
  },
};

function scenicHomeProfile(scenic) {
  return SCENIC_HOME_PROFILES[scenic?.slug] || {
    kicker: scenic?.shortName || "园区导览",
    focus: scenic?.heroCopy || scenic?.tagline || "",
    summary: scenic?.summary || scenic?.tagline || "",
    chips: (scenic?.signatureExperiences || []).slice(0, 4),
  };
}

function orderScenicAreas(areas) {
  const preferred = ["lingshan-shengjing", "nianhuawan"];
  return [
    ...preferred.map((slug) => areas.find((area) => area.slug === slug)).filter(Boolean),
    ...areas.filter((area) => !preferred.includes(area.slug)),
  ];
}

/* ───────── hooks ───────── */

function useScrollReveal(deps = []) {
  return useStableReveal({
    rootSelector: ".home-premium",
    targetSelector: ".reveal, .reveal-stagger, .reveal-child, .reveal-scale, .reveal-left, .reveal-right, .img-reveal, .char-reveal",
    visibleClass: "visible",
    childSelector: ".reveal-child, .reveal-left, .reveal-right, .reveal-scale, .img-reveal, .char-reveal",
    childVisibleClass: "visible",
    threshold: 0.1,
    rootMargin: "0px 0px -48px 0px",
    staggerMs: 90,
    deps,
  });
}

function useParticleCanvas() {
  const canvasRef = useRef(null);
  useEffect(() => {
    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let animationId;
    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();
    window.addEventListener("resize", resize);
    const particles = [];
    const count = 50;
    for (let i = 0; i < count; i++) {
      particles.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        radius: Math.random() * 2 + 1,
        opacity: Math.random() * 0.4 + 0.1,
        speedY: Math.random() * 0.2 + 0.1,
        speedX: (Math.random() - 0.5) * 0.3,
        oscillationSpeed: Math.random() * 0.02 + 0.005,
        oscillationDistance: Math.random() * 30 + 10,
        phase: Math.random() * Math.PI * 2,
      });
    }
    const animate = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.globalCompositeOperation = "lighter";
      particles.forEach((p) => {
        p.y -= p.speedY;
        p.phase += p.oscillationSpeed;
        const drawX = p.x + Math.sin(p.phase) * p.oscillationDistance;
        if (p.y < -10) {
          p.y = canvas.height + 10;
          p.x = Math.random() * canvas.width;
        }
        ctx.beginPath();
        ctx.arc(drawX, p.y, p.radius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(245, 158, 11, ${p.opacity})`;
        ctx.fill();
      });
      animationId = requestAnimationFrame(animate);
    };
    animate();
    return () => {
      cancelAnimationFrame(animationId);
      window.removeEventListener("resize", resize);
    };
  }, []);
  return canvasRef;
}

function useCursorGlow() {
  const glowRef = useRef(null);
  useEffect(() => {
    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;
    const glow = glowRef.current;
    if (!glow) return;
    let mouseX = -500;
    let mouseY = -500;
    let glowX = -500;
    let glowY = -500;
    const onMouseMove = (e) => {
      mouseX = e.clientX;
      mouseY = e.clientY;
      glow.style.opacity = "1";
    };
    const onMouseLeave = () => {
      glow.style.opacity = "0";
    };
    const lerp = (a, b, t) => a + (b - a) * t;
    let rafId;
    const updateGlow = () => {
      glowX = lerp(glowX, mouseX, 0.08);
      glowY = lerp(glowY, mouseY, 0.08);
      glow.style.transform = `translate(${glowX - 200}px, ${glowY - 200}px)`;
      rafId = requestAnimationFrame(updateGlow);
    };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseleave", onMouseLeave);
    updateGlow();
    return () => {
      cancelAnimationFrame(rafId);
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseleave", onMouseLeave);
    };
  }, []);
  return glowRef;
}

function useTiltCards() {
  useEffect(() => {
    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;
    const cards = document.querySelectorAll(".home-premium .tilt-card");
    const handleMouseMove = (e) => {
      const card = e.currentTarget;
      const rect = card.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const deltaX = e.clientX - centerX;
      const deltaY = e.clientY - centerY;
      const maxTilt = 8;
      const tiltX = (deltaY / (rect.height / 2)) * -maxTilt;
      const tiltY = (deltaX / (rect.width / 2)) * maxTilt;
      const shineX = ((e.clientX - rect.left) / rect.width) * 100;
      const shineY = ((e.clientY - rect.top) / rect.height) * 100;
      card.style.transform = `perspective(800px) rotateX(${tiltX}deg) rotateY(${tiltY}deg) scale3d(1.02, 1.02, 1.02)`;
      card.style.setProperty("--shine-x", shineX + "%");
      card.style.setProperty("--shine-y", shineY + "%");
    };
    const handleMouseLeave = (e) => {
      e.currentTarget.style.transform = "perspective(800px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)";
    };
    cards.forEach((card) => {
      card.addEventListener("mousemove", handleMouseMove);
      card.addEventListener("mouseleave", handleMouseLeave);
    });
    return () => {
      cards.forEach((card) => {
        card.removeEventListener("mousemove", handleMouseMove);
        card.removeEventListener("mouseleave", handleMouseLeave);
      });
    };
  }, []);
}

function useMagneticButtons() {
  useEffect(() => {
    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;
    const buttons = document.querySelectorAll(".home-premium .magnetic-btn");
    const handleMouseMove = (e) => {
      const btn = e.currentTarget;
      const rect = btn.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const deltaX = e.clientX - centerX;
      const deltaY = e.clientY - centerY;
      const maxMove = 8;
      const moveX = (deltaX / (rect.width / 2)) * maxMove;
      const moveY = (deltaY / (rect.height / 2)) * maxMove;
      btn.style.transform = `translate(${moveX}px, ${moveY}px)`;
    };
    const handleMouseLeave = (e) => {
      e.currentTarget.style.transform = "translate(0, 0)";
    };
    buttons.forEach((btn) => {
      btn.addEventListener("mousemove", handleMouseMove);
      btn.addEventListener("mouseleave", handleMouseLeave);
    });
    return () => {
      buttons.forEach((btn) => {
        btn.removeEventListener("mousemove", handleMouseMove);
        btn.removeEventListener("mouseleave", handleMouseLeave);
      });
    };
  }, []);
}

function useCounterAnimation() {
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const el = entry.target;
            const target = parseInt(el.dataset.count) || 0;
            if (!target) return;
            const duration = 1500;
            const start = performance.now();
            const animate = (now) => {
              const elapsed = now - start;
              const progress = Math.min(elapsed / duration, 1);
              const eased = 1 - Math.pow(1 - progress, 3);
              el.textContent = Math.floor(target * eased).toLocaleString();
              if (progress < 1) requestAnimationFrame(animate);
              else el.textContent = target.toLocaleString();
            };
            requestAnimationFrame(animate);
            observer.unobserve(el);
          }
        });
      },
      { threshold: 0.5 }
    );
    document.querySelectorAll("[data-count]").forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);
}

function useHeroParallax() {
  useEffect(() => {
    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;
    const handleScroll = () => {
      const els = document.querySelectorAll(".home-premium .hero-parallax");
      els.forEach((el) => {
        const rect = el.closest("section")?.getBoundingClientRect();
        if (rect && rect.bottom > 0) {
          el.style.transform = `translateY(${window.scrollY * 0.3}px)`;
        }
      });
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);
}

function useFlowGallery(selector, deps = []) {
  useEffect(() => {
    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;
    const rows = Array.from(document.querySelectorAll(selector));
    if (!rows.length) return;
    let rafId;
    const state = rows.map((row, index) => ({
      row,
      offset: index % 2 === 0 ? 0 : -row.scrollWidth / 4,
      direction: index % 2 === 0 ? -1 : 1,
      speed: 0.28 + index * 0.06,
      paused: false,
      enter: null,
      leave: null,
    }));
    state.forEach((item) => {
      item.enter = () => {
        item.paused = true;
      };
      item.leave = () => {
        item.paused = false;
      };
      item.row.addEventListener("mouseenter", item.enter);
      item.row.addEventListener("mouseleave", item.leave);
    });
    const tick = () => {
      state.forEach((item) => {
        const distance = item.row.scrollWidth / 2 || 1;
        if (!item.paused) {
          item.offset += item.direction * item.speed;
          if (item.offset <= -distance) item.offset += distance;
          if (item.offset >= 0) item.offset -= distance;
        }
        item.row.style.transform = `translate3d(${item.offset}px, 0, 0)`;
      });
      rafId = requestAnimationFrame(tick);
    };
    tick();
    return () => {
      cancelAnimationFrame(rafId);
      state.forEach((item) => {
        item.row.removeEventListener("mouseenter", item.enter);
        item.row.removeEventListener("mouseleave", item.leave);
      });
    };
  }, deps);
}

/* ───────── sub-components ───────── */

function StatCounter({ stat }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || !stat.dataCount) return;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const target = parseInt(stat.dataCount) || 0;
            const duration = 1500;
            const start = performance.now();
            const animate = (now) => {
              const elapsed = now - start;
              const progress = Math.min(elapsed / duration, 1);
              const eased = 1 - Math.pow(1 - progress, 3);
              el.textContent = Math.floor(target * eased).toLocaleString();
              if (progress < 1) requestAnimationFrame(animate);
              else el.textContent = target.toLocaleString();
            };
            requestAnimationFrame(animate);
            observer.unobserve(el);
          }
        });
      },
      { threshold: 0.5 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [stat.dataCount]);

  return (
    <div className="hp-stats__item reveal-child">
      <div className="hp-stats__value" ref={ref} data-count={stat.dataCount || undefined}>
        {stat.text || "0"}
      </div>
      <div className="hp-stats__label">{stat.label}</div>
    </div>
  );
}

function StarRating({ rating }) {
  const full = Math.floor(rating);
  const half = rating % 1 >= 0.5;
  const empty = 5 - full - (half ? 1 : 0);
  return (
    <div className="hp-stars">
      {Array.from({ length: full }).map((_, i) => (
        <i key={`f${i}`} className="fas fa-star" />
      ))}
      {half ? <i className="fas fa-star-half-alt" /> : null}
      {Array.from({ length: empty }).map((_, i) => (
        <i key={`e${i}`} className="far fa-star" />
      ))}
      <span>{rating.toFixed(1)}</span>
    </div>
  );
}

function ScenicAreaCard({ scenic, guideLabel, revealClass = "", compact = false }) {
  const profile = scenicHomeProfile(scenic);
  const chips = profile.chips.length
    ? profile.chips
    : scenic.featuredAttractions?.map(attractionLabel).filter(Boolean).slice(0, 4) || [];

  return (
    <div className={`hp-scenic-card-shell ${revealClass}`}>
      <div className={`hp-scenic-card hp-scenic-card--${scenic.slug} ${compact ? "hp-scenic-card--compact" : ""} tilt-card card-lift`}>
        <div className="tilt-shine" />
        <div className="hp-scenic-card__media img-reveal">
          <img src={scenicImage(scenic, ["hero-primary", "home-card", "gallery-1"])} alt={scenic.name} loading={compact ? "eager" : "lazy"} />
          <div className="hp-scenic-card__badge">{scenic.shortName}</div>
        </div>
        <div className="hp-scenic-card__body">
          <div className="hp-scenic-card__kicker">{profile.kicker}</div>
          <h3>{scenic.name}</h3>
          <strong className="hp-scenic-card__focus">{profile.focus}</strong>
          <p>{profile.summary || scenic.tagline}</p>
          <div className="hp-scenic-card__tags">
            {chips.slice(0, 4).map((label) => (
              <span key={label} className="hp-scenic-card__tag">{label}</span>
            ))}
          </div>
          <div className="hp-scenic-card__actions">
            <a
              href={buildScenicHref(scenic.slug)}
              className="hp-btn hp-btn--primary hp-btn--sm magnetic-btn"
              onClick={(e) => e.stopPropagation()}
            >
              <span>进入景区</span>
              <i className="fas fa-arrow-right" />
            </a>
            <a
              href={buildPlannerHref(scenic.slug)}
              className="hp-btn hp-btn--ghost hp-btn--sm"
              onClick={(e) => e.stopPropagation()}
            >
              规划路线
            </a>
            <a
              href={buildGuideHref({ scenicSlug: scenic.slug, scenicName: scenic.name })}
              className="hp-btn hp-btn--ghost hp-btn--sm"
              onClick={(e) => e.stopPropagation()}
            >
              {guideLabel}
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ───────── main component ───────── */

export function HomeApp() {
  const [areas, setAreas] = useState([]);
  const [attractionsBySlug, setAttractionsBySlug] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const token = localStorage.getItem("auth_token");
  const guideLabel = token ? "开始导览" : "登录后开始导览";

  useEffect(() => {
    let alive = true;
    fetchScenicAreas()
      .then((result) => {
        if (!alive) return;
        setAreas(result);
        Promise.all(
          result.map((area) =>
            fetchScenicAttractions(area.slug)
              .then((items) => [area.slug, Array.isArray(items) ? items : []])
              .catch(() => [area.slug, []])
          )
        ).then((entries) => {
          if (!alive) return;
          setAttractionsBySlug(Object.fromEntries(entries));
        });
      })
      .catch((err) => {
        if (!alive) return;
        setError(err.message);
      })
      .finally(() => {
        if (!alive) return;
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const orderedAreas = orderScenicAreas(areas);
  const primary = orderedAreas.find((area) => area.slug === "lingshan-shengjing") || orderedAreas[0];
  const secondary = orderedAreas.find((area) => area.slug === "nianhuawan") || orderedAreas.find((area) => area !== primary);
  const heroAreas = orderedAreas.slice(0, 2);
  const heroImageSrc =
    scenicImage(primary, ["hero-primary", "gallery-1", "home-card"]) ||
    "/media/scenic/lingshan-shengjing/lingshan-hero-1.jpg";
  const ctaImageSrc =
    scenicImage(secondary, ["hero-primary", "gallery-1", "home-card"]) ||
    scenicImage(primary, ["gallery-2", "hero-primary", "home-card"]) ||
    "/media/scenic/nianhuawan/nianhuawan-hero-1.jpg";
  const apiGalleryImages = galleryImagesFromAreas(areas, attractionsBySlug);
  const displayGalleryImages = (apiGalleryImages.length ? apiGalleryImages : GALLERY_IMAGES).slice(0, 36);
  const galleryRows = galleryFlowRows(displayGalleryImages, 3);

  const scrollRevealRef = useScrollReveal([loading, areas.length]);
  const canvasRef = useParticleCanvas();
  const glowRef = useCursorGlow();
  useTiltCards();
  useMagneticButtons();
  useCounterAnimation();
  useHeroParallax();
  useFlowGallery(".hp-gallery__row", [displayGalleryImages.length]);

  const scrollToStats = useCallback(() => {
    const el = document.getElementById("hp-stats");
    if (el) el.scrollIntoView({ behavior: "smooth" });
  }, []);

  return (
    <div className="home-premium product-page">
      {/* Particle Canvas Background */}
      <canvas ref={canvasRef} className="hp-particle-canvas" />

      {/* Cursor Glow Follow */}
      <div ref={glowRef} className="hp-cursor-glow" />

      <div className="page-container" ref={scrollRevealRef}>
        <ProductHeader active="home" />

        {/* ===== HERO SECTION ===== */}
        <section className="hp-hero">
          <div className="hp-hero__bg hero-parallax">
            <img
              src={heroImageSrc}
              alt="灵山胜境山景"
              loading="eager"
            />
          </div>
          <div className="hp-hero__overlay" />

          <div className="hp-hero__content">
            <div className="hp-hero__badge">
              <span className="hp-hero__badge-dot" />
              <span>国家5A级旅游景区</span>
            </div>

            <h1 className="hp-hero__title">
              <span className="char-reveal">
                <span>灵</span>
                <span>山</span>
                <span>胜</span>
                <span>境</span>
                <span> · </span>
                <span>拈</span>
                <span>花</span>
                <span>湾</span>
              </span>
            </h1>

            <p className="hp-hero__subtitle">
              一边是佛教文化、建筑艺术和朝圣主线，一边是禅意慢游、夜游灯影和休闲度假。先选场景，再进入对应的数字人导览节奏。
            </p>

            <div className="hp-hero__actions">
              <a href={buildGuideHref()} className="hp-btn hp-btn--primary magnetic-btn">
                <span>开始探索</span>
                <i className="fas fa-compass" />
              </a>
              <a href={buildPlannerHref()} className="hp-btn hp-btn--outline magnetic-btn">
                <span>查看景区</span>
                <i className="fas fa-map-marked-alt" />
              </a>
            </div>

            {/* Capability tags */}
            <div className="hp-capability-strip">
              {CAPABILITIES.map((item) => (
                <span key={item} className="hp-capability-tag">{item}</span>
              ))}
            </div>

            {loading ? (
              <div className="hp-hero-scenic hp-hero-scenic--loading">
                <div className="loading-row">正在加载双园区资料...</div>
              </div>
            ) : heroAreas.length > 0 ? (
              <div className="hp-hero-scenic">
                {heroAreas.map((scenic, idx) => (
                  <ScenicAreaCard
                    key={scenic.slug}
                    scenic={scenic}
                    guideLabel={guideLabel}
                    compact
                    revealClass={idx === 0 ? "reveal-left" : "reveal-right"}
                  />
                ))}
              </div>
            ) : null}
          </div>

          {/* Scroll indicator */}
          <div className="hp-hero__scroll" onClick={scrollToStats}>
            <span>向下滚动</span>
            <i className="fas fa-chevron-down" />
          </div>
        </section>

        {/* ===== STATS BAR ===== */}
        <section id="hp-stats" className="hp-stats">
          <div className="hp-stats__wave" aria-hidden="true">
            <svg viewBox="0 0 1200 40" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M0 40V20C200 0 400 0 600 20C800 40 1000 40 1200 20V40H0Z" fill="#14b8a6" />
            </svg>
          </div>
          <div className="hp-stats__grid reveal-stagger">
            {STATS.map((stat) => (
              <StatCounter key={stat.label} stat={stat} />
            ))}
          </div>
        </section>

        {/* ===== ABOUT SECTION ===== */}
        <section className="hp-about section-fade">
          <div className="hp-about__grid">
            <div className="hp-about__left reveal-left">
              <div className="hp-eyebrow hp-eyebrow--amber">
                <span>关于灵山</span>
              </div>
              <h2 className="hp-about__title">
                探索灵山胜境的<br />每一处风景
              </h2>
            </div>
            <div className="hp-about__right reveal-right">
              <p>
                灵山胜境位于无锡市滨湖区马山国家风景名胜区，是国家5A级旅游景区。景区以佛教文化为主题，集湖光山色、园林广场、佛教建筑于一体，是中国最为完整、也是唯一集中展示佛祖释迦牟尼成就的佛教文化主题园区。
              </p>
              <p>
                这里拥有高达88米的灵山大佛、气势恢宏的梵宫、充满禅意的五印坛城以及浪漫的灵山小镇拈花湾。无论您是文化朝圣还是休闲度假，灵山胜境都将为您带来一次难忘的心灵之旅。
              </p>
            </div>
          </div>

          <div className="hp-about__cards reveal-stagger">
            {ABOUT_CARDS.map((card) => (
              <div key={card.title} className="hp-about-card reveal-child tilt-card card-lift">
                <div className="tilt-shine" />
                <div className="hp-about-card__icon" style={{ background: `${card.color}15` }}>
                  <i className={card.icon} style={{ color: card.color }} />
                </div>
                <h3>{card.title}</h3>
                <p>{card.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ===== SCENIC AREAS (dynamic from API) ===== */}
        <section className="hp-scenic section-fade">
          <div className="hp-section-header reveal">
            <div className="hp-eyebrow hp-eyebrow--amber">
              <span>双园区入口</span>
            </div>
            <h2>先选场景，再进入对应的导览节奏。</h2>
            <p>灵山胜境承担佛教文化与建筑艺术主线，拈花湾承担慢游、夜游和禅意休闲体验。</p>
          </div>

          {error ? <div className="feedback feedback-danger">{error}</div> : null}
          {loading ? <div className="loading-row">正在加载双园区资料...</div> : null}
          {!loading ? (
            <div className="hp-scenic__grid">
              {orderedAreas.map((scenic, idx) => (
                <ScenicAreaCard
                  key={scenic.slug}
                  scenic={scenic}
                  guideLabel={guideLabel}
                  revealClass={idx === 0 ? "reveal-left" : "reveal-right"}
                />
              ))}
            </div>
          ) : null}
        </section>

        {/* ===== MARQUEE SECTION ===== */}
        <section className="hp-marquee">
          <div className="hp-marquee__track">
            {[...MARQUEE_ITEMS, ...MARQUEE_ITEMS].map((item, i) => (
              <div key={i} className="hp-marquee__item">
                <i className={item.icon} style={{ color: `${item.color}50` }} />
                <span>{item.text}</span>
              </div>
            ))}
          </div>
        </section>

        {/* ===== PHOTO GALLERY ===== */}
        <section className="hp-gallery section-fade">
          <div className="hp-section-header reveal">
            <div className="hp-eyebrow hp-eyebrow--coral">
              <span>光影瞬间</span>
            </div>
            <h2>景区风光</h2>
          </div>
          <div className="hp-gallery__flow reveal-stagger">
            {galleryRows.map((row, rowIndex) => (
              <div key={rowIndex} className={`hp-gallery__row hp-gallery__row--${rowIndex + 1}`}>
                {[...row, ...row].map((img, i) => (
                  <div key={`${img.src}-${rowIndex}-${i}`} className="hp-gallery__item reveal-child img-reveal">
                    <img src={img.src} alt={img.alt} loading="lazy" />
                  </div>
                ))}
              </div>
            ))}
          </div>
        </section>

        {/* ===== FEATURES SECTION ===== */}
        <section className="hp-features section-fade">
          <div className="hp-section-header reveal">
            <div className="hp-eyebrow hp-eyebrow--teal">
              <span>科技赋能</span>
            </div>
            <h2>智慧导览体验</h2>
          </div>
          <div className="hp-features__grid reveal-stagger">
            {FEATURES.map((feat) => (
              <div key={feat.title} className="hp-feature-card reveal-child tilt-card card-lift">
                <div className="tilt-shine" />
                <div className="hp-feature-card__bar" style={{ background: feat.barColor }} />
                <div className="hp-feature-card__body">
                  <div className="hp-feature-card__icon" style={{ background: `${feat.color}15` }}>
                    <i className={feat.icon} style={{ color: feat.color }} />
                  </div>
                  <h3>{feat.title}</h3>
                  <p>{feat.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ===== SERVICE LOOP (narrative) ===== */}
        <section className="hp-narrative section-fade">
          <div className="hp-section-header reveal">
            <div className="hp-eyebrow hp-eyebrow--amber">
              <span>服务闭环</span>
            </div>
            <h2>从游客浏览到数字人服务，再到后台运营，整条链路都能自然衔接。</h2>
          </div>
          <div className="hp-narrative__grid reveal-stagger">
            <div className="hp-narrative-card reveal-child tilt-card card-lift">
              <div className="tilt-shine" />
              <div className="hp-narrative-card__step">1</div>
              <strong>浏览园区</strong>
              <span>先看真实景区内容，而不是直接掉进聊天框。</span>
            </div>
            <div className="hp-narrative-card reveal-child tilt-card card-lift">
              <div className="tilt-shine" />
              <div className="hp-narrative-card__step">2</div>
              <strong>规划路线</strong>
              <span>按兴趣、人群、时长与节奏生成结构化游线。</span>
            </div>
            <div className="hp-narrative-card reveal-child tilt-card card-lift">
              <div className="tilt-shine" />
              <div className="hp-narrative-card__step">3</div>
              <strong>数字人带路</strong>
              <span>带着当前园区和路线语境进入多模态导览。</span>
            </div>
            <div className="hp-narrative-card reveal-child tilt-card card-lift">
              <div className="tilt-shine" />
              <div className="hp-narrative-card__step">4</div>
              <strong>后台复盘</strong>
              <span>用统一评测、知识库状态与游客洞察承接管理价值。</span>
            </div>
          </div>
        </section>

        {/* ===== TESTIMONIALS ===== */}
        <section className="hp-testimonials section-fade">
          <div className="hp-section-header reveal">
            <div className="hp-eyebrow hp-eyebrow--amber">
              <span>真实反馈</span>
            </div>
            <h2>游客评价</h2>
          </div>
          <div className="hp-testimonials__grid reveal-stagger">
            {TESTIMONIALS.map((t) => (
              <div key={t.name} className="hp-testimonial-card reveal-child tilt-card card-lift">
                <div className="tilt-shine" />
                <div className="hp-testimonial-card__stars">
                  <StarRating rating={t.stars} />
                </div>
                <p className="hp-testimonial-card__text">&ldquo;{t.text}&rdquo;</p>
                <div className="hp-testimonial-card__author">
                  <div className="hp-testimonial-card__avatar" style={{ background: `${t.avatarColor}20` }}>
                    <span style={{ color: t.avatarColor }}>{t.avatar}</span>
                  </div>
                  <div>
                    <div className="hp-testimonial-card__name">{t.name}</div>
                    <div className="hp-testimonial-card__role">{t.role}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ===== CTA SECTION ===== */}
        <section className="hp-cta reveal">
          <div className="hp-cta__bg hero-parallax">
            <img
              src={ctaImageSrc}
              alt="灵山日落"
              loading="lazy"
            />
          </div>
          <div className="hp-cta__overlay" />
          <div className="hp-cta__content">
            <h2>开启你的灵山之旅</h2>
            <p>让AI数字人导游陪伴您，探索千年佛教圣地的每一处风景，感受东方禅意之美。</p>
            <a href={buildGuideHref()} className="hp-btn hp-btn--primary hp-btn--lg magnetic-btn">
              <span>立即开始</span>
              <i className="fas fa-arrow-right" />
            </a>
          </div>
        </section>

        <ProductFooter />
      </div>
    </div>
  );
}
