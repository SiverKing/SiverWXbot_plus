"""Generic webhook notification support for SiverWXbot_plus."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Dict, Optional, Tuple

import requests

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "webhook.json")


def default_config() -> Dict[str, Any]:
    return {
        "enabled": False,
        "url": "",
        "method": "POST",
        "content_type": "application/json",
        "headers": {},
        "body": '{"msg_type":"text","content":{"text":"$title\\n\\n$content"}}',
        "timeout": 5,
    }


def _merge_with_defaults(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = default_config()
    if isinstance(config, dict):
        merged.update(config)
    merged["enabled"] = bool(merged.get("enabled", False))
    merged["method"] = str(merged.get("method") or "POST").upper()
    merged["content_type"] = str(merged.get("content_type") or "application/json")
    if not isinstance(merged.get("headers"), dict):
        merged["headers"] = {}
    merged["body"] = str(merged.get("body") or "")
    try:
        merged["timeout"] = max(1, int(merged.get("timeout", 5)))
    except (TypeError, ValueError):
        merged["timeout"] = 5
    return merged


def load_config(path: str = CONFIG_PATH) -> Dict[str, Any]:
    if not os.path.exists(path):
        return default_config()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _merge_with_defaults(json.load(f))
    except Exception:
        return default_config()


def save_config(config: Dict[str, Any], path: str = CONFIG_PATH) -> Dict[str, Any]:
    merged = _merge_with_defaults(config)
    if merged["content_type"].lower().startswith("application/json") and merged.get("body"):
        # Validate the JSON template itself before saving. Placeholders are
        # rendered after parsing, so runtime content cannot break valid JSON.
        json.loads(merged["body"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return merged


def _render(value: Any, title: str, content: str) -> Any:
    if isinstance(value, str):
        return value.replace("$title", title).replace("$content", content)
    if isinstance(value, dict):
        return {k: _render(v, title, content) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(item, title, content) for item in value]
    return value


def send_webhook(title: str, content: str, config: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    cfg = _merge_with_defaults(config if config is not None else load_config())
    if not cfg["enabled"]:
        return True, "Webhook disabled"
    url = str(cfg.get("url") or "").strip()
    if not url:
        return False, "Webhook URL is required"

    method = cfg["method"]
    headers = deepcopy(cfg.get("headers") or {})
    content_type = cfg.get("content_type") or "application/json"
    headers.setdefault("Content-Type", content_type)
    headers = _render(headers, title, content)

    kwargs: Dict[str, Any] = {"headers": headers, "timeout": cfg["timeout"]}
    if content_type.lower().startswith("application/json"):
        try:
            # Parse the JSON template before rendering placeholders. Runtime error
            # content often contains newlines, quotes, and traceback snippets; if we
            # render first, those characters can break the JSON string itself.
            body_json = json.loads(cfg.get("body", "")) if cfg.get("body", "") else {}
            kwargs["json"] = _render(body_json, title, content)
        except json.JSONDecodeError:
            return False, "Webhook JSON body is invalid"
    else:
        body = _render(cfg.get("body", ""), title, content)
        kwargs["data"] = body

    try:
        response = requests.request(method, url, **kwargs)
        response_text = response.text or ""
        if 200 <= response.status_code < 300:
            # Some webhook providers, including Feishu/Lark, return HTTP 200
            # even when the message is rejected at the application layer.
            try:
                response_json = response.json()
            except Exception:
                try:
                    response_json = json.loads(response_text) if response_text else {}
                except Exception:
                    response_json = {}
            if isinstance(response_json, dict):
                code = response_json.get("code")
                status_code = response_json.get("StatusCode")
                if code not in (None, 0):
                    return False, f"Webhook provider rejected message: code={code}, msg={response_json.get('msg') or response_json.get('message') or response_text[:200]}"
                if status_code not in (None, 0):
                    return False, f"Webhook provider rejected message: StatusCode={status_code}, msg={response_json.get('StatusMessage') or response_text[:200]}"
            return True, f"Webhook sent: HTTP {response.status_code}"
        return False, f"Webhook failed: HTTP {response.status_code} {response_text[:200]}"
    except Exception as exc:
        return False, f"Webhook request error: {exc}"


def send_message(title: str, content: str) -> Tuple[bool, str]:
    """Convenience wrapper used by runtime notification paths."""
    return send_webhook(title, content)
