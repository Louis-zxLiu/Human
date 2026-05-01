import React, { useEffect, useState } from "react";

import { login, register } from "../lib/api";

const AUTH_FEATURES = [
  {
    title: "游客导览",
    copy: "景点问答、路线推荐和弱 GPS 导航都放在一个连续的对话入口里。",
  },
  {
    title: "数字人联动",
    copy: "视频、语音和文本响应在同一个前台里保持统一节奏。",
  },
  {
    title: "运营洞察",
    copy: "后台直接查看趋势、热点问题和失败样例，不再只是静态列表。",
  },
];

export function LoginApp() {
  const [isLogin, setIsLogin] = useState(true);
  const [form, setForm] = useState({ username: "", password: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const token = localStorage.getItem("auth_token");
    if (!token) return;
    const role = localStorage.getItem("user_role");
    window.location.href = role === "admin" ? "/admin" : "/";
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");

    try {
      if (isLogin) {
        const result = await login(form);
        localStorage.setItem("auth_token", result.access_token);
        localStorage.setItem("username", result.username);
        localStorage.setItem("user_role", result.role);
        window.location.href = result.role === "admin" ? "/admin" : "/";
        return;
      }

      await register(form);
      setIsLogin(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page-shell auth-page">
      <div className="page-container">
        <div className="auth-layout">
          <section className="panel panel-dark auth-hero">
            <div className="eyebrow">灵山胜境数字人系统</div>
            <h1 className="hero-title">把游客接待、数字人展示和运营后台整理成一套更像产品的前端。</h1>
            <p className="hero-copy">
              新版前台围绕真实接待路径重做：游客端以数字人舞台为主，历史会话按用户名保存在本地，后台则聚焦运营判断最需要的几组信号。
            </p>

            <div className="auth-feature-list">
              {AUTH_FEATURES.map((feature) => (
                <article key={feature.title} className="auth-feature-card">
                  <strong>{feature.title}</strong>
                  <span>{feature.copy}</span>
                </article>
              ))}
            </div>
          </section>

          <section className="panel auth-form-panel">
            <div className="panel-header">
              <div>
                <div className="eyebrow">统一入口</div>
                <h2 className="panel-title">{isLogin ? "登录系统" : "创建账号"}</h2>
              </div>
              <button
                type="button"
                className="text-button"
                onClick={() => {
                  setIsLogin((value) => !value);
                  setError("");
                }}
              >
                {isLogin ? "没有账号？去注册" : "已有账号？去登录"}
              </button>
            </div>

            <p className="panel-copy">
              {isLogin
                ? "使用游客或管理员账号进入新版前台。"
                : "新建游客账号后，登录将直接进入新的会话界面。"}
            </p>

            <form className="auth-form" onSubmit={handleSubmit}>
              <label className="field">
                <span className="field-label">用户名</span>
                <input
                  className="input-field"
                  value={form.username}
                  onChange={(event) => setForm({ ...form, username: event.target.value })}
                  placeholder="输入用户名"
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
                  placeholder="输入密码"
                  autoComplete={isLogin ? "current-password" : "new-password"}
                />
              </label>

              {error ? <div className="feedback feedback-danger">{error}</div> : null}
              {!error && !isLogin ? <div className="feedback feedback-info">注册成功后会自动切回登录状态。</div> : null}

              <button type="submit" className="button-primary button-block" disabled={loading}>
                {loading ? "处理中..." : isLogin ? "进入前台" : "创建账号"}
              </button>
            </form>
          </section>
        </div>
      </div>
    </div>
  );
}
