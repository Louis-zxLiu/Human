import React, { useEffect } from "react";

import { ProductFooter } from "../components/ProductFooter";
import { ProductHeader } from "../components/ProductHeader";
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

  return (
    <div className="product-page guide-product-page">
      <div className="page-container">
        <ProductHeader active="guide" />
        <VisitorApp guideContext={guideContext} embedded productTone />
        <ProductFooter />
      </div>
    </div>
  );
}
