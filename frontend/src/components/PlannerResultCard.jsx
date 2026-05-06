import React from "react";

import { buildGuideHref } from "../lib/routes";

export function PlannerResultCard({ plan }) {
  if (!plan) return null;
  const token = localStorage.getItem("auth_token");
  const guideLabel = token ? "开始导览" : "登录后开始导览";

  return (
    <section className="planner-result">
      <div className="planner-result__hero">
        <img src={plan.area.heroImage} alt={plan.area.name} />
        <div className="planner-result__hero-copy">
          <div className="eyebrow">{plan.area.name}</div>
          <h2>{plan.title}</h2>
          <p>{plan.reason}</p>
        </div>
      </div>

      <div className="planner-result__meta">
        <span>{plan.interestLabelDisplay}</span>
        <span>{plan.durationLabel}</span>
        <span>{plan.visitorTypeLabel}</span>
        <span>{plan.paceLabel}</span>
      </div>

      <div className="planner-result__summary">
        <div>
          <strong>预计时长</strong>
          <span>{plan.estimatedDuration}</span>
        </div>
        <div>
          <strong>讲解重点</strong>
          <span>{plan.highlights}</span>
        </div>
        <div>
          <strong>游客行为依据</strong>
          <span>{plan.analyticsHint || "当前行为数据没有额外补充时，将以结构化景点讲解为主。"}</span>
        </div>
      </div>

      {plan.planningNote ? (
        <div className="planner-result__note">
          <strong>规划说明</strong>
          <span>{plan.planningNote}</span>
        </div>
      ) : null}

      <div className="planner-result__steps">
        {plan.routeItems.map((item, index) => (
          <div key={item.attractionId || `${item.name}-${index}`} className="planner-result__step">
            <div className="planner-result__index">{index + 1}</div>
            <div>
              <strong>{item.name}</strong>
              <span>{item.summary}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="planner-result__actions">
        <a
          href={buildGuideHref({
            scenicSlug: plan.scenicSlug,
            scenicName: plan.scenicName,
            routeLabel: plan.interestLabelDisplay,
            routeTitle: plan.title,
            prompt: plan.guidePrompt,
          })}
          className="button-primary"
        >
          {guideLabel}
        </a>
      </div>
    </section>
  );
}
