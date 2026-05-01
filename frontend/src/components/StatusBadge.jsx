import React from "react";

export function StatusBadge({ state, children }) {
  const className =
    state === "success"
      ? "status-badge status-success"
      : state === "warning"
        ? "status-badge status-warning"
        : state === "danger"
          ? "status-badge status-danger"
          : state === "neutral"
            ? "status-badge status-neutral"
            : "status-badge status-info";

  return <span className={className}>{children}</span>;
}
