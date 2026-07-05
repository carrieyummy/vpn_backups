#!/usr/bin/env python3
import argparse
import datetime as dt
import hashlib
import html
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import yaml


APP_DIR = Path(__file__).resolve().parent
MIHOMO_DIR = APP_DIR.parent
STATIC_DIR = APP_DIR / "static"
DEFAULT_CONFIG_PATH = MIHOMO_DIR / "config.yaml"
DEFAULT_SECRET_PATH = MIHOMO_DIR / "secret"
DEFAULT_SERVICE_NAME = "mihomo.service"
TOKEN_HEADER = "X-Mihomo-Config-Token"


class ApiError(Exception):
    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details or {}


def read_text(path):
    return path.read_text(encoding="utf-8")


def config_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def yaml_diagnostics(text):
    warnings = []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        message = getattr(exc, "problem", None) or str(exc)
        context = getattr(exc, "context", None)
        if context and context not in message:
            message = f"{context}: {message}"
        return {
            "valid": False,
            "message": message,
            "line": mark.line + 1 if mark else None,
            "column": mark.column + 1 if mark else None,
            "warnings": warnings,
        }

    if not isinstance(data, dict):
        return {
            "valid": False,
            "message": "YAML 顶层必须是对象映射，例如 mixed-port、proxy-providers 等键。",
            "line": None,
            "column": None,
            "warnings": warnings,
        }

    if "proxy-providers" not in data:
        warnings.append("缺少 proxy-providers。")
    elif not isinstance(data.get("proxy-providers"), dict):
        warnings.append("proxy-providers 不是对象映射。")

    if "lan-allowed-ips" not in data:
        warnings.append("缺少 lan-allowed-ips。")
    elif data.get("lan-allowed-ips") is not None and not isinstance(data.get("lan-allowed-ips"), list):
        warnings.append("lan-allowed-ips 不是列表。")

    return {
        "valid": True,
        "message": "YAML 格式正确。",
        "line": None,
        "column": None,
        "warnings": warnings,
    }


def load_yaml_mapping(text):
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        return {}
    return parsed


def extract_lan_allowed_ips_text(text):
    lines = text.splitlines()
    start, end = find_top_level_block(lines, "lan-allowed-ips")
    if start is None:
        return ""

    result = []
    for line in lines[start + 1 : end]:
        if line.startswith("  "):
            result.append(line[2:])
        elif line.startswith("\t"):
            result.append(line[1:])
        else:
            result.append(line)
    return "\n".join(result).rstrip("\n")


def extract_proxy_providers(text):
    mapping = load_yaml_mapping(text)
    providers = mapping.get("proxy-providers", {})
    if not isinstance(providers, dict):
        return []

    result = []
    for name, value in providers.items():
        if isinstance(value, dict) and "url" in value:
            result.append({"name": str(name), "url": "" if value.get("url") is None else str(value.get("url"))})
    return result


def find_top_level_block(lines, key):
    pattern = re.compile(rf"^{re.escape(key)}\s*:\s*(?:#.*)?$")
    start = None
    for index, line in enumerate(lines):
        if pattern.match(line):
            start = index
            break

    if start is None:
        return None, None

    end = start + 1
    while end < len(lines):
        line = lines[end]
        stripped = line.strip()
        if stripped and not line.startswith((" ", "\t")):
            break
        end += 1
    return start, end


def normalize_lan_line(line):
    return line.rstrip()


def validate_lan_allowed_text(value):
    for number, raw_line in enumerate(value.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith("-"):
            continue
        raise ApiError(400, f"lan-allowed-ips 第 {number} 行必须是列表项或 # 注释。")


def replace_lan_allowed_ips(text, lan_text):
    validate_lan_allowed_text(lan_text)
    lines = text.splitlines(keepends=True)
    plain_lines = [line.rstrip("\r\n") for line in lines]
    start, end = find_top_level_block(plain_lines, "lan-allowed-ips")
    if start is None:
        raise ApiError(400, "找不到 lan-allowed-ips 配置块。")

    newline = detect_newline(text)
    normalized_lines = [normalize_lan_line(line) for line in lan_text.splitlines()]
    replacement = ["lan-allowed-ips:" + newline]
    replacement.extend(("  " + line.strip() + newline) if line.strip() else newline for line in normalized_lines)

    return "".join(lines[:start] + replacement + lines[end:])


def detect_newline(text):
    return "\r\n" if "\r\n" in text else "\n"


def yaml_quote(value):
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def validate_provider_urls(provider_updates, allowed_names):
    normalized = {}
    for item in provider_updates:
        name = str(item.get("name", ""))
        url = str(item.get("url", "")).strip()
        if name not in allowed_names:
            raise ApiError(400, f"未知 provider：{name}")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ApiError(400, f"{name} 的 URL 必须是 http 或 https 地址。")
        normalized[name] = url
    return normalized


def replace_proxy_provider_urls(text, provider_updates):
    existing = extract_proxy_providers(text)
    allowed_names = {item["name"] for item in existing}
    updates = validate_provider_urls(provider_updates, allowed_names)
    if not updates:
        return text

    lines = text.splitlines(keepends=True)
    plain_lines = [line.rstrip("\r\n") for line in lines]
    providers_start, providers_end = find_top_level_block(plain_lines, "proxy-providers")
    if providers_start is None:
        raise ApiError(400, "找不到 proxy-providers 配置块。")

    current_provider = None
    replaced = set()
    provider_pattern = re.compile(r"^  ([^#][^:]*):\s*(?:#.*)?$")
    url_pattern = re.compile(r"^(\s{4,})url\s*:\s*.*$")

    for index in range(providers_start + 1, providers_end):
        plain = plain_lines[index]
        provider_match = provider_pattern.match(plain)
        if provider_match:
            current_provider = provider_match.group(1).strip().strip("'\"")
            continue

        url_match = url_pattern.match(plain)
        if url_match and current_provider in updates:
            newline = "\r\n" if lines[index].endswith("\r\n") else "\n"
            lines[index] = f"{url_match.group(1)}url: {yaml_quote(updates[current_provider])}{newline}"
            replaced.add(current_provider)

    missing = sorted(set(updates) - replaced)
    if missing:
        raise ApiError(400, "找不到这些 provider 的 url 行：" + "、".join(missing))

    return "".join(lines)


def assert_hash_matches(current_text, base_hash):
    if not base_hash:
        raise ApiError(400, "缺少配置 hash，请刷新页面后重试。")
    if config_hash(current_text) != base_hash:
        raise ApiError(409, "config.yaml 已被其他进程修改，请刷新页面后再保存。")


def backup_and_write_config(config_path, new_text):
    backup_dir = APP_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"config.yaml.{timestamp}.bak"
    current_text = read_text(config_path)
    backup_path.write_text(current_text, encoding="utf-8")
    try:
        backup_path.chmod(config_path.stat().st_mode & 0o777)
    except OSError:
        pass

    fd, temp_name = tempfile.mkstemp(prefix=".config.yaml.", suffix=".tmp", dir=str(config_path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(new_text)
        try:
            temp_path.chmod(config_path.stat().st_mode & 0o777)
        except OSError:
            pass
        os.replace(temp_path, config_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return str(backup_path)


def make_state(config_path):
    text = read_text(config_path)
    return {
        "ok": True,
        "configText": text,
        "configHash": config_hash(text),
        "lanAllowedIpsText": extract_lan_allowed_ips_text(text),
        "proxyProviders": extract_proxy_providers(text),
        "yaml": yaml_diagnostics(text),
    }


def save_targeted(config_path, body):
    current_text = read_text(config_path)
    assert_hash_matches(current_text, str(body.get("baseHash", "")))

    updated = replace_lan_allowed_ips(current_text, str(body.get("lanAllowedIpsText", "")))
    updated = replace_proxy_provider_urls(updated, body.get("proxyProviders", []))

    diagnostics = yaml_diagnostics(updated)
    if not diagnostics["valid"]:
        raise ApiError(400, "保存后的 YAML 格式无效。", diagnostics)

    backup_path = backup_and_write_config(config_path, updated)
    state = make_state(config_path)
    state["backupPath"] = backup_path
    return state


def save_full(config_path, body):
    current_text = read_text(config_path)
    assert_hash_matches(current_text, str(body.get("baseHash", "")))

    new_text = str(body.get("configText", ""))
    diagnostics = yaml_diagnostics(new_text)
    if not diagnostics["valid"]:
        raise ApiError(400, "YAML 格式无效，未保存。", diagnostics)

    backup_path = backup_and_write_config(config_path, new_text)
    state = make_state(config_path)
    state["backupPath"] = backup_path
    return state


def run_restart(service_name):
    commands = [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "restart", service_name],
    ]
    completed = []
    for command in commands:
        result = subprocess.run(command, check=False, text=True, capture_output=True, timeout=30)
        completed.append({"command": " ".join(command), "returncode": result.returncode})
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "命令执行失败。").strip()
            raise ApiError(500, f"{' '.join(command)} 失败：{message}", {"completed": completed})
    return {"ok": True, "message": "已 daemon-reload 并重启 mihomo.service。", "completed": completed}


class MihomoConfigHandler(BaseHTTPRequestHandler):
    server_version = "MihomoConfigWeb/1.0"

    def do_GET(self):
        try:
            if self.path == "/api/state":
                self.require_auth()
                self.send_json(make_state(self.server.config_path))
                return
            self.serve_static()
        except ApiError as exc:
            self.send_error_json(exc.status, exc.message, exc.details)
        except Exception as exc:
            self.send_error_json(500, f"服务器错误：{exc}")

    def do_POST(self):
        try:
            self.require_auth()
            body = self.read_json_body()
            if self.path == "/api/validate-yaml":
                text = str(body.get("configText", ""))
                self.send_json({"ok": True, **yaml_diagnostics(text)})
                return
            if self.path == "/api/save-targeted":
                self.send_json(save_targeted(self.server.config_path, body))
                return
            if self.path == "/api/save-full":
                self.send_json(save_full(self.server.config_path, body))
                return
            if self.path == "/api/restart":
                self.send_json(run_restart(self.server.service_name))
                return
            raise ApiError(404, "接口不存在。")
        except ApiError as exc:
            self.send_error_json(exc.status, exc.message, exc.details)
        except Exception as exc:
            self.send_error_json(500, f"服务器错误：{exc}")

    def require_auth(self):
        expected = read_text(self.server.secret_path).strip()
        provided = self.headers.get(TOKEN_HEADER, "")
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            provided = auth[7:]
        if not expected or provided != expected:
            raise ApiError(401, "密钥错误或缺失。")

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(400, f"JSON 请求无效：{exc}")
        if not isinstance(value, dict):
            raise ApiError(400, "JSON 请求必须是对象。")
        return value

    def serve_static(self):
        path = urlparse(self.path).path
        if path in {"", "/"}:
            path = "/index.html"
        candidate = (STATIC_DIR / path.lstrip("/")).resolve()
        if not str(candidate).startswith(str(STATIC_DIR.resolve())) or not candidate.is_file():
            raise ApiError(404, "页面不存在。")

        mime_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{mime_type}; charset=utf-8" if mime_type.startswith("text/") else mime_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, status, message, details=None):
        safe_message = html.escape(str(message), quote=False)
        self.send_json({"ok": False, "error": safe_message, "details": details or {}}, status)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))


def parse_args():
    parser = argparse.ArgumentParser(description="Mihomo config web editor")
    parser.add_argument("--host", default=os.environ.get("MIHOMO_CONFIG_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=9091)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--secret", type=Path, default=DEFAULT_SECRET_PATH)
    parser.add_argument("--service", default=DEFAULT_SERVICE_NAME)
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.config.is_file():
        raise SystemExit(f"config 文件不存在：{args.config}")
    if not args.secret.is_file():
        raise SystemExit(f"secret 文件不存在：{args.secret}")

    server = ThreadingHTTPServer((args.host, args.port), MihomoConfigHandler)
    server.config_path = args.config
    server.secret_path = args.secret
    server.service_name = args.service
    print(f"Mihomo config web listening on http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
