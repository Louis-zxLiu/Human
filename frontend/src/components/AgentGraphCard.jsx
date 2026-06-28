import React, { useMemo, useRef, useEffect, useState } from "react";

// 节点 ID → 中文标签
const NODE_LABELS = {
  planner:           "意图解析",
  fast_answer:       "快速回答",
  tool_dispatch:     "工具调度",
  tool_execute:      "工具执行",
  agent_loop_decide: "循环决策",
  synthesize:        "综合生成",
  review:            "质量审核",
  repair_execute:    "修复执行",
  finalize:          "最终输出",
};

const ALL_NODES = Object.keys(NODE_LABELS);

function formatMs(ms) {
  if (!ms && ms !== 0) return "";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

// 根据状态映射 Mermaid 样式 class
function nodeClass(status) {
  if (status === "running") return "running";
  if (status === "done")    return "done";
  if (status === "skipped") return "skipped";
  return "pending";
}

// 节点标签：running 加 spinner unicode，done 加 ✓
function nodeLabel(id, status) {
  const base = NODE_LABELS[id];
  if (status === "running") return `⟳ ${base}`;
  if (status === "done")    return `✓ ${base}`;
  return base;
}

function buildMermaidSrc(statusMap) {
  const lines = [
    // init 指令：强制 base theme，彻底覆盖默认白色
    "%%{init: {'theme': 'base', 'themeVariables': {'background': '#0b1728', 'primaryColor': '#0d1b2e', 'primaryBorderColor': '#3a5070', 'primaryTextColor': '#94a3b8', 'lineColor': '#3a5070', 'edgeLabelBackground': '#0b1728', 'fontSize': '13px'}}}%%",
    "flowchart TD",
    // classDef 定义四种状态样式
    "  classDef pending fill:#0d1b2e,stroke:#3a5070,stroke-width:1.5px,color:#94a3b8",
    "  classDef running fill:#2d1f00,stroke:#f59e0b,stroke-width:2px,color:#fde68a",
    "  classDef done    fill:#042e1e,stroke:#34d399,stroke-width:2px,color:#a7f3d0",
    "  classDef skipped fill:#0d1b2e,stroke:#1e3050,stroke-width:1px,color:#334155",
    // 节点
    ...ALL_NODES.map(id => {
      const status = statusMap[id] || "pending";
      const label = nodeLabel(id, status);
      return `  ${id}("${label}"):::${nodeClass(status)}`;
    }),
    // 边
    "  planner --> fast_answer",
    "  planner --> tool_dispatch",
    "  fast_answer -.-> finalize",
    "  tool_dispatch --> tool_execute",
    "  tool_execute --> agent_loop_decide",
    "  agent_loop_decide -->|再次| tool_execute",
    "  agent_loop_decide --> synthesize",
    "  synthesize --> review",
    "  review --> finalize",
    "  review --> repair_execute",
    "  repair_execute -->|重试| synthesize",
  ];
  return lines.join("\n");
}

function buildIframeSrc(mermaidDef) {
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
  background: #0b1728;
  font-family: "PingFang SC","Microsoft YaHei",sans-serif;
  overflow: hidden;
}
#app {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 8px 4px;
}
svg {
  max-width: 100%;
  height: auto !important;
  font-family: "PingFang SC","Microsoft YaHei",sans-serif !important;
}
/* 强制覆盖 Mermaid 生成的白色背景 rect */
svg > rect:first-child,
.background { fill: #0b1728 !important; }
/* 边线颜色 */
.edgePath .path,
path.path { stroke: #3a5070 !important; stroke-width: 1.8px !important; fill: none !important; }
/* 箭头 */
marker path { fill: #3a5070 !important; stroke: none !important; }
/* 边标签 — 覆盖白底 */
.edgeLabel { background: transparent !important; }
.edgeLabel rect,
.edgeLabel foreignObject div {
  fill: #0b1728 !important;
  background: #0b1728 !important;
  color: #4a6a8a !important;
  font-size: 10px !important;
}
span.edgeLabel { color: #4a6a8a !important; background: #0b1728 !important; font-size: 10px !important; }
/* 节点字体 */
.nodeLabel, .label { font-size: 13px !important; }
</style>
</head>
<body>
<div id="app">
  <pre class="mermaid">${mermaidDef}</pre>
</div>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"><\/script>
<script>
mermaid.initialize({
  startOnLoad: true,
  theme: 'base',
  themeVariables: {
    background: '#0b1728',
    mainBkg: '#0d1b2e',
    primaryColor: '#0d1b2e',
    primaryBorderColor: '#3a5070',
    primaryTextColor: '#94a3b8',
    nodeBorder: '#3a5070',
    clusterBkg: '#0b1728',
    titleColor: '#94a3b8',
    edgeLabelBackground: '#0b1728',
    lineColor: '#3a5070',
    fontSize: '13px',
    fontFamily: '"PingFang SC","Microsoft YaHei",sans-serif',
  },
  flowchart: {
    curve: 'basis',
    padding: 16,
    htmlLabels: true,
    nodeSpacing: 36,
    rankSpacing: 44,
  },
});
mermaid.run();
// 渲染完后把 SVG 实际高度通知父页面（用 viewBox，不依赖可见性）
const observer = new MutationObserver(() => {
  const svg = document.querySelector('#app svg');
  if (svg) {
    observer.disconnect();
    // 优先用 viewBox，fallback 用 height 属性
    const vb = svg.viewBox && svg.viewBox.baseVal;
    const h = (vb && vb.height > 0)
      ? vb.height
      : parseFloat(svg.getAttribute('height') || '0');
    if (h > 50) {
      window.parent.postMessage({ type: 'mermaid-height', height: Math.ceil(h) + 32 }, '*');
    }
  }
});
observer.observe(document.getElementById('app'), { childList: true, subtree: true });
<\/script>
</body>
</html>`;
}

export function AgentGraphCard({ agentNodes = [], isExpanded, onToggle, elapsedMs }) {
  const statusMap = useMemo(() => {
    const m = {};
    for (const n of agentNodes) m[n.node] = n.status;
    return m;
  }, [agentNodes]);

  const doneCount   = agentNodes.filter(n => n.status === "done").length;
  const runningNode = agentNodes.find(n => n.status === "running");
  const lastDone    = agentNodes.slice().reverse().find(n => n.status === "done");
  const activeNode  = runningNode || lastDone;

  const iframeSrc = useMemo(
    () => buildIframeSrc(buildMermaidSrc(statusMap)),
    [statusMap]
  );

  const [iframeHeight, setIframeHeight] = useState(700);
  const iframeRef = useRef(null);

  useEffect(() => {
    function onMsg(e) {
      if (e.data && e.data.type === "mermaid-height") {
        setIframeHeight(e.data.height);
      }
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);

  // reset height when diagram changes
  useEffect(() => { setIframeHeight(700); }, [iframeSrc]);

  return (
    <>
      {isExpanded && <div className="vis-drawer-backdrop" onClick={onToggle} />}

      <div className={`vis-agent-drawer ${isExpanded ? "is-open" : ""}`}>
        {/* Tab */}
        <button className="vis-agent-drawer__tab" onClick={onToggle}
          aria-label={isExpanded ? "收起执行图" : "展开执行图"}>
          <i className="fas fa-diagram-project vis-agent-drawer__tab-icon" />
          <span className="vis-agent-drawer__tab-text">多智能体</span>
          {doneCount > 0 && <span className="vis-agent-drawer__tab-badge">{doneCount}</span>}
          {runningNode && <span className="vis-agent-drawer__tab-dot" />}
        </button>

        {/* Panel */}
        <div className="vis-agent-drawer__panel">
          {/* Header */}
          <div className="vis-agent-drawer__header">
            <span className="vis-agent-drawer__header-title">
              <i className="fas fa-diagram-project" style={{marginRight:6,color:"#38bdf8"}} />
              执行图
            </span>
            <div className="vis-agent-drawer__header-meta">
              {doneCount > 0 && (
                <span className="vis-agent-drawer__badge">{doneCount}/{ALL_NODES.length}</span>
              )}
              {elapsedMs > 0 && (
                <span className="vis-agent-drawer__elapsed">{formatMs(elapsedMs)}</span>
              )}
            </div>
          </div>

          {/* Active node bar */}
          {activeNode && (
            <div className="vis-agent-drawer__active">
              <span className={`vis-agent-drawer__active-dot vis-agent-drawer__active-dot--${runningNode ? "running" : "done"}`} />
              {runningNode ? `正在执行：${activeNode.label}` : `最近完成：${NODE_LABELS[activeNode.node] || activeNode.label}`}
            </div>
          )}

          {/* Mermaid iframe */}
          <div className="vis-dag-iframe-wrap">
            <iframe
              ref={iframeRef}
              key={iframeSrc}
              srcDoc={iframeSrc}
              className="vis-dag-iframe"
              style={{ height: iframeHeight }}
              sandbox="allow-scripts"
              title="执行图"
            />
          </div>
        </div>
      </div>
    </>
  );
}
