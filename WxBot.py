import re
import time
from pathlib import Path
from random import randint

from PyQt6 import QtCore
from openai import OpenAI

from Common import log, read_config, is_online


class DeepSeekAPI:
    def __init__(self, config):
        self.config = config
        self.DS_NOW_MOD = config.model1
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)

    def chat(self, message, model=None, stream=True, prompt=None):
        if model is None:
            model = self.DS_NOW_MOD
        if prompt is None:
            prompt = self.config.prompt
        try:
            log("INFO", f"处理信息：{message}")
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": message},
                ],
                stream=stream
            )
        except Exception:
            raise
        if stream:
            reasoning_content = ""
            content = ""
            for chunk in response:
                if not hasattr(chunk, 'choices') or not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    chunk_message = delta.reasoning_content
                    if chunk_message:
                        reasoning_content += chunk_message
                elif hasattr(delta, 'content') and delta.content:
                    chunk_message = delta.content
                    if chunk_message:
                        content += chunk_message
            return content.strip()
        else:
            output = response.choices[0].message.content
            return output


class WXBotConfig:
    def __init__(self):
        self.config = read_config()
        self.api_key = self.config.get('api_key', "")
        self.base_url = self.config.get('base_url', "")
        self.model1 = self.config.get('model1', "")
        self.prompt = self.config.get('prompt', "")
        self.AllListen_switch = self.config.get('AllListen_switch', False)
        self.listen_list = self.config.get('listen_list', [])
        self.admin = self.config.get('admin', "")
        self.group = self.config.get('group', [])
        self.group_switch = self.config.get('group_switch', False)
        self.group_reply_at = self.config.get('group_reply_at', False)
        self.group_welcome = self.config.get('group_welcome', False)
        self.group_welcome_msg = self.config.get('group_welcome_msg', "欢迎新朋友！请先查看群公告！")
        self.new_friend_switch = self.config.get('new_friend_switch', False)
        self.new_friend_msg = self.config.get('new_friend_msg', [])
        self.AtMe = ""

    def add_group(self, group_name):
        if group_name not in self.group:
            self.group.append(group_name)

    def remove_group(self, group_name):
        if group_name in self.group:
            self.group.remove(group_name)


class WXBotThread(QtCore.QThread):
    finished = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super(WXBotThread, self).__init__(parent)
        self.parent = parent
        self.run_flag = True
        self.config = WXBotConfig()
        self.all_Mode_listen_list = []
        self.api = DeepSeekAPI(self.config)

    def run(self):
        try:
            self.init_wx_listeners()
            is_online(True)
            wait_time = 1
            check_interval = 10
            check_counter = 0
            check_new_counter = 0
            last_time = time.time()
            self.run_flag = True

            while self.run_flag:
                check_counter += 1
                if check_counter >= check_interval:
                    if not self.check_wechat_window():
                        is_online(False)
                    check_counter = 0

                if self.config.new_friend_switch:
                    check_new_friend_time_MIN = 30
                    check_new_friend_time_MAX = 300
                    check_new_counter += 1
                    if check_new_counter >= randint(check_new_friend_time_MIN, check_new_friend_time_MAX):
                        self.Pass_New_Friends()
                        check_new_counter = 0

                if not self.config.AllListen_switch:
                    self.listen_mode()
                else:
                    last_time = self.ALLListen_mode(last_time=last_time, timeout=10)
                time.sleep(wait_time)
        except Exception as e:
            log("ERROR", e)

        finally:
            self.finished.emit()

    def init_wx_listeners(self):
        self.config.AtMe = "@" + self.parent.wx.nickname
        if not self.config.admin:
            self.parent.wx.AddListenChat(who=self.config.admin)
        if not self.config.AllListen_switch:
            for user in self.config.listen_list:
                self.parent.wx.AddListenChat(who=user)
        if self.config.group_switch:
            for group in self.config.group:
                self.parent.wx.AddListenChat(who=group)

    def wx_send_ai(self, chat, message):
        try:
            reply = self.api.chat(message.content, prompt=self.config.prompt)
        except Exception as e:
            log("ERROR", f"API出错：{e}")
            reply = "API返回错误，请稍后再试"
        chat.SendMsg(reply)

    def find_new_group_friend(self, msg, flag):
        text = msg
        try:
            first_quote_content = text.split('"')[flag]
        except IndexError:
            first_quote_content = text.split('"')[1]
        return first_quote_content

    def send_group_welcome_msg(self, chat, message):
        if message.type.upper() != 'SYS':
            return
        if "加入群聊" in message.content:
            new_friend = self.find_new_group_friend(message.content, 1)
            time.sleep(5)
            chat.SendMsg(msg=self.config.group_welcome_msg, at=new_friend)
        elif "加入了群聊" in message.content:
            new_friend = self.find_new_group_friend(message.content, 3)
            time.sleep(5)
            chat.SendMsg(msg=self.config.group_welcome_msg, at=new_friend)
        log("DEBUG", f"自动欢迎新成员")

    def process_message(self, chat, message):
        if self.config.group_welcome:
            self.send_group_welcome_msg(chat, message)
        if message.type != 'friend':
            return
        is_monitored = (self.config.AllListen_switch or chat.who in self.config.listen_list) or \
                       (chat.who in self.config.group and self.config.group_switch) or \
                       (chat.who == self.config.admin)
        if not is_monitored:
            return
        if chat.who in self.config.group:
            should_reply = self.config.group_reply_at
            if (should_reply and self.config.AtMe in message.content) or not should_reply:
                content_without_at = re.sub(self.config.AtMe, "", message.content).strip()
                try:
                    reply = self.api.chat(content_without_at, prompt=self.config.prompt)
                except Exception:
                    reply = "出错了，请稍后再试"
                log("DEBUG", f"自动发送：{reply}")
                chat.SendMsg(msg=reply, at=message.sender)
            return
        if chat.who == self.config.admin:
            self.process_command(chat, message)
            return
        self.wx_send_ai(chat, message)

    def listen_mode(self):
        messages_dict = self.parent.wx.GetListenMessage()
        for chat, messages in messages_dict.items():
            for message in messages:
                self.process_message(chat, message)

    def ALLListen_mode(self, last_time, timeout=10):
        def process_new_messages():
            messages_new = self.parent.wx.GetNextNewMessage()
            for chat, messages in messages_new.items():
                if chat in self.config.listen_list:
                    continue
                for message in messages:
                    if message.details.get('chat_type') == 'friend':
                        new_msg = self.next_message_handle()
                        if not self.is_chat_listened(chat):
                            self.add_chat_to_listen(chat)
                        for msg in new_msg:
                            ALL_listen = self.parent.wx.GetAllListenChat()
                            self.process_message(ALL_listen.get(chat), msg)

        def process_listen_messages():
            messages_dict = self.parent.wx.GetListenMessage()
            for chat, messages in messages_dict.items():
                for message in messages:
                    for listen_chat in self.all_Mode_listen_list:
                        if listen_chat[0] == chat.who:
                            listen_chat[1] = time.time()
                            break
                    self.process_message(chat, message)

        def remove_timeout_listen(chat_time_out=180):
            for listen_chat in self.all_Mode_listen_list[:]:
                if time.time() - listen_chat[1] >= chat_time_out:
                    self.parent.wx.RemoveListenChat(who=listen_chat[0])
                    self.all_Mode_listen_list.remove(listen_chat)

        process_new_messages()
        process_listen_messages()
        if time.time() - last_time >= timeout:
            remove_timeout_listen()
            return time.time()
        return last_time

    def next_message_handle(self):
        AllMessage = self.parent.wx.GetAllMessage()
        new_msg = self.new_msg_get_plus(AllMessage)
        return new_msg

    def is_chat_listened(self, chat):
        return any(listen_chat[0] == chat for listen_chat in self.all_Mode_listen_list)

    def add_chat_to_listen(self, chat):
        self.all_Mode_listen_list.append([chat, time.time()])
        self.parent.wx.AddListenChat(chat)

    def new_msg_get_plus(self, chat_records):
        filtered = [msg for msg in chat_records if msg[0] not in ("SYS", "Recall")]
        if any(msg[0] == "Self" for msg in filtered):
            latest_self_index = None
            for idx, msg in enumerate(filtered):
                if msg[0] == "Self":
                    latest_self_index = idx
            post_self = filtered[latest_self_index + 1:]
            latest_time_index = None
            for idx, msg in enumerate(post_self):
                if msg[0] == "Time":
                    latest_time_index = idx
            if latest_time_index is not None:
                post_time = post_self[latest_time_index + 1:]
                final_records = [msg for msg in post_time if msg[0] not in ("Self", "Time")]
                return final_records
            else:
                return post_self
        else:
            latest_time_index = None
            for idx, msg in enumerate(filtered):
                if msg[0] == "Time":
                    latest_time_index = idx
            if latest_time_index is not None:
                post_time = filtered[latest_time_index + 1:]
                final_records = [msg for msg in post_time if msg[0] not in ("Self", "Time")]
                return final_records
            else:
                return filtered

    def stop(self):
        self.run_flag = False
        self.parent.wx.RemoveListenChat()
        self.quit()
        self.finished.emit()

    def process_command(self, chat, message):
        commands = {
            "/用户": lambda: chat.SendMsg('\n'.join(self.config.listen_list)),
            "/群": lambda: chat.SendMsg('\n'.join(self.config.group)),
            "/状态": lambda: self.handle_group_switch_status(chat),
            "/加群": lambda: self.handle_add_group(chat, message),
            "/删群": lambda: self.handle_remove_group(chat, message),
            "/开欢迎": lambda: self.handle_enable_welcome_msg(chat),
            "/关欢迎": lambda: self.handle_disable_welcome_msg(chat),
            "/欢迎状态": lambda: self.handle_welcome_msg_status(chat),
            "/当前欢迎": lambda: chat.SendMsg(self.config.group_welcome_msg),
            "/AI设定": lambda: chat.SendMsg('当前AI设定：\n' + self.config.prompt),
            "帮助": lambda: self.send_command_list(chat)
        }

        if message.content in commands:
            commands[message.content]()
        else:
            self.wx_send_ai(chat, message)

    def send_command_list(self, chat):
        commands = ('指令列表：\n'
                    '/用户 - 查看监听用户列表\n'
                    '/群 - 查看所有群组\n'
                    '/加群 - 后接群名称添加群组\n'
                    '/删群 - 后接群名称删除群组\n'
                    '/状态 - 查看群机器人状态\n'
                    '/开欢迎 - 开启欢迎消息\n'
                    '/关欢迎 - 关闭欢迎消息\n'
                    '/欢迎状态 - 查看欢迎消息状态\n'
                    '/当前欢迎 - 查看当前欢迎消息\n'
                    '/AI设定 - 查看当前AI设定\n'
                    '帮助 - 查看所有指令')
        chat.SendMsg(commands)

    def handle_group_switch_status(self, chat):
        chat.SendMsg(f"{'为开启' if self.config.group_switch else '为关闭'}")

    def handle_add_group(self, chat, message):
        new_group = message.content.replace("/加群", "").strip()
        if new_group and new_group not in self.config.group:
            self.config.add_group(new_group)
            self.init_wx_listeners()
            chat.SendMsg(f"添加完成\n{', '.join(self.config.group)}")
        else:
            chat.SendMsg(f"群 {new_group} 已存在或输入为空。\n当前群：\n{', '.join(self.config.group)}")

    def handle_remove_group(self, chat, message):
        group_to_remove = message.content.replace("/删群", "").strip()
        if group_to_remove in self.config.group:
            self.parent.wx.RemoveListenChat(group_to_remove)
            self.config.remove_group(group_to_remove)
            chat.SendMsg(f"删除完成\n{', '.join(self.config.group)}")
        else:
            chat.SendMsg("群不存在或输入为空")

    def handle_enable_welcome_msg(self, chat):
        self.config.group_welcome = True
        chat.SendMsg("欢迎语已开启")

    def handle_disable_welcome_msg(self, chat):
        self.config.group_welcome = False
        chat.SendMsg("欢迎语已关闭")

    def handle_welcome_msg_status(self, chat):
        chat.SendMsg(f"欢迎语{'已开启' if self.config.group_welcome else '已关闭'}")

    def check_wechat_window(self):
        return self.parent.wx.IsOnline()

    def is_file_path(self, s: str) -> bool:
        path = Path(s)
        if path.is_absolute() and not path.is_dir() and len(path.parts) > 1:
            return True
        elif not path.is_absolute() and path.suffix != '':
            return True
        return False

    def Pass_New_Friends(self):
        NewFriends = self.parent.wx.GetNewFriends()
        time.sleep(1)
        if len(NewFriends) != 0:
            log(message="以下是新朋友：\n" + str(NewFriends))
            for new in NewFriends:
                new_name = new.name + '_机器人备注'
                new.Accept(remark=new_name)
                log("DEBUG", f"已通过{new.name}的好友请求")
                self.parent.wx.SwitchToChat()
                time.sleep(5)
                for msg in self.config.new_friend_msg:
                    if self.is_file_path(msg):
                        self.parent.wx.SendFiles(who=new_name, filepath=msg)
                    else:
                        self.parent.wx.SendMsg(who=new_name, msg=msg)
                    time.sleep(1)
                self.parent.wx.SwitchToContact()
                time.sleep(1)
            self.parent.wx.ChatWith(who='文件传输助手')
        self.parent.wx.SwitchToChat()
        time.sleep(1)
