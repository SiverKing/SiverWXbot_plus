# /mnt/data/web_server.py
# ---------------------------------------------
# 机器人管理网页（含关键词与群欢迎概率扩展）
# ---------------------------------------------
"""
机器人管理网页
使用 Flask 框架开发，提供机器人控制、配置管理等功能
"""
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import json
import os
import shutil
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import logging
from functools import wraps
import threading
from wxbot_core import WXBot, version as BOT_VERSION
from logger import log
import logger
import pythoncom
import webbrowser
import time
import socket
import email_send
import ctypes
import atexit

# fix_paths.py
import sys
def resource_path(relative_path):
    """ 获取资源的绝对路径（打包后指向 _MEIPASS，用于只读资源如 templates）"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def base_dir():
    """获取运行时基础目录（打包后为 exe 所在目录，开发时为脚本所在目录）"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")

# 初始化 Flask 应用
app = Flask(__name__, template_folder=resource_path('templates'), static_folder=resource_path('templates/static'))
app.secret_key = 'your_very_long_and_random_secret_key_here'

# 安全配置
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(days=15)
)

# 配置参数
app.secret_key = 'your_secret_key_here'
PORT = 10001
CONFIG_FILE = os.path.join(base_dir(), 'config', 'config.json')
ADMIN_FILE  = os.path.join(base_dir(), 'config', 'admin.json')
EMAIL_FILE  = os.path.join(base_dir(), 'config', 'email.txt')
PROMPT_DIR  = os.path.join(base_dir(), 'config', 'prompt')
BACKUP_BASE = os.path.join(base_dir(), 'old_wxbot_config')
DEFAULT_PROMPT_CONTENT = "你是一个ai回复助手，请根据用户的问题给出回答,回复尽量保持在30字以内"

# 启动时确保目录存在
os.makedirs(os.path.join(base_dir(), 'config'),      exist_ok=True)
os.makedirs(os.path.join(base_dir(), 'panel_logs'),  exist_ok=True)

def load_admin_credentials():
    """从 admin.json 读取账密，文件不存在时自动创建默认账密文件"""
    default = {"username": "admin", "password": "123456"}
    if not os.path.exists(ADMIN_FILE):
        try:
            with open(ADMIN_FILE, 'w', encoding='utf-8') as f:
                json.dump(default, f, ensure_ascii=False, indent=4)
            log('WARNING', f'账密文件不存在，已创建默认账密文件: {ADMIN_FILE}，请及时修改密码')
        except Exception as e:
            log('ERROR', f'创建账密文件失败: {e}，使用默认账密')
        return default
    try:
        with open(ADMIN_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return {
            "username": data.get("username", default["username"]),
            "password": data.get("password", default["password"]),
        }
    except Exception as e:
        log('ERROR', f'读取账密文件失败: {e}，使用默认账密')
        return default

# 用户认证信息（从 admin.json 加载）
USERS = load_admin_credentials()

# 日志颜色映射
LOG_COLORS = {
    'INFO': 'text-primary',
    'WARNING': 'text-warning',
    'ERROR': 'text-danger',
    'DEBUG': 'text-secondary',
    'SUCCESS': 'text-success'
}

log_messages = []

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith('/api/') or request.accept_mimetypes.accept_json:
                return jsonify({'status': 'error', 'message': '未登录'}), 401
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def log_server(level, msg):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = {
        'time': timestamp,
        'level': level,
        'message': msg,
        'color': LOG_COLORS.get(level.upper(), 'text-dark')
    }
    log_messages.append(log_entry)
    if len(log_messages) > 1000:
        log_messages.pop(0)
    print(f"[{timestamp}] [{level}] {msg}")

# ----------------------------------------------------------
# Prompt 文件管理辅助函数
# ----------------------------------------------------------

def _ensure_prompt_dir():
    """确保 prompt 目录存在，若为空则创建默认 prompt 文件"""
    os.makedirs(PROMPT_DIR, exist_ok=True)
    try:
        md_files = [f for f in os.listdir(PROMPT_DIR) if f.endswith('.md')]
    except Exception:
        md_files = []
    if not md_files:
        try:
            with open(os.path.join(PROMPT_DIR, '默认.md'), 'w', encoding='utf-8') as f:
                f.write(DEFAULT_PROMPT_CONTENT)
        except Exception as e:
            log('ERROR', f'创建默认 prompt 文件失败: {e}')

def _get_prompts_list():
    """扫描 PROMPT_DIR，返回 [{name, content}]，"默认" 排第一"""
    _ensure_prompt_dir()
    prompts = []
    try:
        for fname in os.listdir(PROMPT_DIR):
            if not fname.endswith('.md'):
                continue
            name = fname[:-3]
            try:
                with open(os.path.join(PROMPT_DIR, fname), 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                content = ''
            prompts.append({'name': name, 'content': content})
    except Exception as e:
        log('ERROR', f'扫描 prompt 目录失败: {e}')
    # "默认" 排第一，其余字典序
    prompts.sort(key=lambda p: (0 if p['name'] == '默认' else 1, p['name']))
    return prompts

def _migrate_prompt_from_config(config):
    """若 config dict 中存在旧 prompt 字段，迁移到 默认.md，返回 True 表示需要写回。
    注意：不在迁移前调用 _ensure_prompt_dir()，避免其提前创建空白默认文件
    导致旧 prompt 内容被跳过而永久丢失。"""
    if 'prompt' not in config:
        return False
    os.makedirs(PROMPT_DIR, exist_ok=True)  # 只建目录，不创建任何默认文件
    target = os.path.join(PROMPT_DIR, '默认.md')
    try:
        with open(target, 'w', encoding='utf-8') as f:
            f.write(config['prompt'])
        log('SUCCESS', '旧 prompt 字段已迁移至 config/prompt/默认.md')
        del config['prompt']   # 只有写入成功才删除字段，防止数据丢失
        return True
    except Exception as e:
        log('ERROR', f'迁移 prompt 文件失败: {e}，旧 prompt 字段已保留')
        return False

# ----------------------------------------------------------
# 数据备份辅助函数
# ----------------------------------------------------------

def _do_backup():
    """
    执行一次完整数据备份：
      - 将 config/ 和 memory/ 复制到 old_wxbot_config/<时间戳>/
      - 在时间戳目录内创建以当前版本号命名的空标记文件（如 V4.6.10）
    返回备份目录的绝对路径。
    """
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    backup_dir = os.path.join(BACKUP_BASE, ts)
    os.makedirs(backup_dir, exist_ok=True)

    config_src = os.path.join(base_dir(), 'config')
    memory_src = os.path.join(base_dir(), 'memory')

    if os.path.exists(config_src):
        shutil.copytree(config_src, os.path.join(backup_dir, 'config'))
    if os.path.exists(memory_src):
        shutil.copytree(memory_src, os.path.join(backup_dir, 'memory'))

    # 创建版本号标记文件（空文件，文件名即版本号）
    version_marker = os.path.join(backup_dir, BOT_VERSION)
    try:
        open(version_marker, 'w').close()
    except Exception:
        pass

    log('SUCCESS', f'数据已备份至: {backup_dir}')
    return backup_dir


def _check_and_auto_backup():
    """
    启动时自动检查并决定是否需要备份：
      - 首次运行（old_wxbot_config 不存在）且存在 config/ 或 memory/ → 立即备份
      - 已有备份但最新一次距今超过 3 天 → 自动备份
      - 最新备份的版本号标记文件与当前版本不一致 → 自动备份
    """
    config_src = os.path.join(base_dir(), 'config')
    memory_src = os.path.join(base_dir(), 'memory')
    has_data = os.path.exists(config_src) or os.path.exists(memory_src)
    if not has_data:
        return  # 没有任何数据，无需备份

    if not os.path.exists(BACKUP_BASE):
        log('INFO', '首次检测到数据目录，自动备份中...')
        _do_backup()
        return

    # 找所有格式为 14 位纯数字的备份目录（YYYYMMDDHHmmss）
    try:
        backups = [
            d for d in os.listdir(BACKUP_BASE)
            if os.path.isdir(os.path.join(BACKUP_BASE, d))
            and len(d) == 14 and d.isdigit()
        ]
    except Exception:
        backups = []

    if not backups:
        log('INFO', '备份目录为空，执行首次自动备份...')
        _do_backup()
        return

    latest = max(backups)  # 字典序最大即最新时间戳

    # 判断距上次备份天数
    try:
        latest_dt = datetime.strptime(latest, '%Y%m%d%H%M%S')
        days_diff = (datetime.now() - latest_dt).days
    except Exception:
        days_diff = 999  # 解析失败时强制备份

    # 判断最新备份是否包含当前版本号标记文件
    latest_path = os.path.join(BACKUP_BASE, latest)
    version_match = os.path.exists(os.path.join(latest_path, BOT_VERSION))

    if days_diff > 3:
        log('INFO', f'距上次备份已 {days_diff} 天（超过3天），自动备份中...')
        _do_backup()
    elif not version_match:
        # 找出实际存储的旧版本号（遍历目录内不含 / 的文件）
        try:
            old_ver_files = [f for f in os.listdir(latest_path)
                             if os.path.isfile(os.path.join(latest_path, f))
                             and f.startswith('V')]
            old_ver = old_ver_files[0] if old_ver_files else '未知版本'
        except Exception:
            old_ver = '未知版本'
        log('INFO', f'检测到版本变更（{old_ver} → {BOT_VERSION}），自动备份中...')
        _do_backup()

# 读取配置文件
def read_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log('ERROR', f'读取配置文件失败: {str(e)}')
        return None

@app.route('/api/check_auth')
def check_auth():
    return jsonify({'authenticated': session.get('logged_in', False)})

# 登录页
@app.route('/', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
    logout_success = request.args.get('logout') == 'success'
    error = None

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        def safe_str_cmp(a, b):
            if len(a) != len(b):
                return False
            result = 0
            for x, y in zip(a, b):
                result |= ord(x) ^ ord(y)
            return result == 0

        if username == USERS['username'] and safe_str_cmp(USERS['password'], password):
            session['logged_in'] = True
            session['username'] = username
            session.permanent = True
            log('SUCCESS', f'用户 {username} 登录成功')
            next_page = request.args.get('next') or url_for('dashboard')
            return redirect(next_page)
        else:
            log('WARNING', f'登录失败: 用户名或密码错误 (用户名: {username})')
            return render_template('login.html', error='用户名或密码错误')

    return render_template('login.html', error=error, logout_success=logout_success)

@app.route('/logout')
def logout():
    session.clear()
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(url_for('login'))

# 仪表盘
@app.route('/dashboard')
@login_required
def dashboard():
    config = read_config()
    if not config:
        return render_template('error.html', message='无法读取配置文件')

    # 旧配置迁移：只要旧字段存在就迁移并写回磁盘（无论 api_configs 是否已有）
    if 'api_sdk' in config:
        config['api_configs'] = [
            {'sdk': config.get('api_sdk', 'DusAPI'), 'key': config.get('api_key', ''),
             'url': config.get('base_url', 'https://api.dusapi.com'), 'model': config.get('model1', 'gpt-5')},
            {'sdk': config.get('api_sdk', 'DusAPI'), 'key': config.get('api_key', ''),
             'url': config.get('base_url', 'https://api.dusapi.com'), 'model': config.get('model2', 'claude-sonnet-4-6')},
        ]
        config['api_index'] = 0
        for old_key in ('api_sdk', 'api_key', 'base_url', 'model1', 'model2', 'api_sdk_list'):
            config.pop(old_key, None)
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as _f:
                json.dump(config, _f, ensure_ascii=False, indent=4)
            log('SUCCESS', '旧 API 配置已自动迁移为新格式并保存')
        except Exception as _e:
            log('ERROR', f'迁移配置写入失败: {_e}')
    config.setdefault('api_configs', [
        {"sdk": "DusAPI", "key": "", "url": "https://api.dusapi.com", "model": "gpt-5"},
        {"sdk": "DusAPI", "key": "", "url": "https://api.dusapi.com", "model": "claude-sonnet-4-6"},
    ])
    config.setdefault('api_index', 0)

    # —— 新增字段默认值（关键）——
    config.setdefault('group_api_map', {})                   # 群组专属接口映射
    config.setdefault('group_welcome_random', 1.0)          # 新人欢迎概率
    config.setdefault('chat_keyword_switch', False)          # 私聊关键词开关
    config.setdefault('group_keyword_switch', False)         # 群组关键词开关
    config.setdefault('group_keyword_at_only', False)        # 群聊关键词仅@时回复
    config.setdefault('keyword_dict', {})                    # 关键词字典
    config.setdefault('scheduled_msg_switch', config.get('everyday_msg_switch', False))  # 定时消息开关
    config.setdefault('scheduled_msg_list', [])              # 定时消息任务列表
    config.setdefault('scheduled_moments_switch', False)     # 定时朋友圈开关
    config.setdefault('scheduled_moments_list', [])          # 定时朋友圈任务列表
    config.setdefault('moments_like_switch', False)          # 随机朋友圈点赞开关
    config.setdefault('moments_like_min', 60)                # 随机点赞最小间隔（分钟）
    config.setdefault('moments_like_max', 120)               # 随机点赞最大间隔（分钟）
    config.setdefault('random_moments_switch', False)        # 随机定时朋友圈开关
    config.setdefault('random_moments_list', [])             # 随机定时朋友圈任务列表
    # 旧配置迁移：everyday_msg_dict -> scheduled_msg_list
    if not config.get('scheduled_msg_list') and config.get('everyday_msg_dict'):
        import uuid
        migrated = []
        for target, tasks in config.get('everyday_msg_dict', {}).items():
            for task in tasks:
                migrated.append({
                    'id': str(uuid.uuid4())[:8],
                    'enabled': True,
                    'targets': [target],
                    'time': task.get('time', '08:00'),
                    'repeat_type': 'daily',
                    'weekdays': [],
                    'dates': [],
                    'msgs': task.get('msgs', []),
                })
        config['scheduled_msg_list'] = migrated
    # 旧配置迁移：target(str) -> targets(list)
    _target_migrated = False
    for task in config.get('scheduled_msg_list', []):
        if 'targets' not in task:
            old = task.pop('target', '')
            task['targets'] = [old] if old else []
            _target_migrated = True
    if _target_migrated:
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as _f:
                json.dump(config, _f, ensure_ascii=False, indent=4)
            log('SUCCESS', '定时消息发送目标格式已自动迁移 target -> targets')
        except Exception as _e:
            log('ERROR', f'迁移定时消息目标格式写入失败: {_e}')
    config.setdefault('everyday_start_stop_bot_switch', False)
    config.setdefault('everyday_start_bot_time', "08:00")
    config.setdefault('everyday_stop_bot_time', "23:00")
    config.setdefault('memory_switch', True)
    config.setdefault('memory_max_count', 3000)
    config.setdefault('memory_context_count', 1000)
    config.setdefault('reply_delay_switch', True)
    config.setdefault('reply_delay_min', 1)
    config.setdefault('reply_delay_max', 5)
    config.setdefault('chat_image_recognition_switch', False)   # 私聊图片识别开关
    config.setdefault('chat_image_recognition_api',    0)        # 私聊识别接口索引
    config.setdefault('group_image_recognition_switch', False)  # 群组图片识别开关
    config.setdefault('group_image_recognition_api',   0)        # 群组识别接口索引
    config.setdefault('custom_forward_switch', False)            # 自定义转发总开关
    config.setdefault('custom_forward_list', [])                 # 自定义转发规则列表

    # 多 Prompt：迁移旧 prompt 字段 + 补充新字段默认值
    if _migrate_prompt_from_config(config):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as _f:
                json.dump(config, _f, ensure_ascii=False, indent=4)
            log('SUCCESS', '旧 prompt 字段已迁移，config.json 已更新')
        except Exception as _e:
            log('ERROR', f'迁移后写回 config.json 失败: {_e}')
    _ensure_prompt_dir()
    prompts = _get_prompts_list()
    config.setdefault('default_prompt', '默认')
    config.setdefault('chat_prompt_map', {})
    config.setdefault('chat_api_map', {})
    config.setdefault('group_prompt_map', {})
    config.setdefault('api_error_reply', '在忙，我稍后回复您')   # 接口调用失败时的固定回复
    config.setdefault('chat_split_reply_switch', False)   # 私聊拆分多条回复开关
    config.setdefault('chat_split_max_chars', 100)        # 私聊单条最大字数
    config.setdefault('chat_split_max_count', 4)          # 私聊最多条数
    config.setdefault('group_split_reply_switch', False)  # 群聊拆分多条回复开关
    config.setdefault('group_split_max_chars', 100)       # 群聊单条最大字数
    config.setdefault('group_split_max_count', 4)         # 群聊最多条数

    return render_template('dashboard.html', config=config, logs=log_messages[-50:], prompts=prompts)

@app.route('/get_logs')
@login_required
def get_logs():
    return jsonify({'logs': logger.log_messages[-50:]})

def _coerce_bool_fields(merged_config):
    boolean_fields = [
        'AllListen_switch',
        'AllListen_filter_mute',
        'group_switch',
        'group_reply_at',
        'group_welcome',
        'new_friend_switch',
        'new_friend_reply_switch',
        # —— 新增布尔字段 ——
        'chat_keyword_switch',
        'group_keyword_switch',
        'group_keyword_at_only',
        'scheduled_msg_switch',
        'scheduled_moments_switch',         # 定时朋友圈开关
        'moments_like_switch',              # 随机朋友圈点赞开关
        'random_moments_switch',            # 随机定时朋友圈开关
        'everyday_start_stop_bot_switch',   # 新增
        'memory_switch',                    # 记忆开关
        'reply_delay_switch',               # 发送延迟开关
        'chat_image_recognition_switch',    # 私聊图片识别开关
        'group_image_recognition_switch',   # 群组图片识别开关
        'custom_forward_switch',            # 自定义转发总开关
        'chat_split_reply_switch',          # 私聊拆分多条回复开关
        'group_split_reply_switch',         # 群聊拆分多条回复开关
    ]
    for field in boolean_fields:
        if field in merged_config:
            v = merged_config[field]
            if isinstance(v, str):
                merged_config[field] = (v.lower() in ('on', 'true', '1'))
            else:
                merged_config[field] = bool(v)

def _coerce_list_fields(merged_config):
    list_fields = ['listen_list', 'group', 'new_friend_msg', 'scheduled_msg_list', 'scheduled_moments_list', 'random_moments_list', 'custom_forward_list']
    for field in list_fields:
        if field in merged_config and not isinstance(merged_config[field], list):
            if isinstance(merged_config[field], str):
                merged_config[field] = [merged_config[field]] if merged_config[field] else []
            else:
                merged_config[field] = []
        if field in merged_config:
            merged_config[field] = [item for item in merged_config[field] if str(item).strip()]

def _coerce_float_fields(merged_config):
    # 仅当前需要 group_welcome_random，限定 [0.0, 1.0]
    if 'group_welcome_random' in merged_config:
        try:
            val = float(merged_config['group_welcome_random'])
            if val < 0.0: val = 0.0
            if val > 1.0: val = 1.0
            merged_config['group_welcome_random'] = val
        except (TypeError, ValueError):
            # 若非法，则保持原值或回退默认
            merged_config['group_welcome_random'] = float(read_config().get('group_welcome_random', 1.0))

def _coerce_dict_fields(merged_config):
    # keyword_dict 支持：dict / JSON字符串 / list[{key, value}]
    if 'keyword_dict' in merged_config:
        kd = merged_config['keyword_dict']
        if isinstance(kd, dict):
            return
        if isinstance(kd, str):
            try:
                obj = json.loads(kd)
                if isinstance(obj, dict):
                    merged_config['keyword_dict'] = obj
                    return
            except Exception:
                pass
        if isinstance(kd, list):
            out = {}
            for item in kd:
                if isinstance(item, dict):
                    key = str(item.get('key', '')).strip()
                    val = str(item.get('value', ''))
                    if key:
                        out[key] = val
            merged_config['keyword_dict'] = out
            return
        # 其他情况回退空 dict
        merged_config['keyword_dict'] = {}

    # group_api_map: 值必须为 int 接口索引，非法值自动过滤
    if 'group_api_map' in merged_config:
        gam = merged_config['group_api_map']
        if isinstance(gam, dict):
            clean = {}
            for k, v in gam.items():
                k = str(k).strip()
                try:
                    vi = int(v)
                    if k and vi >= 0:
                        clean[k] = vi
                except (ValueError, TypeError):
                    pass
            merged_config['group_api_map'] = clean
        else:
            merged_config['group_api_map'] = {}

    # chat_api_map: 同 group_api_map，适用于私聊白名单用户
    if 'chat_api_map' in merged_config:
        cam = merged_config['chat_api_map']
        if isinstance(cam, dict):
            clean = {}
            for k, v in cam.items():
                k = str(k).strip()
                try:
                    vi = int(v)
                    if k and vi >= -1:
                        clean[k] = vi
                except (ValueError, TypeError):
                    pass
            merged_config['chat_api_map'] = clean
        else:
            merged_config['chat_api_map'] = {}

    # chat_prompt_map: 值为非空字符串（prompt 文件名）
    if 'chat_prompt_map' in merged_config:
        cpm = merged_config['chat_prompt_map']
        if isinstance(cpm, dict):
            clean = {}
            for k, v in cpm.items():
                k = str(k).strip()
                v = str(v).strip()
                if k and v:
                    clean[k] = v
            merged_config['chat_prompt_map'] = clean
        else:
            merged_config['chat_prompt_map'] = {}

    # group_prompt_map: 同 chat_prompt_map，适用于群组
    if 'group_prompt_map' in merged_config:
        gpm = merged_config['group_prompt_map']
        if isinstance(gpm, dict):
            clean = {}
            for k, v in gpm.items():
                k = str(k).strip()
                v = str(v).strip()
                if k and v:
                    clean[k] = v
            merged_config['group_prompt_map'] = clean
        else:
            merged_config['group_prompt_map'] = {}

# 保存配置文件
def save_config(config_data):
    try:
        original_config = read_config() or {}
        merged_config = {**original_config, **config_data}

        # 若已有新格式 api_configs，清除旧 API 字段
        if 'api_configs' in merged_config:
            for _k in ('api_sdk', 'api_key', 'base_url', 'model1', 'model2', 'api_sdk_list'):
                merged_config.pop(_k, None)

        _coerce_bool_fields(merged_config)
        _coerce_list_fields(merged_config)
        _coerce_float_fields(merged_config)
        _coerce_dict_fields(merged_config)

        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(merged_config, f, ensure_ascii=False, indent=4)
        log('SUCCESS', '配置文件保存成功')
        return True
    except Exception as e:
        log('ERROR', f'保存配置文件失败: {str(e)}')
        return False

#   保存配置
update_config_status = False # 记录是否更新了定时启停状态
@app.route('/save_config', methods=['POST'])
@login_required
def save_config_route():
    try:
        config_data = request.get_json()
        if not config_data:
            return jsonify({'status': 'error', 'message': '无效的配置数据'})

        current_config = read_config() or {}

        merged_config = {**current_config, **config_data}

        # 若已有 api_configs，清理旧 API 字段（兼容保存时自动完成迁移）
        if 'api_configs' in merged_config:
            for _k in ('api_sdk', 'api_key', 'base_url', 'model1', 'model2', 'api_sdk_list'):
                merged_config.pop(_k, None)

        # 预处理（与 save_config 二次校验互补）
        _coerce_bool_fields(merged_config)
        _coerce_list_fields(merged_config)
        _coerce_float_fields(merged_config)
        _coerce_dict_fields(merged_config)

        if save_config(merged_config):
            global update_config_status
            update_config_status = True # 执行了保存配置
            return jsonify({'status': 'success', 'message': '配置保存成功'})
        else:
            return jsonify({'status': 'error', 'message': '配置保存失败'})
    except Exception as e:
        log('ERROR', f'保存配置出错: {str(e)}')
        return jsonify({'status': 'error', 'message': str(e)})

# ----------------------------------------------------------
# Prompt 文件管理路由
# ----------------------------------------------------------

@app.route('/list_prompts')
@login_required
def list_prompts_route():
    return jsonify({'status': 'success', 'prompts': _get_prompts_list()})

@app.route('/save_prompt', methods=['POST'])
@login_required
def save_prompt_route():
    import re, tempfile
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'msg': '无效请求'})
        name     = str(data.get('name', '')).strip()
        content  = str(data.get('content', ''))
        old_name = str(data.get('old_name', '')).strip()
        # 去掉用户误填的 .md 后缀
        if name.lower().endswith('.md'):
            name = name[:-3].strip()
        if not name:
            return jsonify({'status': 'error', 'msg': 'Prompt 名称不能为空'})
        # 白名单校验：只允许中文/字母/数字/空格/下划线/连字符
        if not re.fullmatch(r'[\u4e00-\u9fff\w\s\-]+', name):
            return jsonify({'status': 'error', 'msg': 'Prompt 名称含非法字符（只允许中文、字母、数字、空格、_ 和 -）'})
        _ensure_prompt_dir()
        # 重命名：删除旧文件
        if old_name and old_name != name:
            old_path = os.path.join(PROMPT_DIR, f'{old_name}.md')
            if os.path.exists(old_path):
                os.remove(old_path)
        # 原子写入
        target = os.path.join(PROMPT_DIR, f'{name}.md')
        tmp_fd, tmp_path = tempfile.mkstemp(dir=PROMPT_DIR, suffix='.tmp')
        try:
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as tf:
                tf.write(content)
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise
        log('SUCCESS', f'Prompt 已保存：{name}.md')
        return jsonify({'status': 'success'})
    except Exception as e:
        log('ERROR', f'保存 Prompt 失败: {e}')
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/delete_prompt', methods=['POST'])
@login_required
def delete_prompt_route():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'msg': '无效请求'})
        name = str(data.get('name', '')).strip()
        if not name:
            return jsonify({'status': 'error', 'msg': '名称不能为空'})
        _ensure_prompt_dir()
        # 不允许删除最后一个
        md_files = [f for f in os.listdir(PROMPT_DIR) if f.endswith('.md')]
        if len(md_files) <= 1:
            return jsonify({'status': 'error', 'msg': '不允许删除最后一个 Prompt'})
        target = os.path.join(PROMPT_DIR, f'{name}.md')
        if os.path.exists(target):
            os.remove(target)
        log('SUCCESS', f'Prompt 已删除：{name}.md')
        return jsonify({'status': 'success'})
    except Exception as e:
        log('ERROR', f'删除 Prompt 失败: {e}')
        return jsonify({'status': 'error', 'msg': str(e)})

# 启动/停止机器人
bot = None
bot_thread = None

# ============================================================
# 防锁屏 / 防睡眠工具函数（Windows SetThreadExecutionState）
# ============================================================
_ES_CONTINUOUS       = 0x80000000
_ES_SYSTEM_REQUIRED  = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002

def _prevent_sleep():
    """阻止 Windows 自动锁屏、黑屏、睡眠，机器人运行期间保持系统唤醒状态"""
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(
            _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
        )
        log('INFO', '【防锁屏】已阻止 Windows 自动锁屏/黑屏/睡眠，避免影响微信自动化操作')
    except Exception as e:
        log('WARNING', f'【防锁屏】设置防睡眠状态失败: {e}')

def _restore_sleep():
    """恢复 Windows 原有的锁屏、黑屏、睡眠策略"""
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
        log('INFO', '【防锁屏】已恢复 Windows 原有锁屏/黑屏/睡眠策略')
    except Exception as e:
        log('WARNING', f'【防锁屏】恢复睡眠策略失败: {e}')

# 服务器进程异常退出时兜底恢复
atexit.register(_restore_sleep)

@app.route('/start_bot', methods=['POST'])
@login_required
def start_bot():
    log('INFO', '机器人启动请求已接收')
    global bot_thread
    if bot_thread and bot_thread.is_alive():
        log("WARNING", "状态：机器人已在运行")
        return jsonify({'status': 'success', 'message': '机器人已在运行'})

    def run_bot():
        pythoncom.CoInitialize()
        global bot
        try:
            # 启动前先清理旧实例的残留监听，防止崩溃重启后同一群/用户被双重注册导致双回调
            if bot:
                try:
                    bot.stop()
                    log('INFO', '已清理上次残留的 WeChat 监听')
                except Exception as _e:
                    log('WARNING', f'清理旧监听时出错（可忽略）: {_e}')
            bot = WXBot()
            bot.run()
        finally:
            pythoncom.CoUninitialize()
            _restore_sleep()
    try:
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        _prevent_sleep()
    except Exception as e:
        log('ERROR', f'启动机器人失败: {str(e)}')
    return jsonify({'status': 'success', 'message': '机器人启动命令已发送'})

@app.route('/stop_bot', methods=['POST'])
@login_required
def stop_bot():
    log('INFO', '机器人停止请求已接收')
    global bot_thread, bot
    if bot_thread and bot_thread.is_alive():
        if bot.stop_wxbot():
            log('SUCCESS', '机器人已停止')
            bot_thread = None
            bot = None
            _restore_sleep()
            return jsonify({'status': 'success', 'message': '机器人已停止'})
        else:
            log('ERROR', '停止机器人失败')
            return jsonify({'status': 'error', 'message': '停止机器人失败'})
    else:
        log('WARNING', '状态：机器人未运行')
        return jsonify({'status': 'error', 'message': '机器人未运行'})

@app.route('/check_activate')
@login_required
def check_activate():
    try:
        from wxautox4.utils.useful import check_license
        activated = check_license()
        return jsonify({'status': 'success', 'data': {'activated': bool(activated)}})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/activate', methods=['POST'])
@login_required
def activate():
    try:
        data = request.get_json()
        code = (data.get('code') or '').strip()
        if not code:
            return jsonify({'status': 'error', 'message': '激活码不能为空'})
        from wxautox4.utils.useful import authenticate
        result = authenticate(code)
        if result:
            log('SUCCESS', f'wxautox4 激活成功')
            return jsonify({'status': 'success', 'message': '激活成功！'})
        else:
            log('WARNING', f'wxautox4 激活失败，激活码无效或已过期')
            return jsonify({'status': 'error', 'message': '激活失败，激活码无效或已过期'})
    except Exception as e:
        log('ERROR', f'激活出错: {e}')
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/check_update')
@login_required
def check_update():
    try:
        import requests as req
        import wxbot_core as wxbot_mod
        local_version = getattr(wxbot_mod, 'version', '')
        r = req.get('https://wxbot.siverking.online/version.json', timeout=8)
        data = r.json()
        data['local_version'] = local_version
        return jsonify({'status': 'success', 'data': data})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/get_status')
@login_required
def get_status():
    global bot, bot_thread
    if bot_thread and bot_thread.is_alive() and bot:
        try:
            status = bot.get_status()
            status['bot_running'] = True
            return jsonify({'status': 'success', 'data': status})
        except Exception as e:
            return jsonify({'status': 'success', 'data': {'bot_running': True, 'error': str(e)}})
    else:
        return jsonify({'status': 'success', 'data': {'bot_running': False}})

@app.route('/load_config')
@login_required
def load_config():
    config = read_config()
    if not config:
        return jsonify({'status': 'error', 'message': '无法读取配置文件'})
    return jsonify({'status': 'success', 'config': config})

@app.route('/get_admin_config')
@login_required
def get_admin_config():
    try:
        with open(ADMIN_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify({'status': 'success', 'username': data.get('username', '')})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/save_admin_config', methods=['POST'])
@login_required
def save_admin_config():
    global USERS
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        if not username or not password:
            return jsonify({'status': 'error', 'message': '用户名和密码不能为空'})
        new_creds = {'username': username, 'password': password}
        with open(ADMIN_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_creds, f, ensure_ascii=False, indent=4)
        USERS = new_creds
        log('SUCCESS', f'后台账号已更新，用户名：{username}')
        return jsonify({'status': 'success', 'message': '账号密码已保存，下次登录生效'})
    except Exception as e:
        log('ERROR', f'保存账号密码失败: {e}')
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/get_email_config')
@login_required
def get_email_config():
    try:
        with open(EMAIL_FILE, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f.readlines()]
        return jsonify({
            'status': 'success',
            'host': lines[0] if len(lines) > 0 else '',
            'port': lines[1] if len(lines) > 1 else '',
            'user': lines[2] if len(lines) > 2 else '',
            'pass': lines[3] if len(lines) > 3 else '',
        })
    except FileNotFoundError:
        return jsonify({'status': 'success', 'host': '', 'port': '', 'user': '', 'pass': ''})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/save_email_config', methods=['POST'])
@login_required
def save_email_config():
    try:
        data = request.get_json()
        host = data.get('host', '').strip()
        port = data.get('port', '').strip()
        user = data.get('user', '').strip()
        pwd  = data.get('pass', '').strip()
        if not all([host, port, user, pwd]):
            return jsonify({'status': 'error', 'message': '所有字段均不能为空'})
        content = f"{host}\n{port}\n{user}\n{pwd}\n"
        with open(EMAIL_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
        log('SUCCESS', f'邮件配置已更新，SMTP: {host}:{port}，账号: {user}')
        return jsonify({'status': 'success', 'message': '邮件配置已保存'})
    except Exception as e:
        log('ERROR', f'保存邮件配置失败: {e}')
        return jsonify({'status': 'error', 'message': str(e)})

import threading

_tk_lock = threading.Lock()  # 确保同一时刻只弹一个文件选择框

@app.route('/pick_image_file', methods=['GET'])
@login_required
def pick_image_file():
    """
    打开 Windows 原生文件选择对话框，让用户选择一张本地图片，
    返回其绝对路径。前端直接将路径填入输入框，无需上传文件。
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
        path = ''
        with _tk_lock:
            root = tk.Tk()
            root.withdraw()                  # 隐藏 tk 主窗口
            root.attributes('-topmost', True)
            root.lift()
            path = filedialog.askopenfilename(
                parent=root,
                title='选择图片文件',
                filetypes=[
                    ('图片文件', '*.png *.jpg *.jpeg *.gif *.bmp *.webp *.PNG *.JPG *.JPEG'),
                    ('所有文件', '*.*'),
                ]
            )
            root.destroy()
        if path:
            import os
            path = os.path.normpath(path)    # 统一为 Windows 反斜杠路径
            return jsonify({'status': 'success', 'path': path})
        return jsonify({'status': 'cancel'})
    except Exception as e:
        log('ERROR', f'文件选择框出错: {e}')
        return jsonify({'status': 'error', 'message': str(e)})

MEMORY_BASE = os.path.join(base_dir(), 'memory')

@app.route('/api/backup_now', methods=['POST'])
@login_required
def backup_now():
    """立即执行一次数据备份，返回备份路径"""
    try:
        path = _do_backup()
        return jsonify({'status': 'success', 'message': '备份成功！', 'path': path})
    except Exception as e:
        log('ERROR', f'手动备份失败: {e}')
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/memory/list')
@login_required
def memory_list():
    """返回所有微信号目录"""
    try:
        if not os.path.exists(MEMORY_BASE):
            return jsonify({'status': 'success', 'wx_ids': []})
        wx_ids = [d for d in os.listdir(MEMORY_BASE)
                  if os.path.isdir(os.path.join(MEMORY_BASE, d))]
        return jsonify({'status': 'success', 'wx_ids': wx_ids})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

def _safe_is_dir(parent_abs, name):
    """os.path.isdir 在 Windows 上对末尾含 '.' 的名称会自动去掉 '.' 导致误判。
    用 UNC 长路径前缀绕过 Windows 路径规范化，其他系统走普通逻辑。"""
    if os.name == 'nt':
        p = '\\\\?\\' + parent_abs + '\\' + name
    else:
        p = os.path.join(parent_abs, name)
    try:
        import stat as _stat
        return _stat.S_ISDIR(os.stat(p).st_mode)
    except OSError:
        return False


@app.route('/memory/chats/<wx_id>')
@login_required
def memory_chats(wx_id):
    """返回指定微信号下所有窗口名"""
    try:
        wx_path = os.path.join(MEMORY_BASE, wx_id)
        if not os.path.exists(wx_path):
            return jsonify({'status': 'success', 'chats': []})
        wx_abs = os.path.abspath(wx_path)
        chats = [d for d in os.listdir(wx_path) if _safe_is_dir(wx_abs, d)]
        return jsonify({'status': 'success', 'chats': chats})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/memory/data/<wx_id>/<chat_name>')
@login_required
def memory_data(wx_id, chat_name):
    """返回指定窗口的记忆数据（JSON 列表）"""
    try:
        dir_abs = os.path.abspath(os.path.join(MEMORY_BASE, wx_id))
        if os.name == 'nt':
            chat_dir = '\\\\?\\' + dir_abs + '\\' + chat_name
        else:
            chat_dir = os.path.join(dir_abs, chat_name)
        if not os.path.exists(chat_dir):
            return jsonify({'status': 'success', 'messages': []})
        # 扫目录找实际的 *_memory.json 文件（Windows 可能截断目录名导致文件名与目录名不一致）
        mem_files = [f for f in os.listdir(chat_dir) if f.endswith('_memory.json')]
        if not mem_files:
            return jsonify({'status': 'success', 'messages': []})
        if os.name == 'nt':
            file_path = '\\\\?\\' + dir_abs + '\\' + chat_name + '\\' + mem_files[0]
        else:
            file_path = os.path.join(chat_dir, mem_files[0])
        with open(file_path, 'r', encoding='utf-8') as f:
            messages = json.load(f)
        return jsonify({'status': 'success', 'messages': messages if isinstance(messages, list) else []})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/memory/delete_wx/<wx_id>', methods=['DELETE'])
@login_required
def memory_delete_wx(wx_id):
    """删除指定微信号的所有记忆"""
    try:
        if os.name == 'nt':
            wx_path = '\\\\?\\' + os.path.abspath(os.path.join(MEMORY_BASE, wx_id))
        else:
            wx_path = os.path.join(MEMORY_BASE, wx_id)
        if os.path.exists(wx_path):
            shutil.rmtree(wx_path)
        log('SUCCESS', f'已删除微信号 {wx_id} 的所有记忆')
        return jsonify({'status': 'success', 'message': '已删除'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/memory/delete_chat/<wx_id>/<chat_name>', methods=['DELETE'])
@login_required
def memory_delete_chat(wx_id, chat_name):
    """删除指定窗口的记忆文件"""
    try:
        parent_abs = os.path.abspath(os.path.join(MEMORY_BASE, wx_id))
        if os.name == 'nt':
            chat_path = '\\\\?\\' + parent_abs + '\\' + chat_name
        else:
            chat_path = os.path.join(parent_abs, chat_name)
        if os.path.exists(chat_path):
            shutil.rmtree(chat_path)
        log('SUCCESS', f'已删除 {wx_id}/{chat_name} 的记忆')
        return jsonify({'status': 'success', 'message': '已删除'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


def time_start_stop():
    """定时启停"""
    def is_target_time(target_hour, target_minute):
        """
        校验当前时间是否匹配指定的小时和分钟
        """
        # 获取当前本地时间
        now = datetime.now()
        # 比较小时和分钟是否匹配
        return (now.hour == target_hour) and (now.minute == target_minute)
    def time_check_thread():
        """定时检查线程"""
        global bot_thread, bot, update_config_status
        # 读取配置文件
        time_config = read_config()
        everyday_start_stop_bot_switch = time_config.get("everyday_start_stop_bot_switch")
        start_hour = datetime.strptime(time_config.get("everyday_start_bot_time"), "%H:%M").hour
        start_minute = datetime.strptime(time_config.get("everyday_start_bot_time"), "%H:%M").minute
        stop_hour = datetime.strptime(time_config.get("everyday_stop_bot_time"), "%H:%M").hour
        stop_minute = datetime.strptime(time_config.get("everyday_stop_bot_time"), "%H:%M").minute
        if everyday_start_stop_bot_switch:
            log('INFO', f'启动定时启停线程，启动时间：{start_hour}:{start_minute}，停止时间：{stop_hour}:{stop_minute}')
        else:
            log('INFO', '定时启停未启用，未启用')

        while True:
            if update_config_status: # 保存配置后更新定时启停状态
                update_config_status = False
                time_config = read_config()
                everyday_start_stop_bot_switch = time_config.get("everyday_start_stop_bot_switch")
                start_hour = datetime.strptime(time_config.get("everyday_start_bot_time"), "%H:%M").hour
                start_minute = datetime.strptime(time_config.get("everyday_start_bot_time"), "%H:%M").minute
                stop_hour = datetime.strptime(time_config.get("everyday_stop_bot_time"), "%H:%M").hour
                stop_minute = datetime.strptime(time_config.get("everyday_stop_bot_time"), "%H:%M").minute
                if everyday_start_stop_bot_switch:
                    log('INFO', f'配置更新，启动定时启停线程，启动时间：{start_hour}:{start_minute}，停止时间：{stop_hour}:{stop_minute}')
                else:
                    log('INFO', '配置更新，定时启停未启用')
            if everyday_start_stop_bot_switch:
                if is_target_time(start_hour, start_minute): # 启动时间
                    log('INFO', '到达预定启动时间，正在启动机器人')
                    if bot_thread and bot_thread.is_alive():
                        log("WARNING", "状态：机器人已在运行")
                        email_send.send_email(subject="定时启动机器人", content="机器人已在运行，无需启动")
                    else:
                        def run_bot():
                            pythoncom.CoInitialize()  # 防止多线程调用COM组件时出错
                            global bot
                            # 启动前先清理旧实例的残留监听，防止崩溃重启后双回调
                            if bot:
                                try:
                                    bot.stop()
                                    log('INFO', '已清理上次残留的 WeChat 监听')
                                except Exception as _e:
                                    log('WARNING', f'清理旧监听时出错（可忽略）: {_e}')
                            bot = WXBot()
                            bot.run()
                            pythoncom.CoUninitialize()  # 释放COM组件
                        try:
                            bot_thread = threading.Thread(target=run_bot, daemon=True)
                            bot_thread.start()
                            email_send.send_email(subject="定时启动机器人", content="机器人已启动")
                        except Exception as e:
                            log('ERROR', f'启动机器人失败: {str(e)}')
                    time.sleep(60) # 防止一分钟内重复启动
                if is_target_time(stop_hour, stop_minute): # 停止时间
                    log('INFO', '到达预定停止时间，正在停止机器人')
                    if bot_thread and bot_thread.is_alive():
                        if bot.stop_wxbot():  # 调用停止函数并检查返回值
                            log('SUCCESS', '机器人已停止')
                            bot_thread = None
                            bot = None
                            email_send.send_email(subject="定时停止机器人", content="机器人已停止")
                        else:
                            log('ERROR', '停止机器人失败')
                    else:
                        log('WARNING', '状态：机器人未运行')
                        email_send.send_email(subject="定时停止机器人", content="机器人未运行，无需停止")
                    time.sleep(60) # 防止一分钟内重复停止
            time.sleep(10)
    
    time_thread = threading.Thread(target=time_check_thread, daemon=True)
    time_thread.start()
def find_free_port(start_port=10001, max_port=11000):
    """从 start_port 开始寻找空闲端口"""
    for port in range(start_port, max_port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError("未找到可用端口")


def main():
    logging.basicConfig(
        level=logging.WARNING,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.NullHandler()]
    )
    # 屏蔽 werkzeug 的 INFO 级别访问日志（如 /get_logs、/get_status 轮询请求）
    # WARNING 及以上（如端口冲突、路由错误）仍正常输出
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    log('INFO', '服务器启动中...')
    try:
        if not os.path.exists(CONFIG_FILE):
            default_config = {
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
                "scheduled_msg_switch": False,
                "scheduled_msg_list": [],
                "scheduled_moments_switch": False,
                "scheduled_moments_list": [],
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
                "custom_forward_switch": False,
                "custom_forward_list": [],
                "default_prompt": "默认",
                "chat_prompt_map": {},
                "chat_api_map": {},
                "group_prompt_map": {},
                "api_error_reply": "在忙，我稍后回复您",
                "chat_split_reply_switch": False,
                "chat_split_max_chars": 100,
                "chat_split_max_count": 4,
                "group_split_reply_switch": False,
                "group_split_max_chars": 100,
                "group_split_max_count": 4,
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, ensure_ascii=False, indent=4)
            log('WARNING', '配置文件不存在，已创建默认配置文件')
        log('INFO', '服务5s后启动')
        # 启动时自动备份检查
        try:
            _check_and_auto_backup()
        except Exception as _backup_e:
            log('ERROR', f'自动备份检查失败: {_backup_e}')
        # 动态选择端口
        free_port = find_free_port(10001, 11000)
        log('INFO', f'请访问 http://localhost:{free_port} 或者 http://127.0.0.1:{free_port} 进行登录')
        # 启动后自动打开浏览器
        webbrowser.open(f"http://127.0.0.1:{free_port}")
        # 定时启停
        time_start_stop()
        # 启动服务器
        app.run(host='0.0.0.0', port=free_port, debug=False)
    except Exception as e:
        log('ERROR', f'服务器启动失败: {str(e)}')
    finally:
        log('INFO', '服务器已停止')

if __name__ == '__main__':
    main()