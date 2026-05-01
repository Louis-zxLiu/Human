import React, { useState } from "react";

import { login, register } from "../lib/api";


export function LoginApp() {
  const [isLogin, setIsLogin] = useState(true);
  const [form, setForm] = useState({ username: "", password: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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
      } else {
        await register(form);
        setIsLogin(true);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page-shell" style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="card" style={{ width: "100%", maxWidth: 420, padding: 28 }}>
        <h1 style={{ margin: 0, fontSize: 28 }}>{isLogin ? "用户登录" : "用户注册"}</h1>
        <p className="muted">工程化景区数字人系统</p>
        <form onSubmit={handleSubmit} className="grid" style={{ marginTop: 20 }}>
          <input className="input" value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} placeholder="用户名" />
          <input className="input" type="password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} placeholder="密码" />
          {error ? <div className="status-danger pill" style={{ borderRadius: 12 }}>{error}</div> : null}
          <button className="button-primary" type="submit" disabled={loading}>{loading ? "处理中..." : isLogin ? "登录" : "注册"}</button>
        </form>
        <button className="button-secondary" style={{ width: "100%", marginTop: 14 }} onClick={() => setIsLogin((value) => !value)}>
          {isLogin ? "没有账号？立即注册" : "已有账号？返回登录"}
        </button>
      </div>
    </div>
  );
}
