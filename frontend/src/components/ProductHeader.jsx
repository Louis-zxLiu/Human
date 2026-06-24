import React from "react";

import { buildGuideHref, buildMemory3DHref, buildPlannerHref } from "../lib/routes";

export function ProductHeader({ active = "home" }) {
  const token = localStorage.getItem("auth_token");
  const role = localStorage.getItem("user_role");
  const scenicGuideHref = buildGuideHref();
  const guideLabel = token ? "开始导览" : "登录后开始导览";

  return (
    <header className="product-header">
      <a href="/" className="product-header__brand">
        <span className="product-header__brand-mark">灵</span>
        <span>
          <strong>灵山智慧导览</strong>
          <small>双园区数字人服务系统</small>
        </span>
      </a>

      <nav className="product-header__nav">
        <a href="/" className={active === "home" ? "is-active" : ""}>首页</a>
        <a href={buildPlannerHref()} className={active === "planner" ? "is-active" : ""}>路线推荐</a>
        <a href={scenicGuideHref} className={active === "guide" ? "is-active" : ""}>数字人导览</a>
        <a href={buildMemory3DHref()} className={active === "memory3d" ? "is-active" : ""}>3D记忆</a>
        {role === "admin" ? <a href="/admin" className={active === "admin" ? "is-active" : ""}>后台</a> : null}
      </nav>

      <div className="product-header__actions">
        {role === "admin" && active !== "admin" ? <a href="/admin" className="button-secondary compact-link">后台</a> : null}
        {token ? (
          <a href={scenicGuideHref} className="button-primary compact-link">{guideLabel}</a>
        ) : (
          <a href="/login" className="button-primary compact-link">{guideLabel}</a>
        )}
      </div>
    </header>
  );
}
