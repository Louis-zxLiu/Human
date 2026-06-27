import unittest
from unittest.mock import Mock, patch

import numpy as np

from app.services.asr_tts import ASRService, normalize_asr_text


class ASRServiceTests(unittest.TestCase):
    def test_transcribe_rejects_too_short_audio_before_whisper(self):
        service = ASRService.__new__(ASRService)
        service.device = "cpu"
        service.model = Mock()

        with patch("os.path.exists", return_value=True), patch.object(
            service,
            "_decode_audio",
            return_value=np.zeros(1000, dtype=np.float32),
        ):
            with self.assertRaises(ValueError):
                service.transcribe("short.webm")

        service.model.transcribe.assert_not_called()

    def test_transcribe_uses_chinese_language_hint(self):
        service = ASRService.__new__(ASRService)
        service.device = "cpu"
        service.model = Mock()
        service.model.transcribe.return_value = {"text": "  介绍一下灵山大佛  "}

        audio = np.ones(16000, dtype=np.float32) * 0.02
        with patch("os.path.exists", return_value=True), patch.object(service, "_decode_audio", return_value=audio):
            text = service.transcribe("voice.webm")

        self.assertEqual(text, "介绍一下灵山大佛")
        kwargs = service.model.transcribe.call_args.kwargs
        self.assertEqual(kwargs["language"], "zh")

    def test_transcribe_converts_traditional_to_simplified(self):
        service = ASRService.__new__(ASRService)
        service.device = "cpu"
        service.model = Mock()
        service.model.transcribe.return_value = {"text": "  介紹一下靈山梵宮  "}

        audio = np.ones(16000, dtype=np.float32) * 0.02

        class _FakeCC:
            def convert(self, text):
                mapping = str.maketrans("介紹靈梵宮", "介绍灵梵宫")
                return text.translate(mapping)

        fake_opencc_module = Mock()
        fake_opencc_module.OpenCC = Mock(return_value=_FakeCC())

        with patch("os.path.exists", return_value=True), patch.object(
            service, "_decode_audio", return_value=audio
        ), patch.dict("sys.modules", {"opencc": fake_opencc_module}), patch(
            "app.services.asr_tts._simplified_converter", None
        ):
            # Reset cached converter so the mock opencc is used
            import app.services.asr_tts as _asr_mod
            _asr_mod._simplified_converter = None
            text = service.transcribe("voice.webm")

        self.assertEqual(text, "介绍一下灵山梵宫")

    def test_normalize_asr_text_strips_empty_text(self):
        self.assertEqual(normalize_asr_text("  "), "")


if __name__ == "__main__":
    unittest.main()
