import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.mirrors import DEFAULT_HF_ENDPOINT, configure_hf_endpoint
from app.tasks.download_models import has_required_files


class MirrorConfigTests(unittest.TestCase):
    def test_configure_hf_endpoint_sets_default_when_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            endpoint = configure_hf_endpoint()

            self.assertEqual(endpoint, DEFAULT_HF_ENDPOINT)
            self.assertEqual(os.environ["HF_ENDPOINT"], DEFAULT_HF_ENDPOINT)

    def test_configure_hf_endpoint_preserves_existing_value(self):
        with patch.dict(os.environ, {"HF_ENDPOINT": "https://example.invalid"}, clear=True):
            endpoint = configure_hf_endpoint()

            self.assertEqual(endpoint, "https://example.invalid")
            self.assertEqual(os.environ["HF_ENDPOINT"], "https://example.invalid")

    def test_required_any_files_accepts_pytorch_model_fallback(self):
        model = {
            "required_files": ["config.json", "tokenizer.json", "vocab.txt"],
            "required_any_files": [["model.safetensors", "pytorch_model.bin"]],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            for filename in ["config.json", "tokenizer.json", "vocab.txt", "pytorch_model.bin"]:
                (target_dir / filename).write_text("", encoding="utf-8")

            self.assertTrue(has_required_files(target_dir, model))

    def test_required_any_files_rejects_missing_model_weight(self):
        model = {
            "required_files": ["config.json", "tokenizer.json", "vocab.txt"],
            "required_any_files": [["model.safetensors", "pytorch_model.bin"]],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            for filename in ["config.json", "tokenizer.json", "vocab.txt"]:
                (target_dir / filename).write_text("", encoding="utf-8")

            self.assertFalse(has_required_files(target_dir, model))


if __name__ == "__main__":
    unittest.main()
