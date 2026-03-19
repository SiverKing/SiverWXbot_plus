#!/usr/bin/env python3
# Siver微信机器人 siver_wxbot - 面向对象版本 - wxautox V2版本
# 作者：https://siver.top

version = "V4.2.0"
version_log = "V4.2.0 UI重构、定时消息重构为完全自定义"

# ============================================================
# 标准库导入
# ============================================================
import os
import re
import time
import json
import random
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
# 购买地址：https://github.com/cluic/wxauto
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
        self.CONFIG_FILE = 'config.json'
        self.config = {}

        # ---------- 全局监听开关 ----------
        self.AllListen_switch = False   # True=黑名单模式，False=白名单模式

        # ---------- 用户与权限 ----------
        self.listen_list = []           # 白名单/黑名单用户列表
        self.cmd = ""                   # 管理员账号（命令接收者）

        # ---------- AI 接口配置 ----------
        self.api_sdk = ""               # API SDK 类型（OpenAI / Dify / Coze）
        self.api_key = ""               # API 密钥
        self.base_url = ""              # API 请求基础地址
        self.model1 = ""                # 模型标识 1
        self.model2 = ""                # 模型标识 2
        self.prompt = ""                # AI 系统提示词
        self.AtMe = ""                  # 机器人被 @ 的标识（如 "@机器人昵称"）

        # ---------- 群聊配置 ----------
        self.group = []                 # 监听的群聊列表
        self.group_switch = False       # 群机器人总开关
        self.group_reply_at = False     # 群聊是否仅在被 @ 时才回复
        self.group_welcome = False      # 群新人欢迎语开关
        self.group_welcome_random = 1.0 # 群新人欢迎语触发概率（0.0~1.0）
        self.group_welcome_msg = "欢迎新朋友！请先查看群公告！本消息由wxautox发送!"

        # ---------- 新好友配置 ----------
        self.new_frined_switch = False  # 自动通过新好友开关
        self.new_frien_msg = []         # 通过后自动发送的打招呼消息列表

        # ---------- 关键词回复配置 ----------
        self.chat_keyword_switch = False    # 私聊关键词回复开关
        self.group_keyword_switch = False   # 群聊关键词回复开关
        self.keyword_dict = {}              # 关键词 -> 回复内容 字典

        # ---------- 定时消息配置 ----------
        self.scheduled_msg_switch = False    # 定时消息总开关
        self.scheduled_msg_list = []         # 定时消息任务列表

        # 初始化时自动加载配置并同步到属性
        self.load_config()
        self.update_global_config()

    # ----------------------------------------------------------
    # 配置文件读写
    # ----------------------------------------------------------

    def load_config(self):
        """从 config.json 加载配置到 self.config 字典"""
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
                # 默认配置模板（新版配置格式）
                base_config = {
                    "api_key": "your-api-key",
                    "base_url": "https://api.example.com/v1",
                    "model1": "模型名称1",
                    "model2": "模型名称2",
                    "prompt": "你是一个ai回复助手，请根据用户的问题给出回答",
                    "管理员": "管理员",
                    "全局监听开关": False,
                    "用户列表": [],
                    "group": [],
                    "group_switch": False,
                    "群聊是否仅被@时回复": False,
                    "群新人欢迎语开关": False,
                    "群新人欢迎语": "欢迎新朋友！请先查看群公告！本消息由wxautox发送!",
                    "自动通过好友开关": False,
                    "通过好友打招呼语": ["你好", "我是wxauto", "有什么问题尽管问我", "", ""],
                    "备忘录1": "",
                    "备忘录2": "",
                }
                with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(base_config, f, ensure_ascii=False, indent=4)
                log(message=f"已创建默认配置文件：\n{os.path.abspath(self.CONFIG_FILE)}\n请根据需求修改配置")
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
        # AI 接口相关
        self.api_sdk  = self.config.get('api_sdk', "")
        self.api_key  = self.config.get('api_key', "")
        self.base_url = self.config.get('base_url', "")
        self.model1   = self.config.get('model1', "")
        self.model2   = self.config.get('model2', "")
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
        self.new_frined_switch = self.config.get('new_friend_switch')
        self.new_frien_msg     = self.config.get('new_friend_msg', [])

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
                        'target': target,
                        'time': task.get('time', '08:00'),
                        'repeat_type': 'daily',
                        'weekdays': [],
                        'dates': [],
                        'msgs': task.get('msgs', []),
                    })

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

    @staticmethod
    def get_run_time(start_time):
        """计算并返回自 start_time 至今的运行时长，格式：X天X时X分X秒"""
        delta = datetime.now() - start_time
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{days}天{hours}时{minutes}分{seconds}秒"


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

    def chat(self, message, model=None, stream=False, prompt=None):
        """
        调用 OpenAI 兼容接口获取 AI 回复。

        :param message: 用户输入的消息内容
        :param model:   指定模型，为 None 时使用当前默认模型
        :param stream:  是否使用流式输出
        :param prompt:  系统提示词，为 None 时使用配置中的 prompt
        :return:        AI 回复的文本字符串
        """
        if model is None:
            model = self.DS_NOW_MOD
        if prompt is None:
            prompt = self.config.prompt

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user",   "content": message},
                ],
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

    def chat(self, message, model=None, stream=True, prompt=None):
        """
        调用 Dify 对话接口，返回 AI 回复文本。

        :param message: 用户输入内容
        :return:        AI 回复字符串
        """
        # 以阻塞模式请求 Dify 接口
        response = self.run_dify_conversation(
            query=message,
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

    def chat(self, message, model=None, stream=True, prompt=None):
        """
        调用扣子流式接口获取 AI 回复，并拼接完整的回答文本。

        :param message: 用户输入内容
        :return:        AI 回复字符串
        """
        chunk_message = ""
        try:
            for event in self.coze.chat.stream(
                bot_id=self.bot_id,
                user_id=self.user_id + str(time.time()),  # 用时间戳保证 user_id 唯一
                additional_messages=[
                    CozeMessage.build_user_question_text(message),
                ],
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
        self.all_Mode_listen_list = []           # 全局模式下的动态监听列表，元素格式：[昵称, 最新消息时间戳]
        self.start_time          = datetime.now()
        self.callback_is_die     = False        # 回调函数是否发生致命错误的标志
        self.msgs_path           = './wx_msgs/' # 消息本地存储路径（当前未启用）

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
            self.wx.Show()  # 首次强制弹出主窗口以获取焦点

        # 绑定 @ 标识（格式："@机器人昵称"）
        self.config.AtMe = "@" + self.wx.nickname
        log(message='绑定@：' + self.config.AtMe)

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
                    target      = task.get('target', '')
                    repeat_type = task.get('repeat_type', 'daily')
                    task_id     = task.get('id', '')
                    weekdays    = task.get('weekdays', [])
                    dates       = task.get('dates', [])

                    schedule.every().day.at(time_str).do(
                        self.send_scheduled_msg, target, msgs, repeat_type, weekdays, dates, task_id
                    ).tag('scheduled_msg')
                    log(message=f"注册定时消息：{repeat_type} {time_str} 给 {target} 发消息")
                log(message="定时消息注册完成")
            except Exception as e:
                log(level="ERROR", message=f"定时消息注册失败：{e}")

        log(message="监听器初始化完成")

    # ----------------------------------------------------------
    # 定时消息发送
    # ----------------------------------------------------------

    def send_scheduled_msg(self, user, msgs, repeat_type, weekdays, dates, task_id):
        """
        定时触发的消息发送函数，根据 repeat_type 判断今天是否需要发送。

        :param user:        接收消息的用户/群组昵称
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

        log(message=f"{user} 定时消息时间到（{repeat_type}），正在发送...")
        for msg in msgs:
            log(message=f"正在向 {user} 发送定时消息：{msg}")
            try:
                result = self.wx.SendMsg(msg=msg, who=user)
                time.sleep(random.randint(1, 3))  # 每条消息间随机延时，模拟人工操作
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
                    reply = self.api.chat(content_without_at, prompt=self.config.prompt)
                except Exception as e:
                    print(traceback.format_exc())
                    log(level="ERROR", message=str(e) + "\n群组中调用AI回复错误！！")
                    reply = "请稍后再试"
                time.sleep(random.randint(1, 10))  # 随机延时，模拟人工回复
                result = chat.SendMsg(msg=reply, at=message.sender)
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
                # 未命中关键词，调用 AI 接口
                reply = self.api.chat(message.content, prompt=self.config.prompt)
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
            time.sleep(random.randint(1, 10))  # 随机延时，模拟人工回复节奏
            result = chat.SendMsg(reply)
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

        if "/添加用户" in content:
            result = self.handle_add_user(chat, message)
        elif "/删除用户" in content:
            result = self.handle_remove_user(chat, message)
        elif content == "/当前用户":
            result = chat.SendMsg(content + '\n' + ", ".join(self.config.listen_list))
        elif content == "/当前群":
            result = chat.SendMsg(content + '\n' + ", ".join(self.config.group))
        elif content == "/群机器人状态":
            result = self.handle_group_switch_status(chat, message)
        elif "/添加群" in content:
            result = self.handle_add_group(chat, message)
        elif "/删除群" in content:
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
            result = chat.SendMsg(content + '\n' + self.config.group_welcome_msg)
        elif "/更改群机器人欢迎语为" in content:
            result = self.handle_change_welcome_msg(chat, message)
        elif content == "/当前模型":
            result = chat.SendMsg(content + " " + self.api.DS_NOW_MOD)
        elif content == "/切换模型1":
            result = self.handle_switch_model(chat, message, self.config.model1)
        elif content == "/切换模型2":
            result = self.handle_switch_model(chat, message, self.config.model2)
        elif content == "/当前AI设定":
            result = chat.SendMsg('当前AI设定：\n' + self.config.prompt)
        elif "/更改AI设定为" in content or "/更改ai设定为" in content:
            result = self.handle_change_prompt(chat, message)
        elif content == "/更新配置":
            self.config.refresh_config()
            self.init_wx_listeners()
            result = chat.SendMsg(content + ' 完成\n')
        elif content == "/当前版本":
            result = chat.SendMsg(
                content + 'wxbot_' + self.ver + '\n' + self.ver_log + '\n作者:https://siver.top'
            )
        elif content in ("/指令", "指令"):
            result = self.send_command_list(chat)
        elif content == "/状态":
            result = self._build_status_msg(chat, message)
        else:
            # 未匹配到任何指令，当作普通消息交给 AI 回复
            result = self.wx_send_ai(chat, message)

        return result

    def _build_status_msg(self, chat, message):
        """
        构建并发送机器人当前状态摘要信息。
        （从 process_command 中抽离，降低单函数复杂度）
        """
        send_msg = "运行时间：" + self.config.get_run_time(self.start_time) + "\n"

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
                return chat.SendMsg(message.content + ' 完成\n' + ", ".join(self.config.listen_list))
            else:
                # 注册失败则回滚配置
                self.config.remove_user(user_to_add)
                log(level="ERROR", message=f"添加用户 {user_to_add} 监听失败, {result['message']}")
                return chat.SendMsg(
                    message.content + f" 失败\n{result['message']}\n" + ", ".join(self.config.listen_list)
                )
        else:
            # 黑名单模式下只更新配置，无需注册监听
            return chat.SendMsg(message.content + ' 完成(黑名单)\n' + ", ".join(self.config.listen_list))

    def handle_remove_user(self, chat, message):
        """处理 /删除用户 指令：移除用户的监听注册并从配置中删除"""
        user_to_remove = re.sub("/删除用户", "", message.content).strip()
        self.wx.RemoveListenChat(user_to_remove)
        self.config.remove_user(user_to_remove)
        return chat.SendMsg(message.content + ' 完成\n' + ", ".join(self.config.listen_list))

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
                return chat.SendMsg(message.content + ' 完成\n' + ", ".join(self.config.group))
            else:
                # 注册失败则回滚配置
                self.config.remove_group(new_group)
                log(level="ERROR", message=f"添加群组 {new_group} 监听失败, {result['message']}")
                return chat.SendMsg(
                    message.content + f" 失败\n{result['message']}\n" + ", ".join(self.config.group)
                )
        else:
            return chat.SendMsg(message.content + ' 完成(群机器人未开启)\n' + ", ".join(self.config.group))

    def handle_remove_group(self, chat, message):
        """处理 /删除群 指令：移除群组的监听注册并从配置中删除"""
        group_to_remove = re.sub("/删除群", "", message.content).strip()
        self.wx.RemoveListenChat(group_to_remove)
        self.config.remove_group(group_to_remove)
        return chat.SendMsg(message.content + ' 完成\n' + ", ".join(self.config.group))

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

    def handle_switch_model(self, chat, message, model):
        """处理切换模型指令：更新当前使用的 AI 模型"""
        self.api.DS_NOW_MOD = model
        return chat.SendMsg(message.content + ' 完成\n当前模型:' + self.api.DS_NOW_MOD)

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
            '[/当前模型] （返回当前模型）\n'
            '[/切换模型1] （切换回复模型为配置中的 model1）\n'
            '[/切换模型2]\n'
            '[/当前AI设定] （返回当前AI设定）\n'
            '[/更改AI设定为***] （更改AI设定，***为AI设定）\n'
            '[/更新配置] （若在程序运行时修改过配置，请发送此指令以更新配置）\n'
            '[/当前版本] (返回当前版本)\n'
            '作者:https://siver.top  若有非法传播请告知'
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
        检测并批量通过新好友请求，通过后自动发送打招呼消息。
        消息中若包含图片路径则以文件形式发送，否则以文字发送。
        """
        NewFriends = self.wx.GetNewFriends(acceptable=True)
        time.sleep(1)
        if len(NewFriends) != 0:
            log(message="以下是新朋友：\n" + str(NewFriends))
            for new in NewFriends:
                new_name = new.name + '_机器人备注'
                new.accept(remark=new_name)  # 接受好友请求并设置备注
                log(message="已通过" + new.name + "的好友请求")
                self.wx.SwitchToChat()       # 通过请求后切换回聊天页面
                time.sleep(5)
                for msg in self.config.new_frien_msg:
                    if self.is_image_path(msg):
                        self.wx.SendFiles(who=new_name, filepath=msg)
                    else:
                        self.wx.SendMsg(who=new_name, msg=msg)
                    time.sleep(random.randint(1, 3))  # 随机延时，模拟人工操作
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
        log(message=f"wxbot\n版本: wxbot_{self.ver}\n作者: https://siver.top\n")

        # 激活授权校验
        if self.wxautox_activate_check():
            log(message="wxautox已激活")
        else:
            log(level="ERROR", message="wxautox未激活，请激活后再运行程序！！")
            return False

        # 初始化微信监听器
        try:
            self.init_wx_listeners()
            log(message=f"UI面板状态更新完成")

            wait_time      = 1   # 主循环每 1 秒轮询一次
            check_interval = 10  # 每 10 次循环执行一次离线检测
            check_counter      = 0
            check_new_counter  = 0
            last_time          = time.time()
            log(message='siver_wxbot初始化完成，开始监听消息(作者:https://siver.top)')
            self.run_flag = True
        except Exception as e:
            print(traceback.format_exc())
            log(level="ERROR", message=str(e) + "\n初始化微信监听器失败，请检查微信是否启动登录正确")
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
