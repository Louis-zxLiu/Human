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

function sourceBadges(meta) {
  if (!meta) return [];

  const badges = [];
  if (meta.intent === "FACT") {
    badges.push({ text: "DOCX 景区知识库", state: "info" });
  }
  if (meta.intent === "ANALYTICS") {
    badges.push({ text: "游客行为数据", state: "success" });
  }
  if (meta.intent === "RECOMMEND") {
    badges.push({ text: "路线融合推荐", state: "warning" });
  }
  if (meta.recommendation?.analytics_hint) {
    badges.push({ text: "含行为分析依据", state: "success" });
  }
  if (String(meta.response_kind || "").startsWith("refused")) {
    badges.push({ text: "证据不足已拒答", state: "danger" });
  }
  if (String(meta.response_kind || "").startsWith("gps:")) {
    badges.push({ text: "弱 GPS 多轮问路", state: "warning" });
  }
  return badges;
}

export function ChatMessage({ message }) {
  const isUser = message.role === "user";
  const badgeText = message.meta ? gpsStatusText(message.meta) : null;
  const badges = !isUser ? sourceBadges(message.meta) : [];
  const badgeState = message.meta?.gps_state === "resolved" || message.meta?.gps_state === "resolved_recommendation"
    ? "success"
    : "warning";

  return (
    <div className={`chat-message ${isUser ? "is-user" : ""}`}>
      <div className={`message-bubble ${isUser ? "message-bubble--user" : "message-bubble--assistant"}`}>
        <div className="message-role">{isUser ? "游客" : "数字人导游"}</div>
        {badgeText ? <StatusBadge state={badgeState}>{badgeText}</StatusBadge> : null}
        {badges.length ? (
          <div className="message-source-row">
            {badges.map((badge) => (
              <StatusBadge key={badge.text} state={badge.state}>{badge.text}</StatusBadge>
            ))}
          </div>
        ) : null}
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
