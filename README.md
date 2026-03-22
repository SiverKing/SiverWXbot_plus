# 🤖 Siver WX机器人 (wxbot_plus)

[![Version](https://img.shields.io/badge/version-V4.5.2-blue.svg)](https://github.com/SiverKing/SiverWXbot_plus)
[![Python](https://img.shields.io/badge/python-3.8+-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)

> 一个功能完整、架构清晰的WX机器人框架，支持多 AI 平台接入、对话记忆、灵活的监听模式、丰富的管理命令和智能的消息处理流程。

**作者**: [Siver](https://www.siver.top)

📖 **[查看完整使用文档](https://wxbot.siverking.online)**

---

## ✨ 核心特性

### 🧠 对话记忆（新）
- **全窗口记忆存储** - 机器人运行时将所有收发消息按聊天窗口独立存档
- **AI 上下文携带** - 调用 AI 时自动带入最近 N 条历史消息，实现连续对话
- **灵活配置** - 最大存储条数（50~2000）、AI 带入条数均可单独配置
- **记忆管理面板** - 在 Web 面板中可视化查看/删除各窗口的记忆记录，气泡式消息展示

### 🎯 多 AI 平台支持
- **DusAPI** ⭐ 推荐 - 兼容 Claude、GPT 等全系模型，国内稳定低延迟，一个 Key 搞定所有需求
  - 官网：[dusapi.com](https://dusapi.com)
  - **自动重试**：自动失败重试机制
- **OpenAI SDK** - 兼容所有 OpenAI 格式的 API（DeepSeek、通义千问等）
  - 支持流式和非流式输出
  - 支持思维链内容（reasoning_content）
  - 自动降级到 Responses API 备用方案
- **Dify** - 调用 Dify 对话工作流
- **Coze（扣子）** - 使用官方 cozepy SDK

### 🔄 双监听模式
- **白名单模式** - 精准监听指定用户和群组
- **黑名单模式** - 全局监听所有消息，动态管理会话列表

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
- **自定义定时消息** - 像手机闹钟一样完全自定义定时
  - 单次发送 - 指定日期时间发送一次
  - 每天发送 - 每天固定时间发送
  - 每周发送 - 选择星期几发送
  - 每月发送 - 选择每月几号发送
  - 自定义日期 - 指定多个日期发送
- **独立开关** - 每条定时任务可单独启用/禁用
- **定时启停** - 设置机器人每日自动启动和停止时间

### 🛠️ 管理命令系统
通过WX消息发送命令，实时管理机器人：
- 用户管理：添加/删除用户、查看当前用户
- 群组管理：添加/删除群、开启/关闭群机器人
- 接口管理：查看接口列表、切换当前使用的接口
- AI 设定：修改系统提示词
- 系统管理：更新配置、查看状态、查看版本

### 🌐 Web 管理界面
- **状态面板** - 首页实时展示运行状态、消息统计、在线时长等关键指标，5 秒自动刷新
- **记忆管理** - 三栏式记忆查看器（wx号→窗口→消息气泡），支持删除
- **全新 UI** - 侧边栏导航 + 分类标签页，配置一目了然
- **用户认证** - 账密从代码分离到 `admin.json`，修改无需改代码
- **实时日志** - 底部可折叠日志面板，支持级别筛选（INFO/SUCCESS/WARNING/ERROR）
- **配置管理** - 在线修改所有配置，保存即生效

### 📧 告警通知
- **邮件告警** - 发生错误时自动发送邮件通知
- **离线检测** - WX离线时自动告警

---

## 🌟 推荐使用 DusAPI

> **为什么推荐 DusAPI？**

| | DusAPI | 直连 OpenAI |
|---|---|---|
| 国内访问 | ✅ 稳定低延迟 | ❌ 需要代理 |
| 模型覆盖 | ✅ Claude + GPT 全系 | ⚠️ 仅 OpenAI |
| 一个 Key | ✅ 搞定所有模型 | ❌ 各平台单独申请 |
| 兼容性 | ✅ 最优 | ⚠️ 部分接口差异 |
| 自动重试 | ✅ 梯度重试，更稳定 | ⚠️ 依赖 SDK 默认行为 |

👉 前往 [dusapi.com](https://dusapi.com) 注册获取 Key，支持 Claude Opus 4.6、Claude Sonnet 4.6、GPT-5、GPT-5 Pro 等主流模型。

---

## 📦 安装部署

### 环境要求
- Python `3.8` - `3.12`
- Windows 操作系统
- Windows wx PC 版（`4.1.7` - `4.1.8` 版本）
- wxautox4 授权（需购买，地址：[点我进入](https://www.siver.top/static/img/siver_wx.jpg)）

### 安装步骤

> 💡 **懒得折腾？** 直接从 [Releases](../../releases) 下载打包好的 `.exe`，解压即用，无需安装 Python 和依赖。

1. **克隆项目**
```bash
git clone https://github.com/SiverKing/SiverWXbot_plus.git
cd wxbot_plus
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **配置 wxautox4 授权**
   - 购买地址：https://www.siver.top/static/img/siver_wx.jpg
   - 按照官方文档激活授权

4. **配置机器人**
   - 首次运行会自动创建 `config.json` 配置文件
   - 根据需求修改配置（详见配置说明）

5. **配置邮件告警（可选）**
   - 首次运行会自动创建 `email.txt` 配置文件
   - 填写 SMTP 服务器信息

6. **启动机器人**
```bash
python web_server.py
```

---

## ⚙️ 配置说明

### config.json 配置文件

```json
{
    "api_configs": [
        {"sdk": "DusAPI", "key": "your-api-key", "url": "https://api.dusapi.com", "model": "gpt-5"},
        {"sdk": "DusAPI", "key": "your-api-key", "url": "https://api.dusapi.com", "model": "claude-sonnet-4-6"}
    ],
    "api_index": 0,
    "prompt": "你是一个 AI 助手，请根据用户的问题给出回答",
    "admin": "文件传输助手",
    "AllListen_switch": false,
    "listen_list": ["用户1", "用户2"],
    "group": ["群聊1", "群聊2"],
    "group_switch": true,
    "group_reply_at": true,
    "group_welcome": true,
    "group_welcome_random": 1.0,
    "group_welcome_msg": "欢迎新朋友！",
    "new_friend_switch": true,
    "new_friend_msg": ["你好", "我是机器人"],
    "chat_keyword_switch": true,
    "group_keyword_switch": true,
    "keyword_dict": {
        "关键词1": "回复内容1",
        "关键词2": "回复内容2"
    },
    "scheduled_msg_switch": true,
    "scheduled_msg_list": [
        {
            "id": "abc123",
            "enabled": true,
            "target": "用户昵称",
            "time": "08:00",
            "repeat_type": "weekly",
            "weekdays": [1, 3, 5],
            "dates": [],
            "msgs": ["早安", "今天也要加油哦"]
        }
    ],
    "everyday_start_stop_bot_switch": false,
    "everyday_start_bot_time": "08:00",
    "everyday_stop_bot_time": "23:00",
    "memory_switch": true,
    "memory_max_count": 500,
    "memory_context_count": 100
}
```

### 配置项说明

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `api_configs` | array | AI 接口配置列表，每项含 `sdk`/`key`/`url`/`model` 四个字段 |
| `api_index` | integer | 当前使用的接口索引（0-based），通过管理命令或面板切换 |
| `prompt` | string | AI 系统提示词 |
| `admin` | string | 管理员昵称，可发送管理命令 |
| `AllListen_switch` | boolean | `false`=白名单模式，`true`=黑名单模式 |
| `listen_list` | array | 白名单/黑名单用户列表 |
| `group` | array | 监听的群聊列表 |
| `group_switch` | boolean | 群机器人总开关 |
| `group_reply_at` | boolean | 是否仅在被 @ 时回复群消息 |
| `group_welcome` | boolean | 是否开启群新人欢迎语 |
| `group_welcome_random` | float | 欢迎语触发概率（0.0-1.0） |
| `group_welcome_msg` | string | 群新人欢迎语内容 |
| `new_friend_switch` | boolean | 是否自动通过新好友请求 |
| `new_friend_msg` | array | 通过好友后自动发送的打招呼消息列表 |
| `chat_keyword_switch` | boolean | 是否开启私聊关键词回复 |
| `group_keyword_switch` | boolean | 是否开启群聊关键词回复 |
| `keyword_dict` | object | 关键词→回复内容映射 |
| `scheduled_msg_switch` | boolean | 是否开启定时消息 |
| `scheduled_msg_list` | array | 定时任务列表，支持 once/daily/weekly/monthly/custom |
| `everyday_start_stop_bot_switch` | boolean | 是否开启每日定时启停机器人 |
| `everyday_start_bot_time` | string | 每日自动启动机器人的时间（格式 `HH:MM`） |
| `everyday_stop_bot_time` | string | 每日自动停止机器人的时间（格式 `HH:MM`） |
| `memory_switch` | boolean | 是否开启对话记忆功能，默认 `true` |
| `memory_max_count` | integer | 单窗口最多存储的消息条数（50~2000），默认 `500` |
| `memory_context_count` | integer | AI 请求时带入的历史消息条数（50~上限），默认 `100` |

### admin.json 账密文件

位于 `config/admin.json`，首次启动自动创建，直接编辑后重启服务生效，也可在面板「账号密码」页在线修改：

```json
{
    "username": "admin",
    "password": "123456"
}
```

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

### 1、Web 管理界面

1. 启动 Web 服务器：
```bash
python web_server.py
```

2. 浏览器访问：`http://localhost:10001`

3. 默认账号：
   - 用户名：`admin`
   - 密码：`123456`
   - 账密保存在 `config/admin.json`，可在面板内修改

### 2、管理命令列表

向管理员账号发送以下命令来管理机器人：

#### 用户管理
```
/添加用户`用户昵称`
/删除用户`用户昵称`
/当前用户
```

#### 群组管理
```
/添加群`群名称`
/删除群`群名称`
/当前群
/开启群机器人
/关闭群机器人
```

#### 群欢迎语管理
```
/开启群机器人欢迎语
/关闭群机器人欢迎语
/更改群机器人欢迎语为`新的欢迎语内容`
```

#### AI 接口管理
```
/查看接口列表              # 查看所有接口配置，▶ 标记当前使用
/选择接口 N               # 切换至第 N 个接口（如：/选择接口 2）
```

#### AI 设定
```
/当前AI设定
/更改AI设定为`新的系统提示词`
```

#### 系统管理
```
/更新配置        # 重新加载配置文件
/当前版本        # 查看机器人版本
/指令            # 查看所有可用命令
/状态            # 查看机器人运行状态
```

---

## 📁 项目结构

```
wxbot_plus/
├── wxbot_class_only_V2.py    # 机器人主程序
├── web_server.py              # Web 管理界面
├── logger.py                  # 日志模块
├── email_send.py              # 邮件发送模块
├── requirements.txt           # 依赖列表
├── config/                    # 配置文件目录（自动创建）
│   ├── config.json            # 机器人配置
│   ├── admin.json             # Web 管理账密
│   └── email.txt              # 邮件告警配置
├── memory/                    # 对话记忆目录（自动创建）
│   └── {wx_id}/               # 按wx号分目录
│       └── {chat_name}/       # 按聊天窗口分目录
│           └── {chat_name}_memory.json
├── panel_logs/                # 运行日志目录（自动创建）
├── templates/                 # Web 界面模板
└── wxauto_logs/               # wxautox 日志目录
```

---

## 🔧 核心类说明

### WXBotConfig
配置管理类，负责配置文件的加载、保存和动态管理。

### MemoryManager
对话记忆管理类，按聊天窗口分文件存储历史消息，线程安全写入。

**特性**：
- 每个聊天窗口独立存储为 JSON 文件
- 写入带线程锁，并发安全
- 超出最大条数时自动删除最旧的消息
- `get_messages(chat, n)` 读取最近 n 条，供 AI 接口使用

### OpenAIAPI
OpenAI 兼容接口类，支持所有 OpenAI 格式的 API。

**特性**：
- 自动降级到 Responses API 备用方案
- 支持流式和非流式输出
- 支持历史记忆上下文（history 参数）

### DusAPI
DusAPI 兼容接口封装类，使用 Anthropic 格式（`x-api-key` + `/v1/messages`）统一调用 Claude、GPT 等全系模型。

**特性**：
- 根据模型名称自动选择响应解析方式：含 `claude` 按 Claude 格式解析，其他按 GPT 格式解析
- **梯度重试机制**：失败后自动重试最多 5 次，间隔 2s→4s→8s→16s→32s 梯度增长
- 支持历史记忆上下文（history 参数）

### DifyAPI
Dify 平台接口类，通过 HTTP 请求调用 Dify 对话工作流。支持将历史对话拼接为上下文前缀传入。

### CozeAPI
扣子平台接口类，使用官方 cozepy SDK 进行流式对话。支持历史消息作为 additional_messages 传入。

### WXBot
WX机器人主类，整合所有功能的核心控制类。

**核心方法**：
- `init_wx_listeners()` - 初始化WX监听器，同时初始化 MemoryManager
- `message_handle_callback()` - 消息回调处理，写入记忆
- `process_message()` - 消息分发逻辑
- `process_command()` - 管理命令处理
- `main()` - 机器人主循环

---

## 🚀 高级功能

### 对话记忆详解

开启后，机器人运行期间所有收发消息均写入记忆文件：

```
memory/
└── wxid_xxxxxx/           ← 你的wx号
    ├── 张三/
    │   └── 张三_memory.json
    └── 某某群/
        └── 某某群_memory.json
```

**记忆 JSON 格式**：
```json
[
  {
    "time": "2024/01/01 12:00:00",
    "type": "text",
    "attr": "friend",
    "sender": "张三",
    "content": "你好"
  },
  {
    "time": "2024/01/01 12:00:05",
    "type": "text",
    "attr": "self",
    "sender": "我",
    "content": "你好！有什么可以帮你的？"
  }
]
```

**注意**：开启记忆后每次 AI 请求都会携带最近 N 条历史，会增加 token 消耗。推荐配置：`memory_max_count=500`，`memory_context_count=100`。

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
  ├─ 写入对话记忆（memory_switch 开启时）
  ├─ attr=friend → 黑/白名单过滤
  │                  ↓
  │               群聊消息？
  │                  ├─ 是 → 检测 @ → 去除 @ 标识 → 带入记忆 → 调用 AI
  │                  └─ 否 → 管理员命令？
  │                            ├─ 是 → 执行命令
  │                            └─ 否 → 关键词回复？
  │                                      ├─ 是 → 返回关键词回复
  │                                      └─ 否 → 带入记忆 → 调用 AI 回复
  ├─ attr=self  → 窗口是管理员（文件传输助手）？
  │                  ├─ 是 → 执行命令（不调用 AI，防止回复循环）
  │                  └─ 否 → 忽略
  └─ attr=system → 群新人欢迎语
```

### 文件传输助手作为管理员

没有第二个wx账号时，可将 `admin` 设置为 `文件传输助手`，在手机上用当前wx账号向「文件传输助手」发送指令，消息会同步到机器人所在的 PC 并被识别执行。

面板「管理员」页有详细说明。

### 错误恢复机制

- **离线检测**：每 10 秒检测一次WX是否在线
- **回调异常检测**：监听器回调异常时自动停止
- **邮件告警**：发生错误时自动发送邮件通知
- **超时会话管理**：自动移除超时会话，释放资源
- **DusAPI 梯度重试**：网络抖动或接口临时故障时自动重试，最多 5 次，间隔梯度增长

---

## ⚠️ 注意事项

1. **wxautox4 授权**
   - 本项目使用 wxautox4（Plus 版），需要购买授权
   - 购买地址：https://www.siver.top/static/img/siver_wx.jpg
   - 请勿用于转卖或发布到公共平台

2. **WX版本**
   - 建议使用WX 4.1.8 版本
   - 不同版本可能需要调整参数

3. **API 配置**
   - 确保 API 密钥有效
   - 注意 API 调用频率限制
   - 建议配置备用 API

4. **记忆功能**
   - 开启记忆后每次 AI 请求携带历史，**会增加 token 消耗**
   - 推荐存储 500 条，AI 带入 100 条，按需调整
   - 记忆文件存储在 `memory/` 目录，勿提交到公共仓库（含聊天内容）

5. **安全建议**
   - 不要将 `config/` 和 `memory/` 目录提交到公共仓库
   - 定期更换 API 密钥
   - 修改 `config/admin.json` 中的默认密码（默认：`123456`）

6. **性能优化**
   - 白名单模式性能优于黑名单模式
   - 关闭不需要的功能可减少资源占用
   - 定期清理日志文件和记忆文件

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## 💬 联系方式

如有问题或建议，欢迎通过以下方式联系：

- 提交 Issue
- 联系作者：https://www.siver.top/static/img/siver_wx.jpg

---

**⭐ 如果这个项目对你有帮助，请给个 Star 支持一下！**
