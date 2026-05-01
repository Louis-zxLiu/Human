import React, { useEffect, useMemo, useRef, useState } from "react";

import { ChatMessage } from "../components/ChatMessage";
import { StatusBadge } from "../components/StatusBadge";
import { fetchHistory, fetchProfile, sendAudioMessage, sendTextMessage } from "../lib/api";


export function VisitorApp() {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content: "您好，我是您的灵山胜境数字人导游。您可以问我景点事实问题、路线推荐，也可以在弱 GPS 模式下体验多轮问路。",
      meta: null,
    },
  ]);
  const [inputText, setInputText] = useState("");
  const [isGpsWeak, setIsGpsWeak] = useState(localStorage.getItem("gps_weak_mode") === "true");
  const [loading, setLoading] = useState(false);
  const [userProfile, setUserProfile] = useState("");
  const [videoUrl, setVideoUrl] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const chatRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const username = localStorage.getItem("username") || "游客";
  const role = localStorage.getItem("user_role") || "user";
  const clientSessionId = useMemo(() => {
    const current = localStorage.getItem("client_session_id") || crypto.randomUUID();
    localStorage.setItem("client_session_id", current);
    return current;
  }, []);

  useEffect(() => {
    if (!localStorage.getItem("auth_token")) {
      window.location.href = "/login";
      return;
    }
    fetchProfile().then((result) => setUserProfile(result.profile || "")).catch(() => {});
    fetchHistory(10)
      .then((result) => {
        const historyMessages = [];
        for (const item of (result.history || []).reverse()) {
          historyMessages.push({ role: "user", content: item.user_query, meta: null });
          historyMessages.push({ role: "assistant", content: item.ai_response, meta: null });
        }
        setMessages((previous) => [...previous, ...historyMessages]);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages, loading]);

  async function handleSendText() {
    if (!inputText.trim()) return;
    const text = inputText.trim();
    setMessages((previous) => [...previous, { role: "user", content: text, meta: null }]);
    setInputText("");
    setLoading(true);
    try {
      const formData = new FormData();
      formData.append("text", text);
      formData.append("gps_status", isGpsWeak ? "weak" : "normal");
      formData.append("client_session_id", clientSessionId);
      const result = await sendTextMessage(formData);
      setMessages((previous) => [...previous, { role: "assistant", content: result.assistant_text, meta: result.rag_metadata || null }]);
      if (result.video_stream_url) {
        setVideoUrl(`${result.video_stream_url}?t=${Date.now()}`);
      }
    } catch (err) {
      setMessages((previous) => [...previous, { role: "assistant", content: `[系统错误] ${err.message}`, meta: null }]);
    } finally {
      setLoading(false);
    }
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
      try {
        const formData = new FormData();
        formData.append("audio", blob, "voice.webm");
        formData.append("gps_status", isGpsWeak ? "weak" : "normal");
        formData.append("client_session_id", clientSessionId);
        const result = await sendAudioMessage(formData);
        setMessages((previous) => [
          ...previous,
          { role: "user", content: result.user_text, meta: null },
          { role: "assistant", content: result.assistant_text, meta: result.rag_metadata || null },
        ]);
        if (result.video_stream_url) {
          setVideoUrl(`${result.video_stream_url}?t=${Date.now()}`);
        }
      } catch (err) {
        setMessages((previous) => [...previous, { role: "assistant", content: `[系统错误] ${err.message}`, meta: null }]);
      } finally {
        setLoading(false);
      }
    };
  }

  async function startRecording() {
    await ensureRecorder();
    setIsRecording(true);
    mediaRecorderRef.current.start();
  }

  function stopRecording() {
    if (mediaRecorderRef.current && isRecording) {
      setIsRecording(false);
      mediaRecorderRef.current.stop();
    }
  }

  function toggleGps() {
    const nextValue = !isGpsWeak;
    setIsGpsWeak(nextValue);
    localStorage.setItem("gps_weak_mode", String(nextValue));
  }

  return (
    <div className="page-shell grid" style={{ gridTemplateColumns: "1.3fr 1fr" }}>
      <section className="card" style={{ overflow: "hidden", display: "flex", flexDirection: "column" }}>
        <div className="card-dark" style={{ padding: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
            <div>
              <h1 style={{ margin: 0, fontSize: 28 }}>灵山胜境 AI 数字人导游</h1>
              <p style={{ marginTop: 8, color: "#cbd5e1" }}>完整工程版游客端</p>
            </div>
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <StatusBadge state={isGpsWeak ? "warning" : "info"}>{isGpsWeak ? "弱 GPS 模式" : "正常定位模式"}</StatusBadge>
              {role === "admin" ? <a className="button-primary" href="/admin">管理后台</a> : null}
              <button className="button-secondary" onClick={() => { localStorage.clear(); window.location.href = "/login"; }}>退出</button>
            </div>
          </div>
          <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
            <StatusBadge state="info">{username}</StatusBadge>
            {userProfile ? <StatusBadge state="success">{userProfile}</StatusBadge> : null}
            <button className="button-primary" onClick={toggleGps}>{isGpsWeak ? "关闭弱 GPS" : "开启弱 GPS"}</button>
          </div>
        </div>
        <div style={{ background: "#020617", aspectRatio: "16/9", position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
          {videoUrl ? <video key={videoUrl} src={videoUrl} controls autoPlay style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <div style={{ color: "#94a3b8" }}>等待互动开始</div>}
        </div>
        <div style={{ padding: 16, borderTop: "1px solid #e2e8f0", display: "flex", justifyContent: "center" }}>
          <button className="button-primary" onMouseDown={startRecording} onMouseUp={stopRecording} onTouchStart={startRecording} onTouchEnd={stopRecording}>
            {isRecording ? "松开结束说话" : "按住语音提问"}
          </button>
        </div>
      </section>

      <section className="card" style={{ display: "flex", flexDirection: "column", minHeight: "78vh" }}>
        <div style={{ padding: 20, borderBottom: "1px solid #e2e8f0" }}>
          <h2 className="section-title">对话记录</h2>
          <div className="muted">推荐卡片和弱 GPS 状态会直接显示在消息流里</div>
        </div>
        <div ref={chatRef} className="chat-scroll" style={{ flex: 1, padding: 16, display: "grid", gap: 14 }}>
          {messages.map((message, index) => <ChatMessage key={index} message={message} />)}
          {loading ? <div className="muted">正在生成回答...</div> : null}
        </div>
        <div style={{ padding: 16, borderTop: "1px solid #e2e8f0", display: "flex", gap: 10 }}>
          <input className="input" value={inputText} onChange={(event) => setInputText(event.target.value)} onKeyDown={(event) => event.key === "Enter" && handleSendText()} placeholder="输入问题，例如：给我推荐一条历史文化路线" />
          <button className="button-primary" onClick={handleSendText}>发送</button>
        </div>
      </section>
    </div>
  );
}
