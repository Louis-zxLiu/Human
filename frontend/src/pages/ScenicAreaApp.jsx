import React, { useEffect, useState } from "react";

import { AttractionSpotCard } from "../components/AttractionSpotCard";
import { ProductFooter } from "../components/ProductFooter";
import { ProductHeader } from "../components/ProductHeader";
import { fetchScenicArea, fetchScenicAttractions } from "../lib/api";
import { buildGuideHref, buildPlannerHref } from "../lib/routes";

export function ScenicAreaApp({ scenicSlug }) {
  const token = localStorage.getItem("auth_token");
  const guideLabel = token ? "开始导览" : "登录后开始导览";
  const [area, setArea] = useState(null);
  const [attractions, setAttractions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    Promise.all([fetchScenicArea(scenicSlug), fetchScenicAttractions(scenicSlug)])
      .then(([areaResult, attractionResult]) => {
        if (!alive) return;
        setArea(areaResult);
        setAttractions(attractionResult);
      })
      .catch((err) => {
        if (!alive) return;
        setError(err.message);
      })
      .finally(() => {
        if (!alive) return;
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [scenicSlug]);

  if (loading) {
    return (
      <div className="product-page">
        <div className="page-container">
          <ProductHeader />
          <div className="loading-row">正在加载园区资料...</div>
        </div>
      </div>
    );
  }

  if (!area) {
    return (
      <div className="product-page">
        <div className="page-container">
          <ProductHeader />
          <div className="feedback feedback-danger">{error || "园区资料暂时不可用。"}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="product-page">
      <div className="page-container">
        <ProductHeader />

        <section className="scenic-hero">
          <div className="scenic-hero__image">
            <img src={area.heroImage} alt={area.name} />
          </div>
          <div className="scenic-hero__copy">
            <div className="eyebrow">{area.shortName}</div>
            <h1>{area.name}</h1>
            <p>{area.tagline}</p>
            <div className="scenic-hero__chips">
              {area.recommendedAudiences.map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
            <div className="landing-hero__actions">
              <a href={buildPlannerHref(area.slug)} className="button-primary">按这个园区规划路线</a>
              <a
                href={buildGuideHref({ scenicSlug: area.slug, scenicName: area.name })}
                className="button-secondary"
              >
                {guideLabel}
              </a>
            </div>
          </div>
        </section>

        <section className="product-section">
          <div className="product-section__header">
            <div>
              <div className="eyebrow">园区概述</div>
              <h2>先理解它适合什么人，再决定怎么逛。</h2>
            </div>
            <p>{area.summary}</p>
          </div>

          <div className="area-signature-grid">
            {area.signatureExperiences.map((item) => (
              <div key={item} className="narrative-card">
                <strong>{item}</strong>
                <span>{area.heroCopy}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="product-section">
          <div className="product-section__header">
            <div>
              <div className="eyebrow">核心景点</div>
              <h2>从结构化景点库里挑出最适合讲故事的节点。</h2>
            </div>
            <p>{area.attractionCount} 个景点已进入结构化事实层，可直接被路线规划和数字人消费。</p>
          </div>

          <div className="spot-card-grid">
            {attractions.map((attraction) => (
              <AttractionSpotCard key={attraction.attractionId} attraction={attraction} />
            ))}
          </div>
        </section>

        <ProductFooter />
      </div>
    </div>
  );
}
