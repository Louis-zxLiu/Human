import React from "react";

export function StatusBadge({ state, children }) {
  const className =
    state === "success"
      ? "pill status-success"
      : state === "warning"
        ? "pill status-warning"
        : state === "danger"
          ? "pill status-danger"
          : "pill status-info";
  return <span className={className}>{children}</span>;
}
