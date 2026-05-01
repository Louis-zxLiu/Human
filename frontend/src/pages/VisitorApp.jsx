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
import { logout, sendAudioMessage, sendTextMessage } from "../lib/api";

const AUTH_KEYS = ["auth_token", "username", "user_role"];
const GREETING_MESSAGE = {
  role: "assistant",
  content: "你好，我是灵山胜境数字人导游。你可以问我景点事实、路线推荐，也可以在弱 GPS 模式下体验多轮问路。",
  meta: null,
};
const QUICK_PROMPTS = [
  "我第一次来，帮我推荐 90 分钟游览路线",
  "我现在在梵宫附近，下一站适合去哪里",
  "灵山大佛的历史背景是什么",
];
const DEMO_ROUTES = [
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
const PROCESS_STAGE_ORDER = ["idle", "heard", "retrieving", "generating", "avatar", "done"];
const PROCESS_STAGES = [
  { key: "heard", title: "听懂游客意图", detail: "识别文本或语音输入，锁定本轮问题。" },
  { key: "retrieving", title: "检索可信资料", detail: "按意图访问 DOCX 知识库、行为数据或路线融合链路。" },
  { key: "generating", title: "生成讲解回答", detail: "组织事实证据、路线节点和游客可听懂的讲解。" },
  { key: "avatar", title: "数字人出镜", detail: "合成语音和口型视频，形成可演示的多模态反馈。" },
];

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

export function VisitorApp() {
  const username = localStorage.getItem("username") || "游客";
  const role = localStorage.getItem("user_role") || "user";

  const [messages, setMessages] = useState([GREETING_MESSAGE]);
  const [inputText, setInputText] = useState("");
  const [isGpsWeak, setIsGpsWeak] = useState(localStorage.getItem("gps_weak_mode") === "true");
  const [loading, setLoading] = useState(false);
  const [processStage, setProcessStage] = useState("idle");
  const [activeQuestion, setActiveQuestion] = useState("");
  const [videoUrl, setVideoUrl] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [archives, setArchives] = useState([]);
  const [selectedArchiveId, setSelectedArchiveId] = useState(null);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [currentSession, setCurrentSession] = useState(() => createActiveSession(username, [GREETING_MESSAGE]));
  const [editingSessionId, setEditingSessionId] = useState(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [isSessionMenuOpen, setIsSessionMenuOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  const currentSessionRef = useRef(currentSession);
  const chatRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const stageTimersRef = useRef([]);

  useEffect(() => {
    currentSessionRef.current = currentSession;
  }, [currentSession]);

  useEffect(() => () => {
    stageTimersRef.current.forEach((timer) => window.clearTimeout(timer));
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
      window.location.href = "/login";
      return;
    }

    const storedSessions = archiveActiveSessions(username);
    setArchives(getArchivedSessions(username, storedSessions));
    setCurrentSession(createActiveSession(username, [GREETING_MESSAGE]));
  }, [username]);

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
    const freshSession = createActiveSession(username, [GREETING_MESSAGE]);
    setCurrentSession(freshSession);
    setMessages([GREETING_MESSAGE]);
    setSelectedArchiveId(null);
    setEditingSessionId(null);
    setPendingDelete(null);
    setDraftTitle("");
    setInputText("");
    setVideoUrl("");
    setLoading(false);
    setProcessStage("idle");
    setActiveQuestion("");
  }

  function updateVideoFromResult(result) {
    if (result.video_stream_url) {
      setVideoUrl(`${result.video_stream_url}?t=${Date.now()}`);
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

  async function submitTextMessage(text) {
    if (!text.trim() || loading || isArchiveView) return;

    const normalizedText = text.trim();
    setInputText("");
    scheduleProcessingStages(normalizedText);

    const nextMessages = [...messages, { role: "user", content: normalizedText, meta: null }];
    setMessages(nextMessages);
    persistMessages(nextMessages);
    setLoading(true);

    try {
      const formData = new FormData();
      formData.append("text", normalizedText);
      formData.append("gps_status", isGpsWeak ? "weak" : "normal");
      formData.append("client_session_id", currentSessionRef.current.id);
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
        const formData = new FormData();
        formData.append("audio", blob, "voice.webm");
        formData.append("gps_status", isGpsWeak ? "weak" : "normal");
        formData.append("client_session_id", currentSessionRef.current.id);
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

  return (
    <div className="page-shell">
      <div className={`page-container visitor-layout ${isHistoryOpen ? "visitor-layout--history-open" : ""}`}>
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
              <div className="eyebrow">{isArchiveView ? "只读历史" : "实时对话"}</div>
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
                  <div className="prompt-row">
                    {DEMO_ROUTES.map((route) => (
                      <button
                        type="button"
                        key={route.label}
                        className="demo-route-card"
                        onClick={() => submitTextMessage(route.prompt)}
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
                    {QUICK_PROMPTS.map((prompt) => (
                      <button
                        type="button"
                        key={prompt}
                        className="prompt-chip"
                        onClick={() => setInputText(prompt)}
                      >
                        {prompt}
                      </button>
                    ))}
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
                      placeholder="输入问题，例如：帮我规划一条包含梵宫和大佛的路线"
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
                <h2 className="panel-title">视频主位</h2>
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
                {isArchiveView ? "正在回看历史" : "本轮会话实时保存"}
              </StatusBadge>
              <StatusBadge state={isGpsWeak ? "warning" : "success"}>
                {isGpsWeak ? "弱 GPS 模式" : "正常定位"}
              </StatusBadge>
            </div>

            <div className="process-panel">
              <div className="process-panel__header">
                <span>{loading ? "本轮生成进度" : "演示闭环状态"}</span>
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
              {videoUrl ? (
                <video key={videoUrl} src={videoUrl} controls autoPlay className="media-stage__video" />
              ) : (
                <div className="media-stage__placeholder">
                  <strong>等待互动开始</strong>
                  <span>音视频生成后会稳定展示在这里，聊天滚动不会再把舞台挤压变形。</span>
                </div>
              )}
            </div>

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
                onClick={toggleGps}
                disabled={isArchiveView}
              >
                {isGpsWeak ? "关闭弱 GPS" : "开启弱 GPS"}
              </button>
            </div>

            <div className="media-footnote">
              本地历史按用户名隔离保存，刷新或重新进入前台时会自动开启新一轮会话。
            </div>
          </div>
        </section>
      </div>

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
}
