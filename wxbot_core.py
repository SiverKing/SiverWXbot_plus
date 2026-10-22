#!/usr/bin/env python3
# Siver微信机器人 siver_wxbot - 面向对象版本 - wxautox4版本
# 作者：https://www.siver.top

version = "v4.8.1"
version_log = "v4.8.1 - 修复自动备份在长路径下失败、备份改为单 zip 快照、消息类回复支持发送文档等常见文件"

# ============================================================
# 【新增配置字段检查清单】本文件内 2 步：④ 必改、⑥ 可选
# 全流程 5 步必改 + 1 步可选，编号与索引见 web_server.py 顶部
#
#   ④ 运行时读取（真正决定程序行为的地方）
#        · 类属性默认值：class WXBotConfig   →   def __init__
#        · 运行时读取：def update_global_config()
#   ⑥ 可选：面板状态展示   →   def get_status()
#
#   ⚠ 属性名必须与配置键逐字相同。历史上曾有 3 个把 friend 拼成 frined / frien 的
#     属性名，已随本次清理修正；新增字段时请直接从配置键复制属性名，不要手敲。
#
#   ⚠ update_global_config() 里仍有 3 处直接 int()：api_index、
#     chat_image_recognition_api、group_image_recognition_api，三者自带 try/except
#     与越界回退；其余数值字段已统一走 _coerce_int_range()（经 config_defaults 落盘时
#     也会再钳位一次）。注意调用方 run_bot() 线程没有 except，任何未捕获异常都只表现为
#     「机器人启动后静默变成未运行」。
# ============================================================


# ============================================================
# 标准库导入
# ============================================================
import os
import re
import sys
import time
import json
import hashlib
import random
import calendar
import threading
import queue
import traceback
import copy
from datetime import datetime, timedelta

# ============================================================
# 第三方库导入
# ============================================================
import requests
import base64
import mimetypes
import schedule                  # 定时任务库（此处只用 CancelJob 标记；调度器按实例创建）
from openai import OpenAI        # OpenAI SDK

# Coze 官方 Python 库
from cozepy import (
    COZE_CN_BASE_URL,
    Coze,
    TokenAuth,
    Message as CozeMessage,
    ChatStatus,
    MessageContentType,
    ChatEventType,
)

# ============================================================
# wxautox 相关导入（Plus版，需向作者购买授权）
# 购买地址：https://www.siverking.online/static/img/siver_wx.jpg
# ============================================================
from wxautox4 import WeChat
from wxautox4.msgs import *
from wxautox4 import WxParam
from wxautox4.utils.useful import check_license

# ============================================================
# 本地模块导入
# ============================================================
import email_send
import webhook_send
from logger import log
# 原子写与"读-改-写"事务统一由 config_store 提供（零 Flask 依赖）。
# 「配置什么时候生效」的唯一约定（hot / api_rebuild / restart），面板共用同一份
import config_apply
# 沿用 _write_json_atomic 这个名字，历史调用点与 web_server 的导入都不用改。
from config_store import write_json_atomic as _write_json_atomic
from config_store import ConfigStore
import config_defaults

# ============================================================
# 告警发送队列（有界 + 单个后台线程）
# ------------------------------------------------------------
# is_err() 会在 wxautox 消息回调线程与主循环里被调用，而邮件 / Webhook 都是网络操作
# （邮件最坏要等 SMTP_TIMEOUT=10s，Webhook 默认 timeout=5s），同步发送会卡住调用方，
# 异常风暴时更会反复阻塞。因此改为：调用方只做非阻塞入队，由单个后台线程串行发送。
#
# 策略：
#   - 队列有界（_ALERT_QUEUE_MAX）：满了直接丢弃本条并计数 + 限频记录日志，
#     既不阻塞调用方，也不会无限增长
#   - 相同（标题, 内容）在 _ALERT_DEDUP_WINDOW 秒内重复出现只发送一次（重复合并 / 限流）
#   - 发送线程是 daemon，随进程退出；进程退出时队列中尚未发送的告警会丢失
# ============================================================
_ALERT_QUEUE_MAX = 50           # 队列容量上限
_ALERT_DEDUP_WINDOW = 60.0      # 相同告警的去重时间窗（秒）

_alert_queue = queue.Queue(maxsize=_ALERT_QUEUE_MAX)
_alert_dedupe = {}              # (title, content) -> 上次入队时刻（time.monotonic）
_alert_lock = threading.Lock()
_alert_worker = None            # 后台发送线程（按需启动，只启动一次）
_alert_dropped = 0              # 因队列满被丢弃的告警数
_alert_suppressed = 0           # 因重复被抑制的告警数


def _alert_worker_loop():
    """后台告警线程：串行消费队列，依次发送邮件与 Webhook。"""
    while True:
        item = _alert_queue.get()
        try:
            if item is None:
                return
            title, content = item
            try:
                email_send.send_email(subject=title, content=content)
            except Exception as e:
                log(level="ERROR", message=f"发送告警邮件失败：{e}")
            try:
                ok, message = webhook_send.send_message(title, content)
                if not ok:
                    log(level="ERROR", message=f"发送 Webhook 告警失败：{message}")
            except Exception as e:
                log(level="ERROR", message=f"发送 Webhook 告警异常：{e}")
        finally:
            _alert_queue.task_done()


def _ensure_alert_worker():
    """按需启动后台告警线程（只启动一次）。"""
    global _alert_worker
    if _alert_worker is not None and _alert_worker.is_alive():
        return
    with _alert_lock:
        if _alert_worker is not None and _alert_worker.is_alive():
            return
        _alert_worker = threading.Thread(
            target=_alert_worker_loop, name="alert-sender", daemon=True
        )
        _alert_worker.start()


def enqueue_alert(title, content):
    """把一条告警放进有界队列后立即返回，不阻塞调用方。

    :return: True=已入队；False=被去重抑制，或队列满被丢弃（两种情况都计数）
    """
    global _alert_dropped, _alert_suppressed
    now = time.monotonic()
    key = (title, content)
    with _alert_lock:
        last = _alert_dedupe.get(key)
        if last is not None and (now - last) < _ALERT_DEDUP_WINDOW:
            _alert_suppressed += 1
            return False
        # 先占位再入队：队列满被丢弃的告警同样占用去重窗口，
        # 避免风暴期间对同一条告警反复尝试入队
        _alert_dedupe[key] = now
        # 去重表也要有硬上限：先清过期键；窗口内错误种类仍过多时按时间淘汰最旧的
        _dedupe_cap = _ALERT_QUEUE_MAX * 4
        if len(_alert_dedupe) > _dedupe_cap:
            for k in [k for k, t in _alert_dedupe.items() if (now - t) >= _ALERT_DEDUP_WINDOW]:
                _alert_dedupe.pop(k, None)
            if len(_alert_dedupe) > _dedupe_cap:
                for k, _t in sorted(_alert_dedupe.items(), key=lambda kv: kv[1])[:len(_alert_dedupe) - _dedupe_cap]:
                    _alert_dedupe.pop(k, None)

    _ensure_alert_worker()
    try:
        _alert_queue.put_nowait((title, content))
    except queue.Full:
        with _alert_lock:
            _alert_dropped += 1
            dropped = _alert_dropped
        # 限频记录：第 1 次和之后每 10 次记一条，避免日志本身变成风暴
        if dropped == 1 or dropped % 10 == 0:
            log(level="ERROR",
                message=f"告警队列已满（上限 {_ALERT_QUEUE_MAX}），本条告警已丢弃；累计丢弃 {dropped} 条")
        return False
    return True


# ============================================================
# wxautox 全局参数配置
# 说明：
#   MESSAGE_HASH         - 是否启用消息哈希辅助判断，开启后稍微影响性能，默认 False
#   FORCE_MESSAGE_XBIAS  - 是否每次启动都重新自动获取 X 偏移量，默认 False
# 其他可配置参数（供参考，未在此处修改）：
#   ENABLE_FILE_LOGGER        (bool) : 是否启用日志文件，默认 True
#   DEFAULT_SAVE_PATH         (str)  : 下载文件/图片默认保存路径
#   DEFAULT_MESSAGE_XBIAS     (int)  : 头像到消息 X 偏移量，默认 51
#   LISTEN_INTERVAL           (int)  : 监听消息时间间隔（秒），默认 1
#   LISTENER_EXCUTOR_WORKERS  (int)  : 监听执行器线程池大小，默认 4
#   SEARCH_CHAT_TIMEOUT       (int)  : 搜索聊天对象超时时间（秒），默认 5
# ============================================================
WxParam.MESSAGE_HASH = True         # 启用消息哈希，辅助消息去重判断
WxParam.FORCE_MESSAGE_XBIAS = True  # 每次启动强制重新获取 X 偏移量
WxParam.CHAT_WINDOW_SIZE = (1500, 6000)
WxParam.DEFAULT_MESSAGE_YBIAS = 40
_CONFIG_SPECIAL_SESSION_NAMES = set()

# ============================================================
# SDK 名称常量（面板显示名，兼容旧名 "OpenAI SDK"）
# ============================================================
OPENAI_SDK_NAME    = "OpenAI API 格式兼容接口"
OPENAI_SDK_ALIASES = ("OpenAI SDK", OPENAI_SDK_NAME)
API_ERROR_REPLY    = "API返回错误，请稍后再试"

# ============================================================
# 文件回复的「载体消息」文案
# ------------------------------------------------------------
# 关键词回复配成图片/视频路径时，会先发一条纯文本消息、再发文件本身。
# 这条文本不是给用户看的内容，它的作用是承载「@发言人」和「引用」两个语义
# —— 文件消息本身带不了这两样。
# 内容固定为 "1"，**不取文件名**：文件名出现在聊天记录里既没有信息量也不好看
# （早期版本用的是 os.path.basename，用户反馈后改为固定文案）。
# ============================================================
MEDIA_CARRIER_TEXT = "1"

# ============================================================
# 消息类发送：可自动作为「文件」发送的扩展名
# ------------------------------------------------------------
# 关键词回复 / 定时消息 / 随机定时消息 / 新好友招呼语 里填写本地文件完整路径时，
# 程序会走 SendFiles 直接发文件（图片、视频、文档、压缩包等都能发）。
# ⚠ 朋友圈图片/视频不走这里：朋友圈只支持图片和视频（见 send_scheduled_moments）。
# 扩展名只有这一个来源，下面的正则由它生成，避免两处清单漏改。
# ============================================================
SEND_FILE_EXTENSIONS = (
    # 图片
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico', '.tif', '.tiff', '.heic', '.heif',
    # 视频
    '.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.m4v', '.webm', '.3gp',
    # 音频
    '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.amr',
    # 文档 / 表格 / 演示
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.ppt', '.pptx',
    '.txt', '.md', '.rtf', '.odt', '.ods', '.odp', '.wps', '.et', '.dps', '.ofd',
    # 压缩包
    '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz',
    # 其它常见可发送文件
    '.json', '.xml', '.html', '.htm', '.log', '.py', '.js',
    '.apk', '.exe', '.msi', '.iso', '.epub', '.mobi',
)

_SEND_FILE_PATH_RE = re.compile(
    r'^([A-Za-z]:[\\/]|/[^/]+).+\.('
    + '|'.join(ext.lstrip('.') for ext in SEND_FILE_EXTENSIONS)
    + r')$',
    re.IGNORECASE,
)


def _normalize_api_configs(api_configs):
    """规范化接口列表，并将非法备用接口索引统一为 -1。"""
    if not isinstance(api_configs, list):
        return []

    normalized = []
    for cfg in api_configs:
        normalized.append(cfg if isinstance(cfg, dict) else {})

    total = len(normalized)
    for index, cfg in enumerate(normalized):
        try:
            fallback_index = int(cfg.get("fallback_api_index", -1))
        except (TypeError, ValueError):
            fallback_index = -1
        if (
            fallback_index < 0
            or fallback_index >= total
            or fallback_index == index
        ):
            fallback_index = -1
        cfg["fallback_api_index"] = fallback_index
    return normalized


# 原子写的实现见 config_store.write_json_atomic（文件顶部已导入）

# 同一个 config.json 共用一个 ConfigStore（它内部按路径持锁，
# 与面板、siver_panel 的读写排在同一条队列上）
_CONFIG_STORES: dict = {}
_CONFIG_STORES_GUARD = threading.Lock()


def _get_config_store(path):
    """取（或创建）某个配置文件对应的 ConfigStore。

    规范化走 config_defaults.prepare（迁移 -> 补默认值 -> 类型校验），
    与面板 /save_config 完全一致。
    """
    key = os.path.abspath(path)
    with _CONFIG_STORES_GUARD:
        store = _CONFIG_STORES.get(key)
        if store is None:
            store = ConfigStore(
                key,
                defaults=config_defaults.DEFAULT_CONFIG,
                normalize=config_defaults.prepare,
            )
            _CONFIG_STORES[key] = store
        return store


# ============================================================
# 拆分多条回复常量
# ============================================================
SPLIT_SEPARATOR = "||SPLIT||"

SPLIT_PROMPT_TEMPLATE = """\
【回复格式要求】
你的回复将直接发送到即时通讯软件（如微信），请模仿真人聊天可能会拆分多条发送的风格，
你可以自行决定是否将回复拆分为多条消息，以及拆分几条，无需强制拆分。
约束：每条不超过 {max_chars} 字，总条数不超过 {max_count} 条。
若需拆分，在每条消息之间用以下分隔符单独占一行隔开：
||SPLIT||

例如：
好的，我来解释一下。
||SPLIT||
这个问题其实很常见，主要原因是……
||SPLIT||
你可以试试这个方法。

若无需拆分则正常回复，不要添加任何分隔符。
严禁在正文内容中出现 ||SPLIT|| 字样。
如果你想分条回复，一定一定一定要在每个分条直接加上这个分隔符||SPLIT||，不然程序无法处理分条发送。
如果你要换2行来进行分段回复，那请将换两行这个操作改成用分隔符回复的分条回复，以下是示例：
原始内容：
好的，我来解释一下。

这个问题其实很常见，主要原因是……

改动后内容：
好的，我来解释一下。
||SPLIT||
这个问题其实很常见，主要原因是……
【以下是你的角色设定】
{base_prompt}"""

# ============================================================
# 思考清洗常量
# ============================================================
THINK_BLOCK_RE = re.compile(r'<think\b[^>]*>.*?</think>', re.IGNORECASE | re.DOTALL)
LEADING_THINK_RE = re.compile(r'^\s*<think\b[^>]*>', re.IGNORECASE)


def clean_ai_reply_text(text):
    """清理模型回复中的思考标签，避免把推理过程发送给用户。"""
    if text is None:
        return ""
    text = str(text)
    cleaned = THINK_BLOCK_RE.sub("", text)
    removed_think = cleaned != text

    # 未闭合的开头 <think> 视为不安全输出：只保留空行后的正文。
    # 不处理中间出现的未闭合示例，降低误伤普通文本的概率。
    if LEADING_THINK_RE.search(cleaned):
        tail_match = re.search(r'\n\s*\n', cleaned)
        if tail_match:
            cleaned = cleaned[tail_match.end():]
        else:
            cleaned = ""

    lines = [line.rstrip() for line in cleaned.splitlines()]
    cleaned = "\n".join(lines).strip()
    if removed_think:
        cleaned = re.sub(r'\n\s*\n+', '\n', cleaned)
    return cleaned


def _shorten_log_text(text, max_len=500):
    """压缩接口错误文本，避免把 HTML 错误页或完整 prompt 写入日志。"""
    if text is None:
        return ""
    text = str(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\[[^\]]+\]\([^)]+\)', lambda m: m.group(0).split('](', 1)[0].lstrip('['), text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > max_len:
        return text[:max_len].rstrip() + "..."
    return text


def _payload_log_summary(payload):
    """生成请求体摘要，不记录 prompt、历史消息和用户原文。"""
    if not isinstance(payload, dict):
        return ""
    summary = {}
    for key in ("model", "stream", "max_tokens", "max_output_tokens"):
        if key in payload:
            summary[key] = payload.get(key)
    if isinstance(payload.get("messages"), list):
        summary["messages_count"] = len(payload["messages"])
    if isinstance(payload.get("input"), list):
        summary["input_count"] = len(payload["input"])
    if "system" in payload:
        summary["has_system"] = bool(payload.get("system"))
    if _payload_has_image(payload):
        summary["has_image"] = True
    return json.dumps(summary, ensure_ascii=False)


def _payload_has_image(value):
    if isinstance(value, dict):
        type_value = str(value.get("type", "")).lower()
        source = value.get("source")
        if (
            "image" in type_value
            or "image_url" in value
            or (isinstance(source, dict) and "media_type" in source)
        ):
            return True
        return any(_payload_has_image(v) for v in value.values())
    if isinstance(value, list):
        return any(_payload_has_image(item) for item in value)
    return False


def _api_error_summary(error, payload=None, response=None):
    """统一压缩 API 异常日志，保留排障关键字段。"""
    parts = [f"{type(error).__name__}: {_shorten_log_text(error, 260)}"]
    resp = response or getattr(error, "response", None)
    if resp is not None:
        status_code = getattr(resp, "status_code", None)
        if status_code is not None:
            parts.append(f"status={status_code}")
        text = getattr(resp, "text", "")
        if text:
            parts.append(f"response={_shorten_log_text(text, 500)}")
    payload_summary = _payload_log_summary(payload)
    if payload_summary:
        parts.append(f"payload={payload_summary}")
    return ", ".join(part for part in parts if part)


# ============================================================
# 配置管理类
# ============================================================


class WXBotConfig:
    """
    微信机器人配置类
    负责从 config.json 中加载、保存、刷新配置，
    以及对监听用户列表、群组列表等进行增删管理。
    """

    def __init__(self):
        """初始化配置路径，并登记所有字段的类属性默认值。

        ⚠ 这里的默认值是 config 缺键时的兜底，必须与
          create_new_config_file() 的 base_config 保持一致。
          group_welcome_msg 曾因两处不一致导致老配置丢失欢迎语（已修复）。
        """
        _base = os.path.dirname(sys.executable) if hasattr(sys, '_MEIPASS') else os.path.abspath(".")
        self.CONFIG_FILE = os.path.join(_base, 'config', 'config.json')
        self.prompt_dir  = os.path.join(_base, 'config', 'prompt')
        os.makedirs(os.path.join(_base, 'config'), exist_ok=True)
        self.config = {}
        self._loaded_snapshot = {}   # 最近一次从磁盘加载的配置，用于算出"改了哪些字段"
        self.save_failed = False     # 最近一次保存是否失败（管理员命令收尾时据此提示）

        # ---------- 全局监听开关 ----------
        self.AllListen_switch = False   # True=黑名单模式，False=白名单模式
        self.chat_listen_only = False    # 私聊只监听不 AI 回复

        # ---------- 用户与权限 ----------
        self.listen_list = []           # 白名单/黑名单用户列表
        self.special_session_name = []  # 全局监听特殊会话过滤名单（用户附加项）
        self.cmd = ""                   # 管理员账号（命令接收者）

        # ---------- AI 接口配置 ----------
        self.api_configs = []           # 接口配置列表，每项含 sdk/key/url/model/fallback_api_index
        self.api_index = 0              # 当前使用的接口索引
        self.api_sdk  = ""             # 当前接口 SDK（派生）
        self.api_key  = ""             # 当前接口 Key（派生）
        self.base_url = ""             # 当前接口 URL（派生）
        self.model1   = ""             # 当前接口模型（派生，供 AI 类使用）
        self.prompt   = ""             # AI 系统提示词
        self.AtMe     = ""             # 机器人被 @ 的标识（如 "@机器人昵称"）

        # ---------- 群聊配置 ----------
        self.group = []                 # 监听的群聊列表
        self.group_api_map = {}         # 群聊专属接口映射 {群名: api_index}
        self.group_switch = False       # 群机器人总开关
        self.group_listen_only = False   # 群聊只监听不 AI 回复
        self.group_reply_at = False     # 群聊是否仅在被 @ 时才回复
        self.group_welcome = False      # 群新人欢迎语开关
        self.group_welcome_random = 1.0 # 群新人欢迎语触发概率（0.0~1.0）
        self.group_welcome_msg = "欢迎新朋友！请先查看群公告！"

        # ---------- 新好友配置 ----------
        self.new_friend_switch = False        # 自动通过新好友开关
        self.new_friend_reply_switch = False   # 新好友自动回复开关
        self.new_friend_msg = []               # 通过后自动发送的打招呼消息列表
        self.new_friend_remark_use_nickname = True
        self.new_friend_remark_prefix_timestamp = False
        self.new_friend_remark_suffix_timestamp = False

        # ---------- 关键词回复配置 ----------
        self.chat_keyword_switch = False    # 私聊关键词回复开关
        self.group_keyword_switch = False   # 群聊关键词回复开关
        self.group_keyword_at_only = False  # 群聊关键词仅被@时触发
        self.keyword_reply_quote = False     # 关键词回复是否引用消息（私聊/群聊均生效）
        self.group_keyword_reply_at_msg = False   # 群聊关键词回复是否@发言人
        self.keyword_dict = {}              # 关键词 -> 回复内容 字典

        # ---------- 多条消息缓冲合并回复配置 ----------
        self.merge_reply_switch    = False   # 总开关（默认关，行为与未实现前一致）
        self.merge_reply_window    = 5       # 缓冲等待秒数（窗口内没有新消息才回复）
        self.merge_reply_max_count = 10      # 最多合并条数，达到即触发

        # ---------- 自定义转发配置 ----------
        self.custom_forward_switch = False  # 自定义转发总开关
        self.custom_forward_list   = []     # 自定义转发规则列表

        # ---------- 多 Prompt 配置 ----------
        self.default_prompt   = "默认"      # 全局/fallback prompt 文件名（不含 .md）
        self.chat_prompt_map  = {}          # 私聊白名单用户 -> prompt 名称
        self.chat_api_map     = {}          # 私聊白名单用户 -> API 接口索引
        self.chat_max_round_map = {}        # 私聊白名单用户 -> 专属回复轮数上限
        self.group_prompt_map = {}          # 群组名称 -> prompt 名称

        # ---------- 定时消息配置 ----------
        self.scheduled_msg_switch = False    # 定时消息总开关
        self.scheduled_msg_list = []         # 定时消息任务列表

        # ---------- 随机定时消息配置 ----------
        self.random_msg_switch = False  # 随机定时消息总开关
        self.random_msg_list   = []     # 随机定时消息任务列表

        # ---------- 定时朋友圈配置 ----------
        self.scheduled_moments_switch = False  # 定时朋友圈总开关
        self.scheduled_moments_list = []       # 定时朋友圈任务列表

        # ---------- 随机朋友圈点赞配置 ----------
        self.moments_like_switch = False  # 随机点赞总开关
        self.moments_like_min    = 60     # 随机间隔最小分钟数
        self.moments_like_max    = 120    # 随机间隔最大分钟数

        # ---------- 随机定时朋友圈配置 ----------
        self.random_moments_switch = False  # 随机定时朋友圈总开关
        self.random_moments_list   = []     # 随机定时朋友圈任务列表

        # ---------- 对话记忆配置 ----------
        self.memory_switch        = True      # 记忆开关（默认开启）
        self.memory_max_count     = 3000     # 单窗口最多存储条数（上限 5000）
        self.memory_context_count = 1000     # AI 请求时带入条数

        # ---------- 发送延迟配置 ----------
        self.reply_delay_switch = True  # 模拟人工操作延迟开关（默认开启）
        self.reply_delay_min    = 1     # 最小延迟秒数
        self.reply_delay_max    = 5     # 最大延迟秒数
        self.clean_ai_reply_switch = True  # AI 回复清洗开关

        # 初始化时自动加载配置并同步到属性
        self.load_config()
        self.update_global_config()

    # ----------------------------------------------------------
    # 配置文件读写
    # ----------------------------------------------------------

    def load_config(self):
        """从 config.json 加载配置到 self.config 字典"""
        # 若配置文件不存在，先创建默认配置
        if not os.path.exists(self.CONFIG_FILE):
            self.create_new_config_file()
        try:
            with open(self.CONFIG_FILE, 'r', encoding='utf-8') as file:
                self.config = json.load(file)
                log(message="配置文件加载成功")
        except Exception as e:
            # 保存已改为原子替换，正常情况下不会读到半截文件；这里防的是极端时序
            for _ in range(5):
                time.sleep(0.2)
                try:
                    with open(self.CONFIG_FILE, 'r', encoding='utf-8') as file:
                        self.config = json.load(file)
                    log(message="配置文件加载成功（重试后）")
                    break
                except Exception:
                    pass
            else:
                log(level="ERROR", message="打开配置文件失败，请检查配置文件！" + str(e))
                # 不带着坏配置继续运行；但也不永久卡死：每 30 秒重试一次，
                # 用户修好配置文件后会自动恢复，而不是静默挂起到重启为止
                while True:
                    time.sleep(30)
                    try:
                        with open(self.CONFIG_FILE, 'r', encoding='utf-8') as file:
                            self.config = json.load(file)
                        log(message="配置文件已恢复，继续启动")
                        break
                    except Exception:
                        continue
        # 记录磁盘快照：save_config() 靠它算出"改了哪些字段"，
        # 从而只提交差异，不再整份内存快照覆盖别处的改动
        self._loaded_snapshot = copy.deepcopy(self.config)

    def create_new_config_file(self):
        """若配置文件不存在，则创建一份包含默认值的配置文件"""
        try:
            if not os.path.exists(self.CONFIG_FILE):
                base_config = dict(config_defaults.DEFAULT_CONFIG)
                _get_config_store(self.CONFIG_FILE).write(base_config)
                log(message=f"已创建默认配置文件：\n{os.path.abspath(self.CONFIG_FILE)}\n请根据需求修改配置后重启")
        except Exception as e:
            log(level="ERROR", message="创建默认配置文件失败，请检查配置文件！" + str(e))
            # 同 load_config：不永久卡死，每 30 秒重试，磁盘恢复后自动继续
            while True:
                time.sleep(30)
                try:
                    _get_config_store(self.CONFIG_FILE).write(dict(config_defaults.DEFAULT_CONFIG))
                    log(message="默认配置文件已创建，继续启动")
                    break
                except Exception:
                    continue

    def save_config(self):
        """把**改动过的字段**提交给 ConfigStore（不再整份内存快照写回）。

        原来直接写 self.config：bot 内存里是启动时的快照，面板刚保存的改动
        会被整份覆盖回去。现在只提交与"最近一次加载"不同的键，
        由 ConfigStore 在路径锁内合并到磁盘现值上，两边的改动都不会丢。

        :return: True=已落盘（或无改动）；False=写盘失败。
                 调用方必须据此决定要不要报"已完成"，不能再无条件报成功。
        """
        try:
            patch = {
                k: v for k, v in self.config.items()
                if k not in self._loaded_snapshot or self._loaded_snapshot[k] != v
            }
            removed = [k for k in self._loaded_snapshot if k not in self.config]
            if not patch and not removed:
                return True
            merged, _rev = _get_config_store(self.CONFIG_FILE).update(patch, delete=removed)
            # 同步回内存，保持"快照 == 磁盘现状"，下一次差异计算才准确
            self.config = merged
            self._loaded_snapshot = copy.deepcopy(merged)
            return True
        except Exception as e:
            log(level="ERROR", message="保存配置文件失败:" + str(e))
            return False

    def refresh_config(self):
        """重新加载配置文件，并将最新值同步到所有属性。

        ⚠ 只覆盖"立即生效"的字段。默认 API 客户端与监听/定时任务注册不在这里，
          运行中的应用入口是 WXBot.apply_config()，约定见 config_apply.py。
        """
        self.load_config()
        self.update_global_config()

    def init_prompt_dir(self):
        """确保 prompt 目录存在；迁移旧 prompt 字段；空目录时写入默认 prompt"""
        os.makedirs(self.prompt_dir, exist_ok=True)
        # 迁移旧 prompt 字段：先写文件，成功后才删字段并保存，防止写入失败时数据丢失
        if 'prompt' in self.config:
            target = os.path.join(self.prompt_dir, '默认.md')
            try:
                with open(target, 'w', encoding='utf-8') as f:
                    f.write(self.config['prompt'])
                del self.config['prompt']
                self.save_config()
                log(message="已将旧 prompt 字段迁移至 config/prompt/默认.md")
            except Exception as e:
                log(level="ERROR", message=f"迁移 prompt 到文件失败: {e}，旧 prompt 字段已保留")
        # 空目录兜底
        try:
            md_files = [f for f in os.listdir(self.prompt_dir) if f.endswith('.md')]
        except Exception:
            md_files = []
        if not md_files:
            try:
                with open(os.path.join(self.prompt_dir, '默认.md'), 'w', encoding='utf-8') as f:
                    f.write("你是一个ai回复助手，请根据用户的问题给出回答,回复尽量保持在30字以内")
            except Exception as e:
                log(level="ERROR", message=f"创建默认 prompt 文件失败: {e}")

    def get_prompt_content(self, name):
        """按名称读取 prompt 文件内容，找不到时 fallback 到 default_prompt，最终返回空字符串"""
        if not name:
            name = self.default_prompt
        path = os.path.join(self.prompt_dir, f'{name}.md')
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception:
                pass
        # fallback 到 default_prompt
        if name != self.default_prompt:
            fallback = os.path.join(self.prompt_dir, f'{self.default_prompt}.md')
            if os.path.exists(fallback):
                try:
                    with open(fallback, 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception:
                    pass
        return ""

    # ----------------------------------------------------------
    # 配置同步：将 config 字典中的值同步到实例属性
    # ----------------------------------------------------------

    def update_global_config(self):
        """把 self.config 里的每个配置键同步到实例属性（运行期只读属性，不再读字典）。

        本函数是「配置键 → 运行行为」的唯一映射点，按配置域分段，每段用
        `# --- xxx ---` 标注。新增字段时在对应段里加一行 self.xxx = self.config.get(...)。

        ⚠ 三个必须知道的既有行为：
          1. 部分字段调用 self.config.get('键') 时不给默认值（如 AllListen_switch /
             group_switch / group_welcome），配置缺键时属性是 None 而不是 False。
             新增字段请显式给默认值。
          2. 数值字段已统一改用 _coerce_int_range()（类型转换 + 区间钳位）。
             仅剩 3 处直接 int()：api_index、chat_image_recognition_api、
             group_image_recognition_api，三者自带 try/except 与越界回退，可安全保留。
             注意调用方 run_bot() 线程没有 except，任何未捕获异常都只表现为
             「机器人启动后立刻变成未运行」。
          3. 函数内部会主动写盘（旧格式迁移、补默认值），老配置文件首次启动会被重写一次。
        """
        # --- AI 接口列表（新格式）与旧格式迁移 ---
        # 迁移 + 默认值 + 规范化统一走 config_defaults.prepare（幂等、新字段优先），
        # 与面板 /dashboard 是同一份实现，保证两条入口结果一致。
        _before_migrate = dict(self.config)
        config_defaults.prepare(self.config)
        if self.config != _before_migrate:
            self.save_config()
            log(message="旧配置已迁移/规范化并补齐默认值，已写回配置文件")

        _api_configs = self.config.get('api_configs', [
            {"sdk": "", "key": "", "url": "", "model": "", "fallback_api_index": -1},
            {"sdk": "", "key": "", "url": "", "model": "", "fallback_api_index": -1},
        ])
        if not isinstance(_api_configs, list):
            _api_configs = [
                {"sdk": "", "key": "", "url": "", "model": "", "fallback_api_index": -1},
                {"sdk": "", "key": "", "url": "", "model": "", "fallback_api_index": -1},
            ]
        self.api_configs = _normalize_api_configs(_api_configs)
        self.config['api_configs'] = self.api_configs
        try:
            self.api_index = int(self.config.get('api_index', 0))
        except (TypeError, ValueError):
            self.api_index = 0
        if self.api_index < 0 or self.api_index >= len(self.api_configs):
            self.api_index = 0

        # 接口名称迁移：OpenAI SDK → OpenAI API 格式兼容接口（兼容旧配置）
        _sdk_renamed = False
        for _cfg in self.api_configs:
            if _cfg.get('sdk') == 'OpenAI SDK':
                _cfg['sdk'] = OPENAI_SDK_NAME
                _sdk_renamed = True
        if _sdk_renamed:
            self.save_config()
            log(message="接口名称已自动更新：OpenAI SDK → OpenAI API 格式兼容接口")

        # --- 从当前接口派生兼容属性（api_sdk / api_key / base_url / model1）---
        _cur = self.api_configs[self.api_index] if self.api_configs else {}
        self.api_sdk  = _cur.get('sdk', '')
        self.api_key  = _cur.get('key', '')
        self.base_url = _cur.get('url', '')
        self.model1   = _cur.get('model', '')
        self.prompt   = self.config.get('prompt', "")

        # --- 微信基础配置（管理员 / 监听名单 / 全局监听模式）---
        self.cmd            = self.config.get('admin', "")
        self.listen_list          = self.config.get('listen_list', [])
        self.AllListen_switch     = self.config.get('AllListen_switch')
        self.AllListen_filter_mute = bool(self.config.get('AllListen_filter_mute', True))
        self.chat_listen_only     = bool(self.config.get('chat_listen_only', False))

        # 配置中只保存用户附加项，保留 wxautox 内置的特殊会话名单。
        _special_session_names = self.config.get('special_session_name', [])
        if not isinstance(_special_session_names, list):
            _special_session_names = []
        self.special_session_name = []
        for _session_name in _special_session_names:
            _session_name = str(_session_name).strip()
            if _session_name and _session_name not in self.special_session_name:
                self.special_session_name.append(_session_name)

        # 面板进程内重启机器人时，先移除上次由配置追加的项，使删除操作也能生效。
        global _CONFIG_SPECIAL_SESSION_NAMES
        for _session_name in _CONFIG_SPECIAL_SESSION_NAMES:
            if _session_name in WxParam.SPECIAL_SESSION_NAME:
                WxParam.SPECIAL_SESSION_NAME.remove(_session_name)
        _CONFIG_SPECIAL_SESSION_NAMES.clear()
        for _session_name in self.special_session_name:
            if _session_name not in WxParam.SPECIAL_SESSION_NAME:
                WxParam.SPECIAL_SESSION_NAME.append(_session_name)
                _CONFIG_SPECIAL_SESSION_NAMES.add(_session_name)

        # --- 群聊配置 ---
        self.group                = self.config.get('group', [])
        self.group_api_map        = self.config.get('group_api_map', {})
        self.group_switch         = self.config.get('group_switch')
        self.group_listen_only    = bool(self.config.get('group_listen_only', False))
        self.group_reply_at       = self.config.get('group_reply_at')
        self.group_reply_at_msg   = bool(self.config.get('group_reply_at_msg', True))
        self.group_reply_quote    = bool(self.config.get('group_reply_quote', False))
        self.group_welcome        = self.config.get('group_welcome')
        self.group_welcome_random = self.config.get('group_welcome_random')
        self.group_welcome_msg    = self.config.get('group_welcome_msg', '欢迎新朋友！请先查看群公告！')

        # --- 新好友配置（自动通过 / 自动回复 / 备注规则）---
        self.new_friend_switch       = self.config.get('new_friend_switch')
        self.new_friend_reply_switch  = self.config.get('new_friend_reply_switch', False)
        self.new_friend_msg           = self.config.get('new_friend_msg', [])
        self.new_friend_check_min    = self._coerce_int_range(self.config.get('new_friend_check_min'), 60, 60, 3600)
        self.new_friend_check_max    = self._coerce_int_range(self.config.get('new_friend_check_max'), 300, self.new_friend_check_min, 3600)
        self.new_friend_remark_use_nickname = bool(self.config.get('new_friend_remark_use_nickname', True))
        self.new_friend_remark_prefix = self.config.get('new_friend_remark_prefix', '')
        self.new_friend_remark_prefix_timestamp = bool(self.config.get('new_friend_remark_prefix_timestamp', False))
        self.new_friend_remark_suffix = self.config.get('new_friend_remark_suffix', '_机器人备注')
        self.new_friend_remark_suffix_timestamp = bool(self.config.get('new_friend_remark_suffix_timestamp', False))
        self.new_friend_tags         = self.config.get('new_friend_tags', [])

        # --- 关键词回复配置 ---
        self.chat_keyword_switch   = self.config.get('chat_keyword_switch')
        self.group_keyword_switch  = self.config.get('group_keyword_switch')
        self.group_keyword_at_only = self.config.get('group_keyword_at_only', False)
        self.keyword_reply_quote = bool(self.config.get(
            'keyword_reply_quote',
            self.config.get('group_keyword_reply_quote', False)
        ))
        self.group_keyword_reply_at_msg = bool(self.config.get('group_keyword_reply_at_msg', False))
        self.keyword_dict          = self.config.get('keyword_dict', {})

        # --- 定时消息配置 ---
        self.scheduled_msg_switch = self.config.get('scheduled_msg_switch',
                                                     self.config.get('everyday_msg_switch', False))
        self.scheduled_msg_list   = self.config.get('scheduled_msg_list', [])

        # --- 随机定时消息配置 ---
        self.random_msg_switch = self.config.get('random_msg_switch', False)
        self.random_msg_list   = self.config.get('random_msg_list', [])

        # --- 定时朋友圈配置 ---
        self.scheduled_moments_switch = self.config.get('scheduled_moments_switch', False)
        self.scheduled_moments_list   = self.config.get('scheduled_moments_list', [])

        # --- 随机朋友圈点赞配置 ---
        self.moments_like_switch = self.config.get('moments_like_switch', False)
        self.moments_like_min    = self._coerce_int_range(self.config.get('moments_like_min'), 60, 1, 1440)
        self.moments_like_max    = self._coerce_int_range(self.config.get('moments_like_max'), 120, self.moments_like_min, 1440)

        # --- 随机定时朋友圈配置 ---
        self.random_moments_switch = self.config.get('random_moments_switch', False)
        self.random_moments_list   = self.config.get('random_moments_list', [])

        # 旧配置自动迁移：everyday_msg_dict -> scheduled_msg_list
        if not self.scheduled_msg_list and self.config.get('everyday_msg_dict'):
            import uuid
            for target, tasks in self.config.get('everyday_msg_dict', {}).items():
                for task in tasks:
                    self.scheduled_msg_list.append({
                        'id': str(uuid.uuid4())[:8],
                        'enabled': True,
                        'targets': [target],
                        'time': task.get('time', '08:00'),
                        'repeat_type': 'daily',
                        'weekdays': [],
                        'dates': [],
                        'msgs': task.get('msgs', []),
                    })

        # 旧配置自动迁移：target(str) -> targets(list)
        _target_migrated = False
        for task in self.scheduled_msg_list:
            if 'targets' not in task:
                old = task.pop('target', '')
                task['targets'] = [old] if old else []
                _target_migrated = True
        if _target_migrated:
            self.config['scheduled_msg_list'] = self.scheduled_msg_list
            self.save_config()
            log(message="已自动迁移定时消息发送目标格式 target -> targets 并写回配置文件")

        # --- 对话记忆配置 ---
        self.memory_switch        = self.config.get('memory_switch', True)
        self.memory_max_count     = self._coerce_int_range(self.config.get('memory_max_count'), 3000, 1, 99999)
        self.memory_context_count = self._coerce_int_range(self.config.get('memory_context_count'), 1000, 1, 99999)

        # --- 发送延迟配置（缺键已由上面的 apply_defaults 统一补齐）---
        self.reply_delay_switch = bool(self.config.get('reply_delay_switch', True))
        self.reply_delay_min    = self._coerce_int_range(self.config.get('reply_delay_min'), 1, 1, 3600)
        self.reply_delay_max    = self._coerce_int_range(self.config.get('reply_delay_max'), 5, 1, 3600)
        self.clean_ai_reply_switch = bool(self.config.get('clean_ai_reply_switch', True))

        # --- 图片识别配置 ---
        self.chat_image_recognition_switch  = bool(self.config.get('chat_image_recognition_switch', False))
        try:
            self.chat_image_recognition_api = int(self.config.get('chat_image_recognition_api', 0))
        except (TypeError, ValueError):
            self.chat_image_recognition_api = 0
        if self.chat_image_recognition_api < 0 or self.chat_image_recognition_api >= len(self.api_configs):
            self.chat_image_recognition_api = 0
        self.group_image_recognition_switch = bool(self.config.get('group_image_recognition_switch', False))
        try:
            self.group_image_recognition_api = int(self.config.get('group_image_recognition_api', 0))
        except (TypeError, ValueError):
            self.group_image_recognition_api = 0
        if self.group_image_recognition_api < 0 or self.group_image_recognition_api >= len(self.api_configs):
            self.group_image_recognition_api = 0

        # --- 自定义转发配置 ---
        self.custom_forward_switch = bool(self.config.get('custom_forward_switch', False))
        self.custom_forward_list   = self.config.get('custom_forward_list', [])

        # --- 多 Prompt 配置（含 prompt 目录初始化）---
        self.default_prompt   = self.config.get('default_prompt', '默认')
        self.chat_prompt_map  = self.config.get('chat_prompt_map', {})
        self.chat_api_map     = self.config.get('chat_api_map', {})
        self.chat_max_round_map = self._normalize_chat_max_round_map(
            self.config.get('chat_max_round_map', {})
        )
        self.group_prompt_map = self.config.get('group_prompt_map', {})
        self.init_prompt_dir()

        # --- 接口调用失败时的固定回复 ---
        self.api_error_reply = self.config.get('api_error_reply', '在忙，我稍后回复您')
        self.api_error_reply_once = bool(self.config.get('api_error_reply_once', False))

        # --- 单用户最大回复轮数限制配置 ---
        self.chat_max_round_switch = bool(self.config.get('chat_max_round_switch', False))
        self.chat_max_round_default = self._coerce_int_range(self.config.get('chat_max_round_default', 99), 99, 1, 99999)
        self.chat_max_round_reset_days = self._coerce_int_range(self.config.get('chat_max_round_reset_days', 0), 0, 0, 365)
        self.chat_max_round_reply = self.config.get('chat_max_round_reply', '')
        self.chat_max_round_reply_once = bool(self.config.get('chat_max_round_reply_once', False))

        # --- 拆分多条回复配置 ---
        self.chat_split_reply_switch  = bool(self.config.get('chat_split_reply_switch', False))
        self.chat_split_max_chars     = self._coerce_int_range(self.config.get('chat_split_max_chars'), 100, 1, 99999)
        self.chat_split_max_count     = self._coerce_int_range(self.config.get('chat_split_max_count'), 4, 1, 999)
        self.group_split_reply_switch = bool(self.config.get('group_split_reply_switch', False))
        self.group_split_max_chars    = self._coerce_int_range(self.config.get('group_split_max_chars'), 100, 1, 99999)
        self.group_split_max_count    = self._coerce_int_range(self.config.get('group_split_max_count'), 4, 1, 999)

        # --- 多条消息缓冲合并回复配置 ---
        self.merge_reply_switch    = bool(self.config.get('merge_reply_switch', False))
        self.merge_reply_window    = self._coerce_int_range(self.config.get('merge_reply_window'), 5, 1, 300)
        self.merge_reply_max_count = self._coerce_int_range(self.config.get('merge_reply_max_count'), 10, 1, 100)
        # --- SiverPanel 远程访问配置 ---
        # 缺键与旧域名迁移都已由上面的 config_defaults.migrate / apply_defaults 统一处理

        log(message="全局配置更新完成")

    def set_config(self, id, new_content):
        """修改指定配置项并保存。

        :return: True=已落盘；False=写盘失败（调用方不得再报"已完成"）。
        """
        self.config[id] = new_content
        if not self.save_config():
            self._mark_save_failed(id)
            return False
        self.refresh_config()
        log(message=id + "已更改为:" + str(self.config[id]))
        return True

    def _mark_save_failed(self, key):
        """记录一次保存失败；管理员命令收尾时会据此如实提示。"""
        self.save_failed = True
        log(level="ERROR", message=f"{key} 保存失败，本次修改未写入配置文件")

    # ----------------------------------------------------------
    # 监听用户管理
    # ----------------------------------------------------------

    def add_user(self, name):
        """将用户添加到监听列表（白名单/黑名单）"""
        if name not in self.config.get('listen_list', []):
            self.config['listen_list'].append(name)
            if not self.save_config():
                self._mark_save_failed('listen_list')
            self.refresh_config()
            log(message="添加后的监听用户列表:" + str(self.config['listen_list']))
        else:
            log(message=f"用户 {name} 已在监听列表中")

    def remove_user(self, name):
        """从监听列表中删除指定用户"""
        if name in self.listen_list:
            self.config['listen_list'].remove(name)
            if not self.save_config():
                self._mark_save_failed('listen_list')
            self.refresh_config()
            log(message="删除后的监听用户列表:" + str(self.config['listen_list']))
        else:
            log(message=f"用户 {name} 不在监听列表中")

    # ----------------------------------------------------------
    # 监听群组管理
    # ----------------------------------------------------------

    def add_group(self, name):
        """将群组添加到监听列表"""
        if name not in self.config.get('group', []):
            self.config['group'].append(name)
            if not self.save_config():
                self._mark_save_failed('group')
            self.refresh_config()
            log(message="添加后的监听群组列表:" + str(self.config['group']))
        else:
            log(message=f"群组 {name} 已在监听列表中")

    def remove_group(self, name):
        """从监听列表中删除指定群组"""
        if name in self.config.get('group', []):
            self.config['group'].remove(name)
            if not self.save_config():
                self._mark_save_failed('group')
            self.refresh_config()
            log(message="删除后的监听群组列表:" + str(self.config['group']))
        else:
            log(message=f"群组 {name} 不在监听列表中")

    def set_group_switch(self, switch_value):
        """设置群机器人总开关"""
        self.config['group_switch'] = switch_value
        if not self.save_config():
            self._mark_save_failed('group_switch')
        self.refresh_config()
        log(message="群开关设置为" + str(self.config['group_switch']))

    # ----------------------------------------------------------
    # 工具方法（静态）
    # ----------------------------------------------------------

    @staticmethod
    def split_long_text(text, chunk_size=2000):
        """将超长文本按指定长度切分为列表，用于分段发送"""
        return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    @staticmethod
    def _normalize_chat_max_round_map(raw_map):
        """清洗私聊白名单用户的专属回复轮数上限配置"""
        if not isinstance(raw_map, dict):
            return {}
        clean = {}
        for name, value in raw_map.items():
            name = str(name).strip()
            if not name:
                continue
            try:
                value = int(value)
            except Exception:
                continue
            clean[name] = max(1, min(99999, value))
        return clean

    @staticmethod
    def _coerce_int_range(value, default, min_value, max_value):
        """将配置值转为指定范围内的整数"""
        try:
            value = int(value)
        except Exception:
            value = default
        return max(min_value, min(max_value, value))

    def human_delay(self):
        """模拟人工操作随机延迟。reply_delay_switch 关闭时直接跳过。"""
        if not self.reply_delay_switch:
            return
        lo = min(self.reply_delay_min, self.reply_delay_max)
        hi = max(self.reply_delay_min, self.reply_delay_max)
        time.sleep(random.randint(lo, hi))

    @staticmethod
    def get_run_time(start_time):
        """计算并返回自 start_time 至今的运行时长，格式：X天X时X分X秒"""
        delta = datetime.now() - start_time
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{days}天{hours}时{minutes}分{seconds}秒"


# ============================================================
# 对话记忆管理类
#
# ⚠ 记忆目录归属规则、会话锁、旧目录迁移的实现全部在 memory_store.py 里，
#   面板（web_server.py）也导入同一份实现。这里只做转发导入，
#   不允许再在本文件里另写一套路径规则（两边规则不一致会导致
#   「面板看到的」和「机器人写的」对不上）。
# ============================================================

from memory_store import (                       # noqa: E402  (放在此处便于阅读)
    MemoryManager,
    LegacyMigration,
    resolve_storage_key,
    read_original_name,
    is_storage_key,
    get_memory_manager,
)


# ============================================================
# 回复计数器管理类
# ============================================================


class ReplyCountStore:
    """
    私聊回复计数器管理类。
    负责持久化每个用户的 AI 回复次数、超限通知状态和 API 错误通知状态。
    """

    DEFAULT_DATA = {"meta": {"last_reset_date": ""}, "users": {}}

    def __init__(self, file_path):
        """加载计数文件，并建立进程内可重入锁（保护多线程读改写）。"""
        self.file_path = file_path
        self._lock = threading.RLock()
        self.data = self._load()

    @classmethod
    def _empty_data(cls):
        return {"meta": {"last_reset_date": ""}, "users": {}}

    @classmethod
    def _normalize_user_data(cls, user_data):
        if not isinstance(user_data, dict):
            user_data = {}
        try:
            ai_count = int(user_data.get("ai_count", 0))
        except Exception:
            ai_count = 0
        return {
            "ai_count": max(0, ai_count),
            "api_err_notified": bool(user_data.get("api_err_notified", False)),
            "limit_notified": bool(user_data.get("limit_notified", False)),
        }

    @classmethod
    def _normalize_data(cls, raw_data):
        if not isinstance(raw_data, dict):
            return cls._empty_data()
        meta = raw_data.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}
        users = raw_data.get("users", {})
        if not isinstance(users, dict):
            users = {}
        normalized_users = {}
        for user, user_data in users.items():
            user = str(user).strip()
            if user:
                normalized_users[user] = cls._normalize_user_data(user_data)
        return {
            "meta": {"last_reset_date": str(meta.get("last_reset_date", "") or "")},
            "users": normalized_users,
        }

    def _load(self):
        if not os.path.exists(self.file_path):
            return self._empty_data()
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return self._normalize_data(json.load(f))
        except Exception as e:
            log(level="WARNING", message=f"加载 reply_count.json 失败: {e}")
            return self._empty_data()

    def _save_locked(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        tmp_path = self.file_path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_path, self.file_path)

    def save(self):
        with self._lock:
            self._save_locked()

    def get_user(self, user_key):
        user_key = str(user_key).strip()
        with self._lock:
            users = self.data.setdefault("users", {})
            if user_key not in users:
                users[user_key] = self._normalize_user_data({})
            else:
                users[user_key] = self._normalize_user_data(users[user_key])
            return users[user_key]

    def maybe_reset(self, reset_days, now=None):
        try:
            reset_days = int(reset_days)
        except Exception:
            reset_days = 0
        if reset_days <= 0:
            return False
        now = now or datetime.now()
        today = now.strftime("%Y-%m-%d")
        with self._lock:
            meta = self.data.setdefault("meta", {})
            last = str(meta.get("last_reset_date", "") or "")
            if not last:
                meta["last_reset_date"] = today
                self._save_locked()
                return False
            try:
                last_dt = datetime.strptime(last, "%Y-%m-%d")
            except Exception:
                meta["last_reset_date"] = today
                self._save_locked()
                return False
            delta = (now - last_dt).days
            if delta >= reset_days:
                self.data["users"] = {}
                meta["last_reset_date"] = today
                self._save_locked()
                log(message=f"回复计数器已重置（周期 {reset_days} 天）")
                return True
        return False

    def increment_ai_count(self, user_key):
        with self._lock:
            user_data = self.get_user(user_key)
            user_data["ai_count"] = user_data.get("ai_count", 0) + 1
            self._save_locked()
            return user_data["ai_count"]

    def mark_limit_notified(self, user_key):
        with self._lock:
            user_data = self.get_user(user_key)
            if user_data.get("limit_notified"):
                return False
            user_data["limit_notified"] = True
            self._save_locked()
            return True

    def mark_api_err_notified(self, user_key):
        with self._lock:
            user_data = self.get_user(user_key)
            if user_data.get("api_err_notified"):
                return False
            user_data["api_err_notified"] = True
            self._save_locked()
            return True

    def clear_user(self, user_key):
        user_key = str(user_key).strip()
        with self._lock:
            users = self.data.setdefault("users", {})
            if user_key not in users:
                return False
            del users[user_key]
            self._save_locked()
            return True

    @staticmethod
    def was_send_success(result, none_is_success=False):
        """判断一次发送是否算成功。

        :param none_is_success: 是否把 ``None`` 当作成功。
            wxautox 的 ``SendFiles`` 经常"发成功了也没有返回值"（返回 None），
            这些调用点显式传 True。
            ⚠ 默认值必须是 False、不能全局放宽：本文件里 ``result = None`` 同时被当作
            "发送抛异常"的哨兵值（例如异常分支 ``result = None; send_aborted = True``），
            全局把 None 当成功，会把真正的发送异常计成成功。
        """
        if result is True:
            return True
        if result is False:
            return False
        if result is None:
            return bool(none_is_success)
        if isinstance(result, dict):
            status = str(result.get("status", "")).lower()
            if status in ("success", "ok", "true", "成功"):
                return True
            if status in ("error", "fail", "failed", "false", "失败", "错误"):
                return False
            if result.get("code") == 0:
                return True
            if result.get("success") is True:
                return True
            if result.get("success") is False:
                return False
        return bool(result)

    @staticmethod
    def send_result_message(result):
        if isinstance(result, dict):
            return result.get("message") or str(result)
        try:
            return result["message"]
        except Exception:
            return str(result)


class SendOutcome(dict):
    """
    一次发送（可能含多段）的统一结果。

    与 wxautox4 的 WxResponse 同构：dict 形态（status / message / data），
    且只有“成功”状态为真。这样 ReplyCountStore.was_send_success()、
    ReplyCountStore.send_result_message() 以及回调里的 if not result
    都能原样消费，不需要改动既有消费方。

    状态取值：成功 = 全部段成功；部分成功 = 至少一段成功且有失败段；
              失败 = 全部段都没发出去。
    """

    def __init__(self, status="成功", message=None, data=None):
        super().__init__(status=status, message=message, data=data)

    def __bool__(self):
        return self["status"] == "成功"

    @classmethod
    def success(cls, message=None, data=None):
        return cls("成功", message, data)

    @classmethod
    def partial(cls, message=None, data=None):
        return cls("部分成功", message, data)

    @classmethod
    def failure(cls, message="", data=None):
        return cls("失败", message, data)


class _MergedMessage:
    """合并缓冲 flush 时传给 process_message 的合成消息对象。

    只提供下游真正读取的字段（content / sender / type / merged_image）；
    其余属性（quote 等）代理给最后一条真实消息，所以合并后的消息仍然可以引用、
    @，不会"引用失败就降级"。
    """

    def __init__(self, content, sender, msg_type, merged_image, last_msg):
        self.content      = content
        self.sender       = sender
        self.type         = msg_type
        self.merged_image = merged_image
        # 用 __dict__ 存，避免 __getattr__ 在属性缺失时递归
        self.__dict__['_last_msg'] = last_msg

    def quote(self, *args, **kwargs):
        return self.__dict__['_last_msg'].quote(*args, **kwargs)

    def __getattr__(self, name):
        # 只在正常属性查不到时触发（如 attr / id / download）
        return getattr(self.__dict__['_last_msg'], name)


# ============================================================
# AI 接口类
# ============================================================

# ----------------------------------------------------------
# UnconfiguredAPI：未配置接口时的占位实现（保证非 AI 功能可用）
# ----------------------------------------------------------


class UnconfiguredAPI:
    """未配置 AI 接口时的轻量占位实现，保证非 AI 功能可以正常运行。"""

    def __init__(self, config):
        """只取 model1 作为展示用的模型名，不建立任何客户端连接。"""
        self.DS_NOW_MOD = getattr(config, 'model1', '') or ''

    def chat(self, *args, **kwargs):
        log(level="WARNING", message="未配置 API 接口，已跳过 AI 调用")
        return "API返回错误，请稍后再试"


# ----------------------------------------------------------
# OpenAIAPI：OpenAI API 格式兼容接口（DeepSeek / 通义 等）
# ----------------------------------------------------------


class OpenAIAPI:
    """
    OpenAI API 格式兼容接口封装类（面板中名称为「OpenAI API 格式兼容接口」）
    适用于所有兼容 OpenAI API 格式的 AI 服务（如 DeepSeek、通义等）。
    """

    def __init__(self, config):
        """按配置建立 OpenAI 兼容客户端（含超时与自定义 headers）。"""
        self.config = config
        self.DS_NOW_MOD = config.model1  # 当前使用的模型，默认为 model1
        # 添加更详细的日志配置和自定义 headers（用于备用方案）
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=180.0,  # 设置超时时间
            max_retries=2,  # 设置重试次数
            default_headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*"
            }
        )

    @staticmethod
    def _image_to_data_url(image_path: str = "", image_url: str = "") -> str:
        if image_path:
            mime_type, _ = mimetypes.guess_type(image_path)
            if mime_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                mime_type = "image/jpeg"
            with open(image_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("utf-8")
            return f"data:{mime_type};base64,{image_data}"
        if image_url:
            return image_url
        raise ValueError("image_path 和 image_url 不能同时为空")

    @classmethod
    def _build_chat_image_block(cls, image_path: str = "", image_url: str = "") -> dict:
        return {
            "type": "image_url",
            "image_url": {"url": cls._image_to_data_url(image_path, image_url)}
        }

    @classmethod
    def _build_responses_image_block(cls, image_path: str = "", image_url: str = "") -> dict:
        return {
            "type": "input_image",
            "image_url": cls._image_to_data_url(image_path, image_url)
        }

    def _build_history_messages(self, history):
        """将记忆历史转换为 OpenAI 消息列表（主路径与备用路径共用）"""
        messages = []
        for h in history or []:
            role = "assistant" if h.get('attr') == 'self' else "user"
            t = h.get('time', '')
            raw = h.get('content', '')
            sender = h.get('sender', '')
            if role == 'user' and sender:
                content = f"[{t}] {sender}: {raw}" if t else f"{sender}: {raw}"
            else:
                content = f"[{t}] {raw}" if t else raw
            messages.append({"role": role, "content": content})
        return messages

    def chat(self, message, model=None, stream=False, prompt=None, history=None,
             image_path: str = "", image_url: str = ""):
        """
        调用 OpenAI 兼容接口获取 AI 回复。

        :param message: 用户输入的消息内容
        :param model:   指定模型，为 None 时使用当前默认模型
        :param stream:  是否使用流式输出
        :param prompt:  系统提示词，为 None 时使用配置中的 prompt
        :param history: 历史消息列表（MemoryManager.get_messages 返回值）
        :param image_path: 本地图片路径，优先于 image_url
        :param image_url:  图片 URL，image_path 为空时使用
        :return:        AI 回复的文本字符串
        """
        if model is None:
            model = self.DS_NOW_MOD
        if prompt is None:
            prompt = self.config.prompt

        messages = [{"role": "system", "content": prompt}]
        if history:
            messages.extend(self._build_history_messages(history))
        if image_path or image_url:
            user_content = [
                {"type": "text", "text": message},
                self._build_chat_image_block(image_path, image_url),
            ]
        else:
            user_content = message
        messages.append({"role": "user", "content": user_content})

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                stream=stream,
            )
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            log(level="WARN", message=f"Chat Completions API 调用失败 [{error_type}]: {error_msg}")
            log(level="INFO", message="尝试备用方案（Responses API）")
            return self._try_responses_api(message, model, stream, prompt, history, image_path, image_url)

        try:
            if stream:
                # 流式模式：逐块拼接思维链内容与正式回复内容
                reasoning_content = ""
                content = ""
                chunk_count = 0

                for chunk in response:
                    chunk_count += 1

                    # 检查 chunk 是否有 choices 属性
                    if not chunk.choices:
                        continue

                    choice = chunk.choices[0]
                    if not hasattr(choice, 'delta'):
                        continue

                    delta = choice.delta

                    # 优先拼接思维链内容（如 DeepSeek-R1 等支持 reasoning_content 的模型）
                    if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                        reasoning_content += delta.reasoning_content

                    # 拼接正常回复内容
                    if hasattr(delta, 'content') and delta.content:
                        content += delta.content

                # 返回内容（优先返回正常内容，如果为空则返回思维链内容）
                result = content.strip() if content.strip() else reasoning_content.strip()
                if result:
                    log(message=f"API 流式返回成功（共 {chunk_count} 个块）：{result[:100]}...")
                    return result
                else:
                    log(level="WARN", message=f"流式响应为空（收到 {chunk_count} 个块），尝试备用方案")
                    return self._try_responses_api(message, model, stream, prompt, history, image_path, image_url)
            else:
                # 非流式模式：直接取 choices[0] 的消息内容
                if response.choices and len(response.choices) > 0:
                    message_obj = response.choices[0].message

                    # 检查是否有 content 属性
                    if hasattr(message_obj, 'content') and message_obj.content:
                        output = message_obj.content
                        log(message=f"API 非流式返回成功：{output[:100]}...")
                        return output
                    else:
                        log(level="WARN", message="非流式响应内容为空，尝试备用方案")
                        return self._try_responses_api(message, model, stream, prompt, history, image_path, image_url)
                else:
                    log(level="WARN", message="响应中没有 choices，尝试备用方案")
                    return self._try_responses_api(message, model, stream, prompt, history, image_path, image_url)
        except Exception as e:
            error_type = type(e).__name__
            log(level="WARN", message=f"解析 API 响应出错 [{error_type}]: {str(e)}，尝试备用方案")
            return self._try_responses_api(message, model, stream, prompt, history, image_path, image_url)

    def _try_responses_api(self, message, model, stream, prompt, history=None, image_path="", image_url=""):
        """
        备用方案：使用 Responses API 调用。
        当 Chat Completions API 调用失败时自动降级到此方案。
        注意：备用方案暂不支持流式输出，统一使用非流式模式。
        """
        try:
            if stream:
                log(level="WARN", message="备用方案不支持流式输出，将使用非流式模式")

            log(message=f"备用方案：使用 Responses API, model={model}")

            # 与主路径保持一致的输入结构：system 提示词 + 历史消息 + 用户消息
            input_items = []
            if prompt and prompt.strip():
                input_items.append({"role": "system", "content": prompt})
            input_items.extend(self._build_history_messages(history))
            if image_path or image_url:
                input_items.append({
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": message},
                        self._build_responses_image_block(image_path, image_url),
                    ],
                })
            else:
                input_items.append({"role": "user", "content": message})

            response = self.client.responses.create(
                model=model,
                input=input_items,
            )

            # 遍历 output 提取 message 条目中的文本（兼容 reasoning 等其它条目类型）
            output_text = ""
            for item in (response.output or []):
                if getattr(item, 'type', '') != 'message':
                    continue
                item_content = getattr(item, 'content', None)
                if isinstance(item_content, str):
                    if item_content.strip():
                        output_text = item_content
                        break
                    continue
                if not item_content:
                    continue
                parts = []
                for part in item_content:
                    if getattr(part, 'type', '') == 'output_text' and getattr(part, 'text', ''):
                        parts.append(part.text)
                output_text = "".join(parts)
                if output_text.strip():
                    break

            if output_text.strip():
                log(message=f"备用方案返回成功：{output_text[:100]}...")
                return output_text

            log(level="WARN", message="备用方案响应内容为空")
            return "API返回错误，请稍后再试"

        except Exception as e:
            log(level="ERROR", message=f"备用方案也失败 [{type(e).__name__}]: {str(e)}")
            return "API返回错误，请稍后再试"


# ----------------------------------------------------------
# DifyAPI：Dify 对话工作流（HTTP 接口）
# ----------------------------------------------------------


class DifyAPI:
    """
    Dify 平台 API 封装类
    通过 HTTP 请求调用 Dify 对话工作流接口。
    """

    def __init__(self, config):
        """准备 Dify 请求参数；model1 在 Dify 中填工作流 / 应用的 ID。"""
        self.config = config
        self.DS_NOW_MOD = config.model1             # 当前模型标识（Dify 中通常为工作流 ID）
        self.api_key = "Bearer " + config.api_key   # Dify 使用 Bearer Token 鉴权
        self.base_url = config.base_url

    def chat(self, message, model=None, stream=True, prompt=None, history=None):
        """
        调用 Dify 对话接口，返回 AI 回复文本。

        :param message: 用户输入内容
        :param history: 历史消息列表（Dify 不支持多轮消息，拼接为上下文前缀）
        :return:        AI 回复字符串
        """
        query = message
        if history:
            ctx = "\n".join([
                f"[{h.get('time', '')}] {'助手' if h.get('attr') == 'self' else h.get('sender', '用户')}: {h.get('content', '')}"
                for h in history
            ])
            query = f"[历史对话]\n{ctx}\n[当前消息]\n{message}"
        # 以阻塞模式请求 Dify 接口
        response = self.run_dify_conversation(
            query=query,
            response_mode="blocking",
        )

        if "event" in response and response["event"] == "message":
            result = self.handle_blocking_response(response)
            log(message=f"🤖 AI回复: {result['answer']}")
            log(message=f"会话ID: {result['conversation_id']}")
            return result['answer']
        else:
            log(level="ERROR", message=f"❌ 错误: {response.get('error', 'Unknown error')}")
            return "API返回错误，请稍后再试"

    def handle_blocking_response(self, response_data):
        """
        解析阻塞模式（blocking）的 Dify API 响应。

        :param response_data: Dify 返回的 JSON 数据字典
        :return:              包含 success、answer 等字段的结果字典
        """
        if response_data.get("event") == "message":
            return {
                "success": True,
                "conversation_id":   response_data.get("conversation_id"),
                "answer":            response_data.get("answer", ""),
                "message_id":        response_data.get("message_id"),
                "metadata":          response_data.get("metadata", {}),
                "usage":             response_data.get("usage", {}),
                "retriever_resources": response_data.get("retriever_resources", []),
            }
        else:
            return {
                "success": False,
                "error":        f"Unexpected event type: {response_data.get('event')}",
                "raw_response": response_data,
            }

    def run_dify_conversation(
        self,
        query=str,
        inputs={},
        conversation_id=None,
        files=[],
        auto_generate_name=True,
        response_mode="blocking",
    ):
        """
        执行 Dify 对话工作流 API 请求。
        官方文档：https://docs.dify.ai/api/chat-messages

        :param query:               用户输入/提问内容
        :param inputs:              App 中定义的变量值
        :param conversation_id:     会话 ID（多轮对话时传入）
        :param files:               文件列表（支持 Vision 能力时使用）
        :param auto_generate_name:  是否自动生成对话标题
        :param response_mode:       响应模式（blocking / streaming）
        :return:                    API 响应数据字典
        """
        url = self.base_url
        headers = {
            "Authorization": self.api_key,
            "Content-Type":  "application/json",
        }
        payload = {
            "inputs":             inputs,
            "query":              query,
            "response_mode":      response_mode,
            "user":               "api-user",        # 用户标识符
            "conversation_id":    conversation_id,
            "auto_generate_name": auto_generate_name,
        }

        # 仅在提供文件时才将 files 字段加入请求体
        if files:
            payload["files"] = files

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=180)
            response.raise_for_status()  # 非 2xx 状态码时抛出异常
            if response_mode == "blocking":
                return response.json()
            else:
                # 流式响应暂未实现，返回原始文本
                return {"raw_stream": response.text}
        except requests.exceptions.RequestException as e:
            # 构造详细的错误信息字典
            error_info = {
                "error_type": "request_error",
                "message":    _api_error_summary(e, payload),
            }
            if e.response is not None:
                try:
                    error_data = e.response.json()
                    error_info.update({
                        "status_code": e.response.status_code,
                        "error_code":  error_data.get("code", "unknown"),
                        "api_message": error_data.get("message", "No error details"),
                    })
                except Exception:
                    error_info["response_text"] = _shorten_log_text(e.response.text)
            return {"success": False, "error": error_info}


# ----------------------------------------------------------
# CozeAPI：扣子平台（官方 cozepy SDK 流式对话）
# ----------------------------------------------------------


class CozeAPI:
    """
    扣子（Coze）平台 API 封装类
    使用扣子官方 Python SDK（cozepy）进行流式对话。
    """

    def __init__(self, config):
        """准备扣子请求参数；model1 填机器人 ID（从 Coze 页面 URL 末尾复制）。"""
        self.config = config
        self.DS_NOW_MOD = config.model1             # 当前模型标识
        self.bot_id     = config.model1             # Coze 机器人 ID（从页面 URL 末尾复制）
        self.user_id    = "SiverWxBot"              # 请求用的用户标识
        self.api_key    = config.api_key
        self.base_url   = COZE_CN_BASE_URL          # 使用扣子官方定义的国内 API 地址
        self.coze = Coze(
            auth=TokenAuth(token=self.api_key),
            base_url=self.base_url,
        )

    def chat(self, message, model=None, stream=True, prompt=None, history=None):
        """
        调用扣子流式接口获取 AI 回复，并拼接完整的回答文本。

        :param message: 用户输入内容
        :param history: 历史消息列表
        :return:        AI 回复字符串
        """
        additional_messages = []
        if history:
            for h in history:
                t = h.get('time', '')
                raw = h.get('content', '')
                sender = h.get('sender', '')
                if h.get('attr') == 'self':
                    content = f"[{t}] {raw}" if t else raw
                    try:
                        additional_messages.append(CozeMessage.build_assistant_answer(content))
                    except Exception:
                        additional_messages.append(CozeMessage.build_user_question_text(f"[助手]: {content}"))
                else:
                    if sender:
                        content = f"[{t}] {sender}: {raw}" if t else f"{sender}: {raw}"
                    else:
                        content = f"[{t}] {raw}" if t else raw
                    additional_messages.append(CozeMessage.build_user_question_text(content))
        additional_messages.append(CozeMessage.build_user_question_text(message))
        chunk_message = ""
        try:
            for event in self.coze.chat.stream(
                bot_id=self.bot_id,
                user_id=self.user_id + str(time.time()),  # 用时间戳保证 user_id 唯一
                additional_messages=additional_messages,
            ):
                # 逐块拼接流式回答内容
                if event.event == ChatEventType.CONVERSATION_MESSAGE_DELTA:
                    chunk_message += event.message.content

                # 对话完成时记录 token 消耗
                if event.event == ChatEventType.CONVERSATION_CHAT_COMPLETED:
                    log(f"token消耗:{event.chat.usage.token_count}")

            log(f"扣子回复：{chunk_message}")
            return chunk_message
        except Exception as e:
            log(level="ERROR", message=f"❌ 调用Coze接口错误: {e}")
            return "API返回错误，请稍后再试"


# ----------------------------------------------------------
# DusAPI：按模型名自动切换协议（claude → Anthropic / gpt → OpenAI）
# ----------------------------------------------------------


class DusAPI:
    """
    DusAPI 兼容接口封装类
    根据模型名称自动选择协议：
    - 包含 'claude' → Anthropic 格式（x-api-key + /v1/messages）
    - 包含 'gpt'    → GPT/OpenAI 格式（Bearer + /v1/chat/completions）
    """

    def __init__(self, config):
        """准备 DusAPI 请求参数；具体走哪套协议在 chat() 里按模型名判定。"""
        self.config = config
        self.DS_NOW_MOD = config.model1
        self.api_key = config.api_key
        self.base_url = config.base_url.rstrip('/')

    @staticmethod
    def build_image_block(image_path: str = "", image_url: str = "") -> dict:
        """根据本地路径或 URL 构建 Anthropic image content block"""
        if image_path:
            mime_type, _ = mimetypes.guess_type(image_path)
            if mime_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                mime_type = "image/jpeg"
            with open(image_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("utf-8")
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": image_data,
                },
            }
        elif image_url:
            return {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": image_url,
                },
            }
        else:
            raise ValueError("image_path 和 image_url 不能同时为空")

    @staticmethod
    def _build_gpt_image_block(image_path: str = "", image_url: str = "") -> dict:
        """根据本地路径或 URL 构建 GPT/Responses API image input block"""
        if image_path:
            mime_type, _ = mimetypes.guess_type(image_path)
            if mime_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                mime_type = "image/jpeg"
            with open(image_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("utf-8")
            return {
                "type": "input_image",
                "image_url": f"data:{mime_type};base64,{image_data}"
            }
        elif image_url:
            return {
                "type": "input_image",
                "image_url": image_url
            }
        else:
            raise ValueError("image_path 和 image_url 不能同时为空")

    @staticmethod
    def _extract_gpt_text(response_data: dict):
        """提取 GPT/Responses API 非流式返回文本"""
        try:
            output_text = response_data.get("output_text")
            if isinstance(output_text, str) and output_text:
                return output_text

            output = response_data.get("output", [])
            result_parts = []

            if isinstance(output, list):
                for item in output:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") != "message":
                        continue

                    content = item.get("content", [])
                    if not isinstance(content, list):
                        continue

                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") in ("output_text", "text"):
                            text = block.get("text")
                            if text:
                                result_parts.append(text)

            if result_parts:
                return "".join(result_parts)

            return None
        except Exception:
            return None

    def _stream_claude_text(self, api_endpoint, headers, payload) -> str:
        """Anthropic 流式接收并拼接为完整文本"""
        response = requests.post(
            api_endpoint,
            headers=headers,
            json=payload,
            timeout=180,
            stream=True
        )
        response.raise_for_status()
        response.encoding = 'utf-8'

        result_parts = []

        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            if not raw_line.startswith("data:"):
                continue

            data_str = raw_line[5:].strip()
            if not data_str:
                continue

            try:
                data = json.loads(data_str)
            except Exception:
                continue

            if data.get("type") == "content_block_delta":
                delta = data.get("delta", {})
                text = delta.get("text")
                if text:
                    result_parts.append(text)
            elif data.get("type") == "message_stop":
                break

        return "".join(result_parts)

    def _stream_gpt_text(self, api_endpoint, headers, payload) -> str:
        """GPT/Responses API 流式接收并拼接为完整文本"""
        response = requests.post(
            api_endpoint,
            headers=headers,
            json=payload,
            timeout=180,
            stream=True
        )
        response.encoding = 'utf-8'

        if response.status_code >= 400:
            error = Exception("GPT接口请求失败")
            error.response = response
            raise error

        result_parts = []

        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            if not raw_line.startswith("data:"):
                continue

            data_str = raw_line[5:].strip()
            if not data_str:
                continue
            if data_str == "[DONE]":
                break

            try:
                data = json.loads(data_str)
            except Exception:
                continue

            event_type = data.get("type")

            # Responses API 常见文本增量事件
            if event_type in (
                "response.output_text.delta",
                "response.refusal.delta",
            ):
                delta = data.get("delta")
                if isinstance(delta, str) and delta:
                    result_parts.append(delta)

            # 某些兼容层可能直接给 output_text
            elif event_type == "response.completed":
                try:
                    output_text = data.get("response", {}).get("output_text")
                    if isinstance(output_text, str) and output_text:
                        if not result_parts:
                            result_parts.append(output_text)
                except Exception:
                    pass

        return "".join(result_parts)

    def chat(self, message, model=None, stream=True, prompt=None, history=None,
             image_path: str = "", image_url: str = ""):
        """
        发送消息并返回回复文本。
        :param image_path: 本地图片路径，优先于 image_url
        :param image_url:  图片 URL，image_path 为空时使用

        stream=False -> 普通非流式请求并返回完整字符串
        stream=True  -> 走流式请求，但在 chat 内部收集完整后返回完整字符串
        """
        if model is None:
            model = self.DS_NOW_MOD
        if prompt is None:
            prompt = self.config.prompt

        retry_delays = [2, 4, 8, 16, 32]
        max_retries = 5
        last_error = None

        # =========================
        # Claude / Anthropic 分支
        # =========================
        if 'claude' in model.lower():
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
                'user-agent': f'siver-wxbot-panel/{version}'
            }

            if image_path or image_url:
                user_content = [
                    self.build_image_block(image_path, image_url),
                    {"type": "text", "text": message},
                ]
            else:
                user_content = message

            messages = []
            if history:
                for h in history:
                    role = "assistant" if h.get('attr') == 'self' else "user"
                    t = h.get('time', '')
                    raw = h.get('content', '')
                    sender = h.get('sender', '')
                    if role == 'user' and sender:
                        content = f"[{t}] {sender}: {raw}" if t else f"{sender}: {raw}"
                    else:
                        content = f"[{t}] {raw}" if t else raw
                    messages.append({"role": role, "content": content})
            messages.append({"role": "user", "content": user_content})

            payload = {
                "model": model,
                "max_tokens": 65535,
                "system": prompt,
                "messages": messages,
            }

            api_endpoint = f"{self.base_url}/v1/messages"

            if stream:
                payload["stream"] = True

                for attempt in range(max_retries + 1):
                    try:
                        result = self._stream_claude_text(api_endpoint, headers, payload)
                        if result:
                            if attempt > 0:
                                log(message=f"DusAPI Claude 流式第 {attempt} 次重试成功：{result[:100]}...")
                            else:
                                log(message=f"DusAPI Claude 流式返回成功：{result[:100]}...")
                            return result
                        else:
                            raise ValueError("DusAPI Claude 流式响应中未找到文本内容")

                    except Exception as e:
                        last_error = e
                        if attempt < max_retries:
                            delay = retry_delays[attempt]
                            err = _api_error_summary(e, payload)
                            log(level="WARNING", message=f"DusAPI Claude 流式第 {attempt + 1} 次失败（{err}），{delay}s 后重试...")
                            time.sleep(delay)
                        else:
                            log(level="ERROR", message=f"DusAPI Claude 流式已重试 {max_retries} 次，最终失败: {_api_error_summary(last_error, payload)}")

                return "API返回错误，请稍后再试"

            for attempt in range(max_retries + 1):
                try:
                    response = requests.post(api_endpoint, headers=headers, json=payload, timeout=180)
                    response.raise_for_status()
                    response.encoding = 'utf-8'
                    response_data = response.json()

                    result = response_data['content'][0]['text']

                    if attempt > 0:
                        log(message=f"DusAPI Claude 第 {attempt} 次重试成功：{result[:100]}...")
                    else:
                        log(message=f"DusAPI Claude 返回成功：{result[:100]}...")
                    return result

                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        delay = retry_delays[attempt]
                        err = _api_error_summary(e, payload)
                        log(level="WARNING", message=f"DusAPI Claude 第 {attempt + 1} 次失败（{err}），{delay}s 后重试...")
                        time.sleep(delay)
                    else:
                        log(level="ERROR", message=f"DusAPI Claude 已重试 {max_retries} 次，最终失败: {_api_error_summary(last_error, payload)}")

            return "API返回错误，请稍后再试"

        # =========================
        # GPT / OpenAI 分支
        # =========================
        elif 'gpt' in model.lower():
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
                'user-agent': f'siver-wxbot-panel/{version}'
            }

            input_items = []

            if prompt:
                input_items.append({
                    "role": "system",
                    "content": prompt
                })

            if history:
                for h in history:
                    role = "assistant" if h.get('attr') == 'self' else "user"
                    t = h.get('time', '')
                    raw = h.get('content', '')
                    sender = h.get('sender', '')
                    if role == 'user' and sender:
                        content = f"[{t}] {sender}: {raw}" if t else f"{sender}: {raw}"
                    else:
                        content = f"[{t}] {raw}" if t else raw
                    input_items.append({
                        "role": role,
                        "content": content
                    })

            if image_path or image_url:
                user_content = [
                    {"type": "input_text", "text": message},
                    self._build_gpt_image_block(image_path, image_url),
                ]
            else:
                user_content = message

            input_items.append({
                "role": "user",
                "content": user_content
            })

            payload = {
                "model": model,
                "input": input_items,
                "max_output_tokens": 65535,
            }

            api_endpoint = f"{self.base_url}/v1/responses"

            if stream:
                payload["stream"] = True

                for attempt in range(max_retries + 1):
                    try:
                        result = self._stream_gpt_text(api_endpoint, headers, payload)
                        if result:
                            if attempt > 0:
                                log(message=f"DusAPI GPT 流式第 {attempt} 次重试成功：{result[:100]}...")
                            else:
                                log(message=f"DusAPI GPT 流式返回成功：{result[:100]}...")
                            return result
                        else:
                            raise ValueError("DusAPI GPT 流式响应中未找到文本内容")

                    except Exception as e:
                        last_error = e
                        if attempt < max_retries:
                            delay = retry_delays[attempt]
                            err = _api_error_summary(e, payload)
                            log(level="WARNING", message=f"DusAPI GPT 流式第 {attempt + 1} 次失败（{err}），{delay}s 后重试...")
                            time.sleep(delay)
                        else:
                            log(level="ERROR", message=f"DusAPI GPT 流式已重试 {max_retries} 次，最终失败: {_api_error_summary(last_error, payload)}")

                return "API返回错误，请稍后再试"

            for attempt in range(max_retries + 1):
                try:
                    response = requests.post(api_endpoint, headers=headers, json=payload, timeout=180)
                    response.raise_for_status()
                    response.encoding = 'utf-8'
                    response_data = response.json()

                    result = self._extract_gpt_text(response_data)
                    if result is None:
                        raise ValueError(f"DusAPI GPT 响应中未找到文本内容：{response_data}")

                    if attempt > 0:
                        log(message=f"DusAPI GPT 第 {attempt} 次重试成功：{result[:100]}...")
                    else:
                        log(message=f"DusAPI GPT 返回成功：{result[:100]}...")
                    return result

                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        delay = retry_delays[attempt]
                        err = _api_error_summary(e, payload)
                        log(level="WARNING", message=f"DusAPI GPT 第 {attempt + 1} 次失败（{err}），{delay}s 后重试...")
                        time.sleep(delay)
                    else:
                        log(level="ERROR", message=f"DusAPI GPT 已重试 {max_retries} 次，最终失败: {_api_error_summary(last_error, payload)}")

            return "API返回错误，请稍后再试"

        else:
            log(level="WARNING", message=f"DusAPI 未识别的模型名称：{model}，无法路由到对应协议")
            return "API返回错误，请稍后再试"


# ============================================================
# 微信机器人主类
# ============================================================


class WXBot:
    """
    微信机器人主类
    整合配置管理、AI 接口、微信监听、消息处理、命令分发等核心功能。
    """

    def __init__(self, stop_event=None):
        """装配机器人：加载配置、初始化默认 AI 客户端、准备运行期统计字段。

        :param stop_event: 外部（面板的 BotLifecycle）持有的停止信号。
            面板停止机器人时先置这个 Event、再调 stop_wxbot()；直接运行本文件
            （python wxbot_core.py）时不传，自动新建一份，行为不变。

        ⚠ 本构造会调用 WXBotConfig() → update_global_config()，后者抛异常时本构造
          也会失败；面板侧由 bot_lifecycle 的线程体统一捕获并记录，不再静默死亡。
        """
        self.ver      = version
        self.ver_log  = version_log
        # 停止信号：面板/定时/生命周期"请求停止"时置位。初始化期间也必须能收到信号，
        # 因此这里先建好，绝不等到主循环才开始关心停止。
        self._stop_event = stop_event if stop_event is not None else threading.Event()
        self.run_flag = True                    # 主循环运行标志
        # 保护 _listening_started：停止可能来自 Flask 请求线程，而初始化/收尾在机器人线程，
        # 两边会并发读写这个标志。
        self._wx_lock = threading.Lock()
        self._listening_started = False         # wxautox 监听器是否已启动（决定收尾要不要 StopListening）
        self.config   = WXBotConfig()           # 加载配置

        # 本实例专属的定时任务调度器
        #
        # ⚠ 绝不能用 schedule 的模块级全局调度器：它是进程级的，旧实例停止后
        #   任务仍留在全局注册表里（清理只在对应开关打开时才做），新实例的
        #   run_pending() 会照样执行这些任务，而它们绑定的是已经停掉的旧实例。
        #   每个机器人实例一个 Scheduler，停止时 clear() 自己的任务，互不影响。
        self.scheduler = schedule.Scheduler()

        # 根据配置中的 api_sdk 字段选择对应的 AI 接口
        self.api = self._init_api()
        self.api_cache = {}                     # 群组专属接口缓存 {api_index: api_instance}

        self.wx                  = None         # WeChat 客户端对象（延迟初始化）
        self._moments_like_next_time  = None    # 下次随机朋友圈点赞的触发时间（datetime 或 None）
        self._random_moments_state    = {}     # 随机定时朋友圈运行状态缓存 {task_id: state_dict}
        self._random_msg_state        = {}     # 随机定时消息运行状态缓存 {task_id: state_dict}
        self.memory_manager      = None         # 记忆管理器（init_wx_listeners 时创建）
        self.all_Mode_listen_list = []           # 全局模式下的动态监听列表，元素格式：[昵称, 最新消息时间戳]
        self.start_time          = datetime.now()
        self.callback_is_die     = False        # 回调函数是否发生致命错误的标志
        self.msgs_path           = './wx_msgs/' # 消息本地存储路径（当前未启用）

        # 运行统计数据（供状态面板采集）
        self.msg_received_count  = 0            # 已接收消息数
        self.msg_replied_count   = 0            # 已回复消息数
        self.last_msg_time       = None         # 最近一条消息的时间字符串
        self.last_msg_sender     = None         # 最近一条消息的发送者

        # 多条消息缓冲合并：key=(窗口名, 发送人) -> 缓冲项。
        # ⚠ 群聊必须按发送人分开，否则群里 A、B 同时说话会被拼成一条，AI 张冠李戴。
        # ⚠ flush 只在主循环线程里做（_check_merge_buffers），绝不新开线程碰 wxautox。
        self._merge_buffers = {}
        self._merge_lock    = threading.Lock()

        # 私聊回复轮数计数器
        _base = os.path.dirname(sys.executable) if hasattr(sys, '_MEIPASS') else os.path.abspath(".")
        self.reply_count_store = ReplyCountStore(os.path.join(_base, 'config', 'reply_count.json'))

    def _init_api(self):
        """根据配置中的 api_sdk 字段实例化对应的 AI 接口对象（默认接口）"""
        sdk = self.config.api_sdk
        if sdk == "Dify":
            log(message="使用Dify API")
            return DifyAPI(self.config)
        elif sdk in OPENAI_SDK_ALIASES:
            log(message="使用OpenAI API 格式兼容接口")
            return OpenAIAPI(self.config)
        elif sdk == "Coze":
            log(message="使用Coze API")
            return CozeAPI(self.config)
        elif sdk == "DusAPI":
            log(message="使用DusAPI")
            return DusAPI(self.config)
        else:
            log(level="WARNING", message="未配置 API SDK，已跳过 AI 客户端初始化，非 AI 功能仍可正常使用")
            return UnconfiguredAPI(self.config)

    def _init_api_by_index(self, idx):
        """
        根据指定接口索引实例化 AI 接口对象，用于群组专属接口。
        会创建一个只含接口相关字段的轻量代理配置对象，避免干扰主配置。
        """
        configs = self.config.api_configs
        if idx < 0 or idx >= len(configs):
            log(level="WARNING", message=f"群组接口索引 {idx} 超出范围，回退到默认接口")
            return self.api
        cfg = configs[idx]
        sdk = cfg.get('sdk', '')

        # 轻量代理配置：仅覆盖接口相关字段，其余不涉及
        class _ApiProxy:
            pass
        tmp = _ApiProxy()
        tmp.api_sdk  = sdk
        tmp.api_key  = cfg.get('key', '')
        tmp.base_url = cfg.get('url', '')
        tmp.model1   = cfg.get('model', '')
        tmp.prompt   = ''   # prompt 总是通过 chat() 调用时显式传入，此处置空

        log(message=f"初始化群组专属接口：索引{idx}  SDK:{sdk}  模型:{tmp.model1}")
        if sdk == "Dify":
            return DifyAPI(tmp)
        elif sdk in OPENAI_SDK_ALIASES:
            return OpenAIAPI(tmp)
        elif sdk == "Coze":
            return CozeAPI(tmp)
        elif sdk == "DusAPI":
            return DusAPI(tmp)
        else:
            log(level="WARNING", message=f"接口索引 {idx} 未配置 API SDK，已跳过 AI 客户端初始化")
            return UnconfiguredAPI(tmp)

    def _normalize_api_index(self, idx):
        """将接口索引规范化为有效索引；无效值回退到当前默认接口。"""
        configs = getattr(self.config, 'api_configs', [])
        if not isinstance(configs, list) or not configs:
            return 0
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            idx = -1
        if 0 <= idx < len(configs):
            return idx
        try:
            default_idx = int(getattr(self.config, 'api_index', 0))
        except (TypeError, ValueError):
            default_idx = 0
        return default_idx if 0 <= default_idx < len(configs) else 0

    def _get_api_instance_by_index(self, idx):
        """获取指定接口实例，默认接口复用 self.api，其余接口使用缓存。"""
        idx = self._normalize_api_index(idx)
        default_idx = self._normalize_api_index(getattr(self.config, 'api_index', 0))
        if idx == default_idx:
            return self.api
        if idx not in self.api_cache:
            self.api_cache[idx] = self._init_api_by_index(idx)
        return self.api_cache[idx]

    def _get_group_api_index(self, group_name):
        """获取群聊实际使用的接口下标；未配置专属接口时返回默认接口。"""
        raw = getattr(self.config, 'group_api_map', {}).get(group_name)
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            return self._normalize_api_index(getattr(self.config, 'api_index', 0))
        if idx < 0:
            return self._normalize_api_index(getattr(self.config, 'api_index', 0))
        return self._normalize_api_index(idx)

    def _get_chat_api_index(self, user_name):
        """获取私聊实际使用的接口下标；未配置专属接口时返回默认接口。"""
        if not getattr(self.config, 'AllListen_switch', False):
            raw = getattr(self.config, 'chat_api_map', {}).get(user_name)
            try:
                idx = int(raw)
            except (TypeError, ValueError):
                idx = -1
            if idx >= 0:
                return self._normalize_api_index(idx)
        return self._normalize_api_index(getattr(self.config, 'api_index', 0))

    def _call_api_with_fallback(self, api_index, message, api=None, **kwargs):
        """
        调用一次主接口，失败后最多调用一次其配置的备用接口。
        备用接口自身的 fallback 配置不会继续展开，避免形成循环。
        """
        configs = getattr(self.config, 'api_configs', [])
        if not isinstance(configs, list) or not configs:
            configs = []
        primary_index = self._normalize_api_index(api_index)
        attempts = [(primary_index, api)]

        if configs and primary_index < len(configs):
            primary_config = configs[primary_index]
            if isinstance(primary_config, dict):
                try:
                    fallback_index = int(primary_config.get('fallback_api_index', -1))
                except (TypeError, ValueError):
                    fallback_index = -1
                if (
                    0 <= fallback_index < len(configs)
                    and fallback_index != primary_index
                ):
                    attempts.append((fallback_index, None))

        for attempt_number, (index, current_api) in enumerate(attempts):
            try:
                if current_api is None:
                    current_api = self._get_api_instance_by_index(index)
                reply = current_api.chat(message, **kwargs)
                if reply and reply != API_ERROR_REPLY:
                    if attempt_number > 0:
                        log(message=f"备用接口 {index + 1} 调用成功")
                    return reply
                log(
                    level="WARNING",
                    message=f"接口 {index + 1} 返回失败标记，"
                            f"{'准备切换备用接口' if attempt_number == 0 and len(attempts) > 1 else '本次调用结束'}",
                )
            except Exception as exc:
                log(
                    level="WARNING",
                    message=f"接口 {index + 1} 调用异常：{_shorten_log_text(exc)}"
                            f"{'，准备切换备用接口' if attempt_number == 0 and len(attempts) > 1 else ''}",
                )

        return API_ERROR_REPLY

    def _get_group_api(self, group_name):
        """
        获取群聊对应的 AI 接口实例。
        - 若配置了 group_api_map 映射，则返回对应接口（惰性初始化并缓存）
        - 否则返回默认接口 self.api
        """
        raw = self.config.group_api_map.get(group_name)
        if raw is None:
            return self.api
        try:
            idx = int(raw)
        except (ValueError, TypeError):
            return self.api
        if idx < 0:
            return self.api
        if idx not in self.api_cache:
            self.api_cache[idx] = self._init_api_by_index(idx)
        return self.api_cache[idx]

    # ----------------------------------------------------------
    # 初始化与检测
    # ----------------------------------------------------------

    def wxautox_activate_check(self):
        """检查 wxautox 授权是否已激活"""
        return check_license()

    def check_wechat_window(self):
        """检测微信客户端是否在线（未被弹出登录）"""
        return self.wx.IsOnline()

    def is_err(self, id, err="无"):
        """
        记录错误信息并发送告警通知。

        本地记录（print + log）仍是同步的；告警（邮件 / Webhook）改为异步：
        只把内容放进有界队列后立即返回，由后台单线程串行发送 —— 本方法会在
        wxautox 回调线程与主循环里被调用，同步发网络请求会卡住它们。

        :param id:  错误标题（邮件主题 / Webhook 标题）
        :param err: 错误详情（可为异常对象或字符串）
        """
        print(traceback.format_exc())
        log(level="ERROR", message=f"出现错误：{err}")
        content = '错误信息：\n' + traceback.format_exc() + "\nerr信息：\n" + str(err)
        enqueue_alert(id, content)

    def key_pass(self, year, month, day, hour, minute, second):
        """
        打包保护锁：检测程序是否已过期。
        若当前时间超过指定时间，则阻塞程序不可继续使用。
        """
        target_time  = datetime(year, month, day, hour, minute, second)
        current_time = datetime.now()

        if current_time < target_time:
            remaining_time = target_time - current_time
            days = remaining_time.days
            hours, remainder = divmod(remaining_time.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            log(level="INFO", message=f"还剩 {days} 天 {hours} 小时 {minutes} 分钟 {seconds} 秒 到期。")
        else:
            # 已过期，永久阻塞
            while True:
                log(level="ERROR", message=f"程序以于 {target_time} 过期不可使用")
                time.sleep(60)

    # ----------------------------------------------------------
    # 微信监听器初始化
    # ----------------------------------------------------------

    def _listen_add_error(self, result):
        """从 wxautox 添加监听返回值中提取错误信息，兼容 bool/dict 两类返回。"""
        if isinstance(result, dict):
            return result.get('message', str(result))
        return str(result)

    def _subwindow_who(self, chat):
        """读取子窗口对象的 who 属性，读取失败时返回 None。"""
        try:
            return getattr(chat, 'who', None)
        except Exception:
            return None

    def _try_get_all_subwindow_names(self):
        """获取当前所有已监听子窗口名称集合，失败时返回 None。"""
        try:
            chats = self.wx.GetAllSubWindow()
        except Exception as e:
            log(level="ERROR", message=f"获取全部监听子窗口失败: {e}")
            return None
        if not chats:
            return set()
        return {who for who in (self._subwindow_who(chat) for chat in chats) if who}

    def _get_verified_subwindow(self, nickname):
        """通过 GetSubWindow 获取并校验单个监听子窗口。"""
        try:
            chat = self.wx.GetSubWindow(nickname=nickname)
        except Exception as e:
            log(level="WARNING", message=f"获取监听子窗口 {nickname} 失败: {e}")
            return None
        if chat and self._subwindow_who(chat) == nickname:
            return chat
        return None

    def _add_listen_chat_once(self, nickname, label):
        """执行一次 AddListenChat，并记录基础结果。"""
        result = self.wx.AddListenChat(nickname=nickname, callback=self.message_handle_callback)
        if result:
            log(message=f"添加{label} {nickname} 监听完成")
        else:
            log(level="ERROR", message=f"添加{label} {nickname} 监听失败, {self._listen_add_error(result)}")
        return result

    def _verify_initial_listeners(self, expected_chats, retry_count=3):
        """
        初始化监听完成后，逐个用 GetSubWindow 校验应监听对象。

        ⚠ 校验依据必须与"是否需要注册"的判定相互独立：原先两边都用
          GetAllSubWindow 的名称集合，于是"因已在列表中而跳过注册"的对象
          必然通过校验——循环论证，校验等于没做；而且 RemoveListenChat 后
          子窗口可能仍然存在，名称集合会把没注册成功的对象判成已监听。
          这里改用 GetSubWindow(nickname) 并比对 who，逐对象精确校验，
          是比名称集合更严格的独立依据。

        未通过校验的对象最多重试 retry_count 次，仍失败则跳过实际监听。
        """
        expected = []
        seen = set()
        for nickname in expected_chats:
            if nickname and nickname not in seen:
                expected.append(nickname)
                seen.add(nickname)
        if not expected:
            return

        missing = [nickname for nickname in expected if not self._get_verified_subwindow(nickname)]
        if not missing:
            log(message="初始化监听子窗口校验通过")
            return

        log(level="WARNING", message=f"初始化监听子窗口缺失，准备重试: {missing}")
        for attempt in range(1, retry_count + 1):
            for nickname in missing:
                time.sleep(0.5)
                self._add_listen_chat_once(nickname, "初始化重试")
            missing = [nickname for nickname in missing if not self._get_verified_subwindow(nickname)]
            if not missing:
                log(message=f"初始化监听子窗口重试第 {attempt} 次后校验通过")
                return
            log(level="WARNING", message=f"初始化监听子窗口第 {attempt} 次重试后仍缺失: {missing}")

        log(level="ERROR", message=f"以下对象初始化监听重试失败，已跳过实际监听: {missing}")

    def _add_and_verify_subwindow(self, nickname, retry_count=3):
        """
        添加单个监听并用 GetSubWindow 校验，返回校验成功的子窗口对象。
        初次添加失败或未返回子窗口时再重试 retry_count 次。
        """
        total_attempts = retry_count + 1
        for attempt in range(1, total_attempts + 1):
            if attempt == 1:
                log(message=f"{nickname} 不在动态监听列表，正在添加监听")
            else:
                log(level="WARNING", message=f"{nickname} 动态监听校验失败，正在进行第 {attempt - 1} 次重试")
                time.sleep(0.5)

            self._add_listen_chat_once(nickname, "动态监听")
            sub_chat = self._get_verified_subwindow(nickname)
            if sub_chat:
                return sub_chat

        log(level="ERROR", message=f"{nickname} 动态监听添加失败，重试 {retry_count} 次后仍未获取到子窗口，已跳过")
        return None

    def _remove_dynamic_listen_chat(self, chat):
        """从全局模式动态监听列表中移除指定会话。"""
        before_count = len(self.all_Mode_listen_list)
        self.all_Mode_listen_list = [
            listen_chat for listen_chat in self.all_Mode_listen_list
            if listen_chat[0] != chat
        ]
        if len(self.all_Mode_listen_list) != before_count:
            log(level="WARNING", message=f"{chat} 动态监听子窗口校验失败，已从动态监听列表移除")

    def _remove_listen_chat_verified(self, nickname):
        """移除监听后用 GetAllSubWindow 校验子窗口是否已消失。"""
        try:
            self.wx.RemoveListenChat(nickname)
        except Exception as e:
            log(level="ERROR", message=f"{nickname} 删除监听失败: {e}")
            return False

        time.sleep(0.2)
        listened_names = self._try_get_all_subwindow_names()
        if listened_names is None:
            log(level="ERROR", message=f"{nickname} 删除监听后无法校验，保留在动态监听列表")
            return False
        if nickname not in listened_names:
            log(message=f"{nickname} 删除监听校验通过")
            return True

        log(level="ERROR", message=f"{nickname} 删除监听校验失败，子窗口仍存在，保留在动态监听列表")
        return False

    def init_wx_listeners(self):
        """
        初始化微信客户端及各类监听：
        - 启动 WeChat 客户端
        - 绑定机器人 @ 标识
        - 添加管理员、白名单用户、群组的监听回调
        - 注册每日定时消息任务

        ⚠ 只能在主线程调用（当前唯一调用点是 main() 启动时）。
          绝不能在 wxautox 消息回调线程（message_handle_callback 及其下游）里调用：
          内部的 StopListening() 会 join 自己所在的监听线程池，抛
          RuntimeError: cannot join current thread；随后 callback_is_die 置位，
          主循环会停掉整个机器人。
          需要热重载配置时，请在回调里只置标志位，由主循环或独立线程来执行本方法。
        """
        result = None
        # 若尚未实例化微信客户端则进行初始化
        if not self.wx:
            log(message="本次未获取客户端，正在初始化微信客户端...")
            try:
                self.wx = WeChat(version='微信')
            except Exception:
                try:
                    log(level='WARNING', message="初始化出错，尝试国际版")
                    self.wx = WeChat(version='WeChat')
                except Exception:
                    raise   # 第二次也失败，抛出异常，由外层 try 接住
            # self.wx.Show()  # 首次强制弹出主窗口以获取焦点

        # 绑定 @ 标识（格式："@机器人昵称"）
        self.config.AtMe = "@" + self.wx.nickname
        log(message='绑定@：' + self.config.AtMe)

        # 初始化记忆管理器
        #
        # ⚠ 存储标识（目录名）带原始窗口名的 sha256：旧规则把窗口名里的 <>:"/\|?*
        #   直接删掉，导致 "A:B"/"A?B"/"AB" 共用一个目录、共用一个记忆文件，
        #   且会话锁按原始窗口名取 → 两个窗口各拿一把锁写同一个文件，等于没锁。
        #   现在锁按最终存储标识取，读写清空都走 MemoryManager 这一个入口。
        try:
            my_info = self.wx.GetMyInfo()
            wx_id   = my_info.get('id', f'{self.wx.nickname}')
        except Exception:
            wx_id = f'{self.wx.nickname}'
        _base       = os.path.dirname(sys.executable) if hasattr(sys, '_MEIPASS') else os.path.abspath(".")
        memory_base = os.path.join(_base, 'memory')
        self.memory_manager = get_memory_manager(wx_id, memory_base)
        log(message=f"记忆管理器已初始化，微信号: {wx_id}")
        self._report_legacy_memory_dirs()

        # 启动 wxautox 消息监听器
        log(message='启动wxautox监听器...')
        self.wx.StopListening()
        time.sleep(1)
        self.wx.StartListening()
        # 记下"监听已启动"：收尾时据此决定要不要 StopListening（见 shutdown）。
        # 停止请求可能在初始化期间就到了，那时 StopListening 由收尾统一补做。
        with self._wx_lock:
            self._listening_started = True

        expected_listeners = []

        # 添加管理员账号监听（管理员始终监听，不受白名单模式限制）
        time.sleep(0.5)
        self._add_listen_chat_once(self.config.cmd, "管理员")
        expected_listeners.append(self.config.cmd)

        # 白名单模式下逐一添加用户监听
        if not self.config.AllListen_switch:
            log(message="白名单模式开启")
            for user in self.config.listen_list:
                time.sleep(0.5)
                self._add_listen_chat_once(user, "用户")
                expected_listeners.append(user)

        # 若群机器人开关开启，则添加群聊监听
        if self.config.group_switch:
            for user in self.config.group:
                time.sleep(0.5)
                self._add_listen_chat_once(user, "群组")
                expected_listeners.append(user)

        # 注册自定义转发监听（跳过已在私聊/群组列表中的来源，避免重复注册）
        if self.config.custom_forward_switch:
            # group_switch=OFF 时群组未注册监听器，不能算作"已监听"，否则转发来源中的同名群会被漏掉
            _listened_groups = set(self.config.group) if self.config.group_switch else set()
            _already_listened = set(self.config.listen_list) | _listened_groups | {self.config.cmd}
            _fwd_sources = set()
            for _rule in self.config.custom_forward_list:
                if _rule.get('all_sources', False):
                    continue  # 全部来源：依赖已有的私聊/群组监听，无需额外注册
                for _src in _rule.get('sources', []):
                    if _src:
                        _fwd_sources.add(_src)
            for _source in _fwd_sources:
                if _source and _source not in _already_listened:
                    time.sleep(0.5)
                    self._add_listen_chat_once(_source, "自定义转发监听源")
                    expected_listeners.append(_source)

        self._verify_initial_listeners(expected_listeners)

        # 注册定时消息任务（新版：支持多种重复类型）
        if self.config.scheduled_msg_switch:
            log(message="定时消息注册...")
            try:
                self.scheduler.clear('scheduled_msg')  # 清除本实例旧的定时任务（按 tag 清理）
                for task in self.config.scheduled_msg_list:
                    if not task.get('enabled', True):
                        continue
                    time_str    = task.get('time', '08:00')
                    msgs        = task.get('msgs', [])
                    targets     = task.get('targets', [])
                    repeat_type = task.get('repeat_type', 'daily')
                    task_id     = task.get('id', '')
                    weekdays    = task.get('weekdays', [])
                    dates       = task.get('dates', [])

                    self.scheduler.every().day.at(time_str).do(
                        self.send_scheduled_msg, targets, msgs, repeat_type, weekdays, dates, task_id
                    ).tag('scheduled_msg')
                    log(message=f"注册定时消息：{repeat_type} {time_str} 给 {targets} 发消息")
                log(message="定时消息注册完成")
            except Exception as e:
                log(level="ERROR", message=f"定时消息注册失败：{e}")

        # 注册定时朋友圈任务
        if self.config.scheduled_moments_switch:
            log(message="定时朋友圈注册...")
            try:
                self.scheduler.clear('scheduled_moments')
                for task in self.config.scheduled_moments_list:
                    if not task.get('enabled', True):
                        continue
                    time_str    = task.get('time', '08:00')
                    text        = task.get('text', '')
                    images      = task.get('images', [])
                    privacy     = task.get('privacy', 'public')
                    tags        = task.get('tags', [])
                    repeat_type = task.get('repeat_type', 'daily')
                    task_id     = task.get('id', '')
                    weekdays    = task.get('weekdays', [])
                    dates       = task.get('dates', [])

                    self.scheduler.every().day.at(time_str).do(
                        self.send_scheduled_moments,
                        text, images, privacy, tags, repeat_type, weekdays, dates, task_id
                    ).tag('scheduled_moments')
                    log(message=f"注册定时朋友圈：{repeat_type} {time_str}")
                log(message="定时朋友圈注册完成")
            except Exception as e:
                log(level="ERROR", message=f"定时朋友圈注册失败：{e}")

        log(message="监听器初始化完成")

    # ----------------------------------------------------------
    # 一次性（once）定时任务收尾
    # ----------------------------------------------------------

    def _once_task_has_future_date(self, dates, now):
        """once 任务是否还有尚未到来的目标日期。

        用于区分「今天不是目标日期」的两种情况：
        - 还有未来日期 → 静默跳过、保留注册，等那天到点再执行；
        - 目标日期已全部过去（或 dates 为空 / 不是合法的 YYYY-MM-DD）
          → 任务已不可能再执行，注销并把 enabled 置 False。
        """
        today = now.date()
        for item in dates or []:
            if not isinstance(item, str):
                continue
            try:
                task_date = datetime.strptime(item.strip(), '%Y-%m-%d').date()
            except ValueError:
                continue
            if task_date > today:
                return True
        return False

    def _finish_once_task(self, list_name, task_id, label, reason):
        """一次性计划任务收尾：把 enabled 置 False 并落盘（列表名与配置键同名）。"""
        tasks = getattr(self.config, list_name, None)
        if tasks is None:
            tasks = []
        for task in tasks:
            if task.get('id') == task_id:
                task['enabled'] = False
                break
        self.config.config[list_name] = tasks
        self.config.save_config()
        log(message=f"一次性{label}任务 {task_id} {reason}，已自动禁用并注销")

    # ----------------------------------------------------------
    # 定时消息发送
    # ----------------------------------------------------------

    def send_scheduled_msg(self, targets, msgs, repeat_type, weekdays, dates, task_id):
        """
        定时触发的消息发送函数，根据 repeat_type 判断今天是否需要发送。

        :param targets:     接收消息的用户/群组昵称列表（支持多目标群发）
        :param msgs:        要发送的消息列表
        :param repeat_type: 重复类型 (once/daily/weekly/monthly/custom)
        :param weekdays:    每周几发送 (1=周一 ... 7=周日)
        :param dates:       自定义日期列表 (["2026-03-20", ...]) 或每月几号 ([1, 15, ...])
        :param task_id:     任务ID，用于 once 类型执行后自动禁用
        """
        now = datetime.now()
        should_send = False

        if repeat_type == 'daily':
            should_send = True
        elif repeat_type == 'weekly':
            # isoweekday(): 1=周一, 7=周日
            should_send = now.isoweekday() in weekdays
        elif repeat_type == 'monthly':
            # dates 存储的是每月几号，如 [1, 15]
            should_send = now.day in dates
        elif repeat_type == 'custom':
            # dates 存储的是具体日期字符串，如 ["2026-03-20"]
            today_str = now.strftime('%Y-%m-%d')
            should_send = today_str in dates
        elif repeat_type == 'once':
            today_str = now.strftime('%Y-%m-%d')
            should_send = today_str in dates
        else:
            should_send = True

        # once 任务今天不是目标日期：目标日期还没到就静默跳过、保留注册
        # （每天某时刻注册一次，绝不能因为"今天不该发"就注销，否则未来日期永远等不到）；
        # 只有目标日期已经全部过去才收尾注销。
        if not should_send:
            if repeat_type != 'once':
                return None
            if self._once_task_has_future_date(dates, now):
                return None
            self._finish_once_task('scheduled_msg_list', task_id, '定时消息', '的目标日期已过')
            return schedule.CancelJob

        log(message=f"定时消息时间到（{repeat_type}），目标：{targets}，正在发送...")
        for user in targets:
            for msg in msgs:
                log(message=f"正在向 {user} 发送定时消息：{msg}")
                try:
                    if self.is_media_path(msg):
                        result = self.wx.SendFiles(who=user, filepath=msg)
                        # SendFiles 成功也常常不返回任何值（None），这里显式当成功，
                        # 否则每次发文件都会误报失败、还会触发邮件/Webhook 告警
                        send_ok = ReplyCountStore.was_send_success(result, none_is_success=True)
                    else:
                        result = self.wx.SendMsg(msg=msg, who=user)
                        send_ok = bool(result)
                    self.config.human_delay()  # 模拟人工操作延迟（可在面板配置）
                    if not send_ok:
                        log(level="ERROR", message=f"定时消息发送失败：{ReplyCountStore.send_result_message(result)}")
                        self.is_err(
                            self.wx.nickname + f" wxbot定时消息发送失败！",
                            f"{user} 定时消息发送失败：{ReplyCountStore.send_result_message(result)}",
                        )
                except Exception as e:
                    log(level="ERROR", message=f"定时消息发送失败：{e}")
                    self.is_err(
                        self.wx.nickname + f" wxbot定时消息发送失败！",
                        f"{user} 定时消息发送失败：{e}",
                    )

        # once 类型执行后自动禁用该任务
        if repeat_type == 'once':
            self._finish_once_task('scheduled_msg_list', task_id, '定时消息', '已执行完毕')
            return schedule.CancelJob  # 取消该 schedule 任务

    # ----------------------------------------------------------
    # 定时朋友圈发送
    # ----------------------------------------------------------

    def send_scheduled_moments(self, text, images, privacy, tags, repeat_type, weekdays, dates, task_id):
        """
        定时触发的朋友圈发送函数，根据 repeat_type 判断今天是否需要发送。

        :param text:        朋友圈文字内容（可为空，但文字和图片至少有一个）
        :param images:      朋友圈图片路径列表（本地绝对路径，最多9张，可为空）
        :param privacy:     隐私设置（'public'=公开 / 'whitelist'=白名单 / 'blacklist'=黑名单）
        :param tags:        隐私标签列表（白名单/黑名单模式下生效）
        :param repeat_type: 重复类型 (once/daily/weekly/monthly/custom)
        :param weekdays:    每周几发送 (1=周一 ... 7=周日)
        :param dates:       自定义日期列表 (["2026-03-20", ...]) 或每月几号 ([1, 15, ...])
        :param task_id:     任务ID，用于 once 类型执行后自动禁用
        """
        now = datetime.now()
        should_send = False

        if repeat_type == 'daily':
            should_send = True
        elif repeat_type == 'weekly':
            should_send = now.isoweekday() in weekdays
        elif repeat_type == 'monthly':
            should_send = now.day in dates
        elif repeat_type == 'custom':
            today_str = now.strftime('%Y-%m-%d')
            should_send = today_str in dates
        elif repeat_type == 'once':
            today_str = now.strftime('%Y-%m-%d')
            should_send = today_str in dates
        else:
            should_send = True

        # 与定时消息同理：once 任务目标日期还没到就静默跳过、保留注册，只有日期已过才注销
        if not should_send:
            if repeat_type != 'once':
                return None
            if self._once_task_has_future_date(dates, now):
                return None
            self._finish_once_task('scheduled_moments_list', task_id, '定时朋友圈', '的目标日期已过')
            return schedule.CancelJob

        log(message=f"定时朋友圈时间到（{repeat_type}），正在发送...")

        try:
            # 构建隐私配置
            if privacy == 'whitelist':
                privacy_config = {'privacy': '白名单', 'tags': tags}
            elif privacy == 'blacklist':
                privacy_config = {'privacy': '黑名单', 'tags': tags}
            else:
                privacy_config = {}

            # 过滤有效图片路径（路径不为空）
            valid_images = [img for img in images if img and img.strip()]

            # 打开朋友圈
            log(message="正在打开朋友圈...")
            pyq = self.wx.Moments()
            if pyq is None:
                log(level="ERROR", message="打开朋友圈失败（返回None），请确认微信已开启朋友圈功能")
                self.is_err(
                    self.wx.nickname + " wxbot定时朋友圈发送失败！",
                    "打开朋友圈失败，请在手机端确认朋友圈功能已开启"
                )
                return None

            # 获取朋友圈对象 -> 随机延时 2~5 秒
            delay1 = random.uniform(2, 5)
            log(message=f"朋友圈已打开，等待 {delay1:.1f}s 后发布...")
            time.sleep(delay1)

            # 发布朋友圈
            pyq.Publish(text, valid_images if valid_images else None, privacy_config)
            log(message=f"朋友圈已发布，内容：{text[:30] + '...' if len(text) > 30 else text}，图片数：{len(valid_images)}")

            # 发送完成 -> 随机延时 2~5 秒
            delay2 = random.uniform(2, 5)
            log(message=f"等待 {delay2:.1f}s 后关闭朋友圈...")
            time.sleep(delay2)

            # 关闭朋友圈
            pyq.Close()
            log(message="朋友圈已关闭")

        except Exception as e:
            log(level="ERROR", message=f"定时朋友圈发送失败：{e}")
            self.is_err(
                self.wx.nickname + " wxbot定时朋友圈发送失败！",
                f"定时朋友圈发送失败：{e}",
            )

        # once 类型执行后自动禁用该任务
        if repeat_type == 'once':
            self._finish_once_task('scheduled_moments_list', task_id, '定时朋友圈', '已执行完毕')
            return schedule.CancelJob

    # ----------------------------------------------------------
    # 随机朋友圈点赞
    # ----------------------------------------------------------

    def _do_moments_like(self):
        """
        随机朋友圈点赞执行函数。
        流程：打开朋友圈 → 随机延时 1~5s → 获取内容列表 → 随机延时 1~5s
              → 对第一条点赞 → 随机延时 1~5s → 关闭朋友圈。
        每个动作之间均有随机延时以拟人化操作。
        """
        log(message="随机朋友圈点赞：开始执行...")
        try:
            pyq = self.wx.Moments()
            if pyq is None:
                log(level="ERROR", message="随机点赞：打开朋友圈失败（返回None），请在手机端确认朋友圈功能已开启")
                self.is_err(self.wx.nickname + " wxbot随机朋友圈点赞失败！", "打开朋友圈返回None")
                return

            time.sleep(random.uniform(1, 5))

            moments = pyq.GetMoments()
            if not moments:
                log(level="WARNING", message="随机点赞：获取朋友圈内容为空，跳过本次点赞")
                time.sleep(random.uniform(1, 5))
                pyq.Close()
                return

            time.sleep(random.uniform(1, 5))

            moment = moments[0]
            moment.Like()
            log(message="随机朋友圈点赞：点赞完成")

            time.sleep(random.uniform(1, 5))
            pyq.Close()
            log(message="随机朋友圈点赞：朋友圈已关闭")

        except Exception as e:
            log(level="ERROR", message=f"随机朋友圈点赞执行出错：{e}")
            self.is_err(self.wx.nickname + " wxbot随机朋友圈点赞失败！", e)
            try:
                pyq.Close()
            except Exception:
                pass

    def _plan_random_fire_for_today(self, state, task_id, now, time_start, time_end, action_text, log_prefix):
        h_s, m_s = map(int, time_start.split(':'))
        h_e, m_e = map(int, time_end.split(':'))
        if not (0 <= h_s <= 23 and 0 <= h_e <= 23 and 0 <= m_s <= 59 and 0 <= m_e <= 59):
            raise ValueError(f"无效时间窗口：{time_start} - {time_end}")

        start_dt = now.replace(hour=h_s, minute=m_s, second=0, microsecond=0)
        end_dt = now.replace(hour=h_e, minute=m_e, second=59, microsecond=0)
        if start_dt >= end_dt:
            day_end = now.replace(hour=23, minute=59, second=59, microsecond=0)
            end_dt = min(start_dt + timedelta(minutes=1) - timedelta(seconds=1), day_end)

        earliest_dt = start_dt if now < start_dt else now + timedelta(seconds=1)
        if earliest_dt > end_dt:
            state['next_fire'] = None
            state['skipped_date'] = now.date()
            log(message=f"{log_prefix} {task_id}：今天时间窗口 {time_start}-{time_end} 已过，跳过今日{action_text}，等待下一个发送日")
            return None

        random_seconds = random.randint(0, int((end_dt - earliest_dt).total_seconds()))
        fire_dt = (earliest_dt + timedelta(seconds=random_seconds)).replace(microsecond=0)
        state['next_fire'] = fire_dt
        state['skipped_date'] = None
        log(message=f"{log_prefix} {task_id}：今天计划于 {fire_dt.strftime('%H:%M:%S')} {action_text}")
        return fire_dt

    def _check_random_moments(self):
        """
        随机定时朋友圈调度检查。
        在 main() 主循环中每轮调用，按任务配置决定今天是否发布、何时发布。

        每周模式：每周初随机抽取 random_days_count 天（缓存一整周）。
        每月模式：每月初随机抽取 random_days_count 天（缓存一整月）。
        每日模式：每天必发。
        确定今天发布后，在 [time_start, time_end] 窗口内随机选一个时刻触发。
        """
        now   = datetime.now()
        today = now.date()

        for task in self.config.random_moments_list:
            if not task.get('enabled', True):
                continue
            task_id = task.get('id', '')
            if not task_id:
                continue

            # 初始化 / 取出该任务的运行时状态
            state = self._random_moments_state.setdefault(task_id, {
                'next_fire':    None,   # 今天计划触发的 datetime
                'last_fire_date': None, # 上次实际触发的 date
                'skipped_date': None,   # 今天随机时刻已过时记录跳过，避免启动后补发
                'plan_signature': None,
                'week_cache':   None,   # {'key': (year, week), 'days': [...]}
                'month_cache':  None,   # {'key': (year, month), 'days': [...]}
            })

            # --- 判断今天是否是发送日 ---
            repeat_type       = task.get('repeat_type', 'daily')
            random_days_count = max(1, int(task.get('random_days_count', 1)))
            time_start        = task.get('time_start', '00:00')
            time_end          = task.get('time_end',   '23:59')
            plan_signature    = (repeat_type, random_days_count, time_start, time_end)
            if state.get('plan_signature') != plan_signature:
                state['next_fire'] = None
                state['skipped_date'] = None
                state['week_cache'] = None
                state['month_cache'] = None
                state['plan_signature'] = plan_signature
            is_eligible       = False

            if repeat_type == 'daily':
                is_eligible = True

            elif repeat_type == 'weekly':
                iso = today.isocalendar()
                week_key = (iso[0], iso[1])
                if state['week_cache'] is None or state['week_cache']['key'] != week_key:
                    n        = min(random_days_count, 7)
                    selected = sorted(random.sample(range(1, 8), n))
                    state['week_cache'] = {'key': week_key, 'days': selected}
                    log(message=f"随机朋友圈 {task_id}：本周 {week_key} 随机发送日 {selected}")
                is_eligible = today.isoweekday() in state['week_cache']['days']

            elif repeat_type == 'monthly':
                month_key = (today.year, today.month)
                if state['month_cache'] is None or state['month_cache']['key'] != month_key:
                    days_in_month = calendar.monthrange(today.year, today.month)[1]
                    n        = min(random_days_count, days_in_month)
                    selected = sorted(random.sample(range(1, days_in_month + 1), n))
                    state['month_cache'] = {'key': month_key, 'days': selected}
                    log(message=f"随机朋友圈 {task_id}：本月 {month_key} 随机发送日 {selected}")
                is_eligible = today.day in state['month_cache']['days']

            if not is_eligible:
                # 今天不是发送日，若 next_fire 是今天的则清掉
                if state['next_fire'] is not None and state['next_fire'].date() == today:
                    state['next_fire'] = None
                continue

            # 今天已发送过，跳过
            if state['last_fire_date'] == today:
                continue

            # 今天随机到的发送时刻已经过了，不补发，等下一次符合周期的日期
            if state.get('skipped_date') == today:
                continue

            # --- 还没计算今天的触发时间，则随机生成一个 ---
            if state['next_fire'] is None:
                try:
                    if self._plan_random_fire_for_today(
                        state, task_id, now, time_start, time_end, "发布", "随机朋友圈"
                    ) is None:
                        continue
                except Exception as ex:
                    log(level="ERROR", message=f"随机朋友圈 {task_id} 时间解析失败：{ex}")
                    continue

            # --- 到时间了，执行发布 ---
            if now >= state['next_fire']:
                log(message=f"随机朋友圈 {task_id}：触发发布...")
                try:
                    self.send_scheduled_moments(
                        text        = task.get('text', ''),
                        images      = task.get('images', []),
                        privacy     = task.get('privacy', 'public'),
                        tags        = task.get('tags', []),
                        repeat_type = 'daily',   # 已判断过资格，传 daily 跳过内部日期二次校验
                        weekdays    = [],
                        dates       = [],
                        task_id     = '',        # 空 id 避免 once 自动禁用逻辑
                    )
                    state['last_fire_date'] = today
                except Exception as ex:
                    log(level="ERROR", message=f"随机朋友圈 {task_id} 发布失败：{ex}")
                finally:
                    state['next_fire'] = None

    def _check_random_msg(self):
        """
        随机定时消息调度检查。
        在 main() 主循环中每轮调用，按任务配置决定今天是否发送、何时发送。

        每周模式：每周初随机抽取 random_days_count 天（缓存一整周）。
        每月模式：每月初随机抽取 random_days_count 天（缓存一整月）。
        每日模式：每天必发。
        确定今天发送后，在 [time_start, time_end] 窗口内随机选一个时刻触发。
        """
        now   = datetime.now()
        today = now.date()

        for task in self.config.random_msg_list:
            if not task.get('enabled', True):
                continue
            task_id = task.get('id', '')
            if not task_id:
                continue

            state = self._random_msg_state.setdefault(task_id, {
                'next_fire':      None,
                'last_fire_date': None,
                'skipped_date':   None,
                'plan_signature': None,
                'week_cache':     None,
                'month_cache':    None,
            })

            repeat_type       = task.get('repeat_type', 'daily')
            random_days_count = max(1, int(task.get('random_days_count', 1)))
            time_start        = task.get('time_start', '00:00')
            time_end          = task.get('time_end',   '23:59')
            plan_signature    = (repeat_type, random_days_count, time_start, time_end)
            if state.get('plan_signature') != plan_signature:
                state['next_fire'] = None
                state['skipped_date'] = None
                state['week_cache'] = None
                state['month_cache'] = None
                state['plan_signature'] = plan_signature
            is_eligible       = False

            if repeat_type == 'daily':
                is_eligible = True

            elif repeat_type == 'weekly':
                iso = today.isocalendar()
                week_key = (iso[0], iso[1])
                if state['week_cache'] is None or state['week_cache']['key'] != week_key:
                    n        = min(random_days_count, 7)
                    selected = sorted(random.sample(range(1, 8), n))
                    state['week_cache'] = {'key': week_key, 'days': selected}
                    log(message=f"随机定时消息 {task_id}：本周 {week_key} 随机发送日 {selected}")
                is_eligible = today.isoweekday() in state['week_cache']['days']

            elif repeat_type == 'monthly':
                month_key = (today.year, today.month)
                if state['month_cache'] is None or state['month_cache']['key'] != month_key:
                    days_in_month = calendar.monthrange(today.year, today.month)[1]
                    n        = min(random_days_count, days_in_month)
                    selected = sorted(random.sample(range(1, days_in_month + 1), n))
                    state['month_cache'] = {'key': month_key, 'days': selected}
                    log(message=f"随机定时消息 {task_id}：本月 {month_key} 随机发送日 {selected}")
                is_eligible = today.day in state['month_cache']['days']

            if not is_eligible:
                if state['next_fire'] is not None and state['next_fire'].date() == today:
                    state['next_fire'] = None
                continue

            if state['last_fire_date'] == today:
                continue

            if state.get('skipped_date') == today:
                continue

            if state['next_fire'] is None:
                try:
                    if self._plan_random_fire_for_today(
                        state, task_id, now, time_start, time_end, "发送", "随机定时消息"
                    ) is None:
                        continue
                except Exception as ex:
                    log(level="ERROR", message=f"随机定时消息 {task_id} 时间解析失败：{ex}")
                    continue

            if now >= state['next_fire']:
                log(message=f"随机定时消息 {task_id}：触发发送...")
                try:
                    self.send_scheduled_msg(
                        targets     = task.get('targets', []),
                        msgs        = task.get('msgs', []),
                        repeat_type = 'daily',
                        weekdays    = [],
                        dates       = [],
                        task_id     = '',
                    )
                    state['last_fire_date'] = today
                except Exception as ex:
                    log(level="ERROR", message=f"随机定时消息 {task_id} 发送失败：{ex}")
                finally:
                    state['next_fire'] = None

    # ----------------------------------------------------------
    # 多条消息缓冲合并回复
    #
    # 收到消息先缓冲，窗口内没有新消息（或达到条数上限）再拼成一条、只调一次 AI。
    # ⚠ 缓冲在回调线程里做（只碰内存），flush 只在主循环线程里做：
    #   新开线程调 chat.SendMsg 会变成三个线程并发操作 UI，wxautox 的内部锁
    #   只能保证单次调用原子，挡不住"切窗口 → 发送"两步之间被插入；
    #   而且 pythoncom.CoInitialize() 只在机器人线程里调过。
    # ----------------------------------------------------------

    def _is_ai_reply_target(self, chat):
        """这条会话是否会走 AI 回复（在监听范围内、未开只监听、非管理员窗口）。

        process_message 里的 is_monitored / chat_listen_only / group_listen_only
        判定与合并缓冲共用这一份实现，避免两处各写一份、改一处漏一处。
        """
        who = chat.who
        if who == self.config.cmd:
            return False                    # 管理员窗口走命令分支，不参与 AI 回复
        if who in self.config.group:
            # 群聊：群机器人开关关闭时完全不处理；"只监听不回复"时跳过 AI
            return bool(self.config.group_switch) and not self.config.group_listen_only
        if self.config.AllListen_switch:
            in_scope = who not in self.config.listen_list   # 全局模式：listen_list 是黑名单
        else:
            in_scope = who in self.config.listen_list       # 白名单模式
        if not in_scope:
            return False
        return not self.config.chat_listen_only

    def _match_keyword_reply(self, chat, message):
        """命中关键词时返回要回复的内容，未命中返回 None。

        判定口径与 process_message / wx_send_ai 保持一致：私聊看
        chat_keyword_switch，群聊看 group_keyword_switch（含"仅被 @ 时触发"）。
        合并缓冲用它把"该立即回复"的消息排除在缓冲之外。
        """
        if chat.who in self.config.group:
            if not self.config.group_keyword_switch:
                return None
            if self.config.group_keyword_at_only and self.config.AtMe not in message.content:
                return None
        elif not self.config.chat_keyword_switch:
            return None
        for keyword in self.config.keyword_dict:
            if keyword in message.content:
                return self.config.keyword_dict[keyword]
        return None

    def _should_buffer_message(self, chat, msg):
        """这条消息是否进入合并缓冲（只缓冲"本来就会走 AI 回复"的消息）。"""
        if not self.config.merge_reply_switch:
            return False
        if msg.attr != 'friend':
            return False                    # 命令 / 系统消息走各自分支
        if msg.type not in ('text', 'voice', 'image'):
            return False
        if not self._is_ai_reply_target(chat):
            return False
        # 命中关键词要立即回复，延迟一个窗口体验很差
        if self._match_keyword_reply(chat, msg) is not None:
            return False
        # 群聊"仅被 @ 时才回复"：没 @ 的消息本来就不会走 AI，缓冲了也只会被丢掉
        if (chat.who in self.config.group and self.config.group_reply_at
                and self.config.AtMe not in msg.content):
            return False
        return True

    def _buffer_message(self, chat, msg):
        """把一条消息放进合并缓冲；到期或达到条数上限由主循环统一处理。"""
        key     = (chat.who, msg.sender)    # 群聊按发送人分开，A、B 不能混在一起
        now     = time.monotonic()
        window  = self.config.merge_reply_window
        content = str(msg.content)
        with self._merge_lock:
            entry = self._merge_buffers.get(key)
            if entry is None:
                entry = {
                    'chat':        chat,
                    'texts':       [],
                    'types':       [],
                    'image_paths': [],
                    'last_msg':    msg,
                    'last_sender': msg.sender,
                    'deadline':    now + window,
                    'count':       0,
                }
                self._merge_buffers[key] = entry
            entry['texts'].append(content)
            entry['types'].append(str(msg.type))
            if msg.type == 'image' and content:
                entry['image_paths'].append(content)
            entry['last_msg']    = msg        # 只用于 quote()，见 _MergedMessage
            entry['last_sender'] = msg.sender
            entry['deadline']    = now + window   # 窗口内有新消息 → 刷新计时
            entry['count']      += 1
            count = entry['count']
        log(message=(
            f"[合并回复] {chat.who} / {msg.sender} 第 {count} 条进入缓冲"
            f"（窗口 {window} 秒，满 {self.config.merge_reply_max_count} 条立即回复）"
        ))

    def _clear_merge_buffers(self):
        """清空所有缓冲，返回清掉的组数（停止机器人时用，不做延迟回复）。"""
        with self._merge_lock:
            count = len(self._merge_buffers)
            self._merge_buffers.clear()
        return count

    def _check_merge_buffers(self):
        """主循环每轮调用：把到期或达到条数上限的缓冲合并回复。

        ⚠ 必须在主循环线程里执行（原因见本节顶部注释）。
        """
        if not self._merge_buffers:
            return
        if not self.config.merge_reply_switch:
            # 运行中把开关关掉 → 丢弃缓冲，不做延迟回复
            dropped = self._clear_merge_buffers()
            if dropped:
                log(level="WARNING", message=f"[合并回复] 开关已关闭，丢弃 {dropped} 组未回复的缓冲")
            return
        now       = time.monotonic()
        max_count = self.config.merge_reply_max_count
        with self._merge_lock:
            ready = [k for k, e in self._merge_buffers.items()
                     if now >= e['deadline'] or e['count'] >= max_count]
            # 先摘出再 flush：flush 期间新到的消息会新建缓冲，不会被这里连带清掉
            pending = [(k, self._merge_buffers.pop(k)) for k in ready]
        for key, entry in pending:
            try:
                self._flush_merged(key, entry)
            except Exception as e:
                log(level="ERROR", message=f"[合并回复] 合并回复失败：{e}")

    def _flush_merged(self, key, entry):
        """把一组缓冲消息拼成一条：调一次 process_message，再逐条补写记忆。"""
        chat        = entry['chat']
        texts       = entry['texts']
        types       = entry['types']
        image_paths = entry['image_paths']
        image_path  = image_paths[-1] if image_paths else ''   # 接口只收一张，取最后一张
        merged = _MergedMessage(
            content      = "\n".join(texts),
            sender       = entry['last_sender'],
            msg_type     = 'image' if image_path else 'text',
            merged_image = image_path,
            last_msg     = entry['last_msg'],
        )
        log(message=(
            f"[合并回复] {chat.who} / {entry['last_sender']} 合并 {len(texts)} 条"
            f"（含 {len(image_paths)} 张图）后回复"
        ))
        result = self.process_message(chat, merged)
        # 逐条补写记忆：必须在 process_message 之后 —— 先写会让 AI 读历史时
        # 当前消息已经在里面，同一条消息进 AI 两次（全局模式踩过这个坑）。
        if self.config.memory_switch and self.memory_manager:
            for text, msg_type in zip(texts, types):
                try:
                    self.memory_manager.save_message(
                        chat_name  = chat.who,
                        sender     = entry['last_sender'],
                        content    = text,
                        msg_type   = msg_type,
                        msg_attr   = 'friend',
                        max_count  = self.config.memory_max_count,
                    )
                except Exception as e:
                    log(level="WARNING", message=f"写入记忆失败: {e}")
        if not result:
            self.is_err(
                self._nickname() + " wxbot合并回复发送失败！",
                f"{chat.who} 合并 {len(texts)} 条后回复失败："
                + ReplyCountStore.send_result_message(result),
            )

    # ----------------------------------------------------------
    # 消息回调与处理入口
    # ----------------------------------------------------------

    def message_handle_callback(self, msg, chat):
        """
        wxautox 监听器的消息回调函数。
        每当监听到新消息时由 wxautox 自动调用。

        :param msg:  消息对象（含 type、attr、sender、content 等属性）
        :param chat: 聊天窗口子对象（含 who 等属性）
        """
        try:
            # 记录原始消息日志
            message_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
            text = (
                message_time + " "
                + f'类型：{msg.type} 属性：{msg.attr} 窗口：{chat.who}'
                + f' 发送人：{msg.sender} - 消息：{msg.content}'
            )
            log(message=text)

            buffered = False   # 合并缓冲：本条不立即处理，也不在这里写记忆（flush 后统一逐条补写）

            if msg.attr == "friend":
                # 根据当前会话类型决定是否需要下载图片（识别开关关闭时跳过下载）
                # 纯自定义转发来源（不在群组、白名单、全局动态列表中、全局模式在黑名单）不下载图片
                _is_group = chat.who in self.config.group
                if _is_group:
                    _img_enabled = self.config.group_image_recognition_switch
                elif not self.config.AllListen_switch and chat.who in self.config.listen_list: # 白名单
                    _img_enabled = self.config.chat_image_recognition_switch
                elif (self.config.AllListen_switch and chat.who not in self.config.listen_list and chat.chat_type != 'group'): # 全局黑名单且排除自定义转发监听来源的群聊
                    _img_enabled = self.config.chat_image_recognition_switch
                else:
                    _img_enabled = False  # 纯自定义转发来源，跳过图片下载
                try:
                    if _img_enabled:
                        if msg.type == 'image':
                            _down_path = msg.download()
                            if _down_path:
                                msg.content = str(_down_path)
                            else:
                                log("ERROR", f"{_down_path}")
                                log("ERROR", "message_handle_callback下载图片出错")
                        elif msg.type == 'quote':
                            _down_path = msg.download_quote_image()
                            if _down_path:
                                msg.content = msg.content+"+引用的图片:"+str(_down_path)
                            else:
                                log("INFO", "引用内容不是图片或视频")
                        elif msg.type == 'voice':
                            try:
                                _voice_content = msg.to_text()
                                if _voice_content:
                                    msg.content = str(_voice_content)
                                else:
                                    log("WARNING", "消息自动语音转文字失败")
                            except Exception as e:
                                log("WARNING", "消息自动语音转文字失败")
                except Exception as e:
                    log(level="ERROR", message=f"message_handle_callback下载图片出错,请尝试将windows设置屏幕缩放设置为100%后再尝试: {e}")
                # 统计已接收消息数
                self.msg_received_count += 1
                self.last_msg_time   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.last_msg_sender = msg.sender

                # 好友/群友消息：在全局模式下更新该会话的最新消息时间戳
                if self.config.AllListen_switch:
                    for listen_chat in self.all_Mode_listen_list:
                        if listen_chat[0] == chat.who:
                            log(message=chat.who + " 对话最新消息时间已更新")
                            listen_chat[1] = time.time()
                            break
                if self._should_buffer_message(chat, msg):
                    # 合并回复：本条只入缓冲，等窗口内没有新消息（或满条数）再一起处理
                    self._buffer_message(chat, msg)
                    buffered = True
                else:
                    result = self.process_message(chat, msg)
                # 自定义规则转发处理：缓冲与否都必须立即执行，不能被缓冲延迟
                if self.config.custom_forward_switch:
                    try:
                        self._handle_custom_forward(chat, msg)
                    except Exception as _fwd_e:
                        log(level="ERROR", message=f"自定义转发处理出错: {_fwd_e}")
                if not buffered and not result:
                    self.is_err(
                        self.wx.nickname + f" wxbot处理监听新消息失败！",
                        text + '\n' + ReplyCountStore.send_result_message(result),
                    )

            elif msg.attr == "system":
                # 系统消息：触发群新人欢迎语逻辑（仅限已配置群组，纯转发来源群组跳过）
                if self.config.group_welcome and chat.who in self.config.group:
                    result = self.send_group_welcome_msg(chat, msg)
                    if not result:
                        self.is_err(
                            self.wx.nickname + f" wxbot发送群新人欢迎语失败！",
                            text + '\n' + ReplyCountStore.send_result_message(result),
                        )

            elif msg.attr == "self":
                # 自己账号同步过来的消息（如从手机向文件传输助手发送指令）
                # 仅当当前窗口与管理员配置匹配时才作为指令处理
                if chat.who == self.config.cmd:
                    self.msg_received_count += 1
                    self.last_msg_time   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.last_msg_sender = msg.sender
                    result = self.process_command(chat, msg)
                    if not result:
                        self.is_err(
                            self.wx.nickname + f" wxbot处理管理员指令失败！",
                            text + '\n' + ReplyCountStore.send_result_message(result),
                        )

            # 写入对话记忆（合并缓冲的消息由 _flush_merged 在处理之后逐条补写）
            if not buffered and self.config.memory_switch and self.memory_manager:
                try:
                    self.memory_manager.save_message(
                        chat_name=chat.who,
                        sender=msg.sender,
                        content=msg.content,
                        msg_type=msg.type,
                        msg_attr=msg.attr,
                        max_count=self.config.memory_max_count,
                        message_time=message_time,
                    )
                except Exception as e:
                    log(level="WARNING", message=f"写入记忆失败: {e}")
        except Exception as e:
            # 回调函数出现未捕获异常时标记 callback_is_die，由主循环检测并处理
            self.callback_is_die = True
            self.is_err(self.wx.nickname + " wxbot回调函数处理出错！处理监听失败！！", e)

    # ----------------------------------------------------------
    # 旧记忆目录的迁移提示
    # ----------------------------------------------------------

    def _report_legacy_memory_dirs(self):
        """打印一次旧记忆目录的处理情况（迁移/隔离），便于用户核对数据去向。

        迁移本身是在第一次访问某个窗口时按需做的（见 memory_store.MemoryManager），
        这里只做只读扫描 + 日志，不移动任何目录：
        - 归属明确的目录会被迁到带哈希的新目录，原目录留在 memory/_quarantine/ 下；
        - 归属不明的目录只隔离、不迁移，宁可让用户手动处理，也不让 AI 读到
          混在一起的历史。
        """
        try:
            items = self.memory_manager.migration.scan()
        except Exception as e:
            log(level="WARNING", message=f"扫描旧记忆目录失败: {e}")
            return
        if not items:
            return
        migrate_items = [i for i in items if i['action'] == 'migrate']
        quarantine_items = [i for i in items if i['action'] == 'quarantine']
        log(level="WARNING", message=(
            f"发现旧格式记忆目录：可迁移 {len(migrate_items)} 个、"
            f"归属不明需隔离 {len(quarantine_items)} 个（首次访问该窗口时自动处理）"
        ))
        for item in migrate_items:
            log(level="INFO", message=f"  迁移：{item['wx_id']}/{item['legacy_name']}")
        for item in quarantine_items:
            log(level="WARNING", message=(
                f"  隔离：{item['wx_id']}/{item['legacy_name']} —— {item.get('reason', '')}"
            ))
        log(message=(
            f"隔离区：{self.memory_manager.migration.quarantine_root}"
            f"（迁移台账：{self.memory_manager.migration.ledger_path}，"
            "可用 tools/rollback_memory_migration.py 回滚）"
        ))

    # ----------------------------------------------------------
    # 消息分发与处理
    # ----------------------------------------------------------

    def process_message(self, chat, message):
        """
        处理单条消息的核心分发逻辑：
        1. 黑/白名单过滤
        2. 群聊消息（含 @ 检测和关键词回复）
        3. 管理员命令解析
        4. 普通好友 AI 回复

        :param chat:    聊天窗口子对象
        :param message: 消息对象
        :return:        发送结果
        """
        log(message=f"处理 {chat.who} 窗口 {message.sender} 消息：{message.content}")
        result = True  # 默认返回成功（WxResponse 类型）

        # --- 黑/白名单过滤 ---
        # 全局模式（黑名单）：listen_list 中的用户跳过；
        # 白名单模式：仅处理 listen_list 中的用户；
        # 群聊：group_switch 开启时处理；管理员始终处理。
        is_monitored = (
            (self.config.AllListen_switch and chat.who not in self.config.listen_list)
            or (not self.config.AllListen_switch and chat.who in self.config.listen_list)
            or (chat.who in self.config.group and self.config.group_switch)
            or (chat.who == self.config.cmd)
        )
        if not is_monitored:
            return True  # 不在监听范围，跳过处理（返回 True 表示正常）

        # --- 群聊消息处理 ---
        if chat.who in self.config.group and not self.config.group_switch:
            return True  # 群机器人开关关闭，跳过 AI 处理（自定义转发在回调层已处理）
        if chat.who in self.config.group:
            # 群聊关键词回复
            if self.config.group_keyword_switch:
                # 若开启"仅被@时触发"，则消息中必须包含 @ 标识才继续匹配
                _kw_at_pass = (not self.config.group_keyword_at_only) or (self.config.AtMe in message.content)
                if _kw_at_pass:
                    for keyword in self.config.keyword_dict:
                        if keyword in message.content:
                            log(message=f"群组 {chat.who} 关键字消息：" + message.content)
                            self.config.human_delay()  # 模拟人工操作延迟（可在面板配置）
                            # 走 _send_keyword_reply(is_group=True)：文字回复行为不变，
                            # 关键词内容是文件路径且开启引用时，先发载体消息再发文件
                            result = self._send_keyword_reply(
                                chat,
                                message,
                                self.config.keyword_dict[keyword],
                                is_group=True,
                            )
                            if ReplyCountStore.was_send_success(result):
                                self.msg_replied_count += 1   # 全部失败不计入“已回复”
                            time.sleep(1)
                            return result

            if (self.config.AtMe in message.content and self.config.group_reply_at) \
                    or not self.config.group_reply_at:
                if self.config.group_listen_only:
                    log(message=f"群组 {chat.who} 已启用只监听不AI回复，跳过 AI 调用")
                    return result
                # 去除消息中的 @ 标识后再传给 AI
                content_without_at = re.sub(self.config.AtMe, "", message.content).strip()
                log(message=f"群组 {chat.who} 消息：" + content_without_at)
                # 拼接发送人前缀，与历史消息格式保持一致
                content_with_sender = f"{message.sender}: {content_without_at}"
                try:
                    history = []
                    if self.config.memory_switch and self.memory_manager:
                        history = self.memory_manager.get_messages(
                            chat.who, self.config.memory_context_count
                        )
                    # 构建有效 prompt（拆分开关开启时注入格式要求）
                    _base_group_prompt = self._get_group_prompt(chat.who)
                    if self.config.group_split_reply_switch:
                        _effective_group_prompt = self._build_split_prompt(
                            _base_group_prompt,
                            self.config.group_split_max_chars,
                            self.config.group_split_max_count
                        )
                    else:
                        _effective_group_prompt = _base_group_prompt
                    if self.config.group_image_recognition_switch:
                        if getattr(message, 'merged_image', ''):
                            # 合并回复带图片：正文用合并后的文字（已去掉 @），图片取最后一张
                            rec_index = self.config.group_image_recognition_api
                            reply = self._call_api_with_fallback(
                                rec_index,
                                f"{message.sender}: {content_without_at}",
                                prompt=_effective_group_prompt,
                                history=history,
                                image_path=message.merged_image
                            )
                        elif message.type == 'image':
                            # 直接图片消息：content 已被替换为本地路径
                            rec_index = self.config.group_image_recognition_api
                            reply = self._call_api_with_fallback(
                                rec_index,
                                f"{message.sender}: [这是 {message.sender} 单独发送的一条图片消息，请根据上下文语境分析这张图片和发送者发送的意图进行回复]",
                                prompt=_effective_group_prompt,
                                history=history,
                                image_path=message.content
                            )
                        elif '+引用的图片:' in content_without_at:
                            # 引用图片消息：拆分文字部分和图片路径
                            text_part, img_path = content_without_at.split('+引用的图片:', 1)
                            rec_index = self.config.group_image_recognition_api
                            reply = self._call_api_with_fallback(
                                rec_index,
                                f"{message.sender}: {text_part.strip()}" if text_part.strip() else f"{message.sender}: [这是 {message.sender} 单独发送的一条图片消息，请根据上下文语境分析这张图片和发送者发送的意图进行回复]",
                                prompt=_effective_group_prompt,
                                history=history,
                                image_path=img_path.strip()
                            )
                        else:
                            # 普通文字消息，走原有群组逻辑
                            group_api_index = self._get_group_api_index(chat.who)
                            reply = self._call_api_with_fallback(
                                group_api_index,
                                content_with_sender,
                                prompt=_effective_group_prompt,
                                history=history,
                            )
                    else:
                        # 识别关闭：图片消息静默跳过，文字正常
                        # if message.type == 'image' or '+引用的图片:' in content_without_at:
                            # return result
                        group_api_index = self._get_group_api_index(chat.who)
                        reply = self._call_api_with_fallback(
                            group_api_index,
                            content_with_sender,
                            prompt=_effective_group_prompt,
                            history=history,
                        )
                except Exception as e:
                    print(traceback.format_exc())
                    log(level="ERROR", message=str(e) + "\n群组中调用AI回复错误！！")
                    reply = "API返回错误，请稍后再试"

                # 接口调用失败时替换为配置的固定回复
                if reply == "API返回错误，请稍后再试":
                    reply = self.config.api_error_reply
                else:
                    reply = self._clean_reply_for_send(reply)

                # 拆分多条回复：首条 @ 发言人，后续条不 @
                if self.config.group_split_reply_switch:
                    parts = self._parse_split_reply(reply, self.config.group_split_max_count)
                else:
                    parts = [reply]

                _at_msg   = self.config.group_reply_at_msg
                _quote    = self.config.group_reply_quote
                planned   = len(parts)   # 计划发送的段数
                sent_ok   = 0            # 实际发送成功的段数
                sent_fail = 0            # 实际发送失败的段数
                send_aborted = False     # 中途异常：停止后续发送
                for i, part in enumerate(parts):
                    self.config.human_delay()   # 每条发送前都延迟（含第一条，与原逻辑等效）
                    try:
                        result = self._send_group_reply(
                            chat,
                            message,
                            part,
                            at_sender=_at_msg and i == 0,
                            quote=_quote and i == 0,
                        )
                    except Exception as e:
                        # 发送异常已在 _send_group_reply 内部转成失败结果，
                        # 这里只兜住其它意外，避免穿透到回调最外层触发 callback_is_die
                        log(level="ERROR", message=f"向 {chat.who} 发送群聊消息失败（第 {i + 1} 段）: {e}")
                        result = None
                        send_aborted = True
                    if ReplyCountStore.was_send_success(result):
                        sent_ok += 1
                    else:
                        sent_fail += 1
                    if send_aborted:
                        break

                # 汇总本次群聊发送：不能用 bool(SendOutcome.partial) 判断零成功
                # （部分成功的布尔值就是 False），也不能只看最后一段；未发完一律不算全部成功。
                if sent_ok == 0:
                    group_outcome = SendOutcome.failure(
                        f"发送失败：{planned} 段全部未送达" if planned else "发送失败：没有可发送的段")
                elif sent_ok == planned:
                    group_outcome = SendOutcome.success(f"发送完成：共 {planned} 段")
                else:
                    group_outcome = SendOutcome.partial(
                        f"分段发送部分成功：成功 {sent_ok}/{planned} 段，失败 {sent_fail} 段")

                if sent_ok:
                    # 至少一段实际成功，只计一次；全部失败不计
                    self.msg_replied_count += 1
                return group_outcome

            return result

        # --- 管理员命令处理 ---
        if chat.who == self.config.cmd:
            result = self.process_command(chat, message)
            return result

        # --- 普通好友：调用 AI 回复 ---
        # 白名单模式：来源不在白名单中（纯自定义转发来源），跳过 AI 回复
        if (not self.config.AllListen_switch and
                chat.who not in self.config.listen_list and
                chat.who not in self.config.group and
                chat.who != self.config.cmd):
            return result
        # 全局模式：来源在黑名单中,或者不是私聊（纯自定义转发来源）,跳过 AI 回复
        if (self.config.AllListen_switch and chat.who in self.config.listen_list) or\
            (self.config.AllListen_switch and chat.chat_type == 'group'):
            return result
        # 私聊AI接口回复
        result = self.wx_send_ai(chat, message)
        return result

    def _get_chat_api(self, user_name):
        """获取私聊用户对应的 AI 接口实例（白名单模式查 chat_api_map，否则用默认接口）"""
        if not self.config.AllListen_switch:
            idx = self.config.chat_api_map.get(user_name)
            if idx is not None:
                if idx not in self.api_cache:
                    self.api_cache[idx] = self._init_api_by_index(idx)
                return self.api_cache[idx]
        return self.api

    def _get_chat_prompt(self, user_name):
        """获取私聊用户对应的 prompt 内容（白名单模式查 chat_prompt_map，全局模式用 default_prompt）"""
        if not self.config.AllListen_switch:
            name = self.config.chat_prompt_map.get(user_name) or self.config.default_prompt
        else:
            name = self.config.default_prompt
        return self.config.get_prompt_content(name)

    def _get_group_prompt(self, group_name):
        """获取群组对应的 prompt 内容（查 group_prompt_map，未配置则用 default_prompt）"""
        name = self.config.group_prompt_map.get(group_name) or self.config.default_prompt
        return self.config.get_prompt_content(name)

    def _send_group_reply(self, chat, message, content, at_sender=False, quote=False):
        """发送群聊回复；引用失败时降级为普通发送，避免中断监听回调。

        引用发送与降级后的普通发送若抛异常，统一转成明确的失败结果返回，
        不再穿透到 message_handle_callback 最外层触发 callback_is_die；
        这里只包住发送调用本身，不吞掉其它程序错误。
        """
        if quote:
            try:
                if at_sender:
                    result = message.quote(content, at=message.sender)
                else:
                    result = message.quote(content)
                if ReplyCountStore.was_send_success(result):
                    return result
                err_msg = ReplyCountStore.send_result_message(result)
                log(level="WARNING", message=f"群聊引用回复失败，已降级为普通发送：{err_msg}")
            except Exception as e:
                log(level="WARNING", message=f"群聊引用回复异常，已降级为普通发送：{e}")

        try:
            if at_sender:
                return chat.SendMsg(msg=content, at=message.sender)
            return chat.SendMsg(msg=content)
        except Exception as e:
            log(level="ERROR", message=f"向 {chat.who} 发送群聊消息失败: {e}")
            return SendOutcome.failure(f"群聊发送失败：{e}")

    def _send_keyword_reply(self, chat, message, content, is_group=False):
        """发送关键词回复；引用开关对私聊/群聊均生效，@仅对群聊生效。

        关键词内容是文件路径时：
        - 开启「关键词回复时引用消息」→ 先发一条载体消息（内容固定为
          MEDIA_CARRIER_TEXT "1"）承载引用/@ 语义，再发送文件本身；
        - 未开启引用 → 直接发文件。文件消息本身带不了 @/引用，没有引用语义时
          那条 "1" 只会让用户多收到一条无意义的消息。
        载体消息发送失败只记 WARNING，不阻断发文件。
        """
        if self.is_media_path(content):
            if self.config.keyword_reply_quote:
                carrier = MEDIA_CARRIER_TEXT
                carrier_result = None
                try:
                    if is_group:
                        carrier_result = self._send_group_reply(
                            chat,
                            message,
                            carrier,
                            at_sender=self.config.group_keyword_reply_at_msg,
                            quote=True,
                        )
                    else:
                        carrier_result = message.quote(carrier)
                        if not ReplyCountStore.was_send_success(carrier_result):
                            err_msg = ReplyCountStore.send_result_message(carrier_result)
                            log(level="WARNING", message=f"私聊关键词载体引用失败，已降级为普通发送：{err_msg}")
                            carrier_result = chat.SendMsg(carrier)
                except Exception as e:
                    log(level="WARNING", message=f"关键词文件回复的载体消息发送异常，继续发送文件：{e}")
                if carrier_result is not None and not ReplyCountStore.was_send_success(carrier_result):
                    log(level="WARNING", message=(
                        "关键词文件回复的载体消息发送失败，继续发送文件："
                        + ReplyCountStore.send_result_message(carrier_result)
                    ))

            result = chat.SendFiles(content)
            # SendFiles 成功也常常不返回任何值（None），这里显式当成功，避免误报发送失败
            file_ok = ReplyCountStore.was_send_success(result, none_is_success=True)
            if not file_ok:
                log(level="ERROR", message=f"关键词文件回复发送失败：{ReplyCountStore.send_result_message(result)}")
            # 归一化返回：上层（已回复计数 / 分段发送汇总）用的是普通的 was_send_success，
            # 不归一化的话"发成功但返回 None"会被上层记成失败
            return True if file_ok else result

        if is_group:
            return self._send_group_reply(
                chat,
                message,
                content,
                at_sender=self.config.group_keyword_reply_at_msg,
                quote=self.config.keyword_reply_quote,
            )

        if self.config.keyword_reply_quote:
            try:
                result = message.quote(content)
                if ReplyCountStore.was_send_success(result):
                    return result
                err_msg = ReplyCountStore.send_result_message(result)
                log(level="WARNING", message=f"私聊关键词引用回复失败，已降级为普通发送：{err_msg}")
            except Exception as e:
                log(level="WARNING", message=f"私聊关键词引用回复异常，已降级为普通发送：{e}")

        return chat.SendMsg(content)

    # ----------------------------------------------------------
    # 拆分多条回复辅助方法
    # ----------------------------------------------------------

    def _build_split_prompt(self, base_prompt, max_chars, max_count):
        """将拆分格式要求注入到 prompt 前面，返回组合后的 prompt"""
        return SPLIT_PROMPT_TEMPLATE.format(
            max_chars=max_chars,
            max_count=max_count,
            base_prompt=base_prompt,
        )

    def _parse_split_reply(self, reply, max_count):
        """按 ||SPLIT|| 分隔符解析回复，过滤空白，截断到 max_count 条"""
        parts = [p.strip() for p in reply.split(SPLIT_SEPARATOR) if p.strip()]
        return parts[:max_count] if parts else [reply]

    def _clean_reply_for_send(self, reply):
        """按配置清洗即将发送给用户的 AI 回复。"""
        if not self.config.clean_ai_reply_switch:
            return reply
        cleaned = clean_ai_reply_text(reply)
        if cleaned:
            return cleaned
        log(level="WARNING", message="AI 回复清洗后为空，已使用接口失败固定回复兜底")
        return self.config.api_error_reply

    def _get_reply_count_key(self, chat, message=None):
        """获取回复计数器 key；当前 wxautox4 可用稳定字段有限，先集中使用 chat.who。"""
        return str(getattr(chat, 'who', '') or '').strip()

    def _get_chat_max_round(self, user_name):
        """获取私聊用户的回复轮数上限；白名单模式优先用户专属上限。"""
        if not self.config.AllListen_switch:
            custom_value = self.config.chat_max_round_map.get(user_name)
            if custom_value:
                return custom_value
        return self.config.chat_max_round_default

    def _check_chat_max_round_limit(self, chat, user_key):
        """检查并处理私聊回复轮数超限；返回 (是否已处理, 发送结果)。"""
        if not self.config.chat_max_round_switch or not user_key:
            return False, True
        self.reply_count_store.maybe_reset(self.config.chat_max_round_reset_days)
        user_data = self.reply_count_store.get_user(user_key)
        max_round = self._get_chat_max_round(user_key)
        if user_data.get("ai_count", 0) < max_round:
            return False, True

        if self.config.chat_max_round_reply_once and user_data.get("limit_notified"):
            return True, True
        if not self.config.chat_max_round_reply:
            return True, True

        result = chat.SendMsg(self.config.chat_max_round_reply)
        if ReplyCountStore.was_send_success(result):
            self.msg_replied_count += 1
            if self.config.chat_max_round_reply_once:
                self.reply_count_store.mark_limit_notified(user_key)
        return True, result

    def _is_custom_forward_source(self, chat_who):
        """判断某个会话是否是任意自定义转发规则的监听来源"""
        for rule in self.config.custom_forward_list:
            if chat_who in rule.get('sources', []):
                return True
        return False

    def _handle_custom_forward(self, chat, message):
        """
        自定义规则转发执行器。
        遍历所有规则，找到 chat.who 匹配的来源，按规则类型判断是否转发，
        符合条件则逐目标转发（每次转发前延时 1 秒）。

        转发类型：
          keyword — 消息内容包含任意关键词时转发
          sender  — 消息发送人匹配时转发
          all     — 无差别转发，所有消息均转发
        """
        if not self.config.custom_forward_switch:
            return
        for rule in self.config.custom_forward_list:
            # 全部来源：不过滤来源；否则只处理配置的来源
            if not rule.get('all_sources', False) and chat.who not in rule.get('sources', []):
                continue
            rule_type = rule.get('type', 'all')
            should_forward = False
            if rule_type == 'all':
                should_forward = True
            elif rule_type == 'keyword':
                keywords = rule.get('keywords', [])
                should_forward = any(kw and kw in message.content for kw in keywords)
            elif rule_type == 'sender':
                senders = rule.get('senders', [])
                should_forward = bool(senders) and message.sender in senders
            if should_forward:
                forward_with_source = rule.get('forward_with_source', False)
                src_msg = f"来源窗口：{chat.who}，发送人：{message.sender}" if forward_with_source else None
                for target in rule.get('targets', []):
                    if target:
                        time.sleep(1)
                        if src_msg:
                            if message.type in ['image', 'video', 'file', 'location', 'link', 'emotion', 'merge', 'personal_card', 'note', 'miniapp']:
                                message.forward(target, message=src_msg)
                            else:
                                self.wx.SendMsg(who=target, msg=message.content+"\n"+src_msg)
                        else:
                            if message.type in ['image', 'video', 'file', 'location', 'link', 'emotion', 'merge', 'personal_card', 'note', 'miniapp']:
                                message.forward(target)
                            else:
                                self.wx.SendMsg(who=target, msg=message.content)
                        log(message=f"[自定义转发] {chat.who} → {target}（规则类型：{rule_type}，附带来源：{forward_with_source}）")

    def wx_send_ai(self, chat, message):
        """
        对私聊消息调用 AI 接口并发送回复。
        支持关键词优先匹配，超过 2000 字时自动分段发送。

        :param chat:    聊天窗口子对象
        :param message: 消息对象
        :return:        发送结果
        """
        result = True
        user_key = self._get_reply_count_key(chat, message)

        api_error_reply = False
        api_error_should_mark = False
        is_keyword = False
        try:
            # 私聊关键词优先匹配
            if self.config.chat_keyword_switch:
                for keyword in self.config.keyword_dict:
                    if keyword in message.content:
                        is_keyword = True
                        log(message=f"私聊 {chat.who} 关键字消息：" + message.content)
                        reply = self.config.keyword_dict[keyword]
            if not is_keyword:
                if self.config.chat_listen_only:
                    log(message=f"私聊 {chat.who} 已启用只监听不AI回复，跳过 AI 调用")
                    return True
                limit_handled, limit_result = self._check_chat_max_round_limit(chat, user_key)
                if limit_handled:
                    return limit_result
                # 未命中关键词，调用 AI 接口（带入历史记忆）
                history = []
                if self.config.memory_switch and self.memory_manager:
                    history = self.memory_manager.get_messages(
                        chat.who, self.config.memory_context_count
                    )
                # 构建有效 prompt（拆分开关开启时注入格式要求）
                _base_prompt = self._get_chat_prompt(chat.who)
                if self.config.chat_split_reply_switch:
                    _effective_prompt = self._build_split_prompt(
                        _base_prompt,
                        self.config.chat_split_max_chars,
                        self.config.chat_split_max_count
                    )
                else:
                    _effective_prompt = _base_prompt
                if self.config.chat_image_recognition_switch:
                    if getattr(message, 'merged_image', ''):
                        # 合并回复带图片：正文是合并后的文字，图片取最后一张
                        rec_index = self.config.chat_image_recognition_api
                        reply = self._call_api_with_fallback(
                            rec_index,
                            message.content,
                            prompt=_effective_prompt,
                            history=history,
                            image_path=message.merged_image
                        )
                    elif message.type == 'image':
                        # 直接图片消息：content 已被替换为本地路径（图片识别优先使用图片识别接口）
                        rec_index = self.config.chat_image_recognition_api
                        reply = self._call_api_with_fallback(
                            rec_index,
                            "[这是单独发送的一条图片消息，请根据上下文语境分析这张图片和发送者发送的意图进行回复]",
                            prompt=_effective_prompt,
                            history=history,
                            image_path=message.content
                        )
                    elif '+引用的图片:' in message.content:
                        # 引用图片消息：拆分文字部分和图片路径
                        text_part, img_path = message.content.split('+引用的图片:', 1)
                        rec_index = self.config.chat_image_recognition_api
                        reply = self._call_api_with_fallback(
                            rec_index,
                            text_part.strip() or "[这是单独发送的一条图片消息，请根据上下文语境分析这张图片和发送者发送的意图进行回复]",
                            prompt=_effective_prompt,
                            history=history,
                            image_path=img_path.strip()
                        )
                    else:
                        # 普通文字消息：使用用户专属接口和 prompt
                        chat_api_index = self._get_chat_api_index(chat.who)
                        reply = self._call_api_with_fallback(
                            chat_api_index,
                            message.content,
                            prompt=_effective_prompt,
                            history=history,
                        )
                else:
                    # 识别关闭：图片消息静默跳过，文字消息正常
                    # if message.type == 'image' or '+引用的图片:' in message.content:
                        # return True
                    chat_api_index = self._get_chat_api_index(chat.who)
                    reply = self._call_api_with_fallback(
                        chat_api_index,
                        message.content,
                        prompt=_effective_prompt,
                        history=history,
                    )
        except Exception as e:
            print(traceback.format_exc())
            log(level="ERROR", message=str(e) + "\nAPI返回错误，请稍后再试")
            api_error_reply = True
            if self.config.api_error_reply_once and user_key:
                user_data = self.reply_count_store.get_user(user_key)
                if user_data.get("api_err_notified"):
                    return True
                api_error_should_mark = True
            reply = self.config.api_error_reply

        # 接口调用失败时替换为配置的固定回复
        if reply == "API返回错误，请稍后再试":
            if self.config.api_error_reply_once and user_key:
                user_data = self.reply_count_store.get_user(user_key)
                if user_data.get("api_err_notified"):
                    return True
                api_error_should_mark = True
            reply = self.config.api_error_reply
            api_error_reply = True
        else:
            reply = self._clean_reply_for_send(reply)

        # 拆分多条回复：仅在开关开启且回复包含分隔符时生效
        if self.config.chat_split_reply_switch:
            parts = self._parse_split_reply(reply, self.config.chat_split_max_count)
        else:
            parts = [reply]

        send_success = False
        send_aborted = False    # 发送抛异常：只结束本条消息的发送，不算基础故障
        sent_total   = 0        # 实际尝试发送的段数
        sent_ok      = 0        # 发送成功的段数
        for i, part in enumerate(parts):
            self.config.human_delay()   # 每条发送前都延迟（含第一条，与原逻辑等效）
            if len(part) >= 2000:
                for j, segment in enumerate(self.config.split_long_text(part)):
                    sent_total += 1
                    try:
                        if is_keyword and i == 0 and j == 0:
                            result = self._send_keyword_reply(chat, message, segment)
                        else:
                            result = chat.SendMsg(segment)
                    except Exception as e:
                        # 普通发送失败：记录后结束本次处理即可。
                        # 若让它穿透到 message_handle_callback 最外层，会置 callback_is_die，
                        # 主循环随即 StopListening 停掉全部监听（一条消息发失败 → 机器人整体停机）。
                        log(level="ERROR", message=f"向 {chat.who} 发送消息失败（第 {i + 1} 条）: {e}")
                        result = None
                        send_aborted = True
                    if ReplyCountStore.was_send_success(result):
                        send_success = True
                        sent_ok += 1
                    if send_aborted:
                        break
            else:
                sent_total += 1
                try:
                    if is_keyword and i == 0:
                        result = self._send_keyword_reply(chat, message, part)
                    else:
                        result = chat.SendMsg(part)
                except Exception as e:
                    log(level="ERROR", message=f"向 {chat.who} 发送消息失败（第 {i + 1} 条）: {e}")
                    result = None
                    send_aborted = True
                if ReplyCountStore.was_send_success(result):
                    send_success = True
                    sent_ok += 1
            if send_aborted:
                break

        # 统一发送结果：不再让 result 被最后一段覆盖（失败+成功曾返回“成功”）
        if sent_total and sent_ok == sent_total:
            send_outcome = SendOutcome.success(f"发送完成：共 {sent_total} 段")
        elif sent_ok:
            send_outcome = SendOutcome.partial(f"分段发送部分成功：成功 {sent_ok}/{sent_total} 段")
        else:
            send_outcome = SendOutcome.failure(f"发送失败：{sent_total} 段全部未送达")

        if send_success and api_error_should_mark:
            self.reply_count_store.mark_api_err_notified(user_key)

        if send_success and self.config.chat_max_round_switch and user_key and not api_error_reply:
            self.reply_count_store.increment_ai_count(user_key)

        if send_success:
            # 全部失败不计入“已回复”
            self.msg_replied_count += 1
        return send_outcome

    # ----------------------------------------------------------
    # 管理员命令分发
    # ----------------------------------------------------------

    def process_command(self, chat, message):
        """
        解析并分发管理员指令。
        支持用户/群组管理、模型切换、AI 设定修改、状态查询等。

        :param chat:    管理员聊天窗口子对象
        :param message: 消息对象
        :return:        操作结果
        """
        result = True
        content = message.content

        # --- 用户与群组管理（监听名单 / 群开关 / 群欢迎语）---
        if content.startswith("/添加用户"):
            result = self.handle_add_user(chat, message)
        elif content.startswith("/删除用户"):
            result = self.handle_remove_user(chat, message)
        elif content == "/当前用户":
            result = chat.SendMsg("当前用户：\n" + ", ".join(self.config.listen_list))
        elif content == "/当前群":
            result = chat.SendMsg("当前群：\n" + ", ".join(self.config.group))
        elif content == "/群机器人状态":
            result = self.handle_group_switch_status(chat, message)
        elif content.startswith("/添加群"):
            result = self.handle_add_group(chat, message)
        elif content.startswith("/删除群"):
            result = self.handle_remove_group(chat, message)
        elif content == "/开启群机器人":
            result = self.handle_enable_group_bot(chat, message)
        elif content == "/关闭群机器人":
            result = self.handle_disable_group_bot(chat, message)
        elif content == "/开启群机器人欢迎语":
            result = self.handle_enable_welcome_msg(chat, message)
        elif content == "/关闭群机器人欢迎语":
            result = self.handle_disable_welcome_msg(chat, message)
        elif content == "/群机器人欢迎语状态":
            result = self.handle_welcome_msg_status(chat, message)
        elif content == "/当前群机器人欢迎语":
            result = chat.SendMsg("当前群机器人欢迎语：\n" + self.config.group_welcome_msg)
        elif content.startswith("/更改群机器人欢迎语为"):
            result = self.handle_change_welcome_msg(chat, message)
        # --- 接口与设定：查看/选择接口、改 AI 设定、热重载配置、查版本 ---
        elif content == "/查看接口列表":
            result = self.handle_list_api_configs(chat, message)
        elif content.startswith("/选择接口"):
            result = self.handle_select_api_config(chat, message)
        elif content == "/当前AI设定":
            _default_content = self.config.get_prompt_content(self.config.default_prompt)
            result = chat.SendMsg(f'当前默认AI设定（{self.config.default_prompt}）：\n' + _default_content)
        elif content.startswith("/更改AI设定为") or content.startswith("/更改ai设定为"):
            result = self.handle_change_prompt(chat, message)
        elif content == "/当前版本":
            result = chat.SendMsg(
                content + 'wxbot_' + self.ver + '\n' + self.ver_log + '\n作者:https://www.siver.top'
            )
        # --- 指令帮助清单：把分类指令一次性发给管理员 ---
        elif content in ("/指令", "指令"):
            result = self.send_command_list(chat)
        elif content == "/系统状态指令":
            result = chat.SendMsg(
                '--- 系统状态 ---\n'
                '[/状态] 完整运行状态摘要\n'
                '[/接口测试 内容] 测试当前AI接口\n'
                '[/当前版本] 版本号及更新说明'
            )
        elif content == "/用户管理指令":
            result = chat.SendMsg(
                '--- 用户管理 ---\n'
                '[/当前用户] 当前监听用户列表\n'
                '[/添加用户***] 添加监听用户\n'
                '[/删除用户***] 移除监听用户'
            )
        elif content == "/群组管理指令":
            result = chat.SendMsg(
                '--- 群组管理 ---\n'
                '[/当前群] 当前监听群列表\n'
                '[/添加群***] / [/删除群***]\n'
                '[/开启群机器人] / [/关闭群机器人]\n'
                '[/群机器人状态]\n'
                '[/开启群机器人欢迎语] / [/关闭群机器人欢迎语]\n'
                '[/群机器人欢迎语状态]\n'
                '[/当前群机器人欢迎语]\n'
                '[/更改群机器人欢迎语为***]'
            )
        elif content == "/Prompt管理指令":
            result = chat.SendMsg(
                '--- Prompt 管理 ---\n'
                '[/Prompt列表] 所有可用Prompt\n'
                '[/当前Prompt] 默认Prompt名称及内容\n'
                '[/切换Prompt ***] 切换默认Prompt\n'
                '[/更改AI设定为***] 修改默认Prompt内容\n'
                '[/当前AI设定] 查看当前默认Prompt内容'
            )
        elif content == "/关键词指令":
            result = chat.SendMsg(
                '--- 关键词回复 ---\n'
                '[/关键词状态] 查看关键词配置及列表\n'
                '[/开启私聊关键词] / [/关闭私聊关键词]\n'
                '[/开启群聊关键词] / [/关闭群聊关键词]\n'
                '[/开启群聊关键词@触发] / [/关闭群聊关键词@触发]\n'
                '群关键词 @ 发言人和引用原消息请在面板配置'
            )
        elif content == "/记忆指令":
            result = chat.SendMsg(
                '--- 对话记忆 ---\n'
                '[/记忆状态] 查看记忆配置\n'
                '[/开启记忆] / [/关闭记忆]\n'
                '[/清除记忆] 清除管理员对话记忆\n'
                '[/清除用户记忆 ***] 清除指定用户/群记忆\n'
                '[/清除全部记忆] 清除所有对话记忆'
            )
        elif content == "/延迟指令":
            result = chat.SendMsg(
                '--- 回复延迟 ---\n'
                '[/回复延迟状态] 查看回复延迟配置\n'
                '[/开启回复延迟] / [/关闭回复延迟]'
            )
        elif content == "/暂停恢复指令":
            result = chat.SendMsg(
                '--- 只监听不 AI 回复 ---\n'
                '[/自动回复状态] 查看当前只监听状态\n'
                '[/暂停私聊自动回复] 开启私聊只监听不 AI 回复\n'
                '[/恢复私聊自动回复] 关闭私聊只监听不 AI 回复\n'
                '[/暂停群聊自动回复] 开启群聊只监听不 AI 回复\n'
                '[/恢复群聊自动回复] 关闭群聊只监听不 AI 回复\n'
                '开启后监听、记忆、关键词回复和自定义转发保持运行，仅停止调用 AI 接口自动回复'
            )
        elif content == "/图片识别指令":
            result = chat.SendMsg(
                '--- 图片识别 ---\n'
                '[/图片识别状态] 查看私聊/群聊图片识别开关及接口\n'
                '（开关需在面板配置，指令仅支持查看）'
            )
        elif content == "/拆分回复指令":
            result = chat.SendMsg(
                '--- 拆分多条回复 ---\n'
                '[/拆分回复状态] 查看拆分回复配置\n'
                '[/开启私聊拆分回复] / [/关闭私聊拆分回复]\n'
                '[/开启群聊拆分回复] / [/关闭群聊拆分回复]\n'
                '（字数/条数上限需在面板配置）'
            )
        elif content == "/新好友指令":
            result = chat.SendMsg(
                '--- 新好友 ---\n'
                '[/新好友状态] 查看新好友自动通过及回复状态\n'
                '（开关需在面板配置，指令仅支持查看）'
            )
        elif content == "/接口指令":
            result = chat.SendMsg(
                '--- AI接口 & 错误回复 ---\n'
                '[/查看接口列表] 返回所有接口配置\n'
                '[/选择接口 N] 切换至第N个接口\n'
                '[/查看错误回复] 查看接口失败固定回复\n'
                '[/设置错误回复 ***] 修改接口失败固定回复'
            )
        elif content == "/计数器指令":
            _round_sw = "开启" if self.config.chat_max_round_switch else "关闭"
            _round_reset = self.config.chat_max_round_reset_days
            _reset_desc = "不重置" if _round_reset == 0 else f"{_round_reset}天"
            _reply_desc = self.config.chat_max_round_reply or "（空，超限后静默）"
            result = chat.SendMsg(
                '--- 回复计数器 ---\n'
                f'轮数限制开关：{_round_sw}\n'
                f'默认上限：{self.config.chat_max_round_default} 轮\n'
                f'白名单专属上限：{len(self.config.chat_max_round_map)} 个\n'
                f'重置周期：{_reset_desc}\n'
                f'超限话术：{_reply_desc}\n'
                f'超限只回复一次：{"是" if self.config.chat_max_round_reply_once else "否"}\n'
                f'接口失败只回复一次：{"是" if self.config.api_error_reply_once else "否"}\n'
                '[/清除计数 昵称] 清除指定用户的回复计数与通知状态'
            )
        # --- 状态查询与快捷开关（关键词 / 记忆 / 回复延迟 / 暂停恢复 / 接口测试）---
        elif content == "/状态":
            result = self._build_status_msg(chat, message)
        elif content == "/关键词状态":
            priv = "开启" if self.config.chat_keyword_switch else "关闭"
            grp  = "开启" if self.config.group_keyword_switch else "关闭"
            at   = "是"   if self.config.group_keyword_at_only else "否"
            reply_at = "是" if self.config.group_keyword_reply_at_msg else "否"
            quote = "是" if self.config.keyword_reply_quote else "否"
            cnt  = len(self.config.keyword_dict)
            keys = ", ".join(self.config.keyword_dict.keys()) if self.config.keyword_dict else "（无）"
            result = chat.SendMsg(
                f"私聊关键词：{priv}\n"
                f"群聊关键词：{grp}\n"
                f"群聊仅@触发：{at}\n"
                f"群聊关键词回复@发言人：{reply_at}\n"
                f"关键词回复引用消息：{quote}（私聊/群聊均生效）\n"
                f"关键词数量：{cnt} 个\n"
                f"关键词列表：{keys}"
            )
        elif content == "/开启群聊关键词@触发":
            self.config.set_config('group_keyword_at_only', True)
            result = chat.SendMsg("群聊关键词已设为：仅被@时触发")
        elif content == "/关闭群聊关键词@触发":
            self.config.set_config('group_keyword_at_only', False)
            result = chat.SendMsg("群聊关键词已设为：无论是否@均触发")
        elif content == "/记忆状态":
            sw  = "开启" if self.config.memory_switch else "关闭"
            result = chat.SendMsg(
                f"对话记忆：{sw}\n"
                f"上下文条数：{self.config.memory_context_count} 条\n"
                f"最大存储：{self.config.memory_max_count} 条"
            )
        elif content == "/开启记忆":
            self.config.set_config('memory_switch', True)
            result = chat.SendMsg("对话记忆已开启")
        elif content == "/关闭记忆":
            self.config.set_config('memory_switch', False)
            result = chat.SendMsg("对话记忆已关闭")
        elif content == "/回复延迟状态":
            sw = "开启" if self.config.reply_delay_switch else "关闭"
            result = chat.SendMsg(
                f"回复延迟：{sw}\n"
                f"延迟范围：{self.config.reply_delay_min}~{self.config.reply_delay_max}s"
            )
        elif content == "/开启回复延迟":
            self.config.set_config('reply_delay_switch', True)
            result = chat.SendMsg(f"回复延迟已开启（{self.config.reply_delay_min}~{self.config.reply_delay_max}s）")
        elif content == "/关闭回复延迟":
            self.config.set_config('reply_delay_switch', False)
            result = chat.SendMsg("回复延迟已关闭")
        # --- 暂停/恢复自动回复 ---
        elif content == "/暂停私聊自动回复":
            self.config.set_config('chat_listen_only', True)
            result = chat.SendMsg("私聊已开启只监听不 AI 回复；监听、记忆、关键词回复和自定义转发保持运行。发送 /恢复私聊自动回复 可关闭")
        elif content == "/恢复私聊自动回复":
            self.config.set_config('chat_listen_only', False)
            result = chat.SendMsg("私聊只监听不 AI 回复已关闭，私聊 AI 自动回复已恢复")
        elif content == "/暂停群聊自动回复":
            self.config.set_config('group_listen_only', True)
            result = chat.SendMsg("群聊已开启只监听不 AI 回复；监听、记忆、关键词回复和自定义转发保持运行。发送 /恢复群聊自动回复 可关闭")
        elif content == "/恢复群聊自动回复":
            self.config.set_config('group_listen_only', False)
            result = chat.SendMsg("群聊只监听不 AI 回复已关闭，群聊 AI 自动回复已恢复")
        elif content == "/自动回复状态":
            chat_st  = "只监听不 AI 回复" if self.config.chat_listen_only else "AI 自动回复开启"
            group_st = "只监听不 AI 回复" if self.config.group_listen_only else "AI 自动回复开启"
            result = chat.SendMsg(
                f"--- 自动回复状态 ---\n"
                f"私聊：{chat_st}\n"
                f"群聊：{group_st}"
            )
        elif content.startswith("/接口测试"):
            message_re = message
            message_re.content = re.sub("/接口测试", "", message.content).strip()
            result = self.wx_send_ai(chat, message_re)
        # --- Prompt 管理 ---
        # --- Prompt 与记忆操作、其余开关与状态 ---
        elif content == "/Prompt列表":
            result = self.handle_list_prompts(chat, message)
        elif content == "/当前Prompt":
            name = self.config.default_prompt
            body = self.config.get_prompt_content(name)
            result = chat.SendMsg(f"当前默认Prompt（{name}）：\n{body}")
        elif content.startswith("/切换Prompt"):
            result = self.handle_switch_prompt(chat, message)
        # --- 清除记忆 ---
        elif content == "/清除记忆":
            result = self.handle_clear_memory(chat, message)
        elif content.startswith("/清除用户记忆"):
            result = self.handle_clear_user_memory(chat, message)
        elif content == "/清除全部记忆":
            result = self.handle_clear_all_memory(chat, message)
        # --- 图片识别 ---
        elif content == "/图片识别状态":
            result = self.handle_image_recognition_status(chat, message)
        # --- 拆分多条回复 ---
        elif content == "/拆分回复状态":
            result = self.handle_split_reply_status(chat, message)
        elif content == "/开启私聊拆分回复":
            self.config.set_config('chat_split_reply_switch', True)
            result = chat.SendMsg(f"私聊拆分回复已开启（单条≤{self.config.chat_split_max_chars}字，最多{self.config.chat_split_max_count}条）")
        elif content == "/关闭私聊拆分回复":
            self.config.set_config('chat_split_reply_switch', False)
            result = chat.SendMsg("私聊拆分回复已关闭")
        elif content == "/开启群聊拆分回复":
            self.config.set_config('group_split_reply_switch', True)
            result = chat.SendMsg(f"群聊拆分回复已开启（单条≤{self.config.group_split_max_chars}字，最多{self.config.group_split_max_count}条）")
        elif content == "/关闭群聊拆分回复":
            self.config.set_config('group_split_reply_switch', False)
            result = chat.SendMsg("群聊拆分回复已关闭")
        # --- 关键词开关完善 ---
        elif content == "/开启私聊关键词":
            self.config.set_config('chat_keyword_switch', True)
            result = chat.SendMsg("私聊关键词回复已开启")
        elif content == "/关闭私聊关键词":
            self.config.set_config('chat_keyword_switch', False)
            result = chat.SendMsg("私聊关键词回复已关闭")
        elif content == "/开启群聊关键词":
            self.config.set_config('group_keyword_switch', True)
            result = chat.SendMsg("群聊关键词回复已开启")
        elif content == "/关闭群聊关键词":
            self.config.set_config('group_keyword_switch', False)
            result = chat.SendMsg("群聊关键词回复已关闭")
        # --- 新好友 ---
        elif content == "/新好友状态":
            result = self.handle_new_friend_status(chat, message)
        # --- 接口错误固定回复 ---
        elif content == "/查看错误回复":
            result = chat.SendMsg(f"接口失败固定回复：{self.config.api_error_reply}")
        elif content.startswith("/设置错误回复"):
            new_err = re.sub("/设置错误回复", "", content).strip()
            if new_err:
                self.config.set_config('api_error_reply', new_err)
                result = chat.SendMsg(f"接口失败固定回复已更新：{new_err}")
            else:
                result = chat.SendMsg("请提供回复内容，如：/设置错误回复 在忙，我稍后回复您")
        # --- 回复计数器清零 ---
        elif content.startswith("/清除计数"):
            target = re.sub("/清除计数", "", content).strip()
            if not target:
                result = chat.SendMsg("请提供用户昵称，如：/清除计数 张三")
            elif self.reply_count_store.clear_user(target):
                result = chat.SendMsg(f"已清除 {target} 的回复计数与通知状态")
            else:
                result = chat.SendMsg(f"未找到 {target} 的计数记录（可能尚未触发过回复）")
        else:
            # 未匹配到任何指令
            # self 消息（文件传输助手场景下机器人自身回复的同步）不调用 AI，避免误触发关键词或 AI 回复
            if message.attr != "self":
                result = self.wx_send_ai(chat, message)

        # 本轮命令期间若有配置保存失败，补一条明确警告。
        # 各分支的"完成"文案不再逐个改：这里统一兜底，避免"失败却报成功"。
        if self.config.save_failed:
            self.config.save_failed = False
            try:
                chat.SendMsg("⚠ 注意：本次操作的配置未能写入磁盘，重启后可能丢失，请检查磁盘权限/空间")
            except Exception:
                pass

        return result

    def _build_status_msg(self, chat, message):
        """
        构建并发送机器人当前状态摘要信息。
        （从 process_command 中抽离，降低单函数复杂度）
        """
        wx_nickname = self.wx.nickname if self.wx else "未知"
        send_msg  = f"账号：{wx_nickname}\n"
        send_msg += "运行时间：" + self.config.get_run_time(self.start_time) + "\n"
        send_msg += f"当前接口：{self.config.api_index + 1}/{len(self.config.api_configs)}  SDK：{self.config.api_sdk}  模型：{self.api.DS_NOW_MOD}\n"
        send_msg += f"已收消息：{self.msg_received_count} 条  已回复：{self.msg_replied_count} 条\n"
        if self.last_msg_time:
            send_msg += f"最近消息：{self.last_msg_sender}（{self.last_msg_time}）\n"

        # 当前监听模式及列表
        if self.config.AllListen_switch:
            send_msg += "当前模式：黑名单模式\n"
            send_msg += "当前黑名单：" + ", ".join(self.config.listen_list) + "\n"
        else:
            send_msg += "当前模式：白名单模式\n"
            send_msg += "当前白名单：" + ", ".join(self.config.listen_list) + "\n"

        # 群机器人状态
        if self.config.group_switch:
            send_msg += "当前群机器人状态：开启\n"
            send_msg += "当前群：" + ", ".join(self.config.group) + "\n"
            if self.config.group_welcome:
                send_msg += f"当前群机器人欢迎语状态：开启 欢迎概率：{self.config.group_welcome_random}\n"
            else:
                send_msg += "当前群机器人欢迎语状态：关闭\n"
        else:
            send_msg += "当前群机器人状态：关闭\n"

        # 关键词回复状态
        send_msg += "当前私聊关键词回复状态：" + ("开启\n" if self.config.chat_keyword_switch else "关闭\n")
        send_msg += "当前群聊关键词回复状态：" + ("开启\n" if self.config.group_keyword_switch else "关闭\n")
        if self.config.group_keyword_switch:
            send_msg += "群聊关键词仅@触发：" + ("是\n" if self.config.group_keyword_at_only else "否\n")
            send_msg += "群聊关键词回复@发言人：" + ("是\n" if self.config.group_keyword_reply_at_msg else "否\n")
        send_msg += "关键词回复引用消息：" + ("是\n" if self.config.keyword_reply_quote else "否\n")
        send_msg += f"关键词数量：{len(self.config.keyword_dict)} 个\n"
        if self.config.keyword_dict:
            send_msg += "当前关键词：" + ", ".join(self.config.keyword_dict.keys()) + "\n"

        # 对话记忆状态
        send_msg += "对话记忆：" + ("开启" if self.config.memory_switch else "关闭")
        if self.config.memory_switch:
            send_msg += f"  上下文条数：{self.config.memory_context_count}\n"
        else:
            send_msg += "\n"

        # 回复延迟状态
        send_msg += "回复延迟：" + ("开启" if self.config.reply_delay_switch else "关闭")
        if self.config.reply_delay_switch:
            send_msg += f"  延迟范围：{self.config.reply_delay_min}~{self.config.reply_delay_max}s\n"
        else:
            send_msg += "\n"

        # 定时消息状态
        send_msg += "当前定时消息状态：" + ("开启\n" if self.config.scheduled_msg_switch else "关闭\n")

        # 图片识别状态
        send_msg += "私聊图片识别：" + ("开启" if self.config.chat_image_recognition_switch else "关闭")
        send_msg += "  群聊图片识别：" + ("开启\n" if self.config.group_image_recognition_switch else "关闭\n")

        # 拆分多条回复状态
        send_msg += "私聊拆分回复：" + ("开启" if self.config.chat_split_reply_switch else "关闭")
        send_msg += "  群聊拆分回复：" + ("开启\n" if self.config.group_split_reply_switch else "关闭\n")

        # 新好友状态
        send_msg += "新好友自动通过：" + ("开启" if self.config.new_friend_switch else "关闭")
        send_msg += "  自动回复：" + ("开启\n" if self.config.new_friend_reply_switch else "关闭\n")

        # 当前默认 Prompt
        send_msg += f"当前默认Prompt：{self.config.default_prompt}\n"

        # 接口错误固定回复
        send_msg += f"接口失败回复：{self.config.api_error_reply}\n"

        return chat.SendMsg(send_msg)

    # ----------------------------------------------------------
    # 管理员命令处理子函数
    # ----------------------------------------------------------

    def handle_add_user(self, chat, message):
        """处理 /添加用户 指令：将用户加入监听列表并注册监听"""
        user_to_add = re.sub("/添加用户", "", message.content).strip()
        self.config.add_user(user_to_add)
        if not self.config.AllListen_switch:
            # 白名单模式下需要同时向 wxautox 注册监听
            result = self.wx.AddListenChat(nickname=user_to_add, callback=self.message_handle_callback)
            if result:
                log(message=f"添加用户 {user_to_add} 监听完成")
                return chat.SendMsg('添加用户完成\n' + ", ".join(self.config.listen_list))
            else:
                # 注册失败则回滚配置
                self.config.remove_user(user_to_add)
                log(level="ERROR", message=f"添加用户 {user_to_add} 监听失败, {ReplyCountStore.send_result_message(result)}")
                return chat.SendMsg(
                    f"添加用户失败\n{ReplyCountStore.send_result_message(result)}\n" + ", ".join(self.config.listen_list)
                )
        else:
            # 黑名单模式下只更新配置，无需注册监听
            return chat.SendMsg('添加用户完成(黑名单)\n' + ", ".join(self.config.listen_list))

    def handle_remove_user(self, chat, message):
        """处理 /删除用户 指令：移除用户的监听注册并从配置中删除"""
        user_to_remove = re.sub("/删除用户", "", message.content).strip()
        self.wx.RemoveListenChat(user_to_remove)
        self.config.remove_user(user_to_remove)
        return chat.SendMsg('删除用户完成\n' + ", ".join(self.config.listen_list))

    def handle_group_switch_status(self, chat, message):
        """处理 /群机器人状态 指令：返回当前群机器人开关状态"""
        if self.config.group_switch:
            result = chat.SendMsg(message.content + '为关闭')
        else:
            result = chat.SendMsg(message.content + '为开启')
        return result

    def handle_add_group(self, chat, message):
        """处理 /添加群 指令：将群组加入监听列表并注册监听"""
        new_group = re.sub("/添加群", "", message.content).strip()
        self.config.add_group(new_group)
        if self.config.group_switch:
            result = self.wx.AddListenChat(nickname=new_group, callback=self.message_handle_callback)
            if result:
                log(message=f"添加群组 {new_group} 监听完成")
                return chat.SendMsg('添加群完成\n' + ", ".join(self.config.group))
            else:
                # 注册失败则回滚配置
                self.config.remove_group(new_group)
                log(level="ERROR", message=f"添加群组 {new_group} 监听失败, {ReplyCountStore.send_result_message(result)}")
                return chat.SendMsg(
                    f"添加群失败\n{ReplyCountStore.send_result_message(result)}\n" + ", ".join(self.config.group)
                )
        else:
            return chat.SendMsg('添加群完成(群机器人未开启)\n' + ", ".join(self.config.group))

    def handle_remove_group(self, chat, message):
        """处理 /删除群 指令：移除群组的监听注册并从配置中删除"""
        group_to_remove = re.sub("/删除群", "", message.content).strip()
        self.wx.RemoveListenChat(group_to_remove)
        self.config.remove_group(group_to_remove)
        return chat.SendMsg('删除群完成\n' + ", ".join(self.config.group))

    def handle_enable_group_bot(self, chat, message):
        """处理 /开启群机器人 指令：开启开关并逐个注册群列表监听。

        ⚠ 本方法运行在 wxautox 的消息回调线程里，绝不能调用 init_wx_listeners()：
        它内部的 StopListening() 会 join 自己所在的监听线程池，抛
        RuntimeError: cannot join current thread，随后 callback_is_die 置位，
        主循环会停掉整个机器人。因此这里与 /关闭群机器人 对称，只逐个注册。
        """
        self.config.set_config(id='group_switch', new_content=True)

        if not self.config.group:
            return chat.SendMsg(message.content + ' 完成，但当前没有配置任何群\n请先用 /添加群 添加群')

        registered, failed = [], []
        for group_name in self.config.group:
            try:
                # 无条件注册，与 init_wx_listeners 一致：子窗口存在不等于"回调已注册"，
                # 不能用它作为跳过注册的依据（/关闭群机器人 只移除回调，子窗口可能仍在，
                # 一旦据此跳过，该群将永久不被监听）。
                time.sleep(0.5)
                if self._add_listen_chat_once(group_name, "群组"):
                    registered.append(group_name)
                else:
                    failed.append(group_name)
            except Exception as e:
                # 逐群捕获：单个群注册异常只算该群失败，不能让整轮注册静默中断后仍回报"完成"
                log(level="ERROR", message=f"注册群监听时出错（{group_name}）: {e}")
                failed.append(group_name)

        if registered:
            try:
                self._verify_initial_listeners(registered)
            except Exception as e:
                log(level="ERROR", message=f"校验群监听时出错: {e}")

        if failed and not registered:
            # 一个都没注册成功：回滚开关，避免"开关开着却没有任何群被监听"
            self.config.set_config('group_switch', False)
            return chat.SendMsg(
                message.content + ' 失败\n请检查群名称是否正确、机器人号是否在该群内\n'
                + '注册失败的群：' + ", ".join(failed)
            )
        if failed:
            return chat.SendMsg(
                message.content + ' 部分完成\n注册成功：' + ", ".join(registered)
                + '\n注册失败：' + ", ".join(failed)
            )
        return chat.SendMsg(message.content + ' 完成\n当前群：\n' + ", ".join(self.config.group))

    def handle_disable_group_bot(self, chat, message):
        """处理 /关闭群机器人 指令：关闭群机器人并移除所有群组监听"""
        self.config.set_config(id='group_switch', new_content=False)
        for user in self.config.group:
            self.wx.RemoveListenChat(user)
        return chat.SendMsg(message.content + ' 完成\n' + '当前群：\n' + ", ".join(self.config.group))

    def handle_enable_welcome_msg(self, chat, message):
        """处理 /开启群机器人欢迎语 指令"""
        self.config.group_welcome = True
        self.config.set_config('group_welcome', True)
        return chat.SendMsg(message.content + ' 完成\n' + '当前群：\n' + ", ".join(self.config.group))

    def handle_disable_welcome_msg(self, chat, message):
        """处理 /关闭群机器人欢迎语 指令"""
        self.config.group_welcome = False
        self.config.set_config('group_welcome', False)
        return chat.SendMsg(message.content + ' 完成\n' + '当前群：\n' + ", ".join(self.config.group))

    def handle_welcome_msg_status(self, chat, message):
        """处理 /群机器人欢迎语状态 指令：返回当前欢迎语开关状态"""
        status = "开启" if self.config.group_welcome else "关闭"
        return chat.SendMsg(f"/群机器人欢迎语状态 为{status}\n当前群：\n" + ", ".join(self.config.group))

    def handle_change_welcome_msg(self, chat, message):
        """处理 /更改群机器人欢迎语为 指令：更新群欢迎语内容"""
        new_welcome = re.sub("/更改群机器人欢迎语为", "", message.content).strip()
        self.config.set_config('group_welcome_msg', new_welcome)
        return chat.SendMsg('群机器人欢迎语已更新\n' + self.config.group_welcome_msg)

    def handle_list_api_configs(self, chat, message):
        """处理 /查看接口列表 指令：返回所有接口配置的摘要"""
        lines = ["接口列表："]
        for i, cfg in enumerate(self.config.api_configs):
            mark = "▶ " if i == self.config.api_index else "   "
            lines.append(f"{mark}{i + 1}. {cfg.get('sdk', '')} | {cfg.get('model', '')} | {cfg.get('url', '')}")
        return chat.SendMsg('\n'.join(lines))

    def handle_select_api_config(self, chat, message):
        """处理 /选择接口 N 指令：切换到第 N 个接口配置（1-indexed）"""
        num_str = re.sub("/选择接口", "", message.content).strip()
        try:
            n = int(num_str)
        except ValueError:
            return chat.SendMsg("接口序号无效，请输入数字，如：/选择接口 2")
        idx = n - 1
        if idx < 0 or idx >= len(self.config.api_configs):
            return chat.SendMsg(f"接口 {n} 不存在，当前共 {len(self.config.api_configs)} 个接口")
        self.config.config['api_index'] = idx
        self.config.save_config()
        self.config.refresh_config()
        self.api = self._init_api()
        self.api_cache = {}   # 默认接口已切换，清除群组接口缓存
        cfg = self.config.api_configs[idx]
        return chat.SendMsg(f"已切换至接口 {n}\nSDK：{cfg.get('sdk', '')}\n模型：{cfg.get('model', '')}")

    def handle_change_prompt(self, chat, message):
        """处理 /更改AI设定为 指令：更新默认 prompt 文件内容"""
        if "AI设定" in message.content:
            new_prompt = re.sub("/更改AI设定为", "", message.content).strip()
        else:
            new_prompt = re.sub("/更改ai设定为", "", message.content).strip()
        # 写入默认 prompt 文件
        target = os.path.join(self.config.prompt_dir, f'{self.config.default_prompt}.md')
        try:
            with open(target, 'w', encoding='utf-8') as f:
                f.write(new_prompt)
            log(message=f"默认 prompt 已更新：{target}")
        except Exception as e:
            log(level="ERROR", message=f"更新默认 prompt 文件失败: {e}")
            return chat.SendMsg(f'AI设定更新失败：{e}')
        return chat.SendMsg(f'默认AI设定（{self.config.default_prompt}）已更新\n' + new_prompt)

    def handle_list_prompts(self, chat, message):
        """处理 /Prompt列表 指令：列出所有可用 Prompt 名称"""
        try:
            files = sorted([f[:-3] for f in os.listdir(self.config.prompt_dir) if f.endswith('.md')])
        except Exception:
            files = []
        if not files:
            return chat.SendMsg("当前没有可用的 Prompt")
        current = self.config.default_prompt
        lines = ["可用 Prompt 列表（* 为当前默认）："]
        for name in files:
            mark = "* " if name == current else "  "
            lines.append(f"{mark}{name}")
        return chat.SendMsg('\n'.join(lines))

    def handle_switch_prompt(self, chat, message):
        """处理 /切换Prompt xxx 指令：切换默认 Prompt"""
        name = re.sub("/切换Prompt", "", message.content).strip()
        if not name:
            return chat.SendMsg("请提供 Prompt 名称，如：/切换Prompt 默认")
        path = os.path.join(self.config.prompt_dir, f'{name}.md')
        if not os.path.exists(path):
            try:
                files = sorted([f[:-3] for f in os.listdir(self.config.prompt_dir) if f.endswith('.md')])
            except Exception:
                files = []
            available = '、'.join(files) if files else '（无）'
            return chat.SendMsg(f"Prompt「{name}」不存在\n可用 Prompt：{available}")
        self.config.set_config('default_prompt', name)
        return chat.SendMsg(f"默认 Prompt 已切换为：{name}")

    def handle_clear_memory(self, chat, message):
        """处理 /清除记忆 指令：清除管理员（当前聊天）的对话记忆"""
        if not self.memory_manager:
            return chat.SendMsg("记忆功能未初始化")
        self.memory_manager.clear_messages(self.config.cmd)
        return chat.SendMsg(f"已清除「{self.config.cmd}」的对话记忆")

    def handle_clear_user_memory(self, chat, message):
        """处理 /清除用户记忆 xxx 指令：清除指定用户/群的记忆"""
        name = re.sub("/清除用户记忆", "", message.content).strip()
        if not name:
            return chat.SendMsg("请提供用户或群名称，如：/清除用户记忆 张三")
        if not self.memory_manager:
            return chat.SendMsg("记忆功能未初始化")
        self.memory_manager.clear_messages(name)
        return chat.SendMsg(f"已清除「{name}」的对话记忆")

    def handle_clear_all_memory(self, chat, message):
        """处理 /清除全部记忆 指令：清除所有对话记忆"""
        if not self.memory_manager:
            return chat.SendMsg("记忆功能未初始化")
        count = self.memory_manager.clear_all_messages()
        return chat.SendMsg(f"已清除所有对话记忆（共 {count} 个会话）")

    def handle_image_recognition_status(self, chat, message):
        """处理 /图片识别状态 指令：返回私聊和群聊图片识别开关及接口信息"""
        def api_label(idx):
            if 0 <= idx < len(self.config.api_configs):
                cfg = self.config.api_configs[idx]
                return f"接口{idx + 1}（{cfg.get('model', '')}）"
            return f"接口{idx + 1}"
        chat_sw  = "开启" if self.config.chat_image_recognition_switch  else "关闭"
        group_sw = "开启" if self.config.group_image_recognition_switch else "关闭"
        lines = [
            "--- 图片识别状态 ---",
            f"私聊图片识别：{chat_sw}  识别接口：{api_label(self.config.chat_image_recognition_api)}",
            f"群聊图片识别：{group_sw}  识别接口：{api_label(self.config.group_image_recognition_api)}",
        ]
        return chat.SendMsg('\n'.join(lines))

    def handle_split_reply_status(self, chat, message):
        """处理 /拆分回复状态 指令：返回私聊和群聊拆分回复配置"""
        chat_sw  = "开启" if self.config.chat_split_reply_switch  else "关闭"
        group_sw = "开启" if self.config.group_split_reply_switch else "关闭"
        lines = [
            "--- 拆分多条回复状态 ---",
            f"私聊拆分回复：{chat_sw}  单条≤{self.config.chat_split_max_chars}字  最多{self.config.chat_split_max_count}条",
            f"群聊拆分回复：{group_sw}  单条≤{self.config.group_split_max_chars}字  最多{self.config.group_split_max_count}条",
        ]
        return chat.SendMsg('\n'.join(lines))

    def handle_new_friend_status(self, chat, message):
        """处理 /新好友状态 指令：返回新好友自动通过和自动回复配置"""
        accept = "开启" if self.config.new_friend_switch      else "关闭"
        reply  = "开启" if self.config.new_friend_reply_switch else "关闭"
        use_name = "是" if self.config.new_friend_remark_use_nickname else "否"
        prefix_time = "是" if self.config.new_friend_remark_prefix_timestamp else "否"
        suffix_time = "是" if self.config.new_friend_remark_suffix_timestamp else "否"
        msgs   = self.config.new_friend_msg if self.config.new_friend_msg else ["（无）"]
        lines  = [
            "--- 新好友状态 ---",
            f"自动通过好友申请：{accept}",
            f"自动回复新好友：{reply}",
            f"备注采用昵称：{use_name}",
            f"备注前缀：{self.config.new_friend_remark_prefix or '（空）'}  前缀加时间戳：{prefix_time}",
            f"备注后缀：{self.config.new_friend_remark_suffix or '（空）'}  后缀加时间戳：{suffix_time}",
            "自动回复消息：",
        ] + [f"  · {m}" for m in msgs]
        return chat.SendMsg('\n'.join(lines))

    def send_command_list(self, chat):
        """发送全量指令帮助列表"""
        commands = (
            '指令目录（发送对应指令查看详细）：\n'
            '/系统状态指令\n'
            '/用户管理指令\n'
            '/群组管理指令\n'
            '/Prompt管理指令\n'
            '/关键词指令\n'
            '/记忆指令\n'
            '/延迟指令\n'
            '/暂停恢复指令\n'
            '/图片识别指令\n'
            '/拆分回复指令\n'
            '/新好友指令\n'
            '/接口指令\n'
            '/计数器指令\n'
            '作者:https://www.siver.top'
        )
        return chat.SendMsg(commands)

    # ----------------------------------------------------------
    # 群组辅助功能
    # ----------------------------------------------------------

    def find_new_group_friend(self, msg, flag):
        """
        从系统消息中解析出新加入群聊的成员昵称。

        :param msg:  系统消息文本
        :param flag: 引号索引（1=扫码加入，3=邀请加入）
        :return:     新成员昵称字符串
        """
        text = msg
        try:
            first_quote_content = text.split('"')[flag]
        except Exception:
            first_quote_content = text.split('"')[1]
        return first_quote_content

    def _send_group_welcome_once(self, chat, new_friend):
        """发送一条群新人欢迎语；发送异常转成失败结果，不穿透到回调最外层。

        只包住 SendMsg 本身：调用方（message_handle_callback 的 system 分支）
        会按 if not result 消费失败结果并告警，这里不能吞掉其它程序错误。
        """
        try:
            return chat.SendMsg(msg=self.config.group_welcome_msg, at=new_friend)
        except Exception as e:
            log(level="ERROR", message=f"{chat.who} 发送群新人欢迎语失败: {e}")
            return SendOutcome.failure(f"群新人欢迎语发送失败：{e}")

    def send_group_welcome_msg(self, chat, message):
        """
        处理群系统消息，若检测到新成员加入则按概率发送欢迎语。

        :param chat:    聊天窗口子对象
        :param message: 系统消息对象
        :return:        发送结果
        """
        result = True
        log(message=f"{chat.who} 系统消息:" + message.content)

        if "加入群聊" in message.content and random.random() < self.config.group_welcome_random:
            # 扫码加入群聊
            new_friend = self.find_new_group_friend(message.content, 1)
            log(message=f"{chat.who} 新群友:" + new_friend)
            time.sleep(5)
            result = self._send_group_welcome_once(chat, new_friend)

        elif "加入了群聊" in message.content and random.random() < self.config.group_welcome_random:
            # 被邀请加入群聊
            new_friend = self.find_new_group_friend(message.content, 3)
            log(message=f"{chat.who} 新群友:" + new_friend)
            time.sleep(5)
            result = self._send_group_welcome_once(chat, new_friend)

        return result

    # ----------------------------------------------------------
    # 新好友处理
    # ----------------------------------------------------------

    def is_media_path(self, s: str) -> bool:
        """
        判断字符串是否为「可自动作为文件发送的本地文件」完整路径。
        支持图片、视频、音频、文档、压缩包等常见后缀（见 SEND_FILE_EXTENSIONS），
        支持 Windows（C:\\...）和 Unix（/home/...）风格绝对路径。

        ⚠ 只用于消息类发送（关键词回复 / 定时消息 / 随机定时消息 / 新好友招呼语），
          朋友圈图片/视频不走这里（朋友圈只支持图片和视频）。

        :param s: 待判断的字符串
        :return:  True 表示是文件路径，False 则不是
        """
        text = str(s or '').strip()
        if not text.lower().endswith(SEND_FILE_EXTENSIONS):
            return False
        return bool(_SEND_FILE_PATH_RE.match(text))

    @staticmethod
    def _remark_unit_len(text):
        """按微信备注近似限制计算长度：ASCII 算 1，中文和特殊字符算 2。"""
        total = 0
        for ch in str(text or ""):
            try:
                total += len(ch.encode("gbk"))
            except UnicodeEncodeError:
                total += 2
        return total

    @classmethod
    def _truncate_remark_units(cls, text, max_units):
        """按备注长度单位裁剪，不截断字符。"""
        if max_units <= 0:
            return ""
        result = []
        used = 0
        for ch in str(text or ""):
            try:
                unit = len(ch.encode("gbk"))
            except UnicodeEncodeError:
                unit = 2
            if used + unit > max_units:
                break
            result.append(ch)
            used += unit
        return "".join(result)

    def build_new_friend_remark(self, nickname):
        """根据面板配置生成新好友备注，并裁剪到微信备注长度限制内。"""
        max_units = 32
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        leading = timestamp if self.config.new_friend_remark_prefix_timestamp else ""
        prefix = str(self.config.new_friend_remark_prefix or "")
        name = str(nickname or "") if self.config.new_friend_remark_use_nickname else ""
        suffix = str(self.config.new_friend_remark_suffix or "")
        trailing = timestamp if self.config.new_friend_remark_suffix_timestamp else ""

        fixed_left = leading + prefix
        fixed_right = suffix + trailing
        fixed_units = self._remark_unit_len(fixed_left) + self._remark_unit_len(fixed_right)
        if fixed_units <= max_units:
            name_units = max_units - fixed_units
            remark = fixed_left + self._truncate_remark_units(name, name_units) + fixed_right
        else:
            trailing_units = self._remark_unit_len(trailing)
            available_main_units = max(0, max_units - trailing_units)
            main = self._truncate_remark_units(fixed_left + suffix, available_main_units)
            remark = main + trailing
        if not remark:
            fallback = str(nickname or "新好友") if self.config.new_friend_remark_use_nickname else "新好友"
            remark = self._truncate_remark_units(fallback, max_units)
        return remark

    def Pass_New_Friends(self):
        """
        检测并批量通过新好友请求，通过后按需自动发送打招呼消息。
        - new_friend_switch：自动通过新好友申请
        - new_friend_reply_switch：通过后自动回复消息
        消息中若包含图片/视频路径则以文件形式发送，否则以文字发送。
        """
        NewFriends = self.wx.GetNewFriends(acceptable=True)
        time.sleep(1)
        if len(NewFriends) != 0:
            log(message="以下是新朋友：\n" + str(NewFriends))
            for new in NewFriends:
                new_name = self.build_new_friend_remark(new.name)
                tags = self.config.new_friend_tags if self.config.new_friend_tags else None
                new.accept(remark=new_name, tags=tags)  # 接受好友请求并设置备注和标签
                log(message="已通过" + new_name + "的好友请求")
                self.wx.SwitchToChat()       # 通过请求后切换回聊天页面
                time.sleep(5)
                if self.config.new_friend_reply_switch:
                    for msg in self.config.new_friend_msg:
                        if self.is_media_path(msg):
                            self.wx.SendFiles(who=new_name, filepath=msg)
                        else:
                            self.wx.SendMsg(who=new_name, msg=msg)
                        self.config.human_delay()  # 模拟人工操作延迟（可在面板配置）
                # 发送完毕后跳转到文件传输助手，再切换到通讯录准备处理下一个
                self.wx.ChatWith(who='文件传输助手')
                time.sleep(1)
                self.wx.SwitchToContact()
            time.sleep(1)
        self.wx.SwitchToChat()  # 所有好友处理完毕后切回聊天页面
        time.sleep(1)

    # ----------------------------------------------------------
    # 消息监听模式
    # ----------------------------------------------------------

    def listen_mode(self):
        """
        普通监听模式（白名单模式）：
        获取所有监听窗口的最新消息并逐一处理。
        """
        messages_dict = self.wx.GetListenMessage()
        for chat in messages_dict:
            for message in messages_dict.get(chat, []):
                self.process_message(chat, message)

    def new_msg_get_plus(self, chat_records):
        """
        从聊天记录中过滤出"上一条自己发送消息之后"的新消息：
        1. 过滤掉 SYS 与 Recall 类型消息（保留 Time 消息）
        2. 若存在 Self 消息：定位最新 Self 消息，取其后的记录；
           若后续有 Time 消息，则取最新 Time 消息之后的对方消息。
        3. 若无 Self 消息：定位最新 Time 消息，取其后的对方消息；
           若也无 Time 消息，返回全部过滤后的消息。

        :param chat_records: wx.GetAllMessage() 返回的消息列表
        :return:             过滤后的新消息列表
        """
        # 步骤1：过滤掉 SYS 与 Recall 消息
        filtered = [msg for msg in chat_records if msg[0] not in ("SYS", "Recall")]

        if any(msg[0] == "Self" for msg in filtered):
            # 找到最新 Self 消息的索引（最后一次出现）
            latest_self_index = None
            for idx, msg in enumerate(filtered):
                if msg[0] == "Self":
                    latest_self_index = idx
            post_self = filtered[latest_self_index + 1:]

            # 在 Self 之后查找最新 Time 消息
            latest_time_index = None
            for idx, msg in enumerate(post_self):
                if msg[0] == "Time":
                    latest_time_index = idx

            if latest_time_index is not None:
                post_time = post_self[latest_time_index + 1:]
                return [msg for msg in post_time if msg[0] not in ("Self", "Time")]
            else:
                return post_self
        else:
            # 无 Self 消息，直接查找最新 Time 消息
            latest_time_index = None
            for idx, msg in enumerate(filtered):
                if msg[0] == "Time":
                    latest_time_index = idx

            if latest_time_index is not None:
                post_time = filtered[latest_time_index + 1:]
                return [msg for msg in post_time if msg[0] not in ("Self", "Time")]
            else:
                return filtered

    def next_message_handle(self):
        """
        在全局监听模式中辅助获取新消息，防止消息遗漏。
        获取当前窗口全部消息后调用 new_msg_get_plus 过滤出真正的新消息。

        :return: 过滤后的新消息列表
        """
        AllMessage = self.wx.GetAllMessage()           # 获取当前窗口所有消息
        new_msg    = self.new_msg_get_plus(AllMessage) # 过滤出上一条 Self 消息之后的新消息
        return new_msg

    def add_chat_to_listen(self, chat):
        """
        将指定会话加入全局动态监听列表，并向 wxautox 注册监听回调。

        :param chat: 会话昵称（字符串）
        :return:     校验成功的子窗口对象；失败返回 None
        """
        sub_chat = self._add_and_verify_subwindow(chat)
        if not sub_chat:
            return None

        if self.is_chat_listened(chat):
            return sub_chat

        log(message=chat + ' 已添加监听，正在加入动态监听列表')
        self.all_Mode_listen_list.append([chat, time.time()])
        log(message='当前全局模式动态监听列表：' + str(self.all_Mode_listen_list))
        return sub_chat

    def is_chat_listened(self, chat):
        """
        判断指定会话是否已在全局动态监听列表中。

        :param chat: 会话昵称（字符串）
        :return:     True 表示已监听，False 表示未监听
        """
        return any(listen_chat[0] == chat for listen_chat in self.all_Mode_listen_list)

    def ALLListen_mode(self, last_time, timeout=10):
        """
        全局监听模式主函数（黑名单模式）。
        包含三个内部子函数，分别处理：
        - 新消息获取（旧版 process_new_messages，已切换为 get_next_new_message）
        - 监听中会话的消息更新（process_listen_messages）
        - 超时会话的自动移除（remove_timeout_listen）

        :param last_time: 上次执行超时检测的时间戳
        :param timeout:   超时检测间隔（秒），默认 10 秒
        :return:          更新后的 last_time
        """

        def process_new_messages():
            """
            【旧版，当前未启用】
            通过 GetNextNewMessage 获取新消息，过滤黑名单后添加监听并处理。
            """
            messages_new = self.wx.GetNextNewMessage()
            for chat, messages in messages_new.items():
                if chat in self.config.listen_list:  # 黑名单过滤
                    log(message=f'{chat} 为黑名单用户，跳过处理')
                    continue
                for message in messages:
                    if message.attr == 'friend':
                        new_msg = self.next_message_handle()
                        if not self.is_chat_listened(chat):
                            _sub_chat = self.add_chat_to_listen(chat)
                        else:
                            log(message=chat + '在监听列表')
                            _sub_chat = self._get_verified_subwindow(chat)
                            if not _sub_chat:
                                self._remove_dynamic_listen_chat(chat)
                        for msg in new_msg:
                            if _sub_chat:
                                self.process_message(_sub_chat, msg)
                            else:
                                log(level="ERROR", message=f"{chat} 未获取到子窗口，跳过本次消息处理")

        def process_listen_messages():
            """
            【旧版，当前未启用】
            获取所有已监听会话的新消息，更新最新消息时间戳，并逐条处理。
            """
            messages_dict = self.wx.GetListenMessage()
            for chat, messages in messages_dict.items():
                for message in messages:
                    # 更新对应会话的最新消息时间戳
                    for listen_chat in self.all_Mode_listen_list:
                        if listen_chat[0] == chat.who:
                            log(message=chat.who + " 对话最新消息时间已更新")
                            listen_chat[1] = time.time()
                            break
                    self.process_message(chat, message)

        def remove_timeout_listen(chat_time_out=600):
            """
            移除超过指定时长未收到消息的监听会话（默认 10 分钟）。
            使用列表副本遍历，避免遍历时修改原列表导致跳过元素。
            """
            for listen_chat in self.all_Mode_listen_list[:]:  # 遍历副本，安全删除
                if time.time() - listen_chat[1] >= chat_time_out:
                    log(message=str(listen_chat[0]) + '对话超时，正在删除监听')
                    if self._remove_listen_chat_verified(listen_chat[0]):
                        self.all_Mode_listen_list.remove(listen_chat)

        def get_next_new_message():
            """
            【当前启用】通过 GetNextNewMessage 获取新消息（V2 版本接口）。
            黑名单过滤后，仅处理 friend 类型的私聊消息。
            """
            Next_callback_down_map = {}  # {msg.id: save_path}
            def Next_callback(msg):
                nonlocal Next_callback_down_map
                # 排除群聊再下载
                if self.wx.chat_type != 'group':
                    log(message=f'收到私聊消息：{msg.sender}: {msg.content}')
                    # Next回调即为私聊
                    _any_img_enabled = (self.config.chat_image_recognition_switch)
                    try:
                        if _any_img_enabled:
                            if msg.type == 'image':
                                _path = msg.download()
                                if _path:
                                    Next_callback_down_map[msg.id] = _path
                                else:
                                    log("ERROR", "Next_callback下载图片出错，请尝试将windows屏幕设置的缩放调整为100%后重试")
                            elif msg.type == 'quote':
                                _path = msg.download_quote_image()
                                if _path:
                                    Next_callback_down_map[msg.id] = _path
                                else:
                                    log("INFO", "引用内容不是图片或视频")
                            elif msg.type == 'voice':
                                try:
                                    _voice_content = msg.to_text()
                                    if _voice_content:
                                        Next_callback_down_map[msg.id] = _voice_content
                                    else:
                                        log("WARNING", "消息自动语音转文字失败")
                                except Exception as e:
                                    log("WARNING", "消息自动语音转文字失败")
                    except Exception as e:
                        log(level="ERROR", message=f"Next_callback下载图片出错，请尝试将windows屏幕设置的缩放调整为100%后重试: {e}")
                else:
                    log('INFO', '私聊全局监听收到群聊消息，跳过')

            messages_new = self.wx.GetNextNewMessage(filter_mute=self.config.AllListen_filter_mute, callback=Next_callback)
            chat      = messages_new.get('chat_name')
            chat_type = messages_new.get('chat_type')
            msgs      = messages_new.get('msg')

            # 黑名单过滤：全局模式下 listen_list 为黑名单
            if chat in self.config.listen_list:
                log(message=f'{chat} 为黑名单用户，跳过处理')
                return

            if msgs:
                for msg in msgs:
                    if msg.type == 'image':
                        if msg.id in Next_callback_down_map:
                            msg.content = str(Next_callback_down_map[msg.id])
                    elif msg.type == 'quote':
                        if msg.id in Next_callback_down_map:
                            msg.content = msg.content+"+引用的图片:"+str(Next_callback_down_map[msg.id])
                    elif msg.type == 'voice':
                        if msg.id in Next_callback_down_map:
                            msg.content = str(Next_callback_down_map[msg.id])
                    # 仅处理 friend 类型的私聊消息，排除群聊
                    if msg.attr == 'friend' and chat_type != 'group':
                        # 接收计数与“最近消息”更新：与 message_handle_callback 的 friend 分支保持一致
                        self.msg_received_count += 1
                        self.last_msg_time   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        self.last_msg_sender = msg.sender
                        message_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

                        # 自定义规则转发：必须在 add_chat_to_listen 之前执行
                        # msg.forward() 依赖主窗口上下文，加入监听后上下文切换到子窗口会失效
                        if self.config.custom_forward_switch:
                            try:
                                import types as _types
                                self._handle_custom_forward(_types.SimpleNamespace(who=chat), msg)
                            except Exception as _fwd_e:
                                log(level="ERROR", message=f"自定义转发处理出错: {_fwd_e}")

                        if not self.is_chat_listened(chat):
                            _sub_chat = self.add_chat_to_listen(chat)
                        else:
                            log(message=chat + '在监听列表')
                            _sub_chat = self._get_verified_subwindow(chat)
                            if not _sub_chat:
                                self._remove_dynamic_listen_chat(chat)
                        buffered = False
                        if _sub_chat:
                            if self._should_buffer_message(_sub_chat, msg):
                                # 全局监听的首条消息同样进合并缓冲：否则它会先回复，
                                # 之后同一个人再发消息才走回调进缓冲，两条路径不一致。
                                # 用子窗口对象入缓冲，flush 时才有窗口可发送。
                                self._buffer_message(_sub_chat, msg)
                                buffered = True
                            else:
                                result = self.process_message(_sub_chat, msg)
                                if not result:
                                    # 失败与部分失败（SendOutcome.partial 的布尔值是 False）都按现有规则告警；
                                    # 被过滤、无需回复等正常分支返回 True，不会误报成发送失败
                                    self.is_err(
                                        self.wx.nickname + " wxbot全局监听处理新消息失败！",
                                        f"{message_time} 类型：{msg.type} 属性：{msg.attr} 窗口：{chat} "
                                        f"发送人：{msg.sender} - 消息：{msg.content}\n"
                                        + ReplyCountStore.send_result_message(result),
                                    )
                        else:
                            log(level="ERROR", message=f"{chat} 未获取到子窗口，跳过本次消息处理")

                        # 写入记忆：与 message_handle_callback 一致，放在处理之后。
                        # 放在处理之前会让当前消息先进入历史、又被当成本次输入传给 AI，
                        # 同一条消息进 AI 两次（此处不经过 message_handle_callback）。
                        # 合并缓冲的消息不在这里写：由 _flush_merged 在处理之后逐条补写。
                        if not buffered and self.config.memory_switch and self.memory_manager:
                            try:
                                self.memory_manager.save_message(
                                    chat_name=chat,
                                    sender=msg.sender,
                                    content=msg.content,
                                    msg_type=msg.type,
                                    msg_attr=msg.attr,
                                    max_count=self.config.memory_max_count,
                                    message_time=message_time,
                                )
                            except Exception as e:
                                log(level="WARNING", message=f"写入记忆失败: {e}")

        # ---- 全局监听模式主流程 ----
        # 当前仅启用 get_next_new_message（混合模式中的新消息拉取）
        # process_new_messages() 和 process_listen_messages() 已注释备用
        get_next_new_message()

        # 每隔 timeout 秒执行一次超时会话清理
        if time.time() - last_time >= timeout:
            remove_timeout_listen()
            return time.time()
        return last_time

    # ----------------------------------------------------------
    # 机器人生命周期
    # ----------------------------------------------------------

    def get_status(self):
        """
        暴露机器人运行状态数据，供 Web 状态面板采集。
        :return: 包含运行参数和统计数据的字典
        """
        uptime_secs = int((datetime.now() - self.start_time).total_seconds())
        hours, rem  = divmod(uptime_secs, 3600)
        minutes, seconds = divmod(rem, 60)
        uptime_str  = f"{hours}h {minutes}m {seconds}s"

        wx_nickname = None
        if self.wx:
            try:
                wx_nickname = self.wx.nickname
            except Exception:
                pass

        scheduled_enabled = sum(
            1 for t in self.config.scheduled_msg_list if t.get('enabled', True)
        ) if self.config.scheduled_msg_list else 0

        return {
            "running":            self.run_flag,
            "version":            self.ver,
            "start_time":         self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "uptime":             uptime_str,
            "wx_nickname":        wx_nickname,
            "api_sdk":            self.config.api_sdk,
            "model":              self.api.DS_NOW_MOD,
            "api_index":          self.config.api_index + 1,
            "api_total":          len(self.config.api_configs),
            "listen_mode":        "黑名单" if self.config.AllListen_switch else "白名单",
            "listen_count":       len(self.config.listen_list),
            "chat_listen_only":   self.config.chat_listen_only,
            "group_switch":       self.config.group_switch,
            "group_listen_only":  self.config.group_listen_only,
            "group_count":        len(self.config.group),
            "msg_received":       self.msg_received_count,
            "msg_replied":        self.msg_replied_count,
            "last_msg_time":      self.last_msg_time,
            "last_msg_sender":    self.last_msg_sender,
            "callback_is_die":    self.callback_is_die,
            "scheduled_switch":   self.config.scheduled_msg_switch,
            "scheduled_count":    scheduled_enabled,
            "chat_keyword_switch":   self.config.chat_keyword_switch,
            "group_keyword_switch":  self.config.group_keyword_switch,
            "group_keyword_at_only": self.config.group_keyword_at_only,
            "keyword_reply_quote": self.config.keyword_reply_quote,
            "group_keyword_reply_at_msg": self.config.group_keyword_reply_at_msg,
            "keyword_count":         len(self.config.keyword_dict),
            "memory_switch":         self.config.memory_switch,
            "memory_context_count":  self.config.memory_context_count,
            "reply_delay_switch":    self.config.reply_delay_switch,
            "reply_delay_min":       self.config.reply_delay_min,
            "reply_delay_max":       self.config.reply_delay_max,
            "chat_max_round_switch": self.config.chat_max_round_switch,
            "chat_max_round_default": self.config.chat_max_round_default,
            "chat_max_round_reset_days": self.config.chat_max_round_reset_days,
            "pause_chat_reply":      self.config.chat_listen_only,
            "pause_group_reply":     self.config.group_listen_only,
        }

    # ------------------------------------------------------------------
    # 停止信号与统一收尾
    # ------------------------------------------------------------------

    def request_stop(self):
        """置停止信号：幂等、可在任意线程调用、绝不碰 wxautox。

        面板停止 / 定时停止 / BotLifecycle 停止都先走这里。实例还没构造出来、
        监听还没注册时，"停止"唯一能做的就是留下这个信号 —— 由 `main()` 在初始化
        结束处以及最后的收尾统一兑现。
        """
        self._stop_event.set()
        self.run_flag = False

    def stop_requested(self):
        """是否已收到停止请求。

        ⚠ 初始化结束后必须查它再决定要不要开跑：否则"初始化期间点了停止"会被
          "初始化完成"整个抹掉（历史上 `self.run_flag = True` 就在这里无条件执行）。
        """
        return self._stop_event.is_set()

    def _nickname(self):
        """安全取微信昵称：wx 可能没初始化/已失效，取不到时用占位名，别让日志抛异常。"""
        try:
            if self.wx is not None:
                return self.wx.nickname
        except Exception:
            pass
        return '未初始化'

    def shutdown(self, reason=''):
        """统一收尾：无论从哪条路径退出，都走这里。

        四条路径共用同一份收尾实现：
          1. 初始化部分成功（init_wx_listeners 抛异常，可能已经启动了监听）；
          2. 主动停止（面板 / 定时启停 / BotLifecycle）；
          3. 主循环异常退出；
          4. 主循环正常退出。

        幂等且不丢先后：重复调用不会重复 StopListening；而"停止请求先到、初始化后完成"
        这种顺序颠倒的情况，会在初始化真正把监听启动起来之后被收尾补停。

        :return: True=没有残留监听（本来没启动 / 已成功停掉）；False=StopListening 抛异常。
        """
        self.run_flag = False
        # 停止时丢弃未回复的合并缓冲：只清内存，不做延迟回复
        if getattr(self, '_merge_buffers', None):
            dropped = self._clear_merge_buffers()
            log(level="WARNING", message=f"[合并回复] 机器人停止，丢弃 {dropped} 组未回复的缓冲")
        try:
            scheduler = getattr(self, 'scheduler', None)
            if scheduler is not None:
                scheduler.clear()
        except Exception as e:
            log(level="WARNING", message=f'清理定时任务失败: {e}')
        return self._stop_listening(reason)

    def _stop_listening(self, reason=''):
        """停掉 wxautox 监听；监听从未启动/客户端还没造出来时不动 wxautox。

        调用前先把标志清掉：即使 StopListening 抛异常也不会漏掉后续的补停
        （异常时把标志放回去，留给下一次收尾重试）。
        """
        with self._wx_lock:
            if self.wx is None or not self._listening_started:
                return True
            self._listening_started = False
        try:
            self.wx.StopListening()
            log(level="WARNING", message=f'siver_wxbot已停止监听（{reason or "退出"}）')
            return True
        except Exception as e:
            with self._wx_lock:
                self._listening_started = True   # 没停成功，别丢掉这个事实
            log(level="ERROR", message=f'StopListening 执行失败（{reason or "退出"}）: {e}')
            return False

    def stop_wxbot(self):
        """安全停止机器人（对外保持原有语义）：置停止信号 + 立即收尾。

        停止监听、清掉本实例注册的定时任务，主循环随之退出；线程真正结束由
        BotLifecycle 负责等待（它确认线程退出后才清空实例引用）。

        :return: True=已无残留监听（成功停掉，或本来就没启动）；False=StopListening 抛异常。
        """
        self.request_stop()
        return self.shutdown('主动停止')

    # ------------------------------------------------------------------
    # 配置应用：把磁盘新配置推给运行中的实例，并如实说明生效范围
    # ------------------------------------------------------------------

    def apply_config(self, changed_fields=None):
        """把磁盘上的新配置应用到运行中的实例，并**如实说明生效范围**。

        生效约定见 config_apply.py（面板、机器人与验收脚本共用同一份分类）：

        · hot         —— refresh_config() 同步属性，立即生效；
        · api_rebuild —— 额外重建默认 API 客户端（换 SDK 类型时只刷新属性不够）
                         并清空群组专属接口缓存；
        · restart     —— 监听注册 / 定时任务注册只在启动初始化阶段做，
                         这里只如实上报"未生效"，绝不假装已全部应用。

        :param changed_fields: 本次真正改动的配置键。面板已有"保存前/后"的磁盘差异，
                               直接传进来最准；传 None 时用磁盘快照自行推断。
        :return: dict(changed_fields, hot_fields, api_fields, restart_fields,
                      restart_labels, api_rebuilt, errors)
        """
        result = {
            'changed_fields': [],
            'hot_fields': [],
            'api_fields': [],
            'restart_fields': [],
            'restart_labels': '',
            'api_rebuilt': False,
            'errors': [],
        }
        before = copy.deepcopy(getattr(self.config, '_loaded_snapshot', {}) or {})

        # 面板已经算好了改动字段：先分类，这样即使随后重载配置失败，
        # "哪些改动必须重启才生效"这条信息也不会丢（否则面板会误报 needs_restart=False）。
        plan = config_apply.summary(changed_fields) if changed_fields is not None else None

        try:
            self.config.refresh_config()
        except Exception as e:
            result['errors'].append(f'重载配置失败: {e}')
            log(level="ERROR", message=f'应用新配置失败（重载配置出错）: {e}')
            if plan is not None:
                result['changed_fields'] = sorted(set(changed_fields))
                result['hot_fields'] = plan['hot_fields']
                result['api_fields'] = plan['api_fields']
                result['restart_fields'] = plan['restart_fields']
                result['restart_labels'] = plan['restart_labels']
            return result

        if changed_fields is None:
            after = getattr(self.config, '_loaded_snapshot', {}) or {}
            changed_fields = {
                k for k in set(before) | set(after) if before.get(k) != after.get(k)
            }

        if plan is None:
            plan = config_apply.summary(changed_fields)
        result['changed_fields'] = sorted(set(changed_fields))
        result['hot_fields'] = plan['hot_fields']
        result['api_fields'] = plan['api_fields']
        result['restart_fields'] = plan['restart_fields']
        result['restart_labels'] = plan['restart_labels']

        if plan['api_fields']:
            # 默认接口客户端是启动时按 api_sdk 实例化的对象：SDK 类型 / Key / URL / 模型
            # 变了都必须重建，否则"属性刷新了、调用还在用旧客户端"。
            try:
                self.api = self._init_api()
                self.api_cache = {}     # 群组专属接口缓存同样按新配置重建
                result['api_rebuilt'] = True
                log(message=f"默认接口客户端已按新配置重建（{self.config.api_sdk or '未配置'}）")
            except Exception as e:
                result['errors'].append(f'重建默认接口客户端失败: {e}')
                log(level="ERROR", message=f'重建默认接口客户端失败: {e}')

        if plan['restart_fields']:
            log(level="WARNING", message=(
                "以下改动需重启才生效（监听注册 / 定时任务注册只在启动时做）："
                f"{plan['restart_labels']}"
            ))
        return result

    def main(self):
        """
        机器人主运行函数：
        - 校验 wxautox 授权
        - 初始化微信监听器
        - 进入主循环，依次执行：离线检测、新好友检测、全局监听/定时任务
        """
        # self.key_pass(2025, 6, 20, 0, 0, 0)  # 打包保护锁（按需启用）
        log(message=f"wxbot\n版本: wxbot_{self.ver}\n作者: https://www.siver.top\n")

        # 激活授权校验
        if self.wxautox_activate_check():
            log(message="wxautox已激活")
        else:
            log(level="ERROR", message="wxautox未激活，请购买激活后再运行程序！！")
            log(level="ERROR", message="购买激活地址：https://www.siverking.online/static/img/siver_wx.jpg")
            log(level="ERROR", message="wxautox未激活，请购买激活后再运行程序！！")
            log(level="ERROR", message="购买激活地址：https://www.siverking.online/static/img/siver_wx.jpg")
            log(level="ERROR", message="wxautox未激活，请购买激活后再运行程序！！")
            log(level="ERROR", message="购买激活地址：https://www.siverking.online/static/img/siver_wx.jpg")
            return False

        # 初始化微信监听器
        init_ok = False
        try:
            self.init_wx_listeners()
            log(message=f"UI面板状态更新完成")

            wait_time      = 1   # 主循环每 1 秒轮询一次（合并回复的窗口精度靠它）
            check_interval = 30  # 每 30 次循环（= 30 秒）执行一次离线检测
            check_counter      = 0
            check_new_counter  = 0
            alllisten_counter  = 0   # 全局监听仍保持原来的 3 秒节奏
            last_time          = time.time()
            log(message='siver_wxbot初始化完成，开始监听消息(作者:https://www.siver.top)')
            init_ok = True
        except Exception as e:
            print(traceback.format_exc())
            log(level="ERROR", message=str(e) + "\n 初始化微信监听器失败，请检查微信是否启动登录正确，微信主窗口是否开着")
            log(level="ERROR", message=str(e) + "\n 请尝试退出wx再重新登录后再启动")
            log(level="ERROR", message=str(e) + "\n 若重启wx还是不行，就请重启整个面板程序，面板和wx都重启了还不行就请进入面板右上角文档检查环境要求，wx版本是否匹配,4.1.9 ~ 4.1.15.56")
            log(level="ERROR", message=str(e) + "\n 若是wx 4.1.9.35往后版本有初始化问题，请到wx群内@Siver")
            log(level="ERROR", message=str(e) + "\n 若以上情况都检查完没有问题，那大概率为wx本身或者windows系统不稳定导致的，重启程序即可，若是一直这样，如果您是虚拟机就请分配更多性能，若是实体机可以联系作者询问")
            self.run_flag = False

        # ⚠ 这里原先无条件 self.run_flag = True：初始化要好几秒，期间收到的停止请求
        #   （面板点了停止 / 定时停止到点）会被这一行整个抹掉 —— 表现为"点了停止却继续跑"。
        #   现在只有"初始化成功且期间没有停止请求"才真正开跑。
        if self.stop_requested():
            self.run_flag = False
            if init_ok:
                log(level="WARNING", message='初始化期间收到停止请求，不再进入主循环，立即收尾')
        elif init_ok:
            self.run_flag = True
        else:
            self.run_flag = False

        # 主循环
        #
        # 整个循环包在 try/finally 里：初始化部分成功、主动停止、主循环异常、正常退出
        # 四条路径最后都会走到同一个收尾（shutdown → StopListening），
        # 不再出现"日志写着正在退出监听，实际监听还挂着"的情况。
        try:
            while self.run_flag and not self.stop_requested():
                try:
                    # ---- 离线检测模块（每 check_interval 次循环执行一次）----
                    check_counter += 1
                    if check_counter >= check_interval:
                        try:
                            if self.callback_is_die:
                                # 回调函数已出错，停止所有监听并退出主循环
                                self._stop_listening('回调函数出错')
                                log(level="ERROR", message="检测到回调函数出错!!已停止所有监听并跳出主线程!!")
                                break
                            if not self.check_wechat_window():
                                # 微信离线，阻塞等待人工处理；收尾统一交给最外层 finally
                                self.is_err(f"{self._nickname()} wxbot监听出错！！微信可能已被弹出登录！！在线检查失败！！")
                                self.request_stop()
                                log(level="ERROR", message=f"微信 {self._nickname()} 已被弹出登录！！请检查微信是否登录！！")
                                break
                        except Exception as e:
                            self.is_err(f"{self._nickname()} wxbot监听出错！！微信可能已被弹出登录！！在线检查失败！！", e)
                            self.request_stop()
                            log(level="ERROR", message=f"微信 {self._nickname()} 已被弹出登录！！请检查微信是否登录！！")
                            break
                        check_counter = 0

                    # ---- 新好友检测模块（随机检查，间隔由配置决定）----
                    if self.config.new_friend_switch:
                        # 将秒数阈值除以循环周期得到循环次数（取整，最小1次）
                        check_new_friend_time_MIN = max(1, int(self.config.new_friend_check_min / wait_time))
                        check_new_friend_time_MAX = max(check_new_friend_time_MIN, int(self.config.new_friend_check_max / wait_time))
                        check_new_counter += 1
                        if check_new_counter >= random.randint(check_new_friend_time_MIN, check_new_friend_time_MAX):
                            try:
                                self.Pass_New_Friends()
                                # log(message="检查新好友完成")
                            except Exception as e:
                                self.is_err(f"{self._nickname()}  智能客服bot监听新好友出错！！请检查程序！！", e)
                            check_new_counter = 0

                    # ---- 全局监听模式（黑名单模式下启用）----
                    # 主循环从 3 秒改成 1 秒后，这里用计数器保持"每 3 秒一次"：
                    # 否则 ALLListen_mode 的调用频率会翻三倍，CPU 白白上升。
                    alllisten_counter += 1
                    if alllisten_counter >= 3:
                        alllisten_counter = 0
                        if self.config.AllListen_switch:
                            try:
                                last_time = self.ALLListen_mode(last_time=last_time)
                            except Exception as e:
                                if not self.run_flag:
                                    log(level="ERROR", message=str(e) + "\n全局模式出错！！请检查程序！！")

                    # ---- 多条消息缓冲合并回复（到期/满条数才回复）----
                    self._check_merge_buffers()

                    # ---- 定时任务执行（定时消息 / 定时朋友圈）----
                    # 只跑本实例调度器里的任务：模块级全局 schedule 是进程级的，
                    # 旧实例残留的任务会被这里误执行（任务仍绑定已停掉的旧实例）。
                    if self.config.scheduled_msg_switch or self.config.scheduled_moments_switch:
                        self.scheduler.run_pending()

                    # ---- 随机定时朋友圈模块 ----
                    if self.config.random_moments_switch:
                        try:
                            self._check_random_moments()
                        except Exception as e:
                            log(level="ERROR", message=f"随机定时朋友圈模块出错：{e}")
                    else:
                        self._random_moments_state = {}  # 开关关闭时清空缓存

                    # ---- 随机定时消息模块 ----
                    if self.config.random_msg_switch:
                        try:
                            self._check_random_msg()
                        except Exception as e:
                            log(level="ERROR", message=f"随机定时消息模块出错：{e}")
                    else:
                        self._random_msg_state = {}  # 开关关闭时清空缓存

                    # ---- 随机朋友圈点赞模块 ----
                    if self.config.moments_like_switch:
                        if self._moments_like_next_time is None:
                            # 在 [min, max] 分钟范围内随机选取下次触发间隔
                            lo = max(1, self.config.moments_like_min)
                            hi = max(lo, self.config.moments_like_max)
                            delay_min = random.randint(lo, hi)
                            self._moments_like_next_time = datetime.now() + timedelta(minutes=delay_min)
                            log(message=f"随机朋友圈点赞：下次触发 {self._moments_like_next_time.strftime('%H:%M:%S')}（{delay_min} 分钟后）")
                        elif datetime.now() >= self._moments_like_next_time:
                            try:
                                self._do_moments_like()
                            except Exception as e:
                                log(level="ERROR", message=f"随机朋友圈点赞模块出错：{e}")
                            self._moments_like_next_time = None  # 执行后重置，下次循环重新生成间隔
                    else:
                        self._moments_like_next_time = None  # 开关关闭时重置计时器

                except Exception as e:
                    self.is_err(
                        self._nickname() + " wxbot消息处理出错！！微信可能已被弹出登录！！处理监听失败！！",
                        e,
                    )
                    self.run_flag = False

                time.sleep(wait_time)

            log(level="WARNING", message='siver_wxbot主线程安全退出，正在退出监听...')
        except Exception as e:
            # 主循环外层异常：原先只置 run_flag=False、日志写"正在退出监听"，
            # 实际没有调用 StopListening()，监听线程会一直残留到进程结束。
            self.run_flag = False
            try:
                self.is_err(f"{self._nickname()} wxbot主循环异常退出！！", e)
            except Exception:
                pass
        finally:
            # 四条路径（初始化部分成功 / 主动停止 / 主循环异常 / 正常退出）统一收尾
            self.shutdown('主循环退出')

    def run(self):
        """启动机器人（对外暴露的入口函数）"""
        self.main()

    def stop(self):
        """停止机器人（对外暴露的入口函数）"""
        self.stop_wxbot()


# ============================================================
# 程序入口
# ============================================================
if __name__ == "__main__":
    bot = WXBot()
    bot.run()
