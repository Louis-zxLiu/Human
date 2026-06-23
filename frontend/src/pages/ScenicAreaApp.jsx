import React, { useEffect, useState, useRef, useCallback } from "react";

import { AttractionSpotCard } from "../components/AttractionSpotCard";
import { ProductFooter } from "../components/ProductFooter";
import { ProductHeader } from "../components/ProductHeader";
import { fetchScenicArea, fetchScenicAttractions } from "../lib/api";
import { useStableReveal } from "../lib/reveal";
import { buildAttractionHref, buildGuideHref, buildPlannerHref } from "../lib/routes";

/* ── audience icon/color mapping ── */
const AUDIENCE_META = [
  { icon: "fas fa-pray", color: "#f59e0b", bg: "rgba(245,158,11,0.15)" },
  { icon: "fas fa-users", color: "#14b8a6", bg: "rgba(20,184,166,0.15)" },
  { icon: "fas fa-camera", color: "#f97316", bg: "rgba(249,115,22,0.15)" },
  { icon: "fas fa-graduation-cap", color: "#fb7185", bg: "rgba(251,113,133,0.15)" },
];

/* ── signature experience descriptions (fallback) ── */
const SIG_DESCRIPTIONS = [
  "感受庄严的佛教仪式与祈福文化",
  "再现九龙喷水沐浴的震撼场景",
  "穹顶壁画与琉璃装饰的深度艺术体验",
  "千年古刹中的宁静时刻",
];

/* ── practical info defaults ── */
const DEFAULT_PRACTICAL_INFO = [
  { title: "开放时间", content: "请咨询景区官方获取最新开放时间" },
  { title: "门票价格", content: "请咨询景区官方获取最新票价信息" },
  { title: "交通方式", content: "请咨询景区官方获取交通指南" },
  { title: "景区地址", content: "请咨询景区官方获取详细地址" },
];

function imagePath(asset) {
  if (!asset) return "";
  if (typeof asset === "string") return asset;
  return asset.path || asset.url || asset.src || "";
}

function attractionLabel(attraction) {
  return attraction?.attractionName || attraction?.name || attraction?.title || "";
}

function buildGalleryImages(area, attractions) {
  const images = [];
  (area.heroAssets || []).forEach((asset) => {
    const src = imagePath(asset);
    if (src) images.push({ src, alt: asset.alt || area.name });
  });
  attractions.forEach((attraction) => {
    const gallery = Array.isArray(attraction.gallery) && attraction.gallery.length ? attraction.gallery : [attraction.image];
    gallery.forEach((asset) => {
      const src = imagePath(asset);
      if (src) images.push({ src, alt: attractionLabel(attraction) || area.name });
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
      speed: 0.26 + index * 0.06,
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

export function ScenicAreaApp({ scenicSlug }) {
  const token = localStorage.getItem("auth_token");
  const guideLabel = token ? "开始导览" : "登录后开始导览";
  const [area, setArea] = useState(null);
  const [attractions, setAttractions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  /* ── refs for premium animations ── */
  const heroImgRef = useRef(null);
  const revealRootRef = useStableReveal({
    rootSelector: ".sa-page",
    targetSelector: ".sa-reveal, .sa-reveal-stagger, .sa-reveal-child, .sa-reveal-scale, .sa-reveal-left, .sa-reveal-right",
    visibleClass: "sa-visible",
    childSelector: ".sa-reveal-child, .sa-reveal, .sa-reveal-stagger, .sa-reveal-scale, .sa-reveal-left, .sa-reveal-right",
    childVisibleClass: "sa-visible",
    threshold: 0.1,
    rootMargin: "0px 0px -48px 0px",
    staggerMs: 75,
    deps: [loading, area?.slug, attractions.length],
  });
  const particleCanvasRef = useRef(null);
  const cursorGlowRef = useRef(null);

  /* ── Data fetching ── */
  useEffect(() => {
    let alive = true;
    Promise.all([fetchScenicArea(scenicSlug), fetchScenicAttractions(scenicSlug)])
      .then(([areaResult, attractionResult]) => {
        if (!alive) return;
        setArea(areaResult);
        setAttractions(attractionResult);
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
  }, [scenicSlug]);
  useFlowGallery(".sa-gallery-row", [loading, area?.slug, attractions.length]);

  /* ── Premium animations (runs after data loads) ── */
  const initAnimations = useCallback(() => {
    /* Hero parallax */
    const heroEl = heroImgRef.current;
    if (heroEl) {
      const onScroll = () => {
        heroEl.style.transform = `translateY(${window.pageYOffset * 0.25}px)`;
      };
      window.addEventListener("scroll", onScroll, { passive: true });
    }

    /* Canvas particles */
    const canvas = particleCanvasRef.current;
    if (canvas) {
      const ctx = canvas.getContext("2d");
      let w, h;
      const particles = [];
      const PARTICLE_COUNT = 35;

      function resize() {
        w = canvas.width = window.innerWidth;
        h = canvas.height = window.innerHeight;
      }
      resize();
      window.addEventListener("resize", resize);

      class Particle {
        constructor() {
          this.reset();
        }
        reset() {
          this.x = Math.random() * w;
          this.y = Math.random() * h;
          this.size = Math.random() * 2.5 + 0.5;
          this.speedX = (Math.random() - 0.5) * 0.3;
          this.speedY = (Math.random() - 0.5) * 0.3;
          this.opacity = Math.random() * 0.4 + 0.1;
          this.fadeDir = Math.random() > 0.5 ? 1 : -1;
        }
        update() {
          this.x += this.speedX;
          this.y += this.speedY;
          this.opacity += this.fadeDir * 0.002;
          if (this.opacity > 0.5) this.fadeDir = -1;
          if (this.opacity < 0.05) this.fadeDir = 1;
          if (this.x < -10 || this.x > w + 10 || this.y < -10 || this.y > h + 10) {
            this.reset();
          }
        }
        draw() {
          ctx.beginPath();
          ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(245, 158, 11, ${this.opacity})`;
          ctx.fill();
          ctx.beginPath();
          ctx.arc(this.x, this.y, this.size * 3, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(245, 158, 11, ${this.opacity * 0.15})`;
          ctx.fill();
        }
      }

      for (let i = 0; i < PARTICLE_COUNT; i++) {
        particles.push(new Particle());
      }

      function animate() {
        ctx.clearRect(0, 0, w, h);
        particles.forEach((p) => {
          p.update();
          p.draw();
        });
        requestAnimationFrame(animate);
      }
      animate();
    }

    /* Cursor glow */
    const glow = cursorGlowRef.current;
    if (glow) {
      let active = false;
      const onMove = (e) => {
        if (!active) {
          glow.classList.add("sa-cursor-glow--active");
          active = true;
        }
        glow.style.left = e.clientX + "px";
        glow.style.top = e.clientY + "px";
      };
      const onLeave = () => {
        glow.classList.remove("sa-cursor-glow--active");
        active = false;
      };
      document.addEventListener("mousemove", onMove, { passive: true });
      document.addEventListener("mouseleave", onLeave);
    }

    /* 3D tilt cards */
    const tiltCards = document.querySelectorAll(".sa-tilt-card");
    tiltCards.forEach((card) => {
      const onTiltMove = (e) => {
        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const centerX = rect.width / 2;
        const centerY = rect.height / 2;
        const rotateX = ((y - centerY) / centerY) * -6;
        const rotateY = ((x - centerX) / centerX) * 6;
        card.style.transform = `perspective(800px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`;
        const shine = card.querySelector(".sa-tilt-shine");
        if (shine) {
          shine.style.setProperty("--sa-shine-x", (x / rect.width) * 100 + "%");
          shine.style.setProperty("--sa-shine-y", (y / rect.height) * 100 + "%");
        }
      };
      const onTiltLeave = () => {
        card.style.transform = "perspective(800px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)";
      };
      card.addEventListener("mousemove", onTiltMove);
      card.addEventListener("mouseleave", onTiltLeave);
    });

    /* Magnetic buttons */
    const magBtns = document.querySelectorAll(".sa-magnetic-btn");
    magBtns.forEach((btn) => {
      const onMagMove = (e) => {
        const rect = btn.getBoundingClientRect();
        const x = e.clientX - rect.left - rect.width / 2;
        const y = e.clientY - rect.top - rect.height / 2;
        btn.style.transform = `translate(${x * 0.2}px, ${y * 0.2}px)`;
      };
      const onMagLeave = () => {
        btn.style.transform = "translate(0, 0)";
      };
      btn.addEventListener("mousemove", onMagMove);
      btn.addEventListener("mouseleave", onMagLeave);
    });

    /* Parallax images */
    const parallaxImgs = document.querySelectorAll(".sa-parallax-img");
    function onParallaxScroll() {
      parallaxImgs.forEach((img) => {
        const rect = img.getBoundingClientRect();
        const vh = window.innerHeight;
        const progress = Math.max(0, Math.min(1, 1 - (rect.top + rect.height) / (vh + rect.height)));
        const scale = 0.85 + progress * 0.15;
        const translateY = (1 - progress) * 30;
        img.style.transform = `scale(${scale}) translateY(${translateY}px)`;
      });
    }
    window.addEventListener("scroll", onParallaxScroll, { passive: true });
    onParallaxScroll();
  }, []);

  useEffect(() => {
    if (!loading && area) {
      /* Small delay to ensure DOM is rendered */
      const timer = setTimeout(initAnimations, 100);
      return () => clearTimeout(timer);
    }
  }, [loading, area, initAnimations]);

  /* ── Loading state ── */
  if (loading) {
    return (
      <div className="product-page">
        <div className="page-container">
          <ProductHeader />
          <div className="loading-row">正在加载园区资料...</div>
        </div>
      </div>
    );
  }

  /* ── Error state ── */
  if (!area) {
    return (
      <div className="product-page">
        <div className="page-container">
          <ProductHeader />
          <div className="feedback feedback-danger">{error || "园区资料暂时不可用。"}</div>
        </div>
      </div>
    );
  }

  /* ── Derived data ── */
  const heroImage = imagePath(area.heroImage);
  const heroAssets = (area.heroAssets || []).map(imagePath).filter(Boolean);
  const galleryImages = buildGalleryImages(area, attractions).slice(0, 30);
  const galleryRows = galleryFlowRows(galleryImages, 3);
  const practicalInfo = area.practicalInfo || DEFAULT_PRACTICAL_INFO;
  const audiences = area.recommendedAudiences || [];
  const signatureExperiences = area.signatureExperiences || [];

  return (
    <div className="product-page sa-page">
      {/* Particle canvas */}
      <canvas ref={particleCanvasRef} className="sa-particle-canvas" />
      {/* Cursor glow */}
      <div ref={cursorGlowRef} className="sa-cursor-glow" />

      <div className="page-container sa-page__inner">
        <ProductHeader />

        <main>
          {/* ── SECTION 1: HERO (70vh) ── */}
          <section className="sa-hero">
            <img
              ref={heroImgRef}
              src={heroImage}
              alt={area.name}
              loading="eager"
              className="sa-hero__img sa-hero-parallax"
            />
            <div className="sa-hero__overlay" />
            <div className="sa-hero__content">
              <div className="sa-hero__inner">
                {/* Quick info pills */}
                <div className="sa-hero__pills">
                  <span className="sa-pill sa-pill--amber">
                    <i className="fas fa-map-marker-alt" />
                    {area.attractionCount}个核心景点
                  </span>
                  <span className="sa-pill sa-pill--teal">
                    <i className="fas fa-clock" />
                    3-4小时游览
                  </span>
                  <span className="sa-pill sa-pill--coral">
                    <i className="fas fa-star" />
                    4.8评分
                  </span>
                </div>

                {/* Title */}
                <h1 className="sa-hero__title">{area.name}</h1>

                {/* Tagline */}
                <p className="sa-hero__tagline">{area.tagline}</p>

                {/* Buttons */}
                <div className="sa-hero__actions">
                  <a
                    href={buildGuideHref({ scenicSlug: area.slug, scenicName: area.name })}
                    className="sa-btn-solid sa-magnetic-btn"
                  >
                    <i className="fas fa-comments" />
                    {guideLabel}
                  </a>
                  <a
                    href={buildPlannerHref(area.slug)}
                    className="sa-btn-outline-white sa-magnetic-btn"
                  >
                    <i className="fas fa-route" />
                    规划路线
                  </a>
                </div>
              </div>
            </div>
          </section>

          {/* ── SECTION 2: OVERVIEW (2-col) ── */}
          <section className="sa-section sa-section--bg sa-reveal">
            <div className="sa-section__inner">
              <div className="sa-overview-grid">
                {/* Left: text */}
                <div className="sa-overview-text sa-reveal-left">
                  <h2 className="sa-section-title">景区简介</h2>
                  <div className="sa-section-bar" />
                  <p className="sa-overview-text__body">{area.summary}</p>
                </div>

                {/* Right: image */}
                <div className="sa-overview-image sa-reveal-right">
                  <div className="sa-overview-image__frame">
                    {heroAssets[1] && (
                      <img
                        src={heroAssets[1]}
                        alt={area.name}
                        loading="lazy"
                        className="sa-img-lazy"
                        onLoad={(e) => e.target.classList.add("sa-img-loaded")}
                      />
                    )}
                  </div>
                  <div className="sa-overview-image__accent" />
                </div>
              </div>
            </div>
          </section>

          {/* ── SECTION 3: KEY FACTS GRID ── */}
          <section className="sa-section sa-section--surface sa-reveal">
            <div className="sa-section__inner">
              <div className="sa-section-header">
                <h2 className="sa-section-title">景区数据</h2>
                <p className="sa-section-subtitle">
                  一览{area.shortName || area.name}的核心数据
                </p>
              </div>

              <div className="sa-facts-grid sa-reveal-stagger">
                <div className="sa-fact-card sa-tilt-card sa-reveal-child">
                  <div className="sa-tilt-shine" />
                  <div className="sa-fact-number sa-fact-number--amber">{area.attractionCount}</div>
                  <div className="sa-fact-label">核心景点</div>
                </div>
                <div className="sa-fact-card sa-tilt-card sa-reveal-child">
                  <div className="sa-tilt-shine" />
                  <div className="sa-fact-number sa-fact-number--teal">
                    3-4<span className="sa-fact-unit">h</span>
                  </div>
                  <div className="sa-fact-label">游览时长</div>
                </div>
                <div className="sa-fact-card sa-tilt-card sa-reveal-child">
                  <div className="sa-tilt-shine" />
                  <div className="sa-fact-number sa-fact-number--coral">4.8</div>
                  <div className="sa-fact-label">游客评分</div>
                </div>
                <div className="sa-fact-card sa-tilt-card sa-reveal-child">
                  <div className="sa-tilt-shine" />
                  <div className="sa-fact-number sa-fact-number--rose">
                    200<span className="sa-fact-unit">万+</span>
                  </div>
                  <div className="sa-fact-label">年接待人次</div>
                </div>
              </div>
            </div>
          </section>

          {/* ── SECTION 4: AUDIENCES ── */}
          <section className="sa-section sa-section--bg sa-reveal">
            <div className="sa-section__inner">
              <div className="sa-section-header">
                <h2 className="sa-section-title">适合人群</h2>
                <p className="sa-section-subtitle">
                  无论您是哪种旅行者，{area.shortName || area.name}都能满足您的期待
                </p>
              </div>

              <div className="sa-audiences-grid sa-reveal-stagger">
                {audiences.map((item, idx) => {
                  const meta = AUDIENCE_META[idx % AUDIENCE_META.length];
                  const title = typeof item === "string" ? item : item.title || item;
                  const desc = typeof item === "string" ? "" : item.description || "";
                  return (
                    <div
                      key={idx}
                      className="sa-audience-card sa-tilt-card sa-reveal-child"
                      style={{ borderTopColor: meta.color }}
                    >
                      <div className="sa-tilt-shine" />
                      <div
                        className="sa-audience-icon"
                        style={{ background: meta.bg, color: meta.color }}
                      >
                        <i className={meta.icon} />
                      </div>
                      <h3 className="sa-audience-card__title">{title}</h3>
                      {desc && <p className="sa-audience-card__desc">{desc}</p>}
                    </div>
                  );
                })}
              </div>
            </div>
          </section>

          {/* ── SECTION 5: SIGNATURE EXPERIENCES (2x2) ── */}
          <section className="sa-section sa-section--gradient sa-reveal">
            <div className="sa-section__tint sa-section__tint--teal" />
            <div className="sa-section__inner sa-section__inner--z">
              <div className="sa-section-header">
                <h2 className="sa-section-title">标志体验</h2>
                <p className="sa-section-subtitle">
                  不可错过的{area.shortName || area.name}经典体验
                </p>
              </div>

              <div className="sa-exp-grid sa-reveal-stagger">
                {signatureExperiences.map((item, idx) => {
                  const title = typeof item === "string" ? item : item.title || item;
                  const desc =
                    typeof item === "string"
                      ? SIG_DESCRIPTIONS[idx] || area.heroCopy || ""
                      : item.description || area.heroCopy || "";
                  const img =
                    typeof item === "object" && item.image
                      ? item.image
                      : heroAssets[idx] || heroImage;
                  return (
                    <div key={idx} className="sa-exp-card sa-tilt-card sa-reveal-child">
                      <div className="sa-tilt-shine" />
                      <img src={img} alt={title} loading="lazy" />
                      <div className="sa-exp-card__overlay">
                        <h3 className="sa-exp-card__title">{title}</h3>
                        <p className="sa-exp-card__desc">{desc}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </section>

          {/* ── SECTION 6: ATTRACTIONS (vertical list) ── */}
          <section className="sa-section sa-section--bg sa-reveal">
            <div className="sa-section__inner">
              <div className="sa-section-header">
                <h2 className="sa-section-title">核心景点</h2>
                <p className="sa-section-subtitle">
                  探索{area.shortName || area.name}的{area.attractionCount}大核心景点
                </p>
              </div>

              <div className="sa-attractions-list">
                {attractions.map((item) => (
                  <a
                    key={item.attractionId}
                    href={buildAttractionHref(item.scenicSlug || area.slug, item.attractionId)}
                    className="sa-attraction-row sa-tilt-card"
                  >
                    <div className="sa-tilt-shine" />
                    {item.image && (
                      <img
                        src={item.image}
                        alt={item.attractionName}
                        loading="lazy"
                        className="sa-attraction-thumb sa-img-lazy"
                        onLoad={(e) => e.target.classList.add("sa-img-loaded")}
                      />
                    )}
                    <div className="sa-attraction-row__body">
                      <div className="sa-attraction-row__header">
                        <h3 className="sa-attraction-row__name">{item.attractionName}</h3>
                        <span className="sa-id-badge">{item.attractionId}</span>
                      </div>
                      <p className="sa-attraction-row__desc">{item.description}</p>
                      <span className="sa-detail-link">
                        查看详情 <i className="fas fa-arrow-right sa-detail-link__icon" />
                      </span>
                    </div>
                  </a>
                ))}
              </div>
            </div>
          </section>

          {/* ── SECTION 7: PHOTO GALLERY ── */}
          {galleryImages.length > 0 && (
            <section className="sa-section sa-section--gradient sa-section--gradient-coral sa-reveal">
              <div className="sa-section__tint sa-section__tint--coral" />
              <div className="sa-section__inner sa-section__inner--z">
                <div className="sa-section-header">
                  <h2 className="sa-section-title">景区风光</h2>
                  <p className="sa-section-subtitle">
                    用镜头记录{area.shortName || area.name}的壮丽与宁静
                  </p>
                </div>

                <div className="sa-gallery-flow sa-reveal-stagger">
                  {galleryRows.map((row, rowIndex) => (
                    <div key={rowIndex} className={`sa-gallery-row sa-gallery-row--${rowIndex + 1}`}>
                      {[...row, ...row].map((img, idx) => (
                        <div key={`${img.src}-${rowIndex}-${idx}`} className="sa-gallery-item sa-reveal-scale sa-reveal-child">
                          <img
                            src={img.src}
                            alt={img.alt || `${area.name}风光${idx + 1}`}
                            loading="lazy"
                            className="sa-parallax-img"
                          />
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            </section>
          )}

          {/* ── SECTION 8: PRACTICAL INFO ── */}
          <section className="sa-section sa-section--bg sa-reveal">
            <div className="sa-section__inner">
              <div className="sa-section-header">
                <h2 className="sa-section-title">游览信息</h2>
                <p className="sa-section-subtitle">出行前需要了解的实用信息</p>
              </div>

              <div className="sa-info-grid">
                {/* Left: info list */}
                <div className="sa-info-list sa-reveal-left">
                  {practicalInfo.map((info, idx) => (
                    <div key={idx} className="sa-info-item">
                      <div className="sa-info-bullet" />
                      <div>
                        <p className="sa-info-item__title">{info.title}</p>
                        <p className="sa-info-item__content">{info.content}</p>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Right: image */}
                <div className="sa-info-image sa-reveal-right">
                  <div className="sa-info-image__frame">
                    {heroAssets[2] && (
                      <img
                        src={heroAssets[2]}
                        alt={`${area.name}鸟瞰`}
                        loading="lazy"
                        className="sa-img-lazy sa-parallax-img"
                        onLoad={(e) => e.target.classList.add("sa-img-loaded")}
                      />
                    )}
                  </div>
                  <div className="sa-info-image__accent" />
                </div>
              </div>
            </div>
          </section>

          {/* ── SECTION 9: CTA ── */}
          <section className="sa-section sa-section--cta sa-reveal">
            <div className="sa-section__glow" />
            <div className="sa-section__inner sa-section__inner--z sa-section__inner--center">
              <h2 className="sa-cta-title">准备好探索{area.name}了吗?</h2>
              <p className="sa-cta-subtitle">通过AI数字人导游获取个性化景点讲解与智能路线推荐</p>
              <div className="sa-cta-actions">
                <a
                  href={buildGuideHref({ scenicSlug: area.slug, scenicName: area.name })}
                  className="sa-btn-solid sa-magnetic-btn sa-btn-pulse"
                >
                  <i className="fas fa-comments" />
                  {guideLabel}
                </a>
                <a
                  href={buildPlannerHref(area.slug)}
                  className="sa-btn-outline-teal sa-magnetic-btn"
                >
                  <i className="fas fa-route" />
                  规划游览路线
                </a>
              </div>
            </div>
          </section>
        </main>

        <ProductFooter />
      </div>
    </div>
  );
}
