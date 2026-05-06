import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import webhook_send


class WebhookSendTests(unittest.TestCase):
    def test_default_config_is_disabled_and_has_safe_defaults(self):
        cfg = webhook_send.default_config()
        self.assertFalse(cfg["enabled"])
        self.assertEqual(cfg["method"], "POST")
        self.assertEqual(cfg["content_type"], "application/json")
        self.assertIn("$title", cfg["body"])
        self.assertIn("$content", cfg["body"])
        self.assertIn("msg_type", cfg["body"])

    def test_load_config_returns_defaults_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = webhook_send.load_config(os.path.join(tmp, "webhook.json"))
            self.assertFalse(cfg["enabled"])

    def test_save_and_load_config_merges_with_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "webhook.json")
            webhook_send.save_config({"enabled": True, "url": "https://example.com/hook"}, path)
            cfg = webhook_send.load_config(path)
            self.assertTrue(cfg["enabled"])
            self.assertEqual(cfg["url"], "https://example.com/hook")
            self.assertEqual(cfg["method"], "POST")

    def test_save_config_rejects_invalid_json_body_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "webhook.json")
            with self.assertRaises(ValueError):
                webhook_send.save_config({
                    "enabled": True,
                    "url": "https://example.com/hook",
                    "content_type": "application/json",
                    "body": '{"msg":"unterminated}',
                }, path)
            self.assertFalse(os.path.exists(path))

    @patch("webhook_send.requests.request")
    def test_send_webhook_posts_rendered_json_body_and_headers(self, request_mock):
        response = Mock(status_code=200, text="ok")
        request_mock.return_value = response
        cfg = {
            "enabled": True,
            "url": "https://example.com/hook",
            "method": "POST",
            "content_type": "application/json",
            "headers": {"X-Test": "hello $title"},
            "body": '{"msg":"$title: $content"}',
            "timeout": 3,
        }
        ok, message = webhook_send.send_webhook("title", "content", cfg)
        self.assertTrue(ok, message)
        request_mock.assert_called_once()
        self.assertEqual(request_mock.call_args.args[0], "POST")
        self.assertEqual(request_mock.call_args.args[1], "https://example.com/hook")
        kwargs = request_mock.call_args.kwargs
        self.assertEqual(kwargs["headers"]["X-Test"], "hello title")
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(kwargs["json"], {"msg": "title: content"})
        self.assertEqual(kwargs["timeout"], 3)

    @patch("webhook_send.requests.request")
    def test_send_webhook_uses_text_data_for_non_json_content_type(self, request_mock):
        request_mock.return_value = Mock(status_code=204, text="")
        cfg = {"enabled": True, "url": "https://example.com/hook", "content_type": "text/plain", "body": "$title\n$content"}
        ok, message = webhook_send.send_webhook("t", "c", cfg)
        self.assertTrue(ok, message)
        kwargs = request_mock.call_args.kwargs
        self.assertEqual(kwargs["data"], "t\nc")
        self.assertNotIn("json", kwargs)

    def test_send_webhook_is_noop_when_disabled_or_url_missing(self):
        ok, message = webhook_send.send_webhook("t", "c", {"enabled": False})
        self.assertTrue(ok)
        self.assertIn("disabled", message.lower())
        ok, message = webhook_send.send_webhook("t", "c", {"enabled": True, "url": ""})
        self.assertFalse(ok)
        self.assertIn("url", message.lower())

    @patch("webhook_send.requests.request", side_effect=RuntimeError("network down"))
    def test_send_webhook_catches_request_errors(self, request_mock):
        ok, message = webhook_send.send_webhook("t", "c", {"enabled": True, "url": "https://example.com", "body": '{"title":"$title","content":"$content"}'})
        self.assertFalse(ok)
        self.assertIn("network down", message)

    @patch("webhook_send.requests.request")
    def test_send_webhook_reports_feishu_business_error_even_with_http_200(self, request_mock):
        response = Mock(status_code=200, text='{"code":19024,"msg":"Key Words Not Found"}')
        response.json.side_effect = ValueError("no json")
        request_mock.return_value = response
        cfg = {
            "enabled": True,
            "url": "https://open.feishu.cn/open-apis/bot/v2/hook/example",
            "body": '{"title":"$title","content":"$content"}',
        }

        ok, message = webhook_send.send_webhook("t", "c", cfg)

        self.assertFalse(ok)
        self.assertIn("19024", message)
        self.assertIn("Key Words Not Found", message)

    @patch("webhook_send.requests.request")
    def test_send_webhook_json_escapes_multiline_content_before_parsing(self, request_mock):
        request_mock.return_value = Mock(status_code=200, text='{"code":0,"msg":"ok"}')
        cfg = {
            "enabled": True,
            "url": "https://example.com/hook",
            "content_type": "application/json",
            "body": '{"msg_type":"text","content":{"text":"$title\\n\\n$content"}}',
        }
        content = '错误信息：\nTraceback (most recent call last):\n  File "wxbot_core.py", line 1\nerr信息：\nFind Control Timeout'

        ok, message = webhook_send.send_webhook("机器人告警", content, cfg)

        self.assertTrue(ok, message)
        sent_json = request_mock.call_args.kwargs["json"]
        self.assertEqual(sent_json["content"]["text"], "机器人告警\n\n" + content)


if __name__ == "__main__":
    unittest.main()
