import React, { useRef, useEffect, useState, useCallback, useMemo, useId } from "react";

const NODE_LABELS = {
  planner: "意图解析",
  fast_answer: "快速回答",
  tool_dispatch: "工具调度",
  tool_execute: "工具执行",
  agent_loop_decide: "循环判断",
  synthesize: "综合生成",
  review: "质量审核",
  repair_execute: "修复执行",
  finalize: "最终输出",
};

const ALL_NODES = [
  "planner",
  "fast_answer",
  "tool_dispatch",
  "tool_execute",
  "agent_loop_decide",
  "synthesize",
  "review",
  "repair_execute",
  "finalize",
];

// [row, col] 1-indexed — mapped to CSS grid-row / grid-column
const NODE_GRID = {
  planner:           [1, 1],
  fast_answer:       [2, 1],
  tool_dispatch:     [2, 2],
  tool_execute:      [3, 2],
  agent_loop_decide: [4, 2],
  synthesize:        [5, 1],
  review:            [6, 1],
  finalize:          [7, 1],
  repair_execute:    [7, 2],
};

// Edges: [source, target, isDashed]
const EDGES = [
  ["planner",           "fast_answer",       false],
  ["planner",           "tool_dispatch",     false],
  ["fast_answer",       "finalize",          false],
  ["tool_dispatch",     "tool_execute",      false],
  ["tool_execute",      "agent_loop_decide", false],
  ["agent_loop_decide", "tool_execute",      true],  // loop — dashed
  ["agent_loop_decide", "synthesize",        false],
  ["synthesize",        "review",            false],
  ["review",            "finalize",          false],
  ["review",            "repair_execute",    false],
  ["repair_execute",    "synthesize",        true],  // loop — dashed
];

function statusColor(status) {
  switch (status) {
    case "running": return "#f59e0b";
    case "done":    return "#34d399";
    case "skipped": return "#4b5563";
    default:        return "#334155"; // pending
  }
}

function formatMs(ms) {
  if (!ms && ms !== 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function AgentGraphCard({ agentNodes = [], isExpanded, onToggle, elapsedMs }) {
  const nodeRefs = useRef({});
  const dagRef = useRef(null);
  const [lines, setLines] = useState([]);
  const uid = useId(); // stable per-instance prefix for SVG marker IDs

  // Build a stable lookup: node id -> status (memoized to avoid stale closures)
  const statusMap = useMemo(() => {
    const map = {};
    for (const n of agentNodes) {
      map[n.node] = n.status;
    }
    for (const id of ALL_NODES) {
      if (!map[id]) map[id] = "pending";
    }
    return map;
  }, [agentNodes]);

  const activeNode =
    agentNodes.find((n) => n.status === "running") ||
    agentNodes.slice().reverse().find((n) => n.status === "done");

  const computeLines = useCallback(() => {
    if (!dagRef.current) return;
    const dagRect = dagRef.current.getBoundingClientRect();
    const newLines = [];

    for (const [src, tgt, dashed] of EDGES) {
      const srcEl = nodeRefs.current[src];
      const tgtEl = nodeRefs.current[tgt];
      if (!srcEl || !tgtEl) continue;

      const srcRect = srcEl.getBoundingClientRect();
      const tgtRect = tgtEl.getBoundingClientRect();

      const srcCx = srcRect.left - dagRect.left + srcRect.width / 2;
      const tgtCx = tgtRect.left - dagRect.left + tgtRect.width / 2;
      const tgtCy = tgtRect.top  - dagRect.top  + tgtRect.height / 2;

      const srcGridRow = NODE_GRID[src][0];
      const tgtGridRow = NODE_GRID[tgt][0];
      const isLoop = tgtGridRow <= srcGridRow;

      let path;

      if (isLoop) {
        // Exit from right side of source, re-enter from right side of target
        const x1 = srcRect.right - dagRect.left;
        const y1 = srcRect.top - dagRect.top + srcRect.height / 2;
        const x2 = tgtRect.right - dagRect.left;
        const y2 = tgtCy;
        const midX = Math.max(x1, x2) + 28;
        path = `M ${x1} ${y1} C ${midX} ${y1} ${midX} ${y2} ${x2} ${y2}`;
      } else {
        // Normal downward: bottom of source → top of target
        const x1 = srcCx;
        const y1 = srcRect.bottom - dagRect.top;
        const x2 = tgtCx;
        const y2 = tgtRect.top - dagRect.top;
        const midY = (y1 + y2) / 2;
        path = `M ${x1} ${y1} C ${x1} ${midY} ${x2} ${midY} ${x2} ${y2}`;
      }

      newLines.push({
        key: `${src}-${tgt}`,
        path,
        dashed,
        status: statusMap[src] || "pending",
      });
    }
    setLines(newLines);
  }, [statusMap]);

  useEffect(() => {
    if (!isExpanded) return;
    const id = requestAnimationFrame(computeLines);
    return () => cancelAnimationFrame(id);
  }, [isExpanded, agentNodes, computeLines]);

  useEffect(() => {
    if (!isExpanded) return;
    let timer;
    const onResize = () => {
      clearTimeout(timer);
      timer = setTimeout(computeLines, 100);
    };
    window.addEventListener("resize", onResize);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("resize", onResize);
    };
  }, [isExpanded, computeLines]);

  return (
    <div className="vis-agent-graph-card">
      {/* Toggle row — always visible */}
      <button
        className="vis-agent-graph-card__toggle"
        onClick={onToggle}
        aria-expanded={isExpanded}
        aria-label={isExpanded ? "收起执行图" : "展开执行图"}
      >
        <span className="vis-agent-graph-card__toggle-label">
          <span className="vis-agent-graph-card__toggle-arrow">{isExpanded ? "▾" : "▸"}</span>
          多智能体执行图
        </span>

        {!isExpanded && activeNode && (
          <span className="vis-agent-graph-card__active-hint">
            {NODE_LABELS[activeNode.node] || activeNode.node}
          </span>
        )}

        <span className="vis-agent-graph-card__elapsed">{formatMs(elapsedMs)}</span>
      </button>

      {/* Expanded body */}
      {isExpanded && (
        <div className="vis-agent-graph-card__body">
          <div className="vis-agent-graph-card__dag" ref={dagRef}>
            {ALL_NODES.map((id) => {
              const [row, col] = NODE_GRID[id];
              const status = statusMap[id];
              return (
                <div
                  key={id}
                  ref={(el) => { nodeRefs.current[id] = el; }}
                  className={`vis-agent-node vis-agent-node--${status}`}
                  style={{ gridRow: row, gridColumn: col }}
                >
                  {NODE_LABELS[id]}
                </div>
              );
            })}

            <svg className="vis-agent-graph-card__svg" aria-hidden="true">
              <defs>
                {["pending", "running", "done", "skipped"].map((s) => (
                  <marker
                    key={s}
                    id={`${uid}-arrow-${s}`}
                    markerWidth="6"
                    markerHeight="6"
                    refX="5"
                    refY="3"
                    orient="auto"
                  >
                    <path d="M0,0 L6,3 L0,6 Z" fill={statusColor(s)} />
                  </marker>
                ))}
              </defs>

              {lines.map(({ key, path, dashed, status }) => (
                <path
                  key={key}
                  d={path}
                  fill="none"
                  stroke={statusColor(status)}
                  strokeWidth="1.5"
                  strokeDasharray={dashed ? "5 4" : undefined}
                  markerEnd={`url(#${uid}-arrow-${status})`}
                  className="vis-agent-graph-card__edge"
                />
              ))}
            </svg>
          </div>

          {/* Footer status bar */}
          <div className="vis-agent-graph-card__footer">
            <span>
              当前：
              <strong>
                {activeNode ? NODE_LABELS[activeNode.node] || activeNode.node : "—"}
              </strong>
            </span>
            <span className="vis-agent-graph-card__footer-sep">|</span>
            <span>
              已耗时：<strong>{formatMs(elapsedMs)}</strong>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
