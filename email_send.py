'''
邮件发送程序
作者：https://siver.top
时间：2025-03-05

email.txt文件格式：
第一行填发件人邮箱的SMTP服务器地址
第二行填发件人邮箱的SMTP服务器端口
第三行填写发件人邮箱
第四行填写邮箱授权码或密码/qq邮箱为授权码

email.txt文件需要和email_send.py文件在同一目录下
'''
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import time
import os
import sys

def _base_dir():
    if hasattr(sys, '_MEIPASS'):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")

email_path = os.path.join(_base_dir(), 'config', 'email.txt')

def read_config(config_path=email_path):
    """从配置文件读取SMTP参数，如果不存在或内容不完整，则创建默认配置文件"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f.readlines()[:4]]
            if len(lines) < 4:
                raise ValueError("配置文件内容不完整")
            return {
                'host': lines[0],
                'port': int(lines[1]),  # 转换端口为整数
                'user': lines[2],
                'pass': lines[3]
            }
    except Exception as e:
        print(f"配置文件读取失败: {str(e)}\n正在创建默认配置文件：{config_path}")
        default_content = "smtp.qq.com\n465\n1234567890@qq.com\nsqmpasswordsqm\n\n\n第一行填发件人邮箱的SMTP服务器地址\n第二行填发件人邮箱的SMTP服务器端口\n第三行填写发件人邮箱\n第四行填写邮箱授权码或密码/qq邮箱为授权码"
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(default_content)
            print(f"默认配置文件email.txt已创建：{config_path}")
        except Exception as write_e:
            print(f"默认配置文件创建失败: {str(write_e)}")
            while True:
                time.sleep(100)
        # 再次尝试读取刚创建的默认配置文件
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f.readlines()[:4]]
                return {
                    'host': lines[0],
                    'port': int(lines[1]),
                    'user': lines[2],
                    'pass': lines[3]
                }
        except Exception as e2:
            print(f"读取默认配置文件失败: {str(e2)}")
            while True:
                time.sleep(100)

# 配置在每次发送时动态读取，不使用模块级全局变量（避免启动时缓存旧配置）

def send_qq_email(receiver, subject, content):
    '''
    发送QQ邮箱邮件
    receiver: 收件人邮箱
    subject: 邮件主题
    content: 邮件内容
    '''
    # 每次发送时重新读取配置，确保使用最新配置
    cfg = read_config()
    mail_host = cfg['host']
    mail_port = cfg['port']
    mail_user = cfg['user']
    mail_pass = cfg['pass']

    # 创建MIMEText对象构建邮件内容
    message = MIMEText(content, 'plain', 'utf-8')
    message['From'] = Header(mail_user)          # 发件人
    message['To'] = Header(receiver)             # 收件人
    message['Subject'] = Header(subject)         # 主题

    try:
        # 使用SSL加密连接SMTP服务器
        smtpObj = smtplib.SMTP_SSL(mail_host, mail_port)
        # 确保用户名和密码是纯 ASCII 字符串，去除可能的空白字符和 BOM
        user_clean = mail_user.strip().encode('ascii', errors='ignore').decode('ascii')
        pass_clean = mail_pass.strip().encode('ascii', errors='ignore').decode('ascii')
        smtpObj.login(user_clean, pass_clean)      # 登录邮箱
        smtpObj.sendmail(mail_user, receiver, message.as_string())
        print("邮件发送成功")
    except smtplib.SMTPException as e:
        print(f"邮件发送失败，错误：{str(e)}")
    finally:
        smtpObj.quit()

def send_email(receiver=None, subject="默认邮件主题", content="这是来自Python程序的默认邮件内容"):
    '''
    发送邮件 默认给配置中的自己发邮件
    receiver: 收件人邮箱（None 时发给配置文件中的发件人自己）
    subject: 邮件主题
    content: 邮件内容
    '''
    cfg = read_config()
    if receiver is None:
        receiver = cfg['user']
    send_qq_email(receiver, subject, content)

# 使用示例
if __name__ == "__main__":
    send_qq_email(
        receiver="666666@qq.com",  # 收件邮箱
        subject="测试邮件主题",
        content="这是来自Python程序的测试邮件内容"
    )
