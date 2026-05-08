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


_install_import_stubs()
from wxbot_core import clean_ai_reply_text


class AIReplyCleanerTests(unittest.TestCase):
    def test_removes_complete_think_block(self):
        text = '<think>内部推理\n不应发送</think>\n\n您好，有什么可以帮您的？'

        self.assertEqual(clean_ai_reply_text(text), '您好，有什么可以帮您的？')

    def test_removes_multiple_complete_think_blocks_case_insensitive(self):
        text = '开头\n<THINK>一</THINK>\n中间\n<think>二</think>\n结尾'

        self.assertEqual(clean_ai_reply_text(text), '开头\n中间\n结尾')

    def test_removes_unclosed_leading_think_until_blank_line(self):
        text = '<think>这里没有结束标签\n但是后面有正式回复\n\n您好'

        self.assertEqual(clean_ai_reply_text(text), '您好')

    def test_drops_unclosed_leading_think_when_no_safe_tail_exists(self):
        text = '<think>这里没有结束标签，所以不能直接发给用户'

        self.assertEqual(clean_ai_reply_text(text), '')

    def test_keeps_unclosed_think_inside_normal_text(self):
        text = '这是一段正常说明：<think> 是一个标签示例'

        self.assertEqual(clean_ai_reply_text(text), text)

    def test_keeps_plain_text_unchanged_except_outer_whitespace(self):
        text = '  普通回复，不包含思考标签。  '

        self.assertEqual(clean_ai_reply_text(text), '普通回复，不包含思考标签。')


if __name__ == "__main__":
    unittest.main()
