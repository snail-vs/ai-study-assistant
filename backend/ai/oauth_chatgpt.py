"""OpenAI Codex (ChatGPT Plus/Pro) OAuth client.

Implements the same subscription-login flows the Codex CLI uses, so ChatGPT
Plus/Pro models can be called without an API key:

- ``device_code``: headless device authorization (requires the account's
  "device code authorization for Codex" setting).
- ``browser``: PKCE authorization code flow. The redirect URI is the fixed
  ``localhost:1455`` callback used by the Codex client, so remote deployments
  complete it by pasting the callback URL/code back into the app.
"""

import asyncio
import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTH_BASE_URL = "https://auth.openai.com"
AUTHORIZE_URL = f"{AUTH_BASE_URL}/oauth/authorize"
TOKEN_URL = f"{AUTH_BASE_URL}/oauth/token"
DEVICE_USER_CODE_URL = f"{AUTH_BASE_URL}/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = f"{AUTH_BASE_URL}/api/accounts/deviceauth/token"
DEVICE_VERIFICATION_URI = f"{AUTH_BASE_URL}/codex/device"
DEVICE_REDIRECT_URI = f"{AUTH_BASE_URL}/deviceauth/callback"
BROWSER_REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPE = "openid profile email offline_access"
JWT_CLAIM_PATH = "https://api.openai.com/auth"
DEVICE_CODE_TIMEOUT_SECONDS = 15 * 60
EXPIRY_SKEW_MS = 60_000


class ChatGptOAuthError(RuntimeError):
    """A ChatGPT OAuth step failed."""


@dataclass
class ChatGptCredential:
    access_token: str
    refresh_token: str
    expires_at: int
    account_id: str

    def is_expired(self) -> bool:
        return int(time.time() * 1000) + EXPIRY_SKEW_MS >= self.expires_at


@dataclass
class DeviceAuthorization:
    device_auth_id: str
    user_code: str
    interval_seconds: int = 5
    verification_uri: str = field(default=DEVICE_VERIFICATION_URI)


@dataclass
class BrowserAuthorization:
    verifier: str
    state: str
    url: str


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def generate_pkce() -> tuple[str, str]:
    verifier = _base64url(secrets.token_bytes(32))
    challenge = _base64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def create_browser_authorization(originator: str = "pi") -> BrowserAuthorization:
    verifier, challenge = generate_pkce()
    state = secrets.token_hex(16)
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": BROWSER_REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": originator,
    }
    return BrowserAuthorization(verifier=verifier, state=state, url=f"{AUTHORIZE_URL}?{urlencode(params)}")


def parse_authorization_input(value: str) -> tuple[str | None, str | None]:
    """Extract (code, state) from a pasted redirect URL, query string, or code."""
    text = value.strip()
    if not text:
        return None, None
    if text.startswith(("http://", "https://")):
        params = parse_qs(urlparse(text).query)
        return _first(params, "code"), _first(params, "state")
    if "code=" in text:
        params = parse_qs(text)
        return _first(params, "code"), _first(params, "state")
    if "#" in text:
        code, _, state = text.partition("#")
        return code or None, state or None
    return text, None


def _first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    return values[0] or None


def extract_account_id(access_token: str) -> str:
    try:
        parts = access_token.split(".")
        if len(parts) != 3:
            raise ValueError("not a JWT")
        padding = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + padding))
        account_id = payload.get(JWT_CLAIM_PATH, {}).get("chatgpt_account_id")
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same error
        raise ChatGptOAuthError("无法从 access token 解析 ChatGPT 账号信息") from exc
    if not isinstance(account_id, str) or not account_id:
        raise ChatGptOAuthError("access token 中缺少 chatgpt_account_id")
    return account_id


def _credential_from_token(payload: dict[str, Any]) -> ChatGptCredential:
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    if not isinstance(access, str) or not isinstance(refresh, str) or not isinstance(expires_in, (int, float)):
        raise ChatGptOAuthError("token 响应缺少 access_token/refresh_token/expires_in")
    return ChatGptCredential(
        access_token=access,
        refresh_token=refresh,
        expires_at=int(time.time() * 1000 + float(expires_in) * 1000),
        account_id=extract_account_id(access),
    )


def _error_code(body: str) -> str | None:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict):
        return error.get("code")
    return error if isinstance(error, str) else None


async def start_device_authorization() -> DeviceAuthorization:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(DEVICE_USER_CODE_URL, json={"client_id": CLIENT_ID})
        if response.status_code >= 400:
            raise ChatGptOAuthError(
                f"申请设备码失败（HTTP {response.status_code}）: {response.text[:300]}"
            )
        body = response.json()
    device_auth_id = body.get("device_auth_id")
    user_code = body.get("user_code")
    if not device_auth_id or not user_code:
        raise ChatGptOAuthError(f"设备码响应缺少字段: {body}")
    raw_interval = body.get("interval")
    try:
        interval_seconds = max(int(float(raw_interval)), 1)
    except (TypeError, ValueError):
        interval_seconds = 5
    return DeviceAuthorization(device_auth_id=device_auth_id, user_code=user_code, interval_seconds=interval_seconds)


async def exchange_authorization_code(
    code: str, verifier: str, *, redirect_uri: str = DEVICE_REDIRECT_URI
) -> ChatGptCredential:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
            },
        )
    if response.status_code >= 400:
        raise ChatGptOAuthError(f"兑换授权码失败（HTTP {response.status_code}）: {response.text[:300]}")
    return _credential_from_token(response.json())


async def poll_device_authorization(device: DeviceAuthorization) -> ChatGptCredential:
    deadline = time.monotonic() + DEVICE_CODE_TIMEOUT_SECONDS
    interval = device.interval_seconds
    async with httpx.AsyncClient(timeout=30) as client:
        while time.monotonic() < deadline:
            response = await client.post(
                DEVICE_TOKEN_URL,
                json={"device_auth_id": device.device_auth_id, "user_code": device.user_code},
            )
            if response.status_code == 200:
                body = response.json()
                code = body.get("authorization_code")
                verifier = body.get("code_verifier")
                if not code or not verifier:
                    raise ChatGptOAuthError(f"设备授权响应缺少字段: {body}")
                return await exchange_authorization_code(code, verifier)
            if response.status_code in (403, 404):
                await asyncio.sleep(interval)
                continue
            body = response.text
            code = _error_code(body)
            if code == "deviceauth_authorization_pending":
                await asyncio.sleep(interval)
                continue
            if code == "slow_down":
                interval += 5
                await asyncio.sleep(interval)
                continue
            raise ChatGptOAuthError(f"设备授权失败（HTTP {response.status_code}）: {body[:300]}")
    raise ChatGptOAuthError("设备码登录超时，请重新发起登录")


async def refresh_credential(refresh_token: str) -> ChatGptCredential:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLIENT_ID,
            },
        )
    if response.status_code >= 400:
        raise ChatGptOAuthError(f"刷新令牌失败（HTTP {response.status_code}）: {response.text[:300]}")
    return _credential_from_token(response.json())
