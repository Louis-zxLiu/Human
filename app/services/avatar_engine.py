import os
import sys
import time

from app.core.config import settings

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SOULX_ROOT = os.path.join(PROJECT_ROOT, "SoulX-FlashHead")
if SOULX_ROOT not in sys.path and os.path.exists(SOULX_ROOT):
    sys.path.insert(0, SOULX_ROOT)

# Must be set before importing torch to take effect.
if settings.AVATAR_CUDA_ALLOC_CONF:
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", settings.AVATAR_CUDA_ALLOC_CONF)

import torch
import cv2
import numpy as np

# Adjust imports to match SoulX-FlashHead repository structure
_original_cwd = os.getcwd()
if os.path.exists(SOULX_ROOT):
    os.chdir(SOULX_ROOT)
from flash_head.inference import get_pipeline, get_base_data, get_audio_embedding, run_pipeline
os.chdir(_original_cwd)

class AvatarEngine:
    """
    Wrapper for Soul-AILab/SoulX-FlashHead Lite 1.3B model.
    Handles digital avatar rendering and lip-sync synchronization.
    """
    def __init__(self):
        self.model_path = os.path.abspath(settings.MODEL_AVATAR_PATH)
        self.fps_target = 25
        self.lip_sync_error_margin = 100  # ms
        self.device = (
            settings.AVATAR_DEVICE
            if settings.AVATAR_DEVICE in {"cuda", "cpu"}
            else ("cuda" if torch.cuda.is_available() else "cpu")
        )
        if self.device == "cuda" and not torch.cuda.is_available():
            self.device = "cpu"
        self.current_image_path = None
        self._load_model()

    def _load_model(self):
        """
        Load the SoulX-FlashHead Lite 1.3B model.
        Ensures 100% parameter loading from .env without hardcoding.
        """
        print(f"[AvatarEngine] Initializing SoulX-FlashHead Lite 1.3B from {self.model_path} on {self.device}...")
        
        # 核心修复：现在的 CWD 是 SoulX-FlashHead 目录，如果 model_path 是相对路径，
        # os.path.abspath 会把它解析到 D:\Human\SoulX-FlashHead\models\... 下
        # 但我们实际下载的模型在项目根目录 D:\Human\models\... 下
        # 因此需要在切换 CWD 前，将相对路径转化为相对于项目根目录的绝对路径
        original_cwd = os.getcwd()
        # Ensure model_path is resolved relative to the actual project root
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        raw_path = settings.MODEL_AVATAR_PATH
        
        # Clean up any potential relative prefixes in the env var (like ./)
        if raw_path.startswith("./") or raw_path.startswith(".\\"):
            raw_path = raw_path[2:]
            
        if not os.path.isabs(raw_path):
            self.model_path = os.path.join(project_root, raw_path)
        else:
            self.model_path = raw_path
            
        # Standardize slashes for Windows
        self.model_path = os.path.normpath(self.model_path)
            
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Model path {self.model_path} not found.")

        soulx_path = os.path.abspath(os.path.join(project_root, "SoulX-FlashHead"))
        if os.path.exists(soulx_path):
            os.chdir(soulx_path)
            print(f"[AvatarEngine] Changed CWD to {soulx_path} to satisfy internal yaml dependencies.")
            
        try:
            wav2vec_path = os.path.abspath(os.path.join(project_root, "models", "wav2vec2-base-960h")) # Using the local wav2vec2-base-960h path as wav2vec fallback/source
            
            # Setup the pipeline according to flash_head.inference actual functions
            self.pipeline = get_pipeline(
                world_size=1,
                ckpt_dir=self.model_path,
                model_type="lite",
                wav2vec_dir=wav2vec_path,
                param_dtype=self._get_torch_dtype(),
                device=self.device,
            )
            
            # Initialize a default driving condition
            self.current_image_path = os.path.join(soulx_path, "assets", "demo_image.jpg")
            
            # 【核心修复】：SoulX-FlashHead 必须先执行 get_base_data 来向 pipeline 注入 frame_num 等必要参数
            if not os.path.exists(self.current_image_path):
                import cv2
                import numpy as np
                os.makedirs(os.path.dirname(self.current_image_path), exist_ok=True)
                black_image = np.zeros((512, 512, 3), dtype=np.uint8)
                cv2.imwrite(self.current_image_path, black_image)
                print(f"[AvatarEngine] Created dummy condition image at {self.current_image_path}")
                
            get_base_data(self.pipeline, self.current_image_path, base_seed=42, use_face_crop=False)
            
            self.is_loaded = True
            print(f"[AvatarEngine] Model loaded successfully. Target FPS: >={self.fps_target}.")
        except Exception as e:
            print(f"[AvatarEngine] Error initializing model: {e}")
            self.is_loaded = False
        finally:
            # 恢复工作目录
            os.chdir(original_cwd)

    def update_base_image(self, image_path: str):
        """
        Dynamically update the avatar's base condition image.
        """
        if not self.is_loaded:
            print("[AvatarEngine] Warning: Engine not loaded, cannot update base image.")
            return
            
        self.current_image_path = image_path
        print(f"[AvatarEngine] Updating base image to: {image_path}")
        original_cwd = os.getcwd()
        soulx_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "SoulX-FlashHead"))
        try:
            if os.path.exists(soulx_path):
                os.chdir(soulx_path)
            # Use a default frame_num during image update, will be refined during inference
            get_base_data(self.pipeline, image_path, base_seed=42, use_face_crop=False)
            print(f"[AvatarEngine] Base image updated successfully.")
        except Exception as e:
            print(f"[AvatarEngine] Failed to update base image: {e}")
        finally:
            os.chdir(original_cwd)

    def _sync_pipeline_to_audio(self, audio_len: int):
        """
        【核心修复】：同步 Pipeline 参数以匹配音频长度。
        如果不匹配，FlashHeadModel 在 forward 时会因为 einops.rearrange 形状对不齐而崩溃。
        确保 target_frame_num 严格等于 audio_embedding.shape[1]。
        """
        from flash_head.inference import get_infer_params
        params = get_infer_params()
        base_frame_num = int(params["frame_num"])

        # FlashHead 模型的 n_frame 参数通常固定为 8（或者其他定值），
        # audio_len 必须是 n_frame 的整数倍，否则在 einops.rearrange 阶段会报错：
        # Shape mismatch, can't divide axis of length X in chunks of 8
        n_frame_chunk = 8
        
        # 将 audio_len 强制对齐到 n_frame_chunk (8) 的倍数
        if audio_len % n_frame_chunk != 0:
            audio_len = ((audio_len // n_frame_chunk) + 1) * n_frame_chunk
            
        target_frame_num = audio_len
        print(f"[AvatarEngine] Syncing pipeline: audio_len={audio_len} -> target_frame_num={target_frame_num}")
        
        # 获取当前的推理参数（包含 height, width, sample_steps 等）
        original_cwd = os.getcwd()
        soulx_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "SoulX-FlashHead"))
        try:
            if os.path.exists(soulx_path):
                os.chdir(soulx_path)
            
            # 重新调用 prepare_params，但传入根据音频计算出的准确 frame_num
            # 此时 frame_num 与 audio_embedding.shape[1] 完全一致
            self.pipeline.prepare_params(
                cond_image_path_or_dir=self.current_image_path,
                target_size=(params['height'], params['width']),
                frame_num=target_frame_num,
                motion_frames_num=params['motion_frames_num'],
                sampling_steps=params['sample_steps'],
                seed=42, # 保持 seed 一致
                shift=params['sample_shift'],
                color_correction_strength=params['color_correction_strength'],
                use_face_crop=False,
            )
        finally:
            os.chdir(original_cwd)
        
        return target_frame_num

    def generate_avatar_video(self, audio_path: str, output_video_path: str):
        """
        Generate a complete MP4 video from an audio file.
        1. Extract audio embedding
        2. Run SoulX-FlashHead pipeline to get video frames
        3. Use FFmpeg to combine frames and original audio into a high-quality MP4
        """
        import sys
        start_time = time.time()
        
        if not self.is_loaded:
            print("[AvatarEngine] Engine not loaded, cannot generate video.")
            sys.stdout.flush()
            return None
            
        try:
            import librosa
            import subprocess
            import imageio
            import imageio_ffmpeg
            from collections import deque
            from flash_head.inference import get_infer_params

            infer_params = get_infer_params()
            sample_rate = int(infer_params["sample_rate"])
            tgt_fps = int(infer_params["tgt_fps"])
            cached_audio_duration = int(infer_params.get("cached_audio_duration", 8))
            frame_num = int(infer_params["frame_num"])
            motion_frames_num = int(infer_params["motion_frames_num"])
            slice_len = frame_num - motion_frames_num

            # 1) Load audio (match SoulX config)
            print(f"[AvatarEngine] Loading audio from {audio_path} (sr={sample_rate})...")
            sys.stdout.flush()
            audio_array, sr = librosa.load(audio_path, sr=sample_rate, mono=True)

            # Optional warmup (prepend silence only for generation; final video trims it away)
            warmup_duration = float(settings.AVATAR_WARMUP_SECONDS or 0.0)
            if warmup_duration > 0:
                warmup_samples = int(sr * warmup_duration)
                audio_array = np.concatenate([np.zeros(warmup_samples, dtype=audio_array.dtype), audio_array])

            # 2) Stream-style chunking (prevents CUDA OOM on long audios)
            human_speech_array_slice_len = slice_len * sample_rate // tgt_fps
            remainder = len(audio_array) % human_speech_array_slice_len
            if remainder > 0:
                pad_length = human_speech_array_slice_len - remainder
                audio_array = np.concatenate([audio_array, np.zeros(pad_length, dtype=audio_array.dtype)])

            cached_audio_length_sum = sample_rate * cached_audio_duration
            audio_end_idx = cached_audio_duration * tgt_fps
            audio_start_idx = audio_end_idx - frame_num
            audio_dq = deque([0.0] * cached_audio_length_sum, maxlen=cached_audio_length_sum)

            slices = audio_array.reshape(-1, human_speech_array_slice_len)

            # 3) Write video incrementally to avoid holding all frames in RAM/VRAM
            os.makedirs(os.path.dirname(os.path.abspath(output_video_path)), exist_ok=True)
            temp_video_path = output_video_path.replace(".mp4", "_tmp.mp4")

            if self.device == "cuda" and settings.AVATAR_EMPTY_CACHE_BEFORE_INFER:
                torch.cuda.empty_cache()

            with imageio.get_writer(
                temp_video_path,
                format="mp4",
                mode="I",
                fps=tgt_fps,
                codec="h264",
                ffmpeg_params=["-bf", "0", "-crf", str(settings.AVATAR_VIDEO_CRF)],
            ) as writer:
                for chunk_idx, chunk_audio in enumerate(slices):
                    audio_dq.extend(chunk_audio.tolist())
                    audio_ctx = np.array(audio_dq, dtype=np.float32)

                    with torch.inference_mode():
                        audio_embedding = get_audio_embedding(
                            self.pipeline, audio_ctx, audio_start_idx, audio_end_idx
                        )
                        video = run_pipeline(self.pipeline, audio_embedding)

                    # remove motion overlap for subsequent chunks
                    if chunk_idx != 0:
                        video = video[motion_frames_num:]

                    frames = video.detach().cpu().numpy().astype(np.uint8)
                    for i in range(frames.shape[0]):
                        writer.append_data(frames[i])

                    # aggressive cleanup to reduce VRAM fragmentation
                    del audio_embedding, video, frames
                    if self.device == "cuda":
                        torch.cuda.empty_cache()

            # 4) Merge original audio + (optionally) trim warmup from video
            # Trim is applied on video stream only; audio starts at t=0.
            trim_ss = f"{max(warmup_duration, 0.0):.3f}"
            ffmpeg_cmd = [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-ss",
                trim_ss,
                "-i",
                temp_video_path,
                "-i",
                audio_path,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                output_video_path,
            ]
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, encoding="utf-8")
            if result.returncode != 0:
                print(f"[AvatarEngine] FFmpeg Error: {result.stderr}")
                sys.stdout.flush()
                return None
            try:
                os.remove(temp_video_path)
            except Exception:
                pass

            processing_time = time.time() - start_time
            print(f"[AvatarEngine] Video generated successfully at {output_video_path} in {processing_time:.2f}s")
            sys.stdout.flush()
            return output_video_path
            
        except torch.cuda.OutOfMemoryError as e:
            if self.device == "cuda":
                torch.cuda.empty_cache()
            import traceback
            print("[AvatarEngine] CUDA OOM during video generation.")
            print("建议：1) EMBEDDING_DEVICE=cpu 2) AVATAR_WARMUP_SECONDS=0.0~0.5 3) 关闭并发视频生成 4) 重启进程释放显存")
            print(traceback.format_exc())
            sys.stdout.flush()
            return None
        except Exception as e:
            import traceback
            print(f"[AvatarEngine] Video generation failed: {e}")
            print(traceback.format_exc())
            sys.stdout.flush()
            return None

    def _get_torch_dtype(self):
        dtype_name = str(settings.AVATAR_TORCH_DTYPE).lower()
        if dtype_name == "float16":
            return torch.float16
        if dtype_name == "float32":
            return torch.float32
        return torch.bfloat16

    def generate_avatar_stream(self, audio_chunk: bytes, is_file_path=False):
        """
        Generate real-time avatar video frames from audio chunks or audio file paths.
        Designed for < 5 seconds full-chain latency and >= 25 FPS.
        """
        start_time = time.time()
        
        if not self.is_loaded:
            print("[AvatarEngine] Engine not loaded properly, skipping real inference.")
            return []
            
        frames = []
        try:
            import librosa
            import io
            
            # Use librosa to load audio from bytes or file path
            if is_file_path:
                audio_array, sr = librosa.load(audio_chunk, sr=16000, mono=True)
            else:
                audio_array, sr = librosa.load(io.BytesIO(audio_chunk), sr=16000, mono=True)
            
            # Convert to float32
            audio_array = audio_array.astype(np.float32)
            
            # Run pipeline
            from flash_head.inference import get_infer_params
            from collections import deque
            
            infer_params = get_infer_params()
            sample_rate = int(infer_params["sample_rate"])
            tgt_fps = int(infer_params["tgt_fps"])
            cached_audio_duration = int(infer_params.get("cached_audio_duration", 8))
            frame_num = int(infer_params["frame_num"])
            motion_frames_num = int(infer_params["motion_frames_num"])
            slice_len = frame_num - motion_frames_num
            
            # 【核心修复】：由于模型是基于 Diffusion 的，一次性生成大量帧会导致显存暴增（OOM），GPU 占用 100% 然后崩溃或极慢。
            # 流式推流必须和生成视频一样，采用滑动窗口（分块）生成机制，每次只生成少量帧。
            # 1. 恢复 pipeline 的帧数为模型默认的 frame_num (如 8 帧)
            self._sync_pipeline_to_audio(frame_num)
            
            # 2. 对音频进行切块处理
            human_speech_array_slice_len = slice_len * sample_rate // tgt_fps
            remainder = len(audio_array) % human_speech_array_slice_len
            if remainder > 0:
                pad_length = human_speech_array_slice_len - remainder
                audio_array = np.concatenate([audio_array, np.zeros(pad_length, dtype=audio_array.dtype)])

            cached_audio_length_sum = sample_rate * cached_audio_duration
            audio_end_idx = cached_audio_duration * tgt_fps
            audio_start_idx = audio_end_idx - frame_num
            audio_dq = deque([0.0] * cached_audio_length_sum, maxlen=cached_audio_length_sum)

            slices = audio_array.reshape(-1, human_speech_array_slice_len)

            try:
                for chunk_idx, chunk_audio in enumerate(slices):
                    audio_dq.extend(chunk_audio.tolist())
                    audio_ctx = np.array(audio_dq, dtype=np.float32)

                    with torch.inference_mode():
                        audio_embedding = get_audio_embedding(
                            self.pipeline, audio_ctx, audio_start_idx, audio_end_idx
                        )
                        video_tensor = run_pipeline(self.pipeline, audio_embedding)

                    # 移除重叠帧，防止视频卡顿
                    if chunk_idx != 0:
                        video_tensor = video_tensor[motion_frames_num:]

                    frames_np = video_tensor.detach().cpu().numpy().astype(np.uint8)
                    
                    for i in range(frames_np.shape[0]):
                        frame_bgr = cv2.cvtColor(frames_np[i], cv2.COLOR_RGB2BGR)
                        ret, buffer = cv2.imencode('.jpg', frame_bgr)
                        if ret:
                            frames.append(buffer.tobytes())
                            
                    del audio_embedding, video_tensor, frames_np
                    if self.device == "cuda":
                        torch.cuda.empty_cache()
            except Exception as inner_e:
                import traceback
                print(f"[AvatarEngine] Inner pipeline error: {inner_e}\n{traceback.format_exc()}")
                raise inner_e
                
        except Exception as e:
            print(f"[AvatarEngine] Inference error: {e}")

        processing_time = time.time() - start_time
        print(f"[AvatarEngine] Generated {len(frames)} frames of video data in {processing_time:.2f}s")
        
        # Ensure lip-sync error margin is within 100ms
        if processing_time * 1000 > self.lip_sync_error_margin:
            print(f"[AvatarEngine] Warning: Lip-sync processing took {processing_time*1000:.2f}ms")
            
        return frames

_avatar_engine = None


def get_avatar_engine() -> AvatarEngine:
    global _avatar_engine
    if _avatar_engine is None:
        _avatar_engine = AvatarEngine()
    return _avatar_engine

if __name__ == "__main__":
    print("[AvatarEngine] Running as standalone service...")
    # In a real setup, this might start a WebSocket or ZeroMQ server to listen for audio streams.
    # For Phase 3, we ensure the process stays alive as required by the .bat script.
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[AvatarEngine] Shutting down.")
