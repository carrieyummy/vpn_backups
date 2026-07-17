#!/usr/bin/env python3
import argparse
import contextlib
import datetime as dt
import errno
import hashlib
import html
import ipaddress
import json
import mimetypes
import os
import posixpath
import re
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
import paramiko
import yaml


APP_DIR = Path(__file__).resolve().parent
MIHOMO_DIR = APP_DIR.parent
STATIC_DIR = APP_DIR / "static"
DEFAULT_CONFIG_PATH = MIHOMO_DIR / "config.yaml"
DEFAULT_SECRET_PATH = MIHOMO_DIR / "secret"
DEFAULT_SERVICE_NAME = "mihomo.service"
DEFAULT_PROXY_TEMPLATE_PATH = STATIC_DIR / "proxy_setting.sh"
DEFAULT_REMOTE_CREDENTIALS_DB_PATH = APP_DIR / "remote_credentials.db"
DEFAULT_REMOTE_CREDENTIALS_KEY_PATH = APP_DIR / "remote_credentials.key"
TOKEN_HEADER = "X-Mihomo-Config-Token"
MAX_BACKUPS = 3
MAX_JSON_BODY_BYTES = 64 * 1024
MAX_REMOTE_FILE_BYTES = 1024 * 1024
REMOTE_CONNECT_TIMEOUT_SECONDS = 15
REMOTE_PROXY_START_MARKER = "# >>> mihomo-config-editor: proxy environment >>>"
REMOTE_PROXY_END_MARKER = "# <<< mihomo-config-editor: proxy environment <<<"
REMOTE_PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
)
REMOTE_PROXY_VARIABLE_ASSIGNMENT = re.compile(
    rf"(?<![A-Za-z0-9_$])(?:{'|'.join(map(re.escape, REMOTE_PROXY_VARIABLES))})\s*=",
    re.IGNORECASE,
)
REMOTE_PROXY_FILES = (
    {
        "key": "bashrc",
        "label": "~/.bashrc",
        "relativePath": ".bashrc",
        "createMode": 0o644,
    },
    {
        "key": "codexEnv",
        "label": "~/.codex/.env",
        "relativePath": ".codex/.env",
        "createMode": 0o600,
    },
)
SENSITIVE_STATIC_FILENAMES = {"login_confiig.yaml", "login_config.yaml"}


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


def extract_remote_host_candidates(text):
    lines = text.splitlines()
    start, end = find_top_level_block(lines, "lan-allowed-ips")
    if start is None:
        return []

    candidates = []
    seen = set()
    entry_pattern = re.compile(r"^\s*(?:#\s*)?-\s*([^\s#]+)")
    for line in lines[start + 1 : end]:
        match = entry_pattern.match(line)
        if not match:
            continue
        try:
            network = ipaddress.ip_network(match.group(1), strict=False)
        except ValueError:
            continue
        if network.prefixlen != network.max_prefixlen:
            continue
        host = network.network_address
        if host.is_loopback or str(host) == "10.100.10.33":
            continue
        value = str(host)
        if value not in seen:
            candidates.append(value)
            seen.add(value)
    return candidates


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


def prune_config_backups(backup_dir, keep=MAX_BACKUPS):
    backups = sorted(
        (path for path in backup_dir.glob("config.yaml.*.bak") if path.is_file()),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    for backup_path in backups[keep:]:
        try:
            backup_path.unlink()
        except OSError:
            pass


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

    prune_config_backups(backup_dir)

    return str(backup_path)


def make_state(config_path):
    text = read_text(config_path)
    return {
        "ok": True,
        "configText": text,
        "configHash": config_hash(text),
        "lanAllowedIpsText": extract_lan_allowed_ips_text(text),
        "remoteHostCandidates": extract_remote_host_candidates(text),
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


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_newlines(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_proxy_template(template_path):
    try:
        template = normalize_newlines(read_text(template_path))
    except OSError as exc:
        raise ApiError(500, "无法读取代理片段模板。") from exc

    if not template.endswith("\n"):
        template += "\n"
    if template.count(REMOTE_PROXY_START_MARKER) != 1 or template.count(REMOTE_PROXY_END_MARKER) != 1:
        raise ApiError(500, "代理片段模板缺少唯一的起止标记。")

    start_index = template.index(REMOTE_PROXY_START_MARKER)
    end_index = template.index(REMOTE_PROXY_END_MARKER)
    if start_index >= end_index:
        raise ApiError(500, "代理片段模板的起止标记顺序无效。")

    missing = [
        name
        for name in REMOTE_PROXY_VARIABLES
        if not re.search(rf"(?m)^\s*export\s+{re.escape(name)}\s*=", template)
    ]
    if missing:
        raise ApiError(500, "代理片段模板缺少变量：" + "、".join(missing))
    return template


def is_proxy_variable_definition(line):
    stripped = line.lstrip()
    return not stripped.startswith("#") and bool(REMOTE_PROXY_VARIABLE_ASSIGNMENT.search(line))


def has_exact_managed_proxy_fragment(text, template):
    position = text.find(template)
    if position < 0 or text.find(template, position + len(template)) >= 0:
        return False

    before = text[:position]
    after = text[position + len(template) :]
    return not any(is_proxy_variable_definition(line) for line in (before + after).split("\n"))


def remove_managed_proxy_blocks(lines):
    result = []
    removed = 0
    index = 0
    while index < len(lines):
        if lines[index].strip() != REMOTE_PROXY_START_MARKER:
            result.append(lines[index])
            index += 1
            continue

        end_index = index + 1
        while end_index < len(lines) and lines[end_index].strip() != REMOTE_PROXY_END_MARKER:
            end_index += 1
        if end_index == len(lines):
            raise ApiError(400, "远端文件包含未闭合的 Mihomo 代理片段标记，请先手动修复。")
        removed += 1
        index = end_index + 1
    return result, removed


def reconcile_remote_proxy_text(text, template):
    newline = detect_newline(text)
    normalized_text = normalize_newlines(text)
    if has_exact_managed_proxy_fragment(normalized_text, template):
        return text, 0

    lines, _ = remove_managed_proxy_blocks(normalized_text.split("\n"))
    kept = []
    removed_definitions = 0
    for line in lines:
        if not is_proxy_variable_definition(line):
            kept.append(line)
            continue

        removed_definitions += 1
        while kept and (not kept[-1].strip() or kept[-1].lstrip().startswith("#")):
            kept.pop()

    while kept and not kept[-1].strip():
        kept.pop()

    template_lines = template.rstrip("\n").split("\n")
    result_lines = template_lines if not kept else kept + [""] + template_lines
    result = "\n".join(result_lines) + "\n"
    if normalized_text == result:
        return text, 0
    return result.replace("\n", newline), removed_definitions


def remove_remote_proxy_text(text):
    newline = detect_newline(text)
    normalized_text = normalize_newlines(text)
    source_lines = normalized_text.split("\n")
    lines, removed_blocks = remove_managed_proxy_blocks(source_lines)
    removed_definitions = sum(is_proxy_variable_definition(line) for line in source_lines)
    if not removed_blocks and not removed_definitions:
        return text, 0

    kept = []
    for line in lines:
        if not is_proxy_variable_definition(line):
            kept.append(line)
            continue
        while kept and (not kept[-1].strip() or kept[-1].lstrip().startswith("#")):
            kept.pop()

    while kept and not kept[-1].strip():
        kept.pop()
    result = "\n".join(kept)
    if result:
        result += "\n"
    return result.replace("\n", newline), removed_definitions


def is_missing_remote_file_error(exc):
    return getattr(exc, "errno", None) == errno.ENOENT


def remote_file_state(sftp, path, label):
    try:
        attributes = sftp.lstat(path)
    except OSError as exc:
        if is_missing_remote_file_error(exc):
            return {"exists": False, "text": "", "mode": None}
        raise ApiError(502, f"无法检查远端文件 {label}。") from exc

    mode = getattr(attributes, "st_mode", 0)
    if stat.S_ISLNK(mode):
        raise ApiError(400, f"远端文件 {label} 是符号链接，为避免覆盖目标文件而拒绝同步。")
    if not stat.S_ISREG(mode):
        raise ApiError(400, f"远端路径 {label} 不是普通文件。")

    try:
        with sftp.open(path, "rb") as handle:
            data = handle.read(MAX_REMOTE_FILE_BYTES + 1)
    except OSError as exc:
        raise ApiError(502, f"无法读取远端文件 {label}。") from exc
    if len(data) > MAX_REMOTE_FILE_BYTES:
        raise ApiError(400, f"远端文件 {label} 超过 1 MiB，拒绝修改。")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(400, f"远端文件 {label} 不是 UTF-8 文本，拒绝修改。") from exc

    return {"exists": True, "text": text, "mode": mode & 0o777}


def ensure_remote_directory(sftp, path):
    try:
        attributes = sftp.stat(path)
    except OSError as exc:
        if not is_missing_remote_file_error(exc):
            raise
        sftp.mkdir(path, mode=0o700)
        return
    if not stat.S_ISDIR(getattr(attributes, "st_mode", 0)):
        raise ApiError(400, "远端 ~/.codex 不是目录，无法创建 .env。")


def write_remote_text(sftp, path, text, mode):
    directory = posixpath.dirname(path)
    basename = posixpath.basename(path)
    temporary_path = posixpath.join(directory, f".{basename}.mihomo-proxy-{uuid.uuid4().hex}.tmp")
    try:
        with sftp.open(temporary_path, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
        sftp.chmod(temporary_path, mode)
        if hasattr(sftp, "posix_rename"):
            sftp.posix_rename(temporary_path, path)
        else:
            sftp.rename(temporary_path, path)
    finally:
        try:
            sftp.remove(temporary_path)
        except OSError:
            pass


def make_remote_backup(sftp, path, state):
    backup_path = f"{path}.mihomo-proxy.{dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.{uuid.uuid4().hex[:8]}.bak"
    try:
        with sftp.open(backup_path, "wb") as handle:
            handle.write(state["text"].encode("utf-8"))
            handle.flush()
        sftp.chmod(backup_path, state["mode"])
    except OSError:
        try:
            sftp.remove(backup_path)
        except OSError:
            pass
        raise
    return backup_path


def prune_remote_backups(sftp, path, keep=MAX_BACKUPS):
    directory = posixpath.dirname(path)
    basename = posixpath.basename(path)
    pattern = re.compile(
        rf"^{re.escape(basename)}\.mihomo-proxy\.\d{{8}}-\d{{6}}-\d{{6}}\.[0-9a-f]{{8}}\.bak$"
    )
    backups = sorted(
        (
            posixpath.join(directory, attributes.filename)
            for attributes in sftp.listdir_attr(directory)
            if pattern.fullmatch(attributes.filename)
        ),
        reverse=True,
    )
    for backup_path in backups[keep:]:
        sftp.remove(backup_path)


def validate_remote_host(value):
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, "请输入远端 IP 地址。")
    host = value.strip()
    try:
        ipaddress.ip_address(host)
    except ValueError as exc:
        raise ApiError(400, "远端地址必须是 IPv4 或 IPv6 地址。") from exc
    return host


def validate_remote_username(value, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ApiError(400, "远端用户名无效。")
    username = value.strip()
    if required and not username:
        raise ApiError(400, "请输入远端用户名。")
    if len(username) > 128 or any(character in username for character in "\r\n\x00"):
        raise ApiError(400, "远端用户名包含无效字符。")
    return username


def open_remote_credentials_db(db_path):
    db_path = Path(db_path)
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(db_path), timeout=5)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS remote_credentials (
                host TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                password_token TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.commit()
        try:
            db_path.chmod(0o600)
        except OSError:
            pass
        return connection
    except (sqlite3.Error, OSError) as exc:
        raise ApiError(500, "无法访问远端登录凭据数据库。") from exc


def remote_credentials_fernet(key_path):
    key_path = Path(key_path)
    try:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key = key_path.read_bytes()
    except FileNotFoundError:
        generated_key = Fernet.generate_key()
        try:
            descriptor = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                key = key_path.read_bytes()
            except OSError as exc:
                raise ApiError(500, "无法读取远端登录凭据加密密钥。") from exc
        except OSError as exc:
            raise ApiError(500, "无法创建远端登录凭据加密密钥。") from exc
        else:
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(generated_key)
                key = generated_key
            except OSError as exc:
                raise ApiError(500, "无法写入远端登录凭据加密密钥。") from exc
    except OSError as exc:
        raise ApiError(500, "无法读取远端登录凭据加密密钥。") from exc

    try:
        return Fernet(key)
    except (TypeError, ValueError) as exc:
        raise ApiError(500, "远端登录凭据加密密钥无效。") from exc


def saved_remote_login_profile(db_path, host):
    connection = open_remote_credentials_db(db_path)
    try:
        row = connection.execute("SELECT username FROM remote_credentials WHERE host = ?", (host,)).fetchone()
    except sqlite3.Error as exc:
        raise ApiError(500, "无法读取远端登录凭据。") from exc
    finally:
        connection.close()
    return {"host": host, "username": row[0]} if row else None


def lookup_saved_remote_login(db_path, body):
    host = validate_remote_host(body.get("host"))
    profile = saved_remote_login_profile(db_path, host)
    return {"ok": True, "host": host, "found": bool(profile), "username": profile["username"] if profile else ""}


def saved_remote_login(db_path, key_path, host):
    connection = open_remote_credentials_db(db_path)
    try:
        row = connection.execute(
            "SELECT username, password_token FROM remote_credentials WHERE host = ?",
            (host,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise ApiError(500, "无法读取远端登录凭据。") from exc
    finally:
        connection.close()
    if not row:
        return None

    try:
        password = remote_credentials_fernet(key_path).decrypt(row[1].encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError) as exc:
        raise ApiError(500, "已保存的远端登录密码无法解密，请重新输入密码。") from exc
    return {"host": host, "username": row[0], "password": password, "credentialSource": "saved"}


def save_remote_login(db_path, key_path, credentials):
    if credentials.get("credentialSource") != "manual":
        return
    try:
        password_token = remote_credentials_fernet(key_path).encrypt(credentials["password"].encode("utf-8")).decode("ascii")
        connection = open_remote_credentials_db(db_path)
        try:
            connection.execute(
                """
                INSERT INTO remote_credentials (host, username, password_token, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(host) DO UPDATE SET
                    username = excluded.username,
                    password_token = excluded.password_token,
                    updated_at = excluded.updated_at
                """,
                (
                    credentials["host"],
                    credentials["username"],
                    password_token,
                    dt.datetime.now(dt.timezone.utc).isoformat(),
                ),
            )
            connection.commit()
        finally:
            connection.close()
    except ApiError:
        raise
    except (sqlite3.Error, OSError, UnicodeError) as exc:
        raise ApiError(500, "无法保存远端登录凭据。") from exc


def resolve_remote_credentials(body, db_path, key_path):
    host = validate_remote_host(body.get("host"))
    username = validate_remote_username(body.get("username"))
    password = body.get("password", "")
    if not isinstance(password, str):
        raise ApiError(400, "远端登录密码无效。")
    if password:
        username = validate_remote_username(username, required=True)
        return {"host": host, "username": username, "password": password, "credentialSource": "manual"}

    saved = saved_remote_login(db_path, key_path, host)
    if not saved:
        raise ApiError(400, "该 IP 没有保存的登录密码，请输入用户名和密码后检查。")
    if username and username != saved["username"]:
        raise ApiError(400, "用户名与该 IP 已保存的凭据不同；请输入密码后再更新。")
    return saved


def remote_host_fingerprint(client):
    transport = client.get_transport()
    if transport is None:
        return ""
    key = transport.get_remote_server_key()
    return ":".join(f"{byte:02x}" for byte in key.get_fingerprint())


@contextlib.contextmanager
def remote_sftp_session(credentials):
    client = paramiko.SSHClient()
    # 由界面选项确定：首次和后续连接均自动接受主机密钥，不持久化 known_hosts。
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            credentials["host"],
            port=22,
            username=credentials["username"],
            password=credentials["password"],
            look_for_keys=False,
            allow_agent=False,
            timeout=REMOTE_CONNECT_TIMEOUT_SECONDS,
            auth_timeout=REMOTE_CONNECT_TIMEOUT_SECONDS,
            banner_timeout=REMOTE_CONNECT_TIMEOUT_SECONDS,
        )
        sftp = client.open_sftp()
        home = sftp.normalize(".")
        if not home.startswith("/"):
            raise ApiError(502, "无法确定远端登录用户的主目录。")
        yield sftp, home, remote_host_fingerprint(client)
    except paramiko.AuthenticationException as exc:
        raise ApiError(403, "远端用户名或密码错误。") from exc
    except ApiError:
        raise
    except (paramiko.SSHException, socket.timeout, socket.gaierror, OSError, EOFError) as exc:
        raise ApiError(502, "无法建立远端 SSH 连接，请检查 IP、网络、密码认证和 SSH 服务。") from exc
    finally:
        client.close()


def build_remote_proxy_plan(sftp, home, template):
    files = []
    for specification in REMOTE_PROXY_FILES:
        path = posixpath.join(home, specification["relativePath"])
        state = remote_file_state(sftp, path, specification["label"])
        final_text, removed_definitions = reconcile_remote_proxy_text(state["text"], template)
        removal_text, removal_definitions = remove_remote_proxy_text(state["text"])
        if not state["exists"]:
            action = "create"
        elif final_text == state["text"]:
            action = "unchanged"
        else:
            action = "update"
        removal_action = "remove" if removal_text != state["text"] else "unchanged"
        files.append(
            {
                **specification,
                "path": path,
                "state": state,
                "finalText": final_text,
                "baseHash": content_hash(state["text"]) if state["exists"] else None,
                "action": action,
                "removedDefinitions": removed_definitions,
                "removalText": removal_text,
                "removalAction": removal_action,
                "removalDefinitions": removal_definitions,
            }
        )
    return files


def public_remote_proxy_plan(files):
    return [
        {
            "key": item["key"],
            "label": item["label"],
            "exists": item["state"]["exists"],
            "action": item["action"],
            "removedDefinitions": item["removedDefinitions"],
            "removalAction": item["removalAction"],
            "removalDefinitions": item["removalDefinitions"],
            "baseHash": item["baseHash"],
        }
        for item in files
    ]


def preview_remote_proxy(template_path, credentials_db_path, credentials_key_path, body):
    credentials = resolve_remote_credentials(body, credentials_db_path, credentials_key_path)
    template = read_proxy_template(template_path)
    with remote_sftp_session(credentials) as (sftp, home, fingerprint):
        files = build_remote_proxy_plan(sftp, home, template)
    save_remote_login(credentials_db_path, credentials_key_path, credentials)
    return {
        "ok": True,
        "hostFingerprint": fingerprint,
        "credentialSource": credentials["credentialSource"],
        "files": public_remote_proxy_plan(files),
    }


def assert_remote_proxy_hashes(files, supplied_hashes):
    if not isinstance(supplied_hashes, dict):
        raise ApiError(400, "缺少远端文件预览信息，请重新检查。")
    conflicts = []
    for item in files:
        if item["key"] not in supplied_hashes:
            raise ApiError(400, "预览信息不完整，请重新检查。")
        if supplied_hashes[item["key"]] != item["baseHash"]:
            conflicts.append(item["label"])
    if conflicts:
        raise ApiError(409, "远端文件已被修改，请重新检查后再同步。", {"files": conflicts})


def remote_proxy_operation_fields(item, operation):
    if operation == "sync":
        return item["action"], item["finalText"], item["removedDefinitions"]
    if operation == "remove":
        return item["removalAction"], item["removalText"], item["removalDefinitions"]
    raise ApiError(500, "未知的远端代理操作。")


def rollback_remote_proxy_files(sftp, written_files):
    results = []
    for item in reversed(written_files):
        try:
            if item["state"]["exists"]:
                write_remote_text(sftp, item["path"], item["state"]["text"], item["state"]["mode"])
            else:
                try:
                    sftp.remove(item["path"])
                except OSError as exc:
                    if not is_missing_remote_file_error(exc):
                        raise
            results.append({"label": item["label"], "restored": True})
        except Exception:
            results.append({"label": item["label"], "restored": False})
    return results


def apply_remote_proxy(template_path, credentials_db_path, credentials_key_path, body, operation="sync"):
    credentials = resolve_remote_credentials(body, credentials_db_path, credentials_key_path)
    template = read_proxy_template(template_path)
    supplied_hashes = body.get("baseHashes")

    with remote_sftp_session(credentials) as (sftp, home, fingerprint):
        files = build_remote_proxy_plan(sftp, home, template)
        save_remote_login(credentials_db_path, credentials_key_path, credentials)
        assert_remote_proxy_hashes(files, supplied_hashes)
        changed_files = [item for item in files if remote_proxy_operation_fields(item, operation)[0] != "unchanged"]

        try:
            for item in changed_files:
                if item["state"]["exists"]:
                    item["backupPath"] = make_remote_backup(sftp, item["path"], item["state"])
        except Exception as exc:
            raise ApiError(502, "无法创建远端备份，未修改任何文件。") from exc

        written_files = []
        try:
            for item in changed_files:
                if item["relativePath"].startswith(".codex/"):
                    ensure_remote_directory(sftp, posixpath.join(home, ".codex"))
                mode = item["state"]["mode"] if item["state"]["exists"] else item["createMode"]
                _, final_text, _ = remote_proxy_operation_fields(item, operation)
                write_remote_text(sftp, item["path"], final_text, mode)
                written_files.append(item)
        except Exception as exc:
            rollback = rollback_remote_proxy_files(sftp, written_files)
            raise ApiError(
                502,
                "远端同步失败，已尝试回滚已写入的文件。",
                {"rollback": rollback},
            ) from exc

        try:
            for item in changed_files:
                if item["state"]["exists"]:
                    prune_remote_backups(sftp, item["path"])
        except Exception as exc:
            raise ApiError(502, "远端文件已同步，但无法清理旧备份。") from exc

    return {
        "ok": True,
        "operation": operation,
        "hostFingerprint": fingerprint,
        "credentialSource": credentials["credentialSource"],
        "files": [
            remote_proxy_result_item(item, operation)
            for item in files
        ],
    }


def remote_proxy_result_item(item, operation):
    action, final_text, removed_definitions = remote_proxy_operation_fields(item, operation)
    return {
        "key": item["key"],
        "label": item["label"],
        "exists": item["state"]["exists"],
        "action": action,
        "removedDefinitions": removed_definitions,
        "content": final_text,
        "backupPath": item.get("backupPath"),
    }


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
    server_version = "MihomoConfigEditor/1.0"

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
            if self.path == "/api/remote-proxy/preview":
                self.send_json(
                    preview_remote_proxy(
                        self.server.proxy_template_path,
                        self.server.remote_credentials_db_path,
                        self.server.remote_credentials_key_path,
                        body,
                    )
                )
                return
            if self.path == "/api/remote-proxy/apply":
                self.send_json(
                    apply_remote_proxy(
                        self.server.proxy_template_path,
                        self.server.remote_credentials_db_path,
                        self.server.remote_credentials_key_path,
                        body,
                    )
                )
                return
            if self.path == "/api/remote-proxy/remove":
                self.send_json(
                    apply_remote_proxy(
                        self.server.proxy_template_path,
                        self.server.remote_credentials_db_path,
                        self.server.remote_credentials_key_path,
                        body,
                        operation="remove",
                    )
                )
                return
            if self.path == "/api/remote-login/lookup":
                self.send_json(lookup_saved_remote_login(self.server.remote_credentials_db_path, body))
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
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiError(400, "Content-Length 无效。") from exc
        if length <= 0:
            return {}
        if length > MAX_JSON_BODY_BYTES:
            raise ApiError(413, "请求内容过大。")
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
        if (
            not str(candidate).startswith(str(STATIC_DIR.resolve()))
            or candidate.name in SENSITIVE_STATIC_FILENAMES
            or not candidate.is_file()
        ):
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
    parser = argparse.ArgumentParser(description="Mihomo config editor")
    parser.add_argument("--host", default="10.100.10.33")
    parser.add_argument("--port", type=int, default=9091)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--secret", type=Path, default=DEFAULT_SECRET_PATH)
    parser.add_argument("--service", default=DEFAULT_SERVICE_NAME)
    parser.add_argument("--proxy-template", type=Path, default=DEFAULT_PROXY_TEMPLATE_PATH)
    parser.add_argument("--remote-credentials-db", type=Path, default=DEFAULT_REMOTE_CREDENTIALS_DB_PATH)
    parser.add_argument("--remote-credentials-key", type=Path, default=DEFAULT_REMOTE_CREDENTIALS_KEY_PATH)
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.config.is_file():
        raise SystemExit(f"config 文件不存在：{args.config}")
    if not args.secret.is_file():
        raise SystemExit(f"secret 文件不存在：{args.secret}")
    if not args.proxy_template.is_file():
        raise SystemExit(f"proxy 模板文件不存在：{args.proxy_template}")

    server = ThreadingHTTPServer((args.host, args.port), MihomoConfigHandler)
    server.config_path = args.config
    server.secret_path = args.secret
    server.service_name = args.service
    server.proxy_template_path = args.proxy_template
    server.remote_credentials_db_path = args.remote_credentials_db
    server.remote_credentials_key_path = args.remote_credentials_key
    print(f"Mihomo config editor listening on http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
