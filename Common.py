import os
import sys
from datetime import datetime
import json
# from web_server import log_server

main_window = None

CONFIG_FILE = "config.json"
LOG_PATH = "./logs"


def read_config(config_file=CONFIG_FILE):
    if not os.path.exists(config_file) or os.path.getsize(config_file) == 0:
        return {}
    with open(config_file, 'r', encoding='utf-8') as file:
        return json.load(file)


def save_json(data, config_file=CONFIG_FILE):
    try:
        with open(config_file, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"无法保存配置文件: {e}")


def update_config_value(key, value, config_file="config.json"):
    data = read_config(config_file)
    data[key] = value
    save_json(data, config_file)


def is_online(online=True):
    """在线状态改变"""
    if online:
        main_window.verticalFrame_Onlinestatus.setStyleSheet(
            "QFrame {background-color: rgb(199, 228, 255); border-radius: 9px; border: none; padding: 2px;}")
        main_window.label_Online_Status.setStyleSheet(
            "color:rgb(63, 158, 255); qproperty-alignment: 'AlignHCenter | AlignVCenter';")
        main_window.label_Online_Status.setText("在线")
    else:
        main_window.verticalFrame_Onlinestatus.setStyleSheet(
            "QFrame {background-color: rgb(139, 0, 0); border-radius: 9px; border: none; padding: 2px;}")
        main_window.label_Online_Status.setStyleSheet(
            "color: #FFFFFF; qproperty-alignment: 'AlignHCenter | AlignVCenter';")
        main_window.label_Online_Status.setText("离线")
def UI_nickname_change(nickname):
    """UI昵称改变"""
    main_window.label_Nickname.setText(nickname)


def log(level="INFO", message=''):
    """日志输出"""
    timestamp = datetime.now().strftime("%m-%d %H:%M:%S")
    colors = {
        "INFO": "#691bfd",
        "WARNING": "#FFA500",
        "ERROR": "#FF0000",
        "DEBUG": "#00CC33"
    }
    # qt6日志输出
    """color = colors.get(level, "#00CC33")
    formatted_message = f'<span style="color:{color}">[{timestamp}]: {message}</span>'
    main_window.textEdit_log.append(formatted_message)
    scrollbar = main_window.textEdit_log.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())"""
    # server端日志输出
    # log_server(level, message)
    # 终端日志输出
    print(f'[{timestamp}]: {message}')
    # 写入log到本地
    try:
        now_day = datetime.now().strftime("%y%m%d")
        with open(LOG_PATH+f'/log_{now_day}.txt', 'a', encoding='utf-8') as f:
            f.write(f'[{timestamp}]: {message}' + '\n') # 写入log到本地
    except:
        os.makedirs(LOG_PATH)
        print(f"文件夹 '{LOG_PATH}' 创建成功！")

def get_resource_path(relative_path):
    """获取资源路径"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path).replace(os.sep, '/')