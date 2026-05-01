import React from "react";

export function MetricCard({ title, value, hint }) {
  return (
    <div className="card" style={{ padding: 20 }}>
      <div className="muted" style={{ fontSize: 14 }}>{title}</div>
      <div className="metric-value" style={{ marginTop: 10 }}>{value}</div>
      {hint ? <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>{hint}</div> : null}
    </div>
  );
}
