import React from "react";

import { normalizePathname } from "./lib/routes";
import { ProductHeader } from "./components/ProductHeader";
import { AdminApp } from "./pages/AdminApp";
import { GuideApp } from "./pages/GuideApp";
import { HomeApp } from "./pages/HomeApp";
import { LoginApp } from "./pages/LoginApp";
import { PlannerApp } from "./pages/PlannerApp";
import { ScenicAreaApp } from "./pages/ScenicAreaApp";
import { ScenicAttractionApp } from "./pages/ScenicAttractionApp";

function NotFoundApp() {
  return (
    <div className="product-page">
      <div className="page-container">
        <ProductHeader />
        <div className="empty-state">
          <strong>页面不存在</strong>
          <span>这个路径没有对应的公开产品页。</span>
        </div>
      </div>
    </div>
  );
}

export function AppRouter() {
  const pathname = normalizePathname(window.location.pathname);
  const segments = pathname.split("/").filter(Boolean);

  if (pathname === "/admin") {
    return <AdminApp />;
  }
  if (pathname === "/login") {
    return <LoginApp />;
  }
  if (pathname === "/guide") {
    return <GuideApp />;
  }
  if (pathname === "/planner") {
    return <PlannerApp />;
  }
  if (segments[0] === "scenic" && segments.length === 2) {
    return <ScenicAreaApp scenicSlug={decodeURIComponent(segments[1])} />;
  }
  if (segments[0] === "scenic" && segments[2] === "attractions" && segments[3]) {
    return <ScenicAttractionApp attractionId={decodeURIComponent(segments[3])} />;
  }
  if (pathname === "/") {
    return <HomeApp />;
  }
  return <NotFoundApp />;
}
