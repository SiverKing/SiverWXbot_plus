import sys
import types
import unittest


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


class FakeVisionAPI:
    def __init__(self):
        self.image_path_seen = None

    def chat(self, message, stream=False, prompt=None, history=None, image_path=""):
        self.image_path_seen = image_path
        return "OK"


class FakeTextOnlyAPI:
    def chat(self, message, stream=False, prompt=None, history=None):
        return "OK"


_install_import_stubs()
import web_server


class APIConfigImageTestTests(unittest.TestCase):
    def test_image_test_uses_temporary_png_for_supported_api(self):
        api = FakeVisionAPI()

        result = web_server._run_api_image_test(api, "OpenAI SDK")

        self.assertEqual(result["status"], "success")
        self.assertTrue(api.image_path_seen.endswith(".png"))

    def test_image_test_reports_unsupported_sdk(self):
        result = web_server._run_api_image_test(FakeTextOnlyAPI(), "Dify")

        self.assertEqual(result["status"], "skipped")
        self.assertIn("暂不支持", result["message"])


if __name__ == "__main__":
    unittest.main()
