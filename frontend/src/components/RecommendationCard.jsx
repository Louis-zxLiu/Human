import React from "react";

export function RecommendationCard({ recommendation }) {
  if (!recommendation) return null;

  return (
    <div className="recommendation-card">
      <div className="recommendation-card__header">
        <div>
          <div className="recommendation-card__eyebrow">路线建议</div>
          <div className="recommendation-card__title">{recommendation.title}</div>
        </div>
        {recommendation.label ? <span className="recommendation-card__label">{recommendation.label}</span> : null}
      </div>
      <div className="recommendation-card__reason">{recommendation.reason}</div>
      <div className="recommendation-card__duration">
        预计游览时长：{recommendation.estimated_duration}
      </div>
      {recommendation.highlights ? (
        <div className="recommendation-card__insight">
          <strong>讲解重点</strong>
          <span>{recommendation.highlights}</span>
        </div>
      ) : null}
      {recommendation.analytics_hint ? (
        <div className="recommendation-card__insight recommendation-card__insight--data">
          <strong>游客行为依据</strong>
          <span>{recommendation.analytics_hint}</span>
        </div>
      ) : null}
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
