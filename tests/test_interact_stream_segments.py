import unittest

from app.api.stream_utils import build_stream_tts_segments


class InteractStreamSegmentTests(unittest.TestCase):
    def test_refusal_response_uses_single_tts_segment(self):
        text = (
            "\u62b1\u6b49\uff0c\u6211\u6682\u65f6\u6ca1\u6709\u627e\u5230\u8fd9\u90e8\u5206\u8bc1\u636e\u3002"
            "\u60a8\u53ef\u4ee5\u6362\u4e00\u79cd\u95ee\u6cd5\u3002"
        )
        self.assertEqual(
            build_stream_tts_segments(text, response_kind="refused"),
            [text],
        )

    def test_regular_response_keeps_sentence_split_streaming(self):
        text = "\u7075\u5c71\u5927\u4f5b\u5728\u4e2d\u8f74\u6838\u5fc3\u533a\u57df\u3002\u53ef\u4ee5\u6cbf\u4e3b\u6e38\u7ebf\u524d\u5f80\u3002"
        self.assertEqual(
            build_stream_tts_segments(text, response_kind="field:location"),
            [
                "\u7075\u5c71\u5927\u4f5b\u5728\u4e2d\u8f74\u6838\u5fc3\u533a\u57df\u3002",
                "\u53ef\u4ee5\u6cbf\u4e3b\u6e38\u7ebf\u524d\u5f80\u3002",
            ],
        )


if __name__ == "__main__":
    unittest.main()
