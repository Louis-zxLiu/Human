import React from "react";

export function RecommendationCard({ recommendation }) {
  if (!recommendation) return null;
  return (
    <div className="card" style={{ padding: 16, borderColor: "#fde68a", background: "#fffbeb" }}>
      <div style={{ fontWeight: 700, marginBottom: 8 }}>{recommendation.title}</div>
      <div style={{ fontSize: 14, marginBottom: 8 }}>{recommendation.reason}</div>
      <div style={{ fontSize: 14, marginBottom: 8 }}>预计游览时长：{recommendation.estimated_duration}</div>
      <div className="grid">
        {recommendation.route_items?.map((item, index) => (
          <div key={`${item.name}-${index}`} className="card" style={{ padding: 12 }}>
            <div style={{ fontWeight: 600 }}>{index + 1}. {item.name}</div>
            <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>{item.summary}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
