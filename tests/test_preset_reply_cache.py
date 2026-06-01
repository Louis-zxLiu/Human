import unittest

from app.services.preset_route_cache import preset_route_cache


class PresetReplyCacheTests(unittest.TestCase):
    def test_resolves_weak_gps_followup_reply(self):
        text = (
            "\u5f53\u524d GPS \u4fe1\u53f7\u8f83\u5f31\uff0c\u6211\u5148\u4e0d\u80fd\u51c6\u786e\u5b9a\u4f4d\u60a8\u3002"
            "\u8bf7\u63cf\u8ff0\u4e00\u4e0b\u60a8\u9644\u8fd1\u6700\u660e\u663e\u7684\u4f5b\u50cf\u3001\u6865\u3001\u5e7f\u573a\u3001\u5bab\u6bbf\u3001\u5854\u3001\u82b1\u6d77\u3001\u6e56\u9762\u6216\u8857\u533a\uff0c"
            "\u6211\u518d\u7ed3\u5408\u666f\u70b9\u8d44\u6599\u7ee7\u7eed\u5e2e\u60a8\u5224\u65ad\u3002"
        )
        reply = preset_route_cache.resolve_reply(text, response_kind="gps:awaiting_landmarks")
        self.assertIsNotNone(reply)
        self.assertEqual(reply["key"], "gps-awaiting-landmarks")

    def test_resolves_generic_insufficient_fact_refusal(self):
        text = (
            "\u62b1\u6b49\uff0c\u6211\u6682\u65f6\u6ca1\u6709\u5728\u7075\u5c71\u80dc\u5883\u77e5\u8bc6\u8d44\u6599\u4e2d\u627e\u5230\u8db3\u591f\u8bc1\u636e\u6765\u56de\u7b54\u8fd9\u4e2a\u95ee\u9898\u3002"
            "\u60a8\u53ef\u4ee5\u8865\u5145\u5177\u4f53\u666f\u70b9\u540d\u79f0\uff0c\u6216\u8005\u6539\u95ee\u4f4d\u7f6e\u3001\u5f00\u653e\u4fe1\u606f\u3001\u5386\u53f2\u80cc\u666f\u3001\u4eae\u70b9\u548c\u6e38\u89c8\u5efa\u8bae\u3002"
        )
        reply = preset_route_cache.resolve_reply(text, response_kind="refused")
        self.assertIsNotNone(reply)
        self.assertEqual(reply["key"], "refused-insufficient-fact-evidence")

    def test_response_kind_must_match(self):
        text = (
            "\u62b1\u6b49\uff0c\u6211\u6682\u65f6\u6ca1\u6709\u5728\u7075\u5c71\u80dc\u5883\u77e5\u8bc6\u8d44\u6599\u4e2d\u627e\u5230\u8db3\u591f\u8bc1\u636e\u6765\u56de\u7b54\u8fd9\u4e2a\u95ee\u9898\u3002"
            "\u60a8\u53ef\u4ee5\u8865\u5145\u5177\u4f53\u666f\u70b9\u540d\u79f0\uff0c\u6216\u8005\u6539\u95ee\u4f4d\u7f6e\u3001\u5f00\u653e\u4fe1\u606f\u3001\u5386\u53f2\u80cc\u666f\u3001\u4eae\u70b9\u548c\u6e38\u89c8\u5efa\u8bae\u3002"
        )
        self.assertIsNone(preset_route_cache.resolve_reply(text, response_kind="field:description"))


if __name__ == "__main__":
    unittest.main()
