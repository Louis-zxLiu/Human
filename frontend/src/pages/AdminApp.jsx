import React, { useEffect, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";
import { fetchDashboard, fetchVoices, previewVoice, updateVoice, uploadAvatar } from "../lib/api";


export function AdminApp() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [voices, setVoices] = useState([]);
  const [currentVoice, setCurrentVoice] = useState("");
  const [avatarFile, setAvatarFile] = useState(null);
  const username = localStorage.getItem("username") || "admin";

  useEffect(() => {
    const token = localStorage.getItem("auth_token");
    const role = localStorage.getItem("user_role");
    if (!token || role !== "admin") {
      window.location.href = "/login";
      return;
    }
    refresh();
    fetchVoices().then((result) => {
      setVoices(result.available_voices || []);
      setCurrentVoice(result.current_voice || "");
    }).catch(() => {});
  }, []);

  async function refresh() {
    setLoading(true);
    try {
      const result = await fetchDashboard();
      setData(result);
    } finally {
      setLoading(false);
    }
  }

  async function handleVoiceSave() {
    await updateVoice(currentVoice);
    alert("音色已更新");
  }

  async function handleVoicePreview() {
    const result = await previewVoice(currentVoice);
    const audio = new Audio(result.audio_url);
    await audio.play();
  }

  async function handleAvatarUpload() {
    if (!avatarFile) return;
    await uploadAvatar(avatarFile);
    alert("数字人形象已更新");
  }

  if (loading || !data) {
    return <div className="page-shell"><div className="card" style={{ padding: 24 }}>加载中...</div></div>;
  }

  const status = data.data_status || {};
  return (
    <div className="page-shell" style={{ display: "grid", gap: 16 }}>
      <header className="card-dark card" style={{ padding: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 28 }}>景区数字人管理后台</h1>
            <p style={{ color: "#cbd5e1" }}>欢迎，{username}</p>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button className="button-primary" onClick={refresh}>刷新数据</button>
            <button className="button-secondary" onClick={() => (window.location.href = "/")}>返回前台</button>
          </div>
        </div>
      </header>

      <section className="grid" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
        <MetricCard title="累计交互量" value={data.total_interactions} />
        <MetricCard title="当日交互量" value={data.daily_interactions} />
        <MetricCard title="平均响应耗时" value={`${data.avg_cost_time}s`} />
      </section>

      <section className="grid" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
        <div className="card" style={{ padding: 20 }}>
          <div className="section-title">数据状态</div>
          <div style={{ display: "grid", gap: 10 }}>
            <StatusBadge state={status.preflight_ok ? "success" : "danger"}>{status.preflight_ok ? "预检通过" : "预检未通过"}</StatusBadge>
            <StatusBadge state={status.knowledge_base_ready ? "success" : "warning"}>景区知识库：{status.knowledge_base_ready ? "已就绪" : "未就绪"}</StatusBadge>
            <StatusBadge state={status.behavior_db_ready ? "success" : "warning"}>行为分析库：{status.behavior_db_ready ? "已就绪" : "未就绪"}</StatusBadge>
            <div className="muted">知识文档数：{status.knowledge_doc_count || 0}</div>
          </div>
        </div>

        <div className="card" style={{ padding: 20 }}>
          <div className="section-title">推荐标签分布</div>
          <div className="grid">
            {Object.entries(data.recommendation_label_distribution || {}).map(([label, value]) => (
              <div key={label} className="card" style={{ padding: 12 }}>
                <div>{label}</div>
                <div className="muted">触发次数：{value}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="card" style={{ padding: 20 }}>
          <div className="section-title">音色与数字人</div>
          <div className="grid">
            <select className="input" value={currentVoice} onChange={(event) => setCurrentVoice(event.target.value)}>
              {voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.name}</option>)}
            </select>
            <div style={{ display: "flex", gap: 10 }}>
              <button className="button-primary" onClick={handleVoiceSave}>保存音色</button>
              <button className="button-secondary" onClick={handleVoicePreview}>试听</button>
            </div>
            <input type="file" onChange={(event) => setAvatarFile(event.target.files?.[0] || null)} />
            <button className="button-primary" onClick={handleAvatarUpload} disabled={!avatarFile}>上传默认头像</button>
          </div>
        </div>
      </section>

      <section className="grid" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
        <div className="card" style={{ padding: 20 }}>
          <div className="section-title">热门分析问题</div>
          <div className="grid">
            {(data.hot_analytics_questions || []).map((item) => (
              <div key={item.question} className="card" style={{ padding: 12 }}>
                <div>{item.question}</div>
                <div className="muted">出现次数：{item.count}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="card" style={{ padding: 20 }}>
          <div className="section-title">热门景点偏好</div>
          <div className="grid">
            {(data.top_attraction_preferences || []).map((item) => (
              <div key={item.name} className="card" style={{ padding: 12 }}>
                <div>{item.name}</div>
                <div className="muted">触发次数：{item.value}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="card" style={{ padding: 20 }}>
          <div className="section-title">最近失败样例</div>
          <div className="grid">
            {(data.recent_failed_samples || []).map((item, index) => (
              <div key={index} className="card" style={{ padding: 12 }}>
                <StatusBadge state="warning">{item.response_kind}</StatusBadge>
                <div style={{ marginTop: 8, fontWeight: 600 }}>{item.user_query}</div>
                <div className="muted" style={{ marginTop: 6, fontSize: 13 }}>{item.ai_response}</div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
