/* ============================================================
 * bot_restart.js —— 重启流程：等到「真实已停止」再启动
 *
 * 为什么单独成文件
 * ----------------
 * 面板原来的「重启载入新配置」是"点停止 → 固定等 4 秒 → 启动"。
 * 4 秒既不是"后台已经停了"的保证（StopListening 可能卡住），也不该被当成
 * 保证 —— 停止没完成就启动，会出现两条线程同时监听。
 *
 * 这里把流程写成纯逻辑：轮询 /get_status 直到 bot_state=stopped 才允许启动，
 * 超时给出明确提示。所有副作用（发请求、按钮文案、弹窗）都通过回调注入，
 * 因此可以在 Node 里直接验收（tests/verify_frontend_restart_flow.js）。
 *
 * 依赖的服务端字段：/get_status 返回 data.bot_state ∈
 *   stopped / starting / running / stopping（缺省时退化为 bot_running）
 * ============================================================ */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) { module.exports = api; }
  if (root) { root.BotRestart = api; }
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  // 停止确认窗口：给 StopListening + 线程退出留足时间；超时不是"失败"，是"没确认"
  var DEFAULT_TIMEOUT_MS = 30000;
  var DEFAULT_INTERVAL_MS = 800;
  // 单次 /get_status 请求的超时。与上面的"总预算"是两件事：
  //   预算是「多久之内必须确认停住」，单次超时是「这一发请求多久算没答上」。
  // 单次请求慢/没答上，不会让预算暂停、顺延或重置 —— 预算由独立计时器走着。
  var DEFAULT_REQUEST_TIMEOUT_MS = 8000;

  var STATE_LABELS = {
    stopped:  '已停止',
    starting: '启动中',
    running:  '运行中',
    stopping: '停止中',
    unknown:  '状态未知'
  };

  function stateOf(data) {
    if (!data) { return 'unknown'; }
    if (data.bot_state) { return String(data.bot_state); }
    // 兼容旧接口：没有 bot_state 时退化为 bot_running
    if (data.bot_running === true) { return 'running'; }
    if (data.bot_running === false) { return 'stopped'; }
    return 'unknown';
  }

  function labelOf(state) {
    return STATE_LABELS[state] || state || STATE_LABELS.unknown;
  }

  function isStopped(data) {
    return stateOf(data) === 'stopped';
  }

  /**
   * 轮询状态直到确认真实停止。
   *
   * 三条硬约束（都靠"唯一收口 + 独立截止计时器"实现）：
   *   1. 预算不依赖回调到达 —— 截止计时器自己走，请求挂住也会按时结束；
   *   2. 成功 / 失败 / 超时只结束一次，结束即清掉全部计时器、不再排下一次轮询；
   *   3. 结束之后的迟到回调一律丢弃：既不 resolve/reject，也不再发请求。
   *
   * @param {Object} opts
   *   fetchStatus(cb)     cb(err, data)：data 为 /get_status 的 data 字段
   *   timeoutMs           停止确认总预算（默认 30s）；到点 reject，原因区分 timeout / status_error
   *   intervalMs          轮询间隔（默认 800ms）
   *   requestTimeoutMs    单次请求超时（默认 8s）；只影响这一轮，不改变总预算
   *   onTick(info)        每轮之后回调：{polls, elapsedMs, lastState, error}
   *   onRequestTimeout()  单次请求超时时的通知（可在里面 abort 掉在途 XHR）
   *   onAbort()           流程结束或放弃某一发请求时调用：请调用方中止在途请求，
   *                       避免流程早已收口、连接还挂着（也少了迟到回调的来源）
   *   isCancelled()       返回 true 时立刻结束且不启动后续动作（被新流程顶替时用）
   *   now()               取当前时间（测试可注入）
   * @returns {Promise} resolve {stopped:true, polls, lastState, elapsedMs}
   *                    reject  {stopped:false, reason:'timeout'|'status_error'|'cancelled',
   *                             polls, lastState, lastError, elapsedMs}
   */
  function waitStopped(opts) {
    opts = opts || {};
    var fetchStatus = opts.fetchStatus;
    if (typeof fetchStatus !== 'function') {
      throw new TypeError('waitStopped 需要 fetchStatus 回调');
    }
    var timeoutMs = typeof opts.timeoutMs === 'number' ? opts.timeoutMs : DEFAULT_TIMEOUT_MS;
    var intervalMs = typeof opts.intervalMs === 'number' ? opts.intervalMs : DEFAULT_INTERVAL_MS;
    var requestTimeoutMs = typeof opts.requestTimeoutMs === 'number'
      ? opts.requestTimeoutMs : DEFAULT_REQUEST_TIMEOUT_MS;
    var now = typeof opts.now === 'function' ? opts.now : function () { return Date.now(); };
    var onTick = typeof opts.onTick === 'function' ? opts.onTick : null;
    var onRequestTimeout = typeof opts.onRequestTimeout === 'function' ? opts.onRequestTimeout : null;
    var onAbort = typeof opts.onAbort === 'function' ? opts.onAbort : null;
    var isCancelled = typeof opts.isCancelled === 'function' ? opts.isCancelled : null;
    var startedAt = now();
    var polls = 0;
    var lastState = 'unknown';
    var lastError = null;

    return new Promise(function (resolve, reject) {
      var settled = false;         // 只结束一次
      var deadlineTimer = null;    // 独立总截止：不等任何回调
      var pollTimer = null;        // 下一次轮询
      var requestTimer = null;     // 当前这一发请求的超时兜底
      var inFlight = false;        // 当前这一发请求是否还没有结论

      function notifyAbort() {
        if (!onAbort) { return; }
        try { onAbort(); } catch (e) { /* 中止失败不影响流程收口 */ }
      }

      function clearTimers() {
        if (deadlineTimer !== null) { clearTimeout(deadlineTimer); deadlineTimer = null; }
        if (pollTimer !== null) { clearTimeout(pollTimer); pollTimer = null; }
        if (requestTimer !== null) { clearTimeout(requestTimer); requestTimer = null; }
      }

      function elapsed() { return now() - startedAt; }

      function payload(extra) {
        var out = {
          stopped: false,
          polls: polls,
          lastState: lastState,
          lastError: lastError,
          elapsedMs: elapsed()
        };
        if (extra) {
          for (var k in extra) {
            if (Object.prototype.hasOwnProperty.call(extra, k)) { out[k] = extra[k]; }
          }
        }
        return out;
      }

      /** 唯一的收口：无论成功/失败/超时/取消，都从这里结束，且只结束一次。 */
      function settle(ok, data) {
        if (settled) { return false; }
        settled = true;
        clearTimers();
        if (inFlight) { inFlight = false; notifyAbort(); }   // 还有请求挂着：一并中止
        if (ok) { resolve(data); } else { reject(data); }
        return true;
      }

      function rejectByDeadline() {
        settle(false, payload({ reason: lastError ? 'status_error' : 'timeout' }));
      }

      function rejectCancelled() {
        settle(false, payload({ reason: 'cancelled', cancelled: true }));
      }

      function reportTick() {
        if (settled || !onTick) { return; }
        onTick({ polls: polls, elapsedMs: elapsed(), lastState: lastState, error: lastError });
      }

      function scheduleNext() {
        if (settled) { return; }
        pollTimer = setTimeout(tick, intervalMs);
      }

      function tick() {
        pollTimer = null;
        if (settled) { return; }
        if (isCancelled && isCancelled()) { rejectCancelled(); return; }

        polls += 1;
        inFlight = true;
        var answered = false;    // 本轮是否已经有结论（回调或超时，先到先算）

        requestTimer = setTimeout(function () {
          if (settled || answered) { return; }
          answered = true;
          requestTimer = null;
          inFlight = false;
          if (isCancelled && isCancelled()) { rejectCancelled(); return; }
          // 这一发没答上：只当本轮失败，继续在总预算内轮询，绝不干等
          lastError = new Error('状态请求超时（' + requestTimeoutMs + 'ms）');
          if (onRequestTimeout) {
            try { onRequestTimeout(); } catch (e) { /* 通知失败不影响流程 */ }
          }
          notifyAbort();       // 这一发不再等了，请调用方中止它
          reportTick();
          scheduleNext();
        }, requestTimeoutMs);

        fetchStatus(function (err, data) {
          // 迟到回调：本轮已判超时，或整个流程已结束 —— 直接丢弃：
          // 既不 resolve/reject、不再轮询，也不碰 inFlight（那是后来那一发的事）
          if (settled || answered) { return; }
          answered = true;
          inFlight = false;
          if (requestTimer !== null) { clearTimeout(requestTimer); requestTimer = null; }
          if (isCancelled && isCancelled()) { rejectCancelled(); return; }
          // 过了截止时间才回来的结果不算数：只有窗口内确认的 stopped 才作数
          if (elapsed() >= timeoutMs) { rejectByDeadline(); return; }

          if (err) {
            lastError = err;
          } else {
            lastError = null;
            lastState = stateOf(data);
            if (lastState === 'stopped') {
              settle(true, {
                stopped: true, polls: polls, lastState: lastState, elapsedMs: elapsed()
              });
              return;
            }
          }
          reportTick();
          scheduleNext();
        });
      }

      // 先立截止计时器再发第一发请求：预算从这一刻开始走，与回调无关
      deadlineTimer = setTimeout(rejectByDeadline, timeoutMs);
      tick();
    });
  }

  // 同一时刻只允许一条重启流程：新流程把旧流程顶替掉。
  // 被顶替的旧流程此后：不再发轮询、不再改 UI（onStage/onTick）、绝不允许触发启动 ——
  // 否则旧流程迟到时可能在新流程已经接管界面之后，再补一次 /start_bot。
  var _activeRun = null;

  /**
   * 完整重启流程：停止 → 轮询确认真实停止 → 启动。
   * 任何一步没确认成功都不会进入下一步（尤其：没停住绝不启动）。
   *
   * @param {Object} opts
   *   postStop(cb)     cb(err, res)：res 为 /stop_bot 的响应体
   *   fetchStatus(cb)  见 waitStopped
   *   postStart(cb)    cb(err, res)：res 为 /start_bot 的响应体
   *   onStage(name)    'stop' / 'wait' / 'start'，用于更新按钮文案
   *   其余参数透传给 waitStopped（timeoutMs / intervalMs / requestTimeoutMs /
   *   onTick / now / onRequestTimeout）
   * @returns {Promise} resolve {stop, wait, start}
   *                    reject  {stage:'stop'|'wait'|'start', reason, message, ...}
   *                    （被新流程顶替时为 {cancelled:true, reason:'superseded_by_new_run'}）
   */
  function runRestart(opts) {
    opts = opts || {};
    var postStop = opts.postStop;
    var postStart = opts.postStart;

    return new Promise(function (resolve, reject) {
      if (typeof postStop !== 'function' || typeof postStart !== 'function') {
        reject({ stage: 'stop', reason: 'bad_options', message: '重启流程缺少请求回调' });
        return;
      }

      var token = { cancelled: false };
      var previous = _activeRun;
      _activeRun = token;
      if (previous) { previous.cancelled = true; }

      var stageName = 'stop';
      var settled = false;

      function isCurrent() { return _activeRun === token && !token.cancelled; }

      // 结束只能发生一次；结束后摘掉自己的"当前流程"身份
      function finish(ok, data) {
        if (settled) { return false; }
        settled = true;
        if (_activeRun === token) { _activeRun = null; }
        if (ok) { resolve(data); } else { reject(data); }
        return true;
      }

      function aborted() {
        return finish(false, {
          cancelled: true,
          stage: stageName,
          reason: 'superseded_by_new_run',
          message: '本次重启已被新的重启请求取代'
        });
      }

      function stage(name) {
        stageName = name;
        if (isCurrent() && typeof opts.onStage === 'function') { opts.onStage(name); }
      }

      // 透传给 waitStopped 的参数副本：额外挂上"是否已作废"，并把 onTick 也挡住，
      // 保证旧流程既不轮询、也不改新流程的按钮文案。
      var waitOpts = {};
      for (var k in opts) {
        if (Object.prototype.hasOwnProperty.call(opts, k)) { waitOpts[k] = opts[k]; }
      }
      waitOpts.isCancelled = function () { return !isCurrent(); };
      if (typeof opts.onTick === 'function') {
        waitOpts.onTick = function (info) { if (isCurrent()) { opts.onTick(info); } };
      }

      stage('stop');
      postStop(function (stopErr, stopRes) {
        if (!isCurrent()) { aborted(); return; }
        // 服务端"没能在确认窗口内停完"（409 + code=timeout / state=stopping）不算停止失败：
        // 继续轮询真实状态，等它真的停下来再启动 —— 这正是轮询存在的意义。
        // 但 code=superseded（停止期间另一次启动已经跑起来）不能当"还在停"，
        // 否则会白等到超时，还给出"等待停止超时"这种与事实不符的提示。
        var stillStopping = !!(stopRes && (stopRes.code === 'timeout' || stopRes.state === 'stopping'));
        if (stopErr || (!stillStopping && (!stopRes || stopRes.status !== 'success'))) {
          finish(false, {
            stage: 'stop',
            reason: (stopRes && stopRes.code === 'superseded') ? 'superseded' : 'stop_failed',
            message: (stopRes && stopRes.message) || (stopErr && (stopErr.message || stopErr)) || '停止失败'
          });
          return;
        }
        stage('wait');
        waitStopped(waitOpts).then(function (waitInfo) {
          // 只有窗口内确认 stopped 才会走到这里；启动前再核对一次是不是仍归自己管
          if (!isCurrent()) { aborted(); return; }
          stage('start');
          postStart(function (startErr, startRes) {
            if (!isCurrent()) { aborted(); return; }
            if (startErr || !startRes || startRes.status !== 'success') {
              finish(false, {
                stage: 'start',
                reason: 'start_failed',
                message: (startRes && startRes.message) || (startErr && (startErr.message || startErr)) || '启动失败'
              });
              return;
            }
            finish(true, { stop: stopRes, wait: waitInfo, start: startRes });
          });
        }).catch(function (waitErr) {
          if (!isCurrent() || (waitErr && waitErr.cancelled)) { aborted(); return; }
          waitErr.stage = 'wait';
          finish(false, waitErr);
        });
      });
    });
  }

  /** 把失败结果转成给用户看的一句话（前端只负责弹窗）。 */
  function describeFailure(err) {
    err = err || {};
    // 被新的重启流程顶替：不提示 —— 界面已经归新流程管了，
    // 旧流程这时弹一句"重启未完成"只会误导用户。
    if (err.cancelled) { return ''; }
    // waitStopped 单独使用时没有 stage 字段，用 stopped===false 识别"没确认停止"
    var stage = err.stage || (err.stopped === false ? 'wait' : '');
    if (stage === 'stop') {
      if (err.reason === 'superseded') {
        return '检测到机器人已被其他操作重新启动，本次重启已取消。' +
               '请刷新页面状态后重试（当前运行中的实例已载入你刚保存的配置）。';
      }
      return '停止失败，重启已中断：' + (err.message || '未知原因');
    }
    if (stage === 'start') {
      return '机器人已停止，但启动失败：' + (err.message || '未知原因');
    }
    if (stage === 'wait') {
      var secs = Math.round((err.elapsedMs || 0) / 1000);
      if (err.reason === 'status_error') {
        return '连续 ' + secs + ' 秒无法读取机器人状态，已取消启动（避免在未确认停止时重复启动）。请查看运行日志后重试。';
      }
      return '等待机器人停止超时（' + secs + ' 秒，当前状态：' + labelOf(err.lastState) +
             '），已取消启动。请稍后重试或查看运行日志。';
    }
    return err.message || '重启失败';
  }

  return {
    DEFAULT_TIMEOUT_MS: DEFAULT_TIMEOUT_MS,
    DEFAULT_INTERVAL_MS: DEFAULT_INTERVAL_MS,
    DEFAULT_REQUEST_TIMEOUT_MS: DEFAULT_REQUEST_TIMEOUT_MS,
    STATE_LABELS: STATE_LABELS,
    stateOf: stateOf,
    labelOf: labelOf,
    isStopped: isStopped,
    waitStopped: waitStopped,
    runRestart: runRestart,
    describeFailure: describeFailure
  };
});
