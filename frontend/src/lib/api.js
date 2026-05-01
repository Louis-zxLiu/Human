async function request(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === "string" ? payload : payload.detail || payload.message || "Request failed";
    throw new Error(message);
  }
  return payload;
}

export function getAuthToken() {
  return localStorage.getItem("auth_token") || "";
}

export function authHeaders(extra = {}) {
  const token = getAuthToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

export function login(payload) {
  return request("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function register(payload) {
  return request("/api/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function fetchProfile() {
  return request("/api/v1/interact/profile", { headers: authHeaders() });
}

export function fetchHistory(limit = 10) {
  return request(`/api/v1/interact/history?limit=${limit}`, { headers: authHeaders() });
}

export function sendTextMessage(formData) {
  return request("/api/v1/interact/text", {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
}

export function sendAudioMessage(formData) {
  return request("/api/v1/interact/audio", {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
}

export function fetchDashboard() {
  return request("/api/v1/admin/dashboard", { headers: authHeaders() });
}

export function fetchVoices() {
  return request("/api/v1/admin/voice/list", { headers: authHeaders() });
}

export function updateVoice(voiceId) {
  return request("/api/v1/admin/voice/update", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ voice_id: voiceId }),
  });
}

export function previewVoice(voiceId) {
  return request("/api/v1/admin/voice/preview", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ voice_id: voiceId }),
  });
}

export function uploadAvatar(file) {
  const formData = new FormData();
  formData.append("file", file);
  return request("/api/v1/admin/avatar", {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
}
