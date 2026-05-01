const STORAGE_KEY = "visitor_chat_archives_v1";
const MAX_ARCHIVED_SESSIONS_PER_USER = 20;
const DEFAULT_TITLE = "新对话";

function isBrowser() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function compactText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function shorten(text, limit) {
  const normalized = compactText(text);
  if (!normalized) return "";
  if (normalized.length <= limit) return normalized;
  return `${normalized.slice(0, limit - 1).trimEnd()}…`;
}

function normalizeMessage(message = {}) {
  return {
    role: message.role === "user" ? "user" : "assistant",
    content: typeof message.content === "string" ? message.content : "",
    meta: message.meta ?? null,
  };
}

export function summarizeMessages(messages) {
  const normalized = Array.isArray(messages) ? messages.map(normalizeMessage) : [];
  const nonEmptyMessages = normalized.filter((message) => compactText(message.content));
  const firstUserMessage = nonEmptyMessages.find((message) => message.role === "user");
  const lastMessage = [...nonEmptyMessages].reverse().find((message) => compactText(message.content));

  return {
    title: shorten(firstUserMessage?.content || lastMessage?.content || DEFAULT_TITLE, 26) || DEFAULT_TITLE,
    preview: shorten(lastMessage?.content || "", 80),
    messages: normalized,
  };
}

function normalizeSession(session = {}) {
  const createdAt = typeof session.createdAt === "string" ? session.createdAt : new Date().toISOString();
  const updatedAt = typeof session.updatedAt === "string" ? session.updatedAt : createdAt;
  const summary = summarizeMessages(session.messages);

  return {
    id: typeof session.id === "string" && session.id ? session.id : crypto.randomUUID(),
    username: typeof session.username === "string" ? session.username : "",
    status: session.status === "active" ? "active" : "archived",
    createdAt,
    updatedAt,
    title: compactText(session.title) || summary.title,
    preview: compactText(session.preview) || summary.preview,
    titlePinned: Boolean(session.titlePinned),
    messages: summary.messages,
  };
}

function sortSessionsByTime(sessions) {
  return [...sessions].sort(
    (left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime(),
  );
}

function dedupeSessions(sessions) {
  const seen = new Map();
  for (const session of sessions) {
    const normalized = normalizeSession(session);
    seen.set(normalized.id, normalized);
  }
  return [...seen.values()];
}

function clampSessions(sessions) {
  const normalized = sortSessionsByTime(dedupeSessions(sessions));
  const groupedByUser = new Map();

  for (const session of normalized) {
    const bucketKey = session.username || "__anonymous__";
    if (!groupedByUser.has(bucketKey)) {
      groupedByUser.set(bucketKey, { active: [], archived: [] });
    }
    const group = groupedByUser.get(bucketKey);
    if (session.status === "active") {
      group.active.push(session);
    } else if (group.archived.length < MAX_ARCHIVED_SESSIONS_PER_USER) {
      group.archived.push(session);
    }
  }

  return [...groupedByUser.values()].flatMap((group) => [...group.active, ...group.archived]);
}

export function readChatArchives() {
  if (!isBrowser()) return [];
  try {
    const raw = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "[]");
    return clampSessions(Array.isArray(raw) ? raw : []);
  } catch {
    return [];
  }
}

export function writeChatArchives(sessions) {
  if (!isBrowser()) return [];
  const nextSessions = clampSessions(sessions);
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextSessions));
  return nextSessions;
}

export function getArchivedSessions(username, sessions = readChatArchives()) {
  return sortSessionsByTime(
    sessions.filter((session) => session.username === username && session.status === "archived"),
  );
}

export function archiveActiveSessions(username) {
  const sessions = readChatArchives().map((session) => (
    session.username === username && session.status === "active"
      ? { ...session, status: "archived", updatedAt: new Date().toISOString() }
      : session
  ));
  return writeChatArchives(sessions);
}

export function createActiveSession(username, messages) {
  const now = new Date().toISOString();
  const summary = summarizeMessages(messages);
  const hasUserMessage = summary.messages.some((message) => message.role === "user" && compactText(message.content));

  return {
    id: crypto.randomUUID(),
    username,
    status: "active",
    createdAt: now,
    updatedAt: now,
    title: hasUserMessage ? summary.title : DEFAULT_TITLE,
    preview: hasUserMessage ? summary.preview : "",
    titlePinned: false,
    messages: summary.messages,
  };
}

function buildUpdatedSession(baseSession, messages) {
  const summary = summarizeMessages(messages);

  return normalizeSession({
    ...baseSession,
    updatedAt: new Date().toISOString(),
    title: baseSession.titlePinned ? baseSession.title : summary.title,
    preview: summary.preview,
    messages: summary.messages,
  });
}

export function persistActiveSession(username, baseSession, messages) {
  const session = buildUpdatedSession({
    ...baseSession,
    username,
    status: "active",
  }, messages);
  return saveChatSession(session);
}

export function saveChatSession(session) {
  const normalized = normalizeSession(session);
  const sessions = writeChatArchives([
    normalized,
    ...readChatArchives().filter((item) => item.id !== normalized.id),
  ]);
  return { session: normalized, sessions };
}

export function renameChatSession(sessionId, nextTitle) {
  const trimmedTitle = compactText(nextTitle);
  if (!trimmedTitle) {
    return { session: null, sessions: readChatArchives() };
  }

  let updatedSession = null;
  const sessions = writeChatArchives(readChatArchives().map((session) => {
    if (session.id !== sessionId) return session;
    updatedSession = normalizeSession({
      ...session,
      title: trimmedTitle,
      titlePinned: true,
      updatedAt: new Date().toISOString(),
    });
    return updatedSession;
  }));

  return { session: updatedSession, sessions };
}

export function deleteChatSession(sessionId) {
  const sessions = writeChatArchives(readChatArchives().filter((session) => session.id !== sessionId));
  return { sessions };
}
