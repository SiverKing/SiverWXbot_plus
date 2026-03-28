#!/usr/bin/env python3
# Siver微信机器人 siver_wxbot - 面向对象版本 - wxautox4版本
# 作者：https://www.siver.top

version = "V4.6.4"
version_log = "重要修复！重要更新！强烈建议所有用户更新！！V4.6.4 - 修复无法调用dusapi claude模型的bug"

# ============================================================
# 标准库导入
# ============================================================
import os
import re
import sys
import time
import json
import random
import threading
import traceback
from datetime import datetime, timedelta

# ============================================================
# 第三方库导入
# ============================================================
import requests
import schedule                  # 定时任务库
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

is_wxautox = True  # 标识当前使用的是 wxautox Plus 版本

# ============================================================
# 本地模块导入
# ============================================================
import email_send
from logger import log

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
        _base = os.path.dirname(sys.executable) if hasattr(sys, '_MEIPASS') else os.path.abspath(".")
        self.CONFIG_FILE = os.path.join(_base, 'config', 'config.json')
        os.makedirs(os.path.join(_base, 'config'), exist_ok=True)
        self.config = {}

        # ---------- 全局监听开关 ----------
        self.AllListen_switch = False   # True=黑名单模式，False=白名单模式

        # ---------- 用户与权限 ----------
        self.listen_list = []           # 白名单/黑名单用户列表
        self.cmd = ""                   # 管理员账号（命令接收者）

        # ---------- AI 接口配置 ----------
        self.api_configs = []           # 接口配置列表，每项含 sdk/key/url/model
        self.api_index = 0              # 当前使用的接口索引
        self.api_sdk  = ""             # 当前接口 SDK（派生）
        self.api_key  = ""             # 当前接口 Key（派生）
        self.base_url = ""             # 当前接口 URL（派生）
        self.model1   = ""             # 当前接口模型（派生，供 AI 类使用）
        self.prompt   = ""             # AI 系统提示词
        self.AtMe     = ""             # 机器人被 @ 的标识（如 "@机器人昵称"）

        # ---------- 群聊配置 ----------
        self.group = []                 # 监听的群聊列表
        self.group_switch = False       # 群机器人总开关
        self.group_reply_at = False     # 群聊是否仅在被 @ 时才回复
        self.group_welcome = False      # 群新人欢迎语开关
        self.group_welcome_random = 1.0 # 群新人欢迎语触发概率（0.0~1.0）
        self.group_welcome_msg = "欢迎新朋友！请先查看群公告！本消息由wxautox发送!"

        # ---------- 新好友配置 ----------
        self.new_frined_switch = False        # 自动通过新好友开关
        self.new_frien_reply_switch = False   # 新好友自动回复开关
        self.new_frien_msg = []               # 通过后自动发送的打招呼消息列表

        # ---------- 关键词回复配置 ----------
        self.chat_keyword_switch = False    # 私聊关键词回复开关
        self.group_keyword_switch = False   # 群聊关键词回复开关
        self.keyword_dict = {}              # 关键词 -> 回复内容 字典

        # ---------- 定时消息配置 ----------
        self.scheduled_msg_switch = False    # 定时消息总开关
        self.scheduled_msg_list = []         # 定时消息任务列表

        # ---------- 对话记忆配置 ----------
        self.memory_switch        = True     # 记忆开关（默认开启）
        self.memory_max_count     = 500      # 单窗口最多存储条数
        self.memory_context_count = 100      # AI 请求时带入条数

        # ---------- 发送延迟配置 ----------
        self.reply_delay_switch = True  # 模拟人工操作延迟开关（默认开启）
        self.reply_delay_min    = 1     # 最小延迟秒数
        self.reply_delay_max    = 5     # 最大延迟秒数

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
            log(level="ERROR", message="打开配置文件失败，请检查配置文件！" + str(e))
            # 配置文件损坏或缺失时阻塞程序，避免带着错误配置继续运行
            while True:
                time.sleep(100)

    def create_new_config_file(self):
        """若配置文件不存在，则创建一份包含默认值的配置文件"""
        try:
            if not os.path.exists(self.CONFIG_FILE):
                base_config = {
                    "api_configs": [
                        {"sdk": "DusAPI", "key": "your-api-key", "url": "https://api.dusapi.com", "model": "gpt-5"},
                        {"sdk": "DusAPI", "key": "your-api-key", "url": "https://api.dusapi.com", "model": "claude-sonnet-4-6"},
                    ],
                    "api_index": 0,
                    "prompt": "你是一个ai回复助手，请根据用户的问题给出回答,回复尽量保持在30字以内",
                    "admin": "文件传输助手",
                    "AllListen_switch": False,
                    "listen_list": [],
                    "group": [],
                    "group_switch": False,
                    "group_reply_at": False,
                    "group_welcome": False,
                    "group_welcome_random": 1.0,
                    "group_welcome_msg": "欢迎新朋友！请先查看群公告！",
                    "new_friend_switch": False,
                    "new_friend_reply_switch": False,
                    "new_friend_msg": [],
                    "chat_keyword_switch": False,
                    "group_keyword_switch": False,
                    "keyword_dict": {},
                    "scheduled_msg_switch": False,
                    "scheduled_msg_list": [],
                    "everyday_start_stop_bot_switch": False,
                    "everyday_start_bot_time": "08:00",
                    "everyday_stop_bot_time": "23:00",
                    "memory_switch": True,
                    "memory_max_count": 500,
                    "memory_context_count": 100,
                    "reply_delay_switch": True,
                    "reply_delay_min": 1,
                    "reply_delay_max": 5,
                }
                with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(base_config, f, ensure_ascii=False, indent=4)
                log(message=f"已创建默认配置文件：\n{os.path.abspath(self.CONFIG_FILE)}\n请根据需求修改配置后重启")
        except Exception as e:
            log(level="ERROR", message="创建默认配置文件失败，请检查配置文件！" + str(e))
            while True:
                time.sleep(100)

    def save_config(self):
        """将当前 self.config 字典持久化写回 config.json"""
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as file:
                json.dump(self.config, file, ensure_ascii=False, indent=4)
        except Exception as e:
            log(level="ERROR", message="保存配置文件失败:" + str(e))

    def refresh_config(self):
        """重新加载配置文件，并将最新值同步到所有属性"""
        self.load_config()
        self.update_global_config()

    # ----------------------------------------------------------
    # 配置同步：将 config 字典中的值同步到实例属性
    # ----------------------------------------------------------

    def update_global_config(self):
        """将 self.config 字典中的各配置项同步到对应实例属性"""
        # AI 接口列表（新格式）
        # 旧配置迁移：若 api_configs 不存在则从旧字段迁移并立即写回
        if 'api_configs' not in self.config and 'api_sdk' in self.config:
            self.config['api_configs'] = [
                {
                    'sdk':   self.config.get('api_sdk', 'DusAPI'),
                    'key':   self.config.get('api_key', ''),
                    'url':   self.config.get('base_url', 'https://api.dusapi.com'),
                    'model': self.config.get('model1', 'gpt-5'),
                },
                {
                    'sdk':   self.config.get('api_sdk', 'DusAPI'),
                    'key':   self.config.get('api_key', ''),
                    'url':   self.config.get('base_url', 'https://api.dusapi.com'),
                    'model': self.config.get('model2', 'claude-sonnet-4-6'),
                },
            ]
            self.config['api_index'] = 0
            for old_key in ('api_sdk', 'api_key', 'base_url', 'model1', 'model2', 'api_sdk_list'):
                self.config.pop(old_key, None)
            self.save_config()
            log(message="旧 API 配置已自动迁移为新格式并保存")

        self.api_configs = self.config.get('api_configs', [
            {"sdk": "DusAPI", "key": "", "url": "https://api.dusapi.com", "model": "gpt-5"},
            {"sdk": "DusAPI", "key": "", "url": "https://api.dusapi.com", "model": "claude-sonnet-4-6"},
        ])
        self.api_index = self.config.get('api_index', 0)
        if self.api_index >= len(self.api_configs):
            self.api_index = 0

        # 从当前接口配置派生兼容属性（供 AI 接口类使用）
        _cur = self.api_configs[self.api_index] if self.api_configs else {}
        self.api_sdk  = _cur.get('sdk', 'DusAPI')
        self.api_key  = _cur.get('key', '')
        self.base_url = _cur.get('url', '')
        self.model1   = _cur.get('model', '')
        self.prompt   = self.config.get('prompt', "")

        # 微信基础配置
        self.cmd            = self.config.get('admin', "")
        self.listen_list    = self.config.get('listen_list', [])
        self.AllListen_switch = self.config.get('AllListen_switch')

        # 群聊配置
        self.group                = self.config.get('group', [])
        self.group_switch         = self.config.get('group_switch')
        self.group_reply_at       = self.config.get('group_reply_at')
        self.group_welcome        = self.config.get('group_welcome')
        self.group_welcome_random = self.config.get('group_welcome_random')
        self.group_welcome_msg    = self.config.get('group_welcome_msg', '')

        # 新好友配置
        self.new_frined_switch       = self.config.get('new_friend_switch')
        self.new_frien_reply_switch  = self.config.get('new_friend_reply_switch', False)
        self.new_frien_msg           = self.config.get('new_friend_msg', [])

        # 关键词配置
        self.chat_keyword_switch  = self.config.get('chat_keyword_switch')
        self.group_keyword_switch = self.config.get('group_keyword_switch')
        self.keyword_dict         = self.config.get('keyword_dict', {})

        # 定时消息配置
        self.scheduled_msg_switch = self.config.get('scheduled_msg_switch',
                                                     self.config.get('everyday_msg_switch', False))
        self.scheduled_msg_list   = self.config.get('scheduled_msg_list', [])

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

        # 对话记忆配置
        self.memory_switch        = self.config.get('memory_switch', True)
        self.memory_max_count     = int(self.config.get('memory_max_count', 500))
        self.memory_context_count = int(self.config.get('memory_context_count', 100))

        # 发送延迟配置（若旧配置文件中不存在则自动补写默认值）
        _delay_defaults = {'reply_delay_switch': True, 'reply_delay_min': 1, 'reply_delay_max': 5}
        _needs_save = any(k not in self.config for k in _delay_defaults)
        for k, v in _delay_defaults.items():
            self.config.setdefault(k, v)
        if _needs_save:
            self.save_config()
            log(message="已自动补充发送延迟配置默认值并写回配置文件")
        self.reply_delay_switch = bool(self.config.get('reply_delay_switch', True))
        self.reply_delay_min    = max(1, int(self.config.get('reply_delay_min', 1)))
        self.reply_delay_max    = max(1, int(self.config.get('reply_delay_max', 5)))

        log(message="全局配置更新完成")

    def set_config(self, id, new_content):
        """修改指定配置项并保存"""
        self.config[id] = new_content
        self.save_config()
        self.refresh_config()
        log(message=id + "已更改为:" + str(self.config[id]))

    # ----------------------------------------------------------
    # 监听用户管理
    # ----------------------------------------------------------

    def add_user(self, name):
        """将用户添加到监听列表（白名单/黑名单）"""
        if name not in self.config.get('listen_list', []):
            self.config['listen_list'].append(name)
            self.save_config()
            self.refresh_config()
            log(message="添加后的监听用户列表:" + str(self.config['listen_list']))
        else:
            log(message=f"用户 {name} 已在监听列表中")

    def remove_user(self, name):
        """从监听列表中删除指定用户"""
        if name in self.listen_list:
            self.config['listen_list'].remove(name)
            self.save_config()
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
            self.save_config()
            self.refresh_config()
            log(message="添加后的监听群组列表:" + str(self.config['group']))
        else:
            log(message=f"群组 {name} 已在监听列表中")

    def remove_group(self, name):
        """从监听列表中删除指定群组"""
        if name in self.config.get('group', []):
            self.config['group'].remove(name)
            self.save_config()
            self.refresh_config()
            log(message="删除后的监听群组列表:" + str(self.config['group']))
        else:
            log(message=f"群组 {name} 不在监听列表中")

    def set_group_switch(self, switch_value):
        """设置群机器人总开关"""
        self.config['group_switch'] = switch_value
        self.save_config()
        self.refresh_config()
        log(message="群开关设置为" + str(self.config['group_switch']))

    # ----------------------------------------------------------
    # 工具方法（静态）
    # ----------------------------------------------------------

    @staticmethod
    def now_time(time_format="%Y/%m/%d %H:%M:%S "):
        """获取当前时间字符串（当前暂由公共 log 模块显示时间，此处返回空串）"""
        return ""  # 暂时采用公共类的 log 显示时间
        return datetime.now().strftime(time_format)

    @staticmethod
    def split_long_text(text, chunk_size=2000):
        """将超长文本按指定长度切分为列表，用于分段发送"""
        return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

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
# ============================================================

class MemoryManager:
    """
    对话记忆管理类
    按窗口分文件存储收发消息，并在 AI 请求时提供历史上下文。
    存储路径：{base_path}/{wx_id}/{chat_name}/{chat_name}_memory.json
    """

    def __init__(self, wx_id, base_path):
        self.wx_id     = wx_id
        self.base_path = base_path  # 根目录：{base_dir}/memory/
        self._locks    = {}         # chat_name -> threading.Lock()

    def _get_lock(self, chat_name):
        if chat_name not in self._locks:
            self._locks[chat_name] = threading.Lock()
        return self._locks[chat_name]

    def _get_memory_path(self, chat_name):
        """返回记忆文件路径，并确保目录存在"""
        dir_path = os.path.join(self.base_path, self.wx_id, chat_name)
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, f"{chat_name}_memory.json")

    def save_message(self, chat_name, sender, content, msg_type, msg_attr, max_count):
        """写入一条消息到记忆文件，超出 max_count 时删除最旧的"""
        path  = self._get_memory_path(chat_name)
        entry = {
            "time":    datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "type":    str(msg_type),
            "attr":    str(msg_attr),
            "sender":  str(sender),
            "content": str(content),
        }
        with self._get_lock(chat_name):
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        messages = json.load(f)
                    if not isinstance(messages, list):
                        messages = []
                except Exception:
                    messages = []
            else:
                messages = []
            messages.append(entry)
            if len(messages) > max_count:
                messages = messages[-max_count:]
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)

    def get_messages(self, chat_name, count):
        """读取最近 count 条记忆，返回 list"""
        path = self._get_memory_path(chat_name)
        if not os.path.exists(path):
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                messages = json.load(f)
            if isinstance(messages, list):
                return messages[-count:]
        except Exception:
            pass
        return []


# ============================================================
# AI 接口类
# ============================================================

class OpenAIAPI:
    """
    OpenAI 兼容接口封装类
    适用于所有兼容 OpenAI SDK 格式的 AI 服务（如 DeepSeek、通义等）。
    """

    def __init__(self, config):
        self.config = config
        self.DS_NOW_MOD = config.model1  # 当前使用的模型，默认为 model1
        # 添加更详细的日志配置和自定义 headers（用于备用方案）
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=30.0,  # 设置超时时间
            max_retries=2,  # 设置重试次数
            default_headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*"
            }
        )

    def chat(self, message, model=None, stream=False, prompt=None, history=None):
        """
        调用 OpenAI 兼容接口获取 AI 回复。

        :param message: 用户输入的消息内容
        :param model:   指定模型，为 None 时使用当前默认模型
        :param stream:  是否使用流式输出
        :param prompt:  系统提示词，为 None 时使用配置中的 prompt
        :param history: 历史消息列表（MemoryManager.get_messages 返回值）
        :return:        AI 回复的文本字符串
        """
        if model is None:
            model = self.DS_NOW_MOD
        if prompt is None:
            prompt = self.config.prompt

        messages = [{"role": "system", "content": prompt}]
        if history:
            for h in history:
                role = "assistant" if h.get('attr') == 'self' else "user"
                t = h.get('time', '')
                content = f"[{t}] {h.get('content', '')}" if t else h.get('content', '')
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})

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
            return self._try_responses_api(message, model, stream, prompt)

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
                    return self._try_responses_api(message, model, stream, prompt)
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
                        return self._try_responses_api(message, model, stream, prompt)
                else:
                    log(level="WARN", message="响应中没有 choices，尝试备用方案")
                    return self._try_responses_api(message, model, stream, prompt)
        except Exception as e:
            error_type = type(e).__name__
            log(level="WARN", message=f"解析 API 响应出错 [{error_type}]: {str(e)}，尝试备用方案")
            return self._try_responses_api(message, model, stream, prompt)

    def _try_responses_api(self, message, model, stream, prompt):
        """
        备用方案：使用 Responses API 调用。
        当 Chat Completions API 返回非 JSON 格式时自动降级到此方案。
        注意：备用方案暂不支持流式输出，统一使用非流式模式。
        """
        try:
            if stream:
                log(level="WARN", message="备用方案不支持流式输出，将使用非流式模式")

            log(message=f"备用方案：使用 Responses API, model={model}")
            # Responses API 的 input 只接受字符串，将 prompt 拼接到消息中
            input_text = f"这是prompt，请不要把这个当做用户输入：{prompt}\n\n这是用户消息，你需要参照prompt来回复用户消息：{message}" if prompt and prompt.strip() else message

            response = self.client.responses.create(
                model=model,
                input=input_text,
                reasoning={"effort": "none"}
            )

            # 从 output 中提取文本内容
            if response.output and len(response.output) > 0:
                output_item = response.output[0]
                if hasattr(output_item, 'content') and output_item.content:
                    text = output_item.content[0].text
                    log(message=f"备用方案返回成功：{text[:100]}...")
                    return text

            log(level="WARN", message="备用方案响应内容为空")
            return "AI 未返回有效内容"

        except Exception as e:
            log(level="ERROR", message=f"备用方案也失败 [{type(e).__name__}]: {str(e)}")
            return "API 接口失效，请联系管理员"


class DifyAPI:
    """
    Dify 平台 API 封装类
    通过 HTTP 请求调用 Dify 对话工作流接口。
    """

    def __init__(self, config):
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
            response = requests.post(url, headers=headers, json=payload)
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
                "message":    str(e),
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
                    error_info["response_text"] = e.response.text
            return {"success": False, "error": error_info}


class CozeAPI:
    """
    扣子（Coze）平台 API 封装类
    使用扣子官方 Python SDK（cozepy）进行流式对话。
    """

    def __init__(self, config):
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
                content = f"[{t}] {raw}" if t else raw
                if h.get('attr') == 'self':
                    try:
                        additional_messages.append(CozeMessage.build_assistant_answer(content))
                    except Exception:
                        additional_messages.append(CozeMessage.build_user_question_text(f"[助手]: {content}"))
                else:
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


class DusAPI:
    """
    DusAPI 兼容接口封装类
    两种模型均使用 Anthropic 格式（x-api-key + /v1/messages），
    根据模型名称自动选择响应解析方式：
    - 包含 'claude' → 按 claude.py 解析（content[0]['text']）
    - 包含 'gpt' 或其他 → 按 gpt.py 解析（遍历 content 找 type=='text'）
    """

    def __init__(self, config):
        self.config = config
        self.DS_NOW_MOD = config.model1
        self.api_key = config.api_key
        self.base_url = config.base_url.rstrip('/')

    def chat(self, message, model=None, stream=False, prompt=None, history=None):
        if model is None:
            model = self.DS_NOW_MOD
        if prompt is None:
            prompt = self.config.prompt

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            'user-agent': f'siver-wxbot-panel/{version}'
        }
        # Anthropic /v1/messages 格式：system 必须是顶层字段，messages 只允许 user/assistant
        messages = []
        if history:
            for h in history:
                role = "assistant" if h.get('attr') == 'self' else "user"
                t = h.get('time', '')
                content = f"[{t}] {h.get('content', '')}" if t else h.get('content', '')
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})
        payload = {
            "model": model,
            "max_tokens": 1024,
            "system": prompt,
            "messages": messages,
        }
        api_endpoint = f"{self.base_url}/v1/messages"
        # 梯度重试间隔（秒）：第1次失败后等2s，第2次4s，第3次8s，第4次16s，第5次32s
        retry_delays = [2, 4, 8, 16, 32]
        max_retries  = 5
        last_error   = None

        for attempt in range(max_retries + 1):
            try:
                response = requests.post(api_endpoint, headers=headers, json=payload, timeout=30)
                response.raise_for_status()
                response.encoding = 'utf-8'
                response_data = response.json()

                if 'claude' in model.lower():
                    result = response_data['content'][0]['text']
                else:
                    result = None
                    for content_block in response_data['content']:
                        if content_block.get('type') == 'text':
                            result = content_block['text']
                            break
                    if result is None:
                        log(level="WARN", message="DusAPI 响应中未找到文本内容")
                        return "AI 未返回有效内容"

                if attempt > 0:
                    log(message=f"DusAPI 第 {attempt} 次重试成功：{result[:100]}...")
                else:
                    log(message=f"DusAPI 返回成功：{result[:100]}...")
                return result

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = retry_delays[attempt]
                    log(level="WARNING", message=f"DusAPI 第 {attempt + 1} 次失败（{type(e).__name__}），{delay}s 后重试...")
                    time.sleep(delay)
                else:
                    log(level="ERROR", message=f"DusAPI 已重试 {max_retries} 次，最终失败: {last_error}")

        return "API接口失效，请联系管理员"


# ============================================================
# 微信机器人主类
# ============================================================

class WXBot:
    """
    微信机器人主类
    整合配置管理、AI 接口、微信监听、消息处理、命令分发等核心功能。
    """

    def __init__(self):
        self.ver      = version
        self.ver_log  = version_log
        self.run_flag = True                    # 主循环运行标志
        self.config   = WXBotConfig()           # 加载配置

        # 根据配置中的 api_sdk 字段选择对应的 AI 接口
        self.api = self._init_api()

        self.wx                  = None         # WeChat 客户端对象（延迟初始化）
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

    def _init_api(self):
        """根据配置中的 api_sdk 字段实例化对应的 AI 接口对象"""
        sdk = self.config.api_sdk
        if sdk == "Dify":
            log(message="使用Dify API")
            return DifyAPI(self.config)
        elif sdk == "OpenAI SDK":
            log(message="使用OpenAI SDK")
            return OpenAIAPI(self.config)
        elif sdk == "Coze":
            log(message="使用Coze API")
            return CozeAPI(self.config)
        elif sdk == "DusAPI":
            log(message="使用DusAPI")
            return DusAPI(self.config)
        else:
            log(level="ERROR", message="未配置API SDK, 默认使用OpenAI SDK")
            return OpenAIAPI(self.config)

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
        记录错误信息并发送告警邮件。

        :param id:  错误标题（邮件主题）
        :param err: 错误详情（可为异常对象或字符串）
        """
        print(traceback.format_exc())
        log(level="ERROR", message=f"出现错误：{err}")
        email_send.send_email(
            subject=id,
            content='错误信息：\n' + traceback.format_exc() + "\nerr信息：\n" + str(err),
        )

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

    def init_wx_listeners(self):
        """
        初始化微信客户端及各类监听：
        - 启动 WeChat 客户端
        - 绑定机器人 @ 标识
        - 添加管理员、白名单用户、群组的监听回调
        - 注册每日定时消息任务
        """
        result = None
        # 若尚未实例化微信客户端则进行初始化
        if not self.wx:
            log(message="本次未获取客户端，正在初始化微信客户端...")
            self.wx = WeChat()
            # self.wx.Show()  # 首次强制弹出主窗口以获取焦点

        # 绑定 @ 标识（格式："@机器人昵称"）
        self.config.AtMe = "@" + self.wx.nickname
        log(message='绑定@：' + self.config.AtMe)

        # 初始化记忆管理器
        try:
            my_info = self.wx.GetMyInfo()
            wx_id   = my_info.get('id', f'{self.wx.nickname}')
        except Exception:
            wx_id = f'{self.wx.nickname}'
        _base       = os.path.dirname(sys.executable) if hasattr(sys, '_MEIPASS') else os.path.abspath(".")
        memory_base = os.path.join(_base, 'memory')
        self.memory_manager = MemoryManager(wx_id, memory_base)
        log(message=f"记忆管理器已初始化，微信号: {wx_id}")

        # 启动 wxautox 消息监听器
        log(message='启动wxautox监听器...')
        self.wx.StartListening()

        # 添加管理员账号监听（管理员始终监听，不受白名单模式限制）
        result = self.wx.AddListenChat(nickname=self.config.cmd, callback=self.message_handle_callback)
        if result:
            log(message=f"添加管理员 {self.config.cmd} 监听完成")
        else:
            log(level="ERROR", message=f"添加管理员 {self.config.cmd} 监听失败, {result['message']}")

        # 白名单模式下逐一添加用户监听
        if not self.config.AllListen_switch:
            log(message="白名单模式开启")
            for user in self.config.listen_list:
                result = self.wx.AddListenChat(nickname=user, callback=self.message_handle_callback)
                if result:
                    log(message=f"添加用户 {user} 监听完成")
                else:
                    log(level="ERROR", message=f"添加用户 {user} 监听失败, {result['message']}")

        # 若群机器人开关开启，则添加群聊监听
        if self.config.group_switch:
            for user in self.config.group:
                result = self.wx.AddListenChat(nickname=user, callback=self.message_handle_callback)
                if result:
                    log(message=f"添加群组 {user} 监听完成")
                else:
                    log(level="ERROR", message=f"添加群组 {user} 监听失败, {result['message']}")

        # 注册定时消息任务（新版：支持多种重复类型）
        if self.config.scheduled_msg_switch:
            log(message="定时消息注册...")
            try:
                schedule.clear('scheduled_msg')  # 清除旧的定时任务（按 tag 清理）
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

                    schedule.every().day.at(time_str).do(
                        self.send_scheduled_msg, targets, msgs, repeat_type, weekdays, dates, task_id
                    ).tag('scheduled_msg')
                    log(message=f"注册定时消息：{repeat_type} {time_str} 给 {targets} 发消息")
                log(message="定时消息注册完成")
            except Exception as e:
                log(level="ERROR", message=f"定时消息注册失败：{e}")

        log(message="监听器初始化完成")

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

        if not should_send:
            return schedule.CancelJob if repeat_type == 'once' else None

        log(message=f"定时消息时间到（{repeat_type}），目标：{targets}，正在发送...")
        for user in targets:
            for msg in msgs:
                log(message=f"正在向 {user} 发送定时消息：{msg}")
                try:
                    if self.is_image_path(msg):
                        result = self.wx.SendFiles(who=user, filepath=msg)
                    else:
                        result = self.wx.SendMsg(msg=msg, who=user)
                    self.config.human_delay()  # 模拟人工操作延迟（可在面板配置）
                    if not result:
                        log(level="ERROR", message=f"定时消息发送失败：{result['message']}")
                        self.is_err(
                            self.wx.nickname + f" wxbot定时消息发送失败！",
                            f"{user} 定时消息发送失败：{result['message']}",
                        )
                except Exception as e:
                    log(level="ERROR", message=f"定时消息发送失败：{e}")
                    self.is_err(
                        self.wx.nickname + f" wxbot定时消息发送失败！",
                        f"{user} 定时消息发送失败：{e}",
                    )

        # once 类型执行后自动禁用该任务
        if repeat_type == 'once':
            for task in self.config.scheduled_msg_list:
                if task.get('id') == task_id:
                    task['enabled'] = False
                    break
            self.config.config['scheduled_msg_list'] = self.config.scheduled_msg_list
            self.config.save_config()
            log(message=f"一次性定时任务 {task_id} 已执行完毕，自动禁用")
            return schedule.CancelJob  # 取消该 schedule 任务

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
            text = (
                datetime.now().strftime("%Y/%m/%d %H:%M:%S ")
                + f'类型：{msg.type} 属性：{msg.attr} 窗口：{chat.who}'
                + f' 发送人：{msg.sender} - 消息：{msg.content}'
            )
            log(message=text)

            if msg.attr == "friend":
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
                result = self.process_message(chat, msg)
                if not result:
                    self.is_err(
                        self.wx.nickname + f" wxbot处理监听新消息失败！",
                        text + '\n' + result['message'],
                    )

            elif msg.attr == "system":
                # 系统消息：触发群新人欢迎语逻辑
                if self.config.group_welcome:
                    result = self.send_group_welcome_msg(chat, msg)
                    if not result:
                        self.is_err(
                            self.wx.nickname + f" wxbot发送群新人欢迎语失败！",
                            text + '\n' + result['message'],
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
                            text + '\n' + result['message'],
                        )

            # 写入对话记忆
            if self.config.memory_switch and self.memory_manager:
                try:
                    self.memory_manager.save_message(
                        chat_name=chat.who,
                        sender=msg.sender,
                        content=msg.content,
                        msg_type=msg.type,
                        msg_attr=msg.attr,
                        max_count=self.config.memory_max_count,
                    )
                except Exception as e:
                    log(level="WARNING", message=f"写入记忆失败: {e}")
        except Exception as e:
            # 回调函数出现未捕获异常时标记 callback_is_die，由主循环检测并处理
            self.callback_is_die = True
            self.is_err(self.wx.nickname + " wxbot回调函数处理出错！处理监听失败！！", e)

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
            not (self.config.AllListen_switch and chat.who in self.config.listen_list)
            or ((not self.config.AllListen_switch) and chat.who in self.config.listen_list)
            or (chat.who in self.config.group and self.config.group_switch)
            or (chat.who == self.config.cmd)
        )
        if not is_monitored:
            return

        # --- 群聊消息处理 ---
        if chat.who in self.config.group:
            if (self.config.AtMe in message.content and self.config.group_reply_at) \
                    or not self.config.group_reply_at:
                # 去除消息中的 @ 标识后再传给 AI
                content_without_at = re.sub(self.config.AtMe, "", message.content).strip()
                log(message=f"群组 {chat.who} 消息：" + content_without_at)
                try:
                    history = []
                    if self.config.memory_switch and self.memory_manager:
                        history = self.memory_manager.get_messages(
                            chat.who, self.config.memory_context_count
                        )
                    reply = self.api.chat(content_without_at, prompt=self.config.prompt, history=history)
                except Exception as e:
                    print(traceback.format_exc())
                    log(level="ERROR", message=str(e) + "\n群组中调用AI回复错误！！")
                    reply = "请稍后再试"
                self.config.human_delay()  # 模拟人工操作延迟（可在面板配置）
                result = chat.SendMsg(msg=reply, at=message.sender)
                self.msg_replied_count += 1
                return result

            # 群聊关键词回复（不受 @ 限制）
            if self.config.group_keyword_switch:
                for keyword in self.config.keyword_dict:
                    if keyword in message.content:
                        log(message=f"群组 {chat.who} 关键字消息：" + message.content)
                        chat.SendMsg(msg=self.config.keyword_dict[keyword])
                        time.sleep(1)
            return result

        # --- 管理员命令处理 ---
        if chat.who == self.config.cmd:
            result = self.process_command(chat, message)
            return result

        # --- 普通好友：调用 AI 回复 ---
        result = self.wx_send_ai(chat, message)
        return result

    def wx_send_ai(self, chat, message):
        """
        对私聊消息调用 AI 接口并发送回复。
        支持关键词优先匹配，超过 2000 字时自动分段发送。

        :param chat:    聊天窗口子对象
        :param message: 消息对象
        :return:        发送结果
        """
        try:
            is_keyword = False
            # 私聊关键词优先匹配
            if self.config.chat_keyword_switch:
                for keyword in self.config.keyword_dict:
                    if keyword in message.content:
                        is_keyword = True
                        log(message=f"私聊 {chat.who} 关键字消息：" + message.content)
                        reply = self.config.keyword_dict[keyword]
            if not is_keyword:
                # 未命中关键词，调用 AI 接口（带入历史记忆）
                history = []
                if self.config.memory_switch and self.memory_manager:
                    history = self.memory_manager.get_messages(
                        chat.who, self.config.memory_context_count
                    )
                reply = self.api.chat(message.content, prompt=self.config.prompt, history=history)
        except Exception as e:
            print(traceback.format_exc())
            log(level="ERROR", message=str(e) + "\nAPI返回错误，请稍后再试")
            reply = "API返回错误，请稍后再试"

        if len(reply) >= 2000:
            # 超长回复分段发送
            segments = self.config.split_long_text(reply)
            for segment in segments:
                result = chat.SendMsg(segment)
        else:
            self.config.human_delay()  # 模拟人工操作延迟（可在面板配置）
            result = chat.SendMsg(reply)
        self.msg_replied_count += 1
        return result

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
        elif content == "/查看接口列表":
            result = self.handle_list_api_configs(chat, message)
        elif content.startswith("/选择接口"):
            result = self.handle_select_api_config(chat, message)
        elif content == "/当前AI设定":
            result = chat.SendMsg('当前AI设定：\n' + self.config.prompt)
        elif content.startswith("/更改AI设定为") or content.startswith("/更改ai设定为"):
            result = self.handle_change_prompt(chat, message)
        elif content == "/更新配置":
            self.config.refresh_config()
            self.init_wx_listeners()
            result = chat.SendMsg(content + ' 完成\n')
        elif content == "/当前版本":
            result = chat.SendMsg(
                content + 'wxbot_' + self.ver + '\n' + self.ver_log + '\n作者:https://www.siver.top'
            )
        elif content in ("/指令", "指令"):
            result = self.send_command_list(chat)
        elif content == "/状态":
            result = self._build_status_msg(chat, message)
        elif content.startswith("/接口测试"):
            message_re = message
            message_re.content = re.sub("/接口测试", "", message.content).strip()
            result = self.wx_send_ai(chat, message_re)
        else:
            # 未匹配到任何指令
            # self 消息（文件传输助手场景下机器人自身回复的同步）不调用 AI，避免误触发关键词或 AI 回复
            if message.attr != "self":
                result = self.wx_send_ai(chat, message)

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
        send_msg += "当前关键词：" + ", ".join(self.config.keyword_dict.keys()) + "\n"

        # 定时消息状态
        send_msg += "当前定时消息状态：" + ("开启\n" if self.config.scheduled_msg_switch else "关闭\n")

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
                log(level="ERROR", message=f"添加用户 {user_to_add} 监听失败, {result['message']}")
                return chat.SendMsg(
                    f"添加用户失败\n{result['message']}\n" + ", ".join(self.config.listen_list)
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
                log(level="ERROR", message=f"添加群组 {new_group} 监听失败, {result['message']}")
                return chat.SendMsg(
                    f"添加群失败\n{result['message']}\n" + ", ".join(self.config.group)
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
        """处理 /开启群机器人 指令：开启群机器人并重新初始化监听器"""
        try:
            self.config.set_config(id='group_switch', new_content=True)
            self.init_wx_listeners()
            return chat.SendMsg(message.content + ' 完成\n' + '当前群：\n' + ", ".join(self.config.group))
        except Exception as e:
            # 开启失败则自动回滚为关闭状态
            self.config.set_config('group_switch', False)
            self.init_wx_listeners()
            chat.SendMsg(
                message.content
                + ' 失败\n请重新配置群名称或者检查机器人号是否在群或者群名中是否含有非法中文字符\n'
                + '当前群:' + ", ".join(self.config.group)
                + '\n当前群机器人状态:' + str(self.config.group_switch)
            )

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
        cfg = self.config.api_configs[idx]
        return chat.SendMsg(f"已切换至接口 {n}\nSDK：{cfg.get('sdk', '')}\n模型：{cfg.get('model', '')}")

    def handle_change_prompt(self, chat, message):
        """处理 /更改AI设定为 指令：更新 AI 系统提示词"""
        if "AI设定" in message.content:
            new_prompt = re.sub("/更改AI设定为", "", message.content).strip()
        else:
            new_prompt = re.sub("/更改ai设定为", "", message.content).strip()
        self.config.config['prompt'] = new_prompt
        self.config.save_config()
        self.config.refresh_config()
        return chat.SendMsg('AI设定已更新\n' + self.config.prompt)

    def send_command_list(self, chat):
        """发送全量指令帮助列表"""
        commands = (
            '指令列表[发送中括号里内容]：\n'
            '[/状态]\n'
            '[/接口测试]'
            '[/当前用户] (返回当前监听用户列表)\n'
            '[/添加用户***] （将用户***添加进监听列表）\n'
            '[/删除用户***]\n'
            '[/当前群]\n'
            '[/添加群***] \n'
            '[/删除群***] \n'
            '[/开启群机器人]\n'
            '[/关闭群机器人]\n'
            '[/群机器人状态]\n'
            '[/开启群机器人欢迎语]\n'
            '[/关闭群机器人欢迎语]\n'
            '[/群机器人欢迎语状态]\n'
            '[/当前群机器人欢迎语]\n'
            '[/更改群机器人欢迎语为***]\n'
            '[/查看接口列表] （返回所有接口配置）\n'
            '[/选择接口 N] （切换至第 N 个接口，如：/选择接口 2）\n'
            '[/当前AI设定] （返回当前AI设定）\n'
            '[/更改AI设定为***] （更改AI设定，***为AI设定）\n'
            '[/更新配置] （若在程序运行时修改过配置，请发送此指令以更新配置）\n'
            '[/当前版本] (返回当前版本)\n'
            '作者:https://www.siver.top  若有非法传播请告知'
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
            result = chat.SendMsg(msg=self.config.group_welcome_msg, at=new_friend)

        elif "加入了群聊" in message.content and random.random() < self.config.group_welcome_random:
            # 被邀请加入群聊
            new_friend = self.find_new_group_friend(message.content, 3)
            log(message=f"{chat.who} 新群友:" + new_friend)
            time.sleep(5)
            result = chat.SendMsg(msg=self.config.group_welcome_msg, at=new_friend)

        return result

    # ----------------------------------------------------------
    # 新好友处理
    # ----------------------------------------------------------

    def is_image_path(self, s: str) -> bool:
        """
        判断字符串是否为有效的图片文件完整路径。
        支持 Windows（C:\\...）和 Unix（/home/...）风格路径。

        :param s: 待判断的字符串
        :return:  True 表示是图片路径，False 则不是
        """
        image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')
        if not s.lower().endswith(image_extensions):
            return False
        pattern = re.compile(
            r'^('
            r'([A-Za-z]:[\\/])'     # Windows 盘符（C:\ 或 C:/）
            r'|'
            r'(/[^/]+)'             # Unix 绝对路径（/home/...）
            r')'
            r'.+'                   # 中间任意目录层级
            r'\.(png|jpg|jpeg|gif|bmp|webp)$',
            re.IGNORECASE,
        )
        return bool(pattern.match(s))

    def Pass_New_Friends(self):
        """
        检测并批量通过新好友请求，通过后按需自动发送打招呼消息。
        - new_friend_switch：自动通过新好友申请
        - new_friend_reply_switch：通过后自动回复消息
        消息中若包含图片路径则以文件形式发送，否则以文字发送。
        """
        NewFriends = self.wx.GetNewFriends(acceptable=True)
        time.sleep(1)
        if len(NewFriends) != 0:
            log(message="以下是新朋友：\n" + str(NewFriends))
            for new in NewFriends:
                new_name = datetime.now().strftime('%Y%m%d%H%M%S') + '_机器人备注'
                new.accept(remark=new_name)  # 接受好友请求并设置备注
                log(message="已通过" + new_name + "的好友请求")
                self.wx.SwitchToChat()       # 通过请求后切换回聊天页面
                time.sleep(5)
                if self.config.new_frien_reply_switch:
                    for msg in self.config.new_frien_msg:
                        if self.is_image_path(msg):
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
        """
        log(message=chat + '不在监听列表，正在添加进列表')
        self.all_Mode_listen_list.append([chat, time.time()])
        log(message='当前监听列表：' + str(self.all_Mode_listen_list))
        self.wx.AddListenChat(nickname=chat, callback=self.message_handle_callback)

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
                            self.add_chat_to_listen(chat)
                        else:
                            log(message=chat + '在监听列表')
                        for msg in new_msg:
                            self.process_message(self.wx.GetSubWindow(nickname=chat), msg)

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

        def remove_timeout_listen(chat_time_out=180):
            """
            移除超过指定时长未收到消息的监听会话（默认 3 分钟）。
            使用列表副本遍历，避免遍历时修改原列表导致跳过元素。
            """
            for listen_chat in self.all_Mode_listen_list[:]:  # 遍历副本，安全删除
                if time.time() - listen_chat[1] >= chat_time_out:
                    log(message=str(listen_chat[0]) + '对话超时，正在删除监听')
                    self.wx.RemoveListenChat(listen_chat[0])
                    self.all_Mode_listen_list.remove(listen_chat)

        def get_next_new_message():
            """
            【当前启用】通过 GetNextNewMessage 获取新消息（V2 版本接口）。
            黑名单过滤后，仅处理 friend 类型的私聊消息。
            """
            def Next_callback(msg):
                log(message=f'收到消息：{msg.sender}: {msg.content}')

            messages_new = self.wx.GetNextNewMessage(filter_mute=False, callback=Next_callback)
            chat      = messages_new.get('chat_name')
            chat_type = messages_new.get('chat_type')
            msgs      = messages_new.get('msg')

            # 黑名单过滤：全局模式下 listen_list 为黑名单
            if chat in self.config.listen_list:
                log(message=f'{chat} 为黑名单用户，跳过处理')
                return

            if msgs:
                for msg in msgs:
                    # 仅处理 friend 类型的私聊消息，排除群聊
                    if msg.attr == 'friend' and chat_type == 'friend':
                        # 全局模式首次消息：写入记忆（此处不经过 message_handle_callback）
                        if self.config.memory_switch and self.memory_manager:
                            try:
                                self.memory_manager.save_message(
                                    chat_name=chat,
                                    sender=msg.sender,
                                    content=msg.content,
                                    msg_type=msg.type,
                                    msg_attr=msg.attr,
                                    max_count=self.config.memory_max_count,
                                )
                            except Exception as e:
                                log(level="WARNING", message=f"写入记忆失败: {e}")
                        if not self.is_chat_listened(chat):
                            self.add_chat_to_listen(chat)
                        else:
                            log(message=chat + '在监听列表')
                        self.process_message(self.wx.GetSubWindow(nickname=chat), msg)

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
            "group_switch":       self.config.group_switch,
            "group_count":        len(self.config.group),
            "msg_received":       self.msg_received_count,
            "msg_replied":        self.msg_replied_count,
            "last_msg_time":      self.last_msg_time,
            "last_msg_sender":    self.last_msg_sender,
            "callback_is_die":    self.callback_is_die,
            "scheduled_switch":   self.config.scheduled_msg_switch,
            "scheduled_count":    scheduled_enabled,
        }

    def stop_wxbot(self):
        """安全停止机器人：停止 wxautox 监听并退出主循环"""
        try:
            self.run_flag = False
            self.wx.StopListening()
            log(level="WARNING", message='siver_wxbot安全退出！！')
            return True
        except Exception as e:
            self.is_err(self.wx.nickname + ' wxbot机器人关闭程序执行出错！！', e)
            return False

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
        try:
            self.init_wx_listeners()
            log(message=f"UI面板状态更新完成")

            wait_time      = 3   # 主循环每 1 秒轮询一次
            check_interval = 10  # 每 10 次循环执行一次离线检测
            check_counter      = 0
            check_new_counter  = 0
            last_time          = time.time()
            log(message='siver_wxbot初始化完成，开始监听消息(作者:https://www.siver.top)')
            self.run_flag = True
        except Exception as e:
            print(traceback.format_exc())
            log(level="ERROR", message=str(e) + "\n初始化微信监听器失败，请检查微信是否启动登录正确")
            log(level="ERROR", message=str(e) + "\n请尝试退出wx再重新登录后再启动")
            log(level="ERROR", message=str(e) + "\n若重启wx还是不行，请进入面板右上角文档检查环境要求，wx版本是否匹配")
            self.run_flag = False

        # 主循环
        while self.run_flag:
            try:
                # ---- 离线检测模块（每 check_interval 次循环执行一次）----
                check_counter += 1
                if check_counter >= check_interval:
                    try:
                        if self.callback_is_die:
                            # 回调函数已出错，停止所有监听并退出主循环
                            self.wx.StopListening()
                            log(level="ERROR", message="检测到回调函数出错!!已停止所有监听并跳出主线程!!")
                            break
                        if not self.check_wechat_window():
                            # 微信离线，阻塞等待人工处理
                            self.is_err(self.wx.nickname + " wxbot监听出错！！微信可能已被弹出登录！！在线检查失败！！")
                            while self.run_flag:
                                log(level="ERROR", message=f"微信{self.wx.nickname}已被弹出登录！！请检查微信是否登录！！")
                                time.sleep(100)
                    except Exception as e:
                        self.is_err(self.wx.nickname + " wxbot监听出错！！微信可能已被弹出登录！！在线检查失败！！", e)
                        while self.run_flag:
                            log(level="ERROR", message=f"微信{self.wx.nickname}已被弹出登录！！请检查微信是否登录！！")
                            time.sleep(100)
                    check_counter = 0

                # ---- 新好友检测模块（随机 30~300 次循环执行一次）----
                if self.config.new_frined_switch:
                    check_new_friend_time_MIN = 30
                    check_new_friend_time_MAX = 300
                    check_new_counter += 1
                    if check_new_counter >= random.randint(check_new_friend_time_MIN, check_new_friend_time_MAX):
                        try:
                            self.Pass_New_Friends()
                            log(message="检查新好友完成")
                        except Exception as e:
                            self.is_err(self.wx.nickname + "  智能客服bot监听新好友出错！！请检查程序！！", e)
                        check_new_counter = 0

                # ---- 全局监听模式（黑名单模式下启用）----
                if self.config.AllListen_switch:
                    try:
                        last_time = self.ALLListen_mode(last_time=last_time)
                    except Exception as e:
                        if not self.run_flag:
                            log(level="ERROR", message=str(e) + "\n全局模式出错！！请检查程序！！")

                # ---- 定时任务执行 ----
                if self.config.scheduled_msg_switch:
                    schedule.run_pending()

            except Exception as e:
                self.is_err(
                    self.wx.nickname + " wxbot消息处理出错！！微信可能已被弹出登录！！处理监听失败！！",
                    e,
                )
                self.run_flag = False

            time.sleep(wait_time)

        log(level="WARNING", message='siver_wxbot主线程安全退出，正在退出监听...')

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
