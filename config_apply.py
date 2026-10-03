# -*- coding: utf-8 -*-
"""config_apply.py —— 「配置什么时候生效」的唯一约定。

背景
----
面板保存配置时，用户看到的提示曾经只有"已保存"和"已应用"两种。但机器人进程里
真正发生的事情分三种，混在一起就会出现"面板说生效了、实际没生效"：

1. **立即生效**（hot）
   机器人每个消息处理流程都从 ``self.config.xxx`` 属性现读，``refresh_config()``
   把磁盘新值同步到属性即可，保存后马上生效。
   例：Prompt、关键词回复、回复延迟、记忆开关、群聊只监听开关（group_listen_only）、
       随机定时、多条消息合并回复（``merge_reply_*``，主循环每轮现读配置）等。

2. **立即生效，但必须重建默认 API 客户端**（api_rebuild）
   ``WXBot.api`` 是启动时按 ``api_sdk`` 实例化的对象；只刷新属性的话，
   换了 SDK 类型（OpenAI ↔ Dify ↔ Coze ↔ DusAPI）对象还是旧的那一个。
   ``WXBot.apply_config()`` 会重建默认客户端并清空群组专属接口缓存。
   例：``api_configs``、``api_index``。

3. **必须重启**（restart）
   监听注册（``init_wx_listeners``）与定时任务注册都发生在启动初始化阶段，
   运行中改这些只刷新属性，wxautox 的监听器与调度器都不知道 —— 等于没生效。
   面板必须如实提示"需重启载入新配置"，不能笼统地说"已应用"。
   例：管理员账号 / 监听名单 / 全局监听模式 / 群列表 / 群机器人开关（group_switch）/
       特殊会话名单 / 自定义转发 / 定时消息 / 定时朋友圈。

未列出的字段默认按"立即生效"处理：新增字段在 ``update_global_config()`` 里被
同步到属性后即可生效，与旧行为一致；如果新字段其实需要重启，必须补进
``RESTART_REASONS``，否则面板会误报"已生效"。

本模块零依赖，面板（web_server）、机器人（wxbot_core）与验收脚本共用同一份分类，
不允许任何一方再自己维护一份"需要重启的字段"列表。
"""

from __future__ import annotations

APPLY_HOT = 'hot'                    # 立即生效
APPLY_API_REBUILD = 'api_rebuild'    # 立即生效，但需重建默认 API 客户端
APPLY_RESTART = 'restart'            # 必须重启才生效

# ------------------------------------------------------------
# 必须重启：字段 → 给用户看的中文名
# ------------------------------------------------------------
RESTART_REASONS = {
    # --- 监听注册：只在 init_wx_listeners() 里做 ---
    # admin 尤其容易误判：它既是"谁是管理员"的判定依据（消息处理时现读），
    # 又决定"给谁注册监听"（只在启动时注册一次）。运行中改它，新管理员在
    # 白名单模式下根本没被监听，命令不生效；旧管理员仍被监听却不再被当管理员，
    # 消息会掉进普通好友 AI 回复。所以必须归为"需重启"。
    'admin': '管理员账号',
    'listen_list': '监听名单',
    'AllListen_switch': '全局监听模式',
    'group': '群列表',
    'group_switch': '群机器人开关',
    'special_session_name': '特殊会话名单',
    'custom_forward_switch': '自定义转发开关',
    'custom_forward_list': '自定义转发规则',
    # --- 定时任务注册：只在 init_wx_listeners() 里注册到本实例调度器 ---
    'scheduled_msg_switch': '定时消息开关',
    'scheduled_msg_list': '定时消息任务',
    'scheduled_moments_switch': '定时朋友圈开关',
    'scheduled_moments_list': '定时朋友圈任务',
}

# ------------------------------------------------------------
# 立即生效，但需重建默认 API 客户端
# ------------------------------------------------------------
API_REBUILD_REASONS = {
    'api_configs': '接口列表',
    'api_index': '默认接口',
}

RESTART_FIELDS = frozenset(RESTART_REASONS)
API_REBUILD_FIELDS = frozenset(API_REBUILD_REASONS)


def semantics(field):
    """单个字段的生效方式：``hot`` / ``api_rebuild`` / ``restart``。"""
    if field in RESTART_FIELDS:
        return APPLY_RESTART
    if field in API_REBUILD_FIELDS:
        return APPLY_API_REBUILD
    return APPLY_HOT


def label_of(field):
    """字段的中文名（用于面板提示）；没有登记时回退到字段名本身。"""
    return RESTART_REASONS.get(field) or API_REBUILD_REASONS.get(field) or field


def classify(fields):
    """把改动的字段分成三类，供 apply_config / 面板提示共用。

    :param fields: 本次真正发生变化的配置键（可迭代）
    :return: {'hot': [...], 'api_rebuild': [...], 'restart': [...]}（均已排序）
    """
    fields = set(fields or ())
    restart = fields & RESTART_FIELDS
    api_rebuild = fields & API_REBUILD_FIELDS
    hot = fields - restart - api_rebuild
    return {
        APPLY_HOT: sorted(hot),
        APPLY_API_REBUILD: sorted(api_rebuild),
        APPLY_RESTART: sorted(restart),
    }


def describe(fields):
    """把一组字段拼成中文串，例如「监听名单、定时消息任务」。"""
    labels = []
    for field in sorted(set(fields or ())):
        label = label_of(field)
        if label not in labels:
            labels.append(label)
    return '、'.join(labels)


def describe_soft(fields):
    """面向用户面板的描述：登记过的字段用中文名，未登记的热字段合并成「其他 N 项配置」。

    立即生效的字段是长尾（回复延迟、记忆、关键词…），没必要逐个登记中文名；
    给用户看的是"哪些部分生效了"，字段级明细由接口的 applied_fields 返回。
    """
    labels = []
    unknown = 0
    for field in sorted(set(fields or ())):
        label = RESTART_REASONS.get(field) or API_REBUILD_REASONS.get(field)
        if label:
            if label not in labels:
                labels.append(label)
        else:
            unknown += 1
    if unknown:
        labels.append(f'其他 {unknown} 项配置')
    return '、'.join(labels)


def needs_restart(fields):
    """这组改动里是否有"必须重启才生效"的字段。"""
    return bool(set(fields or ()) & RESTART_FIELDS)


def summary(changed_fields):
    """给面板用的完整说明。

    :return: dict(
        hot_fields / api_fields / restart_fields: 分类后的字段名列表,
        hot_labels / api_labels / restart_labels: 对应的中文串,
        needs_restart: bool,
        scope: 'none' | 'hot_only' | 'restart_only' | 'mixed'
    )
    """
    plan = classify(changed_fields)
    hot = plan[APPLY_HOT]
    api = plan[APPLY_API_REBUILD]
    restart = plan[APPLY_RESTART]
    if not (hot or api or restart):
        scope = 'none'
    elif restart and (hot or api):
        scope = 'mixed'
    elif restart:
        scope = 'restart_only'
    else:
        scope = 'hot_only'
    return {
        'hot_fields': hot,
        'api_fields': api,
        'restart_fields': restart,
        'hot_labels': describe(hot),
        'api_labels': describe(api),
        'restart_labels': describe(restart),
        'needs_restart': bool(restart),
        'scope': scope,
    }
