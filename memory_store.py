# -*- coding: utf-8 -*-
"""
对话记忆存储模块 —— 记忆目录归属规则与并发控制的唯一实现处（单一事实来源）。

本模块被 wxbot_core.py（机器人主体）与 web_server.py（管理面板）共同导入。
⚠ 依赖方向固定：本模块只依赖标准库，绝不导入 wxbot_core / web_server，
   以保证 wxbot_core 脱离面板也能独立运行。

为什么需要"存储标识"而不是直接用窗口名做目录名
------------------------------------------------
Windows 目录名不允许 <>:"/\\|?* 与不可见字符。旧实现是「把非法字符直接删掉」，
于是不同的窗口名会映射到同一个目录，共用同一个记忆文件、共用一份历史：

    张三: 客服   ┐
    张三 客服    ┴─→  目录名 "张三 客服"  →  同一个 _memory.json
    A:B / A?B / AB  →  目录名 "AB"
    群1|群2 / 群1群2 →  目录名 "群1群2"

微信群里带 | : < > 的名字很常见，因此这不是理论问题：两个窗口的聊天记录会混在
一起，AI 可能读到另一个窗口的历史；并发写入还会互相覆盖（原子写只能保证文件不
会被写坏，保证不了「谁的数据」）。

现在的规则
----------
    存储标识 storage_key = "{剔除非法字符并做长度截断后的名字}~{原始窗口名的 sha256}"
    - 名字部分只为可读性（方便人工在资源管理器里找目录）；
    - 归属完全由 `~` 后的哈希决定，因此窗口名不同 ⇒ 存储标识必然不同
      （sha256 完整 64 位十六进制，不是短哈希，不做截断）。
    - 目录名不合法或过长时退化为 "chat~{sha256}"。

    目录结构：{base_path}/{wx_id}/{storage_key}/{storage_key}_memory.json

会话锁
------
- 进程内：一把锁按「存储标识」取（不是按原始窗口名！），同一存储标识的两条访问
  路径（含面板和机器人后台线程）共用同一把锁。
- 进程间：再用 {storage_key}/.memory.lock 上的操作系统文件锁兜底，
  保证多进程（多个面板实例/独立机器人进程）也不会并发读改写同一个文件。
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime

# 跨平台文件锁：Windows 用 msvcrt，POSIX 用 fcntl
try:                                            # pragma: no cover - 平台分支
    import msvcrt
    _HAS_MSVCRT = True
except ImportError:                             # pragma: no cover - 平台分支
    msvcrt = None
    _HAS_MSVCRT = False

try:                                            # pragma: no cover - 平台分支
    import fcntl
    _HAS_FCNTL = True
except ImportError:                             # pragma: no cover - 平台分支
    fcntl = None
    _HAS_FCNTL = False


# ============================================================
# 常量
# ============================================================

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# 存储标识里分隔「可读名」与「哈希」的字符；哈希是完整 sha256，不做截断
STORAGE_HASH_SEP = '~'

# 可读名部分的最大字符数（目录名 = 名字部分 + '~' + 64 位 sha256）
MAX_STORAGE_NAME_PART = 40

# 目录名 + 文件名 的长度预算：超过就改用短形态
# （'chat~<64 位 sha256>'，目录名 69、文件名 81）。
# 40 字符名字部分时文件名 117 已经偏长，因此卡在 100，
# 保证常见安装路径（base 约 50~80 字符）下总路径不超过 Windows 260。
PATH_KEY_BUDGET = 100

# Windows 传统路径上限；留出余量给 "\\?\"/文件名/临时文件后缀
WINDOWS_MAX_PATH = 260
PATH_BUDGET_MARGIN = 40

# 空窗口名的占位符（带不可打印字符，真实窗口名不可能等于它）
EMPTY_CHAT_PLACEHOLDER = '\x00unnamed-chat'

# 记忆文件后缀与本模块自己维护的文件名
MEMORY_FILE_SUFFIX = '_memory.json'
MEMORY_LOCK_FILE_NAME = '.memory.lock'
ORIGINAL_NAME_FILE = 'name.json'
MIGRATION_LEDGER_NAME = '_migration_log.json'
QUARANTINE_DIR_NAME = '_quarantine'
QUARANTINE_META_NAME = 'migration_info.json'

# 每个 wx_id 目录下的内部子目录（不是聊天窗口）：
#   .locks/     跨进程锁文件（稳定路径，删除会话时不受影响）
#   .deleting/  会话目录被改名后的"待删墓碑"，随会话键唯一
LOCKS_DIR_NAME = '.locks'
DELETING_DIR_NAME = '.deleting'

# 记忆根目录 / wx_id 目录下的保留名字：只有这些才是本模块自己的文件与目录。
# ⚠ 不能用"下划线开头"一刀切判断内部目录：合法存储标识是可读名 + '~' + 哈希，
#   可读名以下划线开头很正常（例如会话 "_team"），那样会被误当内部目录，
#   导致写不进枚举、清空/删除全部也覆盖不到。
RESERVED_MEMORY_NAMES = frozenset({
    MIGRATION_LEDGER_NAME,      # _migration_log.json
    QUARANTINE_DIR_NAME,        # _quarantine
    LOCKS_DIR_NAME,             # .locks
    DELETING_DIR_NAME,          # .deleting
})


def is_internal_dir_name(name):
    """判断是否为内部文件/目录（迁移台账、隔离区、锁目录、墓碑目录）。

    按**精确名字**判断，而不是"下划线开头"：
    - 内部名字就是 `RESERVED_MEMORY_NAMES` 这几个；
    - 本模块生成的存储标识（可读名 + '~' + 64 位哈希）即使可读名以下划线开头，
      也是**合法会话**，必须能被枚举、清空与删除。
    """
    text = str(name)
    return text in RESERVED_MEMORY_NAMES


# ============================================================
# Windows 长路径（MAX_PATH 260）支持
# ============================================================

def long_path(path):
    """文件 API 边界用的长路径安全路径（Windows 下加 `\\\\?\\` 前缀）。

    Windows 的 260 字符限制来自 Win32 的路径解析层；`\\\\?\\` 前缀会让 Win32
    跳过路径解析和 260 检查，把路径直接交给内核（上限 32767 字符），因此
    **不需要**开注册表 LongPathsEnabled、不需要管理员权限、也不需要重启。

    ⚠ 只用于真正调文件 API 的地方；日志、面板展示、返回给前端的路径一律用
      原始路径。加过前缀的路径不要再交给 os.path.abspath/normpath/relpath，
      否则前缀会被破坏。
    ⚠ 入参必须是绝对路径；已经是前缀路径时原样返回（幂等）。
    """
    text = str(os.fspath(path))
    if os.name != 'nt' or text.startswith('\\\\?\\'):
        return text
    text = os.path.abspath(text)
    if text.startswith('\\\\'):                  # UNC：\\server\share\...
        return '\\\\?\\UNC\\' + text[2:]
    return '\\\\?\\' + text


# ============================================================
# 原子写
# ============================================================

_ATOMIC_WRITE_LOCKS = {}          # abspath -> threading.Lock()
_ATOMIC_WRITE_LOCKS_GUARD = threading.Lock()


def _get_atomic_write_lock(path):
    """取某个目标文件的写锁（首次访问时创建，创建过程本身也加锁）。"""
    key = os.path.normcase(long_path(os.path.abspath(str(path))))
    with _ATOMIC_WRITE_LOCKS_GUARD:
        lock = _ATOMIC_WRITE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _ATOMIC_WRITE_LOCKS[key] = lock
        return lock


def write_json_atomic(path, data, indent=4):
    """先写同目录下的唯一临时文件，再原子替换，避免读方读到半截 JSON。

    ⚠ 三处并发要点（都实测踩过）：
    1. 临时文件名必须唯一（mkstemp）。若用固定的 f"{path}.tmp"，多个写入方
       （面板多线程 + 机器人命令线程）会互相踩：A 写 tmp、B 覆盖同名 tmp 并
       replace、A 再 replace 抛 FileNotFoundError，且失败方向是反的
       （文件里是 B 的数据，却只有 A 报成功）。
    2. 同一目标的写入必须串行。即使临时名唯一，Windows 上并发 os.replace
       到同一目标仍会抛 PermissionError(WinError 5)：实测 12 线程 x 60 次
       并发写，720 次里有 278 次失败。因此按目标路径加锁。
    3. os.replace 还要容忍"读方正打开着目标文件"（同样是 WinError 5），
       因此做有限次快速重试。
    """
    with _get_atomic_write_lock(path):
        path = long_path(path)
        directory = os.path.dirname(path) or '.'
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=f'{os.path.basename(path)}.', suffix='.tmp', dir=directory
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=indent)
            for attempt in range(6):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.03 + 0.02 * attempt)
        finally:
            # 正常路径下 tmp 已被 replace 掉；异常时清理，避免残留临时文件
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def read_json_file(path, default=None):
    """安全读取 JSON 文件：文件不存在/内容损坏时返回 default。"""
    path = long_path(path)
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


# ============================================================
# 存储标识（storage_key）解析
# ============================================================

def is_windows_reserved_name(name):
    """CON / NUL / COM1 等 Windows 保留名（含带扩展名的形式）。"""
    stem = str(name).split('.', 1)[0].upper()
    return stem in WINDOWS_RESERVED_NAMES


def hash_storage_name(name):
    """仅由哈希构成的存储标识（名字部分完全不可用时使用）。"""
    digest = hashlib.sha256(str(name).encode('utf-8')).hexdigest()
    return f'chat{STORAGE_HASH_SEP}{digest}'


def max_name_part_for(base_dir=None, wx_id=''):
    """名字部分的最大长度（固定值，不随安装路径变化）。

    保留这个函数名是为了兼容既有调用点；长度恒定意味着同一个窗口名在任何
    机器上算出的目录名完全一致。
    """
    return MAX_STORAGE_NAME_PART


def name_part_for(name, base_dir=None, wx_id=''):
    """（兼容旧调用名）窗口名 → 存储标识里的名字部分。"""
    return storage_name_part(name)


def resolve_storage_key(chat_name, base_dir=None, wx_id=''):
    """窗口名 → 存储标识（唯一、稳定、与窗口名一一对应）。

    ⚠ 这里不是"剔除非法字符"，非法字符只是可读名的一部分被丢掉。
    ⚠ 哈希 = sha256('{名字部分}\\x1f{原始窗口名}')，因此：
      - 原始窗口名不同 ⇒ 哈希必然不同（A:B / A?B / AB 三个目录，绝不合用）；
      - 目录名自洽可校验：只要知道名字部分，就能重算哈希验证归属
        （名字部分随原始名确定，见 `storage_name_part`）；
      - 名字部分过长时会退化成长度固定、不随安装路径变化的形态
        （见 name_part_for / MAX_PATH 处理），因此归属不依赖进程状态。
    ⚠ 空窗口名统一映射到带不可打印字符的占位名，避免与真实的窗口名 'chat' 撞车。
    ⚠ 传入 base_dir 时会额外做 MAX_PATH 保护：完整路径仍超 260 就改用
      "chat~<sha256>" 短目录名，保证没开 LongPathsEnabled 的机器也能写盘。
      机器人、面板、预演工具都走这个函数，因此三方算出来的目录永远一致。
    """
    raw_name = str(chat_name)
    if not raw_name:
        raw_name = EMPTY_CHAT_PLACEHOLDER
    name_part = storage_name_part(raw_name)
    # 哈希只取决于**原始窗口名**：窗口名不同 ⇒ 哈希必然不同。
    # 名字部分只做展示/辨认，允许相同的可读前缀（如 'chat' 兜底形态）。
    digest = storage_key_digest(raw_name)
    key = f'{name_part}{STORAGE_HASH_SEP}{digest}'
    # MAX_PATH 保护：目录名+文件名超过预算就改用短形态（chat~<sha256>）。
    # 判据只看 key 自身长度，不看安装路径 —— 保证同一个窗口名在任何机器上算出的
    # 目录名一致（迁移与回滚不会因为换了目录而错位）。
    if detect_windows_path_risk(key):
        key = f'chat{STORAGE_HASH_SEP}{digest}'
    return key


def detect_windows_path_risk(storage_key):
    """存储标识本身是否过长（长到无论安装在哪个盘都可能超 MAX_PATH）。"""
    if os.name != 'nt':
        return False
    return len(storage_key) + len(MEMORY_FILE_SUFFIX) > PATH_KEY_BUDGET


def storage_name_part(raw_name, base_dir=None, wx_id=''):
    """窗口名 → 存储标识里的"名字部分"（长度稳定、可重算）。

    长度上限只取决于窗口名本身（不随安装路径变化），因此同一个窗口名在任何
    机器上都算出同样的目录名。名字部分仅供辨认，归属由哈希决定。
    """
    text = INVALID_FILENAME_CHARS_RE.sub('', str(raw_name)).strip().rstrip('. ')
    text = text[:MAX_STORAGE_NAME_PART]
    if not text or text in ('.', '..') or is_windows_reserved_name(text):
        return 'chat'
    return text


def storage_key_digest(raw_name):
    """存储标识的哈希部分：只由原始窗口名决定（窗口名不同 ⇒ 哈希不同）。"""
    return hashlib.sha256(str(raw_name).encode('utf-8')).hexdigest()


def storage_key_hash_part(storage_key):
    """取出存储标识里的哈希部分（没有则为空串）。"""
    key = str(storage_key)
    if STORAGE_HASH_SEP not in key:
        return ''
    return key.rsplit(STORAGE_HASH_SEP, 1)[1]


def is_storage_key(storage_key):
    """判断一个名字是否"看起来就是"存储标识（带 64 位 sha256 后缀）。"""
    suffix = storage_key_hash_part(storage_key)
    if len(suffix) != 64:
        return False
    return all(c in '0123456789abcdef' for c in suffix)


def memory_file_name(storage_key):
    """存储标识 → 记忆文件名。目录名与文件名保持一致，便于人工核对。"""
    return f'{storage_key}{MEMORY_FILE_SUFFIX}'


def lock_file_path(storage_dir):
    """某个记忆目录对应的旧式锁文件路径（锁文件放在被锁目录内）。"""
    return os.path.join(storage_dir, MEMORY_LOCK_FILE_NAME)


def stable_lock_file_path(base_dir, storage_key):
    """跨进程/删除安全的锁文件路径：放在稳定的锁目录里，不随会话目录一起被删。

    ⚠ 为什么需要它：删除会话要「加锁 → 改名目录 → rmtree」，
      而 Windows 上不能一边持有目录内的锁文件句柄、一边删掉这个目录。
      把锁文件挪到 {wx_id}/.locks/ 下（目录名稳定、不参与清理），
      就既能持有跨进程互斥、又能安全地把会话目录改名后删除。
      见 `session_lock_file_path()`。
    """
    return os.path.join(base_dir, LOCKS_DIR_NAME,
                        hashlib.sha256(str(storage_key).encode('utf-8')).hexdigest()[:32] + '.lock')


def session_lock_file_path(storage_dir):
    """由会话目录推出稳定锁路径（{wx_id}/{key} → {wx_id}/.locks/<hash>.lock）。"""
    return stable_lock_file_path(os.path.dirname(os.path.abspath(str(storage_dir))),
                                 os.path.basename(os.path.normpath(str(storage_dir))))


def read_original_name(chat_path, fallback=None):
    """读取记忆目录里记录的原始窗口名（面板展示用）。"""
    data = read_json_file(os.path.join(chat_path, ORIGINAL_NAME_FILE), None)
    if isinstance(data, dict):
        name = data.get('name')
        if name:
            return str(name)
    return fallback if fallback is not None else os.path.basename(chat_path)


# ============================================================
# 跨进程文件锁（目录级）
# ============================================================

_GLOBAL_DIR_LOCKS = {}            # abspath(storage_dir) -> threading.Lock()
_GLOBAL_DIR_LOCKS_GUARD = threading.Lock()


def _get_global_dir_lock(storage_dir):
    """取某个记忆目录的进程内全局锁，保证同一进程内只有一个线程去抢文件锁。"""
    key = os.path.abspath(storage_dir)
    with _GLOBAL_DIR_LOCKS_GUARD:
        lock = _GLOBAL_DIR_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _GLOBAL_DIR_LOCKS[key] = lock
        return lock


@contextmanager
def dir_file_lock(storage_dir, timeout=10.0):
    """对某个记忆目录加操作系统级文件锁（跨进程互斥）。

    沿用旧行为：锁文件放在该目录内（`{dir}/.memory.lock`），目录不存在时创建。
    拿不到锁时轮询等待 timeout 秒，超时后**仍然放行**（宁可退化为进程内互斥，
    也不能让机器人的记忆写入永久卡死）。

    ⚠ 需要"删目录也不能丢互斥"时请用 `file_lock_at()` + `stable_lock_file_path()`：
      锁文件在被删目录内时，持锁删除会失败（Windows）或锁一被删就失效。
    """
    if not storage_dir:
        yield
        return
    with _file_lock(os.path.join(str(storage_dir), MEMORY_LOCK_FILE_NAME),
                    timeout=timeout, create_parent=True):
        yield


@contextmanager
def file_lock_at(lock_path, timeout=10.0):
    """对指定锁文件加操作系统级文件锁（锁文件放在稳定位置，不随会话目录被删）。"""
    if not lock_path:
        yield
        return
    with _file_lock(lock_path, timeout=timeout, create_parent=True):
        yield


@contextmanager
def _file_lock(path, timeout=10.0, create_parent=True):
    """底层文件锁实现：在 `path` 上加锁，父目录按需创建。"""
    global_lock = _get_global_dir_lock(path)
    with global_lock:
        if create_parent:
            try:
                parent = os.path.dirname(long_path(path))
                if parent:
                    os.makedirs(parent, exist_ok=True)
            except OSError:
                yield
                return

        handle = None
        locked = False
        try:
            handle = open(long_path(path), 'a+b')
            try:
                # msvcrt.locking 不能锁超过文件末尾的区域，先确保文件至少有 1 字节
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b'\0')
                    handle.flush()
                handle.seek(0)
            except OSError:
                pass

            deadline = time.time() + timeout
            while True:
                try:
                    _try_lock_handle(handle)
                    locked = True
                    break
                except OSError:
                    if time.time() >= deadline:
                        break
                    time.sleep(0.02)

            yield
        finally:
            if handle is not None:
                if locked:
                    try:
                        _unlock_handle(handle)
                    except OSError:
                        pass
                try:
                    handle.close()      # 关闭句柄本身也会释放文件锁
                except OSError:
                    pass


def _try_lock_handle(handle):
    """尝试非阻塞加锁；锁被占用时抛 OSError。"""
    if _HAS_MSVCRT:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    if _HAS_FCNTL:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    raise OSError('当前平台没有可用的文件锁实现')


def _unlock_handle(handle):
    """解锁；未持锁时抛 OSError。"""
    if _HAS_MSVCRT:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    if _HAS_FCNTL:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    raise OSError('当前平台没有可用的文件锁实现')


def storage_key_of(path):
    """从目录路径取存储标识（取目录名）。"""
    if not path:
        return ''
    return os.path.basename(os.path.normpath(str(path)))


def storage_key_from_dir_name(name):
    """目录名 → 存储标识。新格式目录名本身就是存储标识；旧格式返回空串。"""
    name = str(name)
    return name if _is_new_format_dir_name(name) else ''


# ============================================================
# 旧目录迁移 / 隔离
# ============================================================

def scan_wx_dir(wx_dir):
    """扫描某个 wx_id 目录，判定每个旧目录的归属。

    返回 dict：
        {
          'migrate':    {legacy_name: (storage_key, 原始名称)}  # 归属明确，可迁移
          'quarantine': {legacy_name: 原因}                     # 归属不明/不安全，隔离
          'keep':       [legacy_name, ...]                      # 已经是新格式，无需处理
        }

    ⚠ 关键约束：一个旧目录只能映射到**一个** owner，owner 的名字就是
      "旧代码当时用来生成目录名的那个窗口名"。只有 owner 自己能用这个目录，
      别的窗口绝不能复用同一个 key —— 否则两个窗口名继续共用一份记忆
      （例如窗口名 '铭铭.' 与 '铭铭'：旧目录叫 '铭铭'，但它属于 '铭铭.'，
        绝不能让 '铭铭' 也解析到同一份数据）。

    判定规则（宁可隔离，不可猜错：猜错的代价是 AI 读到别的窗口的聊天记录）
    ---------------------------------------------------------------
    1. 目录名已是新格式（可读名~64位sha256）→ keep；
    2. 目录名含非法字符而被清洗过（目录名 != 清洗后目录名）→ 一定混有多个窗口，
       隔离（例：dir "AB" 由旧目录名 "A:B" 清洗而来时，目录名已经丢了 ':'）；
    3. 目录里有 name.json，且记录的原始名"清洗后"与目录名不同 → 同样说明
       原始名是被清洗过的，可能与其他窗口撞名，隔离；
    4. 目录里有多个 *_memory.json → 历史上已被多个窗口共用过，隔离；
    5. 其余情况 → 归属明确，owner 按下面的优先级确定：
       a. name.json 记录的原始名（它才是旧代码当时使用的窗口名；
          例如目录 '铭铭' + name.json '铭铭.' → owner = '铭铭.'）；
       b. 没有 name.json 时，目录名本身就是窗口名。

    注：判定结果会写入台账，之后同一个旧目录名不会再被别的窗口认领
    （见 LegacyMigration）。
    """
    result = {'migrate': {}, 'quarantine': {}, 'keep': []}
    if not os.path.isdir(long_path(wx_dir)):
        return result

    try:
        entries = sorted(os.listdir(long_path(wx_dir)))
    except OSError:
        return result

    for entry in entries:
        if is_internal_dir_name(entry):
            continue
        path = os.path.join(wx_dir, entry)
        if not _is_real_dir(path):
            continue

        if _is_new_format_dir_name(entry):
            result['keep'].append(entry)
            continue

        # 归属是否"明确"由三个信号决定，任一矛盾即隔离（宁隔离，不猜错）
        clean_name = name_part_for(entry)
        recorded = _read_recorded_name(path)
        memory_files = _list_memory_files(path)

        if INVALID_FILENAME_CHARS_RE.search(entry) or entry != clean_name:
            # 目录名本身就被清洗过：原始窗口名可能含非法字符或尾部点号，
            # 与它清洗后同名的另一个窗口会撞到同一个目录
            result['quarantine'][entry] = (
                '目录名与原始窗口名不一致（旧规则剔除了非法字符/尾部点号），'
                f'该目录可能属于窗口「{entry}」或某个被清洗成「{clean_name}」的窗口'
            )
            continue

        if recorded is not None and not _recorded_name_matches_dir(recorded, entry):
            # name.json 记录的原始名不是这个目录名、也不是"只差尾部点号"。
            # 例：dir「群1群2应用群」+ name.json「群1|群2应用群」：目录名已被清洗，
            # 窗口「群1群2应用群」和「群1|群2应用群」都可能认领这个目录 → 隔离
            result['quarantine'][entry] = (
                f'目录内 name.json 记录的原始名是「{recorded}」，与目录名「{entry}」'
                '不一致，该目录可能属于两者中的任意一个窗口'
            )
            continue

        if len(memory_files) > 1:
            result['quarantine'][entry] = (
                f'目录内有多个记忆文件（{", ".join(sorted(memory_files))}），'
                '历史上已被多个窗口共用'
            )
            continue

        # owner：name.json 记录的原始名优先（它才是旧代码当时用的窗口名）；
        # 例如目录 '铭铭' + name.json '铭铭.' → owner '铭铭.'，
        # 目录名 '铭铭' 本身不能解析到这份数据（否则两个窗口继续共用记忆）。
        owner = recorded if recorded else entry
        if not owner or owner == '.' or owner == '..':
            result['quarantine'][entry] = '目录（或 name.json）里的窗口名为空，无法判定归属'
            continue
        # 用记忆根目录算可读名长度上限，保证完整路径不超 Windows MAX_PATH
        result['migrate'][entry] = (resolve_storage_key(owner, wx_dir,
                                                        os.path.basename(os.path.normpath(wx_dir))),
                                    owner)

    return result


def _recorded_name_matches_dir(recorded, dir_name):
    """name.json 记录的原始名是否指向该目录。

    允许一种无害差异：旧代码 `storage_name.strip().rstrip('. ')` 会把窗口名尾部的
    点号和空格抹掉，于是窗口名 '铭铭.' 落到目录 '铭铭'，name.json 记的是 '铭铭.'。
    这种目录只有一个可能的主人（'铭铭.'），可以直接迁移，
    否则真实用户里会出现"旧记忆全部被隔离、记忆变空"的观感。
    """
    recorded = str(recorded)
    if recorded == dir_name:
        return True
    return recorded.rstrip('. ') == dir_name


def _is_new_format_dir_name(name, owner_name=None):
    """目录名是否为本模块生成的存储标识（形态判据）。

    形态恒定 = 「名字部分 + '~' + 64 位十六进制哈希」。窗口名虽然理论上也可能
    长成这样，但那种名字的目录名会落在它自己的哈希上，不会与别人共用目录
    （见 memory_store 顶部关于存储标识的说明）。
    owner_name 参数保留给"按 name.json 校验归属"的调用方，形态判据本身不用它。
    """
    return is_storage_key(name)


def _is_real_dir(path):
    """判断路径是不是目录（Windows 上末位 '.' 会被自动去掉，需要绕过规范化）。"""
    probe = long_path(path)
    try:
        import stat as _stat
        return _stat.S_ISDIR(os.stat(probe).st_mode)
    except OSError:
        return False


def _list_memory_files(chat_path):
    """列出目录里的所有 *_memory.json 文件。"""
    try:
        return [f for f in os.listdir(long_path(chat_path)) if f.endswith(MEMORY_FILE_SUFFIX)]
    except OSError:
        return []


def _read_recorded_name(chat_path):
    """读取目录里 name.json 记录的原始名；不存在时返回 None。"""
    data = read_json_file(os.path.join(chat_path, ORIGINAL_NAME_FILE), None)
    if isinstance(data, dict) and data.get('name'):
        return str(data['name'])
    return None


class LegacyMigration:
    """旧记忆目录的迁移/隔离引擎。

    设计要点
    --------
    - **只在必要时才迁**：`migrate_owner()` 只处理「目录名就是原始窗口名」的旧目录，
      即归属明确的那些；其余一律移入 `_quarantine/`，绝不让两个新目录都去读同一个旧目录。
    - **残留窗口很小**：
        1. 复制 旧目录 → 新目录.staging-<时间戳>（含全部文件）
        2. os.replace(新目录.staging → 新目录)   ← 目录级原子改名，不留半个新目录
        3. os.replace(旧目录 → _quarantine/...)
      第 1、2 步都成功后才动旧目录；第 2 步之后、第 3 步之前中断，旧目录仍在原位，
      下次启动重扫会发现「目标目录已存在」→ 跳过复制，只补做第 3 步（不会复制两份）。
      任何阶段的数据都至少存在于旧目录/_quarantine 中，不会丢。
    - **全程记账**：每步都写 `{base}/_migration_log.json`（原子写），
      回滚脚本 `tools/rollback_memory_migration.py` 依据它把目录改回原名。
    """

    def __init__(self, base_path):
        self.base_path = base_path
        self.ledger_path = os.path.join(base_path, MIGRATION_LEDGER_NAME)
        self.quarantine_root = os.path.join(base_path, QUARANTINE_DIR_NAME)

    # ---------------- 台账 ----------------

    def load_ledger(self):
        """读取迁移台账；结构：{'version':1,'entries':[...]}"""
        data = read_json_file(self.ledger_path, None)
        if not isinstance(data, dict) or not isinstance(data.get('entries'), list):
            return {'version': 1, 'entries': []}
        data.setdefault('version', 1)
        return data

    def _save_ledger(self, ledger):
        """原子写台账；写失败只告警，不影响迁移本身。"""
        try:
            write_json_atomic(self.ledger_path, ledger, indent=2)
        except Exception:
            pass

    def _open_entry(self, ledger, wx_id, legacy_name, **fields):
        """取得（或新建）某旧目录的台账记录。

        同一旧目录重试时复用同一条记录，避免台账里出现多条同源记录。
        """
        for entry in ledger['entries']:
            if entry.get('wx_id') == wx_id and entry.get('legacy_name') == legacy_name:
                entry.update(fields)
                self._save_ledger(ledger)
                return entry
        entry = dict(fields)
        entry['time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        entry['wx_id'] = wx_id
        entry['legacy_name'] = legacy_name
        ledger['entries'].append(entry)
        self._save_ledger(ledger)
        return entry

    # ---------------- 对外入口 ----------------

    def scan(self):
        """扫描全部 wx_id 目录，返回每项 {wx_id, legacy_name, action, ...}。"""
        items = []
        for wx_id in self._list_wx_ids():
            wx_dir = os.path.join(self.base_path, wx_id)
            found = scan_wx_dir(wx_dir)
            for legacy_name, (storage_key, original) in sorted(found['migrate'].items()):
                items.append({
                    'wx_id': wx_id,
                    'legacy_name': legacy_name,
                    'action': 'migrate',
                    'storage_key': storage_key,
                    'original_name': original,
                })
            for legacy_name, reason in sorted(found['quarantine'].items()):
                items.append({
                    'wx_id': wx_id,
                    'legacy_name': legacy_name,
                    'action': 'quarantine',
                    'reason': reason,
                })
        return items

    def apply(self, items, wx_id=None):
        """执行迁移/隔离；返回统计 dict。"""
        stats = {'migrated': 0, 'quarantined': 0, 'skipped': 0, 'failed': 0, 'errors': []}
        ledger = self.load_ledger()
        self._resume_interrupted(ledger)

        for item in items:
            if item['action'] not in ('migrate', 'quarantine'):
                continue
            try:
                if item['action'] == 'migrate':
                    status = self._migrate_one(
                        ledger, item['wx_id'], item['legacy_name'], item['storage_key']
                    )
                else:
                    status = self._quarantine_one(
                        ledger, item['wx_id'], item['legacy_name'], item.get('reason', '')
                    )
            except Exception as e:                      # 单个目录失败不影响其他目录
                stats['failed'] += 1
                stats['errors'].append(f"{item['wx_id']}/{item['legacy_name']}: {e}")
                continue

            if status == 'skipped':
                stats['skipped'] += 1
            elif status == 'migrated':
                stats['migrated'] += 1
            else:
                stats['quarantined'] += 1
        return stats

    def migrate_owner(self, wx_id, legacy_name, storage_key, alias_original=None):
        """把某个「归属明确」的旧目录迁移到新目录，返回 True 表示数据已在新目录。

        迁移结果会被记入台账（含 `alias_original`：目录名对应的原始窗口名，
        例如目录 '铭铭' 的原始名其实是 '铭铭.'），因此后续同一个旧目录名不会再被
        别的窗口认领，原始窗口名也能查到数据迁到了哪里。
        """
        ledger = self.load_ledger()
        self._resume_interrupted(ledger)
        status = self._migrate_one(ledger, wx_id, legacy_name, storage_key,
                                   alias_original=alias_original)
        return status in ('migrated', 'skipped')

    # ---------------- 内部实现 ----------------

    def _list_wx_ids(self):
        try:
            return sorted(
                d for d in os.listdir(long_path(self.base_path))
                if not is_internal_dir_name(d) and _is_real_dir(os.path.join(self.base_path, d))
            )
        except OSError:
            return []

    def _migrate_one(self, ledger, wx_id, legacy_name, storage_key, alias_original=None):
        """迁移单个目录；返回 'migrated' / 'skipped'。"""
        wx_dir = os.path.join(self.base_path, wx_id)
        legacy_path = os.path.join(wx_dir, legacy_name)
        if not _is_real_dir(legacy_path):
            return 'skipped'

        # 旧目录已经处理过（台账里有记录）→ 幂等跳过，同一个旧目录名不会再被别的窗口认领
        if self._already_handled(ledger, wx_id, legacy_name):
            return 'skipped'

        target_path = os.path.join(wx_dir, storage_key)
        entry = self._open_entry(
            ledger, wx_id, legacy_name,
            storage_key=storage_key,
            action='migrate',
            status='in_progress',
            source_dir=legacy_path,
            target_dir=target_path,
            alias_original=alias_original or legacy_name,
        )

        if not _is_real_dir(target_path):
            staging = f'{target_path}.staging-{int(time.time() * 1000)}'
            try:
                shutil.copytree(long_path(legacy_path), long_path(staging))
                self._rename_inside_copy(staging, legacy_name, storage_key)
                if os.path.exists(long_path(target_path)):   # 并发下极小概率被别人抢先创建
                    # 竞态：复制期间新目录被建出来了（可能是并发访问，也可能是
                    # 上一次失败后产生的写入）→ 把旧历史并进去，绝不整目录覆盖
                    self._merge_legacy_history(staging, target_path, storage_key)
                    shutil.rmtree(long_path(staging), ignore_errors=True)
                else:
                    os.replace(long_path(staging), long_path(target_path))  # 目录级原子改名
            except Exception as e:
                shutil.rmtree(long_path(staging), ignore_errors=True)
                entry['status'] = 'failed'
                entry['error'] = str(e)
                self._save_ledger(ledger)
                raise
        else:
            # 目标目录已存在，**不代表旧历史已经迁完**：
            # 上一次迁移可能失败过，期间的新消息已经写进新目录。
            # 这里必须按内容比对，缺什么补什么，绝不覆盖新目录里的数据。
            if not self._target_has_legacy_history(legacy_path, target_path, storage_key):
                self._merge_legacy_history(legacy_path, target_path, storage_key)
            entry['reused_existing_target'] = True
            self._save_ledger(ledger)

        # 数据已经在新目录里了，旧目录整体移入隔离区（不删除，可回滚）
        self._quarantine_legacy_dir(
            ledger, wx_id, legacy_name, legacy_path,
            reason='数据已迁移到新目录，原目录保留在隔离区备查',
            status='migrated', target_dir=target_path,
        )
        entry['status'] = 'migrated'
        self._save_ledger(ledger)
        return 'migrated'

    # ---------------- 旧历史合并（迁移恢复用） ----------------

    @staticmethod
    def _message_identity(entry):
        """消息身份：用于合并时去重（同一时间+同一发送人+同样内容算同一条）。"""
        if not isinstance(entry, dict):
            return repr(entry)
        return tuple(str(entry.get(field, '')) for field in
                     ('time', 'type', 'attr', 'sender', 'content'))

    def _target_has_legacy_history(self, legacy_dir, target_dir, storage_key):
        """目标目录里是否已经包含旧目录的全部历史。

        判断依据是**消息内容**，不是"目标目录是否存在"——目标可能是上一次
        迁移失败后新建的（只有新消息），那种情况必须合并。
        """
        legacy_messages = read_json_file(
            os.path.join(legacy_dir, memory_file_name(storage_key)), None)
        if not isinstance(legacy_messages, list):
            # 旧目录里的记忆文件名可能和目录名不一致（旧版布局），扫一遍
            legacy_messages = []
            for name in _list_memory_files(legacy_dir):
                data = read_json_file(os.path.join(legacy_dir, name), None)
                if isinstance(data, list):
                    legacy_messages.extend(data)
        if not legacy_messages:
            return True

        target_messages = []
        for name in _list_memory_files(target_dir):
            data = read_json_file(os.path.join(target_dir, name), None)
            if isinstance(data, list):
                target_messages.extend(data)
        have = {self._message_identity(m) for m in target_messages}
        return all(self._message_identity(m) in have for m in legacy_messages)

    def _merge_legacy_history(self, legacy_dir, target_dir, storage_key):
        """把旧历史并进新目录：旧消息在前、新消息在后，按内容去重。

        - **绝不覆盖**：目标目录里已有的消息原样保留（时间戳原样不动）；
        - **绝不遗失**：旧目录里独有的消息按原顺序补在最前面；
        - 旧消息本来就比新消息早，因此"旧在前、新在后"既保证了不丢，
          也保持时间顺序（迁移失败期间的窗口期就是这么产生的）。
        """
        legacy_messages = []
        for name in _list_memory_files(legacy_dir):
            data = read_json_file(os.path.join(legacy_dir, name), None)
            if isinstance(data, list):
                legacy_messages.extend(data)
        if not legacy_messages:
            return 0

        target_path = os.path.join(target_dir, memory_file_name(storage_key))
        target_messages = read_json_file(target_path, None)
        if not isinstance(target_messages, list):
            target_messages = []

        have = {self._message_identity(m) for m in target_messages}
        prepend = []
        for message in legacy_messages:
            identity = self._message_identity(message)
            if identity in have:
                continue
            have.add(identity)
            prepend.append(message)

        if prepend:
            write_json_atomic(target_path, prepend + target_messages, indent=2)
        return len(prepend)

    def _rename_inside_copy(self, staging_dir, legacy_name, storage_key):
        """把复制出来的目录整理成新格式：记忆文件名与目录名一致，并补写 name.json。

        用通配而非拼 `{legacy_name}{后缀}`：旧目录里的记忆文件名可能和目录名不一致
        （旧版面板会扫 `*_memory.json` 兜底），拼名字会漏掉、导致迁移后"记忆变空"。
        """
        target_name = memory_file_name(storage_key)
        for name in _list_memory_files(staging_dir):
            if name == target_name:
                continue
            source = os.path.join(staging_dir, name)
            target = os.path.join(staging_dir, target_name)
            if os.path.exists(long_path(target)):
                # 理论上不会出现（多个记忆文件已被判为归属不明、不进迁移流程），
                # 真出现时保留原文件并改名，绝不删除用户数据
                target = os.path.join(staging_dir, f'{storage_key}.{name}')
            os.replace(long_path(source), long_path(target))

        recorded = _read_recorded_name(staging_dir)
        if recorded is None:
            try:
                write_json_atomic(
                    os.path.join(staging_dir, ORIGINAL_NAME_FILE),
                    {'name': legacy_name},
                    indent=2,
                )
            except Exception:
                pass

    def _quarantine_one(self, ledger, wx_id, legacy_name, reason):
        """把归属不明的旧目录移入隔离区。"""
        wx_dir = os.path.join(self.base_path, wx_id)
        legacy_path = os.path.join(wx_dir, legacy_name)
        if not _is_real_dir(legacy_path):
            return 'skipped'

        if self._already_handled(ledger, wx_id, legacy_name):
            return 'skipped'

        self._quarantine_legacy_dir(ledger, wx_id, legacy_name, legacy_path, reason=reason)
        return 'quarantined'

    @staticmethod
    def _already_handled(ledger, wx_id, legacy_name):
        """台账里是否已记录该旧目录的处理结果（幂等保护）。"""
        for entry in ledger['entries']:
            if (entry.get('wx_id') == wx_id
                    and entry.get('legacy_name') == legacy_name
                    and entry.get('status') in ('migrated', 'quarantined')):
                return True
        return False

    def _quarantine_legacy_dir(self, ledger, wx_id, legacy_name, legacy_path,
                               reason='', status='quarantined', target_dir=None):
        """把旧目录整体移入 `_quarantine/{wx_id}/<原名>__<原因>`，并记账。

        不删除原数据，只是改个位置：用户随时可以按台账改回来（见回滚脚本）。
        """
        quarantine_wx_dir = os.path.join(self.quarantine_root, wx_id)
        os.makedirs(long_path(quarantine_wx_dir), exist_ok=True)
        suffix = '__migrated' if status == 'migrated' else '__ambiguous'
        dest_name = f'{legacy_name}{suffix}'
        dest_path = os.path.join(quarantine_wx_dir, dest_name)
        if os.path.exists(long_path(dest_path)):
            dest_name = f'{dest_name}.{int(time.time() * 1000)}'
            dest_path = os.path.join(quarantine_wx_dir, dest_name)

        os.replace(long_path(legacy_path), long_path(dest_path))
        try:
            write_json_atomic(os.path.join(dest_path, QUARANTINE_META_NAME), {
                'original_dir_name': legacy_name,
                'wx_id': wx_id,
                'reason': reason,
                'migrated_to': target_dir,
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }, indent=2)
        except Exception:
            pass

        self._open_entry(
            ledger, wx_id, legacy_name,
            storage_key=storage_key_of(target_dir) if target_dir else '',
            action='migrate' if status == 'migrated' else 'quarantine',
            status=status,
            reason=reason,
            source_dir=legacy_path,
            target_dir=target_dir,
            quarantine_dir=dest_path,
        )

    def _resume_interrupted(self, ledger):
        """处理上次中断留下的 staging 目录，并把中断记录标记出来。

        中断的迁移会在下一次 `migrate_owner()` 里自动重试（幂等），这里只负责
        清理 staging 残骸与更新台账状态，不动任何已有数据。
        """
        changed = False
        for entry in ledger['entries']:
            if entry.get('status') != 'in_progress':
                continue
            target = entry.get('target_dir') or ''
            wx_dir = os.path.dirname(target) if target else ''
            if wx_dir and os.path.isdir(long_path(wx_dir)):
                for name in os.listdir(long_path(wx_dir)):
                    if name.startswith(os.path.basename(target) + '.staging-'):
                        shutil.rmtree(long_path(os.path.join(wx_dir, name)), ignore_errors=True)
            entry['status'] = 'interrupted_needs_review'
            entry['note'] = '上次迁移未完成，下次访问该窗口时会自动重试（幂等）'
            changed = True
        if changed:
            self._save_ledger(ledger)


# ============================================================
# MemoryManager：记忆读写与清空的唯一入口
# ============================================================

class MemoryManager:
    """按窗口分文件存储收发消息，并在 AI 请求时提供历史上下文。

    存储路径：{base_path}/{wx_id}/{storage_key}/{storage_key}_memory.json

    ⚠ 所有会改动记忆的入口（保存 / 清空单个 / 清空全部 / 面板删除）都必须走
      本类的方法，并且都必须经过 `_store_lock()`：
        - 锁按【存储标识】取，不按原始窗口名 —— 两个窗口各拿一把锁却写同一个文件，
          等于没有锁（这正是身份碰撞事故的一部分）；
        - 保存是"读整个文件 → 改 → 写回"，清空若不加同一把锁就会出现
          「保存线程读到旧历史 → 清空写入 [] → 保存线程写回旧历史+新消息」，
          清空被撤销。因此清空必须与保存共用同一把锁、同一个入口。
    """

    # 面板「查看记忆」一次最多返回多少条（避免把整个文件塞进响应）
    MEMORY_READ_LIMIT = 100000

    def __init__(self, wx_id, base_path, migrate_legacy=True):
        """绑定一个微信账号的记忆根目录，并建立进程内写锁表。

        :param wx_id: 微信号目录名
        :param base_path: 记忆根目录（{base_dir}/memory/）
        :param migrate_legacy: 是否在首次访问窗口时迁移归属明确的旧目录（默认开启）
        """
        self.wx_id        = str(wx_id)
        self.base_path    = base_path
        self.base_dir     = os.path.join(base_path, self.wx_id)
        self.migrate_legacy = bool(migrate_legacy)
        self._locks       = {}                  # storage_key -> threading.Lock()
        self._locks_guard = threading.Lock()    # 保护 _locks 的创建过程
        self._resolved    = {}                  # chat_name -> storage_key（进程内缓存）
        self._resolved_guard = threading.Lock()
        self._legacy_scan = None                # {'migrate': {...}, 'quarantine': {...}}
        self._legacy_guard = threading.Lock()
        self._handled_legacy_dirs = set()       # 本进程已迁移/隔离的旧目录名
        self._emitted_keys = {}                 # storage_key -> 原始窗口名（已确认归属）
        self._emitted_scanned = False
        # 本线程持有的会话文件锁（不可重入锁的登记表，见 _session_file_lock）
        self._thread_locks_local = threading.local()
        self.migration = LegacyMigration(base_path)

    # ---------------- 锁 ----------------

    def _get_lock(self, chat_name):
        """取某个窗口的写锁，按【存储标识】共享同一把锁。

        ⚠ 创建过程必须整体加锁。若写成 `if key not in self._locks:
        self._locks[key] = threading.Lock()`，两个回调线程同时首次访问
        同一窗口会各建一把锁、互斥失效 —— _append_message_in_order 里
        "修正回调并发导致的乱序写入" 就是在补这个症状。
        实测：4 线程并发首次访问会拿到 4 把不同的锁。
        注意 defaultdict(threading.Lock) 并不够用：__missing__ 返回的是它自己
        创建的对象，两个线程仍会各拿到一把锁（实测 200/200 轮复现）。

        ⚠ 另一个坑：键必须是【存储标识】。旧实现用原始窗口名做键，于是
        "A:B" 和 "AB" 会各拿一把锁、却写同一个文件 —— 用多少把锁都拦不住互相覆盖。
        """
        key = self.resolve_storage_key(chat_name)
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                # 必须是可重入锁：clear_messages / save_message 会调用
                # _get_memory_path()，其中也可能经 resolve_storage_key 回到这里；
                # 用普通 Lock 时同一线程二次进入会自己把自己锁死。
                lock = threading.RLock()
                self._locks[key] = lock
            return lock

    def get_lock_key(self, chat_name):
        """对外暴露「某个窗口用的是哪把锁」，便于测试与排查。"""
        return self.resolve_storage_key(chat_name)

    @contextmanager
    def _store_lock(self, chat_name):
        """记忆读写/清空的统一互斥：进程内按存储标识 + 进程间按稳定锁文件。

        ⚠ 锁文件必须放在**稳定位置**（{wx_id}/.locks/）而不是会话目录内：
          删除会话时要把目录改名再 rmtree，锁文件在被删目录里时
          Windows 会拒绝删除（句柄占用），或者在 Linux 上锁文件被删掉后
          新进程另建一个文件、绕过互斥。见 `_session_lock()`。
        """
        key = self.resolve_storage_key(chat_name)
        with self._get_lock(key):
            with self._session_file_lock(key):
                yield

    def _session_lock_file(self, storage_key):
        """某个存储标识的稳定锁文件路径。"""
        return stable_lock_file_path(self.base_dir, storage_key)

    @contextmanager
    def _session_file_lock(self, storage_key):
        """跨进程会话互斥：锁文件在 {wx_id}/.locks/ 下，删除目录时不受影响。

        ⚠ 该锁**不可重入**（msvcrt/flock 都不支持同一线程二次加锁）。
          因此要记录"本线程正持有哪几把会话锁"：`_migration_target_for`
          既要持锁跑迁移，又可能被 `save_message` 内部的
          `resolve_storage_key()` 再次调到，没有这个登记就会自己等自己
          （实测直接卡死在 `_file_lock` 的 open/locking 上）。
        """
        key = str(storage_key)
        held = self._thread_locks()
        already = key in held
        if not already:
            with file_lock_at(self._session_lock_file(key)):
                held.add(key)
                try:
                    yield
                finally:
                    held.discard(key)
        else:
            # 本线程已经持有该锁：直接进入（外层负责最终释放）
            yield

    def _thread_locks(self):
        """本线程当前持有的会话锁集合（thread-local，惰性创建）。"""
        held = getattr(self._thread_locks_local, 'held', None)
        if held is None:
            held = set()
            self._thread_locks_local.held = held
        return held

    def _tombstone_path(self, storage_key):
        """会话目录被改名后的"墓碑"路径（删除过程中临时存在）。"""
        return os.path.join(self.base_dir, DELETING_DIR_NAME, storage_key)

    def _delete_session_dir(self, storage_key):
        """加锁 → 把会话目录改名成墓碑 → 释放锁 → 删墓碑。

        为什么必须"先改名、后删除"：
        - 目录内的 .memory.lock 会造成"持锁删不掉、删掉锁就失效"的两难，
          因此改用 .locks/ 下的稳定锁文件；
        - 改名是原子操作，且在锁内完成：改名之后落到这个会话上的保存
          会新建一个干净目录，绝不会被随后的 rmtree 连带删掉
          （这正是"迟到的目录清理抹掉刚保存的新消息"的根因）；
        - rmtree 只针对墓碑路径，不碰任何活跃会话目录。

        返回 True 表示目录已经不存在（删除成功或本来就没有）。
        """
        chat_dir = os.path.join(self.base_dir, storage_key)
        if not _is_real_dir(chat_dir):
            return True

        tombstone = self._tombstone_path(storage_key)
        with self._get_lock(storage_key):
            with self._session_file_lock(storage_key):
                try:
                    os.makedirs(long_path(os.path.dirname(tombstone)), exist_ok=True)
                except OSError as e:
                    _warn(f"删除会话失败（无法创建墓碑目录） {self.wx_id}/{storage_key}: {e}")
                    return False
                if os.path.exists(long_path(tombstone)):       # 上次中断留下的墓碑
                    self._remove_path(tombstone)
                try:
                    os.replace(long_path(chat_dir), long_path(tombstone))
                except OSError as e:
                    # 改名失败（例如目录内有文件被别人打开）：放弃删除，
                    # 语义等同"没删掉"，绝不退回"无保护 rmtree"
                    _warn(f"删除会话失败（目录改名不成功） {self.wx_id}/{storage_key}: {e}")
                    return False
        # 锁已释放；此时新保存只会写进全新的同名目录，不会碰到墓碑
        self._remove_path(tombstone)
        return True

    # ---------------- 存储标识解析 ----------------

    def _scan_legacy(self):
        """惰性扫描一次旧目录（进程内只扫一次）。"""
        if self._legacy_scan is not None:
            return self._legacy_scan
        with self._legacy_guard:
            if self._legacy_scan is None:
                self._legacy_scan = scan_wx_dir(self.base_dir)
            return self._legacy_scan

    def resolve_storage_key(self, chat_name):
        """窗口名（或面板传来的存储标识）→ 最终存储标识。

        1. 参数本身就是一个已有目录名 → 直接用（面板删除/查看走这条路）；
        2. 参数命中"归属明确的旧目录" → 迁移到新目录并返回新标识；
        3. 否则按窗口名算出新标识（并顺带把该窗口对应的旧目录迁移掉）。

        ⚠ 命中缓存时仍会补做"还没成功的旧目录迁移"：迁移失败只是不标记成
          已处理，不能因此让同一个进程余生都不再重试（否则旧历史要等到下次
          重启才可能被救回来）。
        """
        raw = str(chat_name)
        if not raw:
            # 空窗口名统一映射到占位名，避免与真实窗口名 'chat' 撞车
            raw = EMPTY_CHAT_PLACEHOLDER
        key = self._resolved.get(raw)          # 热路径：命中缓存就不加锁
        if key is not None:
            self._retry_pending_migration(raw)
            return key

        key = self._resolve_uncached(raw)
        with self._resolved_guard:
            self._resolved.setdefault(raw, key)
        return self._resolved[raw]

    def _retry_pending_migration(self, raw):
        """补做尚未成功的旧目录迁移（幂等；没有待处理项时开销只是一次字典遍历）。"""
        if not self.migrate_legacy:
            return
        scan = self._scan_legacy()
        if not scan['migrate']:
            return
        self._migration_target_for(raw, scan)

    def _resolve_uncached(self, raw):
        # 1) 调用方传进来的就是存储标识（面板列表回传、或程序内部把
        #    list_storage_keys() 的结果再传回来：clear_all / delete / 锁表）。
        #    本模块的目录名恒定是「名字部分 + '~' + 64 位哈希」，
        #    窗口名不可能天然长成这样，因此形态合法即可原样返回。
        #    这样 `resolve_storage_key(key) == key`（幂等），窗口名与它的存储标识
        #    必然共用同一把锁。
        if _is_new_format_dir_name(raw):
            return raw

        # 2) 与 raw 撞名、且归属不明的旧目录先隔离掉。否则会出现：resolve(raw)
        #    算出新标识，而 _memory_path_if_exists 又回退去读那个旧目录
        #    → 继续抢读混在一起的数据（例：旧目录「群1群2应用群」同时匹配两个窗口）。
        self._quarantine_ambiguous_legacy(raw)

        # 3) 已登记的存储标识（目录可能刚被删掉/还没建）→ 原样返回，
        #    绝不能再哈希一次：否则会另建一个空目录，
        #    表现为"清空全部记忆后历史又回来了"。
        self._scan_emitted_keys()
        if _is_new_format_dir_name(raw) and raw in self._emitted_keys:
            return raw

        # 4) 归属明确的旧目录：把 raw 当作 owner（旧代码当时使用的窗口名）匹配。
        #    ⚠ 只按 owner 匹配，不按"旧目录的目录名"匹配：目录 '铭铭' 的 owner 是
        #      '铭铭.'，窗口 '铭铭' 不能因此拿到同一份数据（否则两个窗口继续共用记忆）。
        #    命中即迁移，避免迁移期间"读旧目录、写新目录"出现分裂。
        scan = self._scan_legacy()
        storage_key = self._migration_target_for(raw, scan)
        if storage_key is not None:
            return storage_key

        # 5) 台账里的别名（例：窗口名 '铭铭.' 迁移后目录名是 '铭铭'，落地 key 按
        #    原始名算 → 直接查台账，避免又建一个空目录、把老记忆"弄丢"）
        alias_key = self._ledger_alias_key(raw)
        if alias_key:
            return alias_key

        # 6) 兜底：这个存储标识已经属于别的窗口名 → 绝不共用目录
        #    （防的是"窗口名恰好等于别人的存储标识"，例如群名被改成 X~<sha256>）
        self._scan_emitted_keys()
        taken = self._emitted_keys.get(raw)
        if taken is not None and taken != raw and not self._is_owner_key(raw):
            return self._conflict_key(raw, raw)        # 7) 常规路径：按根目录长度自适应可读名上限，避免完整路径超过 MAX_PATH
        key = self._canonical_key(raw)
        owner = self._emitted_keys.get(key)
        if owner is not None and owner != raw:
            return self._conflict_key(raw, key)
        return key

    def _canonical_key(self, raw):
        """窗口名 → 存储标识（与模块级 resolve_storage_key 完全同一份规则）。

        包含 base_dir + wx_id 的自适应长度与 MAX_PATH 保护，
        因此机器人、面板、预演工具算出来的一定是同一个目录。
        """
        return resolve_storage_key(raw, self.base_dir, self.wx_id)

    def _conflict_key(self, raw, taken_key):
        """窗口名与已有存储标识撞车时的兜底标识（加前缀后重新哈希，绝不共用目录）。"""
        fallback = f'chatname:{raw}'
        key = self._canonical_key(fallback)
        if key == taken_key:                    # 理论上不可能，保险起见
            key = self._canonical_key(fallback * 2)
        _warn(f"窗口名 {raw!r} 与已有存储标识撞车，改用隔离标识 {key!r}")
        return key

    def _migration_target_for(self, owner_name, scan=None):
        """某个窗口名是否是某个旧目录的 owner；是则迁移并返回它的存储标识。

        ⚠ 迁移失败时不能把旧目录标记成已处理：
          - 不加入 `_handled_legacy_dirs`、不从 scan['migrate'] 里摘掉，
            下一次访问会再次尝试（旧数据仍在旧目录里，不会丢）；
          - 但存储标识照样返回，读写不因此中断 —— 新消息写进新目录，
            之后迁移成功时由 `_merge_legacy_history` 把旧历史并进去
            （不会用旧历史覆盖期间产生的新消息）。

        ⚠ 迁移与合并全过程持有该会话的互斥锁：`_merge_legacy_history` 是
          "读目标 → 补旧消息 → 写回"，若和并发保存交错（保存读到旧内容、
          合并写入、保存再写回自己的副本），并进去的旧历史会被覆盖掉。
          本方法是 `resolve_storage_key()` 的下游，而所有调用方都在
          `resolve_storage_key()` **之后**才去拿会话锁（`_store_lock`、
          `_delete_session_dir` 等），因此这里加锁不会自锁。
        """
        scan = scan if scan is not None else self._scan_legacy()
        for legacy_name, value in list(scan['migrate'].items()):
            if value[1] != owner_name:
                continue
            storage_key = value[0]
            if self.migrate_legacy:
                with self._get_lock(storage_key):
                    with self._session_file_lock(storage_key):
                        try:
                            ok = self.migration.migrate_owner(
                                self.wx_id, legacy_name, storage_key,
                                alias_original=owner_name)
                        except Exception as e:
                            ok = False
                            _warn(f"迁移旧记忆目录失败（保留待重试） "
                                  f"{self.wx_id}/{legacy_name}: {e}")
                if not ok:
                    return storage_key        # 保持待处理状态，下次重试
                self._handled_legacy_dirs.add(legacy_name)
                scan['migrate'].pop(legacy_name, None)
            return storage_key
        return None

    def _quarantine_legacy_dir(self, legacy_name, reason):
        """把旧目录移入隔离区；失败返回 False（保持待处理状态）。"""
        try:
            self.migration.apply([{
                'wx_id': self.wx_id,
                'legacy_name': legacy_name,
                'action': 'quarantine',
                'reason': reason,
            }])
        except Exception as e:
            _warn(f"隔离归属不明的旧记忆目录失败（保留待重试） {self.wx_id}/{legacy_name}: {e}")
            return False
        return True

    def _is_owner_key(self, storage_key, chat_name=None):
        """该存储标识是否确实属于 `chat_name`（靠目录内的 name.json 自证）。

        用于测试与排查：目录存在、且 name.json 记录的原始名重算出来的存储标识
        就是这个目录名，才算"归属确认"。
        """
        key = str(storage_key)
        if not is_storage_key(key):
            return False
        chat_dir = os.path.join(self.base_dir, key)
        if not _is_real_dir(chat_dir):
            return False
        recorded = _read_recorded_name(chat_dir)
        if recorded is None:
            return False
        if chat_name is not None and str(recorded) != str(chat_name):
            return False
        return resolve_storage_key(recorded) == key

    def _scan_emitted_keys(self):
        """（惰性、每实例一次）登记磁盘上已有存储标识的 owner。

        用于识别"窗口名恰好等于别人的存储标识"：那种名字算出来的哈希与真实窗口
        不同，但名字部分一样，只看名字无法区分，必须核对目录里 name.json 的 owner。
        ⚠ 只登记有 name.json 且 owner 非空的目录：没有 name.json 的老目录无法
          证明归属，按旧行为放行（兼容非常老的目录布局）。
        """
        if self._emitted_scanned:
            return
        self._emitted_scanned = True
        try:
            names = os.listdir(long_path(self.base_dir))
        except OSError:
            return
        for name in names:
            if not _is_new_format_dir_name(name):
                continue
            recorded = _read_recorded_name(os.path.join(self.base_dir, name))
            if recorded:
                self._register_emitted_key(name, recorded)

    def _register_emitted_key(self, storage_key, owner_name):
        """登记"某个存储标识属于某个窗口名"，用于识别"窗口名恰好等于别人的 key"。"""
        if not storage_key or not owner_name:
            return
        key = str(storage_key)
        owner = str(owner_name)
        if is_storage_key(key) and key == owner:
            return                      # 存储标识不能自己认领自己
        self._emitted_keys[key] = owner

    def _ledger_alias_key(self, raw):
        """查迁移台账：某个**原始窗口名**是否已经被迁移到确定的存储标识。

        ⚠ 只认 `alias_original`（旧代码当时用的窗口名），**不认旧目录名**：
          目录 '铭铭' 的 owner 是 '铭铭.'，窗口 '铭铭' 不能因为"目录名也是铭铭"
          就解析到那份数据 —— 那正是两个窗口共用一份记忆的另一种写法。
        """
        try:
            ledger = self.migration.load_ledger()
        except Exception:
            return ''
        for entry in ledger.get('entries', []):
            if entry.get('wx_id') != self.wx_id:
                continue
            if entry.get('status') not in ('migrated', 'quarantined'):
                continue
            alias = entry.get('alias_original')
            if not alias or alias != raw:
                continue
            key = entry.get('storage_key') or ''
            if key and _is_real_dir(os.path.join(self.base_dir, key)):
                return key
        return ''

    def _quarantine_ambiguous_legacy(self, raw):
        """把"可能与 raw 属于同一个窗口、但归属不明"的旧目录移入隔离区。

        候选主人 = 目录名 或 目录里 name.json 记录的原始名（两者都可能指代它）。
        """
        scan = self._scan_legacy()
        if not scan['quarantine'] or not self.migrate_legacy:
            return
        raw = str(raw)
        for legacy_name in list(scan['quarantine']):
            chat_path = os.path.join(self.base_dir, legacy_name)
            candidates = {legacy_name}
            recorded = _read_recorded_name(chat_path)
            if recorded:
                candidates.add(recorded)
            if raw not in candidates:
                continue
            # 隔离失败同样保持待处理状态，下次再试；绝不假装已经处理完
            if not self._quarantine_legacy_dir(legacy_name, scan['quarantine'][legacy_name]):
                continue
            scan['quarantine'].pop(legacy_name, None)

    def _storage_dir(self, chat_name):
        """返回该窗口的记忆目录（不创建）。"""
        return os.path.join(self.base_dir, self.resolve_storage_key(chat_name))

    def _get_memory_path(self, chat_name):
        """返回记忆文件路径，并确保目录存在。

        ⚠ 这里必须和 `_storage_dir` 用同一种解析（都带 base_dir + wx_id 的自适应长度），
          否则长窗口名会出现"目录建在 A、文件写到 B"。
        """
        storage_key = self.resolve_storage_key(chat_name)
        dir_path = os.path.join(self.base_dir, storage_key)
        os.makedirs(long_path(dir_path), exist_ok=True)
        name_path = os.path.join(dir_path, ORIGINAL_NAME_FILE)
        if not os.path.exists(long_path(name_path)):
            self._write_original_name(dir_path, chat_name)
        # 登记归属：之后有"窗口名恰好等于这个存储标识"的窗口出现时能被识别出来
        self._register_emitted_key(storage_key, chat_name)
        return os.path.join(dir_path, memory_file_name(storage_key))

    # 兼容旧调用点：旧签名返回 (目录名, 是否需要写 name.json)
    @classmethod
    def _resolve_storage_name(cls, chat_name):
        return resolve_storage_key(chat_name), True

    @staticmethod
    def _hash_storage_name(name):
        return hash_storage_name(name)

    @staticmethod
    def _write_original_name(dir_path, chat_name):
        name_path = os.path.join(dir_path, ORIGINAL_NAME_FILE)
        try:
            write_json_atomic(name_path, {"name": str(chat_name)}, indent=2)
        except Exception as e:
            _warn(f"写入记忆原始名称记录失败: {e}")

    # ---------------- 消息读写 ----------------

    @staticmethod
    def _normalize_message_time(message_time=None):
        """将外部传入的时间统一转成记忆文件使用的字符串格式。"""
        if isinstance(message_time, datetime):
            return message_time.strftime("%Y/%m/%d %H:%M:%S")
        if isinstance(message_time, str):
            message_time = message_time.strip()
            if message_time:
                return message_time
        return datetime.now().strftime("%Y/%m/%d %H:%M:%S")

    @staticmethod
    def _parse_message_time(message_time):
        """解析记忆时间字符串；解析失败时返回 None，避免影响主流程。"""
        if not message_time:
            return None
        try:
            return datetime.strptime(str(message_time), "%Y/%m/%d %H:%M:%S")
        except Exception:
            return None

    def _append_message_in_order(self, messages, entry, recent_count=5):
        """在最近 recent_count 条范围内按时间插入，修正回调并发导致的乱序写入。"""
        current_dt = self._parse_message_time(entry.get("time"))
        if current_dt is None or not messages:
            messages.append(entry)
            return messages

        recent_start = max(0, len(messages) - recent_count)
        recent_messages = messages[recent_start:]
        has_later_recent = False
        for item in recent_messages:
            item_dt = self._parse_message_time(item.get("time"))
            if item_dt and item_dt > current_dt:
                has_later_recent = True
                break

        if not has_later_recent:
            messages.append(entry)
            return messages

        # 只重排尾部最近几条，既能修正本次乱序，也避免每次写入都全量排序。
        sortable_recent = []
        for idx, item in enumerate(recent_messages):
            item_dt = self._parse_message_time(item.get("time")) or datetime.max
            sortable_recent.append((item_dt, idx, item))
        sortable_recent.append((current_dt, len(recent_messages), entry))
        sortable_recent.sort(key=lambda x: (x[0], x[1]))
        messages[recent_start:] = [item for _, _, item in sortable_recent]
        return messages

    def save_message(self, chat_name, sender, content, msg_type, msg_attr, max_count, message_time=None):
        """写入一条消息到记忆文件，超出 max_count 时删除最旧的。"""
        entry = {
            "time":    self._normalize_message_time(message_time),
            "type":    str(msg_type),
            "attr":    str(msg_attr),
            "sender":  str(sender),
            "content": str(content),
        }
        with self._store_lock(chat_name):
            path = self._get_memory_path(chat_name)
            messages = self._read_messages_file(path)
            messages = self._append_message_in_order(messages, entry, recent_count=5)
            if len(messages) > max_count:
                messages = messages[-max_count:]
            write_json_atomic(path, messages, indent=2)

    def get_messages(self, chat_name, count):
        """读取最近 count 条记忆，返回 list。

        不加锁：写入方是「唯一临时文件 + 原子替换」，读方最多读到替换前或替换后的
        完整内容，永远不会读到半个 JSON；加锁反而会让高频的 AI 上下文读取互相排队。
        """
        path = self._memory_path_if_exists(chat_name)
        if not path:
            return []
        messages = read_json_file(path, None)
        if isinstance(messages, list):
            return messages[-count:]
        return []

    def clear_messages(self, chat_name):
        """清空指定会话的对话记忆（与保存共用同一把锁）。"""
        with self._store_lock(chat_name):
            path = self._get_memory_path(chat_name)
            write_json_atomic(path, [], indent=2)

    def clear_all_messages(self):
        """清空所有会话的对话记忆，返回清除的会话数。

        ⚠ 必须逐个会话走 `clear_messages`（同一把锁、同一个入口），
          不能直接遍历目录写空数组：那样会和正在读改写记忆文件的保存线程交错，
          出现「保存线程写回旧历史 + 新消息」把清空撤销掉。
        """
        count = 0
        for storage_key in self.list_storage_keys():
            try:
                self.clear_messages(storage_key)
                count += 1
            except Exception as e:
                _warn(f"清空记忆失败 {self.wx_id}/{storage_key}: {e}")
        return count

    # ---------------- 删除（面板删除走这里，不再自己 rmtree） ----------------

    def delete_chat(self, chat_name):
        """删除某个窗口的全部记忆（含目录），返回是否删除了内容。"""
        storage_key = self._delete_storage_key(chat_name)
        if not storage_key:
            return False
        return self._delete_storage_locked(storage_key)

    def delete_all(self):
        """删除当前微信号（wx_id）下的全部会话记忆，返回删除的会话数。

        面板的「删除该微信全部记忆」和机器人的清空都走这里。
        每个会话独立按「加锁 → 改名成墓碑 → 释放锁 → 删墓碑」处理：
        - 语用上等价于"清空该会话"（排在删除之前的保存结果都会被清掉）；
        - 排在删除之后成功保存的新消息写进新建的干净目录，不会被墓碑清理抹掉；
        - 某个会话失败不影响其他会话，也不虚报成功（计数只算真的删掉的）。
        """
        keys = self.list_storage_keys()
        if not keys:
            self.remove_empty_subdirs()
            return 0

        deleted = 0
        for storage_key in keys:
            if self._delete_storage_locked(storage_key):
                deleted += 1
        self.remove_empty_subdirs()
        return deleted

    def delete_account(self):
        """删除当前微信号下的全部记忆（含迁移遗留的旧目录），返回删除的会话数。

        面板的「删除该微信全部记忆」走这里。注意：
        - 只删记忆数据本身，保留 name.json 等目录内文件（旧实现在这里直接
          rmtree 整个目录，等于绕过会话锁删库）；
        - `_quarantine/` 不动：隔离区里是"归属不明、待人工处理"的历史，
          误删就真没了。
        - 与 delete_all 共用同一套"加锁改名再删"的保护，失败不虚报。
        """
        keys = self.list_storage_keys()
        if not keys:
            self.remove_empty_subdirs()
            return 0

        deleted = 0
        for storage_key in keys:
            if self._delete_storage_locked(storage_key):
                deleted += 1
        self.remove_empty_subdirs()
        return deleted

    def _delete_storage_key(self, chat_name):
        """删除入口的标识解析：优先按磁盘上真实存在的目录删，避免误删/漏删。

        面板可能传「存储标识」，也可能传「窗口名 / name.json 里记录的原始名」，
        三种都要能命中（删除路径只允许有一条，不能再让面板自己拼路径 rmtree）。

        ⚠ 返回值必须是 base_dir 下的**一层目录名**：面板的 chat_name 来自 URL 路径段，
          若把 r'..\\..\\某个目录' 原样返回，后面拼出来的路径就跑到了记忆根目录外面，
          删除会落到别人的目录上。
        """
        raw = str(chat_name)
        if not raw:
            return ''
        # 0) 已经是本程序登记过的存储标识（面板列表回传）→ 原样使用，
        #    否则自适应长度差会让它被重新算成另一个目录
        if _is_new_format_dir_name(raw) and _is_real_dir(
                os.path.join(self.base_dir, raw)) and self._is_owner_key(raw, raw):
            return raw
        # 1) 直接就是磁盘上存在的目录名
        if self._is_safe_storage_name(raw) and _is_real_dir(os.path.join(self.base_dir, raw)):
            return raw
        # 2) 窗口名 → 存储标识（含归属明确的旧目录迁移，逻辑与保存完全一致）
        key = self.resolve_storage_key(raw)
        if self._is_safe_storage_name(key) and _is_real_dir(os.path.join(self.base_dir, key)):
            return key
        # 3) name.json 里记录的原始名（显示名可能与目录名不同，例如 "张三. " → "张三"）
        for storage_key in self.list_storage_keys():
            chat_dir = os.path.join(self.base_dir, storage_key)
            if read_original_name(chat_dir, storage_key) == raw:
                return storage_key
        return ''

    @staticmethod
    def _is_safe_storage_name(name):
        """目录名必须是不含路径分隔符的单层名字（防越界删除）。"""
        name = str(name)
        if not name or name in ('.', '..'):
            return False
        return name == os.path.basename(name) and '/' not in name and '\\' not in name

    def _delete_storage_locked(self, storage_key):
        """删除单个会话的全部记忆：加锁 → 改名成墓碑 → 释放锁 → 删墓碑。

        ⚠ 不能在锁外直接 rmtree：
          保存路径是「读 → 改 → 写回」，若在"删完记忆文件"与"删目录"之间
          有保存成功落盘，那条新消息会被随后的目录清理连带删掉（静默丢数据）。
          改名成墓碑后，后续保存写入的是全新的同名目录，与墓碑无关。
        """
        chat_dir = os.path.join(self.base_dir, storage_key)
        if not _is_real_dir(chat_dir):
            return False
        if not self._delete_session_dir(storage_key):
            return False
        self.remove_empty_subdirs()
        return True


    def remove_empty_subdirs(self):
        """清理残留的空目录与孤儿墓碑。

        - 空目录：删除会话后常留一个空壳，下次清理掉；
        - `.deleting/`：删除会话时"改名 → 删墓碑"，若进程在两步之间退出，
          会留下孤儿墓碑，这里按会话加锁后清理；
        - `.locks/` **不清理**：锁文件必须保持稳定。若在删除会话时把锁文件
          一并删掉，另一个进程可能正阻塞在这个文件上（等着拿锁），
          删掉后它会继续在旧 inode 上拿锁，而我们又新建一个同名文件，
          两个进程就同时持有了"同一把锁"，互斥失效。锁文件很小，
          留在磁盘上是最安全的选择。
        """
        try:
            entries = os.listdir(long_path(self.base_dir))
        except OSError:
            return

        for name in entries:
            if name == DELETING_DIR_NAME:
                self._prune_tombstones(os.path.join(self.base_dir, name))
                continue
            if name == LOCKS_DIR_NAME:
                continue
            path = os.path.join(self.base_dir, name)
            if not _is_real_dir(path):
                continue
            try:
                os.rmdir(long_path(path))   # 只删空目录，非空/被占用则跳过
            except OSError:
                pass

    def _prune_tombstones(self, deleting_dir):
        """清理孤儿墓碑：加会话锁后整目录删除。"""
        try:
            names = os.listdir(long_path(deleting_dir))
        except OSError:
            return
        for name in names:
            path = os.path.join(deleting_dir, name)
            with self._get_lock(name):
                with self._session_file_lock(name):
                    self._remove_path(path)
        try:
            os.rmdir(long_path(deleting_dir))
        except OSError:
            pass

    @staticmethod
    def _list_all_memory_files(chat_dir):
        try:
            return [f for f in os.listdir(long_path(chat_dir)) if f.endswith(MEMORY_FILE_SUFFIX)]
        except OSError:
            return []

    @staticmethod
    def _remove_path(path):
        """递归删除一个路径；失败只告警、不虚报成功。返回是否已不存在。"""
        if not path:
            return True
        # 目录名末尾可能是 '.' 等被 Windows 规范化的字符，用长路径前缀绕过
        probe = long_path(path)
        if not os.path.exists(probe):
            return True
        shutil.rmtree(probe, ignore_errors=True)
        return not os.path.exists(probe)

    # ---------------- 枚举 ----------------

    def list_storage_keys(self):
        """列出当前微信号下所有记忆目录的存储标识（不含内部目录/隔离区）。"""
        keys = []
        try:
            entries = sorted(os.listdir(long_path(self.base_dir)))
        except OSError:
            return keys
        for name in entries:
            if is_internal_dir_name(name):
                continue
            if not _is_real_dir(os.path.join(self.base_dir, name)):
                continue
            keys.append(storage_key_from_dir_name(name) or name)
        return keys

    def list_legacy_entries(self):
        """返回需要人工关注的信息：隔离区里的旧目录 + 迁移台账。"""
        return {
            'quarantine_root': self.migration.quarantine_root,
            'ledger_path': self.migration.ledger_path,
            'pending': self.migration.scan(),
        }

    # ---------------- 内部读取 ----------------

    def _read_messages_file(self, path):
        """读取记忆文件；内容损坏时视为空历史（与旧实现一致）。"""
        messages = read_json_file(path, None)
        return messages if isinstance(messages, list) else []

    def _memory_path_if_exists(self, chat_name):
        """找记忆文件：先按存储标识算，找不到再兼容旧目录里的任意 *_memory.json。

        ⚠ 注意顺序：先 `resolve_storage_key()`（内部会把归属不明的旧目录隔离掉），
          再谈"回退读旧目录"。否则两个窗口都会回退读到同一个混合了数据的旧目录
          —— 这是身份碰撞事故的第二种表现：不是写了同一个文件，而是都读了同一个
          遗留目录。
        """
        storage_key = self.resolve_storage_key(chat_name)
        chat_dir = os.path.join(self.base_dir, storage_key)
        direct = os.path.join(chat_dir, memory_file_name(storage_key))
        if os.path.exists(long_path(direct)):
            return direct

        if _is_new_format_dir_name(storage_key):
            return ''
        # 旧目录已经被迁移/隔离掉了 → 不能再去读它（否则"两个窗口共用一份历史"
        # 会以"回退读遗留目录"的形式复活）。判断依据：本进程刚处理过，或磁盘台账里
        # 已有终态记录（跨进程/重启后同样成立）。
        legacy_name = storage_key
        if legacy_name in self._handled_legacy_dirs or self._ledger_handled(legacy_name):
            return ''
        try:
            candidates = sorted(
                f for f in os.listdir(long_path(chat_dir)) if f.endswith(MEMORY_FILE_SUFFIX)
            )
        except OSError:
            return ''
        if not candidates:
            return ''
        return os.path.join(chat_dir, candidates[0])

    def _ledger_handled(self, legacy_name):
        """台账里是否已记录该旧目录的迁移/隔离结果。"""
        try:
            ledger = self.migration.load_ledger()
        except Exception:
            return False
        for entry in ledger.get('entries', []):
            if (entry.get('wx_id') == self.wx_id
                    and entry.get('legacy_name') == legacy_name
                    and entry.get('status') in ('migrated', 'quarantined')):
                return True
        return False


def _warn(message):
    """记忆存储模块自己的告警出口（不依赖项目 logger，保持可独立导入）。"""
    try:
        import logger as _logger
        _logger.log(level="WARNING", message=message)
    except Exception:
        pass


# ============================================================
# 进程内共享的 MemoryManager 实例
#
# 机器人和管理面板跑在同一个进程（面板机器人线程里 new 的 WXBot，
# 见 web_server._bot_runner），
# 但两侧都可能先访问记忆：面板列表/读取/删除、机器人写消息。
# 如果各自 new 一个 MemoryManager，虽然锁是按存储标识取的、能互斥，
# 但"面板看到的目录"和"机器人写的目录"会各自迁移一遍，仍然浪费且危险。
# 因此统一从这里取实例。
# ============================================================

_MANAGER_REGISTRY = {}
_MANAGER_REGISTRY_GUARD = threading.Lock()


def _default_memory_base():
    """默认记忆根目录，与历史行为一致：{运行目录}/memory。

    打包后（sys._MEIPASS）取 exe 所在目录，与 wxbot_core 里的算法保持一致。
    """
    import sys
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(os.path.dirname(sys.executable), 'memory')
    return os.path.join(os.path.abspath('.'), 'memory')


def get_memory_manager(wx_id, base_path=None):
    """取（必要时创建）某个微信号的 MemoryManager，整个进程共用同一个实例。

    :param wx_id: 微信号目录名（机器人启动时从 GetMyInfo 拿到）
    :param base_path: 记忆根目录；省略时用 {运行目录}/memory
    """
    base = base_path or _default_memory_base()
    key = (os.path.abspath(base), str(wx_id))
    with _MANAGER_REGISTRY_GUARD:
        manager = _MANAGER_REGISTRY.get(key)
        if manager is None:
            manager = MemoryManager(wx_id, base)
            _MANAGER_REGISTRY[key] = manager
        return manager


def forget_memory_manager(wx_id, base_path=None):
    """丢弃注册表里的实例（仅测试/热重载用）。"""
    base = base_path or _default_memory_base()
    key = (os.path.abspath(base), str(wx_id))
    with _MANAGER_REGISTRY_GUARD:
        return _MANAGER_REGISTRY.pop(key, None)

