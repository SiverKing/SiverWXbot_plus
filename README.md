# 🤖 Siver 微信机器人 (wxbot_plus)

[![Version](https://img.shields.io/badge/version-V4.0.1-blue.svg)](https://github.com/yourusername/wxbot_plus)
[![Python](https://img.shields.io/badge/python-3.8+-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)

> 一个功能完整、架构清晰的微信机器人框架，支持多 AI 平台接入、灵活的监听模式、丰富的管理命令和智能的消息处理流程。

**作者**: [Siver](https://siver.top)
**当前版本**: V4.0.1 - 适配 wxautox4 和微信 4.x 版本

---

## ✨ 核心特性

### 🎯 多 AI 平台支持
- **OpenAI SDK** - 兼容所有 OpenAI 格式的 API（DeepSeek、通义千问等）
  - 支持流式和非流式输出
  - 支持思维链内容（reasoning_content）
  - 自动降级到 Responses API 备用方案
- **Dify** - 调用 Dify 对话工作流
- **Coze（扣子）** - 使用官方 cozepy SDK

### 🔄 双监听模式
- **白名单模式** - 精准监听指定用户和群组
- **黑名单模式** - 全局监听所有消息，动态管理会话列表
- 支持运行时切换监听模式

### 💬 智能消息处理
- **关键词回复** - 支持私聊和群聊关键词自动回复
- **AI 智能回复** - 接入多种 AI 平台，提供智能对话
- **超长文本分段** - 自动将超过 2000 字的消息分段发送
- **随机延时** - 模拟人工回复节奏（1-10 秒）
- **消息去重** - 防止重复处理同一条消息

### 👥 群聊功能
- **群新人欢迎语** - 自动检测新成员并发送欢迎消息
- **@ 回复模式** - 支持仅被 @ 时才回复
- **群关键词回复** - 不受 @ 限制的关键词回复
- **欢迎概率配置** - 可设置欢迎语触发概率

### 🤝 新好友管理
- **自动通过好友请求** - 批量处理新好友申请
- **自动打招呼** - 通过后自动发送欢迎消息
- **智能备注** - 自动设置备注（昵称_机器人备注）

### ⏰ 定时任务
- **每日定时消息** - 支持每天指定时间发送消息
- **灵活配置** - 可为不同用户设置不同的定时消息

### 🛠️ 管理命令系统
通过微信消息发送命令，实时管理机器人：
- 用户管理：添加/删除用户、查看当前用户
- 群组管理：添加/删除群、开启/关闭群机器人
- 模型管理：切换 AI 模型、查看当前模型
- AI 设定：修改系统提示词
- 系统管理：更新配置、查看状态、查看版本

### 🌐 Web 管理界面
- **Flask Web 服务器** - 提供可视化管理界面
- **用户认证** - 安全的登录系统
- **实时日志** - 查看机器人运行日志
- **配置管理** - 在线修改配置文件

### 📧 告警通知
- **邮件告警** - 发生错误时自动发送邮件通知
- **离线检测** - 微信离线时自动告警

---

## 📦 安装部署

### 环境要求
- Python 3.8+
- Windows 操作系统
- 微信 PC 版（4.x 版本）
- wxautox4 授权（需购买）

### 安装步骤

1. **克隆项目**
```bash
git clone https://github.com/yourusername/wxbot_plus.git
cd wxbot_plus
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **配置 wxautox4 授权**
   - 购买地址：https://github.com/cluic/wxauto
   - 按照官方文档激活授权

4. **配置机器人**
   - 首次运行会自动创建 `config.json` 配置文件
   - 根据需求修改配置（详见配置说明）

5. **配置邮件告警（可选）**
   - 首次运行会自动创建 `email.txt` 配置文件
   - 填写 SMTP 服务器信息

6. **启动机器人**
```bash
# 方式 1：直接运行主程序
python wxbot_class_only_V2.py

# 方式 2：启动 Web 管理界面
python web_server.py
```

---

## ⚙️ 配置说明

### config.json 配置文件

```json
{
    "api_sdk": "OpenAI",
    "api_key": "your-api-key",
    "base_url": "https://api.example.com/v1",
    "model1": "gpt-4",
    "model2": "gpt-3.5-turbo",
    "prompt": "你是一个 AI 助手，请根据用户的问题给出回答",
    "管理员": "管理员昵称",
    "全局监听开关": false,
    "用户列表": ["用户1", "用户2"],
    "group": ["群聊1", "群聊2"],
    "group_switch": true,
    "群聊是否仅被@时回复": true,
    "群新人欢迎语开关": true,
    "群新人欢迎语": "欢迎新朋友！",
    "群新人欢迎语触发概率": 1.0,
    "自动通过好友开关": true,
    "通过好友打招呼语": ["你好", "我是机器人"],
    "私聊关键词回复开关": true,
    "群聊关键词回复开关": true,
    "关键词回复": {
        "关键词1": "回复内容1",
        "关键词2": "回复内容2"
    },
    "每日定时消息开关": true,
    "每日定时消息": {
        "用户昵称": {
            "time": "08:00",
            "msgs": ["早安", "今天也要加油哦"]
        }
    }
}
```

### 配置项说明

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `api_sdk` | string | AI 接口类型：`OpenAI` / `Dify` / `Coze` |
| `api_key` | string | AI 平台的 API 密钥 |
| `base_url` | string | API 请求基础地址 |
| `model1` / `model2` | string | 模型标识，可通过命令切换 |
| `prompt` | string | AI 系统提示词 |
| `管理员` | string | 管理员昵称，可发送管理命令 |
| `全局监听开关` | boolean | `false`=白名单模式，`true`=黑名单模式 |
| `用户列表` | array | 白名单/黑名单用户列表 |
| `group` | array | 监听的群聊列表 |
| `group_switch` | boolean | 群机器人总开关 |
| `群聊是否仅被@时回复` | boolean | 是否仅在被 @ 时回复群消息 |
| `群新人欢迎语开关` | boolean | 是否开启群新人欢迎语 |
| `群新人欢迎语触发概率` | float | 欢迎语触发概率（0.0-1.0） |
| `自动通过好友开关` | boolean | 是否自动通过新好友请求 |
| `私聊关键词回复开关` | boolean | 是否开启私聊关键词回复 |
| `群聊关键词回复开关` | boolean | 是否开启群聊关键词回复 |
| `关键词回复` | object | 关键词→回复内容映射 |
| `每日定时消息开关` | boolean | 是否开启定时消息 |

### email.txt 配置文件

```
smtp.qq.com
465
your_email@qq.com
your_smtp_password
```

**格式说明**：
- 第 1 行：SMTP 服务器地址
- 第 2 行：SMTP 服务器端口
- 第 3 行：发件人邮箱
- 第 4 行：邮箱授权码（QQ 邮箱为授权码）

---

## 🎮 使用指南

### 管理命令列表

向管理员账号发送以下命令来管理机器人：

#### 用户管理
```
/添加用户 用户昵称
/删除用户 用户昵称
/当前用户
```

#### 群组管理
```
/添加群 群名称
/删除群 群名称
/当前群
/开启群机器人
/关闭群机器人
```

#### 群欢迎语管理
```
/开启群机器人欢迎语
/关闭群机器人欢迎语
/更改群机器人欢迎语为 新的欢迎语内容
```

#### 模型管理
```
/当前模型
/切换模型1
/切换模型2
```

#### AI 设定
```
/当前AI设定
/更改AI设定为 新的系统提示词
```

#### 系统管理
```
/更新配置        # 重新加载配置文件
/当前版本        # 查看机器人版本
/指令            # 查看所有可用命令
/状态            # 查看机器人运行状态
```

### Web 管理界面

1. 启动 Web 服务器：
```bash
python web_server.py
```

2. 浏览器访问：`http://localhost:10001`

3. 默认账号：
   - 用户名：`admin`
   - 密码：`admin`

---

## 📁 项目结构

```
wxbot_plus/
├── wxbot_class_only_V2.py    # 机器人主程序
├── web_server.py              # Web 管理界面
├── logger.py                  # 日志模块
├── email_send.py              # 邮件发送模块
├── requirements.txt           # 依赖列表
├── config.json                # 配置文件（自动生成）
├── email.txt                  # 邮件配置（自动生成）
├── templates/                 # Web 界面模板
├── logs/                      # 日志文件目录
└── wxauto_logs/               # wxautox 日志目录
```

---

## 🔧 核心类说明

### WXBotConfig
配置管理类，负责配置文件的加载、保存和动态管理。

### OpenAIAPI
OpenAI 兼容接口类，支持所有 OpenAI 格式的 API。

**特性**：
- 自动降级到 Responses API 备用方案
- 支持流式和非流式输出
- 详细的错误处理和重试机制

### DifyAPI
Dify 平台接口类，通过 HTTP 请求调用 Dify 对话工作流。

### CozeAPI
扣子平台接口类，使用官方 cozepy SDK 进行流式对话。

### WXBot
微信机器人主类，整合所有功能的核心控制类。

**核心方法**：
- `init_wx_listeners()` - 初始化微信监听器
- `message_handle_callback()` - 消息回调处理
- `process_message()` - 消息分发逻辑
- `process_command()` - 管理命令处理
- `main()` - 机器人主循环

---

## 🚀 高级功能

### 监听模式详解

#### 白名单模式（推荐）
- 仅监听配置文件中指定的用户和群组
- 性能开销小，适合精准监听场景
- 管理员始终被监听

#### 黑名单模式
- 监听所有消息，动态管理会话列表
- 自动移除 3 分钟无消息的会话
- 适合需要全局监听的场景

### 消息处理流程

```
接收消息
  ↓
黑/白名单过滤
  ↓
群聊消息？
  ├─ 是 → 检测 @ → 去除 @ 标识 → 调用 AI
  └─ 否 → 管理员命令？
           ├─ 是 → 执行命令
           └─ 否 → 关键词回复？
                    ├─ 是 → 返回关键词回复
                    └─ 否 → 调用 AI 回复
```

### 错误恢复机制

- **离线检测**：每 10 秒检测一次微信是否在线
- **回调异常检测**：监听器回调异常时自动停止
- **邮件告警**：发生错误时自动发送邮件通知
- **超时会话管理**：自动移除超时会话，释放资源

---

## 📝 开发日志

### V4.0.1 (2026-03-12)
- 适配新版本全局监听
- 优化 OpenAI API 错误处理
- 添加 Responses API 备用方案

### V4.0.0
- 更新为 wxautox4
- 适配微信 4.x 版本

---

## ⚠️ 注意事项

1. **wxautox4 授权**
   - 本项目使用 wxautox4（Plus 版），需要购买授权
   - 购买地址：https://github.com/cluic/wxauto
   - 请勿用于转卖或发布到公共平台

2. **微信版本**
   - 建议使用微信 4.x 版本
   - 不同版本可能需要调整参数

3. **API 配置**
   - 确保 API 密钥有效
   - 注意 API 调用频率限制
   - 建议配置备用 API

4. **安全建议**
   - 不要将 `config.json` 和 `email.txt` 提交到公共仓库
   - 定期更换 API 密钥
   - Web 管理界面建议修改默认密码

5. **性能优化**
   - 白名单模式性能优于黑名单模式
   - 关闭不需要的功能可减少资源占用
   - 定期清理日志文件

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## 🔗 相关链接

- **作者主页**: https://siver.top
- **wxautox 官方**: https://github.com/cluic/wxauto
- **wxautox 文档**: https://docs.wxauto.org

---

## 💬 联系方式

如有问题或建议，欢迎通过以下方式联系：

- 提交 Issue
- 访问作者主页：https://siver.top

---

**⭐ 如果这个项目对你有帮助，请给个 Star 支持一下！**
