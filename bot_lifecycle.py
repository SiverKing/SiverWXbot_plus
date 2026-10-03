# -*- coding: utf-8 -*-
"""bot_lifecycle.py —— 面板进程内唯一的机器人生命周期入口。

为什么要有这个对象
------------------
启停机器人牵动四样东西：**实例、线程、状态、停止信号**。原先它们分散在
web_server 的 ``bot`` / ``bot_thread`` 两个全局变量与 ``WXBot.run_flag`` 里，
于是留下三个必然踩到的窗口：

a) 线程已活、实例尚未赋值
   停止入口按 ``bot_thread.is_alive()`` 判断在运行，随后直接调
   ``bot.stop_wxbot()`` —— 此时 ``bot`` 还是 None，直接 AttributeError。

b) 初始化中收到停止
   停止把 ``run_flag`` 置成 False，但初始化流程结束时又无条件
   ``self.run_flag = True``，停止信号被抹掉，机器人继续跑。

c) 停止不等人退完就清空引用
   ``stop`` 返回后立刻把实例/线程置 None，而线程可能还在退出中；
   紧接着再点启动，新线程与旧线程同时活着 —— 两个机器人同时监听。

本模块把四样东西收进一个对象，并约定：

* 状态机 ``stopped → starting → running → stopping → stopped``，任何时刻
  最多只有一个实例、一条线程；
* **只有线程确认退出之后**才清空实例与线程引用（解决 c）；
* 停止先置 ``stop_event``，再按需调用实例的停止方法；实例还没造出来时
  碰都不碰它，线程构造完成后自己查停止信号收尾（解决 a）；
* 停止信号是 ``threading.Event``，机器人初始化结束时必须查它来决定要不要
  开跑，而不是无条件开跑（解决 b）；
* ``starting`` / ``stopping`` 状态下启动一律拒绝或等待，绝不允许两条线程重叠。

调用约定
--------
面板手动启停（``/start_bot`` ``/stop_bot``）、定时启停线程、重启，**全部只调它**。
其它任何模块都不应当再自己 ``threading.Thread(target=...)`` 起机器人线程、
或自己维护一份运行状态。

本模块零 Flask / 零 wxautox 依赖，可在没有微信环境的机器上直接单元测试。
"""

from __future__ import annotations

import threading
import time

from logger import log

# ============================================================
# 状态
# ============================================================
STATE_STOPPED  = 'stopped'    # 已停止（没有活线程，实例引用已清空）
STATE_STARTING = 'starting'   # 启动中（线程已起，实例还没造出来）
STATE_RUNNING  = 'running'    # 运行中（实例已登记，主循环在跑或即将开跑）
STATE_STOPPING = 'stopping'   # 停止中（停止信号已置，线程还没退完）

STATE_LABELS = {
    STATE_STOPPED:  '已停止',
    STATE_STARTING: '启动中',
    STATE_RUNNING:  '运行中',
    STATE_STOPPING: '停止中',
}

ACTIVE_STATES = (STATE_STARTING, STATE_RUNNING, STATE_STOPPING)

# 停止时最多等线程退出多久；启动时最多等上一次停止走完多久。
# 两者都只是"确认窗口"，超时不会强杀线程，也不会误判为已停止。
DEFAULT_STOP_WAIT  = 20.0
DEFAULT_START_WAIT = 20.0


def state_label(state):
    """状态的中文名，日志与接口提示共用一份。"""
    return STATE_LABELS.get(state, state)


class StartOutcome:
    """启动请求的结果。"""

    __slots__ = ('started', 'state', 'message', 'waited')

    def __init__(self, started, state, message, waited=0.0):
        self.started = bool(started)
        self.state = state
        self.message = message
        self.waited = waited

    def to_dict(self):
        return {
            'started': self.started,
            'state': self.state,
            'state_label': state_label(self.state),
            'message': self.message,
            'waited': round(self.waited, 3),
        }

    def __repr__(self):
        return f'<StartOutcome started={self.started} state={self.state} {self.message!r}>'


class StopOutcome:
    """停止请求的结果。

    ``code`` 给调用方（面板 / 前端流程）区分"为什么没停成"：

    * ``stopped``     —— 已确认停止（或本来就没运行）；
    * ``timeout``     —— 线程未在确认窗口内退出，状态保持「停止中」，可以继续轮询；
    * ``superseded``  —— 停止期间另一次启动已经跑起来了（并发调用），
                         此时**不该**当成"还在停"，也不该谎报已停止。
    """

    __slots__ = ('stopped', 'state', 'message', 'bot_stopped', 'waited', 'timed_out', 'code')

    def __init__(self, stopped, state, message, bot_stopped=None, waited=0.0,
                 timed_out=False, code=None):
        self.stopped = bool(stopped)
        self.state = state
        self.message = message
        self.bot_stopped = bot_stopped     # 实例的 stop_wxbot() 是否返回成功；实例未就绪时为 None
        self.waited = waited
        self.timed_out = bool(timed_out)
        if code is None:
            code = 'stopped' if self.stopped else ('timeout' if self.timed_out else 'superseded')
        self.code = code

    def to_dict(self):
        return {
            'stopped': self.stopped,
            'state': self.state,
            'state_label': state_label(self.state),
            'message': self.message,
            'bot_stopped': self.bot_stopped,
            'waited': round(self.waited, 3),
            'timed_out': self.timed_out,
            'code': self.code,
        }

    def __repr__(self):
        return f'<StopOutcome stopped={self.stopped} code={self.code} state={self.state} {self.message!r}>'


class RunHandle:
    """交给机器人线程的句柄：登记实例 + 查询停止信号。

    线程体（由调用方提供）必须：

    1. 构造出机器人实例后立刻 ``handle.bind(bot)`` —— 这样"线程已活但实例未就绪"
       的窗口里，停止入口知道该等它自己收尾，而不是去碰一个 None；
       登记成功且没有停止请求时，状态同时由「启动中」推进到「运行中」；
    2. 开跑之前 ``handle.should_stop()`` 判断一次 —— 初始化期间收到的停止请求
       不能因为"初始化完成了"就被丢掉；
    3. 之后调用 ``bot.run()``，主循环里持续查停止信号。
    """

    __slots__ = ('_lifecycle', 'stop_event', '_generation')

    def __init__(self, lifecycle, stop_event, generation):
        self._lifecycle = lifecycle
        self.stop_event = stop_event
        self._generation = generation

    def bind(self, bot):
        """把本次运行的机器人实例登记到生命周期对象。"""
        self._lifecycle._bind_bot(bot, self._generation)

    def should_stop(self):
        """是否已收到停止请求（面板停止 / 定时停止 / 生命周期停止都会置位）。"""
        return self.stop_event.is_set()


class BotLifecycle:
    """机器人生命周期：实例、线程、状态、停止 Event 的唯一持有者。

    :param name:       线程名前缀与日志里的名字
    :param stop_wait:  ``stop()`` 默认等待线程退出的秒数
    :param start_wait: ``start()`` 默认等待上一次停止走完的秒数
    """

    def __init__(self, name='siver_wxbot', *, stop_wait=DEFAULT_STOP_WAIT,
                 start_wait=DEFAULT_START_WAIT):
        self.name = name
        self.stop_wait = float(stop_wait)
        self.start_wait = float(start_wait)

        self._lock = threading.RLock()
        self._bot = None
        self._thread = None
        self._state = STATE_STOPPED
        self._stop_event = threading.Event()

        self._generation = 0        # 每启动一次 +1，线程体用它对号入座，避免旧线程改新状态
        self._start_count = 0       # 累计启动次数（验收"连点两次启动只有一个实例"）
        self._last_error = None
        self._last_stop_reason = None
        self._last_start_at = None
        self._last_stop_at = None
        # 上一次运行结束后保留下来的实例：线程已死，但它可能还留着未清理的监听，
        # 下一次启动前由线程体取走做一次兜底清理（唯一一个，不会越攒越多）。
        self._previous_bot = None

    # ------------------------------------------------------------------
    # 查询（全部持锁取值，避免读到半更新的状态）
    # ------------------------------------------------------------------

    @property
    def state(self):
        with self._lock:
            return self._state

    @property
    def bot(self):
        with self._lock:
            return self._bot

    @property
    def thread(self):
        with self._lock:
            return self._thread

    @property
    def stop_event(self):
        return self._stop_event

    @property
    def start_count(self):
        with self._lock:
            return self._start_count

    def is_active(self):
        """是否存在"还没结束"的运行（含启动中/停止中）。"""
        with self._lock:
            return self._state in ACTIVE_STATES

    def is_running(self):
        """是否处于"应该在监听"的状态（启动中/运行中）。停止中不算。"""
        with self._lock:
            return self._state in (STATE_STARTING, STATE_RUNNING)

    def is_stopping(self):
        with self._lock:
            return self._state == STATE_STOPPING

    def take_previous_bot(self):
        """取走上一次运行留下的实例（没有则返回 None），只取一次。

        用途：启动新实例之前，对上一个实例做一次兜底收尾。正常情况下上一轮退出时
        已经清理干净（``shutdown()`` 幂等），这里是防"线程异常死亡/进程内残留监听"。
        """
        with self._lock:
            bot, self._previous_bot = self._previous_bot, None
            return bot

    def snapshot(self):
        """给状态接口用的快照。"""
        with self._lock:
            thread = self._thread
            return {
                'state': self._state,
                'state_label': state_label(self._state),
                'bot_running': self._state in (STATE_STARTING, STATE_RUNNING),
                'thread_alive': bool(thread is not None and thread.is_alive()),
                'bot_ready': self._bot is not None,
                'start_count': self._start_count,
                'generation': self._generation,
                'last_error': self._last_error,
                'last_stop_reason': self._last_stop_reason,
            }

    # ------------------------------------------------------------------
    # 启动
    # ------------------------------------------------------------------

    def start(self, runner, *, reason='手动启动', wait_for_previous=True):
        """启动机器人线程。

        :param runner: 线程体，签名 ``runner(handle)``，在**新线程**里执行；
                       构造机器人实例、登记（``handle.bind``）、跑主循环都由它完成。
                       返回即表示本次运行结束（正常结束或异常退出都一样）。
        :param reason: 日志里的启动来源（手动启动 / 定时启动 / 重启 …）
        :return: :class:`StartOutcome`
        """
        if not callable(runner):
            raise TypeError('runner 必须是可调用对象：runner(handle)')

        waited = 0.0
        with self._lock:
            state = self._state
            if state in (STATE_STARTING, STATE_RUNNING):
                message = f'机器人已在运行（{state_label(state)}），未重复启动'
                log('WARNING', f'[{reason}] {message}')
                return StartOutcome(False, state, message)
            pending = self._thread if self._state == STATE_STOPPING else None
            if pending is None and self._thread is not None and self._thread.is_alive():
                # 状态已回到 stopped 但线程尚未彻底退出（线程 finally 与 is_alive 之间的
                # 毫秒级窗口）：同样按"还没退完"处理，绝不与新线程重叠。
                pending = self._thread

        if pending is not None:
            if not wait_for_previous:
                message = f'上一次停止尚未完成（{state_label(self._state)}），请稍后再启动'
                log('WARNING', f'[{reason}] {message}')
                return StartOutcome(False, self._state, message)
            waited = self._join(pending, self.start_wait)
            with self._lock:
                still_alive = self._thread is not None and self._thread.is_alive()
                if still_alive:
                    message = (f'上一次运行仍未退出（{state_label(self._state)}），'
                               f'本次启动已取消：等它退完再启动，避免两条线程同时监听')
                    log('ERROR', f'[{reason}] {message}')
                    return StartOutcome(False, self._state, message, waited=waited)

        with self._lock:
            if self._state in ACTIVE_STATES:
                # 极端并发（两个请求同时进来）：后到的那个在这里被挡住
                state = self._state
                message = f'机器人已在运行（{state_label(state)}），未重复启动'
                log('WARNING', f'[{reason}] {message}')
                return StartOutcome(False, state, message, waited=waited)

            # 新一代：新的停止 Event + 新的代次号
            self._stop_event = threading.Event()
            self._generation += 1
            generation = self._generation
            stop_event = self._stop_event
            self._start_count += 1
            self._state = STATE_STARTING
            self._last_error = None
            self._last_start_at = time.time()
            thread = threading.Thread(
                target=self._thread_body,
                args=(generation, runner, stop_event),
                name=f'{self.name}-{generation}',
                daemon=True,
            )
            self._thread = thread
            try:
                thread.start()
            except Exception as e:
                # 线程都没起来（例如线程资源耗尽）：状态必须回滚，否则面板会一直
                # 显示"启动中"、再点启动还被当成"已在运行"，只能靠一次停止来复位。
                self._thread = None
                self._state = STATE_STOPPED
                self._start_count -= 1
                self._last_error = f'{type(e).__name__}: {e}'
                log('ERROR', f'[{reason}] 创建机器人线程失败: {e}')
                return StartOutcome(False, STATE_STOPPED, f'启动失败：{e}', waited=waited)

        message = f'启动命令已接收（{reason}），机器人正在初始化'
        log('INFO', f'[{reason}] {message}')
        return StartOutcome(True, STATE_STARTING, message, waited=waited)

    # ------------------------------------------------------------------
    # 停止
    # ------------------------------------------------------------------

    def stop(self, *, wait_timeout=None, reason='面板停止'):
        """停止机器人并**等线程真正退出**。

        顺序刻意如此：

        1. 先置 ``stop_event`` —— 实例还没造出来的窗口里，这是唯一的停止途径；
        2. 实例已就绪才调它的 ``stop_wxbot()``（停止监听 + 清定时任务）；
        3. 等线程退出；线程没退完就保持 ``stopping``，**不清空实例/线程引用**，
           下一次启动会被拒绝，不会出现两条线程重叠。

        :return: :class:`StopOutcome`；``stopped=False`` 表示超时未确认停止。
        """
        timeout = self.stop_wait if wait_timeout is None else float(wait_timeout)
        deadline = time.monotonic() + timeout

        with self._lock:
            thread = self._thread
            generation = self._generation
            alive = thread is not None and thread.is_alive()
            if not alive:
                # 没有活线程：清掉可能残留的引用，直接判定已停止
                self._reset_locked(generation=generation, thread=thread)
                self._last_stop_at = time.time()
                return StopOutcome(True, STATE_STOPPED, '机器人未运行，无需停止', waited=0.0)

            self._stop_event.set()
            self._state = STATE_STOPPING
            self._last_stop_reason = reason
            bot = self._bot

        # 先置信号、再动实例：实例可能还是 None（线程正在构造它），
        # 这时碰都别碰，等线程构造完自己看停止信号收尾。
        bot_stopped = None
        if bot is not None:
            # wxautox 的 StopListening 没有超时，卡住的话 /stop_bot 会永不返回
            # （面板重启按钮一直转圈 —— "假等待"的另一面）。给它一个时限。
            call_budget = max(0.5, timeout * 0.6)
            bot_stopped = self._call_stop_with_timeout(bot, call_budget, reason)

        remaining = max(0.0, deadline - time.monotonic())
        waited = self._join(thread, remaining)
        with self._lock:
            if thread.is_alive():
                message = (f'机器人仍在停止中：线程未在 {timeout:.0f} 秒内退出，'
                           f'已保持「停止中」状态，不会放行下一次启动')
                log('WARNING', f'[{reason}] {message}')
                return StopOutcome(False, STATE_STOPPING, message,
                                   bot_stopped=bot_stopped, waited=waited, timed_out=True,
                                   code='timeout')

            # 只清"仍是这一代"的引用：等待期间可能有新一次启动已经建好新线程，
            # 无条件清空会把新实例的引用抹掉，随后 start() 就会以为空闲而再起一个。
            self._reset_locked(generation=generation, thread=thread)
            self._last_stop_at = time.time()
            current_state = self._state
            if current_state != STATE_STOPPED:
                # 停止期间另一次启动已经起来了（并发调用）：如实回报，不谎报"已停止"
                message = (f'上一代运行已停止，但检测到新的运行（{state_label(current_state)}），'
                           f'当前并未处于已停止状态')
                log('WARNING', f'[{reason}] {message}')
                return StopOutcome(False, current_state, message,
                                   bot_stopped=bot_stopped, waited=waited, code='superseded')
            message = '机器人已停止' if bot_stopped is not False else '机器人已停止（实例停止方法报错，线程已退出）'
            log('SUCCESS', f'[{reason}] {message}')
            return StopOutcome(True, STATE_STOPPED, message,
                               bot_stopped=bot_stopped, waited=waited)

    # ------------------------------------------------------------------
    # 重启（停止 → 确认线程退出 → 启动，同一把锁内不允许插进另一次启动）
    # ------------------------------------------------------------------

    def restart(self, runner, *, reason='重启', wait_timeout=None):
        """原子重启：先停干净再启动。

        面板上的「重启载入新配置」按钮走的是 HTTP 的 stop + 轮询 + start，
        目的是让用户看到"确实停住了"；本方法是服务端等价物，两条路径共用同一份
        状态机，不会出现"某条路径绕过生命周期"。

        :return: ``(StopOutcome, StartOutcome 或 None)``；停止没确认成功时第二个为 None。
        """
        stop_outcome = self.stop(wait_timeout=wait_timeout, reason=reason)
        if not stop_outcome.stopped:
            return stop_outcome, None
        start_outcome = self.start(runner, reason=reason, wait_for_previous=False)
        return stop_outcome, start_outcome

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _thread_body(self, generation, runner, stop_event):
        """生命周期自己的线程体：只负责异常兜底与状态收尾。"""
        handle = RunHandle(self, stop_event, generation)
        try:
            runner(handle)
        except BaseException as e:      # noqa: BLE001 —— 线程里绝不能让异常逃逸
            import traceback
            with self._lock:
                if generation == self._generation:
                    self._last_error = f'{type(e).__name__}: {e}'
            log('ERROR', f'机器人线程异常退出: {type(e).__name__}: {e}\n{traceback.format_exc()}')
        finally:
            self._finish(generation)

    def _bind_bot(self, bot, generation):
        """线程体登记实例（只接受当前代次，旧线程不得改新状态）。

        实例就绪即视为「运行中」：停止请求已经到达时不改状态，让随后的
        ``should_stop()`` 分支收尾（状态由 stop() 置为「停止中」）。
        """
        with self._lock:
            if generation != self._generation:
                return False
            self._bot = bot
            if not self._stop_event.is_set() and self._state == STATE_STARTING:
                self._state = STATE_RUNNING
            return True

    def _finish(self, generation):
        """线程退出（无论怎么退）都走这里：只有此时才清空实例与线程引用。"""
        with self._lock:
            if generation != self._generation:
                return
            if self._bot is not None:
                self._previous_bot = self._bot
            self._bot = None
            self._thread = None
            self._state = STATE_STOPPED
            self._last_stop_at = time.time()
        log('INFO', '机器人线程已退出，运行状态已复位为「已停止」')

    def _reset_locked(self, generation=None, thread=None):
        """没有活线程时清空引用（调用方必须已持锁）。

        ⚠ 必须按"代次 + 线程对象"核对后再清：等待线程退出的这段时间里，
          可能已经有新一次启动把新线程/新实例放进来了；无条件清空会把新实例
          的引用抹掉，随后 start() 就会以为空闲而再起一个 —— 两条线程同时监听。

        :param generation: 调用方观察到的那一代；不一致则不动（说明已经有新的一代）
        :param thread:     调用方观察到的那条线程；当前引用不是它则不动
        """
        if generation is not None and generation != self._generation:
            return False
        if thread is not None and self._thread is not thread:
            return False
        if self._bot is not None:
            self._previous_bot = self._bot
        self._bot = None
        self._thread = None
        self._state = STATE_STOPPED
        return True

    @staticmethod
    def _join(thread, timeout):
        """等线程退出，返回实际等待秒数；绝不 join 自己（会抛 RuntimeError）。"""
        if thread is None or thread is threading.current_thread():
            return 0.0
        started = time.monotonic()
        thread.join(timeout)
        return time.monotonic() - started

    def _call_stop_with_timeout(self, bot, timeout, reason):
        """调用实例的 stop_wxbot()，但给它一个时限。

        为什么要单独起线程：``StopListening()`` 是 wxautox 的阻塞调用、没有超时，
        一旦它卡住，``/stop_bot`` 就永远不会返回，面板的重启按钮会一直转圈 ——
        这正是"假等待"的另一面。这里最多等 ``timeout`` 秒；超时只记日志，
        随后照常等机器人线程退出（大概率也超时 → 状态保持「停止中」，如实回报）。

        :return: True/False 为实例停止方法的返回值；None=超时未返回或未启动调用线程。
        """
        done = threading.Event()
        outcome = {'ok': None, 'error': None}

        def _call():
            try:
                outcome['ok'] = bool(bot.stop_wxbot())
            except Exception as e:      # noqa: BLE001
                outcome['error'] = e
            finally:
                done.set()

        worker = threading.Thread(target=_call, name=f'{self.name}-stop-call', daemon=True)
        try:
            worker.start()
        except Exception as e:
            log('ERROR', f'[{reason}] 无法启动停止调用线程: {e}')
            return None
        if not done.wait(timeout):
            log('WARNING', f'[{reason}] 实例停止方法 {timeout:.1f}s 内未返回'
                           f'（可能卡在 StopListening），继续等待机器人线程退出')
            return None
        if outcome['error'] is not None:
            log('ERROR', f'[{reason}] 调用实例停止方法出错: {outcome["error"]}')
            return False
        return outcome['ok']
