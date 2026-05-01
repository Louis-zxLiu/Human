import React from "react";

export function MetricCard({ title, value, hint, accent = "sky" }) {
  return (
    <article className={`panel metric-card tone-${accent}`}>
      <span className="metric-card__label">{title}</span>
      <strong className="metric-card__value">{value}</strong>
      {hint ? <span className="metric-card__hint">{hint}</span> : null}
    </article>
  );
}
