from datetime import datetime
import os
import sys

LOG_PATH = "./logs"
# 日志颜色映射
LOG_COLORS = {
    'INFO': 'text-primary',
    'WARNING': 'text-warning',
    'ERROR': 'text-danger',
    'DEBUG': 'text-secondary',
    'SUCCESS': 'text-success'
}

log_messages = []
def log_server(level, msg):
    """
    记录日志到内存和文件
    :param level: 日志级别 (INFO, WARNING, ERROR, DEBUG, SUCCESS)
    :param msg: 日志消息
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = {
        'time': timestamp,
        'level': level,
        'message': msg,
        'color': LOG_COLORS.get(level.upper(), 'text-dark')
    }
    log_messages.append(log_entry)
    
    # 限制日志数量，避免内存占用过大
    if len(log_messages) > 1000:
        log_messages.pop(0)
    
    # 同时输出到控制台
    print(f"[{timestamp}] [{level}] {msg}")
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
    log_server(level, message)
    # 终端日志输出
    # print(f'[{timestamp}]: {message}')
    # 写入log到本地
    try:
        now_day = datetime.now().strftime("%y%m%d")
        with open(LOG_PATH+f'/log_{now_day}.txt', 'a', encoding='utf-8-sig') as f:
            f.write(f'[{timestamp}]: {message}' + '\n') # 写入log到本地
        # with open(LOG_PATH+f'/log_{now_day}.txt', 'a', encoding='utf-8') as f:
            # f.write(f'[{timestamp}]: {message}' + '\n') # 写入log到本地
    except:
        os.makedirs(LOG_PATH)
        print(f"文件夹 '{LOG_PATH}' 创建成功！")