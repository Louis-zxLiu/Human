export function normalizePathname(pathname) {
  const normalized = String(pathname || "/").trim() || "/";
  if (normalized.length > 1 && normalized.endsWith("/")) {
    return normalized.slice(0, -1);
  }
  return normalized;
}

export function safeInternalPath(value, fallback = "/") {
  const input = String(value || "").trim();
  if (!input.startsWith("/") || input.startsWith("//")) return fallback;
  return input;
}

export function buildScenicHref(scenicSlug) {
  return `/scenic/${encodeURIComponent(scenicSlug)}`;
}

export function buildAttractionHref(scenicSlug, attractionId) {
  return `${buildScenicHref(scenicSlug)}/attractions/${encodeURIComponent(attractionId)}`;
}

export function buildPlannerHref(scenicSlug = "") {
  return scenicSlug ? `/planner?scenicSlug=${encodeURIComponent(scenicSlug)}` : "/planner";
}

export function buildGuideHref({
  scenicSlug = "",
  scenicName = "",
  attractionId = "",
  attractionName = "",
  routeLabel = "",
  routeTitle = "",
  prompt = "",
} = {}) {
  const params = new URLSearchParams();
  if (scenicSlug) params.set("scenicSlug", scenicSlug);
  if (scenicName) params.set("scenicName", scenicName);
  if (attractionId) params.set("attractionId", attractionId);
  if (attractionName) params.set("attractionName", attractionName);
  if (routeLabel) params.set("routeLabel", routeLabel);
  if (routeTitle) params.set("routeTitle", routeTitle);
  if (prompt) params.set("prompt", prompt);
  const search = params.toString();
  return search ? `/guide?${search}` : "/guide";
}

export function buildMemory3DHref() {
  return "/memory-3d";
}

export function buildLoginHref(nextPath) {
  const params = new URLSearchParams();
  params.set("next", safeInternalPath(nextPath, "/guide"));
  return `/login?${params.toString()}`;
}

export function currentGuidePath() {
  return `${window.location.pathname}${window.location.search || ""}`;
}

export function readGuideContext(search = window.location.search) {
  const params = new URLSearchParams(search || "");
  return {
    scenicSlug: params.get("scenicSlug") || "",
    scenicName: params.get("scenicName") || "",
    attractionId: params.get("attractionId") || "",
    attractionName: params.get("attractionName") || "",
    routeLabel: params.get("routeLabel") || "",
    routeTitle: params.get("routeTitle") || "",
    prompt: params.get("prompt") || "",
  };
}
