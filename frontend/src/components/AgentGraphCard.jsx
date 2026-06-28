import React from "react";

const STATUS_ICONS = {
  running: "fa-spinner fa-spin",
  done: "fa-check-circle",
  error: "fa-times-circle",
  pending: "fa-circle",
};

const STATUS_LABELS = {
  running: "执行中",
  done: "完成",
  error: "失败",
  pending: "等待",
};

/**
 * AgentGraphCard — displays the multi-agent execution graph in real time.
 *
 * Props:
 *   agentNodes    {Array}    list of { node, label, status } objects
 *   isExpanded    {boolean}  whether the detail panel is open
 *   onToggle      {Function} called when the user clicks the toggle button
 *   elapsedMs     {number}   milliseconds elapsed since the graph started
 */
export function AgentGraphCard({ agentNodes = [], isExpanded = false, onToggle, elapsedMs = 0 }) {
  const hasNodes = agentNodes.length > 0;
  const elapsedSec = (elapsedMs / 1000).toFixed(1);

  const runningCount = agentNodes.filter((n) => n.status === "running").length;
  const doneCount = agentNodes.filter((n) => n.status === "done").length;
  const errorCount = agentNodes.filter((n) => n.status === "error").length;

  if (!hasNodes) return null;

  return (
    <div className="agent-graph-card">
      {/* Header row */}
      <div className="agent-graph-card__header">
        <div className="agent-graph-card__header-left">
          <i className="fas fa-project-diagram agent-graph-card__icon" />
          <span className="agent-graph-card__title">智能体执行图</span>
          <span className="agent-graph-card__stats">
            {doneCount}/{agentNodes.length} 完成
            {errorCount > 0 ? `  ·  ${errorCount} 失败` : ""}
            {runningCount > 0 ? `  ·  ${runningCount} 运行中` : ""}
          </span>
        </div>
        <div className="agent-graph-card__header-right">
          <span className="agent-graph-card__elapsed">{elapsedSec}s</span>
          <button
            type="button"
            className="agent-graph-card__toggle"
            onClick={onToggle}
            aria-label={isExpanded ? "收起智能体执行图" : "展开智能体执行图"}
          >
            <i className={`fas ${isExpanded ? "fa-chevron-up" : "fa-chevron-down"}`} />
          </button>
        </div>
      </div>

      {/* Compact pipeline row (always visible) */}
      <div className="agent-graph-card__pipeline">
        {agentNodes.map((node, index) => (
          <React.Fragment key={node.node}>
            <div
              className={`agent-graph-card__node agent-graph-card__node--${node.status || "pending"}`}
              title={`${node.label}: ${STATUS_LABELS[node.status] || node.status}`}
            >
              <i className={`fas ${STATUS_ICONS[node.status] || STATUS_ICONS.pending}`} />
              <span className="agent-graph-card__node-label">{node.label}</span>
            </div>
            {index < agentNodes.length - 1 && (
              <span className="agent-graph-card__arrow">›</span>
            )}
          </React.Fragment>
        ))}
      </div>

      {/* Expanded detail list */}
      {isExpanded && (
        <div className="agent-graph-card__detail">
          {agentNodes.map((node) => (
            <div
              key={node.node}
              className={`agent-graph-card__detail-row agent-graph-card__detail-row--${node.status || "pending"}`}
            >
              <i className={`fas ${STATUS_ICONS[node.status] || STATUS_ICONS.pending}`} />
              <span className="agent-graph-card__detail-label">{node.label}</span>
              <span className="agent-graph-card__detail-status">
                {STATUS_LABELS[node.status] || node.status}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
