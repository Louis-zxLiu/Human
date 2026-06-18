import os
import unittest
from unittest.mock import patch

from app.core.mirrors import DEFAULT_HF_ENDPOINT, configure_hf_endpoint


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


if __name__ == "__main__":
    unittest.main()
