import React, { useEffect, useState } from "react";

import { PlannerResultCard } from "../components/PlannerResultCard";
import { ProductFooter } from "../components/ProductFooter";
import { ProductHeader } from "../components/ProductHeader";
import { fetchScenicAreas, planScenicRoute } from "../lib/api";

const INTEREST_OPTIONS = [
  { value: "general", label: "经典首游" },
  { value: "history", label: "历史文化" },
  { value: "nature", label: "风景打卡" },
  { value: "family", label: "亲子同游" },
  { value: "architecture", label: "建筑艺术" },
  { value: "relaxed", label: "轻松慢游" },
];
const DURATION_OPTIONS = [
  { value: "short", label: "轻量半日" },
  { value: "half-day", label: "半日游" },
  { value: "full-day", label: "整日游" },
  { value: "night-tour", label: "夜游" },
];
const VISITOR_OPTIONS = [
  { value: "solo", label: "独自出行" },
  { value: "couple", label: "情侣同游" },
  { value: "family", label: "亲子家庭" },
  { value: "elder", label: "长辈同行" },
  { value: "friends", label: "朋友结伴" },
];
const PACE_OPTIONS = [
  { value: "compact", label: "紧凑" },
  { value: "balanced", label: "均衡" },
  { value: "relaxed", label: "舒缓" },
];

export function PlannerApp() {
  const query = new URLSearchParams(window.location.search);
  const [areas, setAreas] = useState([]);
  const [form, setForm] = useState({
    scenicSlug: query.get("scenicSlug") || "lingshan-shengjing",
    interestLabel: "general",
    durationBand: "half-day",
    visitorType: "solo",
    pace: "balanced",
  });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [bootLoading, setBootLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    fetchScenicAreas()
      .then((payload) => {
        if (!alive) return;
        setAreas(payload);
        if (!payload.some((item) => item.slug === form.scenicSlug) && payload[0]) {
          setForm((previous) => ({ ...previous, scenicSlug: payload[0].slug }));
        }
      })
      .catch((err) => {
        if (!alive) return;
        setError(err.message);
      })
      .finally(() => {
        if (!alive) return;
        setBootLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [form.scenicSlug]);

  async function handleSubmit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const payload = await planScenicRoute(form);
      setResult(payload);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="product-page">
      <div className="page-container">
        <ProductHeader active="planner" />

        <section className="planner-shell">
          <div className="planner-shell__form">
            <div className="eyebrow">路线规划</div>
            <h1>先把园区、人群和节奏说清楚，再交给数字人去讲。</h1>
            <p>这页把推荐能力整理成稳定、清晰、可直接使用的规划流程，方便游客先定路线再进入导览。</p>

            {error ? <div className="feedback feedback-danger">{error}</div> : null}
            {bootLoading ? <div className="loading-row">正在加载园区配置...</div> : null}

            <form className="planner-form" onSubmit={handleSubmit}>
              <label className="field">
                <span className="field-label">选择园区</span>
                <select
                  className="input-field"
                  value={form.scenicSlug}
                  onChange={(event) => setForm({ ...form, scenicSlug: event.target.value })}
                >
                  {areas.map((area) => (
                    <option key={area.slug} value={area.slug}>{area.name}</option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span className="field-label">兴趣偏好</span>
                <select
                  className="input-field"
                  value={form.interestLabel}
                  onChange={(event) => setForm({ ...form, interestLabel: event.target.value })}
                >
                  {INTEREST_OPTIONS.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span className="field-label">游玩时长</span>
                <select
                  className="input-field"
                  value={form.durationBand}
                  onChange={(event) => setForm({ ...form, durationBand: event.target.value })}
                >
                  {DURATION_OPTIONS.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span className="field-label">游客类型</span>
                <select
                  className="input-field"
                  value={form.visitorType}
                  onChange={(event) => setForm({ ...form, visitorType: event.target.value })}
                >
                  {VISITOR_OPTIONS.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span className="field-label">整体节奏</span>
                <select
                  className="input-field"
                  value={form.pace}
                  onChange={(event) => setForm({ ...form, pace: event.target.value })}
                >
                  {PACE_OPTIONS.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>

              <button type="submit" className="button-primary" disabled={loading || bootLoading}>
                {loading ? "生成中..." : "生成推荐路线"}
              </button>
            </form>
          </div>

          <div className="planner-shell__result">
            {result ? (
              <PlannerResultCard plan={result} />
            ) : (
              <div className="empty-state planner-empty">
                <strong>先生成一条路线</strong>
                <span>结果会带上园区语境、讲解重点、行为分析补充和进入数字人导览的入口。</span>
              </div>
            )}
          </div>
        </section>

        <ProductFooter />
      </div>
    </div>
  );
}
