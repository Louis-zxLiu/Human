import React, { useEffect, useRef, useCallback } from "react";

import { buildPlannerHref, buildLoginHref } from "../lib/routes";
import { ProductHeader } from "../components/ProductHeader";
import { ProductFooter } from "../components/ProductFooter";

/* ------------------------------------------------------------------ */
/*  Particle canvas                                                    */
/* ------------------------------------------------------------------ */
function ParticleCanvas() {
  const canvasRef = useRef(null);
  const rafRef = useRef(0);

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

    const PARTICLE_COUNT = 20;
    const particles = Array.from({ length: PARTICLE_COUNT }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: Math.random() * 1.5 + 0.5,
      o: Math.random() * 0.3 + 0.1,
      vx: (Math.random() - 0.5) * 0.3,
      vy: -(Math.random() * 0.3 + 0.1),
      phase: Math.random() * Math.PI * 2,
    }));

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
      rafRef.current = requestAnimationFrame(animate);
    }
    animate();

    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return <canvas ref={canvasRef} className="notfound-canvas" />;
}

/* ------------------------------------------------------------------ */
/*  Cursor glow                                                        */
/* ------------------------------------------------------------------ */
function CursorGlow() {
  const glowRef = useRef(null);
  const rafRef = useRef(0);
  const mouse = useRef({ x: 0, y: 0 });
  const glow = useRef({ x: 0, y: 0 });

  useEffect(() => {
    const onMove = (e) => {
      mouse.current.x = e.clientX;
      mouse.current.y = e.clientY;
    };
    document.addEventListener("mousemove", onMove, { passive: true });

    function tick() {
      glow.current.x += (mouse.current.x - glow.current.x) * 0.08;
      glow.current.y += (mouse.current.y - glow.current.y) * 0.08;
      const el = glowRef.current;
      if (el) {
        el.style.left = glow.current.x + "px";
        el.style.top = glow.current.y + "px";
      }
      rafRef.current = requestAnimationFrame(tick);
    }
    tick();

    return () => {
      document.removeEventListener("mousemove", onMove);
      cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return <div ref={glowRef} className="notfound-cursor-glow" />;
}

/* ------------------------------------------------------------------ */
/*  Magnetic button wrapper                                           */
/* ------------------------------------------------------------------ */
function MagneticButton({ children, className = "", ...rest }) {
  const ref = useRef(null);

  const onMouseMove = useCallback((e) => {
    const btn = ref.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const x = e.clientX - rect.left - rect.width / 2;
    const y = e.clientY - rect.top - rect.height / 2;
    btn.style.transform = `translate(${x * 0.15}px, ${y * 0.15}px)`;
  }, []);

  const onMouseLeave = useCallback(() => {
    const btn = ref.current;
    if (btn) btn.style.transform = "translate(0, 0)";
  }, []);

  return (
    <button
      ref={ref}
      className={`notfound-magnetic ${className}`}
      onMouseMove={onMouseMove}
      onMouseLeave={onMouseLeave}
      {...rest}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Suggestion card                                                   */
/* ------------------------------------------------------------------ */
function SuggestionCard({ label, desc, href }) {
  return (
    <a href={href} className="notfound-suggest-card">
      <strong>{label}</strong>
      <span>{desc}</span>
    </a>
  );
}

/* ------------------------------------------------------------------ */
/*  NotFoundApp                                                        */
/* ------------------------------------------------------------------ */
export function NotFoundApp() {
  const contentRef = useRef(null);

  useEffect(() => {
    const root = contentRef.current;
    if (!root) return undefined;

    const timers = new Set();
    const frames = new Set();
    const easeOut = (value) => 1 - Math.pow(1 - value, 3);
    const mix = (from, to, progress) => from + (to - from) * progress;

    const items = Array.from(root.querySelectorAll(".notfound-animate, .notfound-animate-scale"));
    items.forEach((item, index) => {
      const isScale = item.classList.contains("notfound-animate-scale");
      const delay = [100, 250, 400, 550, 700][index] || 0;
      const duration = isScale ? 1000 : 800;

      item.style.animation = "none";
      item.style.opacity = "0";
      item.style.transform = isScale ? "scale(0.9)" : "translateY(30px)";
      item.style.filter = isScale ? "blur(8px)" : "blur(6px)";

      const timer = window.setTimeout(() => {
        const startedAt = window.performance?.now?.() ?? Date.now();
        const step = (now) => {
          const progress = Math.min(1, (now - startedAt) / duration);
          const eased = easeOut(progress);
          item.style.opacity = String(eased);
          item.style.transform = isScale ? `scale(${mix(0.9, 1, eased)})` : `translateY(${mix(30, 0, eased)}px)`;
          item.style.filter = `blur(${mix(isScale ? 8 : 6, 0, eased)}px)`;

          if (progress < 1) {
            const frame = window.requestAnimationFrame(step);
            frames.add(frame);
            return;
          }

          item.style.opacity = "1";
          item.style.transform = isScale ? "scale(1)" : "translateY(0)";
          item.style.filter = "none";
        };
        const frame = window.requestAnimationFrame(step);
        frames.add(frame);
      }, delay);
      timers.add(timer);
    });

    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
      frames.forEach((frame) => window.cancelAnimationFrame(frame));
    };
  }, []);

  const goBack = () => {
    if (window.history.length > 1) {
      window.history.back();
    } else {
      window.location.href = "/";
    }
  };

  return (
    <div className="notfound-scene">
      {/* Background layers */}
      <ParticleCanvas />
      <CursorGlow />

      {/* Decorative circles */}
      <div className="notfound-deco notfound-deco-1" />
      <div className="notfound-deco notfound-deco-2" />
      <div className="notfound-deco notfound-deco-3" />

      {/* Content */}
      <div className="notfound-content" ref={contentRef}>
        <ProductHeader />

        <div className="notfound-body">
          {/* 404 error code */}
          <div className="notfound-code notfound-animate-scale notfound-delay-1">
            404
          </div>

          {/* Title */}
          <h1 className="notfound-title notfound-animate notfound-delay-2">
            页面未找到
          </h1>

          {/* Description */}
          <p className="notfound-desc notfound-animate notfound-delay-3">
            抱歉，您访问的页面不存在或已被移除。
            <br />
            请检查URL是否正确，或返回首页继续浏览。
          </p>

          {/* Action buttons */}
          <div className="notfound-btn-group notfound-animate notfound-delay-4">
            <MagneticButton
              className="notfound-btn-amber"
              onClick={() => {
                window.location.href = "/";
              }}
            >
              返回首页
            </MagneticButton>
            <MagneticButton className="notfound-btn-outline" onClick={goBack}>
              返回上一页
            </MagneticButton>
            <MagneticButton
              className="notfound-btn-outline"
              onClick={() => {
                window.location.href = buildLoginHref();
              }}
            >
              前往登录
            </MagneticButton>
          </div>

          {/* Suggestion cards */}
          <div className="notfound-suggestions notfound-animate notfound-delay-5">
            <h3>或者您可能在找：</h3>
            <div className="notfound-suggest-grid">
              <SuggestionCard
                label="首页"
                desc="浏览景区概览与推荐"
                href="/"
              />
              <SuggestionCard
                label="景区详情"
                desc="查看景点介绍与图片"
                href="/scenic/lingshan"
              />
              <SuggestionCard
                label="路线规划"
                desc="智能规划游览路线"
                href={buildPlannerHref()}
              />
            </div>
          </div>
        </div>

        <ProductFooter />
      </div>
    </div>
  );
}
