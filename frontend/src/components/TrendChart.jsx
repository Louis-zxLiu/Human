import React from "react";

const SERIES = [
  { key: "positive", label: "正向", color: "var(--tone-mint)" },
  { key: "neutral", label: "中性", color: "var(--tone-amber)" },
  { key: "negative", label: "负向", color: "var(--tone-coral)" },
];

function buildPolylinePoints(data, key, width, height, padding, maxValue) {
  return data.map((item, index) => {
    const step = data.length === 1 ? 0 : index / (data.length - 1);
    const x = padding + step * (width - padding * 2);
    const y = height - padding - ((Number(item[key] || 0) / maxValue) * (height - padding * 2));
    return `${x},${y}`;
  }).join(" ");
}

function buildMarkers(data, key, width, height, padding, maxValue) {
  return data.map((item, index) => {
    const step = data.length === 1 ? 0 : index / (data.length - 1);
    return {
      x: padding + step * (width - padding * 2),
      y: height - padding - ((Number(item[key] || 0) / maxValue) * (height - padding * 2)),
    };
  });
}

export function TrendChart({ data }) {
  if (!data?.length) {
    return (
      <div className="empty-state empty-state--compact">
        <strong>最近 7 天暂无趋势数据</strong>
      </div>
    );
  }

  const width = 560;
  const height = 220;
  const padding = 26;
  const maxValue = Math.max(
    1,
    ...data.flatMap((item) => SERIES.map((series) => Number(item[series.key] || 0))),
  );

  return (
    <div className="trend-chart">
      <div className="trend-chart__legend">
        {SERIES.map((series) => (
          <div className="chart-legend__item" key={series.key}>
            <span className="chart-legend__swatch" style={{ background: series.color }} />
            <span>{series.label}</span>
          </div>
        ))}
      </div>

      <svg className="trend-chart__svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="满意度趋势">
        {[0.25, 0.5, 0.75].map((marker) => (
          <line
            key={marker}
            x1={padding}
            x2={width - padding}
            y1={height - padding - marker * (height - padding * 2)}
            y2={height - padding - marker * (height - padding * 2)}
            className="trend-chart__grid"
          />
        ))}

        {SERIES.map((series) => (
          <g key={series.key}>
            <polyline
              fill="none"
              stroke={series.color}
              strokeWidth="4"
              strokeLinejoin="round"
              strokeLinecap="round"
              points={buildPolylinePoints(data, series.key, width, height, padding, maxValue)}
            />
            {buildMarkers(data, series.key, width, height, padding, maxValue).map((point, index) => (
              <circle key={`${series.key}-${index}`} cx={point.x} cy={point.y} r="4.5" fill={series.color} />
            ))}
          </g>
        ))}

        {data.map((item, index) => {
          const step = data.length === 1 ? 0 : index / (data.length - 1);
          const x = padding + step * (width - padding * 2);
          return (
            <text key={item.date} className="trend-chart__label" x={x} y={height - 4} textAnchor="middle">
              {String(item.date || "").slice(5)}
            </text>
          );
        })}
      </svg>
    </div>
  );
}
