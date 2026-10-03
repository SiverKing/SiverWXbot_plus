"""config.json 的默认值、规范化与迁移 —— 单一来源。

零第三方依赖、零 Flask 依赖（wxbot_core 必须能独立运行）。

统一掉原来的三处默认值来源：
  - web_server.main() 建文件时的 default_config（96 个键）
  - wxbot_core.create_new_config_file() 的 base_config（96 个键，与上一处是两份重复拷贝）
  - web_server.dashboard() 给老配置补键的 76 个 setdefault
现在三者合并为本文件的 DEFAULT_CONFIG（98 个键），老配置补键由 apply_defaults() 统一完成。

迁移原则
--------
1. **新字段优先**：新旧字段共存时以新字段为准，旧字段只做清理。
   原面板实现是"只要发现旧字段就无条件重建新字段"，会覆盖用户已有配置
   且不幂等；原核心实现是"新字段不存在才迁移"。
   统一为：api_configs 已存在 -> 只删旧字段，不重建。
2. **幂等**：同一份配置连续跑两次 migrate()，结果必须完全一致。
3. **未知字段一律保留**：只增删自己认识的键，其余原样带过。
"""

from __future__ import annotations

import json

# 旧版 SiverPanel 域名（迁移时替换为新域名）
LEGACY_PANEL_BASE_URL = 'https://wxbot-panel.siverking.online'
LEGACY_PANEL_WS_URL = 'wss://wxbot-panel.siverking.online/relay/ws'

# ============================================================
# 默认值（新建配置文件 / 给老配置补键时使用）
# ============================================================
DEFAULT_CONFIG = {
    'api_configs': [{'sdk': '', 'key': '', 'url': '', 'model': '', 'fallback_api_index': -1}, {'sdk': '', 'key': '', 'url': '', 'model': '', 'fallback_api_index': -1}],
    'api_index': 0,
    # 注意：旧字段 "prompt" 故意不放在这里。
    # 它的归宿是 config/prompt/默认.md（由 init_prompt_dir / _migrate_prompt_from_config 迁移）。
    # 若把它写进 DEFAULT_CONFIG，apply_defaults 每次都会把它加回来、迁移逻辑再删掉，
    # 形成"每次保存都迁移一次"的循环（日志里会反复出现"已将旧 prompt 字段迁移…"）。
    'admin': '文件传输助手',
    'AllListen_switch': False,
    'AllListen_filter_mute': True,
    'chat_listen_only': False,
    'listen_list': [],
    'special_session_name': [],
    'group': [],
    'group_api_map': {},
    'group_switch': False,
    'group_listen_only': False,
    'group_reply_at': False,
    'group_reply_at_msg': True,
    'group_reply_quote': False,
    'group_welcome': False,
    'group_welcome_random': 1.0,
    'group_welcome_msg': '欢迎新朋友！请先查看群公告！',
    'new_friend_switch': False,
    'new_friend_reply_switch': False,
    'new_friend_msg': [],
    'new_friend_check_min': 60,
    'new_friend_check_max': 300,
    'new_friend_remark_use_nickname': True,
    'new_friend_remark_prefix': '',
    'new_friend_remark_prefix_timestamp': False,
    'new_friend_remark_suffix': '_机器人备注',
    'new_friend_remark_suffix_timestamp': False,
    'new_friend_tags': [],
    'chat_keyword_switch': False,
    'group_keyword_switch': False,
    'group_keyword_at_only': False,
    'keyword_reply_quote': False,
    'group_keyword_reply_at_msg': False,
    'keyword_dict': {},
    'custom_forward_switch': False,
    'custom_forward_list': [],
    'default_prompt': '默认',
    'chat_prompt_map': {},
    'chat_api_map': {},
    'chat_max_round_map': {},
    'group_prompt_map': {},
    'scheduled_msg_switch': False,
    'scheduled_msg_list': [],
    'random_msg_switch': False,
    'random_msg_list': [],
    'scheduled_moments_switch': False,
    'scheduled_moments_list': [],
    'moments_like_switch': False,
    'moments_like_min': 60,
    'moments_like_max': 120,
    'random_moments_switch': False,
    'random_moments_list': [],
    'everyday_start_stop_bot_switch': False,
    'everyday_start_bot_time': '08:00',
    'everyday_stop_bot_time': '23:00',
    'memory_switch': True,
    'memory_max_count': 3000,
    'memory_context_count': 1000,
    'reply_delay_switch': True,
    'reply_delay_min': 1,
    'reply_delay_max': 5,
    'clean_ai_reply_switch': True,
    'chat_image_recognition_switch': False,
    'chat_image_recognition_api': 0,
    'group_image_recognition_switch': False,
    'group_image_recognition_api': 0,
    'api_error_reply': '在忙，我稍后回复您',
    'api_error_reply_once': False,
    'chat_max_round_switch': False,
    'chat_max_round_default': 99,
    'chat_max_round_reset_days': 0,
    'chat_max_round_reply': '',
    'chat_max_round_reply_once': False,
    'chat_split_reply_switch': False,
    'chat_split_max_chars': 100,
    'chat_split_max_count': 4,
    'group_split_reply_switch': False,
    'group_split_max_chars': 100,
    'group_split_max_count': 4,
    'merge_reply_switch': False,
    'merge_reply_window': 5,
    'merge_reply_max_count': 10,
    'siver_panel_enabled': False,
    'siver_panel_activation_code': '',
    'siver_panel_activation_code_applied_hash': '',
    'siver_panel_activation_code_failed_hash': '',
    'siver_panel_slug': '',
    'siver_panel_install_id': '',
    'siver_panel_machine_fingerprint': '',
    'siver_panel_device_id': '',
    'siver_panel_device_secret': '',
    'siver_panel_base_url': 'https://panel.siver.top',
    'siver_panel_ws_url': 'wss://panel.siver.top/relay/ws',
    'siver_panel_panel_url': '',
    'siver_panel_service_expire_at': '',
    'siver_panel_last_error_code': '',
    'siver_panel_last_error_message': '',
}


# ============================================================
# 规范化（类型校验）
# ============================================================


def _normalize_api_configs(api_configs):
    """规范化接口列表，并将非法备用接口索引统一为 -1。"""
    if not isinstance(api_configs, list):
        return []

    normalized = []
    for cfg in api_configs:
        normalized.append(cfg if isinstance(cfg, dict) else {})

    total = len(normalized)
    for index, cfg in enumerate(normalized):
        try:
            fallback_index = int(cfg.get("fallback_api_index", -1))
        except (TypeError, ValueError):
            fallback_index = -1
        if (
            fallback_index < 0
            or fallback_index >= total
            or fallback_index == index
        ):
            fallback_index = -1
        cfg["fallback_api_index"] = fallback_index
    return normalized


def _coerce_bool_fields(merged_config):
    boolean_fields = [
        'AllListen_switch',
        'AllListen_filter_mute',
        'chat_listen_only',
        'group_switch',
        'group_listen_only',
        'group_reply_at',
        'group_reply_at_msg',
        'group_reply_quote',
        'group_welcome',
        'new_friend_switch',
        'new_friend_reply_switch',
        'new_friend_remark_use_nickname',
        'new_friend_remark_prefix_timestamp',
        'new_friend_remark_suffix_timestamp',
        # —— 新增布尔字段 ——
        'chat_keyword_switch',
        'group_keyword_switch',
        'group_keyword_at_only',
        'keyword_reply_quote',
        'group_keyword_reply_at_msg',
        'scheduled_msg_switch',
        'random_msg_switch',                # 随机定时消息开关
        'scheduled_moments_switch',         # 定时朋友圈开关
        'moments_like_switch',              # 随机朋友圈点赞开关
        'random_moments_switch',            # 随机定时朋友圈开关
        'everyday_start_stop_bot_switch',   # 新增
        'memory_switch',                    # 记忆开关
        'reply_delay_switch',               # 发送延迟开关
        'clean_ai_reply_switch',            # AI 回复清洗开关
        'chat_image_recognition_switch',    # 私聊图片识别开关
        'group_image_recognition_switch',   # 群组图片识别开关
        'custom_forward_switch',            # 自定义转发总开关
        'chat_split_reply_switch',          # 私聊拆分多条回复开关
        'group_split_reply_switch',         # 群聊拆分多条回复开关
        'merge_reply_switch',               # 多条消息缓冲合并回复开关
        'siver_panel_enabled',
        'api_error_reply_once',             # API错误只回复一次
        'chat_max_round_switch',            # 单用户最大回复轮数限制开关
        'chat_max_round_reply_once',        # 超限后只回复一次
    ]
    for field in boolean_fields:
        if field in merged_config:
            v = merged_config[field]
            if isinstance(v, str):
                merged_config[field] = (v.lower() in ('on', 'true', '1'))
            else:
                merged_config[field] = bool(v)


def _coerce_list_fields(merged_config):
    list_fields = ['listen_list', 'special_session_name', 'group', 'new_friend_msg', 'new_friend_tags', 'scheduled_msg_list', 'random_msg_list', 'scheduled_moments_list', 'random_moments_list', 'custom_forward_list']
    for field in list_fields:
        if field in merged_config and not isinstance(merged_config[field], list):
            if isinstance(merged_config[field], str):
                merged_config[field] = [merged_config[field]] if merged_config[field] else []
            else:
                merged_config[field] = []
        if field in merged_config:
            merged_config[field] = [item for item in merged_config[field] if str(item).strip()]
    if 'special_session_name' in merged_config:
        merged_config['special_session_name'] = list(dict.fromkeys(
            str(item).strip() for item in merged_config['special_session_name'] if str(item).strip()
        ))


def _coerce_float_range(merged_config):
    # 仅当前需要 group_welcome_random，限定 [0.0, 1.0]
    if 'group_welcome_random' in merged_config:
        try:
            val = float(merged_config['group_welcome_random'])
            if val < 0.0: val = 0.0
            if val > 1.0: val = 1.0
            merged_config['group_welcome_random'] = val
        except (TypeError, ValueError):
            # 非法值直接回退默认。原实现会再读一次磁盘，使规范化结果依赖调用时机，
            # 也可能与调用方刚提交的值不一致。
            merged_config['group_welcome_random'] = 1.0


def _coerce_int_range_fields(merged_config):
    """对整数范围字段做类型校验和区间限制"""
    int_range_fields = {
        'new_friend_check_min': (60, 3600, 60),
        'new_friend_check_max': (60, 3600, 300),
        'chat_max_round_default': (1, 99999, 99),
        'chat_max_round_reset_days': (0, 365, 0),
        'merge_reply_window': (1, 300, 5),
        'merge_reply_max_count': (1, 100, 10),
    }
    for field, (lo, hi, default) in int_range_fields.items():
        if field in merged_config:
            try:
                val = int(merged_config[field])
                merged_config[field] = max(lo, min(hi, val))
            except (TypeError, ValueError):
                merged_config[field] = default
    # 保证 min <= max
    if 'new_friend_check_min' in merged_config and 'new_friend_check_max' in merged_config:
        if merged_config['new_friend_check_min'] > merged_config['new_friend_check_max']:
            merged_config['new_friend_check_max'] = merged_config['new_friend_check_min']


def _coerce_api_fields(merged_config):
    """校验接口列表及所有依赖接口下标的配置项。"""
    if 'api_configs' not in merged_config:
        return

    api_configs = merged_config.get('api_configs')
    if not isinstance(api_configs, list):
        api_configs = []
    merged_config['api_configs'] = _normalize_api_configs(api_configs)
    api_count = len(api_configs)

    for field in ('api_index', 'chat_image_recognition_api', 'group_image_recognition_api'):
        if field not in merged_config:
            continue
        try:
            value = int(merged_config[field])
        except (TypeError, ValueError):
            value = 0
        merged_config[field] = value if 0 <= value < api_count else 0


def _coerce_dict_fields(merged_config):
    # keyword_dict 支持：dict / JSON字符串 / list[{key, value}]
    if 'keyword_dict' in merged_config:
        kd = merged_config['keyword_dict']
        if isinstance(kd, dict):
            pass
        if isinstance(kd, str):
            try:
                obj = json.loads(kd)
                if isinstance(obj, dict):
                    merged_config['keyword_dict'] = obj
                    kd = obj
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
            kd = out
        # 其他情况回退空 dict
        if not isinstance(kd, dict):
            merged_config['keyword_dict'] = {}

    # group_api_map: 值必须为 int 接口索引，非法值自动过滤
    if 'group_api_map' in merged_config:
        gam = merged_config['group_api_map']
        if isinstance(gam, dict):
            clean = {}
            api_count = len(merged_config.get('api_configs', []))
            for k, v in gam.items():
                k = str(k).strip()
                try:
                    vi = int(v)
                    if k and 0 <= vi < api_count:
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
            api_count = len(merged_config.get('api_configs', []))
            for k, v in cam.items():
                k = str(k).strip()
                try:
                    vi = int(v)
                    if k and (vi == -1 or 0 <= vi < api_count):
                        clean[k] = vi
                except (ValueError, TypeError):
                    pass
            merged_config['chat_api_map'] = clean
        else:
            merged_config['chat_api_map'] = {}

    # chat_max_round_map: 白名单模式下私聊用户专属回复次数上限，范围 1~99999
    if 'chat_max_round_map' in merged_config:
        cmrm = merged_config['chat_max_round_map']
        if isinstance(cmrm, dict):
            clean = {}
            for k, v in cmrm.items():
                k = str(k).strip()
                try:
                    vi = int(v)
                    if k:
                        clean[k] = max(1, min(99999, vi))
                except (ValueError, TypeError):
                    pass
            merged_config['chat_max_round_map'] = clean
        else:
            merged_config['chat_max_round_map'] = {}

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

def normalize(config):
    """统一规范化：清掉旧 API 字段 + 6 类类型校验。

    这是 config.json 唯一的规范化入口，ConfigStore 落盘前会调用它。
    就地修改并返回传入的 dict。
    """
    # 已有新格式 api_configs 时，清掉旧版单接口字段
    if 'api_configs' in config:
        for _k in ('api_sdk', 'api_key', 'base_url', 'model1', 'model2', 'api_sdk_list'):
            config.pop(_k, None)

    # api_configs 必须是列表；不是列表时恢复成默认的两条空接口，
    # 与建文件时保持一致（否则面板上一个接口都渲染不出来）
    if not isinstance(config.get('api_configs'), list):
        config['api_configs'] = [dict(c) for c in DEFAULT_CONFIG['api_configs']]

    _coerce_bool_fields(config)
    _coerce_list_fields(config)
    _coerce_float_range(config)
    _coerce_int_range_fields(config)
    _coerce_api_fields(config)
    _coerce_dict_fields(config)
    return config


# ============================================================
# 迁移（旧字段 -> 新字段；必须幂等）
# ============================================================

def migrate(config):
    """把旧版配置就地迁移成当前格式，返回同一个 dict。

    幂等：连续执行两次结果一致；新旧字段共存时新字段优先。
    """
    # 旧版单接口字段 -> api_configs 列表
    # 新字段已存在时只清理旧字段、不重建，避免覆盖用户已配置的多接口
    if 'api_sdk' in config:
        if 'api_configs' not in config:
            config['api_configs'] = [
                {'sdk': config.get('api_sdk', ''), 'key': config.get('api_key', ''),
                 'url': config.get('base_url', ''), 'model': config.get('model1', ''),
                 'fallback_api_index': -1},
                {'sdk': config.get('api_sdk', ''), 'key': config.get('api_key', ''),
                 'url': config.get('base_url', ''), 'model': config.get('model2', ''),
                 'fallback_api_index': -1},
            ]
            config['api_index'] = 0
        for _k in ('api_sdk', 'api_key', 'base_url', 'model1', 'model2', 'api_sdk_list'):
            config.pop(_k, None)

    # 接口显示名变更：OpenAI SDK -> OpenAI API 格式兼容接口（只改显示名，不改行为）
    for _cfg in config.get('api_configs') or []:
        if isinstance(_cfg, dict) and _cfg.get('sdk') == 'OpenAI SDK':
            _cfg['sdk'] = 'OpenAI API 格式兼容接口'

    # 旧版定时消息 everyday_msg_dict -> scheduled_msg_list
    if not config.get('scheduled_msg_list') and config.get('everyday_msg_dict'):
        import uuid
        migrated = []
        for target, tasks in (config.get('everyday_msg_dict') or {}).items():
            for task in tasks or []:
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

    # 旧版定时消息目标 target(str) -> targets(list)
    for _task in config.get('scheduled_msg_list') or []:
        if isinstance(_task, dict) and 'targets' not in _task:
            _old = _task.pop('target', '')
            _task['targets'] = [_old] if _old else []

    # 旧版 SiverPanel 域名 -> 新域名
    if config.get('siver_panel_base_url') == LEGACY_PANEL_BASE_URL:
        config['siver_panel_base_url'] = 'https://panel.siver.top'
    if config.get('siver_panel_ws_url') == LEGACY_PANEL_WS_URL:
        config['siver_panel_ws_url'] = 'wss://panel.siver.top/relay/ws'

    return config


def apply_defaults(config):
    """给老配置补上缺失的键（已存在的键不动）。"""
    for key, value in DEFAULT_CONFIG.items():
        config.setdefault(key, value)
    return config


def prepare(config):
    """完整流水线：迁移 -> 补默认值 -> 规范化。"""
    return normalize(apply_defaults(migrate(config)))
