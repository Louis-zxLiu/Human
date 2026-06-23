import React, { useEffect, useState, useRef } from "react";

import { PlannerResultCard } from "../components/PlannerResultCard";
import { ProductFooter } from "../components/ProductFooter";
import { ProductHeader } from "../components/ProductHeader";
import { fetchScenicAreas, planScenicRoute } from "../lib/api";
import { useStableReveal } from "../lib/reveal";
import { buildGuideHref } from "../lib/routes";

function imagePath(asset) {
  if (!asset) return "";
  if (typeof asset === "string") return asset;
  return asset.path || asset.url || asset.src || "";
}

function themeLabel(area) {
  if (!area?.theme) return area?.name || "";
  if (typeof area.theme === "string") return area.theme;
  return area.shortName || area.name || "";
}

const INTEREST_OPTIONS = [
  { value: "general", label: "经典首游" },
  { value: "history", label: "历史文化" },
  { value: "nature", label: "风景打卡" },
  { value: "family", label: "亲子同游" },
  { value: "architecture", label: "建筑艺术" },
  { value: "relaxed", label: "轻松慢游" },
];
const DURATION_OPTIONS = [
  { value: "short", label: "轻量半日" },
  { value: "half-day", label: "半日游" },
  { value: "full-day", label: "整日游" },
  { value: "night-tour", label: "夜游" },
];
const VISITOR_OPTIONS = [
  { value: "solo", label: "独自出行" },
  { value: "couple", label: "情侣同游" },
  { value: "family", label: "亲子家庭" },
  { value: "elder", label: "长辈同行" },
  { value: "friends", label: "朋友结伴" },
];
const PACE_OPTIONS = [
  { value: "compact", label: "紧凑" },
  { value: "balanced", label: "均衡" },
  { value: "relaxed", label: "舒缓" },
];

const TIPS_DATA = [
  { icon: "\u23F0", title: "最佳时间", desc: "建议上午9点前入园，避开人流高峰。春秋两季气候宜人，是最佳游览季节。", color: "amber" },
  { icon: "\uD83D\uDCA1", title: "装备建议", desc: "穿舒适运动鞋，带好防晒和雨具。夏季注意防暑降温，冬季注意保暖。", color: "teal" },
  { icon: "\uD83D\uDCB0", title: "门票信息", desc: "建议提前在线购票，可享受优惠价格。部分景区提供联票折扣。", color: "coral" },
  { icon: "\uD83D\uDE9E", title: "交通指南", desc: "可乘坐公共交通直达景区，自驾可导航至景区停车场。", color: "rose" },
];

const DOT_COLORS = ["amber", "teal", "coral", "rose", "amber"];

/* ── Particle Canvas Hook ── */
function useParticleCanvas() {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let animId;
    const PARTICLE_COUNT = 25;
    let particles = [];

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    }

    function init() {
      resize();
      particles = Array.from({ length: PARTICLE_COUNT }, () => ({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        r: Math.random() * 1.5 + 0.5,
        o: Math.random() * 0.3 + 0.1,
        vx: (Math.random() - 0.5) * 0.3,
        vy: -(Math.random() * 0.3 + 0.1),
        phase: Math.random() * Math.PI * 2,
      }));
    }

    function animate() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.globalCompositeOperation = "lighter";
      particles.forEach((p) => {
        p.x += p.vx + Math.sin(p.phase) * 0.1;
        p.y += p.vy;
        p.phase += 0.01;
        if (p.y < -10) {
          p.y = canvas.height + 10;
          p.x = Math.random() * canvas.width;
        }
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(245, 158, 11, ${p.o})`;
        ctx.fill();
      });
      animId = requestAnimationFrame(animate);
    }

    init();
    animate();
    window.addEventListener("resize", resize, { passive: true });
    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", resize);
    };
  }, []);
  return canvasRef;
}

/* ── Cursor Glow Hook ── */
function useCursorGlow() {
  const glowRef = useRef(null);
  useEffect(() => {
    const glow = glowRef.current;
    if (!glow) return;
    let mx = 0, my = 0, gx = 0, gy = 0;
    let animId;

    function onMouseMove(e) {
      mx = e.clientX;
      my = e.clientY;
    }

    function updateGlow() {
      gx += (mx - gx) * 0.08;
      gy += (my - gy) * 0.08;
      glow.style.left = gx + "px";
      glow.style.top = gy + "px";
      animId = requestAnimationFrame(updateGlow);
    }

    document.addEventListener("mousemove", onMouseMove, { passive: true });
    updateGlow();
    return () => {
      cancelAnimationFrame(animId);
      document.removeEventListener("mousemove", onMouseMove);
    };
  }, []);
  return glowRef;
}

/* ── Scroll Reveal Hook ── */
function useReveal() {
  return useStableReveal({
    rootSelector: ".pln-page",
    targetSelector: ".pln-reveal, .pln-reveal-stagger, .pln-reveal-scale, .pln-reveal-left, .pln-reveal-right",
    visibleClass: "pln-is-visible",
    threshold: 0.12,
    rootMargin: "0px 0px -32px 0px",
    staggerMs: 70,
  });
}

/* ── Tilt Card Hook ── */
function useTiltCard(ref) {
  useEffect(() => {
    const card = ref.current;
    if (!card) return;

    function onMove(e) {
      const rect = card.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width - 0.5;
      const y = (e.clientY - rect.top) / rect.height - 0.5;
      card.style.transform = `perspective(800px) rotateY(${x * 8}deg) rotateX(${-y * 8}deg)`;
      const shine = card.querySelector(".pln-tilt-shine");
      if (shine) {
        shine.style.setProperty("--pln-shine-x", e.clientX - rect.left + "px");
        shine.style.setProperty("--pln-shine-y", e.clientY - rect.top + "px");
      }
    }

    function onLeave() {
      card.style.transform = "perspective(800px) rotateY(0) rotateX(0)";
    }

    card.addEventListener("mousemove", onMove);
    card.addEventListener("mouseleave", onLeave);
    return () => {
      card.removeEventListener("mousemove", onMove);
      card.removeEventListener("mouseleave", onLeave);
    };
  }, [ref]);
}

/* ── Magnetic Button Hook ── */
function useMagneticBtn(ref) {
  useEffect(() => {
    const btn = ref.current;
    if (!btn) return;

    function onMove(e) {
      const rect = btn.getBoundingClientRect();
      const x = e.clientX - rect.left - rect.width / 2;
      const y = e.clientY - rect.top - rect.height / 2;
      btn.style.transform = `translate(${x * 0.15}px, ${y * 0.15}px)`;
    }

    function onLeave() {
      btn.style.transform = "translate(0, 0)";
    }

    btn.addEventListener("mousemove", onMove);
    btn.addEventListener("mouseleave", onLeave);
    return () => {
      btn.removeEventListener("mousemove", onMove);
      btn.removeEventListener("mouseleave", onLeave);
    };
  }, [ref]);
}

/* ── Hero Parallax Hook ── */
function useHeroParallax() {
  const heroRef = useRef(null);
  useEffect(() => {
    const hero = heroRef.current;
    if (!hero) return;
    const img = hero.querySelector("img");
    if (!img) return;
    let ticking = false;

    function onScroll() {
      if (!ticking) {
        requestAnimationFrame(() => {
          const rect = hero.getBoundingClientRect();
          const scrollPercent = rect.top / window.innerHeight;
          const translateY = scrollPercent * 0.35;
          img.style.transform = `translateY(${translateY}px) scale(1.08)`;
          ticking = false;
        });
        ticking = true;
      }
    }

    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return heroRef;
}

/* ── Main Component ── */
export function PlannerApp() {
  const query = new URLSearchParams(window.location.search);
  const [areas, setAreas] = useState([]);
  const [form, setForm] = useState({
    scenicSlug: query.get("scenicSlug") || "lingshan-shengjing",
    interestLabel: "general",
    durationBand: "half-day",
    visitorType: "solo",
    pace: "balanced",
  });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [bootLoading, setBootLoading] = useState(true);
  const [error, setError] = useState("");

  const particleCanvasRef = useParticleCanvas();
  const cursorGlowRef = useCursorGlow();
  const heroRef = useHeroParallax();
  useReveal();

  useEffect(() => {
    let alive = true;
    fetchScenicAreas()
      .then((payload) => {
        if (!alive) return;
        setAreas(payload);
        if (!payload.some((item) => item.slug === form.scenicSlug) && payload[0]) {
          setForm((previous) => ({ ...previous, scenicSlug: payload[0].slug }));
        }
      })
      .catch((err) => {
        if (!alive) return;
        setError(err.message);
      })
      .finally(() => {
        if (!alive) return;
        setBootLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [form.scenicSlug]);

  async function handleSubmit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const payload = await planScenicRoute(form);
      setResult(payload);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function updateForm(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  const selectedArea = areas.find((a) => a.slug === form.scenicSlug) || areas[0] || null;
  const heroImage = imagePath(selectedArea?.heroImage) || "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1400&h=600&fit=crop";

  /* ── Tilt card refs ── */
  const tiltRefs = useRef([]);
  function setTiltRef(el, idx) {
    tiltRefs.current[idx] = el;
  }
  useEffect(() => {
    tiltRefs.current.forEach((card) => {
      if (!card) return;
      function onMove(e) {
        const rect = card.getBoundingClientRect();
        const x = (e.clientX - rect.left) / rect.width - 0.5;
        const y = (e.clientY - rect.top) / rect.height - 0.5;
        card.style.transform = `perspective(800px) rotateY(${x * 8}deg) rotateX(${-y * 8}deg)`;
        const shine = card.querySelector(".pln-tilt-shine");
        if (shine) {
          shine.style.setProperty("--pln-shine-x", e.clientX - rect.left + "px");
          shine.style.setProperty("--pln-shine-y", e.clientY - rect.top + "px");
        }
      }
      function onLeave() {
        card.style.transform = "perspective(800px) rotateY(0) rotateX(0)";
      }
      card.addEventListener("mousemove", onMove);
      card.addEventListener("mouseleave", onLeave);
      card._cleanup = () => {
        card.removeEventListener("mousemove", onMove);
        card.removeEventListener("mouseleave", onLeave);
      };
    });
    return () => {
      tiltRefs.current.forEach((card) => {
        if (card && card._cleanup) card._cleanup();
      });
    };
  }, [areas]);

  /* ── Magnetic CTA ref ── */
  const ctaBtnRef = useRef(null);
  useEffect(() => {
    const btn = ctaBtnRef.current;
    if (!btn) return;
    function onMove(e) {
      const rect = btn.getBoundingClientRect();
      const x = e.clientX - rect.left - rect.width / 2;
      const y = e.clientY - rect.top - rect.height / 2;
      btn.style.transform = `translate(${x * 0.15}px, ${y * 0.15}px)`;
    }
    function onLeave() {
      btn.style.transform = "translate(0, 0)";
    }
    btn.addEventListener("mousemove", onMove);
    btn.addEventListener("mouseleave", onLeave);
    return () => {
      btn.removeEventListener("mousemove", onMove);
      btn.removeEventListener("mouseleave", onLeave);
    };
  }, []);

  return (
    <div className="pln-page">
      {/* Particle Canvas */}
      <canvas ref={particleCanvasRef} className="pln-particle-canvas" />
      {/* Cursor Glow */}
      <div ref={cursorGlowRef} className="pln-cursor-glow" />

      <ProductHeader active="planner" />

      {/* Hero */}
      <section ref={heroRef} className="pln-hero pln-hero-parallax">
        <img src={heroImage} alt="游览路线" loading="lazy" />
        <div className="pln-hero-overlay">
          <h1 className="pln-hero-title">游览路线规划</h1>
          <p className="pln-hero-sub">智能规划您的完美旅程，让每一刻都精彩</p>
        </div>
      </section>

      {/* Scenic Selector */}
      <section className="pln-scenic-selector">
        <h2 className="pln-section-title pln-reveal">选择景区</h2>
        <div className="pln-selector-grid">
          {areas.map((area, idx) => (
            <div
              key={area.slug}
              ref={(el) => setTiltRef(el, idx)}
              className={`pln-selector-card pln-tilt-card ${idx % 2 === 0 ? "pln-reveal-left" : "pln-reveal-right"} ${form.scenicSlug === area.slug ? "pln-active-amber" : ""}`}
              onClick={() => updateForm("scenicSlug", area.slug)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") updateForm("scenicSlug", area.slug); }}
            >
              <div className="pln-tilt-shine" />
              <img src={imagePath(area.heroImage) || heroImage} alt={area.name} loading="lazy" />
              <div className="pln-selector-card-overlay">
                <span className={`pln-selector-tag ${idx % 2 === 0 ? "pln-tag-amber" : "pln-tag-teal"}`}>
                  {area.level || "景区"}
                </span>
                <h3>{area.name}</h3>
                <p>{area.city || ""} | {themeLabel(area)} | {area.estimatedDuration || "约3-5小时"}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Config Panel */}
      <section className="pln-config-panel">
        <h2 className="pln-section-title pln-reveal">路线配置</h2>

        {error ? <div className="pln-error-banner">{error}</div> : null}
        {bootLoading ? <div className="pln-loading-banner">正在加载园区配置...</div> : null}

        {/* Interest */}
        <div className="pln-config-group pln-reveal-stagger">
          <div className="pln-config-group-title">
            <span className="pln-dot pln-dot-amber" />
            兴趣偏好
          </div>
          <div className="pln-config-options">
            {INTEREST_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`pln-config-btn ${form.interestLabel === opt.value ? "pln-active-amber" : ""}`}
                onClick={() => updateForm("interestLabel", opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Duration */}
        <div className="pln-config-group pln-reveal-stagger">
          <div className="pln-config-group-title">
            <span className="pln-dot pln-dot-teal" />
            游玩时长
          </div>
          <div className="pln-config-options">
            {DURATION_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`pln-config-btn ${form.durationBand === opt.value ? "pln-active-teal" : ""}`}
                onClick={() => updateForm("durationBand", opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Visitor Type */}
        <div className="pln-config-group pln-reveal-stagger">
          <div className="pln-config-group-title">
            <span className="pln-dot pln-dot-coral" />
            游客类型
          </div>
          <div className="pln-config-options">
            {VISITOR_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`pln-config-btn ${form.visitorType === opt.value ? "pln-active-coral" : ""}`}
                onClick={() => updateForm("visitorType", opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Pace */}
        <div className="pln-config-group pln-reveal-stagger">
          <div className="pln-config-group-title">
            <span className="pln-dot pln-dot-rose" />
            整体节奏
          </div>
          <div className="pln-config-options">
            {PACE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`pln-config-btn ${form.pace === opt.value ? "pln-active-rose" : ""}`}
                onClick={() => updateForm("pace", opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Submit */}
        <div className="pln-submit-row pln-reveal">
          <button
            type="button"
            className="pln-cta-btn pln-magnetic-btn"
            disabled={loading || bootLoading}
            onClick={handleSubmit}
            ref={ctaBtnRef}
          >
            {loading ? "生成中..." : "生成推荐路线"}
          </button>
        </div>
      </section>

      {/* Route Preview / Result */}
      {result ? (
        <section className="pln-route-preview pln-route-preview--stable">
          <h2 className="pln-reveal" style={{ color: "#14b8a6" }}>推荐路线预览</h2>
          <div className="pln-timeline">
            {(result.routeItems || []).map((item, index) => (
              <div key={item.attractionId || `${item.name}-${index}`} className="pln-timeline-item pln-reveal-stagger">
                <div className={`pln-timeline-dot pln-dot-${DOT_COLORS[index % DOT_COLORS.length]}`}>
                  {index + 1}
                </div>
                <div className="pln-timeline-content">
                  <h3>{item.name}</h3>
                  <div className="pln-timeline-time">{item.estimatedTime || `第${index + 1}站`}</div>
                  <p>{item.summary}</p>
                </div>
              </div>
            ))}
          </div>

          {/* PlannerResultCard for full result display */}
          <div className="pln-result-card-wrapper pln-reveal">
            <PlannerResultCard plan={result} />
          </div>
        </section>
      ) : (
        <section className="pln-route-preview pln-route-preview--stable">
          <h2 className="pln-reveal" style={{ color: "#14b8a6" }}>推荐路线预览</h2>
          <div className="pln-empty-state pln-reveal">
            <strong>先生成一条路线</strong>
            <span>配置好园区、人群和节奏后，点击"生成推荐路线"查看结果。路线将带上园区语境、讲解重点、行为分析补充和进入数字人导览的入口。</span>
          </div>
        </section>
      )}

      {/* Tips */}
      <section className="pln-tips">
        <h2 className="pln-reveal" style={{ color: "#f59e0b" }}>游览贴士</h2>
        <div className="pln-tips-grid">
          {TIPS_DATA.map((tip) => (
            <div key={tip.title} className={`pln-tip-card pln-reveal-scale`}>
              <div className={`pln-tip-icon pln-tip-icon-${tip.color}`}>{tip.icon}</div>
              <h3>{tip.title}</h3>
              <p>{tip.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="pln-cta pln-reveal">
        <p>路线已规划完成，准备好出发了吗？</p>
        {result ? (
          <a
            href={buildGuideHref({
              scenicSlug: result.scenicSlug,
              scenicName: result.scenicName,
              routeLabel: result.interestLabelDisplay,
              routeTitle: result.title,
              prompt: result.guidePrompt,
            })}
            className="pln-cta-btn pln-magnetic-btn"
          >
            开始导游讲解
          </a>
        ) : (
          <button
            type="button"
            className="pln-cta-btn pln-magnetic-btn"
            onClick={handleSubmit}
            disabled={loading || bootLoading}
          >
            {loading ? "生成中..." : "立即生成路线"}
          </button>
        )}
      </section>

      <ProductFooter />
    </div>
  );
}
