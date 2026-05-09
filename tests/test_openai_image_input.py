import base64
import sys
import tempfile
import types
import unittest
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


class FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        message = types.SimpleNamespace(content="OK")
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])


class FakeClient:
    def __init__(self):
        self.chat = types.SimpleNamespace(completions=FakeCompletions())


class FakeOpenAI:
    last_client = None

    def __new__(cls, *args, **kwargs):
        cls.last_client = FakeClient()
        return cls.last_client


_install_import_stubs()
import wxbot_core
from wxbot_core import OpenAIAPI


class OpenAIImageInputTests(unittest.TestCase):
    def setUp(self):
        wxbot_core.OpenAI = FakeOpenAI

    def make_api(self):
        config = types.SimpleNamespace(
            api_key="sk-test",
            base_url="https://api.moonshot.ai/v1",
            model1="kimi-k2.6",
            prompt="system prompt",
        )
        return OpenAIAPI(config)

    def test_text_message_keeps_original_string_content(self):
        api = self.make_api()

        reply = api.chat("hello", stream=False)

        self.assertEqual(reply, "OK")
        messages = FakeOpenAI.last_client.chat.completions.kwargs["messages"]
        self.assertEqual(messages[-1], {"role": "user", "content": "hello"})

    def test_image_path_builds_openai_multimodal_content(self):
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
        )
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "tiny.png"
            image_path.write_bytes(png_bytes)
            api = self.make_api()

            reply = api.chat("describe", stream=False, image_path=str(image_path))

        self.assertEqual(reply, "OK")
        messages = FakeOpenAI.last_client.chat.completions.kwargs["messages"]
        content = messages[-1]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "describe"})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))


if __name__ == "__main__":
    unittest.main()
