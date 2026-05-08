import json
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path


def _install_import_stubs():
    wxautox4 = types.ModuleType("wxautox4")
    wxautox4.WeChat = object
    wxautox4.WxParam = types.SimpleNamespace(
        MESSAGE_HASH=False,
        FORCE_MESSAGE_XBIAS=False,
        CHAT_WINDOW_SIZE=None,
        DEFAULT_MESSAGE_YBIAS=0,
    )
    sys.modules.setdefault("wxautox4", wxautox4)

    msgs = types.ModuleType("wxautox4.msgs")
    msgs.__all__ = []
    sys.modules.setdefault("wxautox4.msgs", msgs)

    useful = types.ModuleType("wxautox4.utils.useful")
    useful.check_license = lambda *args, **kwargs: True
    sys.modules.setdefault("wxautox4.utils.useful", useful)

    email_send = types.ModuleType("email_send")
    sys.modules.setdefault("email_send", email_send)

    logger = types.ModuleType("logger")
    logger.log = lambda *args, **kwargs: None
    sys.modules.setdefault("logger", logger)

    openai = types.ModuleType("openai")
    openai.OpenAI = object
    sys.modules.setdefault("openai", openai)

    cozepy = types.ModuleType("cozepy")
    for name in (
        "COZE_CN_BASE_URL",
        "Coze",
        "TokenAuth",
        "Message",
        "ChatStatus",
        "MessageContentType",
        "ChatEventType",
    ):
        setattr(cozepy, name, object)
    sys.modules.setdefault("cozepy", cozepy)

    schedule = types.ModuleType("schedule")
    sys.modules.setdefault("schedule", schedule)

    requests = types.ModuleType("requests")
    requests.post = lambda *args, **kwargs: None
    requests.exceptions = types.SimpleNamespace(RequestException=Exception)
    sys.modules.setdefault("requests", requests)


_install_import_stubs()
from wxbot_core import ReplyCountStore


class ReplyCountStoreTests(unittest.TestCase):
    def test_loads_empty_structure_when_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reply_count.json"
            store = ReplyCountStore(str(path))

            self.assertEqual(store.data["meta"]["last_reset_date"], "")
            self.assertEqual(store.data["users"], {})

    def test_repairs_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reply_count.json"
            path.write_text("{bad json", encoding="utf-8")

            store = ReplyCountStore(str(path))

            self.assertEqual(store.data, {"meta": {"last_reset_date": ""}, "users": {}})

    def test_increment_and_flags_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reply_count.json"
            store = ReplyCountStore(str(path))

            self.assertEqual(store.increment_ai_count("alice"), 1)
            self.assertTrue(store.mark_limit_notified("alice"))
            self.assertFalse(store.mark_limit_notified("alice"))
            self.assertTrue(store.mark_api_err_notified("alice"))
            self.assertFalse(store.mark_api_err_notified("alice"))

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["users"]["alice"]["ai_count"], 1)
            self.assertTrue(saved["users"]["alice"]["limit_notified"])
            self.assertTrue(saved["users"]["alice"]["api_err_notified"])

    def test_maybe_reset_clears_users_when_period_has_elapsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reply_count.json"
            path.write_text(
                json.dumps({
                    "meta": {"last_reset_date": "2026-05-01"},
                    "users": {"alice": {"ai_count": 9}},
                }),
                encoding="utf-8",
            )
            store = ReplyCountStore(str(path))

            did_reset = store.maybe_reset(7, now=datetime(2026, 5, 8, 8, 0, 0))

            self.assertTrue(did_reset)
            self.assertEqual(store.data["users"], {})
            self.assertEqual(store.data["meta"]["last_reset_date"], "2026-05-08")

    def test_clear_user_removes_only_target_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reply_count.json"
            store = ReplyCountStore(str(path))
            store.increment_ai_count("alice")
            store.increment_ai_count("bob")

            self.assertTrue(store.clear_user("alice"))
            self.assertFalse(store.clear_user("missing"))
            self.assertNotIn("alice", store.data["users"])
            self.assertIn("bob", store.data["users"])

    def test_was_send_success_accepts_common_wx_response_shapes(self):
        self.assertTrue(ReplyCountStore.was_send_success(True))
        self.assertFalse(ReplyCountStore.was_send_success(False))
        self.assertTrue(ReplyCountStore.was_send_success({"status": "success"}))
        self.assertTrue(ReplyCountStore.was_send_success({"code": 0}))
        self.assertFalse(ReplyCountStore.was_send_success({"status": "error"}))
        self.assertFalse(ReplyCountStore.was_send_success(None))


if __name__ == "__main__":
    unittest.main()
