import React, { useEffect, useState, useRef, useCallback } from "react";

import { login, register } from "../lib/api";
import { safeInternalPath } from "../lib/routes";

const BACKGROUND_IMAGES = [
  "/media/scenic/lingshan-shengjing/lingshan-hero-1.jpg",
  "/media/scenic/lingshan-shengjing/lingshan-hero-3.jpg",
  "/media/scenic/nianhuawan/nianhuawan-hero-1.jpg",
  "/media/scenic/nianhuawan/nianhuawan-hero-2.jpg",
];

function countPasswordCategories(password) {
  const hasLetter = /[A-Za-z]/.test(password);
  const hasNumber = /\d/.test(password);
  const hasSymbol = /[^A-Za-z0-9]/.test(password);
  return [hasLetter, hasNumber, hasSymbol].filter(Boolean).length;
}

function validateRegisterPassword(password) {
  if (password.length < 8) {
    return "密码至少需要 8 位。";
  }
  if (countPasswordCategories(password) < 2) {
    return "密码需至少包含字母、数字、符号中的任意两种。";
  }
  return "";
}

/* ─── Particle Canvas Hook ─── */
function useParticleCanvas(canvasRef) {
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;

    const ctx = canvas.getContext("2d");
    let animId;

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    }
    resize();

    const PARTICLE_COUNT = 25;
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
      animId = requestAnimationFrame(animate);
    }
    animate();

    window.addEventListener("resize", resize, { passive: true });
    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", resize);
    };
  }, [canvasRef]);
}

/* ─── Cursor Glow Hook ─── */
function useCursorGlow(glowRef) {
  useEffect(() => {
    const glow = glowRef.current;
    if (!glow) return;

    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;

    let mx = 0,
      my = 0,
      gx = 0,
      gy = 0;
    let animId;

    function onMove(e) {
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

    document.addEventListener("mousemove", onMove, { passive: true });
    updateGlow();

    return () => {
      cancelAnimationFrame(animId);
      document.removeEventListener("mousemove", onMove);
    };
  }, [glowRef]);
}

/* ─── Magnetic Button Hook ─── */
function useMagneticButton(btnRef) {
  useEffect(() => {
    const btn = btnRef.current;
    if (!btn) return;

    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;

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
  }, [btnRef]);
}

/* ─── Main Component ─── */
export function LoginApp() {
  const nextPath = safeInternalPath(
    new URLSearchParams(window.location.search).get("next") || "",
    ""
  );
  const [isLogin, setIsLogin] = useState(true);
  const [form, setForm] = useState({ username: "", password: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [activeImageIndex, setActiveImageIndex] = useState(0);

  const particleCanvasRef = useRef(null);
  const cursorGlowRef = useRef(null);
  const submitBtnRef = useRef(null);

  useParticleCanvas(particleCanvasRef);
  useCursorGlow(cursorGlowRef);
  useMagneticButton(submitBtnRef);

  /* Auto-redirect if already logged in */
  useEffect(() => {
    const token = localStorage.getItem("auth_token");
    if (!token) return;
    const role = localStorage.getItem("user_role");
    window.location.href = nextPath || (role === "admin" ? "/admin" : "/guide");
  }, [nextPath]);

  /* Background slideshow: 4 images, 4.8s interval */
  useEffect(() => {
    const timer = window.setInterval(() => {
      setActiveImageIndex((current) => (current + 1) % BACKGROUND_IMAGES.length);
    }, 4800);
    return () => window.clearInterval(timer);
  }, []);

  const registerPasswordHint = !isLogin ? validateRegisterPassword(form.password) : "";

  async function handleSubmit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setNotice("");

    try {
      if (isLogin) {
        const result = await login(form);
        localStorage.setItem("auth_token", result.access_token);
        localStorage.setItem("username", result.username);
        localStorage.setItem("user_role", result.role);
        window.location.href =
          nextPath || (result.role === "admin" ? "/admin" : "/guide");
        return;
      }

      const passwordError = validateRegisterPassword(form.password);
      if (passwordError) {
        throw new Error(passwordError);
      }

      await register(form);
      setNotice("账号已创建，现在可以直接登录。");
      setIsLogin(true);
      setForm((previous) => ({ ...previous, password: "" }));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function switchMode(nextIsLogin) {
    setIsLogin(nextIsLogin);
    setError("");
    setNotice("");
  }

  return (
    <div className="lp-page">
      {/* Particle Canvas */}
      <canvas
        ref={particleCanvasRef}
        className="lp-particle-canvas"
        aria-hidden="true"
      />

      {/* Cursor Glow */}
      <div ref={cursorGlowRef} className="lp-cursor-glow" aria-hidden="true" />

      <div className="lp-layout">
        {/* ── Left Panel: Background Slideshow ── */}
        <div className="lp-left">
          {BACKGROUND_IMAGES.map((src, index) => (
            <div
              key={src}
              className={`lp-left__slide ${index === activeImageIndex ? "lp-left__slide--active" : ""}`}
              style={{ backgroundImage: `url(${src})` }}
              aria-hidden="true"
            />
          ))}
          <div className="lp-left__overlay" aria-hidden="true" />

          <div className="lp-left__text lp-anim-left">
            <h2>探索世界，从这里开始</h2>
            <p>AI数字人导游，为您开启智慧文旅新体验</p>
          </div>
        </div>

        {/* ── Right Panel: Form ── */}
        <div className="lp-right lp-anim-right">
          {/* Brand */}
          <div className="lp-brand lp-anim-up lp-delay-1">
            <span className="lp-brand-mark">灵</span>
            <div className="lp-brand-text">
              <strong>灵山智慧导览</strong>
              <small>数字人导览与运营平台</small>
            </div>
          </div>

          {/* Welcome */}
          <h1 className="lp-welcome lp-anim-up lp-delay-2">
            {isLogin ? "欢迎回来" : "创建账号"}
          </h1>
          <p className="lp-welcome-sub lp-anim-up lp-delay-2">
            {isLogin
              ? "登录您的账号，继续探索精彩旅程"
              : "注册新账号，开始您的智慧导览体验"}
          </p>

          {/* Tabs */}
          <div className="lp-tabs lp-anim-up lp-delay-3" role="tablist" aria-label="登录与注册">
            <button
              type="button"
              className={`lp-tab ${isLogin ? "lp-tab--active" : ""}`}
              role="tab"
              aria-selected={isLogin}
              onClick={() => switchMode(true)}
            >
              登录
            </button>
            <button
              type="button"
              className={`lp-tab ${!isLogin ? "lp-tab--active" : ""}`}
              role="tab"
              aria-selected={!isLogin}
              onClick={() => switchMode(false)}
            >
              注册
            </button>
          </div>

          {/* Form */}
          <form className="lp-form" onSubmit={handleSubmit}>
            <div className="lp-form-group lp-anim-up lp-delay-3">
              <label className="lp-form-label">用户名</label>
              <input
                className="lp-form-input"
                type="text"
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                placeholder="请输入用户名"
                autoComplete="username"
              />
            </div>

            <div className="lp-form-group lp-anim-up lp-delay-4">
              <label className="lp-form-label">密码</label>
              <input
                className="lp-form-input"
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder={
                  isLogin ? "请输入密码" : "至少 8 位，且包含两类字符"
                }
                autoComplete={isLogin ? "current-password" : "new-password"}
              />
            </div>

            {/* Password hint (register only) */}
            {!isLogin ? (
              <div
                className={`lp-password-hint lp-anim-up lp-delay-4 ${
                  registerPasswordHint
                    ? "lp-password-hint--warning"
                    : "lp-password-hint--valid"
                }`}
              >
                {registerPasswordHint || "密码格式符合要求。"}
              </div>
            ) : null}

            {/* Feedback */}
            {error ? (
              <div className="lp-feedback lp-feedback--error lp-anim-up lp-delay-4">
                {error}
              </div>
            ) : null}
            {!error && notice ? (
              <div className="lp-feedback lp-feedback--success lp-anim-up lp-delay-4">
                {notice}
              </div>
            ) : null}

            {/* Submit */}
            <button
              ref={submitBtnRef}
              type="submit"
              className="lp-submit lp-magnetic-btn lp-anim-up lp-delay-5"
              disabled={loading || (!isLogin && Boolean(registerPasswordHint))}
            >
              {loading
                ? "处理中..."
                : isLogin
                  ? "开始导览"
                  : "创建账号"}
            </button>
          </form>

          {/* Bottom Link */}
          <div className="lp-bottom-link lp-anim-up lp-delay-5">
            {isLogin ? (
              <span>
                还没有账号？{" "}
                <button type="button" className="lp-link-btn" onClick={() => switchMode(false)}>
                  立即注册
                </button>
              </span>
            ) : (
              <span>
                已有账号？{" "}
                <button type="button" className="lp-link-btn" onClick={() => switchMode(true)}>
                  立即登录
                </button>
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
