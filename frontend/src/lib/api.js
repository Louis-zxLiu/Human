async function request(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    const message = typeof payload === "string" ? payload : payload.detail || payload.message || "Request failed";
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload;
}

export function isAuthError(error) {
  const message = String(error?.message || "");
  return (
    error?.status === 401 ||
    message === "Invalid authentication token" ||
    message === "Not authenticated"
  );
}

function formDataWithContext({
  text = "",
  gpsStatus = "normal",
  clientSessionId = "",
  scenicSlug = "",
  attractionId = "",
  routeLabel = "",
  presetRouteKey = "",
} = {}) {
  const formData = new FormData();
  if (text) formData.append("text", text);
  formData.append("gps_status", gpsStatus);
  if (clientSessionId) formData.append("client_session_id", clientSessionId);
  if (scenicSlug) formData.append("scenicSlug", scenicSlug);
  if (attractionId) formData.append("attractionId", attractionId);
  if (routeLabel) formData.append("routeLabel", routeLabel);
  if (presetRouteKey) formData.append("presetRouteKey", presetRouteKey);
  return formData;
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

export function logout() {
  return request("/api/v1/auth/logout", {
    method: "POST",
    headers: authHeaders(),
  });
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

export function getInteractStreamUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/v1/interact/stream`;
}

export function buildTextMessageForm(payload) {
  return formDataWithContext(payload);
}

export function buildAudioMessageForm({
  audioFile,
  gpsStatus = "normal",
  clientSessionId = "",
  scenicSlug = "",
  attractionId = "",
  routeLabel = "",
  presetRouteKey = "",
} = {}) {
  const formData = new FormData();
  formData.append("audio", audioFile);
  formData.append("gps_status", gpsStatus);
  if (clientSessionId) formData.append("client_session_id", clientSessionId);
  if (scenicSlug) formData.append("scenicSlug", scenicSlug);
  if (attractionId) formData.append("attractionId", attractionId);
  if (routeLabel) formData.append("routeLabel", routeLabel);
  if (presetRouteKey) formData.append("presetRouteKey", presetRouteKey);
  return formData;
}

export function fetchScenicAreas() {
  return request("/api/v1/scenic/areas");
}

export function fetchScenicArea(scenicSlug) {
  return request(`/api/v1/scenic/areas/${encodeURIComponent(scenicSlug)}`);
}

export function fetchScenicAttractions(scenicSlug) {
  return request(`/api/v1/scenic/areas/${encodeURIComponent(scenicSlug)}/attractions`);
}

export function fetchScenicAttraction(attractionId) {
  return request(`/api/v1/scenic/attractions/${encodeURIComponent(attractionId)}`);
}

export function planScenicRoute(payload) {
  return request("/api/v1/scenic/planner", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function fetchDashboard() {
  return request("/api/v1/admin/dashboard", { headers: authHeaders() });
}

export function fetchVoices() {
  return request("/api/v1/admin/voice/list", { headers: authHeaders() });
}

export function fetchAvatarRuntime() {
  return request("/api/v1/admin/avatar/runtime", { headers: authHeaders() });
}

export function refreshRuntimeCache() {
  return request("/api/v1/admin/cache/refresh", {
    method: "POST",
    headers: authHeaders(),
  });
}

export function updateAvatarRuntime(profileId) {
  return request("/api/v1/admin/avatar/runtime", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ profile_id: profileId }),
  });
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

export function fetchMemory3DStatus() {
  return request("/api/v1/memory3d/status", { headers: authHeaders() });
}

export function fetchMemory3DGallery() {
  return request("/api/v1/memory3d/gallery", { headers: authHeaders() });
}

export function fetchMemory3DTasks() {
  return request("/api/v1/memory3d/tasks", { headers: authHeaders() });
}

export function generateMemory3D(files) {
  const formData = new FormData();
  Array.from(files || []).forEach((file) => {
    formData.append("file", file);
  });
  return request("/api/v1/memory3d/generate", {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
}

export function cancelMemory3DTask(taskId) {
  return request(`/api/v1/memory3d/tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: "POST",
    headers: authHeaders(),
  });
}

export function deleteMemory3DModel(itemId) {
  return request(`/api/v1/memory3d/models/${encodeURIComponent(itemId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
}

export function updateMemory3DModelName(itemId, name) {
  return request(`/api/v1/memory3d/models/${encodeURIComponent(itemId)}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ name }),
  });
}

export async function fetchMemory3DBlob(url) {
  const response = await fetch(url, { headers: authHeaders() });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "Failed to load 3D memory asset");
  }
  return response.blob();
}
