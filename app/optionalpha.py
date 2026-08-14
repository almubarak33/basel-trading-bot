from __future__ import annotations
import httpx
from .config import settings

async def trigger_webhook() -> dict:
    if not settings.option_alpha_enabled:
        raise RuntimeError("Option Alpha webhook is disabled.")
    if not settings.option_alpha_webhook_url:
        raise RuntimeError("OPTION_ALPHA_WEBHOOK_URL is not configured.")

    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        response = await client.post(settings.option_alpha_webhook_url)
        response.raise_for_status()
        return {
            "status_code": response.status_code,
            "ok": True,
        }
