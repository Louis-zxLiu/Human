import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { SparkRenderer, SplatFileType, SplatMesh } from "@sparkjsdev/spark";

import { ProductHeader } from "../components/ProductHeader";
import {
  cancelMemory3DTask,
  deleteMemory3DModel,
  fetchMemory3DBlob,
  fetchMemory3DGallery,
  fetchMemory3DStatus,
  fetchMemory3DTasks,
  generateMemory3D,
  getAuthToken,
  updateMemory3DModelName,
} from "../lib/api";
import { buildLoginHref } from "../lib/routes";

function formatSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function statusLabel(status) {
  const labels = {
    pending: "排队中",
    processing: "生成中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };
  return labels[status] || status || "未知";
}

function modelFormat(item) {
  return item?.model_url ? "ply" : "spz";
}

function modelUrl(item) {
  return item?.model_url || item?.spz_url || "";
}

function fileTypeFromFormat(format) {
  if (format === "spz") return SplatFileType.SPZ;
  if (format === "ply") return SplatFileType.PLY;
  return undefined;
}

const SHARP_VIEWER_CAMERA = {
  initialPosition: [0, 0, 1],
  cameraUp: [0, 1, 0],
  orbitTargetOffset: 10,
  fov: 50,
  near: 0.01,
  far: 1000,
  minDistance: 0.1,
  maxDistance: 20,
  dampingFactor: 0.05,
  frontLimits: {
    minAzimuth: -Math.PI / 4,
    maxAzimuth: Math.PI / 4,
    minPolar: Math.PI / 3,
    maxPolar: (2 * Math.PI) / 3,
  },
};

const SHARP_VIEWER_TRANSFORM = {
  position: [0, 0, 0],
  rotation: [Math.PI, 0, 0],
  scale: 2,
};

function applySharpViewerTransform(mesh) {
  mesh.position.set(...SHARP_VIEWER_TRANSFORM.position);
  mesh.rotation.set(...SHARP_VIEWER_TRANSFORM.rotation);
  mesh.scale.setScalar(SHARP_VIEWER_TRANSFORM.scale);
  mesh.updateMatrixWorld(true);
}

function getWorldBoundingBox(mesh) {
  if (!mesh || typeof mesh.getBoundingBox !== "function") return null;
  mesh.updateMatrixWorld(true);
  const rawBox = mesh.getBoundingBox();
  const box = rawBox?.clone ? rawBox.clone() : rawBox;
  if (!box || box.isEmpty?.()) return null;
  box.applyMatrix4(mesh.matrixWorld);
  return box;
}

function getSharpViewerReset(mesh, camera) {
  const targetPosition = new THREE.Vector3(...SHARP_VIEWER_CAMERA.initialPosition);
  let dynamicOffset = SHARP_VIEWER_CAMERA.orbitTargetOffset;

  try {
    const box = getWorldBoundingBox(mesh);
    if (box) {
      const frontZ = box.max.z;
      const distToFront = Math.max(0.1, targetPosition.z - frontZ);
      dynamicOffset = distToFront + 0.08 * Math.pow(distToFront, 2);
    }
  } catch (err) {
    console.warn("[Memory3D] Bounding box unavailable, using default camera target:", err);
  }

  return {
    position: targetPosition,
    target: targetPosition.clone().add(new THREE.Vector3(0, 0, -1).multiplyScalar(dynamicOffset)),
    near: SHARP_VIEWER_CAMERA.near,
    far: SHARP_VIEWER_CAMERA.far,
    minDistance: SHARP_VIEWER_CAMERA.minDistance,
    maxDistance: SHARP_VIEWER_CAMERA.maxDistance,
  };
}

function useProtectedObjectUrl(url) {
  const [objectUrl, setObjectUrl] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    let nextObjectUrl = "";
    setObjectUrl("");
    setError("");
    if (!url) return undefined;

    fetchMemory3DBlob(url)
      .then((blob) => {
        if (!alive) return;
        nextObjectUrl = URL.createObjectURL(blob);
        setObjectUrl(nextObjectUrl);
      })
      .catch((err) => {
        if (!alive) return;
        setError(err.message || "资源加载失败");
      });

    return () => {
      alive = false;
      if (nextObjectUrl) URL.revokeObjectURL(nextObjectUrl);
    };
  }, [url]);

  return { objectUrl, error };
}

function ProtectedImage({ src, alt, className }) {
  const { objectUrl } = useProtectedObjectUrl(src);
  if (!src) {
    return (
      <div className={`${className || ""} mem3d-thumb-placeholder`}>
        <i className="fas fa-cube" />
      </div>
    );
  }
  return objectUrl ? <img className={className} src={objectUrl} alt={alt} /> : <div className={`${className || ""} mem3d-thumb-placeholder`} />;
}

function Memory3DViewer({ item }) {
  const targetRef = useRef(null);
  const viewerRef = useRef(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [frontLocked, setFrontLocked] = useState(false);
  const selectedUrl = modelUrl(item);
  const selectedFormat = modelFormat(item);
  const { objectUrl, error: blobError } = useProtectedObjectUrl(selectedUrl);

  const disposeViewer = useCallback(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.renderer.setAnimationLoop(null);
    viewer.mesh?.dispose?.();
    viewer.controls?.dispose?.();
    viewer.renderer?.dispose?.();
    viewer.renderer?.domElement?.remove?.();
    viewerRef.current = null;
  }, []);

  const resetCamera = useCallback(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const reset = getSharpViewerReset(viewer.mesh, viewer.camera);
    viewer.camera.near = reset.near;
    viewer.camera.far = reset.far;
    viewer.camera.updateProjectionMatrix();
    viewer.camera.position.copy(reset.position);
    viewer.camera.up.set(...SHARP_VIEWER_CAMERA.cameraUp);
    viewer.controls.target.copy(reset.target);
    viewer.controls.minDistance = reset.minDistance;
    viewer.controls.maxDistance = reset.maxDistance;
    viewer.controls.update();
  }, []);

  useEffect(() => {
    if (!objectUrl || !targetRef.current) {
      disposeViewer();
      return undefined;
    }

    const container = targetRef.current;
    let cancelled = false;
    setLoading(true);
    setError("");
    disposeViewer();

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      SHARP_VIEWER_CAMERA.fov,
      Math.max(container.clientWidth, 1) / Math.max(container.clientHeight, 1),
      SHARP_VIEWER_CAMERA.near,
      SHARP_VIEWER_CAMERA.far,
    );
    camera.position.set(...SHARP_VIEWER_CAMERA.initialPosition);
    camera.up.set(...SHARP_VIEWER_CAMERA.cameraUp);

    const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = SHARP_VIEWER_CAMERA.dampingFactor;
    controls.maxDistance = SHARP_VIEWER_CAMERA.maxDistance;
    controls.minDistance = SHARP_VIEWER_CAMERA.minDistance;
    controls.maxPolarAngle = Math.PI;

    const sparkRenderer = new SparkRenderer({ renderer });
    scene.add(sparkRenderer);

    const resizeObserver = new ResizeObserver(() => {
      const width = container.clientWidth;
      const height = container.clientHeight;
      if (!width || !height) return;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    });
    resizeObserver.observe(container);

    const keyState = new Set();
    const onKeyDown = (event) => keyState.add(event.key.toLowerCase());
    const onKeyUp = (event) => keyState.delete(event.key.toLowerCase());
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);

    const moveCamera = () => {
      const speed = keyState.has("shift") ? 0.05 : 0.018;
      const right = new THREE.Vector3();
      const forward = new THREE.Vector3();
      camera.getWorldDirection(forward);
      right.crossVectors(forward, camera.up).normalize();
      forward.normalize();
      const delta = new THREE.Vector3();
      if (keyState.has("w")) delta.add(forward);
      if (keyState.has("s")) delta.sub(forward);
      if (keyState.has("d")) delta.add(right);
      if (keyState.has("a")) delta.sub(right);
      if (keyState.has("q")) delta.add(camera.up);
      if (keyState.has("e")) delta.sub(camera.up);
      if (delta.lengthSq() > 0) {
        delta.normalize().multiplyScalar(speed);
        camera.position.add(delta);
        controls.target.add(delta);
      }
    };

    renderer.setAnimationLoop(() => {
      moveCamera();
      controls.update();
      renderer.render(scene, camera);
    });

    const mesh = new SplatMesh({
      url: objectUrl,
      fileType: fileTypeFromFormat(selectedFormat),
    });
    applySharpViewerTransform(mesh);

    viewerRef.current = { camera, controls, renderer, scene, sparkRenderer, mesh };
    mesh.initialized
      .then(() => {
        if (cancelled) return;
        scene.add(mesh);
        applySharpViewerTransform(mesh);
        sparkRenderer.sortDirty = true;
        setLoading(false);
        resetCamera();
      })
      .catch((err) => {
        if (cancelled) return;
        setLoading(false);
        setError(err.message || "模型加载失败");
      });

    return () => {
      cancelled = true;
      resizeObserver.disconnect();
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      disposeViewer();
    };
  }, [disposeViewer, objectUrl, resetCamera, selectedFormat]);

  const toggleFront = useCallback(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const next = !frontLocked;
    setFrontLocked(next);
    viewer.controls.minAzimuthAngle = next ? SHARP_VIEWER_CAMERA.frontLimits.minAzimuth : -Infinity;
    viewer.controls.maxAzimuthAngle = next ? SHARP_VIEWER_CAMERA.frontLimits.maxAzimuth : Infinity;
    viewer.controls.minPolarAngle = next ? SHARP_VIEWER_CAMERA.frontLimits.minPolar : 0;
    viewer.controls.maxPolarAngle = next ? SHARP_VIEWER_CAMERA.frontLimits.maxPolar : Math.PI;
    resetCamera();
  }, [frontLocked, resetCamera]);

  return (
    <div className="mem3d-viewer">
      <div ref={targetRef} className="mem3d-viewer__canvas" />
      {!item ? (
        <div className="mem3d-viewer__empty">
          <i className="fas fa-cube" />
          <strong>选择一个 3D 记忆</strong>
          <span>上传照片生成模型后，可在这里在线预览高斯溅射场景。</span>
        </div>
      ) : null}
      {loading ? <div className="mem3d-viewer__overlay">正在加载模型...</div> : null}
      {blobError || error ? <div className="mem3d-viewer__error">{blobError || error}</div> : null}
      <div className="mem3d-viewer__toolbar">
        <button type="button" onClick={resetCamera} disabled={!item} title="重置视角">
          <i className="fas fa-rotate-left" />
        </button>
        <button type="button" onClick={toggleFront} disabled={!item} className={frontLocked ? "is-active" : ""} title="正面视角">
          <i className="fas fa-crosshairs" />
        </button>
        <button type="button" onClick={() => targetRef.current?.requestFullscreen?.()} disabled={!item} title="鍏ㄥ睆">
          <i className="fas fa-expand" />
        </button>
      </div>
    </div>
  );
}

function TaskRow({ task, onCancel }) {
  const canCancel = task.status === "pending" || task.status === "processing";
  return (
    <div className={`mem3d-task mem3d-task--${task.status}`}>
      <div className="mem3d-task__top">
        <strong>{task.original_filename || task.filename}</strong>
        <span>{statusLabel(task.status)}</span>
      </div>
      <div className="mem3d-task__bar">
        <i style={{ width: `${Math.max(0, Math.min(100, task.progress || 0))}%` }} />
      </div>
      <div className="mem3d-task__meta">
        <small>{task.stage || "queued"}</small>
        {canCancel ? <button type="button" onClick={() => onCancel(task.id)}>取消</button> : null}
      </div>
      {task.error ? <p>{task.error}</p> : null}
    </div>
  );
}

function ModelCard({ item, active, onSelect, onDelete, onRename }) {
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState(item.name || "");

  useEffect(() => {
    setDraftName(item.name || "");
  }, [item.name]);

  const saveName = async () => {
    const nextName = draftName.trim();
    if (!nextName || nextName === item.name) {
      setDraftName(item.name || "");
      setEditing(false);
      return;
    }
    await onRename(item.id, nextName);
    setEditing(false);
  };

  return (
    <div
      role="button"
      tabIndex={0}
      className={`mem3d-model ${active ? "is-active" : ""}`}
      onClick={() => {
        if (!editing) onSelect(item);
      }}
      onKeyDown={(event) => {
        if (!editing && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onSelect(item);
        }
      }}
    >
      <ProtectedImage src={item.thumb_url || item.image_url} alt={item.name} className="mem3d-model__thumb" />
      <span className="mem3d-model__body">
        {editing ? (
          <input
            className="mem3d-model__name-input"
            value={draftName}
            autoFocus
            maxLength={80}
            onClick={(event) => event.stopPropagation()}
            onChange={(event) => setDraftName(event.target.value)}
            onKeyDown={(event) => {
              event.stopPropagation();
              if (event.key === "Enter") saveName();
              if (event.key === "Escape") {
                setDraftName(item.name || "");
                setEditing(false);
              }
            }}
          />
        ) : (
          <strong>{item.name}</strong>
        )}
        <small>{item.spz_url ? "SPZ + PLY" : "PLY"} {formatSize(item.spz_size || item.size)}</small>
      </span>
      <span className="mem3d-model__actions">
        {editing ? (
          <>
            <span
              role="button"
              tabIndex={0}
              className="mem3d-model__icon"
              title="保存名称"
              onClick={(event) => {
                event.stopPropagation();
                saveName();
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  event.stopPropagation();
                  saveName();
                }
              }}
            >
              <i className="fas fa-check" />
            </span>
            <span
              role="button"
              tabIndex={0}
              className="mem3d-model__icon"
              title="取消"
              onClick={(event) => {
                event.stopPropagation();
                setDraftName(item.name || "");
                setEditing(false);
              }}
            >
              <i className="fas fa-xmark" />
            </span>
          </>
        ) : (
          <>
            <span
              role="button"
              tabIndex={0}
              className="mem3d-model__icon"
              title="修改名称"
              onClick={(event) => {
                event.stopPropagation();
                setEditing(true);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  event.stopPropagation();
                  setEditing(true);
                }
              }}
            >
              <i className="fas fa-pen" />
            </span>
            <span
              role="button"
              tabIndex={0}
              className="mem3d-model__delete"
              title="删除"
              onClick={(event) => {
                event.stopPropagation();
                onDelete(item.id);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  event.stopPropagation();
                  onDelete(item.id);
                }
              }}
            >
              <i className="fas fa-trash" />
            </span>
          </>
        )}
      </span>
    </div>
  );
}

export function Memory3DApp() {
  const token = getAuthToken();
  const [status, setStatus] = useState(null);
  const [gallery, setGallery] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [hasActiveTasks, setHasActiveTasks] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef(null);

  const selectedItem = useMemo(
    () => gallery.find((item) => item.id === selectedId) || gallery[0] || null,
    [gallery, selectedId],
  );

  const loadStatus = useCallback(() => {
    if (!token) return Promise.resolve();
    return fetchMemory3DStatus()
      .then(setStatus)
      .catch((err) => setError(err.message));
  }, [token]);

  const loadGallery = useCallback(() => {
    if (!token) return Promise.resolve();
    return fetchMemory3DGallery()
      .then((items) => {
        setGallery(Array.isArray(items) ? items : []);
      })
      .catch((err) => setError(err.message));
  }, [token]);

  const loadTasks = useCallback(() => {
    if (!token) return Promise.resolve();
    return fetchMemory3DTasks()
      .then((payload) => {
        setTasks(payload.tasks || []);
        setHasActiveTasks(Boolean(payload.has_active));
        if (!payload.has_active) loadGallery();
      })
      .catch((err) => setError(err.message));
  }, [loadGallery, token]);

  useEffect(() => {
    if (!token) return;
    loadStatus();
    loadGallery();
    loadTasks();
  }, [loadGallery, loadStatus, loadTasks, token]);

  useEffect(() => {
    if (!token) return undefined;
    const interval = window.setInterval(() => {
      loadStatus();
      loadTasks();
    }, hasActiveTasks ? 2000 : 10000);
    return () => window.clearInterval(interval);
  }, [hasActiveTasks, loadStatus, loadTasks, token]);

  useEffect(() => {
    if (selectedId || !gallery[0]) return;
    setSelectedId(gallery[0].id);
  }, [gallery, selectedId]);

  const uploadFiles = useCallback(async (files) => {
    const images = Array.from(files || []).filter((file) => file.type.startsWith("image/"));
    if (!images.length) return;
    setUploading(true);
    setError("");
    try {
      await generateMemory3D(images);
      await loadTasks();
    } catch (err) {
      setError(err.message);
      await loadStatus();
    } finally {
      setUploading(false);
    }
  }, [loadStatus, loadTasks]);

  const handleDrop = useCallback((event) => {
    event.preventDefault();
    setDragging(false);
    uploadFiles(event.dataTransfer.files);
  }, [uploadFiles]);

  const handleDelete = useCallback(async (itemId) => {
    if (!window.confirm("删除这个 3D 记忆吗？")) return;
    try {
      await deleteMemory3DModel(itemId);
      if (selectedId === itemId) setSelectedId("");
      await loadGallery();
      await loadTasks();
    } catch (err) {
      setError(err.message);
    }
  }, [loadGallery, loadTasks, selectedId]);

  const handleRename = useCallback(async (itemId, name) => {
    try {
      const updatedItem = await updateMemory3DModelName(itemId, name);
      setGallery((items) => items.map((item) => (item.id === itemId ? { ...item, ...updatedItem } : item)));
    } catch (err) {
      setError(err.message);
      throw err;
    }
  }, []);

  const handleCancel = useCallback(async (taskId) => {
    try {
      await cancelMemory3DTask(taskId);
      await loadTasks();
    } catch (err) {
      setError(err.message);
    }
  }, [loadTasks]);

  if (!token) {
    return (
      <div className="mem3d-page product-page">
        <div className="page-container">
          <ProductHeader active="memory3d" />
          <main className="mem3d-login panel">
            <i className="fas fa-lock" />
            <h1>登录后创建 3D 记忆</h1>
            <p>上传照片、生成高斯溅射模型和在线预览需要登录，以便保护游客影像和生成结果。</p>
            <a className="button-primary" href={buildLoginHref("/memory-3d")}>去登录</a>
          </main>
        </div>
      </div>
    );
  }

  return (
    <div className="mem3d-page product-page">
      <div className="page-container">
        <ProductHeader active="memory3d" />
        <main className="mem3d-shell">
          <aside className="mem3d-sidebar panel">
            <section className="mem3d-intro">
              <span className={`mem3d-status-dot ${status?.engine_ready ? "is-ready" : "is-offline"}`} />
              <div>
                <p className="eyebrow">3D MEMORY</p>
                <h1>3D记忆</h1>
                <span>{status?.message || "正在检查生成引擎..."}</span>
              </div>
            </section>

            <section
              className={`mem3d-upload ${dragging ? "is-dragging" : ""} ${!status?.engine_ready ? "is-disabled" : ""}`}
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={status?.engine_ready ? handleDrop : (event) => event.preventDefault()}
            >
              <i className="fas fa-cloud-arrow-up" />
              <strong>{uploading ? "正在提交..." : "上传照片生成 3D 高斯溅射"}</strong>
              <span>支持 JPG、PNG、WEBP，可拖拽多张图片加入队列。</span>
              <button
                type="button"
                className="button-primary"
                disabled={!status?.engine_ready || uploading}
                onClick={() => fileInputRef.current?.click()}
              >
                {status?.engine_ready ? "选择照片" : "生成引擎未就绪"}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                multiple
                hidden
                onChange={(event) => uploadFiles(event.target.files)}
              />
            </section>

            {error ? <div className="feedback feedback-danger">{error}</div> : null}

            <section className="mem3d-section">
              <div className="mem3d-section__title">
                <strong>任务队列</strong>
                <span>{tasks.length}</span>
              </div>
              <div className="mem3d-task-list">
                {tasks.length ? tasks.map((task) => <TaskRow key={task.id} task={task} onCancel={handleCancel} />) : <p className="mem3d-empty-copy">暂无生成任务</p>}
              </div>
            </section>

            <section className="mem3d-section mem3d-section--models">
              <div className="mem3d-section__title">
                <strong>模型图库</strong>
                <span>{gallery.length}</span>
              </div>
              <div className="mem3d-model-list">
                {gallery.length ? gallery.map((item) => (
                  <ModelCard
                    key={item.id}
                    item={item}
                    active={selectedItem?.id === item.id}
                    onSelect={(nextItem) => setSelectedId(nextItem.id)}
                    onDelete={handleDelete}
                    onRename={handleRename}
                  />
                )) : <p className="mem3d-empty-copy">生成完成后会出现在这里</p>}
              </div>
            </section>
          </aside>

          <section className="mem3d-stage panel">
            <div className="mem3d-stage__header">
              <div>
                <p className="eyebrow">ONLINE PREVIEW</p>
                <h2>{selectedItem?.name || "在线预览"}</h2>
              </div>
              <div className="mem3d-stage__meta">
                <span>{selectedItem ? modelFormat(selectedItem).toUpperCase() : "WAITING"}</span>
                <span>鼠标 / 触摸 / WASD</span>
              </div>
            </div>
            <Memory3DViewer item={selectedItem} />
          </section>
        </main>
      </div>
    </div>
  );
}
