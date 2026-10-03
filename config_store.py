"""config.json 的统一读写入口。

设计要点
--------
1. 零第三方依赖、零 Flask 依赖 —— wxbot_core 必须能独立运行。
2. 「读 → 改 → 校验 → 写」是**一次受保护的操作**：同一路径全程持同一把锁，
   避免两个调用方各自读到旧值后先后覆盖对方。
   仅给"落盘那一下"加锁是不够的。
3. 对外暴露**内容版本号**（rev），供调用方做冲突检测。
   rev 是文件字节的 sha256 前 16 位：内容相同则版本相同，不会误报冲突。
4. 落盘为原子替换（同目录唯一临时文件 + os.replace + 有限重试）。

三个写入方都必须经过这里，不允许再各写一套：
  1. 面板 /save_config        -> web_server.save_config()
  2. 机器人 WXBotConfig.save_config()
  3. siver_panel._persist_config_updates()
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time

DEFAULT_INDENT = 4

# 同一路径共用一把锁：原子写与「读-改-写」事务必须排到同一条队列上，
# 否则事务持锁期间仍可能被一次裸写插队。
_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


class ConfigError(Exception):
    """配置读写相关错误的基类。"""


class ConfigReadError(ConfigError):
    """配置文件不存在、读不到，或不是合法的 JSON 对象。"""


class ConfigWriteError(ConfigError):
    """配置写盘失败。"""


class ConfigConflictError(ConfigError):
    """调用方持有的版本号已过期（期间被其他写入方改过）。"""

    def __init__(self, expected: str, actual: str):
        super().__init__(f'配置已被其他改动更新（期望版本 {expected}，实际 {actual}）')
        self.expected = expected
        self.actual = actual


def path_lock(path: str) -> threading.Lock:
    """取某个目标文件的锁（首次访问时创建，创建过程本身也加锁）。"""
    key = os.path.abspath(path)
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PATH_LOCKS[key] = lock
        return lock


def revision_of(raw: bytes) -> str:
    """内容版本号：文件字节的 sha256 前 16 位。"""
    return hashlib.sha256(raw).hexdigest()[:16]


def encode_json(data, indent: int = DEFAULT_INDENT) -> bytes:
    """把配置编码成落盘用的字节（与写盘内容完全一致）。"""
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    return text.encode('utf-8')


def write_json_atomic(path: str, data, indent: int = DEFAULT_INDENT) -> bytes:
    """原子落盘（自带路径锁），返回实际写入的字节（供调用方计算 rev）。

    ⚠ 调用方若已持有该路径的锁（例如 ConfigStore 的读-改-写事务），
    必须改用 _write_json_atomic_unlocked()，否则会自我死锁。
    """
    with path_lock(path):
        return _write_json_atomic_unlocked(path, data, indent=indent)


def _write_json_atomic_unlocked(path: str, data, indent: int = DEFAULT_INDENT) -> bytes:
    """原子落盘本体，**不加锁**，由调用方保证互斥。

    ⚠ 三处并发要点（均实测踩过）：
    1. 临时文件名必须唯一（mkstemp）。用固定的 path+".tmp" 时多个写入方会互踩：
       A 写 tmp、B 覆盖同名 tmp 并 replace、A 再 replace 抛 FileNotFoundError，
       且失败方向是反的（文件里是 B 的数据，却只有 A 报成功）。
    2. 同一目标的写入必须串行。即使临时名唯一，Windows 上并发 os.replace
       到同一目标仍会抛 PermissionError(WinError 5)：实测 12 线程 x 60 次
       并发写，720 次里有 278 次失败。
    3. os.replace 还要容忍"读方正打开着目标文件"（同样是 WinError 5），
       因此做有限次快速重试。
    """
    raw = encode_json(data, indent=indent)
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f'{os.path.basename(path)}.', suffix='.tmp', dir=directory
    )
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
        for _attempt in range(6):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if _attempt == 5:
                    raise
                time.sleep(0.03)
    finally:
        # 正常路径下 tmp 已被 replace 掉；异常时清理，避免残留临时文件
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return raw


class ConfigStore:
    """单个配置文件的读写入口。

    :param path:     配置文件路径
    :param defaults: 文件不存在时用于初始化的默认值
    :param normalize: 规范化函数，签名 (dict) -> dict，就地或返回新 dict 均可
    :param migrate:  迁移函数，签名 (dict) -> dict，必须是幂等的
    :param indent:   落盘缩进
    """

    def __init__(self, path, *, defaults=None, normalize=None, migrate=None,
                 indent: int = DEFAULT_INDENT):
        self.path = os.path.abspath(path)
        self.indent = indent
        self._defaults = dict(defaults) if defaults else {}
        self._normalize = normalize
        self._migrate = migrate

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    def read(self) -> tuple[dict, str]:
        """读盘，返回 (config, rev)。读不到或非法时抛 ConfigReadError。"""
        with path_lock(self.path):
            return self._read_locked()

    def read_or_empty(self) -> tuple[dict, str]:
        """读盘；读不到时返回 ({}, '')，不抛异常。"""
        try:
            return self.read()
        except ConfigReadError:
            return {}, ''

    def exists(self) -> bool:
        return os.path.exists(self.path)

    def _read_locked(self) -> tuple[dict, str]:
        try:
            with open(self.path, 'rb') as f:
                raw = f.read()
        except FileNotFoundError as e:
            raise ConfigReadError(f'配置文件不存在: {self.path}') from e
        except OSError as e:
            raise ConfigReadError(f'配置文件读取失败: {e}') from e
        try:
            data = json.loads(raw.decode('utf-8'))
        except Exception as e:
            raise ConfigReadError(f'配置文件不是合法 JSON: {e}') from e
        if not isinstance(data, dict):
            raise ConfigReadError('配置文件的顶层必须是 JSON 对象')
        return data, revision_of(raw)

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    def update(self, patch: dict, *, expected_rev: str | None = None,
               delete=(), create_if_missing: bool = True) -> tuple[dict, str]:
        """读 → 删除 → 合并 patch → 迁移规范化 → 校验版本 → 原子写。

        这是一次受保护的操作：整个过程持有同一把路径锁，
        所以"两个调用方先后覆盖对方"不会发生。

        :param patch:        只包含**要改的字段**，不是完整快照。
                             浅合并意味着未提到的键保留磁盘上的现值，
                             未知字段因此也不会被丢掉。
        :param delete:       要删除的键（迭代对象）。
        :param expected_rev: 调用方读到的版本号；不一致则抛 ConfigConflictError。
                             传 None 表示不做冲突校验（向后兼容）。
        :return: (合并后的完整配置, 新版本号)
        """
        with path_lock(self.path):
            if not os.path.exists(self.path):
                if not create_if_missing:
                    raise ConfigReadError(f'配置文件不存在: {self.path}')
                data, rev = dict(self._defaults), None
            else:
                data, rev = self._read_locked()

            if expected_rev is not None and rev is not None and expected_rev != rev:
                raise ConfigConflictError(expected_rev, rev)

            for _k in delete:
                data.pop(_k, None)
            data.update(patch)
            return self._commit_locked(data)

    def write(self, data: dict) -> tuple[dict, str]:
        """整体替换（仅用于"文件不存在时初始化"与一次性迁移）。"""
        with path_lock(self.path):
            return self._commit_locked(dict(data))

    def ensure_exists(self) -> tuple[dict, str]:
        """确保配置文件存在；不存在则用 defaults 建一份。"""
        with path_lock(self.path):
            if os.path.exists(self.path):
                return self._read_locked()
            return self._commit_locked(dict(self._defaults))

    def _commit_locked(self, data: dict) -> tuple[dict, str]:
        data = self._prepare(data)
        try:
            # 已持有路径锁，必须走不加锁的落盘本体，否则自我死锁
            raw = _write_json_atomic_unlocked(self.path, data, indent=self.indent)
        except OSError as e:
            raise ConfigWriteError(f'配置写盘失败: {e}') from e
        return data, revision_of(raw)

    def _prepare(self, data: dict) -> dict:
        if self._migrate is not None:
            data = self._migrate(data)
        if self._normalize is not None:
            data = self._normalize(data)
        return data
