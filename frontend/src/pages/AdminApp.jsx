import React, { useCallback, useEffect, useRef, useState } from "react";

import { ProductFooter } from "../components/ProductFooter";
import { ProductHeader } from "../components/ProductHeader";
import {
  deleteKBDocument,
  fetchAvatarRuntime,
  fetchDashboard,
  fetchKBDocuments,
  fetchKBRebuildStatus,
  fetchVoices,
  isAuthError,
  logout,
  previewVoice,
  rebuildKnowledgeBase,
  refreshRuntimeCache,
  updateAvatarRuntime,
  updateVoice,
  uploadAvatar,
  uploadKBDocument,
} from "../lib/api";

const AUTH_KEYS = ["auth_token", "username", "user_role"];
const INTENT_LABELS = {
  FACT: "景点问答",
  RECOMMEND: "路线推荐",
  ANALYTICS: "数据分析",
  CHAT: "日常咨询",
  GUIDE: "导览讲解",
};

const COMMON_LABELS = {
  positive: "正向",
  neutral: "中性",
  negative: "负向",
  high: "高",
  medium: "中",
  low: "低",
  total_interactions: "总交互量",
  daily_interactions: "今日交互",
  avg_cost_time: "平均响应时长",
  created_at: "创建时间",
  user_query: "用户问题",
  ai_response: "数字人回复",
  response_kind: "响应类型",
};

const SENTIMENT_COLORS = ["#f59e0b", "#14b8a6", "#ef4444"];
const PREF_BAR_CLASSES = ["adm-pref-bar--amber", "adm-pref-bar--teal", "adm-pref-bar--coral", "adm-pref-bar--rose"];
const LABEL_COLORS = {
  "热门推荐": "#f59e0b",
  "亲子游": "#14b8a6",
  "文化体验": "#f97316",
  "自然风光": "#ef4444",
  "美食之旅": "#f59e0b",
  "历史古迹": "#14b8a6",
};

function formatLabel(value, labelMap = {}) {
  const normalized = String(value || "").trim();
  if (!normalized) return "";
  return labelMap[normalized] || COMMON_LABELS[normalized] || normalized.replace(/_/g, " ");
}

function formatResponseKind(value) {
  const normalized = String(value || "").trim();
  if (!normalized) return "未知类型";
  if (normalized.startsWith("gps:ambiguous")) return "定位信息存在歧义";
  if (normalized.startsWith("gps:need_more")) return "定位信息不足";
  if (normalized.startsWith("refused")) return "已拒答";
  return COMMON_LABELS[normalized] || normalized.replace(/_/g, " ");
}

function getVoiceId(voice) {
  return voice?.id || voice?.voice_id || "";
}

function formatVoiceName(voiceId, voices = []) {
  const match = voices.find((voice) => getVoiceId(voice) === voiceId);
  return match?.name || "未选择音色";
}

function formatProfileName(profileId, profiles = []) {
  const match = profiles.find((profile) => profile.id === profileId);
  return match?.label || COMMON_LABELS[profileId] || "未选择配置";
}

function formatPrecision(value) {
  const normalized = String(value || "").toLowerCase();
  const precisionLabels = {
    float16: "半精度",
    bfloat16: "脑浮点半精度",
    float32: "标准精度",
  };
  return precisionLabels[normalized] || "自动选择";
}

function formatRuntimeText(value) {
  return String(value || "")
    .replace(/\bbfloat16\b/gi, "脑浮点半精度")
    .replace(/\bfloat16\b/gi, "半精度")
    .replace(/\bfloat32\b/gi, "标准精度")
    .replace(/\bwarmup\b/gi, "预热");
}

function formatAdminText(value) {
  return String(value || "")
    .replace(/\bAI\b/g, "数字人")
    .replace(/\bGPS\b/g, "定位信号")
    .replace(/\bDOCX\b/g, "文档")
    .replace(/\bPNG\s*\/\s*JPG\b/gi, "图片文件")
    .replace(/\bMB\b/g, "兆")
    .replace(/约\s*([\d.]+)s\b/g, "约 $1 秒");
}

function formatAdminName(value) {
  const normalized = String(value || "").trim();
  if (!normalized) return "管理员";
  if (normalized.toLowerCase() === "admin") return "管理员";
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

/* ── Reveal hook (IntersectionObserver) ── */
function useReveal() {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("adm-visible");
            e.target.querySelectorAll(".adm-reveal-child").forEach((c, i) => {
              setTimeout(() => c.classList.add("adm-visible"), i * 100);
            });
            obs.unobserve(e.target);
          }
        });
      },
      { threshold: 0.1, rootMargin: "0px 0px -40px 0px" }
    );
    el.querySelectorAll(".adm-reveal, .adm-reveal-stagger, .adm-reveal-scale").forEach((node) => obs.observe(node));
    return () => obs.disconnect();
  }, []);
  return ref;
}

/* ── Particle canvas hook ── */
function useParticleCanvas() {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let animId;
    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();
    const PARTICLE_COUNT = 15;
    const particles = Array.from({ length: PARTICLE_COUNT }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: Math.random() * 1.5 + 0.5,
      o: Math.random() * 0.3 + 0.1,
      vx: (Math.random() - 0.5) * 0.3,
      vy: -(Math.random() * 0.3 + 0.1),
      phase: Math.random() * Math.PI * 2,
    }));
    function animate() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.globalCompositeOperation = "lighter";
      particles.forEach((p) => {
        p.x += p.vx + Math.sin(p.phase) * 0.1;
        p.y += p.vy;
        p.phase += 0.01;
        if (p.y < -10) {
          p.y = canvas.height + 10;
          p.x = Math.random() * canvas.width;
        }
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(245, 158, 11, ${p.o})`;
        ctx.fill();
      });
      animId = requestAnimationFrame(animate);
    }
    animate();
    window.addEventListener("resize", resize, { passive: true });
    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", resize);
    };
  }, []);
  return canvasRef;
}

/* ── Cursor glow hook ── */
function useCursorGlow() {
  const glowRef = useRef(null);
  useEffect(() => {
    const glow = glowRef.current;
    if (!glow) return;
    let mx = 0, my = 0, gx = 0, gy = 0;
    const onMouseMove = (e) => {
      mx = e.clientX;
      my = e.clientY;
    };
    let animId;
    function updateGlow() {
      gx += (mx - gx) * 0.08;
      gy += (my - gy) * 0.08;
      glow.style.left = gx + "px";
      glow.style.top = gy + "px";
      animId = requestAnimationFrame(updateGlow);
    }
    document.addEventListener("mousemove", onMouseMove, { passive: true });
    updateGlow();
    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      cancelAnimationFrame(animId);
    };
  }, []);
  return glowRef;
}

/* ── Tilt card hook ── */
function useTiltCard() {
  const ref = useRef(null);
  useEffect(() => {
    const card = ref.current;
    if (!card) return;
    const onMove = (e) => {
      const rect = card.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width - 0.5;
      const y = (e.clientY - rect.top) / rect.height - 0.5;
      card.style.transform = `perspective(800px) rotateY(${x * 8}deg) rotateX(${-y * 8}deg)`;
      const shine = card.querySelector(".adm-tilt-shine");
      if (shine) {
        shine.style.setProperty("--shine-x", e.clientX - rect.left + "px");
        shine.style.setProperty("--shine-y", e.clientY - rect.top + "px");
      }
    };
    const onLeave = () => {
      card.style.transform = "perspective(800px) rotateY(0) rotateX(0)";
    };
    card.addEventListener("mousemove", onMove);
    card.addEventListener("mouseleave", onLeave);
    return () => {
      card.removeEventListener("mousemove", onMove);
      card.removeEventListener("mouseleave", onLeave);
    };
  }, []);
  return ref;
}

/* ── Magnetic button hook ── */
function useMagneticBtn() {
  const ref = useRef(null);
  useEffect(() => {
    const btn = ref.current;
    if (!btn) return;
    const onMove = (e) => {
      const rect = btn.getBoundingClientRect();
      const x = e.clientX - rect.left - rect.width / 2;
      const y = e.clientY - rect.top - rect.height / 2;
      btn.style.transform = `translate(${x * 0.15}px, ${y * 0.15}px)`;
    };
    const onLeave = () => {
      btn.style.transform = "translate(0, 0)";
    };
    btn.addEventListener("mousemove", onMove);
    btn.addEventListener("mouseleave", onLeave);
    return () => {
      btn.removeEventListener("mousemove", onMove);
      btn.removeEventListener("mouseleave", onLeave);
    };
  }, []);
  return ref;
}

/* ── Counter animation hook ── */
function useCountUp(target, duration = 1200) {
  const [display, setDisplay] = useState(0);
  const ref = useRef(null);
  const started = useRef(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting && !started.current) {
            started.current = true;
            const start = performance.now();
            const animate = (now) => {
              const p = Math.min((now - start) / duration, 1);
              const eased = 1 - Math.pow(1 - p, 3);
              setDisplay(Math.floor(target * eased));
              if (p < 1) requestAnimationFrame(animate);
              else setDisplay(target);
            };
            requestAnimationFrame(animate);
            obs.unobserve(e.target);
          }
        });
      },
      { threshold: 0.5 }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [target, duration]);
  return [display, ref];
}

/* ── Chart bar animation observer ── */
function useBarAnimation() {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.querySelectorAll(".adm-chart-bar-animated").forEach((bar, i) => {
              setTimeout(() => bar.classList.add("adm-visible"), i * 80);
            });
            obs.unobserve(e.target);
          }
        });
      },
      { threshold: 0.2 }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
  return ref;
}

/* ── TiltCard wrapper component ── */
function TiltCard({ children, className = "" }) {
  const tiltRef = useTiltCard();
  return (
    <div ref={tiltRef} className={`adm-tilt-card ${className}`}>
      <div className="adm-tilt-shine" />
      {children}
    </div>
  );
}

/* ── MagneticBtn wrapper component ── */
function MagneticBtn({ children, className = "", ...props }) {
  const btnRef = useMagneticBtn();
  return (
    <button ref={btnRef} className={`adm-magnetic-btn ${className}`} {...props}>
      {children}
    </button>
  );
}

/* ── StatCard with counter ── */
function StatCard({ label, value, accent, suffix = "", isNumber = true }) {
  const target = isNumber ? Number(value) || 0 : 0;
  const [count, countRef] = useCountUp(target);
  return (
    <div className={`adm-stat-card adm-stat-card--${accent}`}>
      <div className="adm-stat-label">{label}</div>
      <div className={`adm-stat-value adm-stat-value--${accent}`} ref={countRef}>
        {isNumber ? count.toLocaleString() : value}{suffix}
      </div>
    </div>
  );
}

/* ── Sentiment Pie Chart ── */
function SentimentPie({ data }) {
  if (!data || !data.length) return <div className="adm-chart-empty">暂无数据</div>;
  let start = 0;
  const stops = data.map((d) => {
    const s = start;
    const e = start + d.value;
    start = e;
    const idx = data.indexOf(d);
    return `${SENTIMENT_COLORS[idx % SENTIMENT_COLORS.length]} ${s}% ${e}%`;
  });
  const style = { background: `conic-gradient(${stops.join(", ")})` };
  return (
    <div>
      <div className="adm-pie-chart" style={style} />
      <div className="adm-pie-legend">
        {data.map((item, i) => (
          <div key={i} className="adm-pie-legend-item">
            <span className="adm-pie-legend-dot" style={{ background: SENTIMENT_COLORS[i % SENTIMENT_COLORS.length] }} />
            {item.label} {item.value}%
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Bar Chart ── */
function BarChart({ data, accent, labelKey = "label", valueKey = "value" }) {
  const barRef = useBarAnimation();
  if (!data || !data.length) return <div className="adm-chart-empty">暂无数据</div>;
  const maxVal = Math.max(...data.map((d) => Number(d[valueKey]) || 0));
  return (
    <div className={`adm-chart-area adm-chart-area--${accent}`} ref={barRef}>
      {data.map((item, i) => {
        const pct = maxVal > 0 ? ((Number(item[valueKey]) || 0) / maxVal) * 100 : 0;
        return (
          <div key={i} className="adm-bar-group">
            <div
              className={`adm-bar adm-bar--${accent} adm-chart-bar-animated`}
              style={{ height: pct + "%" }}
            />
            <div className="adm-bar-label">{item[labelKey]}</div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Satisfaction Trend SVG ── */
function SatisfactionTrend({ data }) {
  if (!data || !data.length) return <div className="adm-chart-empty">暂无数据</div>;
  const w = 400, h = 200, pad = 20;
  if (data.length === 1) {
    const value = Number(data[0].positive || 0);
    const x = w / 2;
    const y = h - pad - (value / 100) * (h - 2 * pad);
    return (
      <div className="adm-line-chart">
        <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
          <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="#e5e7eb" strokeWidth="1" />
          <circle cx={x} cy={y} r="5" fill="#14b8a6" />
          <text x={x} y={Math.max(14, y - 12)} textAnchor="middle" fill="#64748b" fontSize="12">
            {value}%
          </text>
        </svg>
      </div>
    );
  }
  const pts = data.map((t, i) => ({
    x: pad + (i / (data.length - 1)) * (w - 2 * pad),
    y: h - pad - ((t.positive || 0) / 100) * (h - 2 * pad),
  }));
  const linePoints = pts.map((p) => `${p.x},${p.y}`).join(" ");
  let areaPath = `M${pts[0].x},${pts[0].y}`;
  for (let i = 1; i < pts.length; i++) {
    areaPath += ` L${pts[i].x},${pts[i].y}`;
  }
  areaPath += ` L${pts[pts.length - 1].x},${h} L${pts[0].x},${h} Z`;

  return (
    <div className="adm-line-chart">
      <svg viewBox="0 0 400 200" preserveAspectRatio="none">
        <defs>
          <linearGradient id="adm-tealGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#14b8a6" stopOpacity="0.3" />
            <stop offset="100%" stopColor="#14b8a6" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill="url(#adm-tealGrad)" />
        <polyline points={linePoints} fill="none" stroke="#14b8a6" strokeWidth="2.5" />
        {pts.map((pt, i) => (
          <circle key={i} cx={pt.x} cy={pt.y} r="4" fill="#14b8a6" />
        ))}
      </svg>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════
   AdminApp
   ════════════════════════════════════════════════════════════════════ */
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
    cacheRefresh: false,
    saveVoice: false,
    previewVoice: false,
    uploadAvatar: false,
    avatarRuntime: false,
    kbUpload: false,
    kbDelete: null,
    kbRebuild: false,
  });
  const [kbDocs, setKbDocs] = useState([]);
  const [kbFile, setKbFile] = useState(null);
  const [kbRebuildResult, setKbRebuildResult] = useState(null);

  const revealRef = useReveal();
  const particleCanvasRef = useParticleCanvas();
  const cursorGlowRef = useCursorGlow();

  useEffect(() => {
    if (!data) return;
    const el = revealRef.current;
    if (!el) return;
    window.requestAnimationFrame(() => {
      el.querySelectorAll(".adm-reveal, .adm-reveal-stagger, .adm-reveal-scale").forEach((node) => {
        node.classList.add("adm-visible");
      });
      el.querySelectorAll(".adm-reveal-child").forEach((node) => {
        node.classList.add("adm-visible");
      });
    });
  }, [data, revealRef]);

  const redirectToLogin = useCallback(() => {
    AUTH_KEYS.forEach((key) => localStorage.removeItem(key));
    const next = encodeURIComponent(`${window.location.pathname}${window.location.search}`);
    window.location.href = `/login?next=${next}`;
  }, []);

  useEffect(() => {
    const token = localStorage.getItem("auth_token");
    const role = localStorage.getItem("user_role");
    if (!token || role !== "admin") {
      redirectToLogin();
      return;
    }
    bootstrap();
  }, [redirectToLogin]);

  async function bootstrap() {
    setLoading(true);
    setError("");
    try {
      const [dashboardResult, voiceResult, runtimeResult, kbResult] = await Promise.all([
        fetchDashboard(),
        fetchVoices(),
        fetchAvatarRuntime(),
        fetchKBDocuments().catch(() => ({ documents: [] })),
      ]);
      setData(dashboardResult);
      setVoices(voiceResult.available_voices || []);
      setCurrentVoice(voiceResult.current_voice || voiceResult.available_voices?.[0]?.id || "");
      setAvatarRuntime(runtimeResult);
      setKbDocs(kbResult.documents || []);
    } catch (err) {
      if (isAuthError(err)) {
        redirectToLogin();
        return;
      }
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function refreshDashboard() {
    setBusy((prev) => ({ ...prev, refresh: true }));
    setFeedback(null);
    setError("");
    try {
      const dashboardResult = await fetchDashboard();
      setData(dashboardResult);
    } catch (err) {
      if (isAuthError(err)) {
        redirectToLogin();
        return;
      }
      setError(err.message);
    } finally {
      setBusy((prev) => ({ ...prev, refresh: false }));
    }
  }

  async function handleVoiceSave() {
    if (!currentVoice) return;
    setBusy((prev) => ({ ...prev, saveVoice: true }));
    setFeedback(null);
    try {
      await updateVoice(currentVoice);
      setFeedback({ type: "success", message: "音色配置已更新。" });
    } catch (err) {
      setFeedback({ type: "danger", message: err.message });
    } finally {
      setBusy((prev) => ({ ...prev, saveVoice: false }));
    }
  }

  async function handleVoicePreview() {
    if (!currentVoice) return;
    setBusy((prev) => ({ ...prev, previewVoice: true }));
    setFeedback(null);
    try {
      const result = await previewVoice(currentVoice);
      const audio = new Audio(result.audio_url);
      await audio.play();
      setFeedback({ type: "info", message: "正在播放当前音色预览。" });
    } catch (err) {
      setFeedback({ type: "danger", message: err.message });
    } finally {
      setBusy((prev) => ({ ...prev, previewVoice: false }));
    }
  }

  async function handleKBUpload() {
    if (!kbFile) return;
    setBusy((prev) => ({ ...prev, kbUpload: true }));
    setFeedback(null);
    try {
      await uploadKBDocument(kbFile);
      setKbFile(null);
      const result = await fetchKBDocuments();
      setKbDocs(result.documents || []);
      setFeedback({ type: "success", message: `${kbFile.name} 上传成功` });
    } catch (err) {
      setFeedback({ type: "danger", message: err.message });
    } finally {
      setBusy((prev) => ({ ...prev, kbUpload: false }));
    }
  }

  async function handleKBDelete(filename) {
    setBusy((prev) => ({ ...prev, kbDelete: filename }));
    setFeedback(null);
    try {
      await deleteKBDocument(filename);
      const result = await fetchKBDocuments();
      setKbDocs(result.documents || []);
      setFeedback({ type: "success", message: `${filename} 已删除` });
    } catch (err) {
      setFeedback({ type: "danger", message: err.message });
    } finally {
      setBusy((prev) => ({ ...prev, kbDelete: null }));
    }
  }

  async function handleKBRebuild() {
    setBusy((prev) => ({ ...prev, kbRebuild: true }));
    setKbRebuildResult(null);
    setFeedback(null);
    try {
      const res = await rebuildKnowledgeBase();
      setFeedback({ type: "info", message: res.message });
      const poll = setInterval(async () => {
        try {
          const status = await fetchKBRebuildStatus();
          if (!status.running) {
            clearInterval(poll);
            setBusy((prev) => ({ ...prev, kbRebuild: false }));
            setKbRebuildResult(status.last_result);
            const kbResult = await fetchKBDocuments().catch(() => ({ documents: [] }));
            setKbDocs(kbResult.documents || []);
            if (status.last_result?.success) {
              setFeedback({ type: "success", message: status.last_result.message });
            } else {
              setFeedback({ type: "danger", message: status.last_result?.message || "重建失败" });
            }
          }
        } catch (_e) {
          clearInterval(poll);
          setBusy((prev) => ({ ...prev, kbRebuild: false }));
        }
      }, 3000);
    } catch (err) {
      setFeedback({ type: "danger", message: err.message });
      setBusy((prev) => ({ ...prev, kbRebuild: false }));
    }
  }

  async function handleAvatarUpload() {
    if (!avatarFile) return;
    setBusy((prev) => ({ ...prev, uploadAvatar: true }));
    setFeedback(null);
    try {
      await uploadAvatar(avatarFile);
      setAvatarFile(null);
      setFeedback({ type: "success", message: "默认数字人头像已更新。" });
    } catch (err) {
      setFeedback({ type: "danger", message: err.message });
    } finally {
      setBusy((prev) => ({ ...prev, uploadAvatar: false }));
    }
  }

  async function handleAvatarRuntimeChange(profileId) {
    if (!avatarRuntime || avatarRuntime.current_profile_id === profileId) return;
    setBusy((prev) => ({ ...prev, avatarRuntime: true }));
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
      setBusy((prev) => ({ ...prev, avatarRuntime: false }));
    }
  }

  async function handleCacheRefresh() {
    setBusy((prev) => ({ ...prev, cacheRefresh: true }));
    setFeedback(null);
    try {
      const result = await refreshRuntimeCache();
      const removedLogs = Number(result.removed_logs || 0);
      setFeedback({
        type: "success",
        message: `${result.message || "后台状态已清空。"} 已移除 ${removedLogs} 条交互记录。`,
      });
      await refreshDashboard();
    } catch (err) {
      setFeedback({ type: "danger", message: err.message });
    } finally {
      setBusy((prev) => ({ ...prev, cacheRefresh: false }));
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

  /* ── Loading state ── */
  if (loading && !data) {
    return (
      <div className="adm-page">
        <canvas ref={particleCanvasRef} className="adm-particle-canvas" />
        <div ref={cursorGlowRef} className="adm-cursor-glow" />
        <ProductHeader active="admin" />
        <div className="adm-container">
          <section className="adm-state-panel">
            <div className="adm-eyebrow">管理后台</div>
            <h1 className="adm-state-title">正在加载运营驾驶舱...</h1>
            <p className="adm-state-copy">正在同步互动数据、音色配置和数字人后台状态。</p>
          </section>
        </div>
        <ProductFooter />
      </div>
    );
  }

  /* ── Error state ── */
  if (!data) {
    return (
      <div className="adm-page">
        <canvas ref={particleCanvasRef} className="adm-particle-canvas" />
        <div ref={cursorGlowRef} className="adm-cursor-glow" />
        <ProductHeader active="admin" />
        <div className="adm-container">
          <section className="adm-state-panel">
            <div className="adm-eyebrow">管理后台</div>
            <h1 className="adm-state-title">后台暂时不可用</h1>
            <p className="adm-state-copy">{error || "暂时无法加载后台数据。"}</p>
            <MagneticBtn className="adm-btn adm-btn--amber" onClick={bootstrap}>重试加载</MagneticBtn>
          </section>
        </div>
        <ProductFooter />
      </div>
    );
  }

  /* ── Derived data ── */
  const status = data.data_status || {};
  const intentItems = toBarItems(data.intent_distribution, INTENT_LABELS);
  const recommendationItems = toBarItems(data.recommendation_label_distribution);
  const focusItems = (data.focus_points || []).slice(0, 6);
  const questionItems = (data.hot_analytics_questions || []).map((item) => ({
    label: formatAdminText(item.question),
    value: item.count,
  }));
  const attractionItems = (data.top_attraction_preferences || []).map((item) => ({
    label: formatAdminText(item.name),
    value: item.value,
  }));
  const knowledgeDocuments = status.knowledge_documents || [];
  const knowledgeDetails = status.knowledge_document_details || [];
  const behaviorFiles = status.behavior_files || [];
  const rebuildCommands = status.rebuild_commands || {};
  const evalStatus = data.unified_eval || {};
  const evalFailureCount = evalStatus.failure_count ?? 0;
  const evalMetricHint = evalStatus.available
    ? `${evalStatus.case_count || 0} 题 / 待优化 ${evalFailureCount} 题`
    : "尚未生成评测报告";
  const operationRecommendations = data.operation_recommendations || [];

  /* ── Sentiment distribution for pie ── */
  const sentimentDist = data.sentiment_distribution || [];

  /* ── Satisfaction trend ── */
  const satisfactionTrend = data.satisfaction_trend || [];

  /* ── Recommendation label distribution for grid ── */
  const labelEntries = Object.entries(data.recommendation_label_distribution || {}).map(([label, count]) => [
    formatAdminText(formatLabel(label)),
    count,
  ]);

  /* ── Focus points for bar chart ── */
  const focusBarData = focusItems.map((fp) => ({
    label: formatAdminText(fp.name || fp.label || fp),
    value: fp.value || fp.count || 0,
  }));

  return (
    <div className="adm-page">
      <canvas ref={particleCanvasRef} className="adm-particle-canvas" />
      <div ref={cursorGlowRef} className="adm-cursor-glow" />
      <ProductHeader active="admin" />

      <div className="adm-container" ref={revealRef}>
        {/* ── Header Bar ── */}
        <div className="adm-header-bar adm-reveal">
          <div className="adm-header-info">
            <h1 className="adm-header-title">管理后台</h1>
            <p className="adm-header-sub">欢迎回来，{formatAdminName(username)}。运营驾驶舱实时监控。</p>
          </div>
          <div className="adm-header-actions">
            <MagneticBtn className="adm-btn adm-btn--amber" onClick={refreshDashboard} disabled={busy.refresh}>
              {busy.refresh ? "刷新中..." : "刷新数据"}
            </MagneticBtn>
            <MagneticBtn className="adm-btn adm-btn--teal" onClick={handleCacheRefresh} disabled={busy.cacheRefresh}>
              {busy.cacheRefresh ? "处理中..." : "重置后台状态"}
            </MagneticBtn>
            <MagneticBtn className="adm-btn adm-btn--outline" onClick={() => (window.location.href = "/")}>
              返回首页
            </MagneticBtn>
            <MagneticBtn className="adm-btn adm-btn--danger" onClick={handleLogout}>
              退出登录
            </MagneticBtn>
          </div>
        </div>

        {/* ── Feedback / Error ── */}
        {feedback ? (
          <div className={`adm-feedback adm-feedback--${feedback.type}`}>{feedback.message}</div>
        ) : null}
        {error ? (
          <div className="adm-feedback adm-feedback--danger">{error}</div>
        ) : null}

        {/* ── Stats Row ── */}
        <div className="adm-stats-row adm-reveal-stagger">
          <TiltCard className="adm-reveal-child">
            <StatCard label="累计交互量" value={data.total_interactions} accent="amber" />
          </TiltCard>
          <TiltCard className="adm-reveal-child">
            <StatCard label="今日交互量" value={data.daily_interactions} accent="teal" />
          </TiltCard>
          <TiltCard className="adm-reveal-child">
            <StatCard label="平均响应时长" value={data.avg_cost_time} accent="coral" suffix="秒" isNumber={false} />
          </TiltCard>
        </div>

        {/* ── Data Status Row ── */}
        <div className="adm-status-row adm-reveal-stagger">
          <div className="adm-status-card adm-reveal-child">
            <div className={`adm-status-dot ${status.preflight_ok ? "adm-status-dot--green" : "adm-status-dot--rose"}`} />
            <div className="adm-status-info">
              <h3>系统预检</h3>
              <p>
                <span className={`adm-tag ${status.preflight_ok ? "adm-tag--ok" : "adm-tag--err"}`}>
                  {status.preflight_ok ? "正常" : "异常"}
                </span>
              </p>
            </div>
          </div>
          <div className="adm-status-card adm-reveal-child">
            <div className={`adm-status-dot ${status.knowledge_base_ready ? "adm-status-dot--green" : "adm-status-dot--amber"}`} />
            <div className="adm-status-info">
              <h3>知识库状态</h3>
              <p>
                <span className={`adm-tag ${status.knowledge_base_ready ? "adm-tag--ok" : "adm-tag--warn"}`}>
                  {status.knowledge_base_ready ? "就绪" : "未就绪"}
                </span>
                &nbsp;|&nbsp;文档数: {status.knowledge_doc_count || knowledgeDocuments.length}
              </p>
            </div>
          </div>
          <div className="adm-status-card adm-reveal-child">
            <div className={`adm-status-dot ${status.behavior_db_ready ? "adm-status-dot--green" : "adm-status-dot--amber"}`} />
            <div className="adm-status-info">
              <h3>行为数据状态</h3>
              <p>
                <span className={`adm-tag ${status.behavior_db_ready ? "adm-tag--ok" : "adm-tag--warn"}`}>
                  {status.behavior_db_ready ? "就绪" : "未就绪"}
                </span>
                &nbsp;|&nbsp;文件数: {behaviorFiles.length}
              </p>
            </div>
          </div>
        </div>

        {/* ── Unified Eval Row ── */}
        <div className="adm-eval-row adm-reveal-stagger">
          <div className="adm-eval-card adm-reveal-child">
            <h3>综合评测得分</h3>
            <div className="adm-eval-value adm-stat-value--teal">
              {evalStatus.available ? evalStatus.overall_score : "--"}
            </div>
            <div className="adm-eval-sub">综合评分</div>
          </div>
          <div className="adm-eval-card adm-reveal-child">
            <h3>评测用例总数</h3>
            <div className="adm-eval-value adm-stat-value--amber">
              {evalStatus.case_count || 0}
            </div>
            <div className="adm-eval-sub">{evalMetricHint}</div>
          </div>
          <div className="adm-eval-card adm-reveal-child">
            <h3>待优化用例</h3>
            <div className="adm-eval-value adm-stat-value--rose">
              {evalFailureCount}
            </div>
            <div className="adm-eval-sub">失败用例数</div>
          </div>
        </div>

        {/* ── Charts Grid ── */}
        <div className="adm-charts adm-reveal-stagger">
          {/* Sentiment Pie */}
          <TiltCard className="adm-chart-card adm-reveal-scale">
            <h3 className="adm-chart-title">
              <span className="adm-chart-dot" style={{ background: "#f59e0b" }} />
              情感分布
            </h3>
            <SentimentPie data={sentimentDist} />
          </TiltCard>

          {/* Intent Bar */}
          <TiltCard className="adm-chart-card adm-reveal-scale">
            <h3 className="adm-chart-title">
              <span className="adm-chart-dot" style={{ background: "#14b8a6" }} />
              意图分布
            </h3>
            <BarChart data={intentItems} accent="teal" />
          </TiltCard>

          {/* Focus Points Bar */}
          <TiltCard className="adm-chart-card adm-reveal-scale">
            <h3 className="adm-chart-title">
              <span className="adm-chart-dot" style={{ background: "#f97316" }} />
              关注焦点
            </h3>
            <BarChart data={focusBarData} accent="coral" />
          </TiltCard>

          {/* Satisfaction Trend Line */}
          <TiltCard className="adm-chart-card adm-reveal-scale">
            <h3 className="adm-chart-title">
              <span className="adm-chart-dot" style={{ background: "#ef4444" }} />
              满意度趋势
            </h3>
            <SatisfactionTrend data={satisfactionTrend} />
          </TiltCard>
        </div>

        {/* ── Hot Analytics Questions ── */}
        <div className="adm-section adm-reveal">
          <h2 className="adm-section-title">
            <span className="adm-section-dot" style={{ background: "#f59e0b" }} />
            热门分析提问
          </h2>
          <div className="adm-question-list adm-reveal-stagger">
            {(data.hot_analytics_questions || []).length ? (
              (data.hot_analytics_questions || []).map((q, i) => (
                <div key={i} className="adm-question-item adm-reveal-child">
                  <div className="adm-q-badge">{i + 1}</div>
                  <div className="adm-q-text">{q.question}</div>
                  <div className="adm-q-count">{q.count}次</div>
                </div>
              ))
            ) : (
              <div className="adm-empty">暂无分析类热点问题</div>
            )}
          </div>
        </div>

        {/* ── Top Attraction Preferences ── */}
        <div className="adm-section adm-reveal">
          <h2 className="adm-section-title">
            <span className="adm-section-dot" style={{ background: "#f97316" }} />
            景点偏好排行
          </h2>
          <div className="adm-pref-list adm-reveal-stagger">
            {attractionItems.length ? (
              attractionItems.map((p, i) => (
                <div key={i} className="adm-pref-item adm-reveal-child">
                  <div className="adm-pref-name">{p.label}</div>
                  <div className="adm-pref-bar-bg">
                    <div
                      className={`adm-pref-bar ${PREF_BAR_CLASSES[i % PREF_BAR_CLASSES.length]}`}
                      style={{ width: p.value + "%" }}
                    >
                      {p.value}%
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="adm-empty">暂无景点偏好数据</div>
            )}
          </div>
        </div>

        {/* ── Recommendation Label Distribution ── */}
        <div className="adm-section adm-reveal">
          <h2 className="adm-section-title">
            <span className="adm-section-dot" style={{ background: "#14b8a6" }} />
            推荐标签分布
          </h2>
          <div className="adm-label-grid adm-reveal-stagger">
            {labelEntries.length ? (
              labelEntries.map(([label, count]) => (
                <div key={label} className="adm-label-item adm-reveal-child">
                  <span className="adm-label-name">{label}</span>
                  <span className="adm-label-count" style={{ color: LABEL_COLORS[label] || "#f59e0b" }}>
                    {count}
                  </span>
                </div>
              ))
            ) : (
              <div className="adm-empty">暂无推荐标签数据</div>
            )}
          </div>
        </div>

        {/* ── Recent Failed Samples ── */}
        <div className="adm-section adm-reveal">
          <h2 className="adm-section-title">
            <span className="adm-section-dot" style={{ background: "#ef4444" }} />
            最近失败样本
          </h2>
          <div className="adm-table-wrap">
            {(data.recent_failed_samples || []).length ? (
              <table className="adm-table">
                <thead>
                  <tr>
                    <th>创建时间</th>
                    <th>用户问题</th>
                    <th>数字人回复</th>
                    <th>响应类型</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.recent_failed_samples || []).map((s, i) => (
                    <tr key={i}>
                      <td className="adm-td-date">{formatDateTime(s.created_at)}</td>
                      <td>{formatAdminText(s.user_query)}</td>
                      <td className="adm-td-response">{formatAdminText(s.ai_response)}</td>
                      <td>
                        <span className="adm-tag adm-tag--rose">{formatResponseKind(s.response_kind)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="adm-empty">近期没有失败样例</div>
            )}
          </div>
        </div>

        {/* ── Operation Recommendations ── */}
        <div className="adm-section adm-reveal">
          <h2 className="adm-section-title">
            <span className="adm-section-dot" style={{ background: "#f59e0b" }} />
            运营建议
          </h2>
          <div className="adm-rec-list adm-reveal-stagger">
            {operationRecommendations.length ? (
              operationRecommendations.map((rec, i) => {
                const priority = formatLabel(rec.priority);
                const priorityClass =
                  priority === "高" ? "adm-rec-priority--high" :
                  priority === "中" ? "adm-rec-priority--medium" :
                  "adm-rec-priority--low";
                return (
                  <div key={i} className="adm-rec-item adm-reveal-child">
                    <div className={`adm-rec-priority ${priorityClass}`}>{priority || "低"}</div>
                    <div className="adm-rec-body">
                      <div className="adm-rec-title">{formatAdminText(rec.title)}</div>
                      <div className="adm-rec-detail">{formatAdminText(rec.detail)}</div>
                      <span className="adm-rec-action">{formatAdminText(rec.action)}</span>
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="adm-empty">暂无运营建议</div>
            )}
          </div>
        </div>

        {/* ── Admin Actions Panel ── */}
        <div className="adm-section adm-reveal">
          <h2 className="adm-section-title">
            <span className="adm-section-dot" style={{ background: "#14b8a6" }} />
            管理操作
          </h2>
          <div className="adm-actions-grid adm-reveal-stagger">
            {/* Knowledge Base Management */}
            <div className="adm-action-card adm-reveal-child" style={{ gridColumn: "1 / -1" }}>
              <h3 className="adm-action-title">
                <span className="adm-action-icon">&#x1F4DA;</span> 知识库管理
              </h3>
              <div className="adm-action-row" style={{ gap: 8, flexWrap: "wrap" }}>
                <div
                  className="adm-file-upload-area"
                  style={{ flex: "1 1 200px", minWidth: 180 }}
                  onClick={() => document.getElementById("adm-kb-file-input")?.click()}
                >
                  <div className="adm-upload-icon">&#x2B06;</div>
                  <p>点击上传知识文档</p>
                  <p className="adm-upload-hint">支持 .docx / .txt / .xlsx / .csv</p>
                </div>
                <input
                  id="adm-kb-file-input"
                  type="file"
                  accept=".docx,.txt,.xlsx,.csv"
                  style={{ display: "none" }}
                  onChange={(e) => setKbFile(e.target.files?.[0] || null)}
                />
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {kbFile && (
                    <span className="adm-tag adm-tag--ok">已选择: {kbFile.name}</span>
                  )}
                  <MagneticBtn
                    className="adm-btn adm-btn--amber adm-btn--sm"
                    onClick={handleKBUpload}
                    disabled={!kbFile || busy.kbUpload}
                  >
                    {busy.kbUpload ? "上传中..." : "上传文档"}
                  </MagneticBtn>
                  <MagneticBtn
                    className="adm-btn adm-btn--teal adm-btn--sm"
                    onClick={handleKBRebuild}
                    disabled={busy.kbRebuild}
                  >
                    {busy.kbRebuild ? "重建中..." : "重建向量库"}
                  </MagneticBtn>
                  {kbRebuildResult && (
                    <span className={`adm-tag ${kbRebuildResult.success ? "adm-tag--ok" : "adm-tag--err"}`}>
                      {kbRebuildResult.message}
                    </span>
                  )}
                </div>
              </div>
              <div className="adm-kb-doc-list" style={{ marginTop: 12 }}>
                {kbDocs.length === 0 ? (
                  <div className="adm-empty">暂无知识文档</div>
                ) : (
                  kbDocs.map((doc) => (
                    <div key={doc.name} className="adm-action-row" style={{ justifyContent: "space-between", padding: "4px 0" }}>
                      <span style={{ fontSize: "0.85rem" }}>
                        {doc.name}
                        <span className="adm-tag" style={{ marginLeft: 8, fontSize: "0.75rem" }}>
                          {(doc.size / 1024).toFixed(1)} KB
                        </span>
                      </span>
                      <MagneticBtn
                        className="adm-btn adm-btn--outline adm-btn--sm"
                        onClick={() => handleKBDelete(doc.name)}
                        disabled={busy.kbDelete === doc.name}
                        style={{ color: "#ef4444", borderColor: "#ef4444" }}
                      >
                        {busy.kbDelete === doc.name ? "删除中..." : "删除"}
                      </MagneticBtn>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Avatar Upload */}
            <div className="adm-action-card adm-reveal-child">
              <h3 className="adm-action-title">
                <span className="adm-action-icon">&#x1F4F7;</span> 数字人头像上传
              </h3>
              <div
                className="adm-file-upload-area"
                onClick={() => {
                  const input = document.getElementById("adm-avatar-file-input");
                  if (input) input.click();
                }}
              >
                <div className="adm-upload-icon">&#x2B06;</div>
                <p>点击上传数字人头像文件</p>
                <p className="adm-upload-hint">支持图片文件，最大 10 兆</p>
              </div>
              <input
                id="adm-avatar-file-input"
                type="file"
                accept="image/*"
                style={{ display: "none" }}
                onChange={(e) => setAvatarFile(e.target.files?.[0] || null)}
              />
              {avatarFile && (
                <div style={{ marginTop: 12 }}>
                  <span className="adm-tag adm-tag--ok">已选择: {avatarFile.name}</span>
                </div>
              )}
              <MagneticBtn
                className="adm-btn adm-btn--amber adm-btn--block"
                onClick={handleAvatarUpload}
                disabled={!avatarFile || busy.uploadAvatar}
                style={{ marginTop: 12 }}
              >
                {busy.uploadAvatar ? "上传中..." : "上传默认头像"}
              </MagneticBtn>
            </div>

            {/* Cache Refresh */}
            <div className="adm-action-card adm-reveal-child">
              <h3 className="adm-action-title">
                <span className="adm-action-icon">&#x1F504;</span> 缓存刷新
              </h3>
              <div className="adm-action-row">
                <div className="adm-action-label">当前状态</div>
                <div className="adm-action-value">
                  <span className={`adm-tag ${busy.cacheRefresh ? "adm-tag--warn" : "adm-tag--ok"}`}>
                    {busy.cacheRefresh ? "刷新中..." : "待刷新"}
                  </span>
                </div>
              </div>
              <div className="adm-action-row">
                <MagneticBtn
                  className="adm-btn adm-btn--amber adm-btn--sm"
                  onClick={handleCacheRefresh}
                  disabled={busy.cacheRefresh}
                >
                  刷新缓存
                </MagneticBtn>
              </div>
            </div>

            {/* Voice Management */}
            <div className="adm-action-card adm-reveal-child">
              <h3 className="adm-action-title">
                <span className="adm-action-icon">&#x1F3A4;</span> 语音管理
              </h3>
              <div className="adm-action-row">
                <div className="adm-action-label">当前语音</div>
                <div className="adm-action-value">
                  <span className="adm-tag adm-tag--ok">{formatVoiceName(currentVoice, voices)}</span>
                </div>
              </div>
              <div className="adm-voice-list">
                {voices.map((v) => (
                  <div
                    key={getVoiceId(v)}
                    className={`adm-voice-item ${currentVoice === getVoiceId(v) ? "adm-voice-item--active" : ""}`}
                  >
                    <div className="adm-voice-name">{v.name || "未命名音色"}</div>
                    <div className="adm-voice-id">音色来源：中文语音服务</div>
                    <MagneticBtn
                      className="adm-btn adm-btn--outline adm-btn--sm"
                      onClick={() => setCurrentVoice(getVoiceId(v))}
                      disabled={busy.saveVoice}
                    >
                      选择
                    </MagneticBtn>
                    <MagneticBtn
                      className="adm-btn adm-btn--teal adm-btn--sm"
                      onClick={() => {
                        const voiceId = getVoiceId(v);
                        setCurrentVoice(voiceId);
                        setBusy((prev) => ({ ...prev, previewVoice: true }));
                        setFeedback(null);
                        previewVoice(voiceId)
                          .then((result) => {
                            const audio = new Audio(result.audio_url);
                            audio.play();
                            setFeedback({ type: "info", message: "正在播放试听。" });
                          })
                          .catch((err) => setFeedback({ type: "danger", message: err.message }))
                          .finally(() => setBusy((prev) => ({ ...prev, previewVoice: false })));
                      }}
                      disabled={busy.previewVoice}
                    >
                      {busy.previewVoice ? "播放中..." : "试听"}
                    </MagneticBtn>
                  </div>
                ))}
              </div>
              <div className="adm-action-row" style={{ marginTop: 12 }}>
                <MagneticBtn
                  className="adm-btn adm-btn--amber adm-btn--sm"
                  onClick={handleVoiceSave}
                  disabled={busy.saveVoice || !currentVoice}
                >
                  {busy.saveVoice ? "保存中..." : "保存音色"}
                </MagneticBtn>
              </div>
            </div>

            {/* Avatar Runtime */}
            <div className="adm-action-card adm-reveal-child">
              <h3 className="adm-action-title">
                <span className="adm-action-icon">&#x1F916;</span> 数字人运行配置
              </h3>
              {avatarRuntime ? (
                <>
                  <div className="adm-action-row">
                    <div className="adm-action-label">当前配置</div>
                    <div className="adm-action-value">
                      <span className="adm-tag adm-tag--ok">
                        {formatProfileName(avatarRuntime.current_profile_id, avatarRuntime.profiles)}
                      </span>
                    </div>
                  </div>
                  <div className="adm-profile-list">
                    {avatarRuntime.profiles.map((p) => (
                      <div
                        key={p.id}
                        className={`adm-profile-item ${avatarRuntime.current_profile_id === p.id ? "adm-profile-item--active" : ""}`}
                      >
                        <div className="adm-profile-info">
                          <div className="adm-profile-label">{p.label}</div>
                          <div className="adm-profile-summary">{p.summary}</div>
                          <div className="adm-profile-meta">
                            {formatRuntimeText(p.description)} | 推理精度：{formatPrecision(p.torch_dtype)} | 预热时长：{p.warmup_seconds}秒
                          </div>
                        </div>
                        {avatarRuntime.current_profile_id === p.id ? (
                          <span className="adm-tag adm-tag--ok">当前</span>
                        ) : (
                          <MagneticBtn
                            className="adm-btn adm-btn--outline adm-btn--sm"
                            onClick={() => handleAvatarRuntimeChange(p.id)}
                            disabled={busy.avatarRuntime}
                          >
                            切换
                          </MagneticBtn>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="adm-empty">暂无运行时数据</div>
              )}
            </div>
          </div>
        </div>
      </div>

      <ProductFooter />
    </div>
  );
}
