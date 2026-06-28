import React, { useMemo } from "react";

const NODE_DEFS = [
  { id: "planner",           label: "意图解析",  icon: "fa-brain" },
  { id: "fast_answer",       label: "快速回答",  icon: "fa-bolt" },
  { id: "tool_dispatch",     label: "工具调度",  icon: "fa-sitemap" },
  { id: "tool_execute",      label: "工具执行",  icon: "fa-wrench" },
  { id: "agent_loop_decide", label: "循环决策",  icon: "fa-rotate" },
  { id: "synthesize",        label: "综合生成",  icon: "fa-layer-group" },
  { id: "review",            label: "质量审核",  icon: "fa-shield-halved" },
  { id: "repair_execute",    label: "修复执行",  icon: "fa-screwdriver-wrench" },
  { id: "finalize",          label: "最终输出",  icon: "fa-circle-check" },
];

function formatMs(ms) {
  if (!ms && ms !== 0) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function AgentGraphCard({ agentNodes = [], isExpanded, onToggle, elapsedMs }) {
  const statusMap = useMemo(() => {
    const map = {};
    for (const n of agentNodes) map[n.node] = n.status;
    return map;
  }, [agentNodes]);

  const activeNode = agentNodes.find((n) => n.status === "running")
    || agentNodes.slice().reverse().find((n) => n.status === "done");

  const doneCount = agentNodes.filter((n) => n.status === "done").length;
  const total = NODE_DEFS.length;

  return (
    <div className={`vis-agent-sidebar ${isExpanded ? "is-expanded" : ""}`}>
      {/* Header toggle */}
      <button
        className="vis-agent-sidebar__header"
        onClick={onToggle}
        aria-expanded={isExpanded}
        aria-label={isExpanded ? "收起执行图" : "展开执行图"}
      >
        <span className="vis-agent-sidebar__header-left">
          <i className="fas fa-diagram-project vis-agent-sidebar__header-icon" />
          <span className="vis-agent-sidebar__header-title">多智能体</span>
        </span>
        <span className="vis-agent-sidebar__header-right">
          {doneCount > 0 && (
            <span className="vis-agent-sidebar__progress">
              {doneCount}/{total}
            </span>
          )}
          {elapsedMs > 0 && (
            <span className="vis-agent-sidebar__elapsed">{formatMs(elapsedMs)}</span>
          )}
          <i className={`fas ${isExpanded ? "fa-chevron-up" : "fa-chevron-down"} vis-agent-sidebar__chevron`} />
        </span>
      </button>

      {/* Collapsed hint bar */}
      {!isExpanded && activeNode && (
        <div className="vis-agent-sidebar__hint">
          <span className="vis-agent-sidebar__hint-dot" />
          {activeNode.label || NODE_DEFS.find(n => n.id === activeNode.node)?.label || activeNode.node}
        </div>
      )}

      {/* Expanded timeline */}
      {isExpanded && (
        <div className="vis-agent-sidebar__timeline">
          {NODE_DEFS.map((def, idx) => {
            const status = statusMap[def.id] || "pending";
            const isLast = idx === NODE_DEFS.length - 1;
            return (
              <div key={def.id} className={`vis-agent-node vis-agent-node--${status}`}>
                <div className="vis-agent-node__track">
                  <div className="vis-agent-node__dot">
                    {status === "running" ? (
                      <span className="vis-agent-node__spinner" />
                    ) : status === "done" ? (
                      <i className="fas fa-check" />
                    ) : (
                      <i className={`fas ${def.icon}`} />
                    )}
                  </div>
                  {!isLast && <div className="vis-agent-node__line" />}
                </div>
                <div className="vis-agent-node__body">
                  <span className="vis-agent-node__label">{def.label}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
