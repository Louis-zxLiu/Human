import React, { useEffect } from "react";

import { VisitorApp } from "./VisitorApp";
import { buildLoginHref, currentGuidePath, readGuideContext } from "../lib/routes";

export function GuideApp() {
  const token = localStorage.getItem("auth_token");
  const guideContext = readGuideContext();

  useEffect(() => {
    if (token) return;
    window.location.href = buildLoginHref(currentGuidePath());
  }, [token]);

  if (!token) {
    return null;
  }

  return <VisitorApp guideContext={guideContext} embedded productTone />;
}
