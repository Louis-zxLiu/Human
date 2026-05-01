import React, { useEffect, useState } from "react";

import { DonutChart } from "../components/DonutChart";
import { InsightBarList } from "../components/InsightBarList";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";
import { TrendChart } from "../components/TrendChart";
import {
  fetchAvatarRuntime,
  fetchDashboard,
  fetchVoices,
  logout,
  previewVoice,
  updateAvatarRuntime,
  updateVoice,
  uploadAvatar,
} from "../lib/api";

const AUTH_KEYS = ["auth_token", "username", "user_role"];
const INTENT_LABELS = {
  FACT: "景点问答",
  RECOMMEND: "路线推荐",
  ANALYTICS: "数据分析",
};

function formatLabel(value, labelMap = {}) {
  const normalized = String(value || "").trim();
  if (!normalized) return "";
  return labelMap[normalized] || normalized.replace(/_/g, " ");
}

function formatResponseKind(value) {
  const normalized = String(value || "").trim();
  if (!normalized) return "未知原因";
  if (normalized.startsWith("gps:ambiguous")) return "弱 GPS 歧义";
  if (normalized.startsWith("gps:need_more")) return "弱 GPS 信息不足";
  if (normalized.startsWith("refused")) return "拒答或拦截";
  return normalized;
}

function formatDateTime(value) {
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

function toBarItems(data, labelMap) {
  return Object.entries(data || {})
    .map(([label, value]) => ({ label: formatLabel(label, labelMap), value: Number(value || 0) }))
    .filter((item) => item.label && item.value > 0)
    .sort((left, right) => right.value - left.value);
}

export function AdminApp() {
  const username = localStorage.getItem("username") || "admin";

  const [data, setData] = useState(null);
  const [voices, setVoices] = useState([]);
  const [currentVoice, setCurrentVoice] = useState("");
  const [avatarRuntime, setAvatarRuntime] = useState(null);
  const [avatarFile, setAvatarFile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState(null);
  const [busy, setBusy] = useState({
    refresh: false,
    saveVoice: false,
    previewVoice: false,
    uploadAvatar: false,
    avatarRuntime: false,
  });

  useEffect(() => {
    const token = localStorage.getItem("auth_token");
    const role = localStorage.getItem("user_role");
    if (!token || role !== "admin") {
      window.location.href = "/login";
      return;
    }

    bootstrap();
  }, []);

  async function bootstrap() {
    setLoading(true);
    setError("");

    try {
      const [dashboardResult, voiceResult, runtimeResult] = await Promise.all([
        fetchDashboard(),
        fetchVoices(),
        fetchAvatarRuntime(),
      ]);
      setData(dashboardResult);
      setVoices(voiceResult.available_voices || []);
      setCurrentVoice(voiceResult.current_voice || voiceResult.available_voices?.[0]?.id || "");
      setAvatarRuntime(runtimeResult);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function refreshDashboard() {
    setBusy((previous) => ({ ...previous, refresh: true }));
    setFeedback(null);
    setError("");

    try {
      const dashboardResult = await fetchDashboard();
      setData(dashboardResult);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy((previous) => ({ ...previous, refresh: false }));
    }
  }

  async function handleVoiceSave() {
    if (!currentVoice) return;
    setBusy((previous) => ({ ...previous, saveVoice: true }));
    setFeedback(null);

    try {
      await updateVoice(currentVoice);
      setFeedback({ type: "success", message: "音色配置已更新。" });
    } catch (err) {
      setFeedback({ type: "danger", message: err.message });
    } finally {
      setBusy((previous) => ({ ...previous, saveVoice: false }));
    }
  }

  async function handleVoicePreview() {
    if (!currentVoice) return;
    setBusy((previous) => ({ ...previous, previewVoice: true }));
    setFeedback(null);

    try {
      const result = await previewVoice(currentVoice);
      const audio = new Audio(result.audio_url);
      await audio.play();
      setFeedback({ type: "info", message: "正在播放当前音色预览。" });
    } catch (err) {
      setFeedback({ type: "danger", message: err.message });
    } finally {
      setBusy((previous) => ({ ...previous, previewVoice: false }));
    }
  }

  async function handleAvatarUpload() {
    if (!avatarFile) return;
    setBusy((previous) => ({ ...previous, uploadAvatar: true }));
    setFeedback(null);

    try {
      await uploadAvatar(avatarFile);
      setAvatarFile(null);
      setFeedback({ type: "success", message: "默认数字人头像已更新。" });
    } catch (err) {
      setFeedback({ type: "danger", message: err.message });
    } finally {
      setBusy((previous) => ({ ...previous, uploadAvatar: false }));
    }
  }

  async function handleAvatarRuntimeChange(profileId) {
    if (!avatarRuntime || avatarRuntime.current_profile_id === profileId) return;
    setBusy((previous) => ({ ...previous, avatarRuntime: true }));
    setFeedback(null);

    try {
      const result = await updateAvatarRuntime(profileId);
      setAvatarRuntime(result);
      setFeedback({
        type: "success",
        message: result.message || "数字人画质模式已切换。",
      });
    } catch (err) {
      setFeedback({ type: "danger", message: err.message });
    } finally {
      setBusy((previous) => ({ ...previous, avatarRuntime: false }));
    }
  }

  async function handleLogout() {
    try {
      await logout();
    } catch {
      // Ignore transport failure and clear auth state locally.
    }

    AUTH_KEYS.forEach((key) => localStorage.removeItem(key));
    window.location.href = "/login";
  }

  if (loading && !data) {
    return (
      <div className="page-shell">
        <div className="page-container page-stack">
          <section className="panel admin-state">
            <div className="eyebrow">管理后台</div>
            <h1 className="panel-title">正在加载运营驾驶舱...</h1>
            <p className="panel-copy">正在同步互动数据、音色配置和数字人后台状态。</p>
          </section>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="page-shell">
        <div className="page-container page-stack">
          <section className="panel admin-state">
            <div className="eyebrow">管理后台</div>
            <h1 className="panel-title">后台暂时不可用</h1>
            <p className="panel-copy">{error || "暂时无法加载后台数据。"}</p>
            <button type="button" className="button-primary" onClick={bootstrap}>重试加载</button>
          </section>
        </div>
      </div>
    );
  }

  const status = data.data_status || {};
  const intentItems = toBarItems(data.intent_distribution, INTENT_LABELS);
  const recommendationItems = toBarItems(data.recommendation_label_distribution);
  const focusItems = (data.focus_points || []).slice(0, 6);
  const questionItems = (data.hot_analytics_questions || []).map((item) => ({ label: item.question, value: item.count }));
  const attractionItems = (data.top_attraction_preferences || []).map((item) => ({ label: item.name, value: item.value }));
  const knowledgeDocuments = status.knowledge_documents || [];

  return (
    <div className="page-shell">
      <div className="page-container admin-layout">
        <section className="panel panel-dark admin-hero">
          <div className="admin-hero__copy">
            <div className="eyebrow">灵山胜境管理后台</div>
            <h1 className="hero-title">把游客互动趋势、知识库健康度和数字人配置放进一张更好判断的深色大屏里。</h1>
            <p className="hero-copy">
              这块大屏聚焦最值得运营关注的几类信号：游客到底在问什么、推荐是否真正发生、哪些问题最容易失败，以及当前知识库和数字人引擎是否健康。
            </p>
          </div>

          <div className="admin-hero__meta">
            <div className="status-cluster">
              <StatusBadge state="info">{username}</StatusBadge>
              <StatusBadge state={status.preflight_ok ? "success" : "warning"}>
                {status.preflight_ok ? "预检通过" : "预检待处理"}
              </StatusBadge>
            </div>

            <div className="admin-actions">
              <button type="button" className="button-primary" onClick={refreshDashboard} disabled={busy.refresh}>
                {busy.refresh ? "刷新中..." : "刷新数据"}
              </button>
              <button type="button" className="button-secondary" onClick={() => (window.location.href = "/")}>
                返回前台
              </button>
              <button type="button" className="text-button danger-text" onClick={handleLogout}>
                退出登录
              </button>
            </div>
          </div>
        </section>

        {feedback ? <div className={`feedback feedback-${feedback.type}`}>{feedback.message}</div> : null}
        {error ? <div className="feedback feedback-danger">{error}</div> : null}

        <section className="metric-grid">
          <MetricCard title="累计互动量" value={data.total_interactions} hint="全量历史日志" accent="sky" />
          <MetricCard title="当日互动量" value={data.daily_interactions} hint="今天新增的互动记录" accent="amber" />
          <MetricCard title="平均响应耗时" value={`${data.avg_cost_time}s`} hint="从提问到返回的整体耗时" accent="mint" />
          <MetricCard title="知识文档数" value={status.knowledge_doc_count || 0} hint="当前接入知识源数量" accent="coral" />
        </section>

        <section className="admin-grid admin-grid--charts">
          <article className="panel chart-card">
            <div className="panel-header panel-header--tight">
              <div>
                <div className="eyebrow">意图分布</div>
                <h2 className="panel-title">游客主要在问什么</h2>
              </div>
            </div>
            <DonutChart data={intentItems} totalLabel="意图总量" />
          </article>

          <article className="panel chart-card">
            <div className="panel-header panel-header--tight">
              <div>
                <div className="eyebrow">推荐标签</div>
                <h2 className="panel-title">推荐触发分布</h2>
              </div>
            </div>
            <DonutChart data={recommendationItems} totalLabel="推荐总量" />
          </article>

          <article className="panel chart-card chart-card--wide">
            <div className="panel-header panel-header--tight">
              <div>
                <div className="eyebrow">满意度趋势</div>
                <h2 className="panel-title">最近 7 天情绪变化</h2>
              </div>
            </div>
            <TrendChart data={data.satisfaction_trend || []} />
          </article>

          <article className="panel chart-card">
            <div className="panel-header panel-header--tight">
              <div>
                <div className="eyebrow">关注焦点</div>
                <h2 className="panel-title">游客最常提到的点位</h2>
              </div>
            </div>
            <InsightBarList items={focusItems} emptyLabel="暂无焦点词" />
          </article>
        </section>

        <section className="admin-grid admin-grid--ops">
          <article className="panel ops-card">
            <div className="panel-header panel-header--tight">
              <div>
                <div className="eyebrow">运行状态</div>
                <h2 className="panel-title">数据与知识库健康度</h2>
              </div>
            </div>

            <div className="status-cluster">
              <StatusBadge state={status.preflight_ok ? "success" : "warning"}>
                {status.preflight_ok ? "预检通过" : "预检未通过"}
              </StatusBadge>
              <StatusBadge state={status.knowledge_base_ready ? "success" : "warning"}>
                {status.knowledge_base_ready ? "知识库就绪" : "知识库未就绪"}
              </StatusBadge>
              <StatusBadge state={status.behavior_db_ready ? "success" : "warning"}>
                {status.behavior_db_ready ? "行为库就绪" : "行为库未就绪"}
              </StatusBadge>
            </div>

            <div className="note-list">
              <div className="note-card">
                <strong>知识文档清单</strong>
                <span>{knowledgeDocuments.length ? knowledgeDocuments.join("、") : "当前未检测到文档列表。"}</span>
              </div>
            </div>
          </article>

          <article className="panel ops-card">
            <div className="panel-header panel-header--tight">
              <div>
                <div className="eyebrow">运营操作</div>
                <h2 className="panel-title">音色与数字人配置</h2>
              </div>
            </div>

            {avatarRuntime ? (
              <div className="field">
                <span className="field-label">数字人画质模式</span>
                <div className="runtime-mode-grid">
                  {avatarRuntime.profiles.map((profile) => (
                    <button
                      type="button"
                      key={profile.id}
                      className={`runtime-mode-card ${avatarRuntime.current_profile_id === profile.id ? "is-active" : ""}`}
                      onClick={() => handleAvatarRuntimeChange(profile.id)}
                      disabled={busy.avatarRuntime || avatarRuntime.current_profile_id === profile.id}
                      title={profile.description}
                    >
                      <div className="runtime-mode-card__header">
                        <strong>{profile.label}</strong>
                        <span className="runtime-mode-card__hint" title={profile.description}>?</span>
                      </div>
                      <span>{profile.summary}</span>
                      <span className="meta-note">
                        {profile.torch_dtype} / warmup {profile.warmup_seconds}s
                      </span>
                    </button>
                  ))}
                </div>
                <span className="meta-note">
                  鼠标移到按钮或问号上可以查看显存与画质说明。切换后会重载数字人引擎。
                </span>
              </div>
            ) : null}

            <label className="field">
              <span className="field-label">当前音色</span>
              <select
                className="input-field"
                value={currentVoice}
                onChange={(event) => setCurrentVoice(event.target.value)}
              >
                {voices.map((voice) => (
                  <option key={voice.id} value={voice.id}>{voice.name}</option>
                ))}
              </select>
            </label>

            <div className="button-row">
              <button type="button" className="button-primary" onClick={handleVoiceSave} disabled={busy.saveVoice || !currentVoice}>
                {busy.saveVoice ? "保存中..." : "保存音色"}
              </button>
              <button type="button" className="button-secondary" onClick={handleVoicePreview} disabled={busy.previewVoice || !currentVoice}>
                {busy.previewVoice ? "播放中..." : "试听"}
              </button>
            </div>

            <label className="field">
              <span className="field-label">更新数字人头像</span>
              <input
                className="input-field file-input"
                type="file"
                onChange={(event) => setAvatarFile(event.target.files?.[0] || null)}
              />
            </label>

            <button
              type="button"
              className="button-primary button-block"
              onClick={handleAvatarUpload}
              disabled={!avatarFile || busy.uploadAvatar}
            >
              {busy.uploadAvatar ? "上传中..." : "上传默认头像"}
            </button>
          </article>
        </section>

        <section className="admin-grid admin-grid--insights">
          <article className="panel insight-card">
            <div className="panel-header panel-header--tight">
              <div>
                <div className="eyebrow">热点问题</div>
                <h2 className="panel-title">高频分析类提问</h2>
              </div>
            </div>
            <InsightBarList items={questionItems} emptyLabel="暂无分析类热点问题" />
          </article>

          <article className="panel insight-card">
            <div className="panel-header panel-header--tight">
              <div>
                <div className="eyebrow">热门景点</div>
                <h2 className="panel-title">偏好聚焦点位</h2>
              </div>
            </div>
            <InsightBarList items={attractionItems} emptyLabel="暂无景点偏好数据" />
          </article>

          <article className="panel insight-card">
            <div className="panel-header panel-header--tight">
              <div>
                <div className="eyebrow">失败样例</div>
                <h2 className="panel-title">最近需要关注的对话</h2>
              </div>
            </div>

            <div className="failure-list">
              {(data.recent_failed_samples || []).length ? (
                data.recent_failed_samples.map((item, index) => (
                  <div key={`${item.user_query}-${index}`} className="failure-card">
                    <div className="failure-card__meta">
                      <StatusBadge state="warning">{formatResponseKind(item.response_kind)}</StatusBadge>
                      <span className="meta-note">{formatDateTime(item.created_at)}</span>
                    </div>
                    <strong>{item.user_query}</strong>
                    <p>{item.ai_response}</p>
                  </div>
                ))
              ) : (
                <div className="empty-state empty-state--compact">
                  <strong>近期没有失败样例</strong>
                </div>
              )}
            </div>
          </article>
        </section>
      </div>
    </div>
  );
}
