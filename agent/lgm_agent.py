#!/usr/bin/env python3
"""
LGM Monitoring Agent - single file implementation.
"""

import argparse
import hashlib
import hmac
import json
import os
import platform
import shutil
import signal
import socket
import stat
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import psutil
import requests
from cryptography.fernet import Fernet

AGENT_VERSION = "1.0.0"
DEFAULT_CONFIG_PATH = "/etc/lgm-agent/config.json"


def log(level: str, message: str, **fields: Any) -> None:
    payload = {"ts": int(time.time()), "level": level.upper(), "msg": message}
    if fields:
        payload.update(fields)
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_hostname() -> str:
    return socket.gethostname()


def get_primary_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def decrypt_token(key_file: str, token_file: str) -> str:
    with open(key_file, "rb") as f:
        key = f.read()
    with open(token_file, "rb") as f:
        encrypted = f.read()
    return Fernet(key).decrypt(encrypted).decode("utf-8")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class BasePlugin:
    plugin_name = "base"

    def collect_metrics(self) -> Dict[str, Any]:
        raise NotImplementedError


class LinuxPlugin(BasePlugin):
    plugin_name = "linux"

    def collect_metrics(self) -> Dict[str, Any]:
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        load1, load5, load15 = os.getloadavg()
        boot_time = psutil.boot_time()
        return {
            "cpu": psutil.cpu_percent(interval=0.2),
            "memory": vm.percent,
            "disk": disk.percent,
            "load1": round(load1, 3),
            "load5": round(load5, 3),
            "load15": round(load15, 3),
            "uptime": int(time.time() - boot_time),
            "hostname": get_hostname(),
            "primary_ip": get_primary_ip(),
        }


class AsteriskPlugin(BasePlugin):
    plugin_name = "asterisk"

    def collect_metrics(self) -> Dict[str, Any]:
        return {
            "asterisk_ready": False,
            "note": "Placeholder plugin. Future implementation should run 'asterisk -rx'.",
        }


class MySQLPlugin(BasePlugin):
    plugin_name = "mysql"

    def collect_metrics(self) -> Dict[str, Any]:
        return {
            "mysql_ready": False,
            "note": "Placeholder plugin for future DB metrics.",
        }


class AgentConfig:
    def __init__(
        self,
        receiver_url: str,
        update_url: str,
        collection_interval: int = 15,
        update_check_interval: int = 3600,
        verify_tls: bool = True,
        log_level: str = "INFO",
        plugin: str = "linux",
        register_labels: Optional[Dict[str, str]] = None,
        token_key_file: str = "/etc/lgm-agent/key.bin",
        token_enc_file: str = "/etc/lgm-agent/token.enc",
        hmac_enabled: bool = False,
        hmac_key_file: str = "/etc/lgm-agent/hmac_key.bin",
        hmac_secret_enc_file: str = "/etc/lgm-agent/hmac_secret.enc",
        request_timeout_seconds: int = 10,
    ):
        self.receiver_url = receiver_url
        self.update_url = update_url
        self.collection_interval = collection_interval
        self.update_check_interval = update_check_interval
        self.verify_tls = verify_tls
        self.log_level = log_level
        self.plugin = plugin
        self.register_labels = register_labels
        self.token_key_file = token_key_file
        self.token_enc_file = token_enc_file
        self.hmac_enabled = hmac_enabled
        self.hmac_key_file = hmac_key_file
        self.hmac_secret_enc_file = hmac_secret_enc_file
        self.request_timeout_seconds = request_timeout_seconds

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentConfig":
        return cls(
            receiver_url=data["receiver_url"].rstrip("/"),
            update_url=data.get("update_url", data["receiver_url"]).rstrip("/"),
            collection_interval=int(data.get("collection_interval", 15)),
            update_check_interval=int(data.get("update_check_interval", 3600)),
            verify_tls=bool(data.get("verify_tls", True)),
            log_level=str(data.get("log_level", "INFO")).upper(),
            plugin=str(data.get("plugin", "linux")).lower(),
            register_labels=data.get("register_labels", {"role": "linux", "environment": "production"}),
            token_key_file=data.get("token_key_file", "/etc/lgm-agent/key.bin"),
            token_enc_file=data.get("token_enc_file", "/etc/lgm-agent/token.enc"),
            hmac_enabled=bool(data.get("hmac_enabled", False)),
            hmac_key_file=data.get("hmac_key_file", "/etc/lgm-agent/hmac_key.bin"),
            hmac_secret_enc_file=data.get("hmac_secret_enc_file", "/etc/lgm-agent/hmac_secret.enc"),
            request_timeout_seconds=int(data.get("request_timeout_seconds", 10)),
        )


class AgentRuntime:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.token = decrypt_token(config.token_key_file, config.token_enc_file)
        self.hmac_secret = ""
        if config.hmac_enabled:
            self.hmac_secret = decrypt_token(config.hmac_key_file, config.hmac_secret_enc_file)
        self.session = requests.Session()
        self.last_update_check = 0
        self.stop = False
        self.plugin = self._build_plugin(config.plugin)
        self.hostname = get_hostname()
        self.ip = get_primary_ip()

    def _build_plugin(self, plugin_name: str) -> BasePlugin:
        if plugin_name == "linux":
            return LinuxPlugin()
        if plugin_name == "asterisk":
            return AsteriskPlugin()
        if plugin_name == "mysql":
            return MySQLPlugin()
        raise ValueError(f"Unsupported plugin: {plugin_name}")

    def _build_hmac_signature(self, method: str, path: str, ts: str, nonce: str, body: bytes) -> str:
        body_sha = hashlib.sha256(body).hexdigest()
        message = f"{method.upper()}\n{path}\n{ts}\n{nonce}\n{body_sha}".encode("utf-8")
        return hmac.new(self.hmac_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

    def _headers(self, method: str, path: str, body: bytes = b"") -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "X-Agent-Token": self.token,
            "Content-Type": "application/json",
        }
        if self.config.hmac_enabled:
            ts = str(int(time.time()))
            nonce = uuid.uuid4().hex
            headers["X-Signature-Timestamp"] = ts
            headers["X-Signature-Nonce"] = nonce
            headers["X-Signature"] = self._build_hmac_signature(method, path, ts, nonce, body)
        return headers

    def register(self) -> None:
        payload = {
            "host": self.hostname,
            "ip": self.ip,
            "os": "linux",
            "labels": self.config.register_labels or {"role": "linux", "environment": "production"},
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        try:
            resp = self.session.post(
                f"{self.config.receiver_url}/register",
                data=body,
                headers=self._headers("POST", "/register", body),
                timeout=self.config.request_timeout_seconds,
                verify=self.config.verify_tls,
            )
            if resp.status_code >= 400:
                log("ERROR", "register_failed", status=resp.status_code, response=resp.text[:400])
                return
            log("INFO", "register_ok", host=self.hostname)
        except requests.RequestException as exc:
            log("ERROR", "register_exception", error=str(exc))

    def collect_payload(self) -> Dict[str, Any]:
        metrics = self.plugin.collect_metrics()
        return {
            "host": self.hostname,
            "timestamp": int(time.time()),
            "metrics": metrics,
            "agent": {"name": "lgm-agent", "version": AGENT_VERSION, "plugin": self.plugin.plugin_name},
        }

    def send_metrics(self) -> None:
        payload = self.collect_payload()
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        try:
            resp = self.session.post(
                f"{self.config.receiver_url}/ingest",
                data=body,
                headers=self._headers("POST", "/ingest", body),
                timeout=self.config.request_timeout_seconds,
                verify=self.config.verify_tls,
            )
            if resp.status_code >= 400:
                log("ERROR", "ingest_failed", status=resp.status_code, response=resp.text[:400])
                return
            log("INFO", "ingest_ok", host=self.hostname)
        except requests.RequestException as exc:
            log("ERROR", "ingest_exception", error=str(exc))

    def _version_newer(self, remote: str, current: str) -> bool:
        def parse(v: str) -> tuple:
            return tuple(int(x) for x in v.split("."))

        try:
            return parse(remote) > parse(current)
        except Exception:
            return remote != current

    def _current_binary_path(self) -> Optional[str]:
        if getattr(sys, "frozen", False):
            return os.path.abspath(sys.executable)
        return None

    def _download_and_replace(self, url: str, expected_sha256: str) -> bool:
        binary_path = self._current_binary_path()
        if not binary_path:
            log("WARN", "update_skipped_not_frozen")
            return False

        with tempfile.NamedTemporaryFile(delete=False) as tempf:
            temp_path = tempf.name
        try:
            with self.session.get(
                url, stream=True, timeout=self.config.request_timeout_seconds * 3, verify=self.config.verify_tls
            ) as resp:
                resp.raise_for_status()
                with open(temp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)

            got_sha = sha256_file(temp_path)
            if got_sha.lower() != expected_sha256.lower():
                log("ERROR", "update_sha256_mismatch", expected=expected_sha256, got=got_sha)
                return False

            current_mode = os.stat(binary_path).st_mode
            os.chmod(temp_path, current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            backup_path = f"{binary_path}.bak"
            shutil.copy2(binary_path, backup_path)
            os.replace(temp_path, binary_path)
            log("INFO", "update_binary_replaced", path=binary_path)
            return True
        except Exception as exc:
            log("ERROR", "update_replace_failed", error=str(exc))
            return False
        finally:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def check_update(self) -> None:
        now = time.time()
        if now - self.last_update_check < self.config.update_check_interval:
            return
        self.last_update_check = now

        try:
            resp = self.session.get(
                f"{self.config.update_url}/agent/version",
                headers=self._headers("GET", "/agent/version"),
                timeout=self.config.request_timeout_seconds,
                verify=self.config.verify_tls,
            )
            resp.raise_for_status()
            data = resp.json()
            remote_version = data.get("version", AGENT_VERSION)
            if not self._version_newer(remote_version, AGENT_VERSION):
                return
            update_bin_url = data.get("download_url")
            update_sha256 = data.get("sha256")
            if not update_bin_url or not update_sha256:
                log("ERROR", "update_invalid_payload")
                return
            log("INFO", "update_available", current=AGENT_VERSION, remote=remote_version)
            if self._download_and_replace(update_bin_url, update_sha256):
                self.restart()
        except requests.RequestException as exc:
            log("ERROR", "update_check_failed", error=str(exc))
        except ValueError:
            log("ERROR", "update_response_not_json")

    def restart(self) -> None:
        binary_path = self._current_binary_path()
        if not binary_path:
            log("WARN", "restart_skipped_not_frozen")
            return
        log("INFO", "restarting_agent", binary=binary_path)
        os.execv(binary_path, [binary_path] + sys.argv[1:])

    def run(self) -> None:
        self.register()
        while not self.stop:
            self.check_update()
            self.send_metrics()
            time.sleep(self.config.collection_interval)


def setup_signals(runtime: AgentRuntime) -> None:
    def _handler(signum: int, _frame: Any) -> None:
        runtime.stop = True
        log("INFO", "signal_received", signum=signum)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LGM Monitoring Agent")
    parser.add_argument("--config", default=os.environ.get("LGM_AGENT_CONFIG", DEFAULT_CONFIG_PATH))
    parser.add_argument("--print-version", action="store_true")
    parser.add_argument("--generate-key", action="store_true")
    parser.add_argument("--encrypt-token", help="Encrypt token and store in token_enc_file from config")
    parser.add_argument("--generate-hmac-key", action="store_true")
    parser.add_argument("--encrypt-hmac-secret", help="Encrypt HMAC secret and store in hmac_secret_enc_file")
    return parser.parse_args()


def generate_key_file(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    with open(path, "wb") as f:
        f.write(key)
    os.chmod(path, 0o600)


def encrypt_token_to_file(key_file: str, token_file: str, token_plain: str) -> None:
    with open(key_file, "rb") as f:
        key = f.read()
    encrypted = Fernet(key).encrypt(token_plain.encode("utf-8"))
    Path(token_file).parent.mkdir(parents=True, exist_ok=True)
    with open(token_file, "wb") as f:
        f.write(encrypted)
    os.chmod(token_file, 0o600)


def main() -> int:
    args = parse_args()
    if args.print_version:
        print(AGENT_VERSION)
        return 0

    cfg = AgentConfig.from_dict(load_json(args.config))

    if args.generate_key:
        generate_key_file(cfg.token_key_file)
        print(f"Key generated: {cfg.token_key_file}")
        return 0

    if args.encrypt_token:
        encrypt_token_to_file(cfg.token_key_file, cfg.token_enc_file, args.encrypt_token)
        print(f"Encrypted token written: {cfg.token_enc_file}")
        return 0

    if args.generate_hmac_key:
        generate_key_file(cfg.hmac_key_file)
        print(f"HMAC key generated: {cfg.hmac_key_file}")
        return 0

    if args.encrypt_hmac_secret:
        encrypt_token_to_file(cfg.hmac_key_file, cfg.hmac_secret_enc_file, args.encrypt_hmac_secret)
        print(f"Encrypted HMAC secret written: {cfg.hmac_secret_enc_file}")
        return 0

    runtime = AgentRuntime(cfg)
    log("INFO", "agent_started", version=AGENT_VERSION, plugin=runtime.plugin.plugin_name, os=platform.platform())
    setup_signals(runtime)
    runtime.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

