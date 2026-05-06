import React, { useEffect, useState } from "react";

import { ProductFooter } from "../components/ProductFooter";
import { ProductHeader } from "../components/ProductHeader";
import { ScenicCard } from "../components/ScenicCard";
import { fetchScenicAreas } from "../lib/api";
import { buildGuideHref, buildPlannerHref } from "../lib/routes";

const CAPABILITIES = [
  "多模态数字人问答",
  "本地景区知识库",
  "双园区路线规划",
  "弱 GPS 多轮导览",
  "游客洞察驾驶舱",
  "统一评测支撑",
];

export function HomeApp() {
  const [areas, setAreas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const token = localStorage.getItem("auth_token");
  const guideLabel = token ? "开始导览" : "登录后开始导览";

  useEffect(() => {
    let alive = true;
    fetchScenicAreas()
      .then((result) => {
        if (!alive) return;
        setAreas(result);
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
  }, []);

  const primary = areas[0];

  return (
    <div className="product-page">
      <div className="page-container">
        <ProductHeader active="home" />

        <section className="landing-hero">
          <div className="landing-hero__copy">
            <div className="eyebrow">双园区智慧导览</div>
            <h1>把数字人导览、路线规划和运营后台整理成一套完整的景区服务系统。</h1>
            <p>
              游客可以先浏览园区、再规划路线、再进入数字人导览；
              管理方则通过后台持续管理知识库、观察游客洞察并优化服务体验。
            </p>

            <div className="landing-hero__actions">
              <a href={buildPlannerHref()} className="button-primary">先规划一条路线</a>
              <a href={buildGuideHref()} className="button-secondary">{guideLabel}</a>
            </div>

            <div className="capability-strip">
              {CAPABILITIES.map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
          </div>

          <div className="landing-hero__media">
            {primary ? (
              <div className="landing-hero__image landing-hero__image--primary">
                <img src={primary.heroImage} alt={primary.name} />
                <div>
                  <strong>{primary.name}</strong>
                  <span>{primary.tagline}</span>
                </div>
              </div>
            ) : null}
          </div>
        </section>

        <section className="product-section">
          <div className="product-section__header">
            <div>
              <div className="eyebrow">双园区入口</div>
              <h2>先选场景，再进入对应的导览节奏。</h2>
            </div>
            <p>灵山胜境承担佛教文化与建筑艺术主线，拈花湾承担慢游、夜游和禅意休闲体验。</p>
          </div>

          {error ? <div className="feedback feedback-danger">{error}</div> : null}
          {loading ? <div className="loading-row">正在加载双园区资料...</div> : null}
          {!loading ? (
            <div className="scenic-card-grid">
              {areas.map((scenic) => (
                <ScenicCard key={scenic.slug} scenic={scenic} />
              ))}
            </div>
          ) : null}
        </section>

        <section className="product-section product-section--narrative">
          <div className="product-section__header">
            <div>
              <div className="eyebrow">服务闭环</div>
              <h2>从游客浏览到数字人服务，再到后台运营，整条链路都能自然衔接。</h2>
            </div>
          </div>

          <div className="narrative-grid">
            <div className="narrative-card">
              <strong>1. 浏览园区</strong>
              <span>先看真实景区内容，而不是直接掉进聊天框。</span>
            </div>
            <div className="narrative-card">
              <strong>2. 规划路线</strong>
              <span>按兴趣、人群、时长与节奏生成结构化游线。</span>
            </div>
            <div className="narrative-card">
              <strong>3. 数字人带路</strong>
              <span>带着当前园区和路线语境进入多模态导览。</span>
            </div>
            <div className="narrative-card">
              <strong>4. 后台复盘</strong>
              <span>用统一评测、知识库状态与游客洞察承接管理价值。</span>
            </div>
          </div>
        </section>

        <ProductFooter />
      </div>
    </div>
  );
}
