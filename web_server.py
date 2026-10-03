# ============================================================
# 机器人管理网页（含关键词与群欢迎概率扩展）
# ============================================================

"""
机器人管理网页
使用 Flask 框架开发，提供机器人控制、配置管理等功能
"""

# ============================================================
# 【新增配置字段检查清单】改配置结构前必须读完本段
#
# 本文件已不含任何「逐字段」的配置代码：默认值 / 类型校验 / 迁移都集中在
# config_defaults.py，本文件的 dashboard() 与 save_config() 只走通用流水线。
# 所以新增字段时**不需要改 web_server.py**（下面只是全流程索引）。
#
# 全流程 = 5 步必改 + 1 步可选。各文件顶部有该文件的局部清单，编号与此处一致：
#
#   ① 默认值与类型校验 —— config_defaults.py
#        · 默认值加进 DEFAULT_CONFIG
#        · 字段类型加进对应的 _coerce_* 名单（共 6 个：bool / list /
#          float_range / int_range / api / dict）
#        · 需要旧值迁移或跨字段规范化时，加进 migrate() / normalize()
#   ② 前端控件 + 初始值 —— templates/dashboard.html
#        · 在对应的 <div class="config-panel" id="tab-xxx"> 内加控件
#        · 布尔：{% if config.get('字段名', False) %}checked{% endif %}
#        · 文本：value="{{ config.字段名 }}"
#   ③ 前端采集 —— templates/static/dashboard.js
#        · saveConfig() 里的 var configData={ ... } 加一行
#   ④ 运行时读取 —— wxbot_core.py
#        · WXBotConfig.__init__ 的属性默认值
#        · update_global_config() 里的 self.xxx = self.config.get(...)
#   ⑤ 生效方式声明 —— config_apply.py
#        · 只在启动初始化阶段被读取的字段（监听注册 / 定时任务注册）加进
#          RESTART_REASONS，否则面板会误报「已生效」
#        · 接口类字段（需要重建默认 API 客户端）加进 API_REBUILD_REASONS
#
#   可选 ⑥ 面板状态展示 —— wxbot_core.py → get_status()
#
# 缺任何一处都不会报错，只会表现为「面板能改、保存也成功，但重启后被打回默认值」
# 或「改了不生效 / 面板误报已生效」。
# 老配置缺键的兜底由 config_defaults.apply_defaults 统一处理，
# 本文件的 dashboard() 与前端都不需要再补 setdefault。
# ============================================================

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import json
import os
import sys
import shutil
import base64
import tempfile
import hashlib
import certifi
import re
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta
import logging
from functools import wraps
import threading
from wxbot_core import CozeAPI, DifyAPI, DusAPI, OpenAIAPI, WXBot, clean_ai_reply_text, version as BOT_VERSION
from wxbot_core import OPENAI_SDK_ALIASES, OPENAI_SDK_NAME, _write_json_atomic
from config_store import ConfigStore, ConfigError, ConfigConflictError, ConfigReadError
import config_defaults
# 「配置什么时候生效」的唯一约定（立即生效 / 需重建接口客户端 / 必须重启）
import config_apply
# 机器人启停的唯一入口：实例/线程/状态/停止 Event 都在这里，本文件不再自己维护
from bot_lifecycle import BotLifecycle
# 记忆目录归属规则只有一份：memory_store.py（wxbot_core 也导入同一份）。
# 面板不要自己再写一套"剔除非法字符"的规则，否则两边会算出不同目录名。
from memory_store import (
    get_memory_manager,
    is_internal_dir_name,
    read_original_name,
)
from logger import log
import logger
import pythoncom
import webbrowser
import time
import socket
import email_send
import webhook_send
import ctypes
import atexit
import importlib.util
import secrets
from collections import defaultdict, deque
from urllib.parse import urljoin, urlparse

# ============================================================
# 路径与运行时工具
# ============================================================


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


def _is_path_within(base_dir, path):
    """判断 path 是否严格位于 base_dir 内部（Windows 下大小写不敏感）。

    两侧都过 realpath 再比较：'..'、'.'、绝对路径、UNC 路径、软链接/junction
    都会先被归一化，因此拼进来的路径段没法借这些形式跳出 base_dir。
    注意是「严格」内部——等于 base_dir 本身也判 False。
    """
    base = os.path.normcase(os.path.realpath(base_dir))
    target = os.path.normcase(os.path.realpath(path))
    return target.startswith(base + os.sep)


def _resolve_path_within(base_dir, name):
    """把 name 拼到 base_dir 下，并校验结果严格落在 base_dir 内。

    删除、重命名这类不可逆操作必须先过这一关：wx_id / chat_name / Prompt 名都
    直接来自 URL 路径段或请求体，拼出来就是 shutil.rmtree / os.remove 的目标。
    传 '..'（或 Windows 下的 '..%5C..'）原本能指到 base_dir 的上一级，
    从而删掉项目目录。

    :return: 通过 → (target, None)；拒绝 → (None, 拒绝原因)
    """
    target = os.path.realpath(os.path.join(base_dir, name))
    if not _is_path_within(base_dir, target):
        return None, '目标路径不在允许的目录内，已拒绝'
    return target, None


# ============================================================
# Flask 应用与全局配置常量
# ============================================================

# 初始化 Flask 应用
app = Flask(__name__, template_folder=resource_path('templates'), static_folder=resource_path('templates/static'))
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_proto=1, x_prefix=1)

# 安全配置
app.config.update(
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=False,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(days=1)
)

# 配置参数
CONFIG_FILE = os.path.join(base_dir(), 'config', 'config.json')
ADMIN_FILE  = os.path.join(base_dir(), 'config', 'admin.json')
EMAIL_FILE  = os.path.join(base_dir(), 'config', 'email.txt')
WEBHOOK_FILE = os.path.join(base_dir(), 'config', 'webhook.json')
PROMPT_DIR  = os.path.join(base_dir(), 'config', 'prompt')
BACKUP_BASE = os.path.join(base_dir(), 'old_wxbot_config')
APP_SECRET_FILE = os.path.join(base_dir(), 'config', 'panel_secret.key')
SIVER_PANEL_BASE_URL = 'https://panel.siver.top'
SIVER_PANEL_WS_URL = 'wss://panel.siver.top/relay/ws'
LEGACY_SIVER_PANEL_BASE_URL = 'https://wxbot-panel.siverking.online'
LEGACY_SIVER_PANEL_WS_URL = 'wss://wxbot-panel.siverking.online/relay/ws'
DEFAULT_PROMPT_CONTENT = "你是一个ai回复助手，请根据用户的问题给出回答,回复尽量保持在30字以内"

# 启动时确保目录存在
os.makedirs(os.path.join(base_dir(), 'config'),      exist_ok=True)
os.makedirs(os.path.join(base_dir(), 'panel_logs'),  exist_ok=True)

# ============================================================
# 启动期初始化（持久 CA 证书包 / 面板会话密钥）
# ============================================================


def install_persistent_ca_bundle():
    """onefile 打包时 certifi 的 cacert.pem 位于 %TEMP%\\_MEIxxxx\\ 临时目录，
    挂机电脑的临时文件清理（存储感知/管家类软件）会将其删除，
    导致 API 请求报证书错误、重启后恢复。
    启动时将其复制到 config/ 目录并让所有 HTTP 库改用它。"""
    try:
        persistent = os.path.join(base_dir(), 'config', 'cacert.pem')
        src = certifi.where()
        if src and os.path.exists(src):
            tmp = persistent + '.tmp'
            shutil.copyfile(src, tmp)
            os.replace(tmp, persistent)
        if os.path.exists(persistent):
            os.environ['REQUESTS_CA_BUNDLE'] = persistent   # requests 每次请求时读取
            os.environ['CURL_CA_BUNDLE'] = persistent       # 双保险
            os.environ['SSL_CERT_FILE'] = persistent        # httpx(openai/cozepy) trust_env 读取
            certifi.where = lambda: persistent              # httpcore 默认证书上下文读取
            log(level='SUCCESS', message=f'持久CA证书包已安装: {persistent}')
            return True
    except Exception as e:
        log(level='WARNING', message=f'安装持久CA证书包失败: {e}')
    return False


install_persistent_ca_bundle()


def load_panel_secret_key():
    """读取或生成持久化 Flask 会话密钥。"""
    if os.path.exists(APP_SECRET_FILE):
        try:
            with open(APP_SECRET_FILE, 'r', encoding='utf-8') as f:
                secret = f.read().strip()
            if secret:
                return secret
        except Exception as e:
            log('WARNING', f'读取面板会话密钥失败，将重新生成: {e}')

    secret = secrets.token_urlsafe(64)
    try:
        with open(APP_SECRET_FILE, 'w', encoding='utf-8') as f:
            f.write(secret)
    except Exception as e:
        log('ERROR', f'写入面板会话密钥失败，当前会话将使用临时密钥: {e}')
    return secret


app.secret_key = load_panel_secret_key()

# ============================================================
# 后台账密：密码哈希、模块动态加载与账密文件读写
# ============================================================


def hash_password(password):
    """生成后台密码的 PBKDF2-SHA256 哈希（写入 admin.json 用，不存明文）。"""
    return generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)


def verify_password(password, password_hash):
    """校验明文密码与存储哈希是否匹配。

    故意吞掉异常并返回 False：旧版本/损坏的哈希格式不应导致登录接口 500。
    """
    try:
        return check_password_hash(password_hash, password)
    except Exception:
        return False


# --- SiverPanel 客户端模块动态加载（可选组件：缺失或加载失败只降级，不阻断面板启动）---


def load_siver_panel_manager_class():
    """从 siver_panel.py 动态加载 SiverPanelManager 类；模块缺失或加载失败返回 None。"""
    module_path = resource_path('siver_panel.py')
    if not os.path.exists(module_path):
        log('WARNING', f'SiverPanel 客户端模块不存在: {module_path}')
        return None

    try:
        spec = importlib.util.spec_from_file_location('siver_panel_runtime', module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError('无法创建 SiverPanel 模块加载器')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        manager_class = getattr(module, 'SiverPanelManager', None)
        if manager_class is None:
            raise RuntimeError('SiverPanelManager 未在模块中定义')
        return manager_class
    except Exception as e:
        log('ERROR', f'加载 SiverPanel 客户端模块失败: {e}')
        return None

# --- 账密文件读取（含旧版明文密码自动迁移为哈希存储）---


def load_admin_credentials():
    """从 admin.json 读取后台账密；文件缺失时创建默认账密，读取失败时回退默认值。

    兼容旧版明文密码：若存在 password 字段且无 password_hash，自动迁移为哈希并写回文件。
    """
    default_password = "123456"
    default = {"username": "admin", "password_hash": hash_password(default_password)}
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
        username = data.get("username", default["username"])
        password_hash = str(data.get("password_hash", "")).strip()
        plain_password = str(data.get("password", "")).strip()

        if plain_password and not password_hash:
            password_hash = hash_password(plain_password)
            with open(ADMIN_FILE, 'w', encoding='utf-8') as fw:
                json.dump({"username": username, "password_hash": password_hash}, fw, ensure_ascii=False, indent=4)
            log('WARNING', '检测到旧版明文密码配置，已自动迁移为哈希存储')

        if not password_hash:
            password_hash = default["password_hash"]

        return {
            "username": username,
            "password_hash": password_hash,
        }
    except Exception as e:
        log('ERROR', f'读取账密文件失败: {e}，使用默认账密')
        return default

# 用户认证信息（从 admin.json 加载）
USERS = load_admin_credentials()

# ============================================================
# 登录失败限制与请求上下文
# ============================================================

LOGIN_FAIL_LIMIT = 8
LOGIN_FAIL_WINDOW_SEC = 15 * 60
LOGIN_BAN_SEC = 30 * 60
login_failures = defaultdict(deque)
login_bans = {}
panel_server_port = None
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "123456"
FORCE_ADMIN_CHANGE_ALLOWED_PATHS = {
    "/dashboard",
    "/logout",
    "/api/check_auth",
    "/get_admin_config",
    "/save_admin_config",
}


def get_client_ip():
    """取客户端真实 IP：优先 X-Forwarded-For 首段，其次 X-Real-IP，最后 remote_addr。

    面板支持反向代理（SiverPanel 远程访问），直连时 remote_addr 才是真实来源。
    """
    forwarded_for = request.headers.get('X-Forwarded-For', '')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    real_ip = request.headers.get('X-Real-IP', '').strip()
    if real_ip:
        return real_ip
    return request.remote_addr or 'unknown'


def is_remote_panel_request():
    """判断当前请求是否来自 SiverPanel 反向代理（而非本机直连）。

    依据：代理注入的 X-Siver-Remote 标记，或 X-Forwarded-Prefix 以 /panel/ 开头。
    """
    if request.headers.get('X-Siver-Remote', '').strip() == '1':
        return True
    forwarded_prefix = request.headers.get('X-Forwarded-Prefix', '').strip()
    return forwarded_prefix.startswith('/panel/')


def is_default_admin_credentials():
    """当前后台账号是否仍是默认的 admin / 123456（远程访问时的强制改密依据）。"""
    return (
        USERS.get("username") == DEFAULT_ADMIN_USERNAME
        and verify_password(DEFAULT_ADMIN_PASSWORD, USERS.get("password_hash", ""))
    )


def is_force_admin_change_required():
    """是否需要强制改密：仅「远程访问 + 已登录 + 仍用默认账密」三个条件同时成立才为真。

    本机直连不触发，避免用户在自己电脑上被反复拦截。
    """
    if not session.get('logged_in'):
        return False
    if not is_remote_panel_request():
        return False
    return is_default_admin_credentials()


def get_remote_connect_block_reason(*, manual: bool) -> tuple[str, str] | None:
    """远程访问连接前置校验：仍用默认账密时返回 (错误码, 提示语)，否则返回 None。

    作为 connect_guard 传给 SiverPanelManager，由 siver_panel 在每次连接前调用。
    """
    if not is_default_admin_credentials():
        return None
    message = '当前后台仍在使用默认账号密码 admin / 123456。为安全起见，请先在“账号密码”里修改后台账号密码后，再连接远程访问服务。'
    log('WARNING', message)
    return ('default_admin_credentials_block_remote_connect', message)


def is_remote_connect_block_required():
    """面板进入前台时是否需要弹「先改默认密码」提示（远程访问已开启 + 仍用默认账密）。"""
    config = read_config() or {}
    return bool(config.get('siver_panel_enabled') and is_default_admin_credentials())


def is_login_ip_banned(ip):
    """查询 IP 是否处于登录封禁期，返回 (是否封禁, 剩余秒数)；过期自动解封。"""
    expire_ts = login_bans.get(ip)
    if not expire_ts:
        return False, 0
    now = time.time()
    if expire_ts <= now:
        login_bans.pop(ip, None)
        return False, 0
    return True, int(expire_ts - now)


def record_login_failure(ip):
    """记录一次登录失败；滑动窗口内累计达到 LOGIN_FAIL_LIMIT 次则封禁该 IP。

    窗口外的历史失败会先被丢弃，因此偶发输错不会累积成封禁。
    返回 True 表示本次触发了封禁。
    """
    now = time.time()
    bucket = login_failures[ip]
    while bucket and now - bucket[0] > LOGIN_FAIL_WINDOW_SEC:
        bucket.popleft()
    bucket.append(now)
    if len(bucket) >= LOGIN_FAIL_LIMIT:
        login_bans[ip] = now + LOGIN_BAN_SEC
        bucket.clear()
        return True
    return False


def clear_login_failures(ip):
    """登录成功后清空该 IP 的失败记录与封禁状态。"""
    login_failures.pop(ip, None)
    login_bans.pop(ip, None)


def is_safe_redirect_target(target):
    """校验跳转目标是否安全（防开放重定向）：必须与本站同源且为 http/https。"""
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

# ============================================================
# 重定向与响应安全头
# ============================================================


def absolute_url_for(endpoint, **values):
    """生成带完整域名的 URL（反向代理下的重定向用，路径前缀由 ProxyFix 处理）。"""
    return url_for(endpoint, _external=True, **values)


@app.after_request
def apply_panel_security_headers(response):
    """所有响应统一补安全头；并给反向代理场景下漏标的会话 Cookie 补 Secure。

    背景：经 SiverPanel 代理时 Flask 认为不是 https，Secure 只能在这里按 request.is_secure 补。
    """
    session_cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
    cookies = response.headers.getlist('Set-Cookie')
    if request.is_secure and cookies:
        rewritten = []
        changed = False
        for cookie in cookies:
            if cookie.startswith(f'{session_cookie_name}=') and 'Secure' not in cookie:
                cookie = f'{cookie}; Secure'
                changed = True
            rewritten.append(cookie)
        if changed:
            del response.headers['Set-Cookie']
            for cookie in rewritten:
                response.headers.add('Set-Cookie', cookie)
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    return response


def get_panel_server_port():
    """供 SiverPanel 客户端回查本地面板端口（端口在 main() 里动态分配）。"""
    return panel_server_port

# ============================================================
# SiverPanel 客户端实例化（可选组件，初始化失败只记日志、不阻断面板）
# ============================================================

SIVER_PANEL_MANAGER_CLASS = load_siver_panel_manager_class()
siver_panel_manager = None
if SIVER_PANEL_MANAGER_CLASS is not None:
    try:
        siver_panel_manager = SIVER_PANEL_MANAGER_CLASS(
            config_path=CONFIG_FILE,
            client_version=BOT_VERSION,
            log_func=log,
        )
        siver_panel_manager.set_connect_guard(get_remote_connect_block_reason)
    except Exception as e:
        log('ERROR', f'初始化 SiverPanel 客户端失败: {e}')

if siver_panel_manager is not None:
    atexit.register(siver_panel_manager.shutdown)

# ============================================================
# 登录装饰器
# ============================================================


def login_required(f):
    """登录校验装饰器。

    未登录：API/JSON 请求返回 401 JSON，页面请求 302 跳登录页（带 next 回跳）。
    已登录但命中「远程访问 + 仍用默认账密」：只放行 FORCE_ADMIN_CHANGE_ALLOWED_PATHS，
    其余请求一律拦截，防止远程访问时用默认密码长期使用面板。
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith('/api/') or request.accept_mimetypes.accept_json:
                return jsonify({'status': 'error', 'message': '未登录'}), 401
            return redirect(absolute_url_for('login', next=request.url))
        if is_force_admin_change_required() and request.path not in FORCE_ADMIN_CHANGE_ALLOWED_PATHS:
            message = '当前为远程访问，且仍在使用默认账号密码，请先修改后台账号密码后再继续使用'
            wants_json = (
                request.path.startswith('/api/')
                or request.accept_mimetypes.accept_json
                or request.headers.get('X-Requested-With', '') == 'XMLHttpRequest'
            )
            if wants_json:
                return jsonify({
                    'status': 'error',
                    'message': message,
                    'error_code': 'force_admin_credential_change_required',
                }), 403
            return redirect(absolute_url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


# ============================================================
# Prompt 文件管理辅助函数
# ============================================================


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


def _prompt_reference_sources(name):
    """列出配置里仍引用 Prompt 名 name 的位置，用于重命名后的提示。

    只读不改：面板与运行中的机器人各持一份配置快照（见 _push_config_to_running_bot），
    由保存路由之外的代码代改 config.json 会引入新的同步问题。因此重命名时把引用
    摆到明面上，由用户决定改配置还是改回名字。

    :return: 引用位置描述列表，没有引用时返回空列表
    """
    sources = []
    config = read_config() or {}
    if str(config.get('default_prompt', '默认')) == name:
        sources.append('default_prompt（默认 AI 设定）')
    for key, label in (('chat_prompt_map', '用户专属 Prompt'),
                       ('group_prompt_map', '群聊专属 Prompt')):
        mapping = config.get(key)
        if isinstance(mapping, dict):
            for target, prompt_name in mapping.items():
                if str(prompt_name) == name:
                    sources.append(f'{label}（{target}）')
    return sources


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

# ============================================================
# 数据备份辅助函数
# ============================================================


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

# ============================================================
# 配置读取与定时字段校验
# ============================================================


def read_config():
    """读取 config.json；失败时返回 None。

    注意：故意不抛异常，历史调用点已统一按 `read_config() or {}` 兜底。
    """
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log('ERROR', f'读取配置文件失败: {str(e)}')
        return None


def _parse_hhmm_config(value, field_name):
    """解析 `HH:MM` 格式的时间字段，非法时返回错误信息而不是抛异常。"""
    value = str(value or '').strip()
    if not value:
        return None, f'{field_name} 为空'
    try:
        parsed = datetime.strptime(value, "%H:%M")
        return (parsed.hour, parsed.minute), None
    except ValueError:
        return None, f'{field_name} 格式无效: {value}，应为 HH:MM'

# ============================================================
# 登录页与登出路由
# ============================================================


@app.route('/api/check_auth')
def check_auth():
    return jsonify({'authenticated': session.get('logged_in', False)})


@app.route('/', methods=['GET', 'POST'])
def login():
    """登录页：GET 渲染表单，POST 校验账密并建立会话。

    同一 IP 在 LOGIN_FAIL_WINDOW_SEC 内失败 LOGIN_FAIL_LIMIT 次即封禁 LOGIN_BAN_SEC。
    """
    if session.get('logged_in'):
        return redirect(absolute_url_for('dashboard'))
    logout_success = request.args.get('logout') == 'success'
    error = None

    if request.method == 'POST':
        client_ip = get_client_ip()
        blocked, remaining = is_login_ip_banned(client_ip)
        if blocked:
            log('WARNING', f'登录被拒绝：IP {client_ip} 仍处于封禁期，剩余 {remaining}s')
            return render_template('login.html', error=f'登录失败次数过多，请 {remaining} 秒后再试', logout_success=logout_success, bot_version=BOT_VERSION)

        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        if username == USERS['username'] and verify_password(password, USERS['password_hash']):
            clear_login_failures(client_ip)
            session['logged_in'] = True
            session['username'] = username
            session.permanent = True
            log('SUCCESS', f'用户 {username} 登录成功')
            next_page = request.args.get('next') or absolute_url_for('dashboard')
            if not is_safe_redirect_target(next_page):
                next_page = absolute_url_for('dashboard')
            return redirect(next_page)
        else:
            record_login_failure(client_ip)
            log('WARNING', f'登录失败: 用户名或密码错误 (用户名: {username})')
            return render_template('login.html', error='用户名或密码错误', bot_version=BOT_VERSION)

    return render_template('login.html', error=error, logout_success=logout_success, bot_version=BOT_VERSION)


@app.route('/logout')
def logout():
    session.clear()
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(absolute_url_for('login'))

# ============================================================
# 仪表盘路由：旧配置迁移 + 新增字段兜底
# ============================================================


@app.route('/dashboard')
@login_required
def dashboard():
    """渲染配置面板。

    流程：
      ① 读盘（拿到配置 + 版本号）
      ② 旧 prompt 字段迁到 config/prompt/默认.md
      ③ 统一的「迁移 -> 补默认值 -> 规范化」流水线（config_defaults.prepare，幂等）
      ④ 内容真的变了才写回一次（原来打开一次页面最多写盘 4 次）
      ⑤ 注入模板变量（config / prompts / 版本号 / 强制改密与远程访问标记）

    ⚠ 新增配置字段只需改 config_defaults.py：默认值加进 DEFAULT_CONFIG，
      类型归属加进对应的 coerce 名单。这里不用再补 setdefault。
    """
    try:
        config, config_rev = CONFIG_STORE.read()
    except ConfigReadError:
        return render_template('error.html', message='无法读取配置文件')

    _before = dict(config)

    # 旧 prompt 字段 -> config/prompt/默认.md（涉及文件写入，单独一步）
    _migrate_prompt_from_config(config)

    # 统一的「迁移 -> 补默认值 -> 规范化」流水线（幂等，定义在 config_defaults.py）
    config = config_defaults.prepare(config)

    # 只有内容真的变了才写回，避免"打开一次页面写盘多次"
    if config != _before:
        try:
            config, config_rev = CONFIG_STORE.write(config)
            log('SUCCESS', '配置已按当前格式规范化并写回')
        except ConfigError as e:
            log('ERROR', f'配置规范化写回失败: {e}')

    _ensure_prompt_dir()
    prompts = _get_prompts_list()

    force_admin_change_required = is_force_admin_change_required()
    return render_template(
        'dashboard.html',
        config=config,
        logs=logger.get_recent_logs(limit=50),
        prompts=prompts,
        force_admin_change_required=force_admin_change_required,
        remote_connect_block_required=is_remote_connect_block_required(),
        bot_version=BOT_VERSION,
        config_rev=config_rev,
    )

# ============================================================
# 面板日志接口
# ============================================================


@app.route('/get_logs')
@login_required
def get_logs():
    after_id_raw = str(request.args.get('after_id', '') or '').strip()
    after_id = None
    if after_id_raw:
        try:
            after_id = max(0, int(after_id_raw))
        except ValueError:
            after_id = None
    return jsonify(logger.get_logs_after(after_id, limit=50))
# 字段类型校验（6 个 coerce）、默认值与迁移统一放在 config_defaults.py。
# 新增配置字段时：默认值加进 DEFAULT_CONFIG，类型归属加进对应的 coerce 名单。

# ============================================================
# 配置保存管线
# ============================================================


def _normalize_config(config):
    """保存前的统一规范化：委托给 config_defaults.normalize（单一来源）。"""
    return config_defaults.normalize(config)


# config.json 的唯一读写入口。
# 「读 → 改 → 校验 → 写」由 ConfigStore 在一次路径锁内完成，
# 因此面板、机器人、siver_panel 三方不会互相覆盖。
CONFIG_STORE = ConfigStore(CONFIG_FILE, normalize=_normalize_config)


def save_config(config_data, expected_rev=None):
    """把配置写入 config.json。

    入参是**要改的字段**，不是完整快照：ConfigStore 在路径锁内完成
    「读盘 → 浅合并 → 规范化 → 原子写」，所以两个调用方先后保存不会互相覆盖；
    未在入参里出现的键（含未知字段）保留磁盘上的现值。

    :param expected_rev: 页面加载时拿到的版本号。与磁盘现值不一致时拒绝写入，
                         避免"旧页面保存把别处的改动静默覆盖"。
                         传 None 表示不做校验。
    :return: (是否成功, 版本号, 错误标记)
             成功      -> (True,  新版本号, None)
             版本冲突  -> (False, 磁盘现值, 'conflict')
             其它失败  -> (False, None,    错误文本)
    """
    patch = dict(config_data)
    patch.pop('_rev', None)   # _rev 是控制字段，不落盘
    try:
        _merged, rev = CONFIG_STORE.update(patch, expected_rev=expected_rev)
        log('SUCCESS', '配置文件保存成功')
        return True, rev, None
    except ConfigConflictError as e:
        log('WARNING', f'保存被拒绝（版本冲突）: {e}')
        return False, e.actual, 'conflict'
    except ConfigError as e:
        log('ERROR', f'保存配置文件失败: {e}')
        return False, None, str(e)

#   保存配置
update_config_status = False # 记录是否更新了定时启停状态


@app.route('/save_config', methods=['POST'])
@login_required
def save_config_route():
    """面板「保存配置」接口。

    返回的状态（前端据此给不同提示）：
      · status=error/conflict  -> 未保存
      · status=success + apply_state=applied       -> 已保存且全部改动已生效
      · status=success + apply_state=partial       -> 部分立即生效，其余需重启
      · status=success + apply_state=needs_restart -> 改动只在重启后生效
      · status=success + apply_state=not_running   -> 机器人未运行，下次启动生效
      · status=success + apply_state=failed        -> 已保存但推送失败

    另附 needs_restart / restart_fields / restart_hint：本次改动里"必须重启"的部分
    （监听注册、定时任务注册只在启动时做）。分类见 config_apply.py ——
    面板、机器人与验收脚本共用同一份，不在这里再维护第二份字段列表。

    ⚠ 保存成功后必须置 update_config_status = True，定时启停线程靠这个标志
      在下一轮循环里重新加载启停时间（见 time_start_stop）。漏掉则改时间不生效。
    """
    try:
        config_data = request.get_json()
        if not config_data:
            return jsonify({'status': 'error', 'message': '无效的配置数据'}), 400

        # _rev 是前端回传的配置版本号（控制字段，不写入配置）
        expected_rev = config_data.pop('_rev', None)

        # 保存前的快照：用于判断"改动的字段是否**真的变了**"。
        # 面板提交的是整张表单，listen_list / group / scheduled_msg_list 这些键
        # 每次都在（哪怕只改了回复延迟），所以不能只看"提交内容里有没有它们"。
        before, _ = CONFIG_STORE.read_or_empty()

        # 读盘/合并/规范化/版本校验统一由 CONFIG_STORE 在锁内完成，
        # 这里不再重复读一次盘、合并一次、coerce 一遍
        ok, rev, err = save_config(config_data, expected_rev=expected_rev)

        if not ok and err == 'conflict':
            # 409：让前端区分"版本冲突"和"普通保存失败"，并保留用户正在编辑的内容
            return jsonify({
                'status': 'conflict',
                'message': '配置已被其他改动更新，本次保存未生效',
                'rev': rev,
            }), 409
        if not ok:
            return jsonify({'status': 'error', 'message': err or '配置保存失败'}), 500

        global update_config_status
        update_config_status = True # 执行了保存配置

        after, _ = CONFIG_STORE.read_or_empty()
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}

        # 区分"已保存"与"已应用"：推送失败不影响保存结果，但要让界面知道
        apply_result = _push_config_to_running_bot(changed)

        # 需重启的提示只在"机器人正在运行且确实有重启类改动"时给：
        # 未运行时下次启动自然就加载了新配置，提示重启反而误导。
        restart_fields = apply_result['restart_fields']
        needs_restart = bool(restart_fields) and apply_result['apply_state'] != 'not_running'

        return jsonify({
            'status': 'success',
            'message': '配置保存成功',
            'rev': rev,
            'apply_state': apply_result['apply_state'],
            'apply_message': apply_result['apply_message'],
            'applied_fields': apply_result['applied_fields'],
            'api_rebuilt': apply_result['api_rebuilt'],
            'needs_restart': needs_restart,          # 需点"重启载入新配置"才生效
            'restart_fields': restart_fields,
            'restart_hint': apply_result['restart_hint'],
        })
    except Exception as e:
        log('ERROR', f'保存配置出错: {str(e)}')
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============================================================
# 接口连通性测试（模型配置页的「测试」按钮）
# ============================================================


class _TempAPIConfig:
    """用于测试单个接口配置的轻量配置对象，不读写 config.json。"""

    def __init__(self, cfg):
        self.api_sdk = str(cfg.get('sdk', '')).strip()
        self.api_key = str(cfg.get('key', '')).strip()
        self.base_url = str(cfg.get('url', '')).strip().rstrip('/')
        self.model1 = str(cfg.get('model', '')).strip()
        self.prompt = "你是接口连通性测试助手。请只回复 OK。"


def _build_test_api_client(tmp_config):
    sdk = tmp_config.api_sdk
    if sdk in OPENAI_SDK_ALIASES:
        return OpenAIAPI(tmp_config)
    if sdk == "Dify":
        return DifyAPI(tmp_config)
    if sdk == "Coze":
        return CozeAPI(tmp_config)
    if sdk == "DusAPI":
        return DusAPI(tmp_config)
    raise ValueError("不支持的 SDK 类型")


_TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _run_api_image_test(api, sdk):
    """用内置极小 PNG 测试当前接口是否支持图片输入。"""
    if sdk not in ("OpenAI SDK", "DusAPI"):
        return {
            'status': 'skipped',
            'message': '当前接口类型暂不支持通用图片测试'
        }
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as f:
            f.write(base64.b64decode(_TINY_PNG_BASE64))
            tmp_path = f.name
        reply = api.chat(
            "请只回复 OK",
            stream=False,
            prompt="你是图片识别连通性测试助手。请确认你能读取图片，并只回复 OK。",
            history=[],
            image_path=tmp_path,
        )
        raw_reply = str(reply or "")
        cleaned_reply = clean_ai_reply_text(raw_reply)
        if not raw_reply or raw_reply == "API返回错误，请稍后再试":
            return {
                'status': 'error',
                'message': '图片测试未返回有效文本，请确认模型支持视觉输入'
            }
        return {
            'status': 'success',
            'reply': cleaned_reply or '（清洗后为空）',
            'raw_length': len(raw_reply),
            'cleaned': cleaned_reply != raw_reply,
        }
    except TypeError as e:
        return {
            'status': 'skipped',
            'message': f'当前接口类暂不支持图片参数：{e}'
        }
    except Exception as e:
        msg = str(e)
        if len(msg) > 500:
            msg = msg[:500] + '...'
        return {
            'status': 'error',
            'message': f'图片测试失败：{msg}'
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@app.route('/test_api_config', methods=['POST'])
@login_required
def test_api_config_route():
    started = time.time()
    try:
        data = request.get_json() or {}
        cfg = data.get('api_config') or {}
        if not isinstance(cfg, dict):
            return jsonify({'status': 'error', 'message': '接口配置格式无效'})

        tmp_config = _TempAPIConfig(cfg)
        if tmp_config.api_sdk not in ("DusAPI", "Dify", "Coze") and tmp_config.api_sdk not in OPENAI_SDK_ALIASES:
            return jsonify({'status': 'error', 'message': '请选择有效的 SDK'})
        if not tmp_config.api_key:
            return jsonify({'status': 'error', 'message': 'API Key 不能为空'})
        if not tmp_config.base_url:
            return jsonify({'status': 'error', 'message': 'Base URL 不能为空'})
        if not tmp_config.model1:
            return jsonify({'status': 'error', 'message': '模型名称不能为空'})

        api = _build_test_api_client(tmp_config)
        reply = api.chat("请只回复 OK", stream=False, prompt=tmp_config.prompt, history=[])
        raw_reply = str(reply or "")
        cleaned_reply = clean_ai_reply_text(raw_reply)
        cleaned = cleaned_reply != raw_reply

        if not raw_reply or raw_reply == "API返回错误，请稍后再试":
            return jsonify({
                'status': 'error',
                'message': '接口有响应，但未返回有效文本，请检查模型名称、接口地址或服务商兼容性'
            })

        elapsed_ms = int((time.time() - started) * 1000)
        return jsonify({
            'status': 'success',
            'data': {
                'reply': cleaned_reply or '（清洗后为空：接口可能只返回了思考内容）',
                'raw_length': len(raw_reply),
                'cleaned': cleaned,
                'elapsed_ms': elapsed_ms,
            }
        })
    except Exception as e:
        msg = str(e)
        if len(msg) > 800:
            msg = msg[:800] + '...'
        return jsonify({'status': 'error', 'message': f'接口测试失败：{msg}'})

# ============================================================
# Prompt 文件管理路由
# ============================================================


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
        # 重命名只改名字：旧名称同样来自请求体，先做目录内校验（越界直接拒绝，
        # 不做任何删除）。真正的删除挪到「新文件确认写成功」之后，见下面的步骤 2/3。
        old_path = None
        if old_name and old_name != name:
            old_path, old_err = _resolve_path_within(PROMPT_DIR, f'{old_name}.md')
            if old_err:
                log('WARNING', f'拒绝重命名 Prompt：旧名称越界 old_name={old_name!r}')
                return jsonify({'status': 'error', 'msg': '旧 Prompt 名称非法，已拒绝'})

        # 步骤 1/3：确定新文件路径（name 已过白名单，此处只做兜底校验）
        target, path_err = _resolve_path_within(PROMPT_DIR, f'{name}.md')
        if path_err:
            log('WARNING', f'拒绝保存 Prompt：名称越界 name={name!r}')
            return jsonify({'status': 'error', 'msg': 'Prompt 名称非法，已拒绝'})

        # 新旧两个名字是否指向同一个文件（Windows 大小写不敏感：'abc' 改 'ABC' 就是
        # 同一个文件，此时绝不能把旧名字当"旧文件"删掉，否则删的是刚写好的新内容）
        same_file = False
        if old_path is not None:
            try:
                same_file = os.path.samefile(old_path, target)
            except OSError:
                same_file = (os.path.normcase(os.path.realpath(old_path))
                             == os.path.normcase(os.path.realpath(target)))

        # 重名规则：目标名已存在且不是旧名字时按「覆盖保存」处理（与直接保存同名
        # Prompt 行为一致）。因为覆盖发生在旧文件删除之前，覆盖对象不会是被删的旧文件。
        overwrote = os.path.exists(target) and not same_file

        # 步骤 2/3：先把新内容原子写入新名字（临时文件 + os.replace）。
        # 这一步失败就直接抛错返回，旧 Prompt 一个字都没动——不会出现
        # 「新文件没写成、旧 Prompt 已经删掉」的空档。
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

        # 步骤 3/3：新文件已落盘，才删除旧名字文件
        warnings = []
        if old_path is not None and not same_file and os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError as e:
                # 新文件已经就位，此时不再回滚（回滚要再动一次已写好的新文件，风险更大）；
                # 结果是新旧两个 .md 并存，记 WARNING 提示手工删除。
                warnings.append(f'新 Prompt 已保存为 {name}.md，但旧文件 {old_name}.md 删除失败：{e}')
                log('WARNING', warnings[-1])

        # 配置引用规则：重命名不改写 config.json（面板与运行中的机器人各持一份配置快照，
        # 代改会引入新的同步问题），只把「仍有引用指向旧名称」摆到明面上：
        # default_prompt / chat_prompt_map / group_prompt_map 引用旧名称时记 WARNING，
        # 并在响应里回给前端，提醒改配置，避免运行期静默回退到默认 Prompt 或空内容。
        if old_path is not None:
            refs = _prompt_reference_sources(old_name)
            if refs:
                warnings.append(f'配置里仍引用旧名称「{old_name}」：{"、".join(refs)}；请改到「{name}」，否则运行时会回退默认 Prompt')
                log('WARNING', warnings[-1])

        if overwrote:
            log('INFO', f'Prompt 已覆盖同名文件：{name}.md')
        log('SUCCESS', f'Prompt 已保存：{name}.md')
        result = {'status': 'success'}
        if warnings:
            result['warnings'] = warnings
        return jsonify(result)
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
        # name 直接来自请求体，拼出来的删除目标必须在 PROMPT_DIR 内
        target, path_err = _resolve_path_within(PROMPT_DIR, f'{name}.md')
        if path_err:
            log('WARNING', f'拒绝删除 Prompt：名称越界 name={name!r}')
            return jsonify({'status': 'error', 'msg': 'Prompt 名称非法，已拒绝'})
        # 不允许删除最后一个
        md_files = [f for f in os.listdir(PROMPT_DIR) if f.endswith('.md')]
        if len(md_files) <= 1:
            return jsonify({'status': 'error', 'msg': '不允许删除最后一个 Prompt'})
        if os.path.exists(target):
            os.remove(target)
        log('SUCCESS', f'Prompt 已删除：{name}.md')
        return jsonify({'status': 'success'})
    except Exception as e:
        log('ERROR', f'删除 Prompt 失败: {e}')
        return jsonify({'status': 'error', 'msg': str(e)})

# 启动/停止机器人
# --- 机器人运行态：实例、线程、状态、停止信号统一由 BotLifecycle 持有 ---
#
# ⚠ 不要再在本文件里自己起机器人线程，也不要再维护 bot / bot_thread 两个全局变量。
#   手动启动（/start_bot）、定时启动（time_start_stop）、停止、重启**全部只调它**。
#   曾经"各管各的"留下的三个窗口：
#     a) 线程已活而实例还没赋值 → 停止入口直接调 bot.stop_wxbot() 撞 None；
#     b) 初始化期间的停止请求 → 初始化完成后又被 run_flag=True 抹掉；
#     c) 停止没等线程退完就清空引用 → 再启动时与旧线程重叠，两个机器人同时监听。
#   三者都在 bot_lifecycle 里统一解决（含"停止没完成不放行下一次启动"）。
BOT_LIFECYCLE = BotLifecycle('siver_wxbot')


def _bot_runner(handle):
    """机器人线程体：构造实例 → 登记 → 进主循环。

    只在 BotLifecycle 起的线程里执行。停止收尾不在这里做：主动停止由生命周期对象
    调用实例的 stop_wxbot()，正常/异常退出由 WXBot.main() 的 finally 统一收尾。
    """
    pythoncom.CoInitialize()
    try:
        # 防睡眠必须在本线程设置：SetThreadExecutionState 是线程作用域的，
        # 在调用方线程（Flask 请求线程 / 定时调度线程）设置、在机器人线程恢复是无效的。
        # 放在 WXBot() 之前——构造含授权校验与监听初始化，耗时数秒，期间同样可能息屏。
        _prevent_sleep()

        # 启动前兜底清理上一次运行留下的监听：正常情况下上一轮退出时已经清理干净
        # （WXBot.shutdown() 幂等），这里是防"线程异常死亡导致监听残留"。
        previous = BOT_LIFECYCLE.take_previous_bot()
        if previous is not None:
            try:
                previous.shutdown('启动前清理上一次运行的残留监听')
            except Exception as _e:
                log('WARNING', f'清理上一次运行的残留监听时出错（可忽略）: {_e}')

        # 把生命周期的停止信号交给机器人：初始化期间点停止时，它靠这个信号收尾，
        # 而不是把 run_flag 设 False 之后就无人过问。
        bot = WXBot(stop_event=handle.stop_event)
        handle.bind(bot)      # 登记之后，停止入口才可能拿到实例（此前只有停止信号）

        if handle.should_stop():
            # 初始化期间（授权校验 / 拉起微信 / 注册监听，数秒）收到的停止请求
            log('WARNING', '初始化期间收到停止请求，已放弃进入主循环并收尾')
            bot.stop_wxbot()
            return

        bot.run()
    finally:
        # 谁设置、谁恢复：防睡眠与 COM 都在本线程设置，也都在本线程释放
        _restore_sleep()
        pythoncom.CoUninitialize()


def _spawn_bot_thread(reason='手动启动'):
    """启动机器人线程；手动启动与定时启动共用这一份实现。

    只调 BOT_LIFECYCLE.start()：重复点击、上一次停止还没走完就抢跑，
    都会被生命周期对象挡住（不会出现两条线程同时监听）。

    :return: (是否已接受启动, 提示信息)
    """
    outcome = BOT_LIFECYCLE.start(_bot_runner, reason=reason)
    return outcome.started, outcome.message


@app.route('/start_bot', methods=['POST'])
@login_required
def start_bot():
    """启动机器人（在面板进程内起一个后台线程，不是子进程）。

    实际启动逻辑见 _spawn_bot_thread()：与定时启动共用同一份实现，
    由 BotLifecycle 保证"任何时刻最多一个实例、一条线程"。
    """
    log('INFO', '机器人启动请求已接收')
    started, message = _spawn_bot_thread('手动启动')
    state = BOT_LIFECYCLE.state
    if started:
        return jsonify({'status': 'success', 'message': message, 'state': state})
    if BOT_LIFECYCLE.is_running():
        # 已在运行：不算失败，但把真实状态回给前端
        return jsonify({'status': 'success', 'message': message, 'state': state,
                        'already_running': True})
    # 上一次停止还没走完：此时启动会与旧线程重叠，必须明确拒绝
    return jsonify({'status': 'error', 'message': message, 'state': state,
                    'code': 'not_stopped'}), 409


@app.route('/stop_bot', methods=['POST'])
@login_required
def stop_bot():
    """停止机器人：**等线程真的退出**才算成功。

    返回 status=success 表示已确认停止（state=stopped）；未确认时返回 409，
    并带上 code 说明原因：
      · code=timeout    —— 线程未在确认窗口内退出，可以继续轮询 /get_status；
      · code=superseded —— 停止期间另一次启动已经跑起来了（并发调用），
                           此时不该当成"还在停"，前端应提示"已被重新启动"。
    """
    log('INFO', '机器人停止请求已接收')
    outcome = BOT_LIFECYCLE.stop(reason='面板停止')
    if outcome.stopped:
        return jsonify({'status': 'success', 'message': outcome.message,
                        'state': outcome.state, 'code': outcome.code})
    return jsonify({
        'status': 'error',
        'message': outcome.message,
        'state': outcome.state,
        'code': outcome.code,
    }), 409


def _push_config_to_running_bot(changed_fields=None):
    """把磁盘上的新配置推给运行中的机器人实例，并如实回报生效范围。

    面板与机器人是同一个进程：面板保存只写盘，而 bot 内存里仍是启动时加载的
    旧快照。此后任意一条会写盘的微信命令（/群开关、/记忆开关…）都会把旧快照
    整体写回，导致面板的改动被静默回滚。

    ⚠ 生效约定见 config_apply.py：
      · 立即生效（hot）：同步属性；
      · 立即生效但需重建默认 API 客户端（api_configs / api_index）；
      · 必须重启（restart）：监听注册 / 定时任务注册只在启动时做 —— 只报"需重启"，
        绝不把"刷新了几个属性"当成"全部生效"。
      实例是否"在运行"只看 BOT_LIFECYCLE：启动中（实例已登记）也算运行中，
      停止中则不再推送（推了也会被丢弃）。

    :param changed_fields: 本次真正变化的配置键（面板有保存前/后的磁盘差异，最准）
    :return: dict(apply_state, apply_message, applied_fields, restart_fields,
                  restart_hint, api_rebuilt)
              apply_state ∈ {'applied', 'partial', 'needs_restart', 'not_running', 'failed'}
    """
    def _payload(state, message, applied=(), restart=(), hint='', api_rebuilt=False):
        return {
            'apply_state': state,
            'apply_message': message,
            'applied_fields': list(applied),
            'restart_fields': list(restart),
            'restart_hint': hint,
            'api_rebuilt': bool(api_rebuilt),
        }

    bot = BOT_LIFECYCLE.bot
    if bot is None or not BOT_LIFECYCLE.is_running():
        return _payload('not_running', '机器人当前未运行，配置将在下次启动时生效')
    try:
        result = bot.apply_config(changed_fields)
    except Exception as e:
        log('WARNING', f'推送新配置给运行中的机器人失败（配置已保存）: {e}')
        return _payload('failed', f'配置已保存，但推送给运行中的机器人失败：{e}')

    hot_labels = config_apply.describe_soft(result['hot_fields'])
    api_labels = config_apply.describe_soft(result['api_fields'])
    restart_labels = result['restart_labels']
    applied = list(result['hot_fields']) + list(result['api_fields'])
    restart = list(result['restart_fields'])
    applied_count = len(applied)

    # 立即生效部分的说法：接口类字段有中文名就点名，其余长尾按数量汇总
    if api_labels and hot_labels:
        applied_desc = f'{api_labels} 等 {applied_count} 项改动'
    elif api_labels:
        applied_desc = api_labels
    else:
        applied_desc = f'{applied_count} 项改动'

    if result['errors']:
        return _payload('failed',
                        '配置已保存，但应用时出错：' + '；'.join(result['errors']),
                        applied=applied, restart=restart, hint=restart_labels,
                        api_rebuilt=result['api_rebuilt'])

    if restart and applied:
        message = f'已保存：{applied_desc}已立即生效；{restart_labels} 需重启才生效'
        return _payload('partial', message, applied=applied, restart=restart,
                        hint=restart_labels, api_rebuilt=result['api_rebuilt'])
    if restart:
        message = f'已保存：本次改动（{restart_labels}）需点「重启载入新配置」才生效'
        return _payload('needs_restart', message, restart=restart, hint=restart_labels)
    if applied:
        if api_labels:
            message = f'运行中的机器人已应用新配置：{applied_desc}'
        else:
            message = f'运行中的机器人已应用新配置（{applied_desc}）'
        if result['api_rebuilt']:
            message += '，默认接口客户端已重建'
        return _payload('applied', message, applied=applied,
                        api_rebuilt=result['api_rebuilt'])
    return _payload('applied', '配置已保存（本次改动不影响运行中的机器人）')

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

# 这里原本有一句 atexit.register(_restore_sleep) 作为“进程退出兜底”，已移除：
# SetThreadExecutionState 是线程作用域的，atexit 回调运行在主线程上，而主线程从未
# 调用过 _prevent_sleep()；它再调 _restore_sleep() 只会清掉主线程自己的状态（本来就没有），
# 对机器人线程持有的 DISPLAY/SYSTEM 请求毫无作用 —— 留着会让人误以为存在进程级兜底。
# 现在是“谁设置、谁恢复”：机器人在 run_bot() 所属线程内设置，并在同一线程的 finally 恢复。

# ============================================================
# 机器人启停路由
# ============================================================
# /start_bot 与 /stop_bot 的实现已上移到本文件「启动/停止机器人」一节
# （紧挨着 BOT_LIFECYCLE 定义），两条路由都只是对生命周期对象的一次调用。
# 这里不再保留第二份实现 —— 同一件事有两处实现，正是过去启停行为不一致的根源。

# ============================================================
# 激活码与版本更新
# ============================================================


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
        import uuid

        # 获取本地版本
        local_version = getattr(wxbot_mod, 'version', '')

        # 获取机器码（使用 MAC 地址）
        machine_code = hex(uuid.getnode())[2:].upper()

        # 设置自定义 User-Agent: 机器码-版本号
        headers = {
            'User-Agent': f'{machine_code}-{local_version}'
        }

        # 请求版本信息
        r = req.get('https://wxbot.siverking.online/version.json', headers=headers, timeout=60)
        data = r.json()
        data['local_version'] = local_version
        data['machine_code'] = machine_code
        return jsonify({'status': 'success', 'data': data})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

# ============================================================
# 状态查询与 SiverPanel 远程访问接口
# ============================================================


@app.route('/get_status')
@login_required
def get_status():
    """返回机器人运行状态（含真实生命周期状态）。

    · ``bot_running``：是否"大概在跑"（启动中/运行中），状态面板沿用这个字段；
    · ``bot_state``：``stopped`` / ``starting`` / ``running`` / ``stopping``，
      重启流程靠它判断"是不是真的停住了"—— 不能再用固定秒数猜。
    机器人未运行时只回 bot_running=False + bot_state=stopped。
    """
    snap = BOT_LIFECYCLE.snapshot()
    bot = BOT_LIFECYCLE.bot
    data = {
        'bot_running': snap['bot_running'],
        'bot_state': snap['state'],
        'bot_state_label': snap['state_label'],
    }
    if snap['bot_running'] and bot is not None:
        try:
            data.update(bot.get_status())
        except Exception as e:
            data['error'] = str(e)
        # 生命周期状态是权威值，不被 bot 自己的快照覆盖
        data['bot_running'] = snap['bot_running']
        data['bot_state'] = snap['state']
        data['bot_state_label'] = snap['state_label']
    return jsonify({'status': 'success', 'data': data})


@app.route('/api/siver-panel/status')
@login_required
def get_siver_panel_status():
    if siver_panel_manager is None:
        return jsonify({'status': 'error', 'message': 'SiverPanel 客户端未初始化'})
    return jsonify({'status': 'success', 'data': siver_panel_manager.get_status()})


@app.route('/api/siver-panel/connect', methods=['POST'])
@login_required
def connect_siver_panel():
    if siver_panel_manager is None:
        return jsonify({'status': 'error', 'message': 'SiverPanel 客户端未初始化'})
    try:
        status = siver_panel_manager.connect(manual=True)
        if status.get('state') == 'error' and status.get('last_error_code') == 'default_admin_credentials_block_remote_connect':
            return jsonify({
                'status': 'error',
                'message': status.get('last_message') or '远程连接已被安全策略拦截',
                'error_code': status.get('last_error_code') or 'default_admin_credentials_block_remote_connect',
                'data': status,
            })
        return jsonify({'status': 'success', 'message': status.get('last_message') or '正在发起远程连接', 'data': status})
    except Exception as e:
        log('ERROR', f'SiverPanel 手动连接失败: {e}')
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/siver-panel/disconnect', methods=['POST'])
@login_required
def disconnect_siver_panel():
    if siver_panel_manager is None:
        return jsonify({'status': 'error', 'message': 'SiverPanel 客户端未初始化'})
    try:
        status = siver_panel_manager.disconnect(reason='manual_disconnect')
        return jsonify({'status': 'success', 'message': status.get('last_message') or '远程访问服务已断开', 'data': status})
    except Exception as e:
        log('ERROR', f'SiverPanel 断开连接失败: {e}')
        return jsonify({'status': 'error', 'message': str(e)})

# ============================================================
# 面板配置读取路由 / 后台账号 / 邮件告警 / Webhook 告警
# ============================================================


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
        return jsonify({
            'status': 'success',
            'username': data.get('username', ''),
            'force_admin_change_required': is_force_admin_change_required(),
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/save_admin_config', methods=['POST'])
@login_required
def save_admin_config():
    global USERS
    try:
        was_force_required = is_force_admin_change_required()
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        if not username or not password:
            return jsonify({'status': 'error', 'message': '用户名和密码不能为空'})
        if is_force_admin_change_required() and username == DEFAULT_ADMIN_USERNAME and password == DEFAULT_ADMIN_PASSWORD:
            return jsonify({'status': 'error', 'message': '远程访问时不能继续使用默认账号密码，请修改后再保存'})
        new_creds = {'username': username, 'password_hash': hash_password(password)}
        with open(ADMIN_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_creds, f, ensure_ascii=False, indent=4)
        USERS = new_creds
        session['username'] = username
        log('SUCCESS', f'后台账号已更新，用户名：{username}')
        message = '账号密码已保存，下次登录生效'
        force_admin_change_required = is_force_admin_change_required()
        if was_force_required and not force_admin_change_required:
            message = '账号密码已保存，当前会话限制已解除'
        return jsonify({
            'status': 'success',
            'message': message,
            'force_admin_change_required': force_admin_change_required,
            'username': username,
        })
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

_tk_lock = threading.Lock()  # 确保同一时刻只弹一个文件选择框（threading 已在文件顶部导入）


@app.route('/get_webhook_config')
@login_required
def get_webhook_config():
    try:
        config = webhook_send.load_config(WEBHOOK_FILE)
        return jsonify({'status': 'success', **config})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/save_webhook_config', methods=['POST'])
@login_required
def save_webhook_config():
    try:
        data = request.get_json() or {}
        config = webhook_send.save_config(data, WEBHOOK_FILE)
        log('SUCCESS', f"Webhook 配置已更新，启用状态: {config.get('enabled')}")
        return jsonify({'status': 'success', 'message': 'Webhook 配置已保存', 'config': config})
    except Exception as e:
        log('ERROR', f'保存 Webhook 配置失败: {e}')
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/test_webhook', methods=['POST'])
@login_required
def test_webhook():
    try:
        data = request.get_json() or {}
        ok, message = webhook_send.send_webhook('SiverWXbot_plus 测试通知', '这是一条 Webhook 测试消息。', data)
        return jsonify({'status': 'success' if ok else 'error', 'message': message})
    except Exception as e:
        log('ERROR', f'测试 Webhook 失败: {e}')
        return jsonify({'status': 'error', 'message': str(e)})

# ============================================================
# 系统文件选择接口（调 Windows 原生对话框，不属于配置管线）
# ============================================================


@app.route('/pick_image_file', methods=['GET'])
@login_required
def pick_image_file():
    """
    打开 Windows 原生文件选择对话框，让用户选择一张本地图片或一个视频文件，
    返回其绝对路径。前端直接将路径填入输入框，无需上传文件。

    远程访问时**直接拒绝**：对话框弹在运行面板这台电脑的桌面上，远程用户
    看不到也点不到；而 tkinter 的主循环会一直阻塞在那里，请求也就一直挂着
    （代理侧超时后远程恢复，本机这个对话框仍在等）。远程用户请手动填路径。
    """
    if is_remote_panel_request():
        log('WARNING', '远程访问请求「选择本地图片」已被拒绝：'
                       '文件选择框只会弹在运行面板那台电脑的桌面上')
        return jsonify({
            'status': 'error',
            'code': 'remote_not_supported',
            'message': (
                '远程访问时用不了「选择本地图片」：文件选择框会弹在'
                '<b>运行面板那台电脑</b>的桌面上，你这边看不到也点不到。<br><br>'
                '请直接手动填写图片路径 —— 路径要写<b>运行面板那台电脑</b>上的位置，'
                '例如 <code>C:\\图片\\hello.png</code>。<br>'
                '如果图片现在在你自己电脑上，需要先把它传到运行面板那台电脑。'
            ),
        })
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
                title='选择图片/视频文件',
                filetypes=[
                    ('图片/视频', '*.png *.jpg *.jpeg *.gif *.bmp *.webp *.mp4 *.mov *.avi *.mkv *.wmv *.flv'),
                    ('图片文件', '*.png *.jpg *.jpeg *.gif *.bmp *.webp'),
                    ('视频文件', '*.mp4 *.mov *.avi *.mkv *.wmv *.flv'),
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

# ============================================================
# 记忆库路径工具与记忆管理路由
#
# ⚠ 路径规则只能有一份：全部来自 memory_store.py（wxbot_core 也导入同一份）。
#   面板若自己再写一遍「把非法字符删掉得到目录名」的规则，就会出现
#   「面板看到的目录」和「机器人写的目录」对不上 —— 这正是身份碰撞事故里
#   面板侧复制规则带来的风险。这里只保留薄封装，禁止再定义第二套规则。
# ============================================================

MEMORY_BASE = os.path.join(base_dir(), 'memory')


def _memory_manager(wx_id):
    """取该微信号的记忆管理器（与机器人共用同一个实例/同一把锁）。

    机器人没在跑时也能用：get_memory_manager 会按同样规则新建一个实例。
    """
    return get_memory_manager(wx_id, MEMORY_BASE)


def _memory_wx_ids():
    """列出记忆根目录下的微信号目录（跳过 _quarantine 等内部目录）。"""
    if not os.path.exists(MEMORY_BASE):
        return []
    return [d for d in sorted(os.listdir(MEMORY_BASE))
            if not is_internal_dir_name(d)
            and _safe_is_dir(os.path.abspath(MEMORY_BASE), d)]


def _memory_read_original_name(chat_path, fallback=None):
    """读取记忆目录里记录的原始窗口名（展示用）；读不到时用目录名兜底。"""
    return read_original_name(chat_path, fallback)


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


@app.route('/memory/list')
@login_required
def memory_list():
    """返回所有微信号目录（不含 _quarantine 等内部目录）"""
    try:
        return jsonify({'status': 'success', 'wx_ids': _memory_wx_ids()})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/memory/chats/<wx_id>')
@login_required
def memory_chats(wx_id):
    """返回指定微信号下所有窗口名。

    ⚠ 这里会对每个目录名调用一次 resolve_storage_key：
      面板一打开就会把"归属明确的旧目录"迁到新位置、"归属不明的旧目录"隔离掉，
      因此列表里不会出现"点了没反应"的旧目录，也不会让两个窗口都指向同一份旧数据。
    """
    try:
        manager = _memory_manager(wx_id)
        chats = []
        for raw_name in manager.list_storage_keys():
            # 解析时带上 wx_id：面板与机器人必须算出同一个目录名（含长名字的截断规则）
            storage_key = manager.resolve_storage_key(raw_name)   # 已带上该管理器的 base_dir + wx_id
            chat_path = os.path.join(MEMORY_BASE, wx_id, storage_key)
            # 解析后目录可能已经不存在（旧目录刚被迁移/隔离掉）→ 不列出来
            if not _safe_is_dir(os.path.abspath(os.path.join(MEMORY_BASE, wx_id)), storage_key):
                continue
            chats.append({
                'name': _memory_read_original_name(chat_path, storage_key),
                'storage_name': storage_key,
            })
        return jsonify({'status': 'success', 'chats': chats})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/memory/data/<wx_id>/<chat_name>')
@login_required
def memory_data(wx_id, chat_name):
    """返回指定窗口的记忆数据（JSON 列表）。

    ⚠ 读取也走 MemoryManager：归属不明的旧目录会在这里被隔离掉，
      否则面板会继续展示"多个窗口混在一起"的历史。
    """
    try:
        manager = _memory_manager(wx_id)
        messages = manager.get_messages(chat_name, count=manager.MEMORY_READ_LIMIT)
        return jsonify({'status': 'success', 'messages': messages})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/memory/delete_wx/<wx_id>', methods=['DELETE'])
@login_required
def memory_delete_wx(wx_id):
    """删除指定微信号的所有记忆"""
    try:
        # wx_id 直接来自 URL 路径段，删除前先确认目标就是 MEMORY_BASE 下的一层目录。
        # ⚠ 必须逐个删除目标校验：wx_id = r'..\..\某个目录' 时，
        #   os.path.join(MEMORY_BASE, wx_id) 会落在 MEMORY_BASE 之外，
        #   而 delete_account 是按"自己拼出来的目录"遍历的，会跟着删到外面去。
        target, path_err = _resolve_path_within(MEMORY_BASE, wx_id)
        if path_err or target != os.path.join(os.path.abspath(MEMORY_BASE), wx_id):
            log('WARNING', f'拒绝删除越界的记忆目录：wx_id={wx_id!r}')
            return jsonify({'status': 'error',
                            'message': path_err or '目标路径不在允许的目录内，已拒绝'})
        # 删除只允许走记忆存储这一个入口（内部按会话取锁），不再直接 rmtree
        count = _memory_manager(wx_id).delete_account()
        log('SUCCESS', f'已删除微信号 {wx_id} 的所有记忆（{count} 条记录）')
        return jsonify({'status': 'success', 'message': '已删除'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/memory/delete_chat/<wx_id>/<chat_name>', methods=['DELETE'])
@login_required
def memory_delete_chat(wx_id, chat_name):
    """删除指定窗口的记忆文件"""
    try:
        # wx_id 来自 URL 路径段：不校验时 /memory/delete_chat/..%5C..%5C<项目目录名>
        # 会把项目目录当「聊天窗口」递归删掉
        parent_abs, path_err = _resolve_path_within(MEMORY_BASE, wx_id)
        if path_err:
            log('WARNING', f'拒绝删除越界的记忆目录：wx_id={wx_id!r}')
            return jsonify({'status': 'error', 'message': path_err})
        # 删除只允许走记忆存储这一个入口（内部按存储标识取会话锁）。
        # chat_name 可能是窗口名，也可能是面板列表回传的存储标识，两种都支持；
        # 带路径分隔符的名字会在 MemoryManager 里被拒绝（不会命中任何目录）。
        deleted = _memory_manager(wx_id).delete_chat(chat_name)
        log('SUCCESS', f'已删除 {wx_id}/{chat_name} 的记忆（{deleted}）')
        return jsonify({'status': 'success', 'message': '已删除'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


# ============================================================
# 定时启停线程
#
# 每 10 秒轮询一次系统时间。启停时间只在「线程启动时」和「保存配置后」读取，
# 不是每轮都读盘——配置变更靠 update_config_status 标志触发重载（见 /save_config）。
# ============================================================


def time_start_stop():
    """启动定时启停守护线程（daemon，随面板进程一起退出）。"""
    def is_target_time(target_hour, target_minute):
        """
        校验当前时间是否匹配指定的小时和分钟
        """
        # 获取当前本地时间
        now = datetime.now()
        # 比较小时和分钟是否匹配
        return (now.hour == target_hour) and (now.minute == target_minute)
    def load_time_schedule_config():
        """读取并校验定时启停配置，非法时间格式时仅跳过调度。"""
        time_config = read_config() or {}
        enabled = bool(time_config.get("everyday_start_stop_bot_switch"))
        if not enabled:
            return False, None, None

        start_time, start_err = _parse_hhmm_config(
            time_config.get("everyday_start_bot_time"),
            "everyday_start_bot_time",
        )
        stop_time, stop_err = _parse_hhmm_config(
            time_config.get("everyday_stop_bot_time"),
            "everyday_stop_bot_time",
        )

        errors = [err for err in (start_err, stop_err) if err]
        if errors:
            for err in errors:
                log('ERROR', f'定时启停配置校验失败: {err}')
            log('WARNING', '定时启停已临时禁用，本轮不会执行，请修正时间格式后重新保存配置')
            return False, None, None

        return True, start_time, stop_time
    def time_check_thread():
        """定时检查线程（启停只调 BOT_LIFECYCLE，与手动启停共用同一份状态机）。"""
        global update_config_status
        # 读取配置文件
        start_hour = start_minute = stop_hour = stop_minute = None
        everyday_start_stop_bot_switch, start_time, stop_time = load_time_schedule_config()
        if start_time:
            start_hour, start_minute = start_time
        if stop_time:
            stop_hour, stop_minute = stop_time
        if everyday_start_stop_bot_switch:
            log('INFO', f'启动定时启停线程，启动时间：{start_hour}:{start_minute}，停止时间：{stop_hour}:{stop_minute}')
        else:
            log('INFO', '定时启停未启用，未启用')

        while True:
            if update_config_status: # 保存配置后更新定时启停状态
                update_config_status = False
                start_hour = start_minute = stop_hour = stop_minute = None
                everyday_start_stop_bot_switch, start_time, stop_time = load_time_schedule_config()
                if start_time:
                    start_hour, start_minute = start_time
                if stop_time:
                    stop_hour, stop_minute = stop_time
                if everyday_start_stop_bot_switch:
                    log('INFO', f'配置更新，启动定时启停线程，启动时间：{start_hour}:{start_minute}，停止时间：{stop_hour}:{stop_minute}')
                else:
                    log('INFO', '配置更新，定时启停未启用')
            if everyday_start_stop_bot_switch:
                if is_target_time(start_hour, start_minute): # 启动时间
                    log('INFO', '到达预定启动时间，正在启动机器人')
                    started, message = _spawn_bot_thread('定时启动')
                    if started:
                        log(level='INFO', message="定时启动机器人:机器人已启动")
                        # email_send.send_email(subject="定时启动机器人", content="机器人已启动")
                    else:
                        log(level='WARNING', message=f"定时启动机器人:{message}")
                    time.sleep(60) # 防止一分钟内重复启动
                if is_target_time(stop_hour, stop_minute): # 停止时间
                    log('INFO', '到达预定停止时间，正在停止机器人')
                    outcome = BOT_LIFECYCLE.stop(reason='定时停止')
                    if outcome.stopped:
                        log(level='SUCCESS', message="定时停止机器人:机器人已停止")
                        # email_send.send_email(subject="定时停止机器人", content="机器人已停止")
                    else:
                        log(level='ERROR', message=f"定时停止机器人:{outcome.message}")
                    # 不在此处 _restore_sleep()：本线程从未调用过 _prevent_sleep()，
                    # 防睡眠状态由机器人线程持有，只有机器人线程自己的 finally 能清掉它。
                    time.sleep(60) # 防止一分钟内重复停止
            time.sleep(10)

    time_thread = threading.Thread(target=time_check_thread, daemon=True)
    time_thread.start()
# ============================================================
# 服务端口选择与程序入口
# ============================================================


def find_free_port(start_port=10001, max_port=11000):
    """从 start_port 开始寻找空闲端口"""
    for port in range(start_port, max_port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
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
            default_config = dict(config_defaults.DEFAULT_CONFIG)
            _write_json_atomic(CONFIG_FILE, default_config)
            log('WARNING', '配置文件不存在，已创建默认配置文件')
        log('INFO', '服务5s后启动')
        # 启动时自动备份检查
        try:
            _check_and_auto_backup()
        except Exception as _backup_e:
            log('ERROR', f'自动备份检查失败: {_backup_e}')
        # 动态选择端口
        global panel_server_port
        free_port = find_free_port(10001, 11000)
        panel_server_port = free_port
        log('INFO', f'请访问 http://localhost:{free_port} 或者 http://127.0.0.1:{free_port} 进行登录')
        # 启动后自动打开浏览器
        webbrowser.open(f"http://127.0.0.1:{free_port}")
        # 定时启停
        time_start_stop()
        if siver_panel_manager is not None:
            siver_panel_manager.set_local_port_provider(get_panel_server_port)
            siver_panel_manager.start()
        # 启动服务器
        app.run(host='0.0.0.0', port=free_port, debug=False, threaded=True)
    except Exception as e:
        log('ERROR', f'服务器启动失败: {str(e)}')
    finally:
        log('INFO', '服务器已停止')

if __name__ == '__main__':
    main()