import React, { useEffect, useState } from "react";

import { ProductFooter } from "../components/ProductFooter";
import { ProductHeader } from "../components/ProductHeader";
import { fetchScenicAttraction } from "../lib/api";
import { buildGuideHref, buildPlannerHref } from "../lib/routes";

export function ScenicAttractionApp({ attractionId }) {
  const token = localStorage.getItem("auth_token");
  const guideLabel = token ? "开始导览" : "登录后开始导览";
  const [attraction, setAttraction] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    fetchScenicAttraction(attractionId)
      .then((result) => {
        if (!alive) return;
        setAttraction(result);
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
  }, [attractionId]);

  if (loading) {
    return (
      <div className="product-page">
        <div className="page-container">
          <ProductHeader />
          <div className="loading-row">正在加载景点详情...</div>
        </div>
      </div>
    );
  }

  if (!attraction) {
    return (
      <div className="product-page">
        <div className="page-container">
          <ProductHeader />
          <div className="feedback feedback-danger">{error || "景点详情暂时不可用。"}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="product-page">
      <div className="page-container">
        <ProductHeader />

        <section className="attraction-hero">
          <div className="attraction-hero__gallery">
            {attraction.gallery.map((item) => (
              <img key={item.path} src={item.path} alt={item.alt || attraction.attractionName} />
            ))}
          </div>
          <div className="attraction-hero__copy">
            <div className="eyebrow">{attraction.scenicName}</div>
            <h1>{attraction.attractionName}</h1>
            <p>{attraction.highlights || attraction.description}</p>
            <div className="landing-hero__actions">
              <a href={buildPlannerHref(attraction.scenicSlug)} className="button-secondary">先规划这座园区</a>
              <a
                href={buildGuideHref({
                  scenicSlug: attraction.scenicSlug,
                  scenicName: attraction.scenicName,
                  attractionId: attraction.attractionId,
                  attractionName: attraction.attractionName,
                })}
                className="button-primary"
              >
                {guideLabel}
              </a>
            </div>
          </div>
        </section>

        <section className="product-section">
          <div className="detail-grid">
            <article className="detail-card">
              <strong>位置</strong>
              <span>{attraction.location}</span>
            </article>
            <article className="detail-card">
              <strong>建筑 / 景观参数</strong>
              <span>{attraction.architectureParams}</span>
            </article>
            <article className="detail-card">
              <strong>核心功能</strong>
              <span>{attraction.coreFunction}</span>
            </article>
            <article className="detail-card">
              <strong>文化内涵</strong>
              <span>{attraction.culturalMeaning}</span>
            </article>
            <article className="detail-card detail-card--wide">
              <strong>详细介绍</strong>
              <span>{attraction.description}</span>
            </article>
            <article className="detail-card">
              <strong>开放 / 演艺信息</strong>
              <span>{attraction.openInfo}</span>
            </article>
            <article className="detail-card">
              <strong>游览建议</strong>
              <span>{attraction.remarks}</span>
            </article>
          </div>
        </section>

        <section className="product-section">
          <div className="product-section__header">
            <div>
              <div className="eyebrow">推荐提问</div>
              <h2>让数字人直接沿着当前景点讲下去。</h2>
            </div>
          </div>

          <div className="question-chip-row">
            {attraction.recommendedQuestions.map((question) => (
              <a
                key={question}
                href={buildGuideHref({
                  scenicSlug: attraction.scenicSlug,
                  scenicName: attraction.scenicName,
                  attractionId: attraction.attractionId,
                  attractionName: attraction.attractionName,
                  prompt: question,
                })}
                className="prompt-chip question-chip"
              >
                {question}
              </a>
            ))}
          </div>
        </section>

        <ProductFooter />
      </div>
    </div>
  );
}
