#!/usr/bin/env python3
# Siver微信机器人 siver_wxbot - 面向对象版本 - wxautox V2版本
# 作者：https://siver.top
version = "V4.0.1"
version_log = "V4.0.1 fix:适配新版本全局监听"

import time
import json
import re
import traceback
import email_send
from openai import OpenAI
import requests
from datetime import datetime, timedelta
import random
from logger import log
import schedule # 定时任务库
import os
from cozepy import COZE_CN_BASE_URL # 扣子官方python库
from cozepy import Coze, TokenAuth, Message as CozeMessage, ChatStatus, MessageContentType, ChatEventType

from wxautox4 import WeChat  # plus版需要找wxauto作者购买 https://github.com/cluic/wxauto
is_wxautox = True  # 是否为wxautox 即plus版本
from wxautox4.msgs import *
from wxautox4 import WxParam
from wxautox4.utils.useful import check_license
WxParam.MESSAGE_HASH = True # 是否启用消息哈希值用于辅助判断消息，开启后会稍微影响性能，默认False
WxParam.FORCE_MESSAGE_XBIAS = True # 是否强制重新自动获取X偏移量，如果设置为True，则每次启动都会重新获取，默认False
'''
ENABLE_FILE_LOGGER ( bool ) ：是否启用日志文件，默认True
DEFAULT_SAVE_PATH ( str ) ：下载文件/图片默认保存路径，默认为当前工作目录下的wxautox文件下载文件夹
MESSAGE_HASH ( bool ) ：是否启用消息哈希值用于辅助判断消息，开启后会稍微影响性能，默认False
DEFAULT_MESSAGE_XBIAS ( int ) ：头像到消息X偏移量，用于消息定位，点击消息等操作，默认51
FORCE_MESSAGE_XBIAS ( bool ) ：是否强制重新自动获取X偏移量，如果设置为True，则每次启动都会重新获取，默认False
LISTEN_INTERVAL ( int ) ：监听消息时间间隔，单位秒，默认1
LISTENER_EXCUTOR_WORKERS ( int ) ：监听执行器线程池大小，根据自身需求和设备性能设置，默认4
SEARCH_CHAT_TIMEOUT ( int ) ：搜索聊天对象超时时间，单位秒，默认5
'''


class WXBotConfig:
    """微信机器人配置类"""
    def __init__(self):
        self.CONFIG_FILE = 'config.json'
        self.config = {}
        self.AllListen_switch = False  # 全局监听开关
        self.listen_list = []    # 用户列表
        self.api_sdk = ""        # API SDK
        self.api_key = ""        # API 密钥
        self.base_url = ""       # API 基础 URL
        self.AtMe = ""           # 机器人@的标识
        self.cmd = ""            # 命令接收账号（管理员）
        self.group = []          # 群聊ID
        self.group_reply_at = False  # 群聊回复@开关
        self.group_switch = False # 群机器人开关
        self.group_welcome = False # 群新人欢迎开关
        self.group_welcome_random = 1.0 # 群新人欢迎随机概率
        self.group_welcome_msg = "欢迎新朋友！请先查看群公告！本消息由wxautox发送!" # 群新人欢迎语
        self.new_frined_switch = False  # 新好友开关
        self.new_frien_msg = []  # 新好友消息列表
        self.model1 = ""         # 模型1标识
        self.model2 = ""         # 模型2标识
        self.prompt = ""         # AI提示词
        self.chat_keyword_switch = False  # 聊天关键词开关
        self.group_keyword_switch = False  # 群聊关键词开关
        self.keyword_dict = {}   # 关键词字典
        self.everyday_msg_switch = False  # 每日定时消息开关
        self.everyday_msg_dict = {}  # 每日定时消息字典
        self.load_config()
        self.update_global_config()

    def load_config(self):
        """从配置文件加载配置"""
        try:
            with open(self.CONFIG_FILE, 'r', encoding='utf-8') as file:
                self.config = json.load(file)
                log(message="配置文件加载成功")
        except Exception as e:
            log(level="ERROR", message="打开配置文件失败，请检查配置文件！" + str(e))
            while True:
                time.sleep(100)

    def create_new_config_file(self):
        """创建默认配置文件"""
        try:
            if not os.path.exists(self.CONFIG_FILE):
                # 默认配置字典（新版配置格式）
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
                    "备忘录2": ""
                }
                with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(base_config, f, ensure_ascii=False, indent=4)
                log(message=f"已创建默认配置文件：\n{os.path.abspath(self.CONFIG_FILE)}\n请根据需求修改配置")
        except Exception as e:
            log(level="ERROR", message="创建默认配置文件失败，请检查配置文件！" + str(e))
            while True:
                time.sleep(100)

    def update_global_config(self):
        """将 config 中的配置项更新到全局变量中"""
        # ai类
        self.api_sdk = self.config.get('api_sdk', "")
        self.api_key = self.config.get('api_key', "")
        self.base_url = self.config.get('base_url', "")
        self.model1 = self.config.get('model1', "")
        self.model2 = self.config.get('model2', "")
        self.prompt = self.config.get('prompt', "")
        # 微信类
        self.cmd = self.config.get('admin', "")
        self.listen_list = self.config.get('listen_list', [])
        self.AllListen_switch = self.config.get('AllListen_switch')
        # 群聊
        self.group = self.config.get('group', [])
        self.group_switch = self.config.get('group_switch')
        self.group_reply_at = self.config.get('group_reply_at')
        self.group_welcome = self.config.get('group_welcome')
        self.group_welcome_random = self.config.get('group_welcome_random')
        self.group_welcome_msg = self.config.get('group_welcome_msg', '')
        # 新好友
        self.new_frined_switch = self.config.get('new_friend_switch')
        self.new_frien_msg = self.config.get('new_friend_msg', [])
        #关键词
        self.chat_keyword_switch = self.config.get('chat_keyword_switch')
        self.group_keyword_switch = self.config.get('group_keyword_switch')
        self.keyword_dict = self.config.get('keyword_dict', {})
        # 每日定时消息
        self.everyday_msg_switch = self.config.get('everyday_msg_switch')
        self.everyday_msg_dict = self.config.get('everyday_msg_dict', {})
        log(message="全局配置更新完成")

    def save_config(self):
        """将当前的配置写回到配置文件"""
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as file:
                json.dump(self.config, file, ensure_ascii=False, indent=4)
        except Exception as e:
            log(level="ERROR", message="保存配置文件失败:" + str(e))

    def refresh_config(self):
        """刷新配置：重新加载配置文件并更新全局变量"""
        self.load_config()
        self.update_global_config()

    def add_user(self, name):
        """添加用户至监听列表"""
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

    def add_group(self, name):
        """添加群组至监听列表"""
        if name not in self.config.get('group', []):
            self.config['group'].append(name)
            self.save_config()
            self.refresh_config()
            log(message="添加后的监听群组列表:" + str(self.config['group']))
        else:
            log(message=f"群组 {name} 已在监听列表中")

    def remove_group(self, name):
        """删除群组从监听列表"""
        if name in self.config.get('group', []):
            self.config['group'].remove(name)
            self.save_config()
            self.refresh_config()
            log(message="删除后的监听群组列表:" + str(self.config['group']))
        else:
            log(message=f"群组 {name} 不在监听列表中")

    def set_group_switch(self, switch_value):
        """设置是否启用群机器人"""
        self.config['group_switch'] = switch_value
        self.save_config()
        self.refresh_config()
        log(message="群开关设置为" + str(self.config['group_switch']))

    def set_config(self, id, new_content):
        """更改配置"""
        self.config[id] = new_content
        self.save_config()
        self.refresh_config()
        log(message=id + "已更改为:" + str(self.config[id]))

    @staticmethod
    def now_time(time_format="%Y/%m/%d %H:%M:%S "):
        """获取当前时间"""
        return "" # 暂时采用公共类的log显示时间
        return datetime.now().strftime(time_format)

    @staticmethod
    def split_long_text(text, chunk_size=2000):
        """分割长文本"""
        return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

    @staticmethod
    def get_run_time(start_time):
        # 我要获取运行时间 格式为 日时分秒
        end_time = datetime.now()
        delta = end_time - start_time

        # 计算天数、小时、分钟和秒
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{days}天{hours}时{minutes}分{seconds}秒"


class OpenAIAPI:
    """OpenAI API 交互类"""
    def __init__(self, config):
        self.config = config
        self.DS_NOW_MOD = config.model1  # 默认使用模型1
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)

    def chat(self, message, model=None, stream=True, prompt=None):
        """
        调用 OpenAI API 获取对话回复
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
                    {"role": "user", "content": message},
                ],
                stream=stream
            )
        except Exception as e:
            log(level="ERROR", message="调用 API 出错:" + str(e))
            return "API返回错误，请稍后再试"
            # raise

        if stream:
            reasoning_content = ""
            content = ""
            for chunk in response:
                if not hasattr(chunk, 'choices') or not chunk.choices:
                    continue
                    
                delta = chunk.choices[0].delta
                
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    chunk_message = delta.reasoning_content
                    # log(message=chunk_message, end="", flush=True)
                    if chunk_message:
                        reasoning_content += chunk_message
                elif hasattr(delta, 'content') and delta.content:
                    chunk_message = delta.content
                    # log(message=chunk_message, end="", flush=True)
                    if chunk_message:
                        content += chunk_message
            log(message="API接口返回："+content.strip())
            # log(message="\n")
            return content.strip()

        else:
            output = response.choices[0].message.content
            log(message=output)
            return output
class DifyAPI:
    """Dify API 交互类"""
    def __init__(self, config):
        self.config = config
        self.DS_NOW_MOD = config.model1  # 默认使用模型1
        self.api_key = "Bearer " + config.api_key
        self.base_url = config.base_url
        # self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)

    def chat(self, message, model=None, stream=True, prompt=None):
        """
        调用 Dify API 获取对话回复
        """
        # print("=== 简单文本对话 ===")
        response = self.run_dify_conversation(
            query=message,
            response_mode="blocking"
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
        处理阻塞模式(blocking)的响应
        """
        if response_data.get("event") == "message":
            return {
                "success": True,
                "conversation_id": response_data.get("conversation_id"),
                "answer": response_data.get("answer", ""),
                "message_id": response_data.get("message_id"),
                "metadata": response_data.get("metadata", {}),
                "usage": response_data.get("usage", {}),
                "retriever_resources": response_data.get("retriever_resources", [])
            }
        else:
            return {
                "success": False,
                "error": f"Unexpected event type: {response_data.get('event')}",
                "raw_response": response_data
            }
    def run_dify_conversation(self,
        query=str,
        inputs={},
        conversation_id=None,
        files=[],
        auto_generate_name=True,
        response_mode="blocking"
    ):
        """
        执行Dify对话工作流API，严格遵循官方文档规范
        官方文档：https://docs.dify.ai/api/chat-messages
        
        :param query: 用户输入/提问内容
        :param inputs: App定义的变量值
        :param conversation_id: 会话ID（用于多轮对话）
        :param files: 文件列表（支持Vision能力）
        :param auto_generate_name: 是否自动生成标题
        :param response_mode: 响应模式（blocking/streaming）
        :return: API响应数据
        """
        # API端点
        # url = "http://121.37.67.153:8088/v1/chat-messages"
        url = self.base_url
        # 设置请求头
        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json"
        }
        
        # 构建符合文档要求的请求体
        payload = {
            "inputs": inputs,
            "query": query,
            "response_mode": response_mode,
            "user": "api-user",  # 用户标识
            "conversation_id": conversation_id,
            "auto_generate_name": auto_generate_name
        }
        
        # 添加文件参数（如果提供）
        if files:
            payload["files"] = files
        
        try:
            # 发送请求
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()  # 检查HTTP错误
            
            # 解析响应
            if response_mode == "blocking":
                return response.json()
            else:
                # 流式响应需要特殊处理（此处只返回原始响应）
                return {"raw_stream": response.text}
                
        except requests.exceptions.RequestException as e:
            # 详细的错误处理
            error_info = {
                "error_type": "request_error",
                "message": str(e)
            }
            
            if e.response is not None:
                try:
                    error_data = e.response.json()
                    error_info.update({
                        "status_code": e.response.status_code,
                        "error_code": error_data.get("code", "unknown"),
                        "api_message": error_data.get("message", "No error details")
                    })
                except:
                    error_info["response_text"] = e.response.text
                    
            return {"success": False, "error": error_info}
class CozeAPI:
    """Coze API 交互类"""
    def __init__(self, config):
        self.config = config
        self.DS_NOW_MOD = config.model1  # 默认使用模型1
        self.bot_id = config.model1 # 在 Coze 中创建一个机器人实例，从网页链接中复制最后一个数字作为机器人的 ID 。
        self.user_id = "SiverWxBot" # 机器人用户标识
        self.api_key = config.api_key
        self.base_url = COZE_CN_BASE_URL # 采用扣子官方定义api地址
        # self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.coze = Coze(auth=TokenAuth(token=self.api_key), base_url=self.base_url) # 实例化扣子api对象

    def chat(self, message, model=None, stream=True, prompt=None):
        """
        调用 Coze API 获取对话回复
        """
        # 调用 coze.chat.stream 方法来创建一个聊天。该 create 方法属于流式传输类型。
        # 聊天，并将返回一个聊天迭代器。开发人员应使用该迭代器进行迭代以获取……
        # 记录聊天事件并进行处理。
        chunk_message = ""
        try:
            for event in self.coze.chat.stream(
                bot_id=self.bot_id,
                user_id=self.user_id+str(time.time()),
                additional_messages=[
                    CozeMessage.build_user_question_text(message),
                ],
            ):
                if event.event == ChatEventType.CONVERSATION_MESSAGE_DELTA:
                    # print(event.message.content, end="", flush=True)
                    chunk_message += event.message.content # 拼接流式回答
                    

                if event.event == ChatEventType.CONVERSATION_CHAT_COMPLETED:
                    # print()
                    log(f"token消耗:{event.chat.usage.token_count}")

            log(f"扣子回复：{chunk_message}")
            return chunk_message
        except Exception as e:
            log(level="ERROR", message=f"❌ 调用Coze接口错误: {e}")
            return "API返回错误，请稍后再试"

class WXBot:
    """微信机器人主类"""
    def __init__(self):

        self.ver = version
        self.ver_log = version_log
        self.run_flag = True
        self.config = WXBotConfig()
        if self.config.api_sdk == "Dify":
            log(message="使用Dify API")
            self.api = DifyAPI(self.config)
        elif self.config.api_sdk == "OpenAI SDK":
            log(message="使用OpenAI SDK")
            self.api = OpenAIAPI(self.config)
        elif self.config.api_sdk == "Coze":
            log(message="使用Coze API")
            self.api = CozeAPI(self.config)
        else:
            log(level="ERROR", message="未配置API SDK, 默认使用OpenAI SDK")
            self.api = OpenAIAPI(self.config)
        self.wx = None
        self.all_Mode_listen_list = [] # 全局模式的动态·监听列表
        self.start_time = datetime.now()
        self.callback_is_die = False
        self.msgs_path = './wx_msgs/'

    def wxautox_activate_check(self):
        """检查wxautox是否激活"""
        return check_license()

    def is_err(self, id, err="无"):
        """错误中断并发送邮件"""
        # log(message=traceback.format_exc())
        print(traceback.format_exc())
        log(level="ERROR", message=f"出现错误：{err}")
        email_send.send_email(
            subject=id, 
            content='错误信息：\n'+traceback.format_exc()+"\nerr信息：\n"+str(err)
        )


    def check_wechat_window(self):
        """检测微信是否运行"""
        return self.wx.IsOnline()

    def init_wx_listeners(self):
        """初始化微信监听器"""
        result = None
        # self.wx = None # 先清空
        if not self.wx:
            log(message="本次未获取客户端，正在初始化微信客户端...")
            self.wx = WeChat()
            self.wx.Show() # 首次强制显示主窗口聚焦
        
        self.config.AtMe = "@" + self.wx.nickname  # 绑定AtMe
        log(message='绑定@：' + self.config.AtMe)
        
        log(message='启动wxautox监听器...')
        self.wx.StartListening() # 启动监听器
        # 添加管理员监听
        
        result = self.wx.AddListenChat(nickname=self.config.cmd, callback=self.message_handle_callback)
        if result:
            log(message=f"添加管理员 {self.config.cmd} 监听完成")
        else:
            log(level="ERROR", message=f"添加管理员 {self.config.cmd} 监听失败, {result['message']}")
        
        # 添加个人用户监听 # 白名单模式
        if not self.config.AllListen_switch:
            log(message="白名单模式开启")
            for user in self.config.listen_list:
                result = self.wx.AddListenChat(nickname=user, callback=self.message_handle_callback)
                if result:
                    log(message=f"添加用户 {user} 监听完成")
                else:
                    log(level="ERROR", message=f"添加用户 {user} 监听失败, {result['message']}")
            
        # 如果群机器人开关开启，则添加群聊监听
        if self.config.group_switch:
            for user in self.config.group:
                result = self.wx.AddListenChat(nickname=user, callback=self.message_handle_callback)
                if result:
                    log(message=f"添加群组 {user} 监听完成")
                else:
                    log(level="ERROR", message=f"添加群组 {user} 监听失败, {result['message']}")
        
        # 定时消息注册
        if self.config.everyday_msg_switch:
            log(message="定时消息注册...")
            try:
                schedule.clear('everyday_msg')  # 按 tag 清理
                for user, tasks in self.config.everyday_msg_dict.items():  # 遍历用户和对应的任务列表
                    for task in tasks:  # 遍历每个用户的定时任务
                        time_str = task.get('time')  # 定时时间
                        msgs = task.get('msgs')  # 定时消息列表
                        schedule.every().day.at(time_str).do(self.send_everyday_msg, user, msgs).tag('everyday_msg')
                        log(message=f"注册定时消息：每天{time_str} 给 {user} 发消息")
                log(message="定时消息注册完成")
            except Exception as e:
                log(level="ERROR", message=f"定时消息注册失败：{e}")
        log(message="监听器初始化完成")
    def send_everyday_msg(self, user, msgs):
        """定时消息发送"""
        log(message=f"{user} 定时消息时间到，正在发送...")
        for msg in msgs:
            log(message=f"正在向 {user} 发送定时消息：{msg}")
            try:
                result = self.wx.SendMsg(msg=msg, who=user)
                time.sleep(random.randint(1, 3))
                if not result:
                    log(level="ERROR", message=f"定时消息发送失败：{result['message']}")
                    self.is_err(self.wx.nickname+f" wxbot定时消息发送失败！", f"{user} 定时消息发送失败：{result['message']}")
            except Exception as e:
                log(level="ERROR", message=f"定时消息发送失败：{e}")
                self.is_err(self.wx.nickname+f" wxbot定时消息发送失败！", f"{user} 定时消息发送失败：{e}")
    def message_handle_callback(self, msg, chat):
        """监听模式回调"""
        try:
            # chat_name = chat.ChatInfo().get('chat_name')
            text = datetime.now().strftime("%Y/%m/%d %H:%M:%S ") + f'类型：{msg.type} 属性：{msg.attr} 窗口：{chat.who} 发送人：{msg.sender} - 消息：{msg.content}'
            log(message=text)
            """ # 有log本地文件记录，暂不重复写消息文件
            try:
                with open(self.msgs_path+'/wx_msgs.txt', 'a', encoding='utf-8') as f:
                    f.write(text + '\n') # 写入新消息到本地
            except:
                os.makedirs(self.msgs_path)
                log(message=f"文件夹 '{self.msgs_path}' 创建成功！")
            """
            if msg.attr == "friend": # 好友群友的消息
                if self.config.AllListen_switch:
                    # 更新监听列表中该会话的最新消息时间
                    for listen_chat in self.all_Mode_listen_list:
                        if listen_chat[0] == chat.who:
                            log(message=chat.who + " 对话最新消息时间已更新")
                            listen_chat[1] = time.time()
                            break
                result = self.process_message(chat, msg)
                if not result:
                    # self.callback_is_die = True # 反馈主线程回调函数出错
                    self.is_err(self.wx.nickname+f" wxbot处理监听新消息失败！", text+'\n'+result['message'])
            
            elif msg.attr == "system": # 系统的消息
                if self.config.group_welcome: # 群新人欢迎语开关
                    result = self.send_group_welcome_msg(chat, msg) # 获取子窗口对象与消息对象送入处理
                    if not result:
                        # self.callback_is_die = True # 反馈主线程回调函数出错
                        self.is_err(self.wx.nickname+f" wxbot发送群新人欢迎语失败！", text+'\n'+result['message'])
        except Exception as e:
            self.callback_is_die = True # 反馈主线程回调函数出错
            self.is_err(self.wx.nickname+" wxbot回调函数处理出错！处理监听失败！！", e)

    def wx_send_ai(self, chat, message):
        """发送AI生成的消息"""
        try:
            is_keyword = False
            if self.config.chat_keyword_switch: # 关键词回复开关
                for keyword in self.config.keyword_dict:
                    if keyword in message.content:
                        is_keyword = True
                        log(message=f"私聊 {chat.who} 关键字消息：" + message.content)
                        reply = self.config.keyword_dict[keyword]
            if not is_keyword:
                reply = self.api.chat(message.content, prompt=self.config.prompt)
        except Exception as e:
            # log(level="ERROR", message=traceback.format_exc() + str(e))
            print(traceback.format_exc())
            log(level="ERROR", message=str(e)+"\nAPI返回错误，请稍后再试")
            reply = "API返回错误，请稍后再试"
                
        if len(reply) >= 2000:
            segments = self.config.split_long_text(reply)
            for segment in segments:
                result = chat.SendMsg(segment)
        else:
            time.sleep(random.randint(1, 10))
            result = chat.SendMsg(reply)
        return result

    def find_new_group_friend(self, msg, flag):
        """寻找新的群好友"""
        text = msg
        try:
            first_quote_content = text.split('"')[flag]
        except:
            first_quote_content = text.split('"')[1]
        return first_quote_content

    def send_group_welcome_msg(self, chat, message):
        """监听群组欢迎新人"""
        result = True
        log(message=f"{chat.who} 系统消息:" + message.content)
        if "加入群聊" in message.content and random.random()<self.config.group_welcome_random: # 概率触发
            new_friend = self.find_new_group_friend(message.content, 1)  # 扫码加入
            log(message=f"{chat.who} 新群友:" + new_friend)
            time.sleep(5)
            result = chat.SendMsg(msg=self.config.group_welcome_msg, at=new_friend)
        elif "加入了群聊" in message.content and random.random()<self.config.group_welcome_random: # 概率触发
            new_friend = self.find_new_group_friend(message.content, 3)  # 个人邀请
            log(message=f"{chat.who} 新群友:" + new_friend)
            time.sleep(5)
            result = chat.SendMsg(msg=self.config.group_welcome_msg, at=new_friend)
        return result

    def process_message(self, chat, message):
        """处理收到的单条消息"""
        log(message=f"处理 {chat.who} 窗口 {message.sender} 消息：{message.content}")
        result = True # WxResponse 返回类接受对象
        # 检查是否为需要监听的对象 黑白名单处理
        is_monitored = not (self.config.AllListen_switch and chat.who in self.config.listen_list)\
                        or ((not self.config.AllListen_switch) and chat.who in self.config.listen_list)\
                        or (chat.who in self.config.group and self.config.group_switch)\
                        or (chat.who == self.config.cmd)
        if not is_monitored:
            return

        # 群聊中：只有包含 @ 才回复
        if chat.who in self.config.group:
            if (self.config.AtMe in message.content and self.config.group_reply_at) \
                or not self.config.group_reply_at: # 根据是否仅回复群聊@开关判断是否回复

                content_without_at = re.sub(self.config.AtMe, "", message.content).strip()
                log(message=f"群组 {chat.who} 消息：" + content_without_at)
                try:
                    reply = self.api.chat(content_without_at, prompt=self.config.prompt)
                except Exception as e:
                    # log(level="ERROR", message=traceback.format_exc())
                    print(traceback.format_exc())
                    log(level="ERROR", message=str(e)+"\n群组中调用AI回复错误！！")
                    reply = "请稍后再试"
                time.sleep(random.randint(1, 10))
                result = chat.SendMsg(msg=reply, at=message.sender)
                return result
            # 群组关键词处理
            if self.config.group_keyword_switch:
                for keyword in self.config.keyword_dict:
                    if keyword in message.content:
                        log(message=f"群组 {chat.who} 关键字消息：" + message.content)
                        chat.SendMsg(msg=self.config.keyword_dict[keyword])
                        time.sleep(1)
            return result

        # 命令处理
        if chat.who == self.config.cmd:
            result = self.process_command(chat, message)
            return result

        # 普通好友消息
        result = self.wx_send_ai(chat, message)
        return result

    def process_command(self, chat, message):
        """处理管理员命令"""
        result = True # WxResponse 返回类接受对象
        if "/添加用户" in message.content:
            result = self.handle_add_user(chat, message)
        elif "/删除用户" in message.content:
            result = self.handle_remove_user(chat, message)
        elif "/当前用户" == message.content:
            result = chat.SendMsg(message.content + '\n' + ", ".join(self.config.listen_list))
        elif "/当前群" == message.content:
            result = chat.SendMsg(message.content + '\n'+ ", ".join(self.config.group))
        elif "/群机器人状态" == message.content:
            result = self.handle_group_switch_status(chat, message)
        elif "/添加群" in message.content:
            result = self.handle_add_group(chat, message)
        elif "/删除群" in message.content:
            result = self.handle_remove_group(chat, message)
        elif message.content == "/开启群机器人":
            result = self.handle_enable_group_bot(chat, message)
        elif message.content == "/关闭群机器人":
            result = self.handle_disable_group_bot(chat, message)
        elif message.content == "/开启群机器人欢迎语":
            result = self.handle_enable_welcome_msg(chat, message)
        elif message.content == "/关闭群机器人欢迎语":
            result = self.handle_disable_welcome_msg(chat, message)
        elif message.content == "/群机器人欢迎语状态":
            result = self.handle_welcome_msg_status(chat, message)
        elif message.content == "/当前群机器人欢迎语":
            result = chat.SendMsg(message.content + '\n' + self.config.group_welcome_msg)
        elif "/更改群机器人欢迎语为" in message.content:
            result = self.handle_change_welcome_msg(chat, message)
        elif message.content == "/当前模型":
            result = chat.SendMsg(message.content + " " + self.api.DS_NOW_MOD)
        elif message.content == "/切换模型1":
            result = self.handle_switch_model(chat, message, self.config.model1)
        elif message.content == "/切换模型2":
            result = self.handle_switch_model(chat, message, self.config.model2)
        elif message.content == "/当前AI设定":
            result = chat.SendMsg('当前AI设定：\n' + self.config.prompt)
        elif "/更改AI设定为" in message.content or "/更改ai设定为" in message.content:
            result = self.handle_change_prompt(chat, message)
        elif message.content == "/更新配置":
            self.config.refresh_config()
            self.init_wx_listeners()
            result = chat.SendMsg(message.content + ' 完成\n')
        elif message.content == "/当前版本":
            result = chat.SendMsg(message.content + 'wxbot_' + self.ver + '\n' + self.ver_log + '\n作者:https://siver.top')
        elif message.content == "/指令" or message.content == "指令":
            result = self.send_command_list(chat)
        elif message.content == "/状态":
            send_msg = "运行时间：" + self.config.get_run_time(self.start_time) + "\n"
            if self.config.AllListen_switch:
                send_msg += "当前模式：黑名单模式\n"
                send_msg += "当前黑名单：" + ", ".join(self.config.listen_list) + "\n"
            else:
                send_msg += "当前模式：白名单模式\n"
                send_msg += "当前白名单：" + ", ".join(self.config.listen_list) + "\n"
            if self.config.group_switch:
                send_msg += "当前群机器人状态：开启\n"
                send_msg += "当前群：" + ", ".join(self.config.group) + "\n"
                if self.config.group_welcome:
                    send_msg += f"当前群机器人欢迎语状态：开启 欢迎概率：{self.config.group_welcome_random}\n"
                else:
                    send_msg += "当前群机器人欢迎语状态：关闭\n"
            else:
                send_msg += "当前群机器人状态：关闭\n"
            if self.config.chat_keyword_switch:
                send_msg += "当前私聊关键词回复状态：开启\n"
            else:
                send_msg += "当前私聊关键词回复状态：关闭\n"
            if self.config.group_keyword_switch:
                send_msg += "当前群聊关键词回复状态：开启\n"
            else:
                send_msg += "当前群聊关键词回复状态：关闭\n"

            send_msg += "当前关键词："
            for key in self.config.keyword_dict:
                send_msg += key + ", "
            send_msg += "\n"
            if self.config.everyday_msg_switch:
                send_msg += "当前定时消息状态：开启\n"
            else:
                send_msg += "当前定时消息状态：关闭\n"
            
            result = chat.SendMsg(send_msg)
        else:
            result = self.wx_send_ai(chat, message)
        return result

    def handle_add_user(self, chat, message):
        """处理添加用户命令"""
        user_to_add = re.sub("/添加用户", "", message.content).strip()
        self.config.add_user(user_to_add)
        if not self.config.AllListen_switch:
            result = self.wx.AddListenChat(nickname=user_to_add, callback=self.message_handle_callback)
            if result:
                log(message=f"添加用户 {user_to_add} 监听完成")
                result = chat.SendMsg(message.content + ' 完成\n' + ", ".join(self.config.listen_list))
                return result
            else:
                self.config.remove_user(user_to_add)
                log(level="ERROR", message=f"添加用户 {user_to_add} 监听失败, {result['message']}")
                result = chat.SendMsg(message.content + f" 失败\n{result['message']}\n" + ", ".join(self.config.listen_list))
                return result
        else:
            result = chat.SendMsg(message.content + ' 完成(黑名单)\n' + ", ".join(self.config.listen_list))
            return result

    def handle_remove_user(self, chat, message):
        """处理删除用户命令"""
        user_to_remove = re.sub("/删除用户", "", message.content).strip()
        self.wx.RemoveListenChat(user_to_remove)
        self.config.remove_user(user_to_remove)
        result = chat.SendMsg(message.content + ' 完成\n' + ", ".join(self.config.listen_list))
        return result

    def handle_group_switch_status(self, chat, message):
        """处理群机器人状态查询"""
        if self.config.group_switch:
            result = chat.SendMsg(message.content + '为关闭')
        else:
            result = chat.SendMsg(message.content + '为开启')
        return result

    def handle_add_group(self, chat, message):
        """处理添加群组命令"""
        new_group = re.sub("/添加群", "", message.content).strip()
        self.config.add_group(new_group)
        if self.config.group_switch:
            result = self.wx.AddListenChat(nickname=new_group, callback=self.message_handle_callback)
            if result:
                log(message=f"添加群组 {new_group} 监听完成")
                result = chat.SendMsg(message.content + ' 完成\n' + ", ".join(self.config.group))
                return result
            else:
                self.config.remove_group(new_group)
                log(level="ERROR", message=f"添加群组 {new_group} 监听失败, {result['message']}")
                result = chat.SendMsg(message.content + f" 失败\n{result['message']}\n" + ", ".join(self.config.group))
                return result
        else:
            result = chat.SendMsg(message.content + ' 完成(群机器人未开启)\n' + ", ".join(self.config.group))
            return result

            

    def handle_remove_group(self, chat, message):
        """处理删除群组命令"""
        group_to_remove = re.sub("/删除群", "", message.content).strip()
        self.wx.RemoveListenChat(group_to_remove)
        self.config.remove_group(group_to_remove)
        result = chat.SendMsg(message.content + ' 完成\n' + ", ".join(self.config.group))
        return result

    def handle_enable_group_bot(self, chat, message):
        """处理开启群机器人命令"""
        try:
            self.config.set_config(id='group_switch', new_content=True)
            self.init_wx_listeners()
            result = chat.SendMsg(message.content + ' 完成\n' +'当前群：\n'+", ".join(self.config.group))
            return result
        except Exception as e:
            # log(message=traceback.format_exc())
            self.config.set_config('group_switch', False)
            self.init_wx_listeners()
            chat.SendMsg(message.content + ' 失败\n请重新配置群名称或者检查机器人号是否在群或者群名中是否含有非法中文字符\n当前群:'+ ", ".join(self.config.group) +'\n当前群机器人状态:'+self.config.group_switch)

    def handle_disable_group_bot(self, chat, message):
        """处理关闭群机器人命令"""
        self.config.set_config(id='group_switch', new_content=False)
        for user in self.config.group:
            self.wx.RemoveListenChat(user)
        result = chat.SendMsg(message.content + ' 完成\n' +'当前群：\n' + ", ".join(self.config.group))
        return result

    def handle_enable_welcome_msg(self, chat, message):
        """处理开启群欢迎语命令"""
        self.config.group_welcome = True
        self.config.set_config('group_welcome', True)
        result = chat.SendMsg(message.content + ' 完成\n' +'当前群：\n' + ", ".join(self.config.group))
        return result

    def handle_disable_welcome_msg(self, chat, message):
        """处理关闭群欢迎语命令"""
        self.config.group_welcome = False
        self.config.set_config('group_welcome', False)
        result = chat.SendMsg(message.content + ' 完成\n' +'当前群：\n' + ", ".join(self.config.group))
        return result

    def handle_welcome_msg_status(self, chat, message):
        """处理群欢迎语状态查询"""
        if self.config.group_welcome:
            result = chat.SendMsg("/群机器人欢迎语状态 为开启\n" +'当前群：\n' + ", ".join(self.config.group))
        else:
            result = chat.SendMsg("/群机器人欢迎语状态 为关闭\n" +'当前群：\n' + ", ".join(self.config.group))
        return result

    def handle_change_welcome_msg(self, chat, message):
        """处理更改群欢迎语命令"""
        new_welcome = re.sub("/更改群机器人欢迎语为", "", message.content).strip()
        self.config.set_config('group_welcome_msg', new_welcome)
        result = chat.SendMsg('群机器人欢迎语已更新\n' + self.config.group_welcome_msg)
        return result

    def handle_switch_model(self, chat, message, model):
        """处理切换模型命令"""
        self.api.DS_NOW_MOD = model
        result = chat.SendMsg(message.content + ' 完成\n当前模型:' + self.api.DS_NOW_MOD)
        return result

    def handle_change_prompt(self, chat, message):
        """处理更改AI设定命令"""
        if "AI设定" in message.content:
            new_prompt = re.sub("/更改AI设定为", "", message.content).strip()
        else:
            new_prompt = re.sub("/更改ai设定为", "", message.content).strip()
        self.config.config['prompt'] = new_prompt
        self.config.save_config()
        self.config.refresh_config()
        result = chat.SendMsg('AI设定已更新\n' + self.config.prompt)
        return result

    def send_command_list(self, chat):
        """发送指令列表"""
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
        result = chat.SendMsg(commands)
        return result
    def is_image_path(self, s: str) -> bool:
        """检查字符串是否是图片路径（以图片格式结尾，并且是完整路径）"""
        # 检查是否是图片格式
        image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')
        if not s.lower().endswith(image_extensions):
            return False

        # 检查是否是完整路径（Windows 或 Unix 风格）
        # Windows 路径示例：C:\python\1.png 或 C:/python/1.png
        # Unix 路径示例：/home/user/1.png
        pattern = re.compile(
            r'^('
            r'([A-Za-z]:[\\/])'  # Windows 盘符（C:\ 或 C:/）
            r'|'  # 或
            r'(/[^/]+)'  # Unix 绝对路径（/home/...）
            r')'
            r'.+'  # 中间任意内容
            r'\.(png|jpg|jpeg|gif|bmp|webp)$',  # 图片扩展名
            re.IGNORECASE
        )
        return bool(pattern.match(s))
    def Pass_New_Friends(self):
        '''
        监听好友请求并一并通过
        '''
        NewFriends = self.wx.GetNewFriends(acceptable=True)
        time.sleep(1)
        if len(NewFriends) != 0:
            log(message="以下是新朋友：\n" + str(NewFriends))
            for new in NewFriends:
                new_name = new.name + '_机器人备注'
                new.accept(remark = new_name) # 接受好友请求，并设置备注和标签
                log(message="已通过" + new.name + "的好友请求")
                self.wx.SwitchToChat() # 通过请求完后手动切换回聊天页面
                time.sleep(5)
                for msg in self.config.new_frien_msg: # 发送新好友招呼语
                    if self.is_image_path(msg):
                        self.wx.SendFiles(who=new_name, filepath=msg)
                    else:
                        self.wx.SendMsg(who=new_name, msg=msg)
                    time.sleep(random.randint(1, 3)) # 随机延时1-3秒发送消息

                self.wx.ChatWith(who='文件传输助手')
                time.sleep(1)
                self.wx.SwitchToContact() # 切回通讯录同意下一个好友
            time.sleep(1)

        self.wx.SwitchToChat() # 通过请求完后手动切换回聊天页面
        time.sleep(1)

    def listen_mode(self):
        """监听模式"""
        # 消息处理模块
        messages_dict = self.wx.GetListenMessage()
        for chat in messages_dict:
            for message in messages_dict.get(chat, []):
                self.process_message(chat, message)

    def new_msg_get_plus(self, chat_records):
        """
        处理聊天记录：
        1. 过滤掉类型为 SYS 与 Recall 的消息（保留 Time 消息）
        2. 如果存在 Self 消息，则：
            a. 删除掉最新一条 Self 消息及其之前的所有消息，
                仅保留最新 Self 消息之后的记录；
            b. 在该记录中查找最新（最后出现）的 Time 消息，
                如果存在，则仅保留该 Time 消息之后的对方消息（过滤掉 Self 和 Time）；
                否则返回最新 Self 消息之后的所有记录。
        3. 如果没有 Self 消息，则查找过滤后的最新（最后出现）的 Time 消息。
            如果存在，则返回该消息之后的所有对方消息（过滤掉 Self 和 Time）；
            否则返回过滤后的所有消息。
        """
        # 步骤1：过滤掉 SYS 与 Recall 消息
        filtered = [msg for msg in chat_records if msg[0] not in ("SYS", "Recall")]

        # 判断是否存在 Self 消息
        if any(msg[0] == "Self" for msg in filtered):
            # 找到最新的 Self 消息的索引（最后出现的 Self 消息）
            latest_self_index = None
            for idx, msg in enumerate(filtered):
                if msg[0] == "Self":
                    latest_self_index = idx
            # 保留最新 Self 消息之后的记录
            post_self = filtered[latest_self_index + 1:]
            
            # 在最新 Self 消息之后查找最新的 Time 消息（最后出现的 Time 消息）
            latest_time_index = None
            for idx, msg in enumerate(post_self):
                if msg[0] == "Time":
                    latest_time_index = idx
            if latest_time_index is not None:
                # 返回该 Time 消息之后的对方消息（过滤掉 Self 和 Time）
                post_time = post_self[latest_time_index + 1:]
                final_records = [msg for msg in post_time if msg[0] not in ("Self", "Time")]
                return final_records
            else:
                # 未找到 Time 消息，返回最新 Self 消息之后的所有记录
                return post_self
        else:
            # 没有 Self 消息，则查找过滤后的最新 Time 消息
            latest_time_index = None
            for idx, msg in enumerate(filtered):
                if msg[0] == "Time":
                    latest_time_index = idx
            if latest_time_index is not None:
                # 返回该 Time 消息之后的对方消息（过滤掉 Self 和 Time）
                post_time = filtered[latest_time_index + 1:]
                final_records = [msg for msg in post_time if msg[0] not in ("Self", "Time")]
                return final_records
            else:
                # 若也没有 Time 消息，则返回过滤后的所有消息
                return filtered

    def next_message_handle(self):
        """
        处理next获取到的新消息，防止黑色流程漏消息

        参数:
            chat: str  消息发生的窗口
            message: 消息对象（包含 type, sender, content 等信息）
        """
        
        AllMessage = self.wx.GetAllMessage() # 先获取当前窗口的所有消息
        new_msg = self.new_msg_get_plus(AllMessage) # 将上一次自己发送消息后的所有新消息过滤出来
        return new_msg

    def add_chat_to_listen(self, chat):
        """添加会话到监听列表，并调用添加监听的接口"""
        log(message=chat + '不在监听列表，正在添加进列表')
        self.all_Mode_listen_list.append([chat, time.time()])
        log(message='当前监听列表：' + str(self.all_Mode_listen_list))
        self.wx.AddListenChat(nickname=chat, callback=self.message_handle_callback)

    def is_chat_listened(self, chat):
        """判断当前会话是否已经在监听列表中"""
        return any(listen_chat[0] == chat for listen_chat in self.all_Mode_listen_list)

    def ALLListen_mode(self, last_time, timeout=10):

        def process_new_messages():
            """处理获取到的新消息，对好友消息进行监听及消息处理"""
            messages_new = self.wx.GetNextNewMessage()
            # 遍历每个会话及其消息
            for chat, messages in messages_new.items():
                if chat in self.config.listen_list: # chat在用户列表，当前为全局模式，用户列表为黑名单故排除
                    log(message=f'{chat} 为黑名单用户，跳过处理')
                    continue
                for message in messages:
                    # 仅处理包含 chat_type 且为 friend 类型的消息（排除群聊）
                    if message.attr == 'friend':
                        new_msg = self.next_message_handle() # 处理next获取到的新消息
                        if not self.is_chat_listened(chat):
                            self.add_chat_to_listen(chat)
                        else:
                            log(message=chat + '在监听列表')
                        for msg in new_msg:
                            # ALL_listen = self.wx.GetAllListenChat() # 所有监听窗口子对象
                            # print(ALL_listen)
                            self.process_message(self.wx.GetSubWindow(nickname=chat), msg)

        def process_listen_messages():
            """处理监听中的会话消息，同时更新对应会话的最新消息时间"""
            messages_dict = self.wx.GetListenMessage()
            for chat, messages in messages_dict.items():
                for message in messages:
                    # 更新监听列表中该会话的最新消息时间
                    for listen_chat in self.all_Mode_listen_list:
                        if listen_chat[0] == chat.who:
                            log(message=chat.who + " 对话最新消息时间已更新")
                            listen_chat[1] = time.time()
                            break
                    self.process_message(chat, message)

        def remove_timeout_listen(chat_time_out=180): # 默认3分钟超时
            """删除超时的监听会话，避免边遍历边修改列表，通过复制列表实现安全遍历"""
            for listen_chat in self.all_Mode_listen_list[:]:
                if time.time() - listen_chat[1] >= chat_time_out:
                    log(message=str(listen_chat[0]) + '对话超时，正在删除监听')
                    self.wx.RemoveListenChat(listen_chat[0])
                    self.all_Mode_listen_list.remove(listen_chat)

        def get_next_new_message():
            def Next_callback(msg):
                log(message=f'收到消息：{msg.sender}: {msg.content}')
            messages_new = self.wx.GetNextNewMessage(filter_mute=False, callback=Next_callback)
            chat = messages_new.get('chat_name')
            chat_type = messages_new.get('chat_type')
            msgs = messages_new.get('msg')
            if chat in self.config.listen_list:
                log(message=f'{chat} 为黑名单用户，跳过处理')
                return
            if msgs:
                for msg in msgs:
                    if msg.attr == 'friend' and chat_type == 'friend': # 仅处理包含 chat_type 且为 friend 类型的消息（排除群聊）
                        # new_msg = self.next_message_handle() # 处理next获取到的新消息
                        if not self.is_chat_listened(chat):
                            self.add_chat_to_listen(chat)
                        else:
                            log(message=chat + '在监听列表')
                        self.process_message(self.wx.GetSubWindow(nickname=chat), msg)

        """全局监听模式"""
        # 消息检查模块  1s  混合模式 
        # 主逻辑依次调用处理新消息、更新监听消息、删除超时监听
        # process_new_messages()
        # process_listen_messages()
        get_next_new_message()
        # 监听静默超时检测模块 10s
        if time.time() - last_time >= timeout:
            # log(message=f'监听静默超时 {last_time}')
            remove_timeout_listen()
            return time.time()
        return last_time

    def stop_wxbot(self):
        """停止机器人"""
        try:
            self.run_flag = False

            self.wx.StopListening() # 停止监听
            log(level="WARNING", message='siver_wxbot安全退出！！')
            return True
        except Exception as e:
            self.is_err(self.wx.nickname+' wxbot机器人关闭程序执行出错！！', e)
            return False
    def key_pass(self, year, month, day, hour, minute, second):
        # 定义目标时间
        target_time = datetime(year, month, day, hour, minute, second)

        # 获取当前时间
        current_time = datetime.now()

        # 判断当前时间是否超过目标时间
        if current_time < target_time:
            remaining_time = target_time - current_time
            days = remaining_time.days
            hours, remainder = divmod(remaining_time.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            log(level="INFO", message=f"还剩 {days} 天 {hours} 小时 {minutes} 分钟 {seconds} 秒 到期。")
        else:
            while True:
                log(level="ERROR", message=f"程序以于 {target_time} 过期不可使用")
                time.sleep(60)

    def main(self):
        # self.key_pass(2025, 6, 20, 0, 0, 0) # 打包保护锁
        """主运行函数"""
        log(message=f"wxbot\n版本: wxbot_{self.ver}\n作者: https://siver.top\n")
        
        # wxautox激活检测
        if self.wxautox_activate_check():
            log(message="wxautox已激活")
        else:
            log(level="ERROR", message="wxautox未激活，请激活后再运行程序！！")
            return False

        try:
            self.init_wx_listeners()
            log(message=f"UI面板状态更新完成")

            wait_time = 1  # 每1秒检查一次新消息
            check_interval = 10  # 每10次循环检查一次进程状态
            check_counter = 0
            check_new_counter = 0
            last_time = time.time()
            log(message='siver_wxbot初始化完成，开始监听消息(作者:https://siver.top)')
            self.run_flag = True
        except Exception as e:
            print(traceback.format_exc())
            log(level="ERROR", message=str(e)+"\n初始化微信监听器失败，请检查微信是否启动登录正确")
            self.run_flag = False
        
        
        # 以下为测试代码test VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV
        # self.wx.SendMsg('siver_wxbot初始化完成', who=self.config.cmd) # 向管理员发送初始化完成消息
        # 以上为测试代码test ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        # 主循环
        while self.run_flag:
            try:
                # 离线检测模块  10s
                check_counter += 1
                if check_counter >= check_interval:
                    try:
                        if self.callback_is_die:
                            self.wx.StopListening() # 停止微信监听器
                            log(level="ERROR", message="检测到回调函数出错!!已停止所有监听并跳出主线程!!")
                            break
                        if not self.check_wechat_window():
                            self.is_err(self.wx.nickname+" wxbot监听出错！！微信可能已被弹出登录！！在线检查失败！！")
                            while self.run_flag:
                                log(level="ERROR", message=f"微信{self.wx.nickname}已被弹出登录！！请检查微信是否登录！！")
                                time.sleep(100)
                    except Exception as e:
                        self.is_err(self.wx.nickname+" wxbot监听出错！！微信可能已被弹出登录！！在线检查失败！！", e)
                        while self.run_flag:
                            log(level="ERROR", message=f"微信{self.wx.nickname}已被弹出登录！！请检查微信是否登录！！")
                            time.sleep(100)
                    check_counter = 0
                
                # 新好友通过模块 30s - 180s随机
                if self.config.new_frined_switch:
                    check_new_friend_time_MIN = 30
                    check_new_friend_time_MAX = 300
                    check_new_counter += 1
                    if check_new_counter >= random.randint(check_new_friend_time_MIN, check_new_friend_time_MAX):
                        try:
                            self.Pass_New_Friends()
                            log(message="检查新好友完成")
                        except Exception as e:
                            self.is_err(self.wx.nickname+"  智能客服bot监听新好友出错！！请检查程序！！", e)
                        check_new_counter = 0

                # 全局监听模式
                if self.config.AllListen_switch: # 根据全局开关切换监听模式还是全局模式
                    try:
                        last_time = self.ALLListen_mode(last_time=last_time) # 全局模式
                    except Exception as e:
                        if not self.run_flag:
                            log(level="ERROR", message=str(e)+"\n全局模式出错！！请检查程序！！")
                # 定时任务
                if self.config.everyday_msg_switch:
                    schedule.run_pending()
                

            except Exception as e:
                self.is_err(self.wx.nickname+" wxbot消息处理出错！！微信可能已被弹出登录！！处理监听失败！！", e)
                self.run_flag = False

            time.sleep(wait_time)
        log(level="WARNING", message='siver_wxbot主线程安全退出，正在退出监听...')
    def run(self):
        """启动函数"""
        self.main()
    def stop(self):
        """停止函数"""
        self.stop_wxbot()


if __name__ == "__main__":
    bot = WXBot()
    bot.run()