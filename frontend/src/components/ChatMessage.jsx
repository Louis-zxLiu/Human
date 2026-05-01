import React from "react";

import { RecommendationCard } from "./RecommendationCard";
import { StatusBadge } from "./StatusBadge";

function gpsStatusText(meta) {
  if (meta?.gps_state === "awaiting_landmarks") return "弱 GPS：等待补充地标描述";
  if (meta?.gps_state === "ambiguous") return `弱 GPS：候选位置 ${meta.gps_candidates?.join(" / ") || ""}`;
  if (meta?.gps_state === "resolved" || meta?.gps_state === "resolved_recommendation") {
    return `弱 GPS：已匹配 ${meta.matched_attraction || "当前位置"}`;
  }
  return null;
}

export function ChatMessage({ message }) {
  const isUser = message.role === "user";
  const badgeText = message.meta ? gpsStatusText(message.meta) : null;
  const badgeState = message.meta?.gps_state === "resolved" || message.meta?.gps_state === "resolved_recommendation"
    ? "success"
    : "warning";

  return (
    <div className={`chat-message ${isUser ? "is-user" : ""}`}>
      <div className={`message-bubble ${isUser ? "message-bubble--user" : "message-bubble--assistant"}`}>
        <div className="message-role">{isUser ? "游客" : "数字人导游"}</div>
        {badgeText ? <StatusBadge state={badgeState}>{badgeText}</StatusBadge> : null}
        {message.meta?.recommendation ? (
          <div className="message-recommendation">
            <RecommendationCard recommendation={message.meta.recommendation} />
          </div>
        ) : null}
        <div className="message-content">{message.content}</div>
      </div>
    </div>
  );
}
