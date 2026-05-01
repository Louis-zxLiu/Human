import React from "react";

export function RecommendationCard({ recommendation }) {
  if (!recommendation) return null;

  return (
    <div className="recommendation-card">
      <div className="recommendation-card__eyebrow">路线建议</div>
      <div className="recommendation-card__title">{recommendation.title}</div>
      <div className="recommendation-card__reason">{recommendation.reason}</div>
      <div className="recommendation-card__duration">
        预计游览时长：{recommendation.estimated_duration}
      </div>
      <div className="recommendation-card__items">
        {recommendation.route_items?.map((item, index) => (
          <div key={`${item.name}-${index}`} className="recommendation-card__item">
            <div className="recommendation-card__item-title">{index + 1}. {item.name}</div>
            <div className="recommendation-card__item-summary">{item.summary}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
