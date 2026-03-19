from datetime import datetime
import os
import sys

def _base_dir():
    """运行时基础目录：打包后为 exe 所在目录，开发时为当前目录"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")

LOG_PATH = os.path.join(_base_dir(), "panel_logs")
os.makedirs(LOG_PATH, exist_ok=True)
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
    now_day = datetime.now().strftime("%y%m%d")
    try:
        with open(os.path.join(LOG_PATH, f'log_{now_day}.txt'), 'a', encoding='utf-8-sig') as f:
            f.write(f'[{timestamp}]: {message}' + '\n')
    except Exception as e:
        print(f"写入日志文件失败: {e}")