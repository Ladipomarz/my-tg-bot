import os
import time
import json
import base64
import httpx

MAXELPAY_API_KEY = os.getenv("MAXELPAY_API_KEY", "").strip()
MAXELPAY_API_SECRET = os.getenv("MAXELPAY_API_SECRET", "").strip()  # used as encryption secret_key
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")

if not MAXELPAY_API_KEY:
    raise RuntimeError("MAXELPAY_API_KEY not set")
if not MAXELPAY_API_SECRET:
    raise RuntimeError("MAXELPAY_API_SECRET not set (used for encryption)")
if not PUBLIC_BASE_URL:
    raise RuntimeError("PUBLIC_BASE_URL not set")

MAXELPAY_CHECKOUT_URL = "https://api.maxelpay.com/v1/stg/merchant/order/checkout"


def _aes256cbc_encrypt_to_base64(secret_key: str, plaintext: str) -> str:
    """
    MaxelPay docs:
    - AES-256-CBC
    - key = UTF-8 bytes of secret_key (must be 32 bytes for AES-256)
    - iv = UTF-8 bytes of secret_key[0:16]
    - padding = PKCS7
    - output = base64 ciphertext string
    """
    key_bytes = secret_key.encode("utf-8")
    iv_bytes = secret_key[:16].encode("utf-8")

    if len(key_bytes) != 32:
        raise RuntimeError(
            f"MAXELPAY_API_SECRET must be exactly 32 characters (got {len(key_bytes)}). "
            "MaxelPay AES-256-CBC requires a 32-byte key."
        )
    if len(iv_bytes) != 16:
        raise RuntimeError("IV must be 16 bytes (first 16 chars of secret).")

    data = plaintext.encode("utf-8")

    # PKCS7 padding
    pad_len = 16 - (len(data) % 16)
    data += bytes([pad_len]) * pad_len

    # Try cryptography first (common in deployments)
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv_bytes))
        encryptor = cipher.encryptor()
        ct = encryptor.update(data) + encryptor.finalize()
        return base64.b64encode(ct).decode("utf-8")

    except ImportError:
        # Fallback: pycryptodome
        try:
            from Crypto.Cipher import AES  # type: ignore

            cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
            ct = cipher.encrypt(data)
            return base64.b64encode(ct).decode("utf-8")
        except ImportError as e:
            raise RuntimeError(
                "Need 'cryptography' or 'pycryptodome' installed for AES encryption."
            ) from e


async def create_maxelpay_checkout(
    *,
    order_id: str,
    amount_usd: float,
    user_id: int,
    user_name: str,
    user_email: str,
) -> str:
    # Build the payload (this gets encrypted)
    payload = {
        "orderID": order_id,
        "amount": float(f"{amount_usd:.2f}"),
        "currency": "USD",
        "timestamp": int(time.time()),
        "userName": (user_name or "User")[:60],
        "siteName": "My Telegram Bot",
        "userEmail": user_email,
        "redirectUrl": f"{PUBLIC_BASE_URL}/success",
        "websiteUrl": PUBLIC_BASE_URL,
        "cancelUrl": f"{PUBLIC_BASE_URL}/cancel",
        "webhookUrl": f"{PUBLIC_BASE_URL}/webhooks/maxelpay",
        # keep your telegram user id inside payload so it survives encryption
        "metadata": {"telegram_user_id": str(user_id)},
    }

    payload_str = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    encrypted_payload = _aes256cbc_encrypt_to_base64(MAXELPAY_API_SECRET, payload_str)

    # Docs: header is api-key; body is {"data": "<encrypted>"}
    headers = {
        "Content-Type": "application/json",
        "api-key": MAXELPAY_API_KEY,
    }

    body = {"data": encrypted_payload}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(MAXELPAY_CHECKOUT_URL, json=body, headers=headers)

    if r.status_code >= 400:
        raise RuntimeError(f"MaxelPay {r.status_code}: {r.text}")

    data = r.json()
    checkout_url = (
        data.get("checkoutUrl")
        or data.get("url")
        or (data.get("data") or {}).get("checkoutUrl")
    )
    if not checkout_url:
        raise RuntimeError(f"No checkout URL in response: {data}")

    return checkout_url
