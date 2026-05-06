import React from "react";

import { buildGuideHref, buildPlannerHref, buildScenicHref } from "../lib/routes";

export function ScenicCard({ scenic }) {
  const token = localStorage.getItem("auth_token");
  const guideLabel = token ? "开始导览" : "登录后开始导览";

  return (
    <article className="scenic-card">
      <a href={buildScenicHref(scenic.slug)} className="scenic-card__media">
        <img src={scenic.heroImage} alt={scenic.name} />
      </a>
      <div className="scenic-card__body">
        <div className="scenic-card__eyebrow">{scenic.shortName}</div>
        <h3>{scenic.name}</h3>
        <p>{scenic.tagline}</p>
        <div className="scenic-card__meta">
          <span>{scenic.attractionCount} 个结构化景点</span>
          <span>{scenic.featuredAttractions?.length || 0} 个精选节点</span>
        </div>
        <div className="scenic-card__actions">
          <a href={buildScenicHref(scenic.slug)} className="button-secondary compact-link">查看园区</a>
          <a href={buildPlannerHref(scenic.slug)} className="button-secondary compact-link">规划路线</a>
          <a
            href={buildGuideHref({ scenicSlug: scenic.slug, scenicName: scenic.name })}
            className="button-primary compact-link"
          >
            {guideLabel}
          </a>
        </div>
      </div>
    </article>
  );
}
