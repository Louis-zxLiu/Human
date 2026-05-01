import React from "react";

function formatTime(value) {
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

export function HistoryRail({
  isOpen,
  archives,
  currentTitle,
  currentPreview,
  isCurrentSelected,
  selectedArchiveId,
  onToggle,
  onShowCurrent,
  onSelectArchive,
}) {
  return (
    <div className={`history-rail ${isOpen ? "is-open" : ""}`}>
      <button type="button" className="history-rail__toggle" onClick={onToggle}>
        <span className="history-rail__toggle-label">{isOpen ? "收起" : "历史"}</span>
        <span className="history-rail__toggle-count">{archives.length}</span>
      </button>

      <aside className="panel history-panel">
        <div className="panel-header panel-header--tight">
          <div>
            <div className="eyebrow">本地历史</div>
            <h2 className="panel-title">会话侧栏</h2>
          </div>
          <span className="meta-note">{archives.length} 条归档</span>
        </div>

        <button
          type="button"
          className={`history-item history-item--current ${isCurrentSelected ? "is-selected" : ""}`}
          onClick={onShowCurrent}
        >
          <div className="history-item__header">
            <strong>当前会话</strong>
            <span className="history-pill">进行中</span>
          </div>
          <div className="history-item__title">{currentTitle}</div>
          <div className="history-item__preview">
            {currentPreview || "等待第一条提问后，这轮对话会在这里显示摘要。"}
          </div>
        </button>

        <div className="history-list">
          {archives.length ? (
            archives.map((archive) => (
              <button
                type="button"
                key={archive.id}
                className={`history-item ${selectedArchiveId === archive.id ? "is-selected" : ""}`}
                onClick={() => onSelectArchive(archive.id)}
              >
                <div className="history-item__header">
                  <strong>{archive.title}</strong>
                  <span className="meta-note">{formatTime(archive.updatedAt)}</span>
                </div>
                <div className="history-item__preview">{archive.preview || "点击查看完整对话记录"}</div>
              </button>
            ))
          ) : (
            <div className="empty-state">
              <strong>还没有归档会话</strong>
              <span>开始第一轮提问后，旧会话会自动进入这里。</span>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
