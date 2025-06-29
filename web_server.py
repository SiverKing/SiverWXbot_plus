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
from logging.handlers import RotatingFileHandler
from functools import wraps
import threading
from wxbot_class_only_V2 import WXBot
from logger import log
import logger

import pythoncom

# fix_paths.py
import sys
# import os
def resource_path(relative_path):
    """ 获取资源的绝对路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# 初始化 Flask 应用
app = Flask(__name__,
    template_folder=resource_path('templates')
)
app.secret_key = 'your_very_long_and_random_secret_key_here'  # 应该使用随机生成的密钥

# 安全配置
app.config.update(
    SESSION_COOKIE_SECURE=True,    # 只允许HTTPS传输cookie
    SESSION_COOKIE_HTTPONLY=True,  # 防止JavaScript访问cookie
    SESSION_COOKIE_SAMESITE='Lax', # 防止CSRF攻击
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2)  # session有效期
)

# 配置参数
app.secret_key = 'your_secret_key_here'  # Flask 会话加密密钥
PORT = 10001  # 服务器端口
CONFIG_FILE = 'config.json'  # 配置文件路径

# 用户认证信息 (用户名: 密码)
USERS = {
    "admin": "admin",
    "user": "123456"
}

# 日志颜色映射
LOG_COLORS = {
    'INFO': 'text-primary',
    'WARNING': 'text-warning',
    'ERROR': 'text-danger',
    'DEBUG': 'text-secondary',
    'SUCCESS': 'text-success'
}

# 全局日志列表
log_messages = []

def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 检查session和登录状态
        if not session.get('logged_in'):
            # 如果是API请求返回JSON错误
            if request.path.startswith('/api/') or request.accept_mimetypes.accept_json:
                return jsonify({'status': 'error', 'message': '未登录'}), 401
            # 否则重定向到登录页
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

'''# 日志记录函数 (可以被其他文件调用)
def log(level, msg):
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
    print(f"[{timestamp}] [{level}] {msg}")'''

# 日志记录函数 (可以被其他文件调用)
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

# 读取配置文件
def read_config():
    """读取配置文件"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log('ERROR', f'读取配置文件失败: {str(e)}')
        return None

# 保存配置文件
def save_config(config_data):
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        log('SUCCESS', '配置文件保存成功')
        return True
    except Exception as e:
        log('ERROR', f'保存配置文件失败: {str(e)}')
        return False




@app.route('/api/check_auth')
def check_auth():
    """检查认证状态"""
    return jsonify({
        'authenticated': session.get('logged_in', False)
    })
# 登录页面
@app.route('/', methods=['GET', 'POST'])
def login():
    """登录页面"""
    # 如果已登录，直接跳转到dashboard
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # 更安全的密码比较方法（防止时序攻击）
        def safe_str_cmp(a, b):
            if len(a) != len(b):
                return False
            result = 0
            for x, y in zip(a, b):
                result |= ord(x) ^ ord(y)
            return result == 0
        
        if username == USERS['admin'] and safe_str_cmp(USERS['user'], password):
            session['logged_in'] = True
            session['username'] = username
            session.permanent = True  # 持久会话
            log('SUCCESS', f'用户 {username} 登录成功')
            
            # 重定向到原始请求页面或dashboard
            next_page = request.args.get('next') or url_for('dashboard')
            return redirect(next_page)
        else:
            log('WARNING', f'登录失败: 用户名或密码错误 (用户名: {username})')
            return render_template('login.html', error='用户名或密码错误')
    
    return render_template('login.html')

# 登出
@app.route('/logout')
def logout():
    """安全登出"""
    # 清除session数据
    session.clear()
    # 创建新的session ID
    session.regenerate()
    return redirect(url_for('login'))

# 仪表盘主页
@app.route('/dashboard')
@login_required
def dashboard():
    """仪表盘主页"""
    config = read_config()
    if not config:
        return render_template('error.html', message='无法读取配置文件')
    
    # 隐藏敏感信息
    if 'api_key' in config:
        config['api_key_display'] = '*' * len(config['api_key'])
    
    # 确保api_sdk_list和api_sdk字段存在（兼容旧配置）
    if 'api_sdk_list' not in config:
        config['api_sdk_list'] = ["openai SDK", "dify"]  # 默认值
    
    if 'api_sdk' not in config:
        config['api_sdk'] = config['api_sdk_list'][0]  # 默认选择第一个
    
    return render_template('dashboard.html', 
                         config=config,
                         logs=log_messages[-50:])  # 只显示最近50条日志

# 获取最新日志
@app.route('/get_logs')
@login_required
def get_logs():
    """获取最新日志"""
    return jsonify({'logs': logger.log_messages[-50:]})

# 保存配置文件
def save_config(config_data):
    """保存配置文件"""
    try:
        # 读取原始配置以保留未修改的字段
        original_config = read_config() or {}
        
        # 合并配置（保留原始配置中未修改的字段）
        merged_config = {**original_config, **config_data}
        
        # 处理布尔值字段
        boolean_fields = [
            'AllListen_switch', 
            'group_switch', 
            'group_reply_at', 
            'group_welcome', 
            'new_friend_switch'
        ]
        
        for field in boolean_fields:
            if field in merged_config:
                # 将字符串 'on'/'off' 转换为布尔值
                if isinstance(merged_config[field], str):
                    merged_config[field] = (merged_config[field].lower() == 'on')
                # 确保最终是布尔类型
                merged_config[field] = bool(merged_config[field])
        
        # 处理列表字段（确保是列表类型）
        list_fields = ['listen_list', 'group', 'new_friend_msg']
        for field in list_fields:
            if field in merged_config and not isinstance(merged_config[field], list):
                if isinstance(merged_config[field], str):
                    merged_config[field] = [merged_config[field]] if merged_config[field] else []
                else:
                    merged_config[field] = []
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(merged_config, f, ensure_ascii=False, indent=4)
        log('SUCCESS', '配置文件保存成功')
        return True
    except Exception as e:
        log('ERROR', f'保存配置文件失败: {str(e)}')
        return False

@app.route('/save_config', methods=['POST'])
@login_required
def save_config_route():
    """保存配置接口"""
    try:
        config_data = request.get_json()
        if not config_data:
            return jsonify({'status': 'error', 'message': '无效的配置数据'})
        
        # 读取当前配置
        current_config = read_config() or {}
        
        # 处理API Key - 如果前端传的是星号则保留原值
        if 'api_key' in config_data and config_data['api_key'].startswith('*'):
            config_data['api_key'] = current_config.get('api_key', '')
        
        # 合并配置（保留未修改的字段）
        merged_config = {**current_config, **config_data}
        
        # 确保布尔字段是布尔类型
        boolean_fields = [
            'AllListen_switch', 
            'group_switch', 
            'group_reply_at', 
            'group_welcome', 
            'new_friend_switch'
        ]
        
        for field in boolean_fields:
            if field in merged_config:
                merged_config[field] = bool(merged_config[field])
        
        # 确保列表字段是列表类型
        list_fields = ['listen_list', 'group', 'new_friend_msg', 'api_sdk_list']
        for field in list_fields:
            if field in merged_config:
                if not isinstance(merged_config[field], list):
                    merged_config[field] = [merged_config[field]] if merged_config[field] else []
                # 过滤空值
                merged_config[field] = [item for item in merged_config[field] if str(item).strip()]
        
        # 保存配置
        if save_config(merged_config):
            return jsonify({'status': 'success', 'message': '配置保存成功'})
        else:
            return jsonify({'status': 'error', 'message': '配置保存失败'})
            
    except Exception as e:
        log('ERROR', f'保存配置出错: {str(e)}')
        return jsonify({'status': 'error', 'message': str(e)})

# 启动机器人
bot = None
bot_thread = None
@app.route('/start_bot', methods=['POST'])
@login_required
def start_bot():
    """启动机器人接口"""
    # 这里留给你实现机器人启动逻辑
    log('INFO', '机器人启动请求已接收')
    global bot_thread
    if bot_thread and bot_thread.is_alive():
        log("WARNING", "状态：机器人已在运行")
        return jsonify({'status': 'success', 'message': '机器人已在运行'})
    
    def run_bot():
        pythoncom.CoInitialize()  # 防止多线程调用COM组件时出错
        global bot
        bot = WXBot()
        bot.run()
        pythoncom.CoUninitialize()  # 释放COM组件
    try:
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
    except Exception as e:
        log('ERROR', f'启动机器人失败: {str(e)}')
    return jsonify({'status': 'success', 'message': '机器人启动命令已发送'})

# 停止机器人
@app.route('/stop_bot', methods=['POST'])
@login_required
def stop_bot():
    """停止机器人接口"""
    # 这里留给你实现机器人停止逻辑
    log('INFO', '机器人停止请求已接收')
    global bot_thread, bot
    if bot_thread and bot_thread.is_alive():
        if bot.stop_wxbot():  # 调用停止函数并检查返回值
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

    return jsonify({'status': 'success', 'message': '机器人停止命令已发送'})

# 加载配置
@app.route('/load_config')
@login_required
def load_config():
    """加载配置接口"""
    config = read_config()
    if not config:
        return jsonify({'status': 'error', 'message': '无法读取配置文件'})
    
    # 隐藏敏感信息
    if 'api_key' in config:
        config['api_key_display'] = '*' * len(config['api_key'])
    
    return jsonify({'status': 'success', 'config': config})

# 主函数
def main():
    """主函数"""
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            RotatingFileHandler('app.log', maxBytes=1024*1024, backupCount=5)
        ]
    )
    
    log('INFO', '服务器启动中...')
    
    try:
        # 检查配置文件是否存在
        if not os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f)
            log('WARNING', '配置文件不存在，已创建空配置文件')
        # log('INFO', '配置文件存在')
        log('INFO', '服务5s后启动')
        log('INFO', '请访问 http://localhost:10001 或者 http://127.0.0.1:10001 进行登录')
        # 启动Flask应用
        app.run(host='0.0.0.0', port=PORT, debug=False)
    except Exception as e:
        log('ERROR', f'服务器启动失败: {str(e)}')
    finally:
        log('INFO', '服务器已停止')

if __name__ == '__main__':
    main()