#!/usr/bin/env python3
"""
LGM Receiver Server
"""

import argparse
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import uvicorn
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

RECEIVER_VERSION = "1.0.0"
DEFAULT_CONFIG_PATH = "/etc/lgm-monitor/config.json"


def log(level: str, message: str, **fields: Any) -> None:
    payload = {"ts": int(time.time()), "level": level.upper(), "msg": message}
    if fields:
        payload.update(fields)
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def decrypt_token(key_file: str, token_file: str) -> str:
    with open(key_file, "rb") as f:
        key = f.read()
    with open(token_file, "rb") as f:
        encrypted = f.read()
    return Fernet(key).decrypt(encrypted).decode("utf-8")


class ReceiverConfig:
    def __init__(
        self,
        centreon_api_url: str = "",
        centreon_api_token_file: str = "/etc/lgm-monitor/centreon_token.enc",
        centreon_key_file: str = "/etc/lgm-monitor/key.bin",
        centreon_username: str = "",
        centreon_password: str = "",
        centreon_poller_name: str = "Central",
        centreon_default_template: str = "generic-host",
        centreon_hostgroup: str = "LGM",
        receiver_port: int = 8443,
        receiver_bind_address: str = "0.0.0.0",
        log_level: str = "INFO",
        verify_tls: bool = True,
        max_request_size_bytes: int = 262144,
        db_path: str = "/var/lib/lgm-monitor/monitor.db",
        agent_tokens: Optional[List[str]] = None,
        agent_token_file: str = "",
        agent_key_file: str = "",
        hmac_enabled: bool = False,
        hmac_key_file: str = "/etc/lgm-monitor/hmac_key.bin",
        hmac_secret_enc_file: str = "/etc/lgm-monitor/hmac_secret.enc",
        hmac_max_skew_seconds: int = 300,
        hmac_require_nonce: bool = True,
        hmac_nonce_ttl_seconds: int = 600,
        nonce_cleanup_interval_seconds: int = 300,
        sqlite_vacuum_interval_seconds: int = 86400,
        latest_agent_version: str = "1.0.0",
        latest_agent_download_url: str = "",
        latest_agent_sha256: str = "",
    ):
        self.centreon_api_url = centreon_api_url
        self.centreon_api_token_file = centreon_api_token_file
        self.centreon_key_file = centreon_key_file
        self.centreon_username = centreon_username
        self.centreon_password = centreon_password
        self.centreon_poller_name = centreon_poller_name
        self.centreon_default_template = centreon_default_template
        self.centreon_hostgroup = centreon_hostgroup
        self.receiver_port = receiver_port
        self.receiver_bind_address = receiver_bind_address
        self.log_level = log_level
        self.verify_tls = verify_tls
        self.max_request_size_bytes = max_request_size_bytes
        self.db_path = db_path
        self.agent_tokens = agent_tokens
        self.agent_token_file = agent_token_file
        self.agent_key_file = agent_key_file
        self.hmac_enabled = hmac_enabled
        self.hmac_key_file = hmac_key_file
        self.hmac_secret_enc_file = hmac_secret_enc_file
        self.hmac_max_skew_seconds = hmac_max_skew_seconds
        self.hmac_require_nonce = hmac_require_nonce
        self.hmac_nonce_ttl_seconds = hmac_nonce_ttl_seconds
        self.nonce_cleanup_interval_seconds = nonce_cleanup_interval_seconds
        self.sqlite_vacuum_interval_seconds = sqlite_vacuum_interval_seconds
        self.latest_agent_version = latest_agent_version
        self.latest_agent_download_url = latest_agent_download_url
        self.latest_agent_sha256 = latest_agent_sha256

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReceiverConfig":
        return cls(
            centreon_api_url=data.get("centreon_api_url", "").rstrip("/"),
            centreon_api_token_file=data.get("centreon_api_token_file", "/etc/lgm-monitor/centreon_token.enc"),
            centreon_key_file=data.get("centreon_key_file", "/etc/lgm-monitor/key.bin"),
            centreon_username=data.get("centreon_username", ""),
            centreon_password=data.get("centreon_password", ""),
            centreon_poller_name=data.get("centreon_poller_name", "Central"),
            centreon_default_template=data.get("centreon_default_template", "generic-host"),
            centreon_hostgroup=data.get("centreon_hostgroup", "LGM"),
            receiver_port=int(data.get("receiver_port", 8443)),
            receiver_bind_address=data.get("receiver_bind_address", "0.0.0.0"),
            log_level=str(data.get("log_level", "INFO")).upper(),
            verify_tls=bool(data.get("verify_tls", True)),
            max_request_size_bytes=int(data.get("max_request_size_bytes", 262144)),
            db_path=data.get("db_path", "/var/lib/lgm-monitor/monitor.db"),
            agent_tokens=data.get("agent_tokens", []),
            agent_token_file=data.get("agent_token_file", ""),
            agent_key_file=data.get("agent_key_file", ""),
            hmac_enabled=bool(data.get("hmac_enabled", False)),
            hmac_key_file=data.get("hmac_key_file", "/etc/lgm-monitor/hmac_key.bin"),
            hmac_secret_enc_file=data.get("hmac_secret_enc_file", "/etc/lgm-monitor/hmac_secret.enc"),
            hmac_max_skew_seconds=int(data.get("hmac_max_skew_seconds", 300)),
            hmac_require_nonce=bool(data.get("hmac_require_nonce", True)),
            hmac_nonce_ttl_seconds=int(data.get("hmac_nonce_ttl_seconds", 600)),
            nonce_cleanup_interval_seconds=int(data.get("nonce_cleanup_interval_seconds", 300)),
            sqlite_vacuum_interval_seconds=int(data.get("sqlite_vacuum_interval_seconds", 86400)),
            latest_agent_version=data.get("latest_agent_version", "1.0.0"),
            latest_agent_download_url=data.get("latest_agent_download_url", ""),
            latest_agent_sha256=data.get("latest_agent_sha256", ""),
        )


class RegisterPayload(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    ip: str = Field(min_length=1, max_length=64)
    os: str = Field(min_length=1, max_length=64)
    labels: Dict[str, str] = Field(default_factory=dict)


class IngestPayload(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    timestamp: int
    metrics: Dict[str, Any]
    agent: Dict[str, Any] = Field(default_factory=dict)


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics (
                    host TEXT PRIMARY KEY,
                    timestamp INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS registrations (
                    host TEXT PRIMARY KEY,
                    ip TEXT NOT NULL,
                    os TEXT NOT NULL,
                    labels_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hmac_nonces (
                    nonce TEXT PRIMARY KEY,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()

    def upsert_registration(self, payload: RegisterPayload) -> bool:
        now = int(time.time())
        with self._connect() as conn:
            existing = conn.execute("SELECT host FROM registrations WHERE host = ?", (payload.host,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE registrations SET ip=?, os=?, labels_json=?, updated_at=? WHERE host=?",
                    (payload.ip, payload.os, json.dumps(payload.labels), now, payload.host),
                )
                conn.commit()
                return False

            conn.execute(
                "INSERT INTO registrations(host, ip, os, labels_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (payload.host, payload.ip, payload.os, json.dumps(payload.labels), now, now),
            )
            conn.commit()
            return True

    def upsert_metrics(self, payload: IngestPayload) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO metrics(host, timestamp, payload_json, updated_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(host) DO UPDATE SET timestamp=excluded.timestamp, payload_json=excluded.payload_json, updated_at=excluded.updated_at
                """,
                (payload.host, payload.timestamp, payload.model_dump_json(), now),
            )
            conn.commit()

    def cleanup_expired_nonces(self, now: int) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM hmac_nonces WHERE expires_at <= ?", (now,))
            conn.commit()
            return cur.rowcount if cur.rowcount is not None else 0

    def register_hmac_nonce(self, nonce: str, ttl_seconds: int, now: int) -> bool:
        expires_at = now + ttl_seconds
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO hmac_nonces(nonce, expires_at, created_at) VALUES (?, ?, ?)",
                    (nonce, expires_at, now),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def vacuum(self) -> None:
        with self._connect() as conn:
            conn.execute("VACUUM")

    def get_metrics(self, host: Optional[str]) -> Dict[str, Any]:
        with self._connect() as conn:
            if host:
                row = conn.execute("SELECT host, timestamp, payload_json FROM metrics WHERE host = ?", (host,)).fetchone()
                if not row:
                    return {}
                return json.loads(row["payload_json"])

            rows = conn.execute("SELECT host, timestamp, payload_json FROM metrics ORDER BY host ASC").fetchall()
            out: Dict[str, Any] = {}
            for row in rows:
                out[row["host"]] = json.loads(row["payload_json"])
            return out


class CentreonIntegration:
    def __init__(self, cfg: ReceiverConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.api_token = ""
        if cfg.centreon_api_token_file and os.path.exists(cfg.centreon_api_token_file) and os.path.exists(cfg.centreon_key_file):
            self.api_token = decrypt_token(cfg.centreon_key_file, cfg.centreon_api_token_file)

    def _headers(self) -> Dict[str, str]:
        if not self.api_token:
            return {"Content-Type": "application/json"}
        return {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_token}"}

    def _api_request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> bool:
        if not self.cfg.centreon_api_url:
            return False
        try:
            response = self.session.request(
                method,
                f"{self.cfg.centreon_api_url}{path}",
                json=payload,
                headers=self._headers(),
                timeout=10,
                verify=self.cfg.verify_tls,
                auth=(self.cfg.centreon_username, self.cfg.centreon_password)
                if self.cfg.centreon_username and self.cfg.centreon_password
                else None,
            )
            if response.status_code >= 400:
                log("ERROR", "centreon_api_error", path=path, status=response.status_code, body=response.text[:300])
                return False
            return True
        except requests.RequestException as exc:
            log("ERROR", "centreon_api_exception", error=str(exc), path=path)
            return False

    def _cli(self, args: List[str]) -> bool:
        if not (self.cfg.centreon_username and self.cfg.centreon_password):
            return False
        cmd = ["centreon", "-u", self.cfg.centreon_username, "-p", self.cfg.centreon_password] + args
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if result.returncode != 0:
                log("ERROR", "centreon_cli_error", code=result.returncode, stderr=result.stderr[:300])
                return False
            return True
        except Exception as exc:
            log("ERROR", "centreon_cli_exception", error=str(exc))
            return False

    def create_host(self, host: str, ip: str) -> bool:
        api_ok = self._api_request(
            "POST",
            "/api/latest/configuration/hosts",
            {
                "name": host,
                "alias": host,
                "address": ip,
                "monitoring_server_name": self.cfg.centreon_poller_name,
                "templates": [self.cfg.centreon_default_template],
            },
        )
        if api_ok:
            return True
        return self._cli(
            [
                "-o",
                "HOST",
                "-a",
                "ADD",
                "-v",
                f"{host};{host};{ip};{self.cfg.centreon_default_template};{self.cfg.centreon_poller_name}",
            ]
        )

    def apply_template(self, host: str) -> bool:
        api_ok = self._api_request(
            "PATCH",
            f"/api/latest/configuration/hosts/{host}",
            {"templates": [self.cfg.centreon_default_template]},
        )
        if api_ok:
            return True
        return self._cli(["-o", "HOST", "-a", "settemplate", "-v", f"{host};{self.cfg.centreon_default_template}"])

    def assign_hostgroup(self, host: str) -> bool:
        api_ok = self._api_request(
            "PATCH",
            f"/api/latest/configuration/hosts/{host}",
            {"hostgroups": [self.cfg.centreon_hostgroup]},
        )
        if api_ok:
            return True
        return self._cli(["-o", "HOST", "-a", "addhostgroup", "-v", f"{host};{self.cfg.centreon_hostgroup}"])

    def export_configuration(self) -> bool:
        api_ok = self._api_request("POST", "/api/latest/configuration/monitoring-servers/generate-and-reload", {})
        if api_ok:
            return True
        return self._cli(["-a", "APPLYCFG", "-v", self.cfg.centreon_poller_name])


class ServerRuntime:
    def __init__(self, cfg: ReceiverConfig):
        self.cfg = cfg
        self.db = Database(cfg.db_path)
        self.centreon = CentreonIntegration(cfg)
        self.allowed_tokens = set(cfg.agent_tokens or [])
        self.hmac_secret = ""
        self.last_nonce_cleanup_at = 0
        self.last_vacuum_at = 0

        if cfg.agent_token_file and cfg.agent_key_file and os.path.exists(cfg.agent_token_file) and os.path.exists(cfg.agent_key_file):
            self.allowed_tokens.add(decrypt_token(cfg.agent_key_file, cfg.agent_token_file))

        if cfg.hmac_enabled:
            self.hmac_secret = decrypt_token(cfg.hmac_key_file, cfg.hmac_secret_enc_file)

    def check_token(self, value: str) -> None:
        if not self.allowed_tokens:
            raise HTTPException(status_code=500, detail="No agent tokens configured")
        if value not in self.allowed_tokens:
            raise HTTPException(status_code=401, detail="Unauthorized token")

    def maybe_run_db_maintenance(self, now: int) -> None:
        if self.cfg.nonce_cleanup_interval_seconds > 0:
            if now - self.last_nonce_cleanup_at >= self.cfg.nonce_cleanup_interval_seconds:
                removed = self.db.cleanup_expired_nonces(now)
                self.last_nonce_cleanup_at = now
                if removed > 0:
                    log("INFO", "nonce_cleanup_done", removed=removed)

        if self.cfg.sqlite_vacuum_interval_seconds > 0:
            if now - self.last_vacuum_at >= self.cfg.sqlite_vacuum_interval_seconds:
                try:
                    self.db.vacuum()
                    self.last_vacuum_at = now
                    log("INFO", "sqlite_vacuum_done")
                except sqlite3.Error as exc:
                    log("ERROR", "sqlite_vacuum_failed", error=str(exc))

    def validate_hmac(self, request: Request, signature: str, ts: str, nonce: str, body: bytes) -> None:
        if not self.cfg.hmac_enabled:
            return
        if not signature or not ts:
            raise HTTPException(status_code=401, detail="Missing HMAC headers")
        if not ts.isdigit():
            raise HTTPException(status_code=401, detail="Invalid HMAC timestamp")

        now = int(time.time())
        self.maybe_run_db_maintenance(now)

        ts_value = int(ts)
        if abs(now - ts_value) > self.cfg.hmac_max_skew_seconds:
            raise HTTPException(status_code=401, detail="Expired HMAC timestamp")

        if self.cfg.hmac_require_nonce:
            if not nonce:
                raise HTTPException(status_code=401, detail="Missing HMAC nonce")
            if len(nonce) > 128:
                raise HTTPException(status_code=401, detail="Invalid HMAC nonce")
            if not self.db.register_hmac_nonce(nonce, self.cfg.hmac_nonce_ttl_seconds, now):
                raise HTTPException(status_code=401, detail="Replay detected")

        body_sha = hashlib.sha256(body).hexdigest()
        message = f"{request.method.upper()}\n{request.url.path}\n{ts}\n{nonce}\n{body_sha}".encode("utf-8")
        expected = hmac.new(self.hmac_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")


runtime: Optional[ServerRuntime] = None
app = FastAPI(title="LGM Receiver Server", version=RECEIVER_VERSION)


async def auth_dependency(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_agent_token: Optional[str] = Header(default=None),
    x_signature: Optional[str] = Header(default=None),
    x_signature_timestamp: Optional[str] = Header(default=None),
    x_signature_nonce: Optional[str] = Header(default=None),
) -> None:
    if runtime is None:
        raise HTTPException(status_code=500, detail="Runtime unavailable")

    token = x_agent_token or ""
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    runtime.check_token(token)

    raw = await request.body()
    runtime.validate_hmac(request, x_signature or "", x_signature_timestamp or "", x_signature_nonce or "", raw)


@app.middleware("http")
async def request_size_guard(request: Request, call_next):
    if runtime is None:
        return await call_next(request)

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > runtime.cfg.max_request_size_bytes:
        return JSONResponse(status_code=413, content={"error": "Request too large"})

    return await call_next(request)


@app.exception_handler(Exception)
async def catch_all(_request: Request, exc: Exception):
    log("ERROR", "unhandled_exception", error=str(exc))
    return JSONResponse(status_code=500, content={"error": "internal_server_error"})


@app.post("/register")
async def register(payload: RegisterPayload, _auth: None = Depends(auth_dependency)):
    assert runtime is not None
    is_new = runtime.db.upsert_registration(payload)
    if is_new:
        runtime.centreon.create_host(payload.host, payload.ip)
        runtime.centreon.apply_template(payload.host)
        runtime.centreon.assign_hostgroup(payload.host)
        runtime.centreon.export_configuration()
    return {"status": "ok", "new_host": is_new}


@app.post("/ingest")
async def ingest(request: Request, payload: IngestPayload, _auth: None = Depends(auth_dependency)):
    assert runtime is not None
    raw = await request.body()
    if len(raw) > runtime.cfg.max_request_size_bytes:
        raise HTTPException(status_code=413, detail="Request too large")

    runtime.db.upsert_metrics(payload)
    return {"status": "ok"}


@app.get("/metrics")
async def metrics(host: Optional[str] = Query(default=None), _auth: None = Depends(auth_dependency)):
    assert runtime is not None
    data = runtime.db.get_metrics(host)
    if host and not data:
        raise HTTPException(status_code=404, detail="host_not_found")
    return {"status": "ok", "data": data}


@app.get("/agent/version")
async def agent_version(_auth: None = Depends(auth_dependency)):
    assert runtime is not None
    return {
        "version": runtime.cfg.latest_agent_version,
        "download_url": runtime.cfg.latest_agent_download_url,
        "sha256": runtime.cfg.latest_agent_sha256,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LGM Receiver Server")
    parser.add_argument("--config", default=os.environ.get("LGM_RECEIVER_CONFIG", DEFAULT_CONFIG_PATH))
    return parser.parse_args()


def main() -> int:
    global runtime
    args = parse_args()
    cfg = ReceiverConfig.from_dict(load_json(args.config))
    runtime = ServerRuntime(cfg)
    log("INFO", "receiver_started", version=RECEIVER_VERSION, bind=cfg.receiver_bind_address, port=cfg.receiver_port)
    uvicorn.run(app, host=cfg.receiver_bind_address, port=cfg.receiver_port, log_level=cfg.log_level.lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

