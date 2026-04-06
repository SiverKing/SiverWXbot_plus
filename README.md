# 🤖 Siver WX机器人 (wxbot_plus)

[![Version](https://img.shields.io/badge/version-V4.7.07-blue.svg)](https://github.com/SiverKing/SiverWXbot_plus)
[![Python](https://img.shields.io/badge/python-3.9+-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

> 一个功能完整、架构清晰的WX机器人框架，支持多 AI 平台接入、多份 Prompt 管理、对话记忆、拆分多条回复、图片识别、自定义规则转发、灵活的监听模式、50+ 管理命令和智能的消息处理流程。

**作者**: [Siver](https://www.siver.top)

📖 **[查看完整使用文档](https://wxbot.siverking.online)**

---

## 📦 安装部署

### 环境要求
- Python `3.9` ~ `3.12`
- Windows 操作系统
- Windows wx PC 版（`4.1.7` ~ `4.1.8.101` 版本）

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

3. **配置机器人**
   - 首次运行会自动创建 `config.json` 配置文件
   - 首次运行会自动创建 `config/prompt/` 目录及 `默认.md` 文件

4. **配置邮件告警（可选）**
   - 首次运行会自动创建 `email.txt` 配置文件

5. **启动机器人**
```bash
python web_server.py
```

---

## ✨ 核心特性

### 📝 多 Prompt 管理（新）
- **多份独立存储** - Prompt 从配置文件中独立出来，存储为 `config/prompt/*.md` 文件，每个文件一份 Prompt，支持在面板内增删改
- **灵活的差异化配置** - 可为每个群组、每个白名单用户单独绑定不同 Prompt，实现"客服群用客服 Prompt、销售群用销售 Prompt"等场景
- **私聊白名单专属接口 + Prompt** - 白名单模式下，每个监听用户可同时绑定专属 AI 接口和专属 Prompt，与群组的独立接口能力对齐
- **全局默认 Prompt** - 全局监听（黑名单）模式下选择一个全局 Prompt，未单独绑定 Prompt 的用户/群组自动使用全局默认
- **文件导入** - 直接往 `config/prompt/` 文件夹放 `.md` 文件，保存配置后刷新面板即可看到，无需在面板操作
- **自动迁移** - 旧版 `config.json` 中的 `prompt` 字段在首次启动时自动迁移到 `config/prompt/默认.md`，零感知升级

### 🔀 自定义规则转发
- **监听来源灵活配置** - 每条转发规则可设置多个监听来源（联系人或群聊）
- **全部来源模式** - 勾选"全部来源"后，所有已监听的私聊和群组均作为转发来源，无需逐一填写；全局监听（黑名单）模式下同样生效
- **三种触发类型**
  - **关键词转发** - 消息内容包含任意关键词时触发
  - **固定发送人转发** - 指定人发送的消息才转发
  - **无差别转发** - 所有接收到的消息均转发
- **多目标转发** - 每条规则可设置多个转发目标，逐一转发，每次转发间隔 1 秒
- **附带来源信息** - 可选择是否在转发时附带"来源窗口"和"发送人"信息
- **不影响原有功能** - 转发在普通 AI 回复处理完成后执行，已在监听列表中的来源无需重复添加

### 🧠 对话记忆
- **全窗口记忆存储** - 机器人运行时将所有收发消息按聊天窗口独立存档
- **AI 上下文携带** - 调用 AI 时自动带入最近 N 条历史消息，实现连续对话
- **群聊区分发送人** - 群聊历史消息格式为 `[时间] 发送人: 内容`，AI 可准确识别不同人的发言
- **灵活配置** - 最大存储条数、AI 带入条数均可单独配置
- **记忆管理面板** - 在 Web 面板中可视化查看/删除各窗口的记忆记录，气泡式消息展示

### 🎯 多 AI 平台支持
- **DusAPI** ⭐ 推荐 - 兼容 Claude、GPT 等全系模型，国内稳定低延迟，一个 Key 搞定所有需求
  - 官网：[dusapi.com](https://dusapi.com)
  - **自动重试**：梯度重试机制（2/4/8/16/32 秒），5 次失败后报错
- **OpenAI SDK** - 兼容所有 OpenAI 格式的 API（DeepSeek、通义千问等）
  - 支持流式和非流式输出
  - 支持思维链内容（reasoning_content）
  - 自动降级到 Responses API 备用方案
- **Dify** - 调用 Dify 对话工作流
- **Coze（扣子）** - 使用官方 cozepy SDK

### 🔄 双监听模式
- **白名单模式** - 精准监听指定用户和群组；每个用户可绑定专属 AI 接口和专属 Prompt
- **黑名单模式** - 全局监听所有消息，动态管理会话列表；全局共用一个 Prompt，接口使用全局默认配置

### 💬 智能消息处理
- **关键词回复** - 支持私聊和群聊关键词自动回复
- **AI 智能回复** - 接入多种 AI 平台，提供智能对话
- **超长文本分段** - 自动将超过 2000 字的消息分段发送
- **随机延时** - 模拟人工回复节奏，延迟范围可在面板自定义（默认 1~5 秒，最大 600 秒，可关闭）
- **消息去重** - 防止重复处理同一条消息

### 👥 群聊功能
- **群新人欢迎语** - 自动检测新成员并发送欢迎消息
- **@ 回复模式** - 支持仅被 @ 时才回复
- **群关键词回复** - 不受 @ 限制的关键词回复
- **欢迎概率配置** - 可设置欢迎语触发概率
- **群组专属 AI 接口** - 每个监听群聊可单独绑定不同的 AI 接口
- **群组专属 Prompt** - 每个群聊可单独绑定不同的 Prompt，与接口独立配置

### 🤝 新好友管理
- **自动通过好友请求** - 批量处理新好友申请
- **自动打招呼** - 通过后自动发送欢迎消息，支持发送图片（填写图片绝对路径即可）
- **智能备注** - 自动设置备注（昵称_机器人备注）

### ⏰ 定时任务
- **自定义定时消息** - 像手机闹钟一样完全自定义定时
  - 单次发送 - 指定日期时间发送一次
  - 每天发送 - 每天固定时间发送
  - 每周发送 - 选择星期几发送
  - 每月发送 - 选择每月几号发送
  - 自定义日期 - 指定多个日期发送
- **多目标群发** - 每个定时任务支持配置多个发送目标，同一批消息依次发给每个目标
- **支持发送图片** - 消息内容填写图片绝对路径即可自动发送图片
- **独立开关** - 每条定时任务可单独启用/禁用
- **定时启停** - 设置机器人每日自动启动和停止时间

### 🌸 朋友圈功能

#### 随机点赞（活跃账号）
- **自动随机点赞** - 在设定的随机时间间隔内自动打开朋友圈，对当前第一条朋友圈点赞后关闭
- **灵活间隔配置** - 最小 1 分钟、最大 1440 分钟（24 小时），每次执行后重新随机生成下一次间隔
- **拟人化操作** - 每个动作之间有 1~5 秒随机延时，模拟真实用户行为

#### 随机定时发布朋友圈
- **时间窗口随机发布** - 设定起止时间（如 09:00~13:00），机器人在窗口内随机挑选时刻发布，避免固定规律被识别
- **三种周期模式**：每天 / 每周随机抽 N 天 / 每月随机抽 N 天
- **内容与隐私** - 支持图文混发、三级隐私控制

#### 定时发送朋友圈
- **全自动定时发圈** - 与定时消息完全相同的时间控制自由度（每天/每周/每月/单次/自定义日期）
- **图文混发** - 支持纯文字、纯图片（最多9张）、图文混合
- **三级隐私控制** - 公开 / 白名单 / 黑名单

### 💬 拆分多条回复
- **仿真人发送节奏** - 开启后 AI 可自主决定是否将回复拆分为多条消息，每条之间加入发送延迟，避免一大段文字的机械感
- **AI 自主决策** - 不强制拆分，由模型根据内容自行判断是否拆分及条数，仅约束单条最大字数和最多条数
- **私聊 / 群聊独立配置** - 私聊和群聊各有独立的开关、最大字数、最多条数设置
- **群聊 @ 策略** - 群聊模式下首条消息 @ 发言人，后续条不重复 @
- **容错设计** - AI 未遵守格式时（无分隔符）整段正常发出；超长单条走现有 2000 字分段逻辑
- **仅适用于支持自定义 Prompt 的接口** - 推荐 DusAPI；Coze / Dify 等工作流接口在平台侧已固化逻辑，可能无效

### 🔧 接口错误自定义固定回复
- **可配置错误回复** - 调用 AI 接口失败时，机器人发送的回复内容可在面板自定义，默认为"在忙，我稍后回复您"
- **统一兜底** - 私聊和群聊的所有接口失败场景（API 报错、超时、空响应等）均使用同一条配置的固定回复

### 🖼️ 图片识别
- **私聊 & 群组独立开关** - 私聊和群组各有一个图片识别总开关，互不影响
- **接口自由选择** - 开启后可从已配置的接口中选择用哪个接口做识别
- **直接图片消息** - 用户直接发送图片，机器人自动下载并调用多模态接口描述图片内容后回复
- **引用图片消息** - 用户引用带图片的消息，自动提取图片路径与文字内容，一并传给识别接口处理
- **识别关闭时零开销** - 关闭开关后不仅不回复，连图片下载也跳过，节省资源
- **须使用 DusAPI** - 图片识别需使用支持视觉的模型（如 claude-sonnet-4-6、gpt-5 系列），通过 [DusAPI](https://dusapi.com) 调用

### 📂 图片路径快速选择
- 新好友打招呼消息、定时消息内容、定时朋友圈图片三处均支持 **📁 选择图片** 按钮
- 点击后弹出系统原生文件选择框，选中图片后自动将完整本地路径填入输入框

### 🛠️ 管理命令系统（50+ 条）
通过WX消息发送命令，实时管理机器人。发送 `/指令` 获取分类目录，再发送对应分类指令查看详情：
- **系统状态**：运行状态、接口测试、版本、配置热重载
- **用户管理**：添加/删除/查看监听用户
- **群组管理**：添加/删除群、开关群机器人、欢迎语管理
- **Prompt 管理**：查看 Prompt 列表、查看内容、切换默认 Prompt、修改内容
- **关键词**：私聊/群聊关键词开关、@触发模式开关
- **对话记忆**：开关记忆、清除单用户/群/全部记忆
- **回复延迟**：开关延迟
- **图片识别**：查看私聊/群聊识别状态及接口
- **拆分多条回复**：查看配置、私聊/群聊独立开关
- **新好友**：查看自动通过和自动回复状态
- **接口管理**：查看接口列表、切换接口、查看/修改错误固定回复

### 🌐 Web 管理界面
- **状态面板** - 首页实时展示运行状态、消息统计、在线时长等关键指标，5 秒自动刷新
- **Prompt 管理** - 左侧列表 + 右侧编辑器两栏布局，支持新建/编辑/删除 Prompt；也可直接在 `config/prompt/` 放文件后刷新导入
- **记忆管理** - 三栏式记忆查看器（wx号→窗口→消息气泡），支持删除
- **全新 UI** - 侧边栏导航 + 分类标签页，配置一目了然
- **用户认证** - 账密从代码分离到 `admin.json`，修改无需改代码
- **实时日志** - 底部可折叠日志面板，支持级别筛选（INFO/SUCCESS/WARNING/ERROR）
- **配置管理** - 在线修改所有配置，保存即生效
- **自动检查更新** - 页面加载时自动检查新版本，有更新时置顶显示，每 6 小时自动重检
- **开发者广播通知** - 检查更新时同步拉取开发者通知，有内容时在页面顶部显示公告卡片

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
| **图片识别** | ✅ 原生支持，填 Key 即用 | ⚠️ 需自行适配多模态格式 |

👉 前往 [dusapi.com](https://dusapi.com) 注册获取 Key，支持 Claude Opus 4.6、Claude Sonnet 4.6、GPT-5、GPT-5 Pro 等主流模型。**图片识别功能也只需一个 Key，无需任何额外配置，开启开关即可直接使用，非常方便。**

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
    "admin": "文件传输助手",
    "AllListen_switch": false,
    "listen_list": ["用户1", "用户2"],
    "group": ["群聊1", "群聊2"],
    "group_api_map": {
        "群聊1": 0,
        "群聊2": 1
    },
    "group_prompt_map": {
        "群聊1": "客服助手",
        "群聊2": "销售助手"
    },
    "chat_prompt_map": {
        "张三": "客服助手"
    },
    "chat_api_map": {
        "张三": 1
    },
    "default_prompt": "默认",
    "group_switch": true,
    "group_reply_at": true,
    "group_welcome": true,
    "group_welcome_random": 1.0,
    "group_welcome_msg": "欢迎新朋友！",
    "new_friend_switch": true,
    "new_friend_reply_switch": false,
    "new_friend_msg": ["你好，我是机器人", "C:\\图片\\welcome.png"],
    "chat_keyword_switch": true,
    "group_keyword_switch": true,
    "group_keyword_at_only": false,
    "keyword_dict": {
        "关键词1": "回复内容1",
        "关键词2": "回复内容2"
    },
    "custom_forward_switch": false,
    "custom_forward_list": [
        {
            "id": "abc123",
            "sources": ["群聊1", "张三"],
            "type": "keyword",
            "keywords": ["重要", "紧急"],
            "senders": [],
            "targets": ["李四", "群聊2"],
            "forward_with_source": true
        }
    ],
    "scheduled_msg_switch": true,
    "scheduled_msg_list": [
        {
            "id": "abc123",
            "enabled": true,
            "targets": ["用户昵称", "群聊名称"],
            "time": "08:00",
            "repeat_type": "weekly",
            "weekdays": [1, 3, 5],
            "dates": [],
            "msgs": ["早安！", "C:\\图片\\morning.png"]
        }
    ],
    "scheduled_moments_switch": false,
    "scheduled_moments_list": [],
    "moments_like_switch": false,
    "moments_like_min": 60,
    "moments_like_max": 120,
    "random_moments_switch": false,
    "random_moments_list": [],
    "everyday_start_stop_bot_switch": false,
    "everyday_start_bot_time": "08:00",
    "everyday_stop_bot_time": "23:00",
    "memory_switch": true,
    "memory_max_count": 500,
    "memory_context_count": 100,
    "reply_delay_switch": true,
    "reply_delay_min": 1,
    "reply_delay_max": 5,
    "chat_image_recognition_switch": false,
    "chat_image_recognition_api": 0,
    "group_image_recognition_switch": false,
    "group_image_recognition_api": 0,
    "api_error_reply": "在忙，我稍后回复您",
    "chat_split_reply_switch": false,
    "chat_split_max_chars": 100,
    "chat_split_max_count": 4,
    "group_split_reply_switch": false,
    "group_split_max_chars": 100,
    "group_split_max_count": 4
}
```

> ⚠️ **注意**：旧版本中 `config.json` 里的 `prompt` 字段已迁移到 `config/prompt/默认.md` 文件，首次运行新版本会自动迁移，无需手动操作。

### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `api_configs` | array | — | AI 接口配置列表，每项含 `sdk`/`key`/`url`/`model` |
| `api_index` | integer | `0` | 当前使用的接口索引（0-based） |
| `admin` | string | `"文件传输助手"` | 管理员昵称，可发送管理命令 |
| `AllListen_switch` | boolean | `false` | `false`=白名单模式，`true`=黑名单（全局）模式 |
| `listen_list` | array | `[]` | 白名单/黑名单用户列表 |
| `group` | array | `[]` | 监听的群聊列表 |
| `group_api_map` | object | `{}` | 群组专属接口映射，格式 `{"群名": 接口索引}`；未配置的群使用默认接口 |
| `group_prompt_map` | object | `{}` | 群组专属 Prompt 映射，格式 `{"群名": "Prompt文件名"}`；未配置的群使用 `default_prompt` |
| `chat_prompt_map` | object | `{}` | 私聊白名单用户专属 Prompt 映射，格式 `{"用户昵称": "Prompt文件名"}` |
| `chat_api_map` | object | `{}` | 私聊白名单用户专属接口映射，格式 `{"用户昵称": 接口索引}` |
| `default_prompt` | string | `"默认"` | 全局默认 Prompt 文件名（不含 `.md`），对应 `config/prompt/{名称}.md` |
| `group_switch` | boolean | `false` | 群机器人总开关 |
| `group_reply_at` | boolean | `false` | 是否仅在被 @ 时回复群消息 |
| `group_welcome` | boolean | `false` | 是否开启群新人欢迎语 |
| `group_welcome_random` | float | `1.0` | 欢迎语触发概率（0.0-1.0） |
| `group_welcome_msg` | string | — | 群新人欢迎语内容 |
| `new_friend_switch` | boolean | `false` | 是否自动通过新好友请求 |
| `new_friend_reply_switch` | boolean | `false` | 通过新好友后是否自动打招呼 |
| `new_friend_msg` | array | `[]` | 打招呼消息列表，支持文字或图片绝对路径 |
| `chat_keyword_switch` | boolean | `false` | 是否开启私聊关键词回复 |
| `group_keyword_switch` | boolean | `false` | 是否开启群聊关键词回复 |
| `group_keyword_at_only` | boolean | `false` | 群聊关键词回复是否仅在被 @ 时触发 |
| `keyword_dict` | object | `{}` | 关键词→回复内容映射 |
| `custom_forward_switch` | boolean | `false` | 自定义规则转发总开关 |
| `custom_forward_list` | array | `[]` | 自定义转发规则列表，详见下方说明 |
| `scheduled_msg_switch` | boolean | `false` | 是否开启定时消息 |
| `scheduled_msg_list` | array | `[]` | 定时消息任务列表，详见下方说明 |
| `scheduled_moments_switch` | boolean | `false` | 是否开启定时朋友圈 |
| `scheduled_moments_list` | array | `[]` | 定时朋友圈任务列表 |
| `moments_like_switch` | boolean | `false` | 是否开启随机朋友圈点赞 |
| `moments_like_min` | integer | `60` | 随机点赞最小间隔（分钟，1~1440） |
| `moments_like_max` | integer | `120` | 随机点赞最大间隔（分钟，≥min） |
| `random_moments_switch` | boolean | `false` | 是否开启随机定时朋友圈 |
| `random_moments_list` | array | `[]` | 随机定时朋友圈任务列表 |
| `everyday_start_stop_bot_switch` | boolean | `false` | 是否开启每日定时启停机器人 |
| `everyday_start_bot_time` | string | `"08:00"` | 每日自动启动时间（格式 `HH:MM`） |
| `everyday_stop_bot_time` | string | `"23:00"` | 每日自动停止时间（格式 `HH:MM`） |
| `memory_switch` | boolean | `true` | 是否开启对话记忆 |
| `memory_max_count` | integer | `500` | 单窗口最多存储的消息条数 |
| `memory_context_count` | integer | `100` | AI 请求时带入的历史消息条数 |
| `reply_delay_switch` | boolean | `true` | 是否启用发送延迟（模拟人工操作） |
| `reply_delay_min` | integer | `1` | 发送延迟最小秒数（1~600） |
| `reply_delay_max` | integer | `5` | 发送延迟最大秒数（1~600） |
| `chat_image_recognition_switch` | boolean | `false` | 是否开启私聊图片识别 |
| `chat_image_recognition_api` | integer | `0` | 私聊图片识别使用的接口索引（须选择支持视觉的模型） |
| `group_image_recognition_switch` | boolean | `false` | 是否开启群组图片识别 |
| `group_image_recognition_api` | integer | `0` | 群组图片识别使用的接口索引（须选择支持视觉的模型） |
| `api_error_reply` | string | `"在忙，我稍后回复您"` | 调用 AI 接口失败时发送的固定回复内容 |
| `chat_split_reply_switch` | boolean | `false` | 是否开启私聊拆分多条回复 |
| `chat_split_max_chars` | integer | `100` | 私聊拆分回复单条最大字数 |
| `chat_split_max_count` | integer | `4` | 私聊拆分回复最多条数 |
| `group_split_reply_switch` | boolean | `false` | 是否开启群聊拆分多条回复 |
| `group_split_max_chars` | integer | `100` | 群聊拆分回复单条最大字数 |
| `group_split_max_count` | integer | `4` | 群聊拆分回复最多条数 |

### Prompt 文件说明

Prompt 存储于 `config/prompt/` 文件夹，每个 `.md` 文件即一份 Prompt，文件名即 Prompt 名称。

```
config/prompt/
├── 默认.md          ← 全局默认 Prompt，首次运行自动创建
├── 客服助手.md
└── 销售助手.md
```

**使用方式**：
- 在面板「Prompt 管理」页编辑（左侧选择，右侧编辑内容，点保存）
- 或直接在文件夹中新建 `.md` 文件，保存配置后刷新面板即可看到
- 在「群组管理」「私聊监听」页的每个条目后方的下拉框中选择要绑定的 Prompt

**优先级**：`群组/用户专属 Prompt` > `default_prompt（全局默认）` > 空字符串

### 自定义转发规则（custom_forward_list）字段说明

每条转发规则对象包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 规则唯一 ID（自动生成） |
| `all_sources` | boolean | `true`=全部来源模式，所有已监听私聊和群组均作为来源；`false`=手动指定来源 |
| `sources` | array | 手动指定的监听来源列表（`all_sources=false` 时生效），支持多个联系人昵称或群聊名称 |
| `type` | string | 触发类型：`keyword`=关键词触发 / `all`=无差别转发 / `sender`=固定发送人触发 |
| `keywords` | array | `type=keyword` 时使用，消息内容包含任意一个关键词即触发 |
| `senders` | array | `type=sender` 时使用，消息发送人匹配时触发 |
| `targets` | array | 转发目标列表，支持多个联系人昵称或群聊名称，每次转发间隔 1 秒 |
| `forward_with_source` | boolean | 是否在转发时附带来源信息（"来源窗口：xxx，发送人：xxx"） |

### 定时任务（scheduled_msg_list）字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 任务唯一 ID（自动生成） |
| `enabled` | boolean | 是否启用该任务 |
| `targets` | array | 发送目标列表，支持多个用户/群聊名称（群发） |
| `time` | string | 发送时间，格式 `HH:MM` |
| `repeat_type` | string | 重复类型：`once`/`daily`/`weekly`/`monthly`/`custom` |
| `weekdays` | array | `weekly` 时使用，填写星期几（1=周一…7=周日） |
| `dates` | array | `monthly` 时填每月几号；`once`/`custom` 时填日期字符串（如 `"2026-03-20"`） |
| `msgs` | array | 消息内容列表，支持文字或图片绝对路径（自动识别） |

### 定时朋友圈任务（scheduled_moments_list）字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 任务唯一 ID（自动生成） |
| `enabled` | boolean | 是否启用该任务 |
| `time` | string | 发布时间，格式 `HH:MM` |
| `repeat_type` | string | 重复类型：`once`/`daily`/`weekly`/`monthly`/`custom` |
| `weekdays` | array | `weekly` 时使用，填写星期几（1=周一…7=周日） |
| `dates` | array | `monthly` 时填每月几号；`once`/`custom` 时填日期字符串 |
| `text` | string | 朋友圈文字内容，可为空（文字和图片至少有一项） |
| `images` | array | 本地图片绝对路径列表，最多 9 张，可为空 |
| `privacy` | string | 隐私设置：`public`=公开 / `whitelist`=白名单 / `blacklist`=黑名单 |
| `tags` | array | 隐私标签列表，`privacy` 非 `public` 时生效 |

### 随机定时朋友圈任务（random_moments_list）字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 任务唯一 ID（自动生成） |
| `enabled` | boolean | 是否启用该任务 |
| `time_start` | string | 时间窗口开始，格式 `HH:MM` |
| `time_end` | string | 时间窗口结束，格式 `HH:MM` |
| `repeat_type` | string | `daily`=每天 / `weekly`=每周 / `monthly`=每月 |
| `random_days_count` | integer | 每周/每月随机抽取的发送天数（`weekly` 时 1~7；`monthly` 时 1~本月天数） |
| `text` | string | 朋友圈文字内容 |
| `images` | array | 本地图片绝对路径列表，最多 9 张 |
| `privacy` | string | 隐私设置：`public`/`whitelist`/`blacklist` |
| `tags` | array | 隐私标签列表 |

### admin.json 账密文件

位于 `config/admin.json`，首次启动自动创建，也可在面板「账号密码」页在线修改：

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

---

## 🎮 使用指南

### 1、Web 管理界面

1. 启动 Web 服务器：
```bash
python web_server.py
```

2. 浏览器访问：`http://localhost:10001`（端口自动选择 10001~11000 内第一个可用端口）

3. 默认账号：
   - 用户名：`admin`
   - 密码：`123456`
   - 账密保存在 `config/admin.json`，可在面板内修改

### 2、版本更新方法

> 更新不会丢失配置和记忆数据，保留 `config/` 和 `memory/` 文件夹即可。

- **源码版**：替换 `wxbot_core.py`、`web_server.py`、`templates/` 等源码文件即可
- **exe 版**：替换 exe 文件即可
- **更新前建议备份** `config/` 和 `memory/` 文件夹

### 3、管理命令列表

向管理员账号（`admin` 配置的微信昵称）发送命令来管理机器人。

**发送 `/指令` 获取分类目录，再发送分类指令查看该类详情：**

```
/指令           → 返回 11 个分类目录
/系统状态指令   → 状态、版本、接口测试、更新配置
/用户管理指令   → 添加/删除/查看监听用户
/群组管理指令   → 群机器人、欢迎语全套管理
/Prompt管理指令 → 列表、查看、切换、修改 Prompt
/关键词指令     → 私聊/群聊关键词开关、@触发模式
/记忆指令       → 开关记忆、清除单用户/群/全部记忆
/延迟指令       → 开关回复延迟
/图片识别指令   → 查看识别状态及接口
/拆分回复指令   → 查看配置、私聊/群聊独立开关
/新好友指令     → 查看自动通过及自动回复状态
/接口指令       → 接口列表、切换接口、错误回复查看/修改
```

**常用命令速查：**

```
/状态                          # 完整运行状态摘要（含所有功能开关状态）
/添加用户 用户昵称             # 添加白名单监听用户
/删除用户 用户昵称             # 移除白名单监听用户
/添加群 群名称                 # 添加群聊监听
/删除群 群名称                 # 移除群聊监听
/Prompt列表                    # 查看所有可用 Prompt
/切换Prompt 名称               # 切换默认 Prompt
/更改AI设定为 新的提示词内容   # 修改默认 Prompt 文件内容
/查看接口列表                  # 查看所有接口，▶ 标记当前使用
/选择接口 N                    # 切换至第 N 个接口
/清除用户记忆 用户昵称         # 清除指定用户的对话记忆
/清除全部记忆                  # 清空所有对话记忆
/开启私聊拆分回复              # 开启私聊多条发送
/关闭私聊拆分回复              # 关闭私聊多条发送
/开启群聊拆分回复              # 开启群聊多条发送
/关闭群聊拆分回复              # 关闭群聊多条发送
/查看错误回复                  # 查看接口失败时的固定回复
/设置错误回复 回复内容         # 修改接口失败时的固定回复
/更新配置                      # 热重载配置文件并重初始化监听
/当前版本                      # 查看版本号及更新说明
/接口测试 测试内容             # 测试当前 AI 接口是否正常
```

---

## 📁 项目结构

```
wxbot_plus/
├── wxbot_core.py              # 机器人核心（配置管理、AI接入、消息处理）
├── web_server.py              # Web 管理界面
├── logger.py                  # 日志模块
├── email_send.py              # 邮件发送模块
├── requirements.txt           # 依赖列表
├── config/                    # 配置文件目录（自动创建）
│   ├── config.json            # 机器人配置
│   ├── admin.json             # Web 管理账密
│   ├── email.txt              # 邮件告警配置
│   └── prompt/                # Prompt 文件目录（自动创建）
│       ├── 默认.md             # 默认 Prompt（自动创建）
│       └── *.md               # 其他自定义 Prompt
├── memory/                    # 对话记忆目录（自动创建）
│   └── {wx_id}/
│       └── {chat_name}/
│           └── {chat_name}_memory.json
├── panel_logs/                # 运行日志目录（自动创建）
├── templates/                 # Web 界面模板
│   ├── dashboard.html         # 管理面板
│   ├── login.html
│   └── static/                # 本地静态资源（Bootstrap Icons 本地化）
└── wxauto_logs/               # wxautox 日志目录
```

---

## 🚀 高级功能

### 多 Prompt 使用示例

**场景：不同群聊用不同 Prompt**

1. 在面板「Prompt 管理」页新建两份 Prompt：`客服助手.md` 和 `销售助手.md`
2. 在「群组管理」页，为「客服群」选择 `客服助手`，为「销售群」选择 `销售助手`
3. 保存配置，重启机器人即生效

**场景：白名单用户专属接口 + Prompt**

1. 在「私聊监听」页（白名单模式），每个用户后方会出现 Prompt 下拉和接口下拉
2. 为「VIP客户」绑定专属 Prompt 和高端接口（如 claude-opus）
3. 普通用户不绑定，自动使用全局默认配置

### 拆分多条回复使用示例

**场景：让机器人回复更像真人**

1. 在面板「私聊监听」或「群组管理」Tab，找到「启用拆分多条回复」开关并开启
2. 配置"单条最大字数"（如 80）和"最多发送条数"（如 4）
3. 保存配置，机器人下次回复时 AI 会自行决定是否拆分
4. 每条消息之间有发送延迟（使用已配置的回复延迟范围）

> ⚠️ 此功能通过在 Prompt 前注入格式指令实现，仅适用于支持自定义 Prompt 的接口（推荐 DusAPI）；Coze / Dify 等工作流接口可能无效。

### 自定义转发使用示例

**场景：重要群聊消息自动转发到私人账号**

1. 在面板「自定义转发」页添加规则
2. 监听来源：`重要客户群`
3. 转发类型：关键词转发，关键词填 `合同`、`付款`、`紧急`
4. 转发目标：自己的另一个账号
5. 勾选"附带来源信息"
6. 保存并启动机器人，当重要客户群有人发含这些关键词的消息时，自动转发给你

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
  {"time": "2024/01/01 12:00:00", "type": "text", "attr": "friend", "sender": "张三", "content": "你好"},
  {"time": "2024/01/01 12:00:05", "type": "text", "attr": "self", "sender": "我", "content": "你好！有什么可以帮你的？"}
]
```

**群聊记忆特点**：群聊历史消息传给 AI 时格式为 `[时间] 发送人: 内容`，AI 能准确区分不同群成员的发言。

**注意**：开启记忆后每次 AI 请求都会携带最近 N 条历史，会增加 token 消耗。推荐配置：`memory_max_count=500`，`memory_context_count=100`。

### 监听模式详解

#### 白名单模式（推荐）
- 仅监听配置文件中指定的用户和群组
- **每个用户可单独绑定 Prompt 和 AI 接口**
- 性能开销小，适合精准监听场景

#### 黑名单（全局）模式
- 监听所有消息，动态管理会话列表
- 全局共用一个 Prompt（`default_prompt` 指定），接口使用全局默认
- 自动移除 3 分钟无消息的会话

---

## ⚠️ 注意事项

1. **wxautox4 授权**
   - 本项目使用 wxautox4（Plus 版），需要购买授权
   - 购买地址：https://www.siverking.online/static/img/siver_wx.jpg

2. **WX版本**
   - 建议使用WX 4.1.8 版本

3. **API 配置**
   - 确保 API 密钥有效
   - 注意 API 调用频率限制

4. **记忆功能**
   - 开启记忆后每次 AI 请求携带历史，**会增加 token 消耗**
   - 记忆文件存储在 `memory/` 目录，勿提交到公共仓库

5. **安全建议**
   - 不要将 `config/` 和 `memory/` 目录提交到公共仓库（含 API Key 和聊天内容）
   - 修改 `config/admin.json` 中的默认密码（默认：`123456`）

6. **更新注意**
   - 更新程序时保留 `config/` 和 `memory/` 文件夹，原有配置和记忆完全复用
   - 更新前建议备份这两个文件夹

---

## 📄 许可证

本项目采用 Apache 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## 💬 联系方式

如有问题或建议，欢迎通过以下方式联系：

- 提交 Issue
- 联系作者：https://www.siverking.online/static/img/siver_wx.jpg

---

**⭐ 如果这个项目对你有帮助，请给个 Star 支持一下！**
