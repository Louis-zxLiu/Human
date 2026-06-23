import React from "react";

import { normalizePathname } from "./lib/routes";
import { AdminApp } from "./pages/AdminApp";
import { GuideApp } from "./pages/GuideApp";
import { HomeApp } from "./pages/HomeApp";
import { LoginApp } from "./pages/LoginApp";
import { PlannerApp } from "./pages/PlannerApp";
import { ScenicAreaApp } from "./pages/ScenicAreaApp";
import { ScenicAttractionApp } from "./pages/ScenicAttractionApp";
import { NotFoundApp } from "./pages/NotFoundApp";

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
