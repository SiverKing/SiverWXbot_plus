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
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import logging
from functools import wraps
import threading
from wxbot_class_only_V2 import WXBot
from logger import log
import logger
import pythoncom
import webbrowser
import time
import socket
import email_send

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
app = Flask(__name__, template_folder=resource_path('templates'))
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
    # 隐藏 api_configs 中的 key
    for item in config.get('api_configs', []):
        if item.get('key'):
            item['key'] = '*' * min(len(item['key']), 24)

    # —— 新增字段默认值（关键）——
    config.setdefault('group_welcome_random', 1.0)          # 新人欢迎概率
    config.setdefault('chat_keyword_switch', False)          # 私聊关键词开关
    config.setdefault('group_keyword_switch', False)         # 群组关键词开关
    config.setdefault('keyword_dict', {})                    # 关键词字典
    config.setdefault('scheduled_msg_switch', config.get('everyday_msg_switch', False))  # 定时消息开关
    config.setdefault('scheduled_msg_list', [])              # 定时消息任务列表
    # 旧配置迁移：everyday_msg_dict -> scheduled_msg_list
    if not config.get('scheduled_msg_list') and config.get('everyday_msg_dict'):
        import uuid
        migrated = []
        for target, tasks in config.get('everyday_msg_dict', {}).items():
            for task in tasks:
                migrated.append({
                    'id': str(uuid.uuid4())[:8],
                    'enabled': True,
                    'target': target,
                    'time': task.get('time', '08:00'),
                    'repeat_type': 'daily',
                    'weekdays': [],
                    'dates': [],
                    'msgs': task.get('msgs', []),
                })
        config['scheduled_msg_list'] = migrated
    config.setdefault('everyday_start_stop_bot_switch', False)
    config.setdefault('everyday_start_bot_time', "08:00")
    config.setdefault('everyday_stop_bot_time', "23:00")
    config.setdefault('memory_switch', True)
    config.setdefault('memory_max_count', 500)
    config.setdefault('memory_context_count', 100)

    return render_template('dashboard.html', config=config, logs=log_messages[-50:])

@app.route('/get_logs')
@login_required
def get_logs():
    return jsonify({'logs': logger.log_messages[-50:]})

def _coerce_bool_fields(merged_config):
    boolean_fields = [
        'AllListen_switch',
        'group_switch',
        'group_reply_at',
        'group_welcome',
        'new_friend_switch',
        'new_friend_reply_switch',
        # —— 新增布尔字段 ——
        'chat_keyword_switch',
        'group_keyword_switch',
        'scheduled_msg_switch',
        'everyday_start_stop_bot_switch',   # 新增
        'memory_switch',                    # 记忆开关
    ]
    for field in boolean_fields:
        if field in merged_config:
            v = merged_config[field]
            if isinstance(v, str):
                merged_config[field] = (v.lower() in ('on', 'true', '1'))
            else:
                merged_config[field] = bool(v)

def _coerce_list_fields(merged_config):
    list_fields = ['listen_list', 'group', 'new_friend_msg', 'scheduled_msg_list']
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

        # api_configs 中 key 为星号时保留原值
        if 'api_configs' in config_data and isinstance(config_data['api_configs'], list):
            orig_configs = current_config.get('api_configs', [])
            for i, item in enumerate(config_data['api_configs']):
                if isinstance(item.get('key'), str) and item['key'].startswith('*'):
                    item['key'] = orig_configs[i].get('key', '') if i < len(orig_configs) else ''

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

# 启动/停止机器人
bot = None
bot_thread = None

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
        bot = WXBot()
        bot.run()
        pythoncom.CoUninitialize()
    try:
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
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
            return jsonify({'status': 'success', 'message': '机器人已停止'})
        else:
            log('ERROR', '停止机器人失败')
            return jsonify({'status': 'error', 'message': '停止机器人失败'})
    else:
        log('WARNING', '状态：机器人未运行')
        return jsonify({'status': 'error', 'message': '机器人未运行'})

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
    for item in config.get('api_configs', []):
        if item.get('key'):
            item['key'] = '*' * min(len(item['key']), 24)
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

import shutil

MEMORY_BASE = os.path.join(base_dir(), 'memory')

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

@app.route('/memory/chats/<wx_id>')
@login_required
def memory_chats(wx_id):
    """返回指定微信号下所有窗口名"""
    try:
        wx_path = os.path.join(MEMORY_BASE, wx_id)
        if not os.path.exists(wx_path):
            return jsonify({'status': 'success', 'chats': []})
        chats = [d for d in os.listdir(wx_path)
                 if os.path.isdir(os.path.join(wx_path, d))]
        return jsonify({'status': 'success', 'chats': chats})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/memory/data/<wx_id>/<chat_name>')
@login_required
def memory_data(wx_id, chat_name):
    """返回指定窗口的记忆数据（JSON 列表）"""
    try:
        file_path = os.path.join(MEMORY_BASE, wx_id, chat_name, f"{chat_name}_memory.json")
        if not os.path.exists(file_path):
            return jsonify({'status': 'success', 'messages': []})
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
        chat_path = os.path.join(MEMORY_BASE, wx_id, chat_name)
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
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, ensure_ascii=False, indent=4)
            log('WARNING', '配置文件不存在，已创建默认配置文件')
        log('INFO', '服务5s后启动')
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