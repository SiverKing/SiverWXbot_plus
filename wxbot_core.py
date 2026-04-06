#!/usr/bin/env python3
# Siver微信机器人 siver_wxbot - 面向对象版本 - wxautox4版本
# 作者：https://www.siver.top

version = "V4.7.07"
version_log = "V4.7.07 - 新增语音可以自动转文字识别(与图片识别同开关)、dusapi接口参数优化、修复全局模式下自定义转发来源不回复的bug"

# ============================================================
# 标准库导入
# ============================================================
import os
import re
import sys
import time
import json
import random
import calendar
import threading
import traceback
from datetime import datetime, timedelta

# ============================================================
# 第三方库导入
# ============================================================
import requests
import base64
import mimetypes
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
WxParam.DEFAULT_MESSAGE_YBIAS = 40

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
【以下是你的角色设定】
{base_prompt}"""

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
        self.prompt_dir  = os.path.join(_base, 'config', 'prompt')
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
        self.group_api_map = {}         # 群聊专属接口映射 {群名: api_index}
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
        self.group_keyword_at_only = False  # 群聊关键词仅被@时触发
        self.keyword_dict = {}              # 关键词 -> 回复内容 字典

        # ---------- 自定义转发配置 ----------
        self.custom_forward_switch = False  # 自定义转发总开关
        self.custom_forward_list   = []     # 自定义转发规则列表

        # ---------- 多 Prompt 配置 ----------
        self.default_prompt   = "默认"      # 全局/fallback prompt 文件名（不含 .md）
        self.chat_prompt_map  = {}          # 私聊白名单用户 -> prompt 名称
        self.chat_api_map     = {}          # 私聊白名单用户 -> API 接口索引
        self.group_prompt_map = {}          # 群组名称 -> prompt 名称

        # ---------- 定时消息配置 ----------
        self.scheduled_msg_switch = False    # 定时消息总开关
        self.scheduled_msg_list = []         # 定时消息任务列表

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
                    "AllListen_filter_mute": True,
                    "listen_list": [],
                    "group": [],
                    "group_api_map": {},
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
                    "group_keyword_at_only": False,
                    "keyword_dict": {},
                    "custom_forward_switch": False,
                    "custom_forward_list": [],
                    "default_prompt": "默认",
                    "chat_prompt_map": {},
                    "chat_api_map": {},
                    "group_prompt_map": {},
                    "scheduled_msg_switch": False,
                    "scheduled_msg_list": [],
                    "scheduled_moments_switch": False,
                    "scheduled_moments_list": [],
                    "moments_like_switch": False,
                    "moments_like_min": 60,
                    "moments_like_max": 120,
                    "random_moments_switch": False,
                    "random_moments_list": [],
                    "everyday_start_stop_bot_switch": False,
                    "everyday_start_bot_time": "08:00",
                    "everyday_stop_bot_time": "23:00",
                    "memory_switch": True,
                    "memory_max_count": 3000,
                    "memory_context_count": 1000,
                    "reply_delay_switch": True,
                    "reply_delay_min": 1,
                    "reply_delay_max": 5,
                    "chat_image_recognition_switch": False,
                    "chat_image_recognition_api": 0,
                    "group_image_recognition_switch": False,
                    "group_image_recognition_api": 0,
                    "api_error_reply": "在忙，我稍后回复您",
                    "chat_split_reply_switch": False,
                    "chat_split_max_chars": 100,
                    "chat_split_max_count": 4,
                    "group_split_reply_switch": False,
                    "group_split_max_chars": 100,
                    "group_split_max_count": 4,
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
        self.listen_list          = self.config.get('listen_list', [])
        self.AllListen_switch     = self.config.get('AllListen_switch')
        self.AllListen_filter_mute = bool(self.config.get('AllListen_filter_mute', True))

        # 群聊配置
        self.group                = self.config.get('group', [])
        self.group_api_map        = self.config.get('group_api_map', {})
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
        self.chat_keyword_switch   = self.config.get('chat_keyword_switch')
        self.group_keyword_switch  = self.config.get('group_keyword_switch')
        self.group_keyword_at_only = self.config.get('group_keyword_at_only', False)
        self.keyword_dict          = self.config.get('keyword_dict', {})

        # 定时消息配置
        self.scheduled_msg_switch = self.config.get('scheduled_msg_switch',
                                                     self.config.get('everyday_msg_switch', False))
        self.scheduled_msg_list   = self.config.get('scheduled_msg_list', [])

        # 定时朋友圈配置
        self.scheduled_moments_switch = self.config.get('scheduled_moments_switch', False)
        self.scheduled_moments_list   = self.config.get('scheduled_moments_list', [])

        # 随机朋友圈点赞配置
        self.moments_like_switch = self.config.get('moments_like_switch', False)
        self.moments_like_min    = max(1,    int(self.config.get('moments_like_min', 60)))
        self.moments_like_max    = max(self.moments_like_min, int(self.config.get('moments_like_max', 120)))

        # 随机定时朋友圈配置
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

        # 对话记忆配置
        self.memory_switch        = self.config.get('memory_switch', True)
        self.memory_max_count     = int(self.config.get('memory_max_count', 3000))
        self.memory_context_count = int(self.config.get('memory_context_count', 1000))

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

        # 图片识别配置
        self.chat_image_recognition_switch  = bool(self.config.get('chat_image_recognition_switch', False))
        self.chat_image_recognition_api     = int(self.config.get('chat_image_recognition_api', 0))
        self.group_image_recognition_switch = bool(self.config.get('group_image_recognition_switch', False))
        self.group_image_recognition_api    = int(self.config.get('group_image_recognition_api', 0))

        # 自定义转发配置
        self.custom_forward_switch = bool(self.config.get('custom_forward_switch', False))
        self.custom_forward_list   = self.config.get('custom_forward_list', [])

        # 多 Prompt 配置
        self.default_prompt   = self.config.get('default_prompt', '默认')
        self.chat_prompt_map  = self.config.get('chat_prompt_map', {})
        self.chat_api_map     = self.config.get('chat_api_map', {})
        self.group_prompt_map = self.config.get('group_prompt_map', {})
        self.init_prompt_dir()

        # 接口调用失败时的固定回复
        self.api_error_reply = self.config.get('api_error_reply', '在忙，我稍后回复您')

        # 拆分多条回复配置
        self.chat_split_reply_switch  = bool(self.config.get('chat_split_reply_switch', False))
        self.chat_split_max_chars     = max(1, int(self.config.get('chat_split_max_chars', 100)))
        self.chat_split_max_count     = max(1, int(self.config.get('chat_split_max_count', 4)))
        self.group_split_reply_switch = bool(self.config.get('group_split_reply_switch', False))
        self.group_split_max_chars    = max(1, int(self.config.get('group_split_max_chars', 100)))
        self.group_split_max_count    = max(1, int(self.config.get('group_split_max_count', 4)))

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

    def clear_messages(self, chat_name):
        """清空指定会话的对话记忆"""
        path = self._get_memory_path(chat_name)
        with self._get_lock(chat_name):
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump([], f, ensure_ascii=False)
            except Exception:
                pass

    def clear_all_messages(self):
        """清空所有会话的对话记忆，返回清除的会话数"""
        count = 0
        base = os.path.join(self.base_path, self.wx_id)
        if not os.path.exists(base):
            return count
        for chat_dir in os.listdir(base):
            memory_file = os.path.join(base, chat_dir, f"{chat_dir}_memory.json")
            if os.path.exists(memory_file):
                try:
                    with open(memory_file, 'w', encoding='utf-8') as f:
                        json.dump([], f, ensure_ascii=False)
                    count += 1
                except Exception:
                    pass
        return count


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
                raw = h.get('content', '')
                sender = h.get('sender', '')
                if role == 'user' and sender:
                    content = f"[{t}] {sender}: {raw}" if t else f"{sender}: {raw}"
                else:
                    content = f"[{t}] {raw}" if t else raw
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
            return "API返回错误，请稍后再试"

        except Exception as e:
            log(level="ERROR", message=f"备用方案也失败 [{type(e).__name__}]: {str(e)}")
            return "API返回错误，请稍后再试"


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

    def chat(self, message, model=None, stream=False, prompt=None, history=None,
             image_path: str = "", image_url: str = ""):
        if model is None:
            model = self.DS_NOW_MOD
        if not prompt:
            # fallback：尝试从 prompt 目录读取默认 prompt
            prompt = getattr(self.config, 'get_prompt_content', lambda n: '')(
                getattr(self.config, 'default_prompt', '默认')
            )

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
                raw = h.get('content', '')
                sender = h.get('sender', '')
                if role == 'user' and sender:
                    content = f"[{t}] {sender}: {raw}" if t else f"{sender}: {raw}"
                else:
                    content = f"[{t}] {raw}" if t else raw
                messages.append({"role": role, "content": content})
        # 构建 user_content（支持图片多模态）
        if image_path or image_url:
            user_content = [
                self.build_image_block(image_path, image_url),
                {"type": "text", "text": message},
            ]
        else:
            user_content = message
        messages.append({"role": "user", "content": user_content})
        payload = {
            "model": model,
            "max_tokens": 200000,
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
                response = requests.post(api_endpoint, headers=headers, json=payload, timeout=600)
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
                        return "API返回错误，请稍后再试"

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

        return "API返回错误，请稍后再试"


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
        self.api_cache = {}                     # 群组专属接口缓存 {api_index: api_instance}

        self.wx                  = None         # WeChat 客户端对象（延迟初始化）
        self._moments_like_next_time  = None    # 下次随机朋友圈点赞的触发时间（datetime 或 None）
        self._random_moments_state    = {}     # 随机定时朋友圈运行状态缓存 {task_id: state_dict}
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
        """根据配置中的 api_sdk 字段实例化对应的 AI 接口对象（默认接口）"""
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
        sdk = cfg.get('sdk', 'DusAPI')

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
        elif sdk == "OpenAI SDK":
            return OpenAIAPI(tmp)
        elif sdk == "Coze":
            return CozeAPI(tmp)
        elif sdk == "DusAPI":
            return DusAPI(tmp)
        else:
            return OpenAIAPI(tmp)

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
        self.wx.StopListening()
        time.sleep(1)
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
                    _res = self.wx.AddListenChat(nickname=_source, callback=self.message_handle_callback)
                    if _res:
                        log(message=f"添加自定义转发监听源 {_source} 完成")
                    else:
                        log(level="ERROR", message=f"添加自定义转发监听源 {_source} 失败")

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

        # 注册定时朋友圈任务
        if self.config.scheduled_moments_switch:
            log(message="定时朋友圈注册...")
            try:
                schedule.clear('scheduled_moments')
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

                    schedule.every().day.at(time_str).do(
                        self.send_scheduled_moments,
                        text, images, privacy, tags, repeat_type, weekdays, dates, task_id
                    ).tag('scheduled_moments')
                    log(message=f"注册定时朋友圈：{repeat_type} {time_str}")
                log(message="定时朋友圈注册完成")
            except Exception as e:
                log(level="ERROR", message=f"定时朋友圈注册失败：{e}")

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

        if not should_send:
            return schedule.CancelJob if repeat_type == 'once' else None

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
            for task in self.config.scheduled_moments_list:
                if task.get('id') == task_id:
                    task['enabled'] = False
                    break
            self.config.config['scheduled_moments_list'] = self.config.scheduled_moments_list
            self.config.save_config()
            log(message=f"一次性定时朋友圈任务 {task_id} 已执行完毕，自动禁用")
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
                'week_cache':   None,   # {'key': (year, week), 'days': [...]}
                'month_cache':  None,   # {'key': (year, month), 'days': [...]}
            })

            # --- 判断今天是否是发送日 ---
            repeat_type       = task.get('repeat_type', 'daily')
            random_days_count = max(1, int(task.get('random_days_count', 1)))
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

            # --- 还没计算今天的触发时间，则随机生成一个 ---
            if state['next_fire'] is None:
                time_start = task.get('time_start', '00:00')
                time_end   = task.get('time_end',   '23:59')
                try:
                    h_s, m_s   = map(int, time_start.split(':'))
                    h_e, m_e   = map(int, time_end.split(':'))
                    start_mins = h_s * 60 + m_s
                    end_mins   = h_e * 60 + m_e
                    if start_mins >= end_mins:
                        end_mins = start_mins + 1
                    fire_mins  = random.randint(start_mins, end_mins)
                    fire_h, fire_m = divmod(fire_mins, 60)
                    fire_dt    = now.replace(hour=fire_h, minute=fire_m,
                                            second=random.randint(0, 59), microsecond=0)
                    # 若随机时刻已过，则今天在当前时刻后 10 秒触发（避免错过）
                    if fire_dt <= now:
                        fire_dt = now + timedelta(seconds=10)
                    state['next_fire'] = fire_dt
                    log(message=f"随机朋友圈 {task_id}：今天计划于 {fire_dt.strftime('%H:%M:%S')} 发布")
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
                # 根据当前会话类型决定是否需要下载图片（识别开关关闭时跳过下载）
                # 纯自定义转发来源（不在群组、白名单、全局动态列表中、全局模式在黑名单）不下载图片
                _is_group = chat.who in self.config.group
                if _is_group:
                    _img_enabled = self.config.group_image_recognition_switch
                elif not self.config.AllListen_switch and chat.who in self.config.listen_list: # 白名单
                    _img_enabled = self.config.chat_image_recognition_switch
                elif (self.config.AllListen_switch and chat.who not in self.config.listen_list and chat.chat_type == 'friend'): # 全局黑名单且排除自定义转发监听来源的群聊
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
                result = self.process_message(chat, msg)
                # 自定义规则转发处理（在普通消息处理完成后执行，不影响原有流程）
                if self.config.custom_forward_switch:
                    try:
                        self._handle_custom_forward(chat, msg)
                    except Exception as _fwd_e:
                        log(level="ERROR", message=f"自定义转发处理出错: {_fwd_e}")
                if not result:
                    self.is_err(
                        self.wx.nickname + f" wxbot处理监听新消息失败！",
                        text + '\n' + result['message'],
                    )

            elif msg.attr == "system":
                # 系统消息：触发群新人欢迎语逻辑（仅限已配置群组，纯转发来源群组跳过）
                if self.config.group_welcome and chat.who in self.config.group:
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
                            result = chat.SendMsg(msg=self.config.keyword_dict[keyword])
                            self.msg_replied_count += 1
                            time.sleep(1)
                            return result
            
            if (self.config.AtMe in message.content and self.config.group_reply_at) \
                    or not self.config.group_reply_at:
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
                        if message.type == 'image':
                            # 直接图片消息：content 已被替换为本地路径
                            rec_api = self._init_api_by_index(self.config.group_image_recognition_api)
                            reply = rec_api.chat(
                                f"{message.sender}: 请简短描述这张图片的内容",
                                prompt=_effective_group_prompt,
                                history=history,
                                image_path=message.content
                            )
                        elif '+引用的图片:' in content_without_at:
                            # 引用图片消息：拆分文字部分和图片路径
                            text_part, img_path = content_without_at.split('+引用的图片:', 1)
                            rec_api = self._init_api_by_index(self.config.group_image_recognition_api)
                            reply = rec_api.chat(
                                f"{message.sender}: {text_part.strip()}" if text_part.strip() else f"{message.sender}: 请简短描述这张图片的内容",
                                prompt=_effective_group_prompt,
                                history=history,
                                image_path=img_path.strip()
                            )
                        else:
                            # 普通文字消息，走原有群组逻辑
                            group_api = self._get_group_api(chat.who)
                            reply = group_api.chat(content_with_sender, prompt=_effective_group_prompt, history=history)
                    else:
                        # 识别关闭：图片消息静默跳过，文字正常
                        # if message.type == 'image' or '+引用的图片:' in content_without_at:
                            # return result
                        group_api = self._get_group_api(chat.who)
                        reply = group_api.chat(content_with_sender, prompt=_effective_group_prompt, history=history)
                except Exception as e:
                    print(traceback.format_exc())
                    log(level="ERROR", message=str(e) + "\n群组中调用AI回复错误！！")
                    reply = "API返回错误，请稍后再试"

                # 接口调用失败时替换为配置的固定回复
                if reply == "API返回错误，请稍后再试":
                    reply = self.config.api_error_reply

                # 拆分多条回复：首条 @ 发言人，后续条不 @
                if self.config.group_split_reply_switch:
                    parts = self._parse_split_reply(reply, self.config.group_split_max_count)
                else:
                    parts = [reply]

                for i, part in enumerate(parts):
                    self.config.human_delay()   # 每条发送前都延迟（含第一条，与原逻辑等效）
                    result = chat.SendMsg(msg=part, at=message.sender if i == 0 else None)

                self.msg_replied_count += 1
                return result

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
            (self.config.AllListen_switch and chat.chat_type != 'friend'):
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
                            message.forward(target, message=src_msg)
                        else:
                            message.forward(target)
                        log(message=f"[自定义转发] {chat.who} → {target}（规则类型：{rule_type}，附带来源：{forward_with_source}）")

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
                    if message.type == 'image':
                        # 直接图片消息：content 已被替换为本地路径（图片识别优先使用图片识别接口）
                        rec_api = self._init_api_by_index(self.config.chat_image_recognition_api)
                        reply = rec_api.chat(
                            "请简短描述这张图片的内容",
                            prompt=_effective_prompt,
                            history=history,
                            image_path=message.content
                        )
                    elif '+引用的图片:' in message.content:
                        # 引用图片消息：拆分文字部分和图片路径
                        text_part, img_path = message.content.split('+引用的图片:', 1)
                        rec_api = self._init_api_by_index(self.config.chat_image_recognition_api)
                        reply = rec_api.chat(
                            text_part.strip() or "请简短描述这张图片的内容",
                            prompt=_effective_prompt,
                            history=history,
                            image_path=img_path.strip()
                        )
                    else:
                        # 普通文字消息：使用用户专属接口和 prompt
                        reply = self._get_chat_api(chat.who).chat(message.content, prompt=_effective_prompt, history=history)
                else:
                    # 识别关闭：图片消息静默跳过，文字消息正常
                    # if message.type == 'image' or '+引用的图片:' in message.content:
                        # return True
                    reply = self._get_chat_api(chat.who).chat(message.content, prompt=_effective_prompt, history=history)
        except Exception as e:
            print(traceback.format_exc())
            log(level="ERROR", message=str(e) + "\nAPI返回错误，请稍后再试")
            reply = "API返回错误，请稍后再试"

        # 接口调用失败时替换为配置的固定回复
        if reply == "API返回错误，请稍后再试":
            reply = self.config.api_error_reply

        # 拆分多条回复：仅在开关开启且回复包含分隔符时生效
        if self.config.chat_split_reply_switch:
            parts = self._parse_split_reply(reply, self.config.chat_split_max_count)
        else:
            parts = [reply]

        for part in parts:
            self.config.human_delay()   # 每条发送前都延迟（含第一条，与原逻辑等效）
            if len(part) >= 2000:
                for segment in self.config.split_long_text(part):
                    result = chat.SendMsg(segment)
            else:
                result = chat.SendMsg(part)

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
            _default_content = self.config.get_prompt_content(self.config.default_prompt)
            result = chat.SendMsg(f'当前默认AI设定（{self.config.default_prompt}）：\n' + _default_content)
        elif content.startswith("/更改AI设定为") or content.startswith("/更改ai设定为"):
            result = self.handle_change_prompt(chat, message)
        elif content == "/更新配置":
            self.config.refresh_config()
            self.api_cache = {}   # 配置已更新，清除群组接口缓存
            self.init_wx_listeners()
            result = chat.SendMsg(content + ' 完成\n')
        elif content == "/当前版本":
            result = chat.SendMsg(
                content + 'wxbot_' + self.ver + '\n' + self.ver_log + '\n作者:https://www.siver.top'
            )
        elif content in ("/指令", "指令"):
            result = self.send_command_list(chat)
        elif content == "/系统状态指令":
            result = chat.SendMsg(
                '--- 系统状态 ---\n'
                '[/状态] 完整运行状态摘要\n'
                '[/接口测试 内容] 测试当前AI接口\n'
                '[/当前版本] 版本号及更新说明\n'
                '[/更新配置] 重载配置并重初始化监听'
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
                '[/开启群聊关键词@触发] / [/关闭群聊关键词@触发]'
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
        elif content == "/状态":
            result = self._build_status_msg(chat, message)
        elif content == "/关键词状态":
            priv = "开启" if self.config.chat_keyword_switch else "关闭"
            grp  = "开启" if self.config.group_keyword_switch else "关闭"
            at   = "是"   if self.config.group_keyword_at_only else "否"
            cnt  = len(self.config.keyword_dict)
            keys = ", ".join(self.config.keyword_dict.keys()) if self.config.keyword_dict else "（无）"
            result = chat.SendMsg(
                f"私聊关键词：{priv}\n"
                f"群聊关键词：{grp}\n"
                f"群聊仅@触发：{at}\n"
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
        elif content.startswith("/接口测试"):
            message_re = message
            message_re.content = re.sub("/接口测试", "", message.content).strip()
            result = self.wx_send_ai(chat, message_re)
        # --- Prompt 管理 ---
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
        if self.config.group_keyword_switch:
            send_msg += "群聊关键词仅@触发：" + ("是\n" if self.config.group_keyword_at_only else "否\n")
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
        send_msg += "新好友自动通过：" + ("开启" if self.config.new_frined_switch else "关闭")
        send_msg += "  自动回复：" + ("开启\n" if self.config.new_frien_reply_switch else "关闭\n")

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
        accept = "开启" if self.config.new_frined_switch      else "关闭"
        reply  = "开启" if self.config.new_frien_reply_switch else "关闭"
        msgs   = self.config.new_frien_msg if self.config.new_frien_msg else ["（无）"]
        lines  = [
            "--- 新好友状态 ---",
            f"自动通过好友申请：{accept}",
            f"自动回复新好友：{reply}",
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
            '/图片识别指令\n'
            '/拆分回复指令\n'
            '/新好友指令\n'
            '/接口指令\n'
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
                new_name = new.name + '_机器人备注'
                # new_name = datetime.now().strftime('%Y%m%d%H%M%S') + '_机器人备注'
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
        log(message=chat + ' 不在动态监听列表，正在添加进列表')
        self.all_Mode_listen_list.append([chat, time.time()])
        log(message='当前全局模式动态监听列表：' + str(self.all_Mode_listen_list))
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

        def remove_timeout_listen(chat_time_out=600):
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
            Next_callback_down_map = {}  # {msg.id: save_path}
            def Next_callback(msg):
                nonlocal Next_callback_down_map
                # 排除群聊再下载
                if self.wx.chat_type == 'friend':
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
                        
                        # 自定义规则转发：必须在 add_chat_to_listen 之前执行
                        # msg.forward() 依赖主窗口上下文，加入监听后上下文切换到子窗口会失效
                        if self.config.custom_forward_switch:
                            try:
                                import types as _types
                                self._handle_custom_forward(_types.SimpleNamespace(who=chat), msg)
                            except Exception as _fwd_e:
                                log(level="ERROR", message=f"自定义转发处理出错: {_fwd_e}")
                        
                        if not self.is_chat_listened(chat):
                            self.add_chat_to_listen(chat)
                        else:
                            log(message=chat + '在监听列表')
                        _sub_chat = self.wx.GetSubWindow(nickname=chat)
                        self.process_message(_sub_chat, msg)

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
            "chat_keyword_switch":   self.config.chat_keyword_switch,
            "group_keyword_switch":  self.config.group_keyword_switch,
            "group_keyword_at_only": self.config.group_keyword_at_only,
            "keyword_count":         len(self.config.keyword_dict),
            "memory_switch":         self.config.memory_switch,
            "memory_context_count":  self.config.memory_context_count,
            "reply_delay_switch":    self.config.reply_delay_switch,
            "reply_delay_min":       self.config.reply_delay_min,
            "reply_delay_max":       self.config.reply_delay_max,
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
            log(level="ERROR", message=str(e) + "\n 初始化微信监听器失败，请检查微信是否启动登录正确，微信主窗口是否开着")
            log(level="ERROR", message=str(e) + "\n 初始化微信监听器失败，请检查微信是否启动登录正确，微信主窗口是否开着")
            log(level="ERROR", message=str(e) + "\n 请尝试退出wx再重新登录后再启动")
            log(level="ERROR", message=str(e) + "\n 请尝试退出wx再重新登录后再启动")
            log(level="ERROR", message=str(e) + "\n 若重启wx还是不行，就请重启整个面板程序，面板和wx都重启了还不行就请进入面板右上角文档检查环境要求，wx版本是否匹配,4.1.7 ~ 4.1.8.101")
            log(level="ERROR", message=str(e) + "\n 若重启wx还是不行，就请重启整个面板程序，面板和wx都重启了还不行就请进入面板右上角文档检查环境要求，wx版本是否匹配,4.1.7 ~ 4.1.8.101")
            log(level="ERROR", message=str(e) + "\n 若重启wx还是不行，就请重启整个面板程序，面板和wx都重启了还不行就请进入面板右上角文档检查环境要求，wx版本是否匹配,4.1.7 ~ 4.1.8.101")
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
                    # 将秒数阈值除以循环周期得到循环次数（取整，最小1次）
                    check_new_friend_time_MIN = max(1, int(30 / wait_time))
                    check_new_friend_time_MAX = max(check_new_friend_time_MIN, int(300 / wait_time))
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

                # ---- 定时任务执行（定时消息 / 定时朋友圈）----
                if self.config.scheduled_msg_switch or self.config.scheduled_moments_switch:
                    schedule.run_pending()

                # ---- 随机定时朋友圈模块 ----
                if self.config.random_moments_switch:
                    try:
                        self._check_random_moments()
                    except Exception as e:
                        log(level="ERROR", message=f"随机定时朋友圈模块出错：{e}")
                else:
                    self._random_moments_state = {}  # 开关关闭时清空缓存

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
