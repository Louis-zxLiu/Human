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

  const currentSessionRef = useRef(currentSession);
  const chatRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const stageTimersRef = useRef([]);
  const streamFrameQueueRef = useRef([]);
  const streamFrameTimerRef = useRef(null);
  const streamAudioUrlsRef = useRef([]);
  const messagesRef = useRef(messages);

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
    streamAudioUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
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

  async function playStreamingAudio(audioBase64) {
    if (!audioBase64) return;
    const audioUrl = base64ToBlobUrl(audioBase64, "audio/mpeg");
    streamAudioUrlsRef.current.push(audioUrl);
    const audio = new Audio(audioUrl);
    audio.onended = () => {
      URL.revokeObjectURL(audioUrl);
      streamAudioUrlsRef.current = streamAudioUrlsRef.current.filter((url) => url !== audioUrl);
    };
    try {
      await audio.play();
    } catch {
      setStreamNotice("浏览器拦截了自动播放，点击数字人舞台上的音频控件可继续听取。");
    }
  }

  function clearStageTimers() {
    stageTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    stageTimersRef.current = [];
  }

  function scheduleProcessingStages(question, startStage = "heard") {
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
    });
    const result = await sendTextMessage(formData);

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

        if (message.type === "text_token") {
          ensureAssistantPlaceholder();
          assistantText += message.text || "";
          updateAssistantMessage(assistantIndex, { content: assistantText });
          setProcessStage("generating");
          return;
        }

        if (message.type === "chunk") {
          setProcessStage("avatar");
          streamedMedia = true;
          enqueueStreamingFrames(message.frames || []);
          await playStreamingAudio(message.audio);
          return;
        }

        if (message.type === "done") {
          ensureAssistantPlaceholder();
          const finalText = message.full_text || assistantText;
          updateAssistantMessage(
            assistantIndex,
            { content: finalText, meta: message.rag_metadata || null },
            true,
          );
          setStreamNotice("实时流式回答完成。");
          completeProcessing({ video_stream_url: streamedMedia ? "__stream__" : "" });
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

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorderRef.current = new MediaRecorder(stream);
    mediaRecorderRef.current.ondataavailable = (event) => {
      if (event.data.size > 0) {
        audioChunksRef.current.push(event.data);
      }
    };
    mediaRecorderRef.current.onstop = async () => {
      const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
      audioChunksRef.current = [];
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
              audioFile: new File([blob], "voice.webm", { type: "audio/webm" }),
              gpsStatus: isGpsWeak ? "weak" : "normal",
              clientSessionId: currentSessionRef.current.id,
              scenicSlug: activeGuideContext.scenicSlug,
              attractionId: activeGuideContext.attractionId,
              routeLabel: activeGuideContext.routeTitle || activeGuideContext.routeLabel,
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
          }
        } else {
          const formData = buildAudioMessageForm({
            audioFile: new File([blob], "voice.webm", { type: "audio/webm" }),
            gpsStatus: isGpsWeak ? "weak" : "normal",
            clientSessionId: currentSessionRef.current.id,
            scenicSlug: activeGuideContext.scenicSlug,
            attractionId: activeGuideContext.attractionId,
            routeLabel: activeGuideContext.routeTitle || activeGuideContext.routeLabel,
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
        }
      } catch (err) {
        clearStageTimers();
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
      mediaRecorderRef.current.start();
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
    <div className={`visitor-layout ${isHistoryOpen ? "visitor-layout--history-open" : ""} ${productTone ? "visitor-layout--product" : ""}`}>
        <HistoryRail
          isOpen={isHistoryOpen}
          archives={archives}
          currentTitle={currentDisplay.title}
          currentPreview={currentDisplay.preview}
          isCurrentSelected={!isArchiveView}
          selectedArchiveId={selectedArchiveId}
          onToggle={() => {
            setIsSessionMenuOpen(false);
            setIsHistoryOpen((value) => !value);
          }}
          onShowCurrent={() => {
            setIsSessionMenuOpen(false);
            setSelectedArchiveId(null);
          }}
          onSelectArchive={(id) => {
            setSelectedArchiveId(id);
            setEditingSessionId(null);
            setDraftTitle("");
          }}
        />

        <section className="panel chat-panel">
            <div className="panel-header">
              <div className="panel-header__copy">
              <div className="eyebrow">{isArchiveView ? "只读历史" : "导览会话"}</div>
              <h1 className="panel-title">{isArchiveView ? selectedArchive.title : currentDisplay.title}</h1>
              <p className="panel-copy">
                {isArchiveView
                  ? "当前查看的是已经归档的旧会话。返回实时会话后，输入框和语音按钮才会恢复可用。"
                  : "每次进入页面都会开启一轮新会话，旧会话会自动按用户名收进左侧历史栏。"}
              </p>
            </div>

            <div className="panel-toolbar">
              <button
                type="button"
                className="button-ghost"
                onClick={() => {
                  setIsSessionMenuOpen(false);
                  setIsHistoryOpen((value) => !value);
                }}
              >
                {isHistoryOpen ? "收起历史" : "展开历史"}
              </button>

              <div className="menu-shell">
                <button
                  type="button"
                  className="button-secondary"
                  onClick={() => setIsSessionMenuOpen((value) => !value)}
                >
                  更多
                </button>

                {isSessionMenuOpen ? (
                  <div className="menu-popover">
                    {isArchiveView ? (
                      <>
                        <button type="button" className="menu-item" onClick={() => setSelectedArchiveId(null)}>
                          返回当前会话
                        </button>
                        <button
                          type="button"
                          className="menu-item"
                          onClick={() => beginRenameSession(selectedArchive, selectedArchive.title)}
                          disabled={loading}
                        >
                          重命名历史会话
                        </button>
                        <button type="button" className="menu-item menu-item--danger" onClick={requestDeleteArchivedSession}>
                          删除历史会话
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="menu-item"
                          onClick={() => beginRenameSession(currentSession, currentDisplay.title)}
                          disabled={loading}
                        >
                          重命名当前会话
                        </button>
                        <button
                          type="button"
                          className="menu-item menu-item--danger"
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
          </div>

          {!isArchiveView ? (
            <div className="guide-context-bar">
              <div className="guide-context-bar__meta">
                <StatusBadge state="info">{activeGuideContext.scenicName}</StatusBadge>
                <StatusBadge state="warning">{guideModeLabel}</StatusBadge>
                {activeGuideContext.attractionName ? <StatusBadge state="success">{activeGuideContext.attractionName}</StatusBadge> : null}
                {activeGuideContext.routeTitle ? <StatusBadge state="neutral">{activeGuideContext.routeTitle}</StatusBadge> : null}
              </div>
              <div className="guide-context-bar__copy">
                <span>
                  当前导览语境来自
                  {activeGuideContext.attractionName
                    ? `景点「${activeGuideContext.attractionName}」`
                    : activeGuideContext.routeTitle
                      ? `路线「${activeGuideContext.routeTitle}」`
                      : `园区「${activeGuideContext.scenicName}」`}。
                </span>
                <div className="guide-context-bar__links">
                  <a href={buildScenicHref(activeGuideContext.scenicSlug)}>返回园区页</a>
                  <a href={buildPlannerHref(activeGuideContext.scenicSlug)}>重新规划路线</a>
                </div>
              </div>
              <div className="guide-context-bar__actions">
                {activeGuideContext.attractionName ? (
                  <button type="button" className="prompt-chip" onClick={() => submitTextMessage(`${activeGuideContext.attractionName}为什么值得重点讲解？`)}>
                    讲讲这个景点
                  </button>
                ) : null}
                <button type="button" className="prompt-chip" onClick={() => submitTextMessage("如果我继续按照当前语境游览，下一站建议去哪里？")}>
                  下一站怎么走
                </button>
                {activeGuideContext.routeTitle ? (
                  <button type="button" className="prompt-chip" onClick={() => submitTextMessage(`请继续讲解这条${activeGuideContext.routeTitle}路线的每个节点。`)}>
                    继续这条路线
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}

          {editingSessionId === managedSession?.id ? (
            <div className="inline-editor">
              <input
                className="input-field inline-editor__input"
                value={draftTitle}
                onChange={(event) => setDraftTitle(event.target.value)}
                placeholder="输入会话标题"
                maxLength={32}
              />
              <button type="button" className="button-primary" onClick={saveRenamedTitle}>
                保存标题
              </button>
              <button type="button" className="button-secondary" onClick={cancelRenaming}>
                取消
              </button>
            </div>
          ) : null}

          <div className="chat-shell">
            <div ref={chatRef} className="chat-scroll">
              {transcriptMessages.map((message, index) => (
                <ChatMessage key={`${message.role}-${index}`} message={message} />
              ))}
              {loading && !isArchiveView ? <div className="loading-row">正在生成回复...</div> : null}
            </div>

            <div className="composer-shell">
              {isArchiveView ? (
                <div className="readonly-banner">
                  <strong>当前是历史会话</strong>
                  <span>这里仅用于回看；继续提问请返回右侧正在进行的实时会话。</span>
                </div>
              ) : (
                <>
                  <div className={`preset-tray ${isPresetOpen ? "is-open" : ""}`}>
                    <button
                      type="button"
                      className="preset-tray__toggle"
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
                      <div className="preset-tray__content">
                        <div className="prompt-row prompt-row--routes">
                          {demoRoutes.map((route) => (
                            <button
                              type="button"
                              key={route.label}
                              className="demo-route-card"
                              onClick={() => {
                                setIsPresetOpen(false);
                                submitTextMessage(route.prompt, {
                                  presetRouteKey: findPresetRouteMatch(route.prompt, activeGuideContext.scenicSlug)?.presetRouteKey || "",
                                });
                              }}
                              disabled={loading}
                            >
                              <span className="demo-route-card__label">{route.label}</span>
                              <strong>{route.title}</strong>
                              <span>{route.duration}</span>
                              <small>{route.focus}</small>
                              <em>{route.behavior}</em>
                            </button>
                          ))}
                        </div>

                        <div className="prompt-row">
                          {quickPrompts.map((prompt) => (
                            <button
                              type="button"
                              key={prompt}
                              className="prompt-chip"
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

                  <div className="composer-row">
                    <textarea
                      className="input-field composer-input"
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
                        : `输入问题，例如：帮我规划一条${activeGuideContext.scenicName}路线`}
                      rows={1}
                    />
                    <button
                      type="button"
                      className="button-primary composer-send"
                      onClick={handleSendText}
                      disabled={loading}
                    >
                      发送
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </section>

        <section className="media-stack">
          <div className="panel panel-dark media-panel">
            <div className="panel-header panel-header--tight media-panel__header">
              <div>
                <div className="eyebrow">数字人舞台</div>
                <h2 className="panel-title">数字人窗口</h2>
              </div>
              <div className="panel-toolbar">
                {role === "admin" ? <a className="button-secondary compact-link" href="/admin">进入后台</a> : null}
                <button type="button" className="text-button danger-text" onClick={handleLogout}>
                  退出登录
                </button>
              </div>
            </div>

            <div className="media-status-strip">
              <StatusBadge state="info">{username}</StatusBadge>
              <StatusBadge state={isArchiveView ? "neutral" : "warning"}>
                {isArchiveView ? "正在回看历史" : "当前会话实时保存"}
              </StatusBadge>
              <StatusBadge state={isGpsWeak ? "warning" : "success"}>
                {isGpsWeak ? "弱 GPS 模式" : "正常定位"}
              </StatusBadge>
              <StatusBadge state={isRealtimeMode ? "success" : "neutral"}>
                {isRealtimeMode ? "实时生成" : "稳定生成"}
              </StatusBadge>
              <StatusBadge state="info">{activeGuideContext.scenicName}</StatusBadge>
            </div>

            <div className="process-panel">
              <div className="process-panel__header">
                <span>{loading ? "当前生成进度" : "当前交互状态"}</span>
                <strong>{activeQuestion || "等待游客提问"}</strong>
              </div>
              <div className="process-steps">
                {PROCESS_STAGES.map((stage) => {
                  const currentIndex = PROCESS_STAGE_ORDER.indexOf(processStage);
                  const stageIndex = PROCESS_STAGE_ORDER.indexOf(stage.key);
                  const isActive = processStage === stage.key;
                  const isDone = currentIndex > stageIndex || processStage === "done";
                  return (
                    <div
                      key={stage.key}
                      className={`process-step ${isActive ? "is-active" : ""} ${isDone ? "is-done" : ""}`}
                    >
                      <span className="process-step__dot" />
                      <div>
                        <strong>{stage.title}</strong>
                        <small>{stage.detail}</small>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="media-stage">
              {streamFrameUrl ? (
                <img src={streamFrameUrl} alt="实时数字人画面" className="media-stage__stream-frame" />
              ) : videoUrl ? (
                <video key={videoUrl} src={videoUrl} controls autoPlay className="media-stage__video" />
              ) : (
                <div className="media-stage__placeholder">
                  <strong>等待互动开始</strong>
                  <span>音视频生成后会稳定展示在这里，聊天滚动不会再把舞台挤压变形。</span>
                </div>
              )}
            </div>

            {streamNotice ? <div className="stream-notice">{streamNotice}</div> : null}

            <div className="media-actions">
              <button
                type="button"
                className={`button-primary button-block ${isRecording ? "is-recording" : ""}`}
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
                {isRecording ? "松开发送语音" : "按住进行语音提问"}
              </button>

              <button
                type="button"
                className="button-secondary button-block"
                onClick={toggleRealtimeMode}
                disabled={loading || isArchiveView}
              >
                {isRealtimeMode ? "切换稳定生成模式" : "切换实时生成模式"}
              </button>

              <button
                type="button"
                className="button-secondary button-block"
                onClick={toggleGps}
                disabled={isArchiveView}
              >
                {isGpsWeak ? "关闭弱 GPS" : "开启弱 GPS"}
              </button>
            </div>

            <div className="media-footnote">
              本地历史按用户名隔离保存，当前导览保持园区与路线语境，刷新或重新进入导览页时会开启新一轮会话。
            </div>
          </div>
        </section>
      {pendingDelete ? (
        <div className="dialog-scrim" role="presentation" onClick={() => setPendingDelete(null)}>
          <div className="dialog-card" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="eyebrow">删除确认</div>
            <h2 className="panel-title">{pendingDelete.kind === "current" ? "删除当前会话" : "删除历史会话"}</h2>
            <p className="panel-copy">{pendingDelete.description}</p>
            <div className="dialog-session-title">{pendingDelete.title}</div>
            <div className="dialog-actions">
              <button type="button" className="button-secondary" onClick={() => setPendingDelete(null)}>
                取消
              </button>
              <button type="button" className="button-danger" onClick={confirmDeleteSession}>
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
    <div className="page-shell">
      <div className="page-container">
        {guideShell}
      </div>
    </div>
  );
}
