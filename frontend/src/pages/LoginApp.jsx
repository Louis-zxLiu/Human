import React, { useEffect, useState } from "react";

import { login, register } from "../lib/api";
import { safeInternalPath } from "../lib/routes";

const BACKGROUND_IMAGES = [
  "/media/scenic/lingshan-shengjing/lingshan-hero-1.jpg",
  "/media/scenic/lingshan-shengjing/lingshan-hero-3.jpg",
  "/media/scenic/nianhuawan/nianhuawan-hero-1.jpg",
  "/media/scenic/nianhuawan/nianhuawan-hero-2.jpg",
];

const AUTH_THEMES = [
  {
    accent: "#6d8071",
    accentStrong: "#42594b",
    accentSoft: "rgba(109, 128, 113, 0.16)",
    overlayWarm: "rgba(207, 143, 60, 0.14)",
  },
  {
    accent: "#8d6f56",
    accentStrong: "#5d4636",
    accentSoft: "rgba(141, 111, 86, 0.16)",
    overlayWarm: "rgba(201, 126, 82, 0.12)",
  },
  {
    accent: "#7f5d46",
    accentStrong: "#5b4032",
    accentSoft: "rgba(127, 93, 70, 0.16)",
    overlayWarm: "rgba(74, 159, 138, 0.1)",
  },
  {
    accent: "#8a6b4a",
    accentStrong: "#624d36",
    accentSoft: "rgba(138, 107, 74, 0.16)",
    overlayWarm: "rgba(82, 157, 199, 0.08)",
  },
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

export function LoginApp() {
  const nextPath = safeInternalPath(new URLSearchParams(window.location.search).get("next") || "", "");
  const [isLogin, setIsLogin] = useState(true);
  const [form, setForm] = useState({ username: "", password: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [activeImageIndex, setActiveImageIndex] = useState(0);

  useEffect(() => {
    const token = localStorage.getItem("auth_token");
    if (!token) return;
    const role = localStorage.getItem("user_role");
    window.location.href = nextPath || (role === "admin" ? "/admin" : "/guide");
  }, [nextPath]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setActiveImageIndex((current) => (current + 1) % BACKGROUND_IMAGES.length);
    }, 4800);
    return () => window.clearInterval(timer);
  }, []);

  const activeTheme = AUTH_THEMES[activeImageIndex % AUTH_THEMES.length];
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
        window.location.href = nextPath || (result.role === "admin" ? "/admin" : "/guide");
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
    <div
      className="auth-scene"
      style={{
        "--auth-accent": activeTheme.accent,
        "--auth-accent-strong": activeTheme.accentStrong,
        "--auth-accent-soft": activeTheme.accentSoft,
        "--auth-overlay-warm": activeTheme.overlayWarm,
      }}
    >
      <div className="auth-scene__background" aria-hidden="true">
        {BACKGROUND_IMAGES.map((src, index) => (
          <div
            key={src}
            className={`auth-scene__slide ${index === activeImageIndex ? "is-active" : ""}`}
            style={{ backgroundImage: `url(${src})` }}
          />
        ))}
        <div className="auth-scene__overlay" />
      </div>

      <div className="auth-scene__content">
        <section className="auth-card">
          <div className="auth-card__brand">
            <span className="product-header__brand-mark">灵</span>
            <div>
              <strong>灵山智慧导览</strong>
              <small>数字人导览与运营平台</small>
            </div>
          </div>

          <div className="auth-switch" role="tablist" aria-label="登录与注册">
            <div className={`auth-switch__glider ${isLogin ? "is-login" : "is-register"}`} />
            <button
              type="button"
              className={`auth-switch__option ${isLogin ? "is-active" : ""}`}
              onClick={() => switchMode(true)}
            >
              登录
            </button>
            <button
              type="button"
              className={`auth-switch__option ${!isLogin ? "is-active" : ""}`}
              onClick={() => switchMode(false)}
            >
              注册
            </button>
          </div>

          <div className="auth-card__copy">
            <div className="eyebrow">{isLogin ? "开始使用" : "创建账号"}</div>
            <h1>{isLogin ? "进入数字人导览" : "创建游客账号"}</h1>
            <p>
              {isLogin
                ? "登录后会直接进入导览，并保留当前园区、景点或路线语境。"
                : "创建成功后可立即登录，继续浏览园区或直接开始导览。"}
            </p>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            <label className="field">
              <span className="field-label">用户名</span>
              <input
                className="input-field"
                value={form.username}
                onChange={(event) => setForm({ ...form, username: event.target.value })}
                placeholder="请输入用户名"
                autoComplete="username"
              />
            </label>

            <label className="field">
              <span className="field-label">密码</span>
              <input
                className="input-field"
                type="password"
                value={form.password}
                onChange={(event) => setForm({ ...form, password: event.target.value })}
                placeholder={isLogin ? "请输入密码" : "至少 8 位，且包含两类字符"}
                autoComplete={isLogin ? "current-password" : "new-password"}
              />
            </label>

            {!isLogin ? (
              <div className={`auth-password-hint ${registerPasswordHint ? "is-warning" : "is-valid"}`}>
                {registerPasswordHint || "密码格式符合要求。"}
              </div>
            ) : null}

            {error ? <div className="feedback feedback-danger">{error}</div> : null}
            {!error && notice ? <div className="feedback feedback-success">{notice}</div> : null}

            <button
              type="submit"
              className="button-primary button-block auth-submit"
              disabled={loading || (!isLogin && Boolean(registerPasswordHint))}
            >
              {loading ? "处理中..." : isLogin ? "开始导览" : "创建账号"}
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}
