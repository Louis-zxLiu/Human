import React, { useEffect, useMemo, useRef, useState } from "react";

import { ChatMessage } from "../components/ChatMessage";
import { HistoryRail } from "../components/HistoryRail";
import { StatusBadge } from "../components/StatusBadge";
import {
  archiveActiveSessions,
  createActiveSession,
  deleteChatSession,
  getArchivedSessions,
  persistActiveSession,
  renameChatSession,
  saveChatSession,
  summarizeMessages,
} from "../lib/chatArchives";
import {
  buildAudioMessageForm,
  buildTextMessageForm,
  getInteractStreamUrl,
  logout,
  sendAudioMessage,
  sendTextMessage,
} from "../lib/api";
import { buildLoginHref, buildPlannerHref, buildScenicHref } from "../lib/routes";
import { AgentGraphCard } from "../components/AgentGraphCard";

const AUTH_KEYS = ["auth_token", "username", "user_role"];
const LINGSHAN_QUICK_PROMPTS = [
  "我第一次来，帮我推荐 90 分钟游览路线",
  "我现在在梵宫附近，下一站适合去哪里",
  "灵山大佛的历史背景是什么",
];
const NIANHUAWAN_QUICK_PROMPTS = [
  "如果第一次来拈花湾，适合怎么逛？",
  "为什么拈花湾适合夜游和慢游？",
  "我现在在花街附近，下一站适合去哪里？",
];
const LINGSHAN_DEMO_ROUTES = [
  {
    label: "历史文化",
    title: "祥符禅寺 -> 灵山大佛 -> 灵山梵宫",
    duration: "约 2.5-3.5 小时",
    prompt: "我是历史文化爱好者，请给我一条灵山胜境深度讲解路线，并说明每个节点讲什么。",
    focus: "玄奘渊源、五方五佛、梵宫佛教艺术",
    behavior: "结合历史文化类与展馆类游客停留和满意度偏好。",
  },
  {
    label: "亲子家庭",
    title: "百子戏弥勒 -> 九龙灌浴 -> 佛教文化博览馆 -> 灵山大佛",
    duration: "约 2.5-3 小时",
    prompt: "我们带孩子来玩，请推荐一条亲子友好的路线，要有互动点和讲解重点。",
    focus: "吉祥寓意、动态表演、轻知识讲解",
    behavior: "优先选择更易互动、节奏舒缓的节点。",
  },
  {
    label: "自然风光",
    title: "五明桥 -> 菩提大道 -> 灵山大佛 -> 五印坛城",
    duration: "约 2-3 小时",
    prompt: "我喜欢自然风光和拍照打卡，请推荐一条适合拍照的路线，并说明为什么适合多数游客。",
    focus: "太湖视野、中轴线取景、佛像远景",
    behavior: "结合风景名胜与休闲度假类游客偏好。",
  },
];
const NIANHUAWAN_DEMO_ROUTES = [
  {
    label: "夜游慢行",
    title: "香月花街 -> 五灯湖 -> 鹿鸣谷",
    duration: "约 1.5-2.5 小时",
    prompt: "我想在拈花湾慢慢逛，请给我一条适合夜游和放松的路线，并说明每一站看什么。",
    focus: "夜景灯影、街区漫游、山谷静修",
    behavior: "优先保留停留感与氛围感，不把路线压成赶场式快走。",
  },
  {
    label: "禅意文化",
    title: "拈花广场 -> 香月花街 -> 拈花堂 -> 五灯湖",
    duration: "约 2-3 小时",
    prompt: "我更想感受拈花湾的禅意文化和建筑氛围，请推荐一条路线并说明讲解重点。",
    focus: "唐风街区、禅意空间、夜间演艺",
    behavior: "适合文化体验与较完整的街区讲解。",
  },
  {
    label: "花海亲子",
    title: "拈花广场 -> 梵天花海 -> 五灯湖 -> 香月花街",
    duration: "约 2-3 小时",
    prompt: "我们带孩子来拈花湾放松，请推荐一条轻松好走、适合拍照和休息的路线。",
    focus: "花海、水岸、开阔步行空间",
    behavior: "优先保留可停留、可拍照、可中途休息的节点。",
  },
];
const PROCESS_STAGE_ORDER = ["idle", "heard", "retrieving", "generating", "avatar", "done"];
const PROCESS_STAGES = [
  { key: "heard", title: "听懂游客意图", detail: "识别文本或语音输入，锁定本轮问题。" },
  { key: "retrieving", title: "检索可信资料", detail: "按意图访问 DOCX 知识库、行为数据或路线融合链路。" },
  { key: "generating", title: "生成讲解回答", detail: "组织事实证据、路线节点和游客可听懂的讲解。" },
  { key: "avatar", title: "数字人出镜", detail: "合成语音和口型视频，形成稳定的多模态反馈。" },
];
const STREAMING_FRAME_INTERVAL_MS = 40;
const MIN_RECORDING_MS = 600;
const MIN_AUDIO_BYTES = 2048;
const AUDIO_MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
];
const AUDIO_CAPTURE_CONSTRAINTS = {
  audio: {
    channelCount: 1,
    sampleRate: 48000,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
};

function buildGreetingMessage(guideContext = {}) {
  const scenicName = guideContext.scenicName || "灵山胜境";
  const attractionName = guideContext.attractionName || "";
  const routeTitle = guideContext.routeTitle || guideContext.routeLabel || "";
  const scenicGreeting = scenicName.includes("拈花湾")
    ? "你好，我是拈花湾数字人导游。你可以围绕夜游、慢游、花海、街区和禅意体验继续提问。"
    : "你好，我是灵山胜境数字人导游。你可以问我景点事实、路线推荐，也可以在弱 GPS 模式下体验多轮问路。";
  const contextCopy = attractionName
    ? `当前已带入景点语境：${attractionName}。`
    : routeTitle
      ? `当前已带入路线语境：${routeTitle}。`
      : "";
  return {
    role: "assistant",
    content: `${scenicGreeting}${contextCopy}`,
    meta: null,
  };
}

function guidePromptsForContext(guideContext = {}) {
  const scenicSlug = guideContext.scenicSlug || "lingshan-shengjing";
  if (scenicSlug === "nianhuawan") {
    return { quickPrompts: NIANHUAWAN_QUICK_PROMPTS, demoRoutes: NIANHUAWAN_DEMO_ROUTES };
  }
  return { quickPrompts: LINGSHAN_QUICK_PROMPTS, demoRoutes: LINGSHAN_DEMO_ROUTES };
}

const PRESET_ROUTE_KEYS_BY_SCENIC = {
  "lingshan-shengjing": ["lingshan-history", "lingshan-family", "lingshan-nature"],
  nianhuawan: ["nianhuawan-night", "nianhuawan-culture", "nianhuawan-family"],
};

function findPresetRouteMatch(text, scenicSlug) {
  const normalizedText = String(text || "").trim();
  if (!normalizedText) return null;

  const scenicKey = scenicSlug === "nianhuawan" ? "nianhuawan" : "lingshan-shengjing";
  const scenicRoutes = scenicKey === "nianhuawan" ? NIANHUAWAN_DEMO_ROUTES : LINGSHAN_DEMO_ROUTES;
  const routeKeys = PRESET_ROUTE_KEYS_BY_SCENIC[scenicKey] || [];
  const matchedIndex = scenicRoutes.findIndex((route) => route.prompt === normalizedText);

  if (matchedIndex === -1 || !routeKeys[matchedIndex]) return null;
  return { presetRouteKey: routeKeys[matchedIndex] };
}

function buildCurrentSessionDisplay(currentSession, messages) {
  const summary = summarizeMessages(messages);
  const hasUserMessage = messages.some((message) => message.role === "user" && message.content.trim());

  if (!hasUserMessage && !currentSession.titlePinned) {
    return {
      title: "当前新会话",
      preview: "从这里开始这一轮新的对话，旧会话会自动进入左侧归档。",
    };
  }

  return {
    title: currentSession.title || summary.title,
    preview: summary.preview || "这轮会话已建立，还没有新的摘要。",
  };
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",")[1] : result);
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

function getSupportedAudioMimeType() {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return "";
  }
  return AUDIO_MIME_CANDIDATES.find((mimeType) => MediaRecorder.isTypeSupported(mimeType)) || "";
}

function base64ToBlobUrl(base64, mimeType) {
  const binary = window.atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return URL.createObjectURL(new Blob([bytes], { type: mimeType }));
}

export function VisitorApp({ guideContext = {}, embedded = false, productTone = false }) {
  const username = localStorage.getItem("username") || "游客";
  const role = localStorage.getItem("user_role") || "user";
  const activeGuideContext = useMemo(() => ({
    scenicSlug: guideContext.scenicSlug || "lingshan-shengjing",
    scenicName: guideContext.scenicName || "灵山胜境",
    attractionId: guideContext.attractionId || "",
    attractionName: guideContext.attractionName || "",
    routeLabel: guideContext.routeLabel || "",
    routeTitle: guideContext.routeTitle || "",
    prompt: guideContext.prompt || "",
  }), [
    guideContext.attractionId,
    guideContext.attractionName,
    guideContext.prompt,
    guideContext.routeLabel,
    guideContext.routeTitle,
    guideContext.scenicName,
    guideContext.scenicSlug,
  ]);
  const initialGreetingMessage = useMemo(() => buildGreetingMessage(activeGuideContext), [activeGuideContext]);
  const { quickPrompts, demoRoutes } = useMemo(() => guidePromptsForContext(activeGuideContext), [activeGuideContext]);
  const guideModeLabel = activeGuideContext.attractionName
    ? "景点讲解"
    : activeGuideContext.routeTitle || activeGuideContext.routeLabel
      ? "路线导览"
      : "自由问答";

  const [messages, setMessages] = useState([initialGreetingMessage]);
  const [inputText, setInputText] = useState(activeGuideContext.prompt || "");
  const [isGpsWeak, setIsGpsWeak] = useState(localStorage.getItem("gps_weak_mode") === "true");
  const [isRealtimeMode, setIsRealtimeMode] = useState(localStorage.getItem("realtime_demo_mode") !== "false");
  const [loading, setLoading] = useState(false);
  const [processStage, setProcessStage] = useState("idle");
  const [activeQuestion, setActiveQuestion] = useState("");
  const [videoUrl, setVideoUrl] = useState("");
  const [streamFrameUrl, setStreamFrameUrl] = useState("");
  const [streamNotice, setStreamNotice] = useState("");
  const [avatarImageVersion, setAvatarImageVersion] = useState(() => Date.now());
  const [isRecording, setIsRecording] = useState(false);
  const [archives, setArchives] = useState([]);
  const [selectedArchiveId, setSelectedArchiveId] = useState(null);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [currentSession, setCurrentSession] = useState(() => createActiveSession(username, [initialGreetingMessage]));
  const [editingSessionId, setEditingSessionId] = useState(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [isSessionMenuOpen, setIsSessionMenuOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [isPresetOpen, setIsPresetOpen] = useState(false);
  const [agentNodes, setAgentNodes] = useState([]);
  const [isAgentGraphExpanded, setIsAgentGraphExpanded] = useState(true);
  const [agentElapsedMs, setAgentElapsedMs] = useState(0);
  const [pendingReviewLogId, setPendingReviewLogId] = useState(null);

  const currentSessionRef = useRef(currentSession);
  const chatRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const stageTimersRef = useRef([]);
  const streamFrameQueueRef = useRef([]);
  const streamFrameTimerRef = useRef(null);
  const streamAudioUrlsRef = useRef([]);
  const streamAudioQueueRef = useRef([]);
  const streamAudioCurrentRef = useRef(null);
  const streamAudioPlayingRef = useRef(false);
  const messagesRef = useRef(messages);
  const recordingStartedAtRef = useRef(0);
  const agentStartTimeRef = useRef(null);
  const agentElapsedTimerRef = useRef(null);
  const pendingReviewTimerRef = useRef(null);
  const pendingReviewVideoRef = useRef(null);  // stores video_stream_url for after review
  const stableAgentTimersRef = useRef([]);      // timers for stable-path node animation

  useEffect(() => {
    currentSessionRef.current = currentSession;
  }, [currentSession]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => () => {
    stageTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    if (streamFrameTimerRef.current) {
      window.clearInterval(streamFrameTimerRef.current);
    }
    if (streamAudioCurrentRef.current) {
      streamAudioCurrentRef.current.pause();
      streamAudioCurrentRef.current = null;
    }
    streamAudioUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    if (agentElapsedTimerRef.current) clearInterval(agentElapsedTimerRef.current);
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setAvatarImageVersion(Date.now());
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const selectedArchive = archives.find((item) => item.id === selectedArchiveId) || null;
  const isArchiveView = Boolean(selectedArchive);
  const transcriptMessages = isArchiveView ? selectedArchive.messages : messages;
  const currentDisplay = useMemo(
    () => buildCurrentSessionDisplay(currentSession, messages),
    [currentSession, messages],
  );
  const managedSession = isArchiveView ? selectedArchive : currentSession;

  useEffect(() => {
    const token = localStorage.getItem("auth_token");
    if (!token) {
      window.location.href = buildLoginHref(`${window.location.pathname}${window.location.search || ""}`);
      return;
    }

    const storedSessions = archiveActiveSessions(username);
    setArchives(getArchivedSessions(username, storedSessions));
    setCurrentSession(createActiveSession(username, [initialGreetingMessage]));
    setMessages([initialGreetingMessage]);
    setInputText(activeGuideContext.prompt || "");
  }, [initialGreetingMessage, username]);

  useEffect(() => {
    if (selectedArchiveId && !archives.some((archive) => archive.id === selectedArchiveId)) {
      setSelectedArchiveId(null);
    }
  }, [archives, selectedArchiveId]);

  useEffect(() => {
    if (editingSessionId && managedSession?.id !== editingSessionId) {
      setEditingSessionId(null);
      setDraftTitle("");
    }
  }, [editingSessionId, managedSession]);

  useEffect(() => {
    setIsSessionMenuOpen(false);
  }, [selectedArchiveId]);

  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [transcriptMessages, loading, selectedArchiveId]);

  function syncArchivedSessions(sessions) {
    setArchives(getArchivedSessions(username, sessions));
  }

  function persistMessages(nextMessages) {
    const { session, sessions } = persistActiveSession(username, currentSessionRef.current, nextMessages);
    setCurrentSession(session);
    syncArchivedSessions(sessions);
  }

  function resetLiveSession() {
    const freshSession = createActiveSession(username, [initialGreetingMessage]);
    setCurrentSession(freshSession);
    setMessages([initialGreetingMessage]);
    setSelectedArchiveId(null);
    setEditingSessionId(null);
    setPendingDelete(null);
    setDraftTitle("");
    setInputText("");
    setVideoUrl("");
    resetStreamingMedia();
    setLoading(false);
    setProcessStage("idle");
    setActiveQuestion("");
  }

  function updateVideoFromResult(result) {
    resetStreamingMedia();
    if (result.video_stream_url) {
      setVideoUrl(`${result.video_stream_url}?t=${Date.now()}`);
    }
  }

  function resetStreamingMedia() {
    if (streamFrameTimerRef.current) {
      window.clearInterval(streamFrameTimerRef.current);
      streamFrameTimerRef.current = null;
    }
    streamFrameQueueRef.current = [];
    if (streamAudioCurrentRef.current) {
      streamAudioCurrentRef.current.onended = null;
      streamAudioCurrentRef.current.onerror = null;
      streamAudioCurrentRef.current.pause();
      streamAudioCurrentRef.current = null;
    }
    streamAudioQueueRef.current = [];
    streamAudioPlayingRef.current = false;
    streamAudioUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    streamAudioUrlsRef.current = [];
    setStreamFrameUrl("");
    setStreamNotice("");
  }

  function pumpStreamingFrames() {
    if (streamFrameTimerRef.current) return;
    streamFrameTimerRef.current = window.setInterval(() => {
      const nextFrame = streamFrameQueueRef.current.shift();
      if (!nextFrame) {
        window.clearInterval(streamFrameTimerRef.current);
        streamFrameTimerRef.current = null;
        return;
      }
      setStreamFrameUrl(nextFrame);
    }, STREAMING_FRAME_INTERVAL_MS);
  }

  function enqueueStreamingFrames(frames = []) {
    if (!frames.length) return;
    setVideoUrl("");
    streamFrameQueueRef.current.push(...frames.map((frame) => `data:image/jpeg;base64,${frame}`));
    pumpStreamingFrames();
  }

  function revokeStreamingAudioUrl(audioUrl) {
    URL.revokeObjectURL(audioUrl);
    streamAudioUrlsRef.current = streamAudioUrlsRef.current.filter((url) => url !== audioUrl);
  }

  async function drainStreamingAudioQueue() {
    if (streamAudioPlayingRef.current) return;
    const audioUrl = streamAudioQueueRef.current.shift();
    if (!audioUrl) return;

    streamAudioPlayingRef.current = true;
    const audio = new Audio(audioUrl);
    audio.preload = "auto";
    streamAudioCurrentRef.current = audio;

    try {
      await new Promise((resolve, reject) => {
        audio.onended = resolve;
        audio.onerror = reject;
        const playPromise = audio.play();
        if (playPromise && typeof playPromise.catch === "function") {
          playPromise.catch(reject);
        }
      });
    } catch {
      setStreamNotice("浏览器拦截了自动播放，点击数字人舞台上的音频控件可继续听取。");
    } finally {
      audio.onended = null;
      audio.onerror = null;
      if (streamAudioCurrentRef.current === audio) {
        streamAudioCurrentRef.current = null;
      }
      revokeStreamingAudioUrl(audioUrl);
      streamAudioPlayingRef.current = false;
      drainStreamingAudioQueue();
    }
  }

  async function playStreamingAudio(audioBase64) {
    if (!audioBase64) return;
    const audioUrl = base64ToBlobUrl(audioBase64, "audio/mpeg");
    streamAudioUrlsRef.current.push(audioUrl);
    streamAudioQueueRef.current.push(audioUrl);
    drainStreamingAudioQueue();
  }

  function clearStageTimers() {
    stageTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    stageTimersRef.current = [];
  }

  function resetAgentNodes() {
    setAgentNodes([]);
    agentStartTimeRef.current = Date.now();
    if (agentElapsedTimerRef.current) clearInterval(agentElapsedTimerRef.current);
    agentElapsedTimerRef.current = setInterval(() => {
      setAgentElapsedMs(Date.now() - (agentStartTimeRef.current || Date.now()));
    }, 100);
  }

  function stopAgentTimer() {
    if (agentElapsedTimerRef.current) {
      clearInterval(agentElapsedTimerRef.current);
      agentElapsedTimerRef.current = null;
    }
  }

  // 稳定链路（HTTP）没有 WS agent_node 事件，用定时器模拟节点动画
  // 节点按实际执行顺序依次 running→done，间隔根据典型耗时估算
  const STABLE_NODE_SEQUENCE = [
    { node: "planner",           label: "意图解析",  delay: 0,    duration: 500  },
    { node: "fast_answer",       label: "快速回答",  delay: 0,    duration: 400  },
    { node: "tool_dispatch",     label: "工具调度",  delay: 500,  duration: 400  },
    { node: "tool_execute",      label: "工具执行",  delay: 900,  duration: 1200 },
    { node: "agent_loop_decide", label: "循环决策",  delay: 2100, duration: 300  },
    { node: "synthesize",        label: "综合生成",  delay: 2400, duration: 800  },
    { node: "review",            label: "质量审核",  delay: 3200, duration: 400  },
    { node: "repair_execute",    label: "修复执行",  delay: 3200, duration: 400  },
    { node: "finalize",          label: "最终输出",  delay: 3600, duration: 300  },
  ];

  function startStableAgentAnimation() {
    // 清掉上次残留
    stableAgentTimersRef.current.forEach(clearTimeout);
    stableAgentTimersRef.current = [];
    setAgentNodes([]);

    STABLE_NODE_SEQUENCE.forEach(({ node, label, delay, duration }) => {
      const t1 = setTimeout(() => {
        setAgentNodes((prev) => {
          const exists = prev.find(n => n.node === node);
          if (exists) return prev.map(n => n.node === node ? { ...n, status: "running" } : n);
          return [...prev, { node, label, status: "running" }];
        });
      }, delay);
      const t2 = setTimeout(() => {
        setAgentNodes((prev) => prev.map(n => n.node === node ? { ...n, status: "done" } : n));
      }, delay + duration);
      stableAgentTimersRef.current.push(t1, t2);
    });
  }

  function stopStableAgentAnimation() {
    stableAgentTimersRef.current.forEach(clearTimeout);
    stableAgentTimersRef.current = [];
  }

  function clearPendingReviewPoller() {
    if (pendingReviewTimerRef.current) {
      clearInterval(pendingReviewTimerRef.current);
      pendingReviewTimerRef.current = null;
    }
  }

  function startPendingReviewPoller(logId, assistantIndex) {
    clearPendingReviewPoller();
    setPendingReviewLogId(logId);
    const token = localStorage.getItem("auth_token");
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    let attempts = 0;
    pendingReviewTimerRef.current = setInterval(async () => {
      attempts += 1;
      // Stop polling after 10 minutes (120 × 5s)
      if (attempts > 120) {
        clearPendingReviewPoller();
        setPendingReviewLogId(null);
        updateAssistantMessage(assistantIndex, {
          content: "⚠️ 本条回复需人工审核，审核超时，请稍后重试。",
          meta: null,
        }, true);
        return;
      }
      try {
        const res = await fetch(`/api/v1/interact/review/${logId}`, { headers });
        if (!res.ok) return;
        const data = await res.json();
        if (data.review_status === "approved") {
          clearPendingReviewPoller();
          setPendingReviewLogId(null);
          updateAssistantMessage(assistantIndex, {
            content: data.answer,
            meta: null,
          }, true);
          // 审核通过后启动数字人（如果原始响应有视频URL）
          const videoUrl = pendingReviewVideoRef.current;
          if (videoUrl) {
            pendingReviewVideoRef.current = null;
            updateVideoFromResult({ video_stream_url: videoUrl });
            completeProcessing({ video_stream_url: videoUrl });
          }
        } else if (data.review_status === "rejected") {
          clearPendingReviewPoller();
          setPendingReviewLogId(null);
          pendingReviewVideoRef.current = null;
          updateAssistantMessage(assistantIndex, {
            content: "抱歉，本条回复已被系统审核拒绝，请换一种方式提问。",
            meta: null,
          }, true);
        }
      } catch {
        // network hiccup — retry next tick
      }
    }, 5000);
  }

  function scheduleProcessingStages(question, startStage = "heard") {
    resetAgentNodes();
    clearStageTimers();
    setActiveQuestion(question);
    setProcessStage(startStage);
    const plan = startStage === "heard"
      ? [
          ["retrieving", 700],
          ["generating", 1600],
        ]
      : [
          ["generating", 900],
        ];
    stageTimersRef.current = plan.map(([stage, delay]) => window.setTimeout(() => setProcessStage(stage), delay));
  }

  function completeProcessing(result) {
    clearStageTimers();
    setProcessStage(result.video_stream_url ? "avatar" : "done");
    stageTimersRef.current = [window.setTimeout(() => setProcessStage("done"), 1800)];
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

  function replaceMessagesAndPersist(nextMessages) {
    setMessages(nextMessages);
    persistMessages(nextMessages);
  }

  function updateAssistantMessage(index, patch, shouldPersist = false) {
    setMessages((previous) => {
      const updatedMessages = previous.map((message, messageIndex) => (
        messageIndex === index ? { ...message, ...patch } : message
      ));
      if (shouldPersist) {
        persistMessages(updatedMessages);
      }
      return updatedMessages;
    });
  }

  async function runStableTextMessage(normalizedText, options = {}) {
    const formData = buildTextMessageForm({
      text: normalizedText,
      gpsStatus: isGpsWeak ? "weak" : "normal",
      clientSessionId: currentSessionRef.current.id,
      scenicSlug: activeGuideContext.scenicSlug,
      attractionId: activeGuideContext.attractionId,
      routeLabel: activeGuideContext.routeTitle || activeGuideContext.routeLabel,
      presetRouteKey: options.presetRouteKey || "",
      conversationContext: messagesRef.current.slice(-6),
    });

    // 稳定链路：启动模拟节点动画（HTTP 没有 WS agent_node 事件）
    resetAgentNodes();
    startStableAgentAnimation();

    const result = await sendTextMessage(formData);

    // 请求完成，立即把所有模拟节点标为 done
    stopStableAgentAnimation();
    setAgentNodes(STABLE_NODE_SEQUENCE.map(({ node, label }) => ({ node, label, status: "done" })));

    const reviewStatus = result.review_status || "auto";
    const logId = result.log_id || null;

    if (reviewStatus === "pending" && logId) {
      const assistantIndex = messagesRef.current.length;
      // 保存视频URL，审核通过后启动数字人
      pendingReviewVideoRef.current = result.video_stream_url || null;
      setMessages((previous) => {
        const updatedMessages = [
          ...previous,
          { role: "assistant", content: "⏳ 本条回复正在人工审核中，审核通过后将自动显示…", meta: null },
        ];
        persistMessages(updatedMessages);
        return updatedMessages;
      });
      completeProcessing(result);
      stopAgentTimer();
      startPendingReviewPoller(logId, assistantIndex);
      return;
    }

    setMessages((previous) => {
      const updatedMessages = [
        ...previous,
        { role: "assistant", content: result.assistant_text, meta: result.rag_metadata || null },
      ];
      persistMessages(updatedMessages);
      return updatedMessages;
    });
    updateVideoFromResult(result);
    completeProcessing(result);
    stopAgentTimer();
  }

  async function runRealtimeInteraction(payload, options = {}) {
    const { baseMessages, appendRecognizedUser = false } = options;
    resetStreamingMedia();
    setStreamNotice("实时流式链路连接中...");

    return new Promise((resolve, reject) => {
      const socket = new WebSocket(getInteractStreamUrl());
      let assistantIndex = appendRecognizedUser ? null : baseMessages.length;
      let workingMessages = baseMessages;
      let assistantText = "";
      let opened = false;
      let receivedAny = false;
      let streamedMedia = false;
      let settled = false;

      const closeSocket = () => {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onerror = null;
        socket.onclose = null;
        if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
          socket.close();
        }
      };

      const ensureAssistantPlaceholder = () => {
        if (assistantIndex !== null) return;
        assistantIndex = workingMessages.length;
        workingMessages = [...workingMessages, { role: "assistant", content: "", meta: null }];
        setMessages(workingMessages);
      };

      const failBeforeStreaming = (message) => {
        if (settled) return;
        settled = true;
        closeSocket();
        setStreamNotice("实时流式链路暂不可用，正在切换到稳定 MP4 模式。");
        reject(new Error(message));
      };

      socket.onopen = () => {
        opened = true;
        if (!appendRecognizedUser) {
          workingMessages = [...baseMessages, { role: "assistant", content: "", meta: null }];
          replaceMessagesAndPersist(workingMessages);
        }
        socket.send(JSON.stringify({
          ...payload,
          gps_status: isGpsWeak ? "weak" : "normal",
          client_session_id: currentSessionRef.current.id,
          scenicSlug: activeGuideContext.scenicSlug,
          attractionId: activeGuideContext.attractionId,
          routeLabel: activeGuideContext.routeTitle || activeGuideContext.routeLabel,
          presetRouteKey: options.presetRouteKey || "",
          conversation_context: baseMessages.slice(-6),
        }));
        setStreamNotice("实时链路已连接，正在分段生成文本、语音和数字人画面。");
      };

      socket.onmessage = async (event) => {
        receivedAny = true;
        let message;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }

        if (message.type === "error") {
          settled = true;
          closeSocket();
          reject(new Error(message.message || "实时链路返回错误"));
          return;
        }

        if (message.type === "text_user" && appendRecognizedUser) {
          const recognizedText = message.text || "语音提问";
          setActiveQuestion(recognizedText);
          workingMessages = [...baseMessages, { role: "user", content: recognizedText, meta: null }];
          assistantIndex = workingMessages.length;
          workingMessages = [...workingMessages, { role: "assistant", content: "", meta: null }];
          replaceMessagesAndPersist(workingMessages);
          return;
        }

        if (message.type === "agent_node") {
          const { node, label, status } = message;
          setAgentNodes((prev) => {
            const existing = prev.find((n) => n.node === node);
            if (existing) {
              return prev.map((n) => (n.node === node ? { ...n, status } : n));
            }
            return [...prev, { node, label: label || node, status }];
          });
          return;
        }

        if (message.type === "text_token") {
          ensureAssistantPlaceholder();
          assistantText += message.text || "";
          updateAssistantMessage(assistantIndex, { content: assistantText });
          setProcessStage("generating");
          return;
        }

        if (message.type === "chunk") {
          setProcessStage("avatar");
          const frames = message.frames || [];
          streamedMedia = streamedMedia || frames.length > 0;
          enqueueStreamingFrames(frames);
          await playStreamingAudio(message.audio);
          return;
        }

        if (message.type === "done") {
          ensureAssistantPlaceholder();
          const finalText = message.full_text || assistantText;
          const reviewStatus = message.review_status || "auto";
          const logId = message.log_id || null;

          if (reviewStatus === "pending" && logId) {
            updateAssistantMessage(
              assistantIndex,
              { content: "⏳ 本条回复正在人工审核中，审核通过后将自动显示…", meta: null },
              true,
            );
            setStreamNotice("回复已提交人工审核，请稍候。");
            completeProcessing({ video_stream_url: "__stream__" });
            stopAgentTimer();
            settled = true;
            closeSocket();
            startPendingReviewPoller(logId, assistantIndex);
            resolve(message);
            return;
          }

          updateAssistantMessage(
            assistantIndex,
            { content: finalText, meta: message.rag_metadata || null },
            true,
          );
          setStreamNotice("实时流式回答完成。");
          if (!streamedMedia) {
            // 纯文字流模式：没有 chunk 媒体帧，用 video_stream_url 启动数字人
            updateVideoFromResult(message);
          }
          completeProcessing(message);
          stopAgentTimer();
          settled = true;
          closeSocket();
          resolve(message);
        }
      };

      socket.onerror = () => {
        if (settled) return;
        if (!opened || !receivedAny) {
          failBeforeStreaming("实时 WebSocket 连接失败");
          return;
        }
        settled = true;
        closeSocket();
        reject(new Error("实时 WebSocket 中断"));
      };

      socket.onclose = () => {
        if (settled) return;
        if (!opened || !receivedAny) {
          failBeforeStreaming("实时 WebSocket 未能建立连接");
          return;
        }
        settled = true;
        reject(new Error("实时 WebSocket 提前关闭"));
      };
    });
  }

  async function submitTextMessage(text, options = {}) {
    if (!text.trim() || loading || isArchiveView) return;

    const normalizedText = text.trim();
    const presetRouteMatch = options.presetRouteKey
      ? { presetRouteKey: options.presetRouteKey }
      : findPresetRouteMatch(normalizedText, activeGuideContext.scenicSlug);
    const presetRouteKey = presetRouteMatch?.presetRouteKey || "";
    setInputText("");
    scheduleProcessingStages(normalizedText);

    const nextMessages = [...messages, { role: "user", content: normalizedText, meta: null }];
    replaceMessagesAndPersist(nextMessages);
    setLoading(true);

    try {
      if (presetRouteKey) {
        await runStableTextMessage(normalizedText, { presetRouteKey });
      } else if (isRealtimeMode) {
        try {
          await runRealtimeInteraction(
            { text: normalizedText },
            { baseMessages: nextMessages, presetRouteKey },
          );
        } catch {
          replaceMessagesAndPersist(nextMessages);
          await runStableTextMessage(normalizedText, { presetRouteKey });
        }
      } else {
        await runStableTextMessage(normalizedText, { presetRouteKey });
      }
    } catch (err) {
      clearStageTimers();
      stopAgentTimer();
      setProcessStage("done");
      setMessages((previous) => {
        const updatedMessages = [
          ...previous,
          { role: "assistant", content: `[系统错误] ${err.message}`, meta: null },
        ];
        persistMessages(updatedMessages);
        return updatedMessages;
      });
    } finally {
      setLoading(false);
    }
  }

  async function handleSendText() {
    await submitTextMessage(inputText);
  }

  async function ensureRecorder() {
    if (mediaRecorderRef.current) return;

    const stream = await navigator.mediaDevices.getUserMedia(AUDIO_CAPTURE_CONSTRAINTS);
    const mimeType = getSupportedAudioMimeType();
    mediaRecorderRef.current = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    mediaRecorderRef.current.ondataavailable = (event) => {
      if (event.data.size > 0) {
        audioChunksRef.current.push(event.data);
      }
    };
    mediaRecorderRef.current.onstop = async () => {
      const recordingMimeType = mediaRecorderRef.current?.mimeType || mimeType || "audio/webm";
      const blob = new Blob(audioChunksRef.current, { type: recordingMimeType });
      audioChunksRef.current = [];
      const recordingDurationMs = Date.now() - recordingStartedAtRef.current;
      recordingStartedAtRef.current = 0;
      if (recordingDurationMs < MIN_RECORDING_MS || blob.size < MIN_AUDIO_BYTES) {
        setIsRecording(false);
        clearStageTimers();
        setProcessStage("done");
        setActiveQuestion("语音太短，请按住后说完整问题。");
        return;
      }
      setLoading(true);
      scheduleProcessingStages("正在识别语音输入...", "retrieving");

      try {
        if (isRealtimeMode) {
          try {
            const audioBase64 = await blobToBase64(blob);
            await runRealtimeInteraction(
              { audio: audioBase64 },
              { baseMessages: messagesRef.current, appendRecognizedUser: true },
            );
          } catch {
            const formData = buildAudioMessageForm({
              audioFile: new File([blob], "voice.webm", { type: recordingMimeType }),
              gpsStatus: isGpsWeak ? "weak" : "normal",
              clientSessionId: currentSessionRef.current.id,
              scenicSlug: activeGuideContext.scenicSlug,
              attractionId: activeGuideContext.attractionId,
              routeLabel: activeGuideContext.routeTitle || activeGuideContext.routeLabel,
              conversationContext: messagesRef.current.slice(-6),
            });
            const result = await sendAudioMessage(formData);
            setActiveQuestion(result.user_text || "语音提问");

            setMessages((previous) => {
              const updatedMessages = [
                ...previous,
                { role: "user", content: result.user_text, meta: null },
                { role: "assistant", content: result.assistant_text, meta: result.rag_metadata || null },
              ];
              persistMessages(updatedMessages);
              return updatedMessages;
            });
            updateVideoFromResult(result);
            completeProcessing(result);
            stopAgentTimer();
          }
        } else {
          const formData = buildAudioMessageForm({
            audioFile: new File([blob], "voice.webm", { type: recordingMimeType }),
            gpsStatus: isGpsWeak ? "weak" : "normal",
            clientSessionId: currentSessionRef.current.id,
            scenicSlug: activeGuideContext.scenicSlug,
            attractionId: activeGuideContext.attractionId,
            routeLabel: activeGuideContext.routeTitle || activeGuideContext.routeLabel,
            conversationContext: messagesRef.current.slice(-6),
          });
          const result = await sendAudioMessage(formData);
          setActiveQuestion(result.user_text || "语音提问");

          setMessages((previous) => {
            const updatedMessages = [
              ...previous,
              { role: "user", content: result.user_text, meta: null },
              { role: "assistant", content: result.assistant_text, meta: result.rag_metadata || null },
            ];
            persistMessages(updatedMessages);
            return updatedMessages;
          });
          updateVideoFromResult(result);
          completeProcessing(result);
          stopAgentTimer();
        }
      } catch (err) {
        clearStageTimers();
        stopAgentTimer();
        setProcessStage("done");
        setMessages((previous) => {
          const updatedMessages = [
            ...previous,
            { role: "assistant", content: `[系统错误] ${err.message}`, meta: null },
          ];
          persistMessages(updatedMessages);
          return updatedMessages;
        });
      } finally {
        setLoading(false);
      }
    };
  }

  async function startRecording() {
    if (loading || isArchiveView) return;

    try {
      await ensureRecorder();
      setActiveQuestion("正在聆听语音提问...");
      setProcessStage("heard");
      setIsRecording(true);
      audioChunksRef.current = [];
      recordingStartedAtRef.current = Date.now();
      mediaRecorderRef.current.start(250);
    } catch (err) {
      setMessages((previous) => {
        const updatedMessages = [
          ...previous,
          { role: "assistant", content: `[系统错误] ${err.message}`, meta: null },
        ];
        persistMessages(updatedMessages);
        return updatedMessages;
      });
    }
  }

  function stopRecording() {
    if (mediaRecorderRef.current && isRecording) {
      setIsRecording(false);
      mediaRecorderRef.current.stop();
    }
  }

  function toggleGps() {
    if (isArchiveView) return;
    const nextValue = !isGpsWeak;
    setIsGpsWeak(nextValue);
    localStorage.setItem("gps_weak_mode", String(nextValue));
  }

  function toggleRealtimeMode() {
    if (loading || isArchiveView) return;
    const nextValue = !isRealtimeMode;
    setIsRealtimeMode(nextValue);
    localStorage.setItem("realtime_demo_mode", String(nextValue));
    setStreamNotice(nextValue ? "已切换到实时生成模式。" : "已切换到稳定 MP4 回退模式。");
  }

  function beginRenameSession(session, fallbackTitle) {
    setIsSessionMenuOpen(false);
    setEditingSessionId(session.id);
    setDraftTitle(session.titlePinned ? session.title : fallbackTitle || session.title || "");
  }

  function cancelRenaming() {
    setEditingSessionId(null);
    setDraftTitle("");
  }

  function saveRenamedTitle() {
    const title = draftTitle.trim();
    if (!title || !managedSession) {
      cancelRenaming();
      return;
    }

    if (managedSession.status === "active") {
      const { session, sessions } = saveChatSession({
        ...currentSessionRef.current,
        title,
        titlePinned: true,
        messages,
      });
      setCurrentSession(session);
      syncArchivedSessions(sessions);
    } else {
      const { sessions } = renameChatSession(managedSession.id, title);
      syncArchivedSessions(sessions);
    }

    cancelRenaming();
  }

  function requestDeleteCurrentSession() {
    setIsSessionMenuOpen(false);
    setPendingDelete({
      kind: "current",
      title: currentDisplay.title,
      description: "删除后会立刻开启一轮新的空白会话，当前内容会从本地历史中移除。",
    });
  }

  function requestDeleteArchivedSession() {
    if (!selectedArchive) return;
    setIsSessionMenuOpen(false);
    setPendingDelete({
      kind: "archived",
      title: selectedArchive.title,
      description: "这条历史记录只会从当前浏览器删除，不会影响其他账号或后台数据。",
    });
  }

  function confirmDeleteSession() {
    if (!pendingDelete) return;

    if (pendingDelete.kind === "current") {
      const { sessions } = deleteChatSession(currentSessionRef.current.id);
      syncArchivedSessions(sessions);
      resetLiveSession();
      return;
    }

    if (selectedArchive) {
      const { sessions } = deleteChatSession(selectedArchive.id);
      syncArchivedSessions(sessions);
      setSelectedArchiveId(null);
      cancelRenaming();
    }

    setPendingDelete(null);
  }


  const guideShell = (
    <div className={`vis-shell ${isHistoryOpen ? "vis-shell--history-open" : ""} ${productTone ? "vis-shell--product" : ""}`}>

      {/* ===== TOP NAV ===== */}
      <nav className="vis-nav">
        <div className="vis-nav__inner">
          <div className="vis-nav__logo">
            <div className="vis-nav__logo-icon"><i className="fas fa-mountain-sun" /></div>
            <span className="vis-nav__logo-text">{activeGuideContext.scenicName}</span>
          </div>

          <div className="vis-nav__links">
            <a className="vis-nav__link" href={buildScenicHref(activeGuideContext.scenicSlug)}>
              <i className="fas fa-home" style={{ fontSize: 12 }} /> 返回首页
            </a>
            <a className="vis-nav__link" href={buildScenicHref(activeGuideContext.scenicSlug)}>
              <i className="fas fa-map-marked-alt" style={{ fontSize: 12 }} /> 景区详情
            </a>
            <a className="vis-nav__link" href={buildPlannerHref(activeGuideContext.scenicSlug)}>
              <i className="fas fa-route" style={{ fontSize: 12 }} /> 路线规划
            </a>
            <span className="vis-nav__link vis-nav__link--active">
              <i className="fas fa-headset" style={{ fontSize: 12 }} /> 导游对话
            </span>
          </div>

          <div className="vis-nav__right">
            <button type="button" className="vis-nav__icon-btn" onClick={() => {
              setIsSessionMenuOpen(false);
              setIsHistoryOpen((value) => !value);
            }}>
              <i className="fas fa-clock-rotate-left" />
            </button>
            {role === "admin" ? (
              <a className="vis-nav__icon-btn" href="/admin" style={{ textDecoration: "none" }}>
                <i className="fas fa-gear" />
              </a>
            ) : null}
            <button type="button" className="vis-nav__icon-btn" onClick={handleLogout} title="退出登录">
              <i className="fas fa-right-from-bracket" />
            </button>
            <div className="vis-nav__avatar">{username.charAt(0)}</div>
          </div>
        </div>
      </nav>

      {/* ===== MAIN 3-COLUMN LAYOUT ===== */}
      <div className="vis-main">

        {/* ===== LEFT SIDEBAR (replaces HistoryRail) ===== */}
        <aside className="vis-left-sidebar">
          <div className="vis-left-sidebar__label">会话管理</div>
          <nav className="vis-left-sidebar__nav">
            <button
              type="button"
              className={`vis-sidebar-item ${!isArchiveView ? "vis-sidebar-item--active" : ""}`}
              onClick={() => {
                setIsSessionMenuOpen(false);
                setSelectedArchiveId(null);
              }}
            >
              {!isArchiveView ? <div className="vis-sidebar-active-dot" /> : null}
              <i className="vis-sidebar-item__icon fas fa-comments" style={{ color: !isArchiveView ? "#f59e0b" : "#94a3b8" }} />
              <span>{currentDisplay.title}</span>
            </button>
            {archives.map((archive) => (
              <button
                type="button"
                key={archive.id}
                className={`vis-sidebar-item ${selectedArchiveId === archive.id ? "vis-sidebar-item--active" : ""}`}
                onClick={() => {
                  setSelectedArchiveId(archive.id);
                  setEditingSessionId(null);
                  setDraftTitle("");
                }}
              >
                {selectedArchiveId === archive.id ? <div className="vis-sidebar-active-dot" /> : null}
                <i className="vis-sidebar-item__icon fas fa-clock" style={{ color: selectedArchiveId === archive.id ? "#f59e0b" : "#94a3b8" }} />
                <span>{archive.title}</span>
              </button>
            ))}
          </nav>

          <div className="vis-sidebar-bottom">
            <div className="vis-sidebar-vip-card">
              <div className="vis-sidebar-vip-card__header">
                <i className="vis-sidebar-vip-card__icon fas fa-crown" />
                <span className="vis-sidebar-vip-card__title">游客信息</span>
              </div>
              <p className="vis-sidebar-vip-card__text">{username} ({role})</p>
            </div>
          </div>
        </aside>

        {/* ===== CENTER PANEL (Digital Human) ===== */}
        <section className="vis-center">
          <div className="vis-digital-human">
            <div className="vis-digital-human__ring" />

            {/* Media stage overlays the image when active */}
            {(streamFrameUrl || videoUrl) ? (
              <div className="vis-media-stage">
                {streamFrameUrl ? (
                  <img src={streamFrameUrl} alt="实时数字人画面" className="vis-media-stage__frame" />
                ) : videoUrl ? (
                  <video key={videoUrl} src={videoUrl} controls autoPlay className="vis-media-stage__video" />
                ) : null}
              </div>
            ) : (
              <img
                src={`/api/v1/interact/avatar/default?v=${avatarImageVersion}`}
                alt="数字人待机形象"
                loading="lazy"
                className="vis-digital-human__img"
              />
            )}

            <div className="vis-digital-human__overlay-top" />
            <div className="vis-digital-human__overlay-right" />

            {/* Top-left badge */}
            <div className="vis-digital-human__badge">
              <div className="vis-gradient-border">
                <div className="vis-gradient-border-inner">
                  <i className="vis-gradient-border-inner__icon fas fa-broadcast-tower" />
                  <span className="vis-gradient-border-inner__text">
                    {isRealtimeMode ? "实时直播" : "稳定模式"}
                  </span>
                </div>
              </div>
            </div>

            {/* Top-right controls */}
            <div className="vis-digital-human__controls">
              <button
                type="button"
                className={`vis-digital-human__ctrl-btn vis-digital-human__gps-toggle ${isGpsWeak ? "is-weak" : "is-normal"}`}
                onClick={toggleGps}
                disabled={isArchiveView}
                title={isGpsWeak ? "切换到正常定位" : "切换到弱 GPS"}
                aria-label={isGpsWeak ? "切换到正常定位" : "切换到弱 GPS"}
              >
                <i className={`fas ${isGpsWeak ? "fa-satellite-dish" : "fa-location-crosshairs"}`} />
                <span className="vis-digital-human__gps-toggle-text">
                  {isGpsWeak ? "弱 GPS" : "正常定位"}
                </span>
              </button>
            </div>

            {/* Bottom overlay bar */}
            <div className="vis-digital-human__bottom-bar">
              <div className="vis-digital-human__bottom-inner">
                <div className="vis-digital-human__info">
                  <div className="vis-digital-human__avatar">
                    <i className="fas fa-robot" />
                  </div>
                  <div>
                    <h2 className="vis-digital-human__name">{activeGuideContext.scenicName} AI 导游</h2>
                    <div className="vis-digital-human__status">
                      <span className="vis-digital-human__status-dot" />
                      <span className="vis-digital-human__status-text">
                        {loading ? "处理中" : "在线"}
                      </span>
                      <span className="vis-digital-human__status-sub">
                        {isArchiveView ? " · 正在回看历史" : " · 当前会话实时保存"}
                      </span>
                    </div>
                  </div>
                </div>

              </div>
            </div>

            {/* Stream notice */}
            {streamNotice ? <div className="vis-stream-notice">{streamNotice}</div> : null}
          </div>

          {/* Process stages strip */}
          <div className="vis-process-strip">
            <div className="vis-process-strip__header">
              <span>{loading ? "当前生成进度" : "当前交互状态"}</span>
              <span className="vis-process-strip__question">{activeQuestion || "等待游客提问"}</span>
            </div>
            <div className="vis-process-steps">
              {PROCESS_STAGES.map((stage) => {
                const currentIndex = PROCESS_STAGE_ORDER.indexOf(processStage);
                const stageIndex = PROCESS_STAGE_ORDER.indexOf(stage.key);
                const isActive = processStage === stage.key;
                const isDone = currentIndex > stageIndex || processStage === "done";
                return (
                  <div
                    key={stage.key}
                    className={`vis-process-step ${isActive ? "vis-process-step--active" : ""} ${isDone ? "vis-process-step--done" : ""}`}
                  >
                    <span className="vis-process-step__dot" />
                    <div>
                      <strong>{stage.title}</strong>
                      <small>{stage.detail}</small>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Agent graph card moved to right sidebar */}

        </section>

        {/* ===== AGENT GRAPH: fixed right-edge drawer ===== */}
        <AgentGraphCard
          agentNodes={agentNodes}
          isExpanded={isAgentGraphExpanded}
          onToggle={() => setIsAgentGraphExpanded((v) => !v)}
          elapsedMs={agentElapsedMs}
        />

        {/* ===== RIGHT PANEL: CHAT ===== */}
        <section className="vis-chat-panel">

          {/* Chat Header */}
          <div className="vis-chat-header">
            <div className="vis-chat-header__top">
              <div className="vis-chat-header__info">
                <div className="vis-chat-header__icon">
                  <i className="fas fa-comments" />
                </div>
                <div>
                  <h3 className="vis-chat-header__title">
                    {isArchiveView ? selectedArchive.title : currentDisplay.title}
                  </h3>
                  <p className="vis-chat-header__subtitle">
                    {isArchiveView
                      ? "只读历史会话"
                      : `${activeGuideContext.scenicName} AI 导游 · ${guideModeLabel}`}
                  </p>
                </div>
              </div>

              <div className="vis-menu-shell">
                <button
                  type="button"
                  className="vis-chat-header__menu-btn"
                  onClick={() => setIsSessionMenuOpen((value) => !value)}
                >
                  <i className="fas fa-ellipsis-vertical" />
                </button>

                {isSessionMenuOpen ? (
                  <div className="vis-menu-popover">
                    {isArchiveView ? (
                      <>
                        <button type="button" className="vis-menu-item" onClick={() => setSelectedArchiveId(null)}>
                          返回当前会话
                        </button>
                        <button
                          type="button"
                          className="vis-menu-item"
                          onClick={() => beginRenameSession(selectedArchive, selectedArchive.title)}
                          disabled={loading}
                        >
                          重命名历史会话
                        </button>
                        <button type="button" className="vis-menu-item vis-menu-item--danger" onClick={requestDeleteArchivedSession}>
                          删除历史会话
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="vis-menu-item"
                          onClick={() => beginRenameSession(currentSession, currentDisplay.title)}
                          disabled={loading}
                        >
                          重命名当前会话
                        </button>
                        <button
                          type="button"
                          className="vis-menu-item vis-menu-item--danger"
                          onClick={requestDeleteCurrentSession}
                          disabled={loading}
                        >
                          删除当前会话
                        </button>
                      </>
                    )}
                  </div>
                ) : null}
              </div>
            </div>

            {/* Mode Tabs */}
            <div className="vis-mode-tabs">
              <button
                type="button"
                className="vis-mode-tab vis-mode-tab--active"
              >
                全部
              </button>
              <button
                type="button"
                className="vis-mode-tab"
                onClick={toggleRealtimeMode}
                disabled={loading || isArchiveView}
              >
                {isRealtimeMode ? "实时生成" : "稳定生成"}
              </button>
            </div>
          </div>

          {/* Context Bar */}
          {!isArchiveView ? (
            <div className="vis-context-bar">
              <div className="vis-context-bar__meta">
                <StatusBadge state="info">{activeGuideContext.scenicName}</StatusBadge>
                <StatusBadge state="warning">{guideModeLabel}</StatusBadge>
                {activeGuideContext.attractionName ? <StatusBadge state="success">{activeGuideContext.attractionName}</StatusBadge> : null}
                {activeGuideContext.routeTitle ? <StatusBadge state="neutral">{activeGuideContext.routeTitle}</StatusBadge> : null}
              </div>
              <div className="vis-context-bar__copy">
                <span>
                  当前导览语境来自
                  {activeGuideContext.attractionName
                    ? `景点「${activeGuideContext.attractionName}」`
                    : activeGuideContext.routeTitle
                      ? `路线「${activeGuideContext.routeTitle}」`
                      : `园区「${activeGuideContext.scenicName}」`}。
                </span>
                <div className="vis-context-bar__links">
                  <a href={buildScenicHref(activeGuideContext.scenicSlug)}>返回园区页</a>
                  <a href={buildPlannerHref(activeGuideContext.scenicSlug)}>重新规划路线</a>
                </div>
              </div>
              <div className="vis-context-bar__actions">
                {activeGuideContext.attractionName ? (
                  <button type="button" className="vis-context-chip" onClick={() => submitTextMessage(`${activeGuideContext.attractionName}为什么值得重点讲解？`)}>
                    讲讲这个景点
                  </button>
                ) : null}
                <button type="button" className="vis-context-chip" onClick={() => submitTextMessage("如果我继续按照当前语境游览，下一站建议去哪里？")}>
                  下一站怎么走
                </button>
                {activeGuideContext.routeTitle ? (
                  <button type="button" className="vis-context-chip" onClick={() => submitTextMessage(`请继续讲解这条${activeGuideContext.routeTitle}路线的每个节点。`)}>
                    继续这条路线
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}

          {/* Inline Editor */}
          {editingSessionId === managedSession?.id ? (
            <div className="vis-inline-editor">
              <input
                className="vis-inline-editor__input"
                value={draftTitle}
                onChange={(event) => setDraftTitle(event.target.value)}
                placeholder="输入会话标题"
                maxLength={32}
              />
              <button type="button" className="vis-btn-primary" onClick={saveRenamedTitle}>
                保存标题
              </button>
              <button type="button" className="vis-btn-secondary" onClick={cancelRenaming}>
                取消
              </button>
            </div>
          ) : null}

          {/* Messages Area */}
          <div ref={chatRef} className="vis-messages">
            {transcriptMessages.map((message, index) => (
              <ChatMessage key={`${message.role}-${index}`} message={message} />
            ))}
            {loading && !isArchiveView ? (
              <div className="vis-typing-indicator">
                <div className="vis-typing-avatar">
                  <span className="vis-typing-avatar__text">AI</span>
                </div>
                <div className="vis-typing-bubble">
                  <div className="vis-typing-wave">
                    <span /><span /><span />
                  </div>
                </div>
              </div>
            ) : null}
          </div>

          {/* Composer Area */}
          <div className="vis-composer-shell">
            {isArchiveView ? (
              <div className="vis-readonly-banner">
                <strong>当前是历史会话</strong>
                <span>这里仅用于回看；继续提问请返回当前正在进行的实时会话。</span>
              </div>
            ) : (
              <>
                {/* Preset Tray */}
                <div className="vis-preset-tray">
                  <button
                    type="button"
                    className="vis-preset-tray__toggle"
                    onClick={() => setIsPresetOpen((value) => !value)}
                    aria-expanded={isPresetOpen}
                  >
                    <span>
                      <strong>精选问题与推荐路线</strong>
                      <small>{demoRoutes.length} 条路线 · {quickPrompts.length} 个快速入口</small>
                    </span>
                    <b>{isPresetOpen ? "收起" : "展开"}</b>
                  </button>

                  {isPresetOpen ? (
                    <div className="vis-preset-tray__content">
                      <div className="vis-preset-routes">
                        {demoRoutes.map((route) => (
                          <button
                            type="button"
                            key={route.label}
                            className="vis-route-card"
                            onClick={() => {
                              setIsPresetOpen(false);
                              submitTextMessage(route.prompt, {
                                presetRouteKey: findPresetRouteMatch(route.prompt, activeGuideContext.scenicSlug)?.presetRouteKey || "",
                              });
                            }}
                            disabled={loading}
                          >
                            <span className="vis-route-card__label">{route.label}</span>
                            <strong>{route.title}</strong>
                            <span>{route.duration}</span>
                            <small>{route.focus}</small>
                            <em>{route.behavior}</em>
                          </button>
                        ))}
                      </div>

                      <div className="vis-preset-prompts">
                        {quickPrompts.map((prompt) => (
                          <button
                            type="button"
                            key={prompt}
                            className="vis-quick-chip"
                            onClick={() => {
                              setInputText(prompt);
                              setIsPresetOpen(false);
                            }}
                          >
                            {prompt}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>

                {/* Input Row */}
                <div className="vis-input-area">
                  <button
                    type="button"
                    className={`vis-voice-btn ${isRecording ? "vis-voice-btn--recording" : ""}`}
                    onMouseDown={startRecording}
                    onMouseUp={stopRecording}
                    onMouseLeave={stopRecording}
                    onTouchStart={(event) => {
                      event.preventDefault();
                      startRecording();
                    }}
                    onTouchEnd={(event) => {
                      event.preventDefault();
                      stopRecording();
                    }}
                    disabled={loading || isArchiveView}
                  >
                    <i className={`fas ${isRecording ? "fa-stop" : "fa-microphone"}`} />
                  </button>

                  {isRecording ? (
                    <div className="vis-audio-bars">
                      <div className="vis-audio-bar" />
                      <div className="vis-audio-bar" />
                      <div className="vis-audio-bar" />
                      <div className="vis-audio-bar" />
                      <div className="vis-audio-bar" />
                    </div>
                  ) : null}

                  <div className="vis-input-wrap">
                    <input
                      className="vis-input-field"
                      value={inputText}
                      onChange={(event) => setInputText(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && !event.shiftKey) {
                          event.preventDefault();
                          handleSendText();
                        }
                      }}
                      placeholder={activeGuideContext.attractionName
                        ? `围绕${activeGuideContext.attractionName}继续提问`
                        : `输入您的问题...`}
                    />
                    <button
                      type="button"
                      className="vis-send-btn"
                      onClick={handleSendText}
                      disabled={loading || !inputText.trim()}
                    >
                      <i className="fas fa-paper-plane" />
                    </button>
                  </div>
                </div>

                {/* Recording state bar */}
                {isRecording ? (
                  <div className="vis-recording-bar">
                    <span className="vis-recording-bar__dot" />
                    <span className="vis-recording-bar__text">录音中</span>
                  </div>
                ) : null}
              </>
            )}
          </div>
        </section>
      </div>

      {/* ===== BOTTOM STATS BAR ===== */}
      <footer className="vis-stats-bar">
        <div className="vis-stats-bar__inner">
          <div className="vis-stat-card">
            <i className="vis-stat-card__icon fas fa-comments" />
            <span className="vis-stat-card__value">{transcriptMessages.length}</span>
            <span className="vis-stat-card__label">条消息</span>
          </div>
          <div className="vis-stat-card">
            <i className="vis-stat-card__icon fas fa-star" />
            <span className="vis-stat-card__value">{demoRoutes.length}</span>
            <span className="vis-stat-card__label">条路线</span>
          </div>
          <div className="vis-stat-card">
            <i className="vis-stat-card__icon fas fa-clock" />
            <span className="vis-stat-card__value">{activeGuideContext.scenicName}</span>
            <span className="vis-stat-card__label">当前景区</span>
          </div>
          <div className="vis-stat-card">
            <i className="vis-stat-card__icon fas fa-face-smile" />
            <span className="vis-stat-card__value">{username}</span>
            <span className="vis-stat-card__label">当前游客</span>
          </div>
        </div>
      </footer>

      {/* ===== DELETE CONFIRMATION DIALOG ===== */}
      {pendingDelete ? (
        <div className="vis-dialog-scrim" role="presentation" onClick={() => setPendingDelete(null)}>
          <div className="vis-dialog-card" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="vis-dialog-card__eyebrow">删除确认</div>
            <h2 className="vis-dialog-card__title">{pendingDelete.kind === "current" ? "删除当前会话" : "删除历史会话"}</h2>
            <p className="vis-dialog-card__copy">{pendingDelete.description}</p>
            <div className="vis-dialog-card__session-title">{pendingDelete.title}</div>
            <div className="vis-dialog-card__actions">
              <button type="button" className="vis-btn-secondary" onClick={() => setPendingDelete(null)}>
                取消
              </button>
              <button type="button" className="vis-btn-danger" onClick={confirmDeleteSession}>
                确认删除
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );

  if (embedded) {
    return guideShell;
  }

  return (
    <div className="vis-shell">
      {guideShell}
    </div>
  );
}
