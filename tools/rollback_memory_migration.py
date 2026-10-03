# -*- coding: utf-8 -*-
"""回滚记忆目录迁移（memory_store.LegacyMigration 的反向操作）。

背景
----
新版本会把旧的记忆目录改成带哈希的存储标识，并把原目录搬进
    {记忆根目录}/_quarantine/{wx_id}/{原目录名}__migrated   （已迁移）
    {记忆根目录}/_quarantine/{wx_id}/{原目录名}__ambiguous  （归属不明，只是隔离）
每一步都记在台账 {记忆根目录}/_migration_log.json 里。

这个脚本按台账把目录改回原名，用于「升级后发现不对、要退回旧版本」的场景。

用法
----
    python tools/rollback_memory_migration.py --dry-run          # 只看看会做什么
    python tools/rollback_memory_migration.py                    # 真正回滚
    python tools/rollback_memory_migration.py --base D:\\...\\memory
    python tools/rollback_memory_migration.py --wx-id SiverKing  # 只回滚某个微信号

注意
----
- 回滚期间请先停止机器人（面板上点「停止」），避免边回滚边写入。
- 如果原来的目录名现在已经被新的记忆目录占用（同名冲突），脚本会跳过并报告，
  不会覆盖任何现有数据。
- 回滚不会删除 _quarantine/ 里的东西：搬回去 = 原目录被恢复，隔离区里就空了。
"""

import argparse
import io
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory_store import MIGRATION_LEDGER_NAME, QUARANTINE_DIR_NAME  # noqa: E402


def default_base():
    return os.path.join(os.path.abspath('.'), 'memory')


def load_ledger(base_path):
    path = os.path.join(base_path, MIGRATION_LEDGER_NAME)
    if not os.path.exists(path):
        print(f'找不到迁移台账：{path}')
        print('（说明没有做过迁移，或者台账被删掉了）')
        return None
    with io.open(path, encoding='utf-8') as f:
        return json.load(f)


def move_back(source, target, dry_run):
    """把隔离区里的目录搬回原位置；目标已存在则报告冲突。"""
    if not os.path.isdir(source):
        return 'missing', f'隔离目录不存在：{source}'
    if os.path.exists(target):
        return 'conflict', f'目标已存在，跳过：{target}'
    if dry_run:
        return 'rollback', f'[预演] {source}  ->  {target}'
    try:
        shutil.move(source, target)
    except OSError as e:
        return 'failed', f'移动失败 {source} -> {target}: {e}'
    return 'rollback', f'{source}  ->  {target}'


def main():
    parser = argparse.ArgumentParser(description='回滚记忆目录迁移')
    parser.add_argument('--base', default=default_base(), help='记忆根目录（默认 ./memory）')
    parser.add_argument('--wx-id', default='', help='只回滚指定微信号')
    parser.add_argument('--dry-run', action='store_true', help='只打印将要执行的操作')
    args = parser.parse_args()

    base_path = os.path.abspath(args.base)
    print(f'记忆根目录：{base_path}')
    ledger = load_ledger(base_path)
    if ledger is None:
        return 1

    entries = ledger.get('entries', [])
    if not entries:
        print('台账里没有记录，无需回滚。')
        return 0

    stats = {'rollback': 0, 'conflict': 0, 'missing': 0, 'failed': 0, 'skipped': 0}
    planned = []
    for entry in entries:
        wx_id = entry.get('wx_id') or ''
        legacy_name = entry.get('legacy_name') or ''
        status = entry.get('status') or ''
        if entry.get('rolled_back'):
            stats['skipped'] += 1
            continue
        if args.wx_id and wx_id != args.wx_id:
            stats['skipped'] += 1
            continue
        if status not in ('migrated', 'quarantined'):
            print(f'跳过（非终态 {status}）：{wx_id}/{legacy_name}')
            stats['skipped'] += 1
            continue

        quarantine_dir = entry.get('quarantine_dir') or ''
        if not quarantine_dir:
            # 兼容旧台账：按约定推导隔离路径
            suffix = '__migrated' if status == 'migrated' else '__ambiguous'
            quarantine_dir = os.path.join(
                base_path, QUARANTINE_DIR_NAME, wx_id, f'{legacy_name}{suffix}')

        target_dir = os.path.join(base_path, wx_id, legacy_name)
        # 迁移动作：若新目录已不存在（例如已被删除），说明数据仍在隔离区；
        # 恢复原目录是安全的（不会覆盖任何东西）。若新目录仍在，则会把数据
        # 复制回旧位置 —— 这正是"回滚到旧版本"想要的，但需要用户确认。
        if status == 'migrated' and os.path.isdir(entry.get('target_dir') or ''):
            print(f'注意：{wx_id}/{legacy_name} 的新目录仍存在，'
                  f'回滚后会同时存在新旧两份数据：{entry.get("target_dir")}')

        result, message = move_back(quarantine_dir, target_dir, args.dry_run)
        stats[result] += 1
        print(f'[{result}] {message}')
        if result == 'rollback' and not args.dry_run:
            entry['rolled_back'] = True
            entry['rolled_back_to'] = target_dir
            planned.append(entry)

    if planned:
        ledger_path = os.path.join(base_path, MIGRATION_LEDGER_NAME)
        tmp_path = ledger_path + '.rollback.tmp'
        with io.open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, ledger_path)
        print(f'台账已更新：{ledger_path}')

    print()
    print('统计：', ', '.join(f'{k}={v}' for k, v in stats.items() if v))
    if args.dry_run:
        print('（预演模式，没有改动任何文件；去掉 --dry-run 才会真正回滚）')
    if stats['conflict'] or stats['failed']:
        print('有冲突或失败项，请按上面的提示手动处理。')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
