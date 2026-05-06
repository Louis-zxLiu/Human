import React from "react";

import { buildAttractionHref, buildGuideHref } from "../lib/routes";

export function AttractionSpotCard({ attraction }) {
  const token = localStorage.getItem("auth_token");
  const guideLabel = token ? "开始导览" : "登录后开始导览";

  return (
    <article className="spot-card">
      <a href={buildAttractionHref(attraction.scenicSlug, attraction.attractionId)} className="spot-card__media">
        <img src={attraction.image} alt={attraction.attractionName} />
      </a>
      <div className="spot-card__body">
        <div className="spot-card__eyebrow">{attraction.scenicName}</div>
        <h3>{attraction.attractionName}</h3>
        <p>{attraction.highlights || attraction.description}</p>
        <div className="spot-card__footer">
          <a href={buildAttractionHref(attraction.scenicSlug, attraction.attractionId)} className="text-link">查看详情</a>
          <a
            href={buildGuideHref({
              scenicSlug: attraction.scenicSlug,
              scenicName: attraction.scenicName,
              attractionId: attraction.attractionId,
              attractionName: attraction.attractionName,
            })}
            className="text-link"
          >
            {guideLabel}
          </a>
        </div>
      </div>
    </article>
  );
}
