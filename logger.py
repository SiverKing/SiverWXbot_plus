import os
import re
import sys
import threading
from datetime import datetime, timedelta

def _base_dir():
    """运行时基础目录：打包后为 exe 所在目录，开发时为当前目录"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")

LOG_PATH = os.path.join(_base_dir(), "panel_logs")
os.makedirs(LOG_PATH, exist_ok=True)

# 日志文件保留天数：启动时清理更早的 log_YYMMDD.txt（当天文件永不删除）
LOG_RETENTION_DAYS = 365
_LOG_FILE_RE = re.compile(r'log_(\d{6})\.txt')

# 日志颜色映射
LOG_COLORS = {
    'INFO': 'text-primary',
    'WARNING': 'text-warning',
    'ERROR': 'text-danger',
    'DEBUG': 'text-secondary',
    'SUCCESS': 'text-success'
}

log_messages = []
_log_lock = threading.Lock()
_next_log_id = 0

def _copy_logs(items):
    return [dict(item) for item in items]

def log_server(level, msg):
    """
    记录日志到内存、当天日志文件与控制台。

    三者必须在同一把 _log_lock 内完成：wxautox 回调线程、Flask 请求线程、
    定时调度线程都会打日志，若只在内存列表上加锁、文件写在锁外，
    并发写同一个文件会出现行交错（半行拼接），内存顺序与文件顺序也会不一致。

    :param level: 日志级别 (INFO, WARNING, ERROR, DEBUG, SUCCESS)
    :param msg: 日志消息
    """
    # 只取一次当前时间：避免跨零点时文件名与行内时间戳分属两天
    now = datetime.now()
    ts_mem = now.strftime('%Y-%m-%d %H:%M:%S')   # 内存条目与控制台（保持原格式）
    ts_file = now.strftime('%m-%d %H:%M:%S')     # 文件行（保持原格式，不含年份）
    global _next_log_id

    with _log_lock:
        _next_log_id += 1
        log_entry = {
            'id': _next_log_id,
            'time': ts_mem,
            'level': level,
            'message': msg,
            'color': LOG_COLORS.get(level.upper(), 'text-dark')
        }
        log_messages.append(log_entry)

        # 限制日志数量，避免内存占用过大
        if len(log_messages) > 1000:
            log_messages.pop(0)

        # 同时输出到控制台
        print(f"[{ts_mem}] [{level}] {msg}")

        # 写入当天日志文件（与内存、控制台同一把锁，避免多线程并发写产生交错）
        try:
            log_file = os.path.join(LOG_PATH, f'log_{now.strftime("%y%m%d")}.txt')
            with open(log_file, 'a', encoding='utf-8-sig') as f:
                f.write(f'[{ts_file}]: {msg}' + '\n')
        except Exception as e:
            print(f"写入日志文件失败: {e}")

def get_recent_logs(limit=50):
    with _log_lock:
        return _copy_logs(log_messages[-limit:])

def get_logs_after(after_id, limit=50):
    with _log_lock:
        if not log_messages:
            return {
                'logs': [],
                'reset': False,
            }

        if after_id is None or after_id <= 0:
            return {
                'logs': _copy_logs(log_messages[-limit:]),
                'reset': True,
            }

        earliest_id = log_messages[0]['id']
        if after_id < earliest_id:
            return {
                'logs': _copy_logs(log_messages[-limit:]),
                'reset': True,
            }

        return {
            'logs': _copy_logs([item for item in log_messages if item['id'] > after_id]),
            'reset': False,
        }

def cleanup_old_logs(retention_days=LOG_RETENTION_DAYS):
    """删除超过保留期的 log_YYMMDD.txt，返回删除的文件数。

    - 只处理严格匹配 `log_` + 6 位日期 + `.txt` 的文件，其他文件一律不碰
    - 文件名日期解析失败则跳过，绝不按 mtime 猜测
    - 截止日当天及更新的文件保留（当天文件必然保留）

    :param retention_days: 保留天数，超过该天数的文件才会被删除
    :return: 实际删除的文件数量
    """
    cutoff = (datetime.now() - timedelta(days=retention_days)).date()
    try:
        names = os.listdir(LOG_PATH)
    except OSError as e:
        print(f"读取日志目录失败，跳过清理: {e}")
        return 0

    removed = 0
    for name in names:
        m = _LOG_FILE_RE.fullmatch(name)
        if not m:
            continue
        try:
            file_day = datetime.strptime(m.group(1), '%y%m%d').date()
        except ValueError:
            continue
        if file_day >= cutoff:
            continue
        try:
            os.remove(os.path.join(LOG_PATH, name))
            removed += 1
        except OSError as e:
            print(f"清理历史日志失败 {name}: {e}")
    return removed

def log(level="INFO", message=''):
    """日志输出入口（保持原有调用方式不变）。

    实际写入统一交给 log_server()：内存列表 + 当天日志文件 + 控制台。
    """
    log_server(level, message)

# 启动时执行一次日志保留策略：web_server / wxbot_core 首次 import logger 即触发
_removed_old_logs = cleanup_old_logs()
if _removed_old_logs:
    log("INFO", f"已清理 {_removed_old_logs} 个超过 {LOG_RETENTION_DAYS} 天的历史日志文件（当天文件保留）")
