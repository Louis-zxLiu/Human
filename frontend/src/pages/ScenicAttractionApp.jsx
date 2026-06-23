import React, { useEffect, useState, useRef, useCallback } from "react";

import { ProductFooter } from "../components/ProductFooter";
import { ProductHeader } from "../components/ProductHeader";
import { fetchScenicAttraction } from "../lib/api";
import { useStableReveal } from "../lib/reveal";
import { buildGuideHref, buildPlannerHref } from "../lib/routes";

/* ─── highlight bar color cycle ─── */
const BAR_COLORS = [
  "sat-highlight-bar--amber",
  "sat-highlight-bar--teal",
  "sat-highlight-bar--coral",
  "sat-highlight-bar--rose",
];

/* ─── fact-card icon color cycle ─── */
const FACT_ICONS = [
  { cls: "sat-fact-icon--amber", icon: "\u{1F3D4}" },
  { cls: "sat-fact-icon--teal", icon: "\u{1F4CF}" },
  { cls: "sat-fact-icon--coral", icon: "\u2B50" },
  { cls: "sat-fact-icon--rose", icon: "\u{1F3E0}" },
  { cls: "sat-fact-icon--amber", icon: "\u{1F4AC}" },
];

/* ─── small hook: IntersectionObserver scroll-reveal ─── */
function useReveal(deps = []) {
  const ref = useRef(null);
  useStableReveal({
    rootSelector: ".sat-page",
    targetSelector: ".sat-reveal, .sat-reveal-stagger, .sat-reveal-child, .sat-reveal-scale, .sat-reveal-left, .sat-reveal-right",
    visibleClass: "sat-visible",
    childSelector: ".sat-reveal-child, .sat-reveal, .sat-reveal-stagger, .sat-reveal-scale, .sat-reveal-left, .sat-reveal-right",
    childVisibleClass: "sat-visible",
    threshold: 0.08,
    rootMargin: "0px 0px -40px 0px",
    staggerMs: 75,
    deps,
  });
  return ref;
}

/* ─── small hook: tilt-card mouse tracking ─── */
function useTilt() {
  const ref = useRef(null);
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const cards = root.querySelectorAll(".sat-tilt-card");
    cards.forEach((card) => {
      const onMove = (e) => {
        const r = card.getBoundingClientRect();
        const x = (e.clientX - r.left) / r.width - 0.5;
        const y = (e.clientY - r.top) / r.height - 0.5;
        card.style.transform = `perspective(800px) rotateY(${x * 8}deg) rotateX(${-y * 8}deg)`;
        const shine = card.querySelector(".sat-tilt-shine");
        if (shine) {
          shine.style.setProperty("--shine-x", e.clientX - r.left + "px");
          shine.style.setProperty("--shine-y", e.clientY - r.top + "px");
        }
      };
      const onLeave = () => {
        card.style.transform = "perspective(800px) rotateY(0) rotateX(0)";
      };
      card.addEventListener("mousemove", onMove);
      card.addEventListener("mouseleave", onLeave);
    });
  }, []);
  return ref;
}

/* ─── small hook: magnetic button ─── */
function useMagnetic() {
  const ref = useRef(null);
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const btns = root.querySelectorAll(".sat-magnetic-btn");
    btns.forEach((btn) => {
      const onMove = (e) => {
        const r = btn.getBoundingClientRect();
        const x = e.clientX - r.left - r.width / 2;
        const y = e.clientY - r.top - r.height / 2;
        btn.style.transform = `translate(${x * 0.15}px, ${y * 0.15}px)`;
      };
      const onLeave = () => {
        btn.style.transform = "translate(0, 0)";
      };
      btn.addEventListener("mousemove", onMove);
      btn.addEventListener("mouseleave", onLeave);
    });
  }, []);
  return ref;
}

/* ─── small hook: gallery parallax ─── */
function useGalleryParallax() {
  const ref = useRef(null);
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const items = root.querySelectorAll(".sat-gallery-parallax");
    const listeners = [];
    items.forEach((item) => {
      const onMove = (e) => {
        const r = item.getBoundingClientRect();
        const x = (e.clientX - r.left) / r.width - 0.5;
        const y = (e.clientY - r.top) / r.height - 0.5;
        const img = item.querySelector("img");
        if (img) img.style.transform = `scale(1.05) translate(${x * -8}px, ${y * -8}px)`;
      };
      const onLeave = () => {
        const img = item.querySelector("img");
        if (img) img.style.transform = "scale(1)";
      };
      item.addEventListener("mousemove", onMove);
      item.addEventListener("mouseleave", onLeave);
      listeners.push([item, onMove, onLeave]);
    });
    return () => {
      listeners.forEach(([item, onMove, onLeave]) => {
        item.removeEventListener("mousemove", onMove);
        item.removeEventListener("mouseleave", onLeave);
      });
    };
  }, []);
  return ref;
}

/* ─── small hook: hero parallax on scroll ─── */
function useHeroParallax() {
  const imgRef = useRef(null);
  useEffect(() => {
    const img = imgRef.current;
    if (!img) return;
    let ticking = false;
    const onScroll = () => {
      if (!ticking) {
        requestAnimationFrame(() => {
          const scrollY = window.scrollY;
          const heroH = img.parentElement ? img.parentElement.offsetHeight : 0;
          if (scrollY <= heroH) {
            img.style.transform = `translateY(${scrollY * 0.3}px)`;
          }
          ticking = false;
        });
        ticking = true;
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return imgRef;
}

/* ─── small hook: cursor glow ─── */
function useCursorGlow() {
  const glowRef = useRef(null);
  useEffect(() => {
    const glow = glowRef.current;
    if (!glow) return;
    let mx = 0,
      my = 0,
      gx = 0,
      gy = 0;
    const onMove = (e) => {
      mx = e.clientX;
      my = e.clientY;
    };
    let raf;
    const tick = () => {
      gx += (mx - gx) * 0.08;
      gy += (my - gy) * 0.08;
      glow.style.left = gx + "px";
      glow.style.top = gy + "px";
      raf = requestAnimationFrame(tick);
    };
    document.addEventListener("mousemove", onMove, { passive: true });
    tick();
    return () => {
      document.removeEventListener("mousemove", onMove);
      cancelAnimationFrame(raf);
    };
  }, []);
  return glowRef;
}

/* ─── small hook: particle canvas ─── */
function useParticleCanvas() {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();
    window.addEventListener("resize", resize, { passive: true });

    const PARTICLE_COUNT = 30;
    const particles = Array.from({ length: PARTICLE_COUNT }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: Math.random() * 1.5 + 0.5,
      o: Math.random() * 0.3 + 0.1,
      vx: (Math.random() - 0.5) * 0.3,
      vy: -(Math.random() * 0.3 + 0.1),
      phase: Math.random() * Math.PI * 2,
    }));

    let raf;
    const animate = () => {
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
      raf = requestAnimationFrame(animate);
    };
    animate();
    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(raf);
    };
  }, []);
  return canvasRef;
}

/* ═══════════════════════════════════════════════
   Main Component
   ═══════════════════════════════════════════════ */
export function ScenicAttractionApp({ attractionId }) {
  const token = localStorage.getItem("auth_token");
  const guideLabel = token ? "开始导览" : "登录后开始导览";

  const [attraction, setAttraction] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    fetchScenicAttraction(attractionId)
      .then((result) => {
        if (!alive) return;
        setAttraction(result);
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
  }, [attractionId]);

  /* animation hooks */
  const revealRef = useReveal([loading, attraction?.attractionId]);
  const tiltRef = useTilt();
  const magneticRef = useMagnetic();
  const galleryParallaxRef = useGalleryParallax();
  const heroImgRef = useHeroParallax();
  const glowRef = useCursorGlow();
  const particleRef = useParticleCanvas();

  const guideHref = useCallback(
    (prompt) => {
      if (!attraction) return buildGuideHref();
      return buildGuideHref({
        scenicSlug: attraction.scenicSlug,
        scenicName: attraction.scenicName,
        attractionId: attraction.attractionId,
        attractionName: attraction.attractionName,
        prompt: prompt || "",
      });
    },
    [attraction]
  );

  /* ─── loading state ─── */
  if (loading) {
    return (
      <div className="product-page">
        <div className="page-container">
          <ProductHeader />
          <div className="loading-row">正在加载景点详情...</div>
        </div>
      </div>
    );
  }

  /* ─── error / empty state ─── */
  if (!attraction) {
    return (
      <div className="product-page">
        <div className="page-container">
          <ProductHeader />
          <div className="feedback feedback-danger">
            {error || "景点详情暂时不可用。"}
          </div>
        </div>
      </div>
    );
  }

  /* ─── derived data ─── */
  const heroImage =
    attraction.gallery && attraction.gallery.length > 0
      ? attraction.gallery[0].path
      : "";

  /* Parse architectureParams – could be string or array */
  const archParams = Array.isArray(attraction.architectureParams)
    ? attraction.architectureParams
    : typeof attraction.architectureParams === "string"
      ? attraction.architectureParams.split(/[、,，]/).map((s) => s.trim()).filter(Boolean)
      : [];

  /* description could be string or array */
  const descriptionParas = Array.isArray(attraction.description)
    ? attraction.description
    : typeof attraction.description === "string"
      ? attraction.description.split("\n").filter(Boolean)
      : [];

  /* culturalMeaning could be string or array */
  const culturalParas = Array.isArray(attraction.culturalMeaning)
    ? attraction.culturalMeaning
    : typeof attraction.culturalMeaning === "string"
      ? attraction.culturalMeaning.split("\n").filter(Boolean)
      : [];

  /* highlights could be array of objects {title, description} or array of strings */
  const highlightItems = Array.isArray(attraction.highlights)
    ? attraction.highlights.map((h) =>
        typeof h === "object" && h !== null ? h : { title: h, description: "" }
      )
    : [];

  /* recommendedQuestions */
  const questions = Array.isArray(attraction.recommendedQuestions)
    ? attraction.recommendedQuestions
    : [];

  /* fact cards data */
  const factCards = [
    { label: "建造年份", value: archParams[0] || "--" },
    { label: "核心功能", value: attraction.coreFunction || "--" },
    { label: "所在区域", value: attraction.scenicName || "--" },
    { label: "位置", value: attraction.location || "--" },
    { label: "开放信息", value: attraction.openInfo || "--" },
  ];

  const plannerHref = buildPlannerHref(attraction.scenicSlug);

  /* cultural section image – use second gallery image if available */
  const culturalImg =
    attraction.gallery && attraction.gallery.length > 1
      ? attraction.gallery[1].path
      : heroImage;
  const galleryItems = Array.isArray(attraction.gallery) ? attraction.gallery : [];

  return (
    <div className="sat-page">
      {/* Particle Canvas */}
      <canvas ref={particleRef} className="sat-particle-canvas" />
      {/* Cursor Glow */}
      <div ref={glowRef} className="sat-cursor-glow" />

      <ProductHeader />

      {/* ─── Hero ─── */}
      <section className="sat-hero">
        {heroImage && (
          <img
            ref={heroImgRef}
            className="sat-hero__img sat-hero-parallax"
            src={heroImage}
            alt={attraction.attractionName}
            loading="lazy"
          />
        )}
        <div className="sat-hero__overlay">
          <h1 className="sat-hero__title">{attraction.attractionName}</h1>
          <div className="sat-hero__badges">
            {archParams.map((param, idx) => (
              <span key={idx} className="sat-badge sat-badge--amber">
                {param}
              </span>
            ))}
            {attraction.coreFunction && (
              <span className="sat-badge sat-badge--teal">
                {attraction.coreFunction}
              </span>
            )}
          </div>
        </div>
      </section>

      {/* ─── Info Grid ─── */}
      <section className="sat-info-grid" ref={revealRef}>
        <div className="sat-info-text sat-reveal-left">
          <h2>景点介绍</h2>
          {descriptionParas.map((para, idx) => (
            <p key={idx}>{para}</p>
          ))}
        </div>
        <div className="sat-fact-cards sat-reveal-stagger" ref={tiltRef}>
          {factCards.map((card, idx) => {
            const fi = FACT_ICONS[idx % FACT_ICONS.length];
            return (
              <div key={idx} className="sat-fact-card sat-tilt-card sat-reveal-child">
                <div className="sat-tilt-shine" />
                <div className={`sat-fact-icon ${fi.cls}`}>{fi.icon}</div>
                <div>
                  <div className="sat-fact-label">{card.label}</div>
                  <div className="sat-fact-value">{card.value}</div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* ─── Cultural Section ─── */}
      {culturalParas.length > 0 && (
        <section className="sat-cultural sat-reveal" ref={revealRef}>
          <h2>文化内涵</h2>
          <div className="sat-cultural__content">
            <div className="sat-cultural__desc">
              {culturalParas.map((para, idx) => (
                <p key={idx}>{para}</p>
              ))}
            </div>
            {culturalImg && (
              <div className="sat-cultural__img sat-reveal-scale">
                <img src={culturalImg} alt="文化内涵" loading="lazy" />
              </div>
            )}
          </div>
        </section>
      )}

      {/* ─── Highlights ─── */}
      {highlightItems.length > 0 && (
        <section className="sat-highlights" ref={revealRef}>
          <h2 className="sat-section-title sat-reveal">核心亮点</h2>
          <div className="sat-highlights__grid sat-reveal-stagger" ref={tiltRef}>
            {highlightItems.map((item, idx) => (
              <div key={idx} className="sat-highlight-card sat-tilt-card sat-reveal-child">
                <div className="sat-tilt-shine" />
                <div className={`sat-highlight-bar ${BAR_COLORS[idx % BAR_COLORS.length]}`} />
                <div className="sat-highlight-body">
                  <h3>{item.title}</h3>
                  <p>{item.description}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ─── Gallery ─── */}
      {galleryItems.length > 0 && (
        <section className="sat-gallery" ref={revealRef}>
          <h2 className="sat-reveal">景区风光</h2>
          <div className="sat-gallery__grid sat-reveal-stagger" ref={galleryParallaxRef}>
            {galleryItems.map((item, idx) => (
              <div key={`${item.path || "gallery"}-${idx}`} className="sat-gallery-item sat-gallery-parallax sat-reveal-child">
                <img
                  src={item.path}
                  alt={(item.alt || attraction.attractionName) + " - 风光" + (idx + 1)}
                  loading="lazy"
                />
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ─── Recommended Questions ─── */}
      {questions.length > 0 && (
        <section className="sat-questions sat-reveal" ref={revealRef}>
          <h2>向数字人提问</h2>
          <p>选择感兴趣的话题，让AI导游为您详细解答</p>
          <div className="sat-question-btns" ref={magneticRef}>
            {questions.map((q, idx) => (
              <a
                key={idx}
                href={guideHref(q)}
                className="sat-question-btn sat-magnetic-btn"
              >
                {q}
              </a>
            ))}
          </div>
        </section>
      )}

      {/* ─── Action Buttons ─── */}
      <section className="sat-actions" ref={magneticRef}>
        <a href={plannerHref} className="sat-action-btn sat-action-btn--secondary sat-magnetic-btn">
          先规划这座园区
        </a>
        <a
          href={guideHref("")}
          className="sat-action-btn sat-action-btn--primary sat-magnetic-btn"
        >
          {guideLabel}
        </a>
      </section>

      {/* ─── Floating Button ─── */}
      <a
        href={guideHref(`请介绍一下${attraction.attractionName}`)}
        className="sat-float-btn sat-magnetic-btn"
        ref={magneticRef}
      >
        <span>&#x1F916;</span> 向数字人提问
      </a>

      <ProductFooter />
    </div>
  );
}
