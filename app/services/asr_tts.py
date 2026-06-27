import os
import subprocess
import numpy as np
import torch
import imageio_ffmpeg

from app.core.config import resolve_path, settings

_simplified_converter = None


def normalize_asr_text(text: str) -> str:
    """
    Normalize ASR text before it enters chat/RAG.
    """
    normalized = str(text or "").strip()
    if not normalized:
        return ""

    try:
        from opencc import OpenCC
    except Exception:
        return normalized

    global _simplified_converter
    if _simplified_converter is None:
        _simplified_converter = OpenCC("t2s")
    return _simplified_converter.convert(normalized).strip()


class ASRService:
    """
    Wrapper for Whisper (ASR)
    """
    def __init__(self):
        self.model_name = settings.MODEL_ASR_PATH
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._load_model()

    def _load_model(self):
        print(f"[ASR] Loading Whisper model: {self.model_name}")
        import whisper

        download_root = resolve_path(settings.WHISPER_DOWNLOAD_DIR)
        os.makedirs(download_root, exist_ok=True)
        self.model = whisper.load_model(self.model_name, device=self.device, download_root=download_root)
        self.is_loaded = True

    def _decode_audio(self, audio_path: str) -> np.ndarray:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe,
            "-nostdin",
            "-threads",
            "0",
            "-i",
            audio_path,
            "-f",
            "s16le",
            "-ac",
            "1",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-",
        ]
        out = subprocess.run(cmd, capture_output=True, check=True).stdout
        audio = np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0
        return audio

    def _validate_audio(self, audio_array: np.ndarray) -> None:
        duration = len(audio_array) / 16000.0
        rms = float(np.sqrt(np.mean(np.square(audio_array)))) if audio_array.size else 0.0
        peak = float(np.max(np.abs(audio_array))) if audio_array.size else 0.0
        print(f"[ASR] decoded audio duration={duration:.2f}s rms={rms:.4f} peak={peak:.4f}")
        if duration < float(settings.ASR_MIN_AUDIO_SECONDS):
            raise ValueError("Audio is too short for reliable ASR")
        if rms < float(settings.ASR_MIN_RMS) and peak < float(settings.ASR_MIN_RMS) * 3:
            raise ValueError("Audio is too quiet for reliable ASR")

    def transcribe(self, audio_path: str) -> str:
        """
        Transcribe audio file to text.
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        print(f"[ASR] Transcribing {audio_path}...")
        audio_array = self._decode_audio(audio_path)
        self._validate_audio(audio_array)
        result = self.model.transcribe(audio_array, language=settings.ASR_LANGUAGE)
        raw_text = str(result.get("text") or "").strip()
        text = normalize_asr_text(raw_text)
        if raw_text != text:
            print(f"[ASR] normalized='{raw_text}' -> '{text}'")
        print(f"[ASR] result='{text}'")
        return text

class TTSService:
    """
    Wrapper for Edge-TTS (Online, High-quality)
    """
    def __init__(self):
        print(f"[TTS] Initializing Edge-TTS (requires internet)...")
        import edge_tts  # noqa: F401

        self.voice = "zh-CN-XiaoxiaoNeural"  # Default high-quality Chinese female voice
        self.is_loaded = True
        self.available_voices = [
            {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓 (女声，温柔亲切)"},
            {"id": "zh-CN-XiaoyiNeural", "name": "晓伊 (女声，活泼童声)"},
            {"id": "zh-CN-YunjianNeural", "name": "云健 (男声，影视解说)"},
            {"id": "zh-CN-YunxiNeural", "name": "云希 (男声，阳光青年)"},
            {"id": "zh-CN-YunxiaNeural", "name": "云夏 (男声，少年阳光)"},
            {"id": "zh-CN-YunyangNeural", "name": "云扬 (男声，新闻播音)"},
            {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "晓北 (女声，东北口音)"},
            {"id": "zh-CN-shaanxi-XiaoniNeural", "name": "晓妮 (女声，陕西口音)"}
        ]

    def set_voice(self, voice_id: str):
        if any(v["id"] == voice_id for v in self.available_voices):
            self.voice = voice_id
            print(f"[TTS] Voice changed to: {self.voice}")
            return True
        return False
        
    def get_current_voice(self):
        return self.voice

    def _prepend_leading_silence(self, audio_path: str) -> None:
        silence_ms = max(0, int(settings.TTS_LEADING_SILENCE_MS or 0))
        if silence_ms <= 0:
            return

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        temp_output_path = f"{audio_path}.lead.mp3"
        delay = f"{silence_ms}|{silence_ms}"
        cmd = [
            ffmpeg_exe,
            "-y",
            "-i",
            audio_path,
            "-af",
            f"adelay={delay}",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "3",
            temp_output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            raise RuntimeError(f"Failed to prepend TTS leading silence: {result.stderr}")
        os.replace(temp_output_path, audio_path)
        
    def synthesize(self, text: str, output_path: str, voice_id: str = None, style: str = None) -> str:
        """
        Synthesize text to speech using Edge-TTS asynchronously but wrapped synchronously.
        """
        target_voice = voice_id if voice_id else self.voice
        print(f"[TTS] Edge-TTS Synthesis: '{text[:50]}...' using {target_voice} -> {output_path}")

        # Ensure output directory exists
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        import asyncio
        import edge_tts

        async def _save():
            communicate = edge_tts.Communicate(text, target_voice)
            await communicate.save(output_path)

        # Run the async function in the current thread's event loop
        # Since this is likely called from a background thread, we can use asyncio.run
        try:
            asyncio.run(_save())
        except Exception as e:
            print(f"[TTS] Edge-TTS Error: {e}")
            raise e

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise FileNotFoundError(f"Edge-TTS failed to create file: {output_path}")

        self._prepend_leading_silence(output_path)

        return output_path

_asr_service = None
_tts_service = None


def get_asr_service() -> ASRService:
    global _asr_service
    if _asr_service is None:
        _asr_service = ASRService()
    return _asr_service


def get_tts_service() -> TTSService:
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service
