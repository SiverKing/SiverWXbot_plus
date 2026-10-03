# -*- coding: utf-8 -*-
"""升级前预演：把 memory/ 复制到临时目录，跑一遍迁移并打印每个窗口的去向。

用法：
    python tools/preview_memory_migration.py
    python tools/preview_memory_migration.py --base D:\\path\\to\\memory

只读预演：不动真实 memory/ 目录，只操作临时副本。
真正迁移是机器人/面板第一次访问某个窗口时按需进行的。
"""

import argparse
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory_store import (  # noqa: E402
    LegacyMigration,
    MemoryManager,
    is_internal_dir_name,
    read_original_name,
    scan_wx_dir,
)


def main():
    parser = argparse.ArgumentParser(description='预演记忆目录迁移')
    parser.add_argument('--base', default=os.path.join(os.path.abspath('.'), 'memory'),
                        help='记忆根目录（默认 ./memory）')
    args = parser.parse_args()

    src = os.path.abspath(args.base)
    if not os.path.isdir(src):
        print(f'记忆根目录不存在：{src}')
        return 1

    tmp = tempfile.mkdtemp(prefix='migration_preview_')
    dst = os.path.join(tmp, 'memory')
    shutil.copytree(src, dst)
    print(f'真实目录：{src}（不会被改动）')
    print(f'预演副本：{dst}')

    wx_ids = [d for d in sorted(os.listdir(dst))
              if os.path.isdir(os.path.join(dst, d)) and not is_internal_dir_name(d)]

    print()
    print('=' * 78)
    print('迁移前：每个旧目录会被怎么处理')
    print('=' * 78)
    for wx_id in wx_ids:
        found = scan_wx_dir(os.path.join(dst, wx_id))
        print(f'\n[{wx_id}]  迁移 {len(found["migrate"])} 个 / '
              f'隔离 {len(found["quarantine"])} 个 / 已是新格式 {len(found["keep"])} 个')
        for name, (key, owner) in sorted(found['migrate'].items()):
            print(f'  迁移   {name!r:28} -> {key[:44]}…（归属：{owner}）')
        for name, reason in sorted(found['quarantine'].items()):
            print(f'  隔离   {name!r:28} 原因：{reason}')

    print()
    print('=' * 78)
    print('在副本上执行迁移')
    print('=' * 78)
    migration = LegacyMigration(dst)
    items = migration.scan()
    print('待处理条目：', len(items))
    print('结果：', migration.apply(items))

    print()
    print('=' * 78)
    print('迁移后：记忆是否还能按原始窗口名读回（条数为 0 的项需要人工确认）')
    print('=' * 78)
    for wx_id in wx_ids:
        manager = MemoryManager(wx_id, dst)
        print(f'\n[{wx_id}]')
        for key in manager.list_storage_keys():
            chat_dir = os.path.join(dst, wx_id, key)
            original = read_original_name(chat_dir, key)
            count = len(manager.get_messages(original, 10000))
            print(f'   {key[:40]}… 原始名={original!r} 可读回消息数={count}')
        quarantine_wx = os.path.join(dst, '_quarantine', wx_id)
        if os.path.isdir(quarantine_wx):
            print(f'   隔离区：{sorted(os.listdir(quarantine_wx))}')

    print()
    print(f'预演结束。确认无误后删除副本即可：{tmp}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
