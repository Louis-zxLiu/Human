import React from "react";

const COLORS = [
  "var(--tone-sky)",
  "var(--tone-amber)",
  "var(--tone-coral)",
  "var(--tone-mint)",
  "var(--tone-indigo)",
  "var(--tone-sand)",
];

function normalizeItems(data) {
  if (Array.isArray(data)) {
    return data
      .filter((item) => Number(item?.value) > 0)
      .map((item) => ({ label: item.label, value: Number(item.value) }));
  }

  return Object.entries(data || {})
    .filter(([, value]) => Number(value) > 0)
    .map(([label, value]) => ({ label, value: Number(value) }));
}

export function DonutChart({ data, totalLabel = "总量", emptyLabel = "暂无数据" }) {
  const items = normalizeItems(data);
  const total = items.reduce((sum, item) => sum + Number(item.value || 0), 0);

  if (!items.length || total <= 0) {
    return (
      <div className="donut-chart-shell">
        <div className="donut-chart donut-chart--empty">
          <div className="donut-chart__inner">
            <strong>0</strong>
            <span>{emptyLabel}</span>
          </div>
        </div>
      </div>
    );
  }

  let cursor = 0;
  const background = `conic-gradient(${items.map((item, index) => {
    const size = (Number(item.value || 0) / total) * 360;
    const segment = `${COLORS[index % COLORS.length]} ${cursor}deg ${cursor + size}deg`;
    cursor += size;
    return segment;
  }).join(", ")})`;

  return (
    <div className="donut-chart-shell">
      <div className="donut-chart" style={{ background }}>
        <div className="donut-chart__inner">
          <strong>{total}</strong>
          <span>{totalLabel}</span>
        </div>
      </div>
      <div className="chart-legend">
        {items.map((item, index) => (
          <div className="chart-legend__item" key={`${item.label}-${index}`}>
            <span className="chart-legend__swatch" style={{ background: COLORS[index % COLORS.length] }} />
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}
