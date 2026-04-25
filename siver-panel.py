from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import socket
import tempfile
import threading
import time
import uuid
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from requests import Response
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.sync.client import connect as ws_connect

DEFAULT_BASE_URL = "https://panel.siver.top"
DEFAULT_WS_URL = "wss://panel.siver.top/relay/ws"
LEGACY_BASE_URL = "https://wxbot-panel.siverking.online"
LEGACY_WS_URL = "wss://wxbot-panel.siverking.online/relay/ws"
SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{3,30}[a-z0-9])?$")
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
INITIAL_NETWORK_RETRY_DELAYS = (5, 15, 30, 60, 120, 300, 600, 900, 1200, 1800)
RECONNECT_NETWORK_RETRY_DELAYS = (8, 18, 30, 60, 120, 300, 600, 900, 1200, 1800)
TRANSIENT_HTTP_STATUS_CODES = {502, 503, 504}
API_TIMEOUT = 30
WS_OPEN_TIMEOUT = 30
WS_AUTH_TIMEOUT = 25
WS_HEARTBEAT_TIMEOUT = 150
LOCAL_PROXY_TIMEOUT = 45
LOCAL_READY_TIMEOUT = 45


class NetworkIssue(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ServiceIssue(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SiverPanelManager:
    def __init__(
        self,
        *,
        config_path: str,
        client_version: str,
        log_func: Callable[[str, str], None] | None = None,
    ) -> None:
        self.config_path = config_path
        self.client_version = client_version
        self.log_func = log_func

        self._state_lock = threading.Lock()
        self._worker_lock = threading.Lock()
        self._config_lock = threading.Lock()
        self._manual_stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._websocket = None
        self._local_port_provider: Callable[[], int | None] = lambda: None
        self._connect_guard: Callable[[bool], tuple[str, str] | None] | None = None
        self._retry_delays = INITIAL_NETWORK_RETRY_DELAYS
        self._connection_cycle_established = False

        self._state: dict[str, Any] = {
            "state": "disabled",
            "connected": False,
            "enabled": False,
            "slug": "",
            "panel_url": "",
            "service_expire_at": "",
            "device_bound": False,
            "retry_count": 0,
            "retry_max": len(self._retry_delays),
            "last_error_code": "",
            "last_error_message": "",
            "last_message": "远程访问服务未启用",
            "updated_at": self._now_text(),
        }

    def set_local_port_provider(self, provider: Callable[[], int | None]) -> None:
        self._local_port_provider = provider

    def set_connect_guard(self, guard: Callable[[bool], tuple[str, str] | None] | None) -> None:
        self._connect_guard = guard

    def start(self) -> None:
        self._reset_retry_policy()
        config = self._ensure_identity_persisted()
        enabled = bool(config.get("siver_panel_enabled"))
        self._set_state(
            state="idle" if enabled else "disabled",
            connected=False,
            enabled=enabled,
            slug=self._normalize_slug(config.get("siver_panel_slug") or ""),
            panel_url=config.get("siver_panel_panel_url") or "",
            service_expire_at=config.get("siver_panel_service_expire_at") or "",
            device_bound=bool(config.get("siver_panel_device_id") and config.get("siver_panel_device_secret")),
            retry_count=0,
            retry_max=self._retry_max(),
            last_message="等待连接" if enabled else "远程访问服务未启用",
        )
        if enabled:
            self.connect(manual=False)

    def connect(self, *, manual: bool) -> dict[str, Any]:
        config = self._ensure_identity_persisted()
        enabled = bool(config.get("siver_panel_enabled"))
        if manual and not enabled:
            self._set_state(
                state="disabled",
                connected=False,
                enabled=False,
                last_error_code="disabled",
                last_error_message="请先开启远程访问服务开关",
                last_message="请先开启远程访问服务开关",
            )
            return self.get_status()

        if self._connect_guard is not None:
            guard_error = self._connect_guard(manual=manual)
            if guard_error is not None:
                error_code, error_message = guard_error
                self._reset_retry_policy()
                self._set_state(
                    state="error",
                    connected=False,
                    enabled=enabled,
                    retry_count=0,
                    retry_max=self._retry_max(),
                    last_error_code=error_code,
                    last_error_message=error_message,
                    last_message=error_message,
                )
                return self.get_status()

        self._set_state(
            state="connecting",
            connected=False,
            enabled=enabled,
            slug=self._normalize_slug(config.get("siver_panel_slug") or ""),
            retry_count=0,
            retry_max=self._retry_max(),
            last_error_code="",
            last_error_message="",
            last_message="正在连接 SiverPanel 远程访问服务...",
        )

        with self._worker_lock:
            if self._worker and self._worker.is_alive():
                if not manual:
                    return self.get_status()
                self.disconnect(reason="config_changed")
                for _ in range(20):
                    if not self._worker or not self._worker.is_alive():
                        break
                    time.sleep(0.1)
                if self._worker and self._worker.is_alive():
                    return self.get_status()

            self._reset_retry_policy()
            self._manual_stop.clear()
            self._worker = threading.Thread(
                target=self._lifecycle_main,
                args=(manual,),
                daemon=True,
                name="SiverPanelClient",
            )
            self._worker.start()

        return self.get_status()

    def disconnect(self, reason: str = "manual_disconnect") -> dict[str, Any]:
        self._manual_stop.set()
        websocket = self._websocket
        self._websocket = None
        if websocket is not None:
            try:
                websocket.close(reason=reason)
            except Exception:
                pass

        self._reset_retry_policy()
        config = self._load_config()
        enabled = bool(config.get("siver_panel_enabled"))
        reason_map = {
            "disabled": "远程访问服务已关闭",
            "config_changed": "配置已更新，请重新连接使新配置生效",
            "manual_disconnect": "远程访问服务已断开",
            "shutdown": "远程访问服务已停止",
        }
        self._set_state(
            state="disabled" if not enabled or reason == "disabled" else "disconnected",
            connected=False,
            enabled=enabled,
            retry_count=0,
            retry_max=self._retry_max(),
            last_message=reason_map.get(reason, "远程访问服务已断开"),
        )
        return self.get_status()

    def shutdown(self) -> None:
        self.disconnect(reason="shutdown")

    def handle_config_updated(
        self,
        previous_config: dict[str, Any] | None = None,
        current_config: dict[str, Any] | None = None,
    ) -> None:
        current = current_config or self._load_config()
        enabled = bool(current.get("siver_panel_enabled"))
        current_slug = self._normalize_slug(current.get("siver_panel_slug") or "")

        if not enabled:
            self.disconnect(reason="disabled")
            return

        previous_slug = self._normalize_slug((previous_config or {}).get("siver_panel_slug") or "")
        if previous_slug and previous_slug != current_slug and self.is_connected():
            self.disconnect(reason="config_changed")

        self._set_state(
            enabled=True,
            slug=current_slug,
            device_bound=bool(current.get("siver_panel_device_id") and current.get("siver_panel_device_secret")),
        )

    def get_status(self) -> dict[str, Any]:
        config = self._load_config()
        with self._state_lock:
            state = dict(self._state)
        slug = self._normalize_slug(config.get("siver_panel_slug") or "")
        state.update(
            {
                "enabled": bool(config.get("siver_panel_enabled")),
                "slug": slug,
                "panel_url": state.get("panel_url") or config.get("siver_panel_panel_url") or self._build_panel_url(slug),
                "service_expire_at": state.get("service_expire_at") or config.get("siver_panel_service_expire_at") or "",
                "device_bound": bool(config.get("siver_panel_device_id") and config.get("siver_panel_device_secret")),
                "activation_code_configured": bool((config.get("siver_panel_activation_code") or "").strip()),
                "base_url": config.get("siver_panel_base_url") or DEFAULT_BASE_URL,
                "example_url": self._build_panel_url(slug),
            }
        )
        return state

    def is_connected(self) -> bool:
        with self._state_lock:
            return bool(self._state.get("connected"))

    def _lifecycle_main(self, manual: bool) -> None:
        config = self._ensure_identity_persisted()
        if not self._wait_local_panel_ready():
            message = "本地面板尚未就绪，无法建立远程访问连接"
            self._set_state(
                state="error",
                connected=False,
                enabled=bool(config.get("siver_panel_enabled")),
                last_error_code="local_panel_unavailable",
                last_error_message=message,
                last_message=message,
            )
            return

        retry_count = 0
        while not self._manual_stop.is_set():
            try:
                config = self._ensure_identity_persisted()
                enabled = bool(config.get("siver_panel_enabled"))
                if not enabled:
                    self._set_state(
                        state="disabled",
                        connected=False,
                        enabled=False,
                        last_message="远程访问服务未启用",
                    )
                    return

                self._set_state(
                    state="connecting",
                    connected=False,
                    enabled=True,
                    slug=self._normalize_slug(config.get("siver_panel_slug") or ""),
                    retry_count=retry_count,
                    retry_max=self._retry_max(),
                    last_error_code="",
                    last_error_message="",
                    last_message="正在连接 SiverPanel 远程访问服务...",
                )

                config = self._prepare_credentials(dict(config))
                self._open_websocket(config)

                if self._manual_stop.is_set():
                    return
                raise NetworkIssue("ws_closed", "远程连接已断开")
            except ServiceIssue as exc:
                self._persist_config_updates(
                    siver_panel_last_error_code=exc.code,
                    siver_panel_last_error_message=exc.message,
                )
                self._set_state(
                    state="error",
                    connected=False,
                    last_error_code=exc.code,
                    last_error_message=exc.message,
                    last_message=exc.message,
                    retry_count=0,
                    retry_max=self._retry_max(),
                )
                self._log("WARNING", f"SiverPanel 连接失败: {exc.message}")
                return
            except NetworkIssue as exc:
                if self._manual_stop.is_set():
                    return
                if self._connection_cycle_established:
                    retry_count = 0
                    self._connection_cycle_established = False
                retry_max = self._retry_max()
                if retry_count < retry_max:
                    delay = self._retry_delays[retry_count]
                    retry_count += 1
                    self._set_state(
                        state="retrying",
                        connected=False,
                        retry_count=retry_count,
                        retry_max=retry_max,
                        last_error_code=exc.code,
                        last_error_message=exc.message,
                        last_message=f"{exc.message}，{delay} 秒后自动重试（{retry_count}/{retry_max}）",
                    )
                    self._log("WARNING", f"SiverPanel 网络异常: {exc.message}，将在 {delay}s 后重试")
                    if not self._sleep_with_stop(delay):
                        return
                    continue

                self._persist_config_updates(
                    siver_panel_last_error_code=exc.code,
                    siver_panel_last_error_message=exc.message,
                )
                self._set_state(
                    state="error",
                    connected=False,
                    retry_count=retry_max,
                    retry_max=retry_max,
                    last_error_code=exc.code,
                    last_error_message=exc.message,
                    last_message=f"连接失败: {exc.message}",
                )
                self._log("ERROR", f"SiverPanel 连续重试失败: {exc.message}")
                return
            except Exception as exc:
                message = f"远程访问客户端内部异常: {exc}"
                self._persist_config_updates(
                    siver_panel_last_error_code="internal_error",
                    siver_panel_last_error_message=message,
                )
                self._set_state(
                    state="error",
                    connected=False,
                    last_error_code="internal_error",
                    last_error_message=message,
                    last_message=message,
                    retry_max=self._retry_max(),
                )
                self._log("ERROR", message)
                return

    def _prepare_credentials(self, config: dict[str, Any]) -> dict[str, Any]:
        slug = self._normalize_slug(config.get("siver_panel_slug") or "")
        activation_code = (config.get("siver_panel_activation_code") or "").strip()
        if not self._is_valid_slug(slug):
            raise ServiceIssue("invalid_slug", "安全入口格式不正确，至少 5 位，仅支持小写字母、数字和连字符")

        config["siver_panel_slug"] = slug
        device_id = (config.get("siver_panel_device_id") or "").strip()
        device_secret = (config.get("siver_panel_device_secret") or "").strip()

        if device_id and device_secret:
            try:
                status_data = self._fetch_device_status(config)
            except ServiceIssue as exc:
                if exc.code != "invalid_device_credentials" or not activation_code:
                    raise
                self._log("WARNING", "检测到现有设备凭据失效，开始尝试恢复设备凭据")
                return self._recover_credentials(config)

            remote_slug = self._normalize_slug(status_data.get("panel_slug") or slug)
            panel_url = status_data.get("panel_url") or self._build_panel_url(remote_slug)
            service_message = "已验证现有设备凭据"

            if slug and remote_slug and slug != remote_slug:
                slug_data = self._update_remote_slug(config, slug)
                remote_slug = self._normalize_slug(slug_data.get("panel_slug") or slug)
                panel_url = slug_data.get("panel_url") or self._build_panel_url(remote_slug)
                service_message = slug_data.get("message") or "安全入口已更新"
                self._log("INFO", f"SiverPanel 安全入口已更新为 {remote_slug}")

            updates = {
                "siver_panel_slug": remote_slug or slug,
                "siver_panel_panel_url": panel_url,
                "siver_panel_service_expire_at": status_data.get("service_expire_at") or "",
                "siver_panel_ws_url": config.get("siver_panel_ws_url") or self._derive_ws_url(config),
                "siver_panel_last_error_code": "",
                "siver_panel_last_error_message": "",
            }
            self._persist_config_updates(**updates)
            config.update(updates)
            self._set_state(
                slug=updates["siver_panel_slug"],
                panel_url=updates["siver_panel_panel_url"],
                service_expire_at=updates["siver_panel_service_expire_at"],
                last_message=service_message,
                device_bound=True,
            )
            return config

        if not activation_code:
            raise ServiceIssue("missing_activation_code", "请先填写激活码后再连接远程访问服务")

        register_data = self._register_device(config)
        if register_data.get("success"):
            return self._store_bound_credentials(config, register_data)

        error_code = register_data.get("error_code") or "register_failed"
        if error_code == "already_bound":
            return self._recover_credentials(config)

        raise ServiceIssue(error_code, register_data.get("message") or "远程服务返回了未知错误")

    def _recover_credentials(self, config: dict[str, Any]) -> dict[str, Any]:
        recover_data = self._recover_device(config)
        if not recover_data.get("success"):
            raise ServiceIssue(
                recover_data.get("error_code") or "recover_failed",
                recover_data.get("message") or "设备凭据恢复失败",
            )
        return self._store_bound_credentials(config, recover_data)

    def _store_bound_credentials(self, config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        device_id = (payload.get("device_id") or "").strip()
        device_secret = (payload.get("device_secret") or "").strip()
        if not device_id or not device_secret:
            raise ServiceIssue("bind_failed", "远程服务未返回完整的设备凭据")

        updates = {
            "siver_panel_device_id": device_id,
            "siver_panel_device_secret": device_secret,
            "siver_panel_ws_url": payload.get("ws_url") or self._derive_ws_url(config),
            "siver_panel_panel_url": payload.get("panel_url") or self._build_panel_url(config.get("siver_panel_slug") or ""),
            "siver_panel_service_expire_at": payload.get("service_expire_at") or "",
            "siver_panel_last_error_code": "",
            "siver_panel_last_error_message": "",
        }
        self._persist_config_updates(**updates)
        config.update(updates)
        self._set_state(
            slug=self._normalize_slug(config.get("siver_panel_slug") or ""),
            panel_url=updates["siver_panel_panel_url"],
            service_expire_at=updates["siver_panel_service_expire_at"],
            last_message=payload.get("message") or "设备绑定成功",
            device_bound=True,
        )
        return config

    def _open_websocket(self, config: dict[str, Any]) -> None:
        ws_url = (config.get("siver_panel_ws_url") or self._derive_ws_url(config)).strip()
        slug = self._normalize_slug(config.get("siver_panel_slug") or "")
        hello_payload = {
            "type": "auth.hello",
            "device_id": config.get("siver_panel_device_id"),
            "device_secret": config.get("siver_panel_device_secret"),
            "panel_slug": slug,
            "client_version": self.client_version,
            "install_id": config.get("siver_panel_install_id"),
            "capabilities": {
                "proxy_http": True,
                "multipart": True,
            },
        }

        try:
            with ws_connect(
                ws_url,
                open_timeout=WS_OPEN_TIMEOUT,
                close_timeout=3,
                max_size=8 * 1024 * 1024,
                additional_headers=[("X-Client-Version", self.client_version)],
            ) as websocket:
                self._websocket = websocket
                websocket.send(json.dumps(hello_payload, ensure_ascii=False))

                auth_payload = self._decode_ws_message(websocket.recv(timeout=WS_AUTH_TIMEOUT))
                if auth_payload.get("type") == "auth.error":
                    raise ServiceIssue("auth_error", auth_payload.get("message") or "远程服务认证失败")
                if auth_payload.get("type") != "auth.ok":
                    raise ServiceIssue("auth_error", "远程服务返回了未知的认证响应")

                with self._state_lock:
                    previous_message = self._state.get("last_message") or ""
                connected_message = previous_message or "远程访问服务已连接"
                self._enable_reconnect_retry_policy()

                self._set_state(
                    state="connected",
                    connected=True,
                    slug=slug,
                    panel_url=config.get("siver_panel_panel_url") or self._build_panel_url(slug),
                    service_expire_at=config.get("siver_panel_service_expire_at") or "",
                    last_error_code="",
                    last_error_message="",
                    retry_count=0,
                    retry_max=self._retry_max(),
                    last_message=connected_message,
                )
                self._log("SUCCESS", f"SiverPanel 已连接，安全入口: {slug}")

                while not self._manual_stop.is_set():
                    try:
                        frame = self._decode_ws_message(websocket.recv(timeout=WS_HEARTBEAT_TIMEOUT))
                    except TimeoutError as exc:
                        raise NetworkIssue("heartbeat_timeout", "与远程服务的心跳已超时") from exc
                    self._handle_ws_frame(websocket, frame, config)
        except ConnectionClosedOK:
            if self._manual_stop.is_set():
                return
            raise NetworkIssue("ws_closed", "远程连接已关闭")
        except ConnectionClosedError as exc:
            if self._manual_stop.is_set():
                return
            raise NetworkIssue("ws_closed", exc.reason or "远程连接意外中断") from exc
        except OSError as exc:
            raise NetworkIssue("ws_connect_failed", f"无法建立远程连接: {exc}") from exc
        finally:
            self._websocket = None
            if not self._manual_stop.is_set():
                self._set_state(connected=False)

    def _handle_ws_frame(self, websocket, frame: dict[str, Any], config: dict[str, Any]) -> None:
        message_type = frame.get("type")
        if message_type == "heartbeat.ping":
            websocket.send(json.dumps({"type": "heartbeat.pong", "ts": frame.get("ts")}, ensure_ascii=False))
            return
        if message_type == "heartbeat.pong":
            return
        if message_type == "server.warning":
            self._set_state(last_message=frame.get("message") or "远程服务返回了警告消息")
            return
        if message_type == "admin.force_disconnect":
            raise ServiceIssue("force_disconnect", frame.get("message") or "远程服务已强制断开当前连接")
        if message_type == "proxy.request":
            websocket.send(json.dumps(self._forward_to_local_panel(frame, config), ensure_ascii=False))

    def _forward_to_local_panel(self, frame: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        request_id = frame.get("request_id") or f"req_{uuid.uuid4().hex}"
        port = self._local_port_provider()
        if not port:
            return {
                "type": "proxy.error",
                "request_id": request_id,
                "message": "本地面板端口尚未就绪",
            }

        path = frame.get("path") or "/"
        query_string = frame.get("query_string") or ""
        local_url = f"http://127.0.0.1:{port}{path}"
        if query_string:
            local_url = f"{local_url}?{query_string}"

        try:
            response = requests.request(
                method=(frame.get("method") or "GET").upper(),
                url=local_url,
                headers=self._build_local_request_headers(frame.get("headers"), config, frame.get("remote_ip") or ""),
                data=self._decode_body(frame.get("body_base64")),
                timeout=LOCAL_PROXY_TIMEOUT,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            return {
                "type": "proxy.error",
                "request_id": request_id,
                "message": f"本地面板访问失败: {exc}",
            }

        return {
            "type": "proxy.response",
            "request_id": request_id,
            "status_code": response.status_code,
            "headers": self._extract_response_headers(response),
            "body_base64": self._encode_body(response.content),
        }

    def _build_local_request_headers(
        self,
        raw_headers: dict[str, Any] | None,
        config: dict[str, Any],
        remote_ip: str,
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        if isinstance(raw_headers, dict):
            for key, value in raw_headers.items():
                lowered = str(key).lower()
                if lowered in HOP_BY_HOP_HEADERS or lowered in {"host", "content-length"}:
                    continue
                headers[str(key)] = ", ".join(value) if isinstance(value, list) else str(value)

        parsed = urlparse((config.get("siver_panel_base_url") or DEFAULT_BASE_URL).strip())
        headers["X-Forwarded-Proto"] = parsed.scheme or "https"
        headers["X-Forwarded-Host"] = parsed.netloc or "panel.siver.top"
        headers["X-Forwarded-Prefix"] = f"/panel/{self._normalize_slug(config.get('siver_panel_slug') or '')}"
        headers["X-Siver-Remote"] = "1"
        if remote_ip:
            headers["X-Forwarded-For"] = remote_ip
            headers["X-Real-IP"] = remote_ip
        return headers

    def _extract_response_headers(self, response: Response) -> dict[str, Any]:
        header_payload: dict[str, Any] = {}
        raw_headers = getattr(response.raw, "headers", None)
        header_names = list(response.headers.keys())
        if raw_headers is not None:
            try:
                header_names = list(raw_headers.keys())
            except Exception:
                header_names = list(response.headers.keys())

        for name in header_names:
            lowered = name.lower()
            if lowered in HOP_BY_HOP_HEADERS or lowered == "content-length":
                continue

            values: list[str] = []
            if raw_headers is not None and hasattr(raw_headers, "getlist"):
                values = [str(item) for item in raw_headers.getlist(name)]
            elif raw_headers is not None and hasattr(raw_headers, "get_all"):
                values = [str(item) for item in raw_headers.get_all(name) or []]
            if not values:
                value = response.headers.get(name)
                if value is None:
                    continue
                values = [str(value)]

            header_payload[name] = values[0] if len(values) == 1 else values
        return header_payload

    def _fetch_device_status(self, config: dict[str, Any]) -> dict[str, Any]:
        response = self._request("GET", "/api/client/status", headers=self._device_headers(config))
        self._raise_transient_http_error(response, "远程状态查询暂时不可用")
        if response.status_code == 401:
            raise ServiceIssue("invalid_device_credentials", "现有设备凭据已失效，请重新恢复或绑定")
        if response.status_code == 403:
            raise ServiceIssue("service_expired", "当前设备授权已过期，请更换新的激活码后重新绑定")
        if response.status_code >= 400:
            raise ServiceIssue("status_failed", self._response_message(response, "远程状态查询失败"))
        payload = self._response_json(response)
        if not payload.get("success"):
            raise ServiceIssue(payload.get("error_code") or "status_failed", payload.get("message") or "远程状态查询失败")
        return payload

    def _register_device(self, config: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "activation_code": (config.get("siver_panel_activation_code") or "").strip(),
            "panel_slug": self._normalize_slug(config.get("siver_panel_slug") or ""),
            "install_id": config.get("siver_panel_install_id"),
            "machine_fingerprint": config.get("siver_panel_machine_fingerprint"),
            "client_version": self.client_version,
        }
        response = self._request("POST", "/api/client/register", json_data=payload)
        self._raise_transient_http_error(response, "远程绑定服务暂时不可用")
        if response.status_code >= 400:
            raise ServiceIssue("register_failed", self._response_message(response, "远程绑定请求失败"))
        return self._response_json(response)

    def _recover_device(self, config: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "activation_code": (config.get("siver_panel_activation_code") or "").strip(),
            "install_id": config.get("siver_panel_install_id"),
            "machine_fingerprint": config.get("siver_panel_machine_fingerprint"),
            "client_version": self.client_version,
        }
        response = self._request("POST", "/api/client/recover-device", json_data=payload)
        self._raise_transient_http_error(response, "设备凭据恢复服务暂时不可用")
        if response.status_code >= 400:
            raise ServiceIssue("recover_failed", self._response_message(response, "设备凭据恢复失败"))
        return self._response_json(response)

    def _update_remote_slug(self, config: dict[str, Any], slug: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/api/client/update-slug",
            json_data={"panel_slug": slug},
            headers=self._device_headers(config),
        )
        self._raise_transient_http_error(response, "安全入口更新服务暂时不可用")
        if response.status_code == 400:
            raise ServiceIssue("invalid_slug", self._response_message(response, "安全入口格式不正确"))
        if response.status_code == 403:
            raise ServiceIssue("service_expired", self._response_message(response, "当前设备授权已过期"))
        if response.status_code == 409:
            raise ServiceIssue("slug_occupied", self._response_message(response, "安全入口已被占用"))
        if response.status_code >= 400:
            raise ServiceIssue("update_slug_failed", self._response_message(response, "安全入口更新失败"))
        payload = self._response_json(response)
        if not payload.get("success"):
            raise ServiceIssue("update_slug_failed", payload.get("message") or "安全入口更新失败")
        return payload

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        base_url = (self._load_config().get("siver_panel_base_url") or DEFAULT_BASE_URL).rstrip("/")
        url = f"{base_url}{path}"
        try:
            return requests.request(
                method=method,
                url=url,
                json=json_data,
                headers=headers,
                timeout=API_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise NetworkIssue("network_error", f"无法连接远程服务: {exc}") from exc

    def _device_headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {
            "x-device-id": str(config.get("siver_panel_device_id") or "").strip(),
            "x-device-secret": str(config.get("siver_panel_device_secret") or "").strip(),
        }

    def _response_json(self, response: Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _response_message(self, response: Response, fallback: str) -> str:
        payload = self._response_json(response)
        if payload.get("message"):
            return str(payload["message"])
        text = (response.text or "").strip()
        return text or fallback

    def _raise_transient_http_error(self, response: Response, fallback: str) -> None:
        if response.status_code not in TRANSIENT_HTTP_STATUS_CODES:
            return
        payload = self._response_json(response)
        if payload.get("message"):
            message = str(payload["message"])
        else:
            reason = (response.reason or "").strip()
            suffix = f" {reason}" if reason else ""
            message = f"{fallback}: HTTP {response.status_code}{suffix}"
        raise NetworkIssue("remote_unavailable", message)

    def _load_config(self) -> dict[str, Any]:
        try:
            with open(self.config_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _persist_config_updates(self, **updates: Any) -> dict[str, Any]:
        with self._config_lock:
            config = self._load_config()
            config.update(updates)
            self._atomic_write_json(config)
            return config

    def _ensure_identity_persisted(self) -> dict[str, Any]:
        config = self._load_config()
        updates: dict[str, Any] = {}
        if not config.get("siver_panel_install_id"):
            updates["siver_panel_install_id"] = f"ins_{uuid.uuid4().hex}"
        if not config.get("siver_panel_machine_fingerprint"):
            updates["siver_panel_machine_fingerprint"] = self._build_machine_fingerprint()
        if config.get("siver_panel_base_url") == LEGACY_BASE_URL:
            updates["siver_panel_base_url"] = DEFAULT_BASE_URL
        elif not config.get("siver_panel_base_url"):
            updates["siver_panel_base_url"] = DEFAULT_BASE_URL
        if config.get("siver_panel_ws_url") == LEGACY_WS_URL:
            updates["siver_panel_ws_url"] = DEFAULT_WS_URL
        elif not config.get("siver_panel_ws_url"):
            updates["siver_panel_ws_url"] = DEFAULT_WS_URL
        if updates:
            config = self._persist_config_updates(**updates)
        return config

    def _atomic_write_json(self, payload: dict[str, Any]) -> None:
        directory = os.path.dirname(self.config_path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="siver-panel-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=4)
            os.replace(temp_path, self.config_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _wait_local_panel_ready(self) -> bool:
        deadline = time.time() + LOCAL_READY_TIMEOUT
        while time.time() < deadline and not self._manual_stop.is_set():
            port = self._local_port_provider()
            if port and self._can_connect("127.0.0.1", int(port)):
                return True
            time.sleep(0.5)
        return False

    def _can_connect(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            return False

    def _sleep_with_stop(self, seconds: int) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._manual_stop.is_set():
                return False
            time.sleep(0.2)
        return not self._manual_stop.is_set()

    def _reset_retry_policy(self) -> None:
        self._retry_delays = INITIAL_NETWORK_RETRY_DELAYS
        self._connection_cycle_established = False

    def _enable_reconnect_retry_policy(self) -> None:
        self._retry_delays = RECONNECT_NETWORK_RETRY_DELAYS
        self._connection_cycle_established = True

    def _retry_max(self) -> int:
        return len(self._retry_delays)

    def _set_state(self, **updates: Any) -> None:
        updates["updated_at"] = self._now_text()
        with self._state_lock:
            self._state.update(updates)

    def _build_panel_url(self, slug: str) -> str:
        slug = self._normalize_slug(slug)
        if not slug:
            return ""
        base_url = (self._load_config().get("siver_panel_base_url") or DEFAULT_BASE_URL).rstrip("/")
        return f"{base_url}/panel/{slug}"

    def _derive_ws_url(self, config: dict[str, Any]) -> str:
        base_url = (config.get("siver_panel_base_url") or DEFAULT_BASE_URL).strip()
        if base_url.startswith("https://"):
            return base_url.replace("https://", "wss://", 1).rstrip("/") + "/relay/ws"
        if base_url.startswith("http://"):
            return base_url.replace("http://", "ws://", 1).rstrip("/") + "/relay/ws"
        return DEFAULT_WS_URL

    def _build_machine_fingerprint(self) -> str:
        raw = "|".join(
            [
                platform.system(),
                platform.release(),
                platform.machine(),
                socket.gethostname(),
                str(uuid.getnode()),
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]

    def _decode_ws_message(self, raw_message: Any) -> dict[str, Any]:
        if isinstance(raw_message, bytes):
            raw_message = raw_message.decode("utf-8", errors="replace")
        if isinstance(raw_message, str):
            try:
                payload = json.loads(raw_message)
            except json.JSONDecodeError as exc:
                raise ServiceIssue("invalid_ws_payload", f"远程服务返回了无法解析的消息: {exc}") from exc
            if isinstance(payload, dict):
                return payload
        raise ServiceIssue("invalid_ws_payload", "远程服务返回了未知格式的消息")

    def _encode_body(self, body: bytes | None) -> str:
        if not body:
            return ""
        return base64.b64encode(body).decode("ascii")

    def _decode_body(self, body_base64: str | None) -> bytes:
        if not body_base64:
            return b""
        try:
            return base64.b64decode(body_base64.encode("ascii"))
        except Exception:
            return b""

    def _normalize_slug(self, slug: str) -> str:
        return str(slug or "").strip().lower()

    def _is_valid_slug(self, slug: str) -> bool:
        return bool(SLUG_PATTERN.fullmatch(self._normalize_slug(slug)))

    def _now_text(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    def _log(self, level: str, message: str) -> None:
        if self.log_func is not None:
            self.log_func(level, message)
