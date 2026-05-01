import React from "react";

const BAR_COLORS = [
  "linear-gradient(90deg, var(--tone-sky), #5ac8fa)",
  "linear-gradient(90deg, var(--tone-amber), #f59e0b)",
  "linear-gradient(90deg, var(--tone-coral), #f97316)",
  "linear-gradient(90deg, var(--tone-mint), #0f9d87)",
  "linear-gradient(90deg, var(--tone-indigo), #6366f1)",
  "linear-gradient(90deg, var(--tone-sand), #c67c4e)",
];

export function InsightBarList({
  items,
  emptyLabel = "暂无数据",
  valueFormatter = (value) => value,
}) {
  if (!items?.length) {
    return (
      <div className="empty-state empty-state--compact">
        <strong>{emptyLabel}</strong>
      </div>
    );
  }

  const maxValue = Math.max(...items.map((item) => Number(item.value || 0)), 1);

  return (
    <div className="bar-list">
      {items.map((item, index) => (
        <div className="bar-list__item" key={`${item.label}-${index}`}>
          <div className="bar-list__row">
            <span className="bar-list__label">{item.label}</span>
            <strong>{valueFormatter(item.value)}</strong>
          </div>
          <div className="bar-list__track">
            <div
              className="bar-list__fill"
              style={{
                width: `${Math.max((Number(item.value || 0) / maxValue) * 100, 8)}%`,
                background: BAR_COLORS[index % BAR_COLORS.length],
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
