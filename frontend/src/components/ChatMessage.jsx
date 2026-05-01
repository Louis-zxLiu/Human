import React from "react";

import { RecommendationCard } from "./RecommendationCard";
import { StatusBadge } from "./StatusBadge";


function gpsStatusText(meta) {
  if (meta.gps_state === "awaiting_landmarks") return "弱 GPS：等待用户补充地标";
  if (meta.gps_state === "ambiguous") return `弱 GPS：候选位置 ${meta.gps_candidates?.join(" / ") || ""}`;
  if (meta.gps_state === "resolved" || meta.gps_state === "resolved_recommendation") return `弱 GPS：已推测位置 ${meta.matched_attraction || ""}`;
  return null;
}


export function ChatMessage({ message }) {
  const alignRight = message.role === "user";
  const badgeText = message.meta ? gpsStatusText(message.meta) : null;
  return (
    <div style={{ display: "flex", justifyContent: alignRight ? "flex-end" : "flex-start" }}>
      <div
        className="card"
        style={{
          maxWidth: "86%",
          padding: 16,
          background: alignRight ? "#e0f2fe" : "#ffffff",
        }}
      >
        <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
          {alignRight ? "游客" : "数字人导游"}
        </div>
        {badgeText ? <StatusBadge state={message.meta.gps_state === "resolved" ? "success" : "warning"}>{badgeText}</StatusBadge> : null}
        {message.meta?.recommendation ? (
          <div style={{ marginTop: 12 }}>
            <RecommendationCard recommendation={message.meta.recommendation} />
          </div>
        ) : null}
        <div style={{ marginTop: 12, whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{message.content}</div>
      </div>
    </div>
  );
}
