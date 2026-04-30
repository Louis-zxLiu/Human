import os
import torch
import whisper
import asyncio
import edge_tts

from app.core.config import settings

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
        self.model = whisper.load_model(self.model_name, device=self.device)
        self.is_loaded = True

    def transcribe(self, audio_path: str) -> str:
        """
        Transcribe audio file to text.
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
            
        print(f"[ASR] Transcribing {audio_path}...")
        result = self.model.transcribe(audio_path)
        return result["text"]

class TTSService:
    """
    Wrapper for Edge-TTS (Online, High-quality)
    """
    def __init__(self):
        print(f"[TTS] Initializing Edge-TTS (requires internet)...")
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
        
    def synthesize(self, text: str, output_path: str, voice_id: str = None) -> str:
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
            
        return output_path

asr_service = ASRService()
tts_service = TTSService()
