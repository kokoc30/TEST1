import uuid
import httpx

from app.core.settings import (
    MICROSOFT_TRANSLATOR_KEY,
    MICROSOFT_TRANSLATOR_REGION,
    MICROSOFT_TRANSLATOR_ENDPOINT,
)


class MicrosoftTranslator:
    def __init__(self) -> None:
        if not MICROSOFT_TRANSLATOR_KEY:
            raise RuntimeError("MICROSOFT_TRANSLATOR_KEY is not configured.")
        if not MICROSOFT_TRANSLATOR_REGION:
            raise RuntimeError("MICROSOFT_TRANSLATOR_REGION is not configured.")
        if not MICROSOFT_TRANSLATOR_ENDPOINT:
            raise RuntimeError("MICROSOFT_TRANSLATOR_ENDPOINT is not configured.")

    async def translate(self, text: str, from_lang: str | None, to_lang: str) -> str:
        endpoint = MICROSOFT_TRANSLATOR_ENDPOINT.rstrip("/")
        url = f"{endpoint}/translate"

        params = {"api-version": "3.0", "to": to_lang}
        if from_lang and from_lang.lower() not in ("auto", "detect"):
            params["from"] = from_lang

        headers = {
            "Ocp-Apim-Subscription-Key": MICROSOFT_TRANSLATOR_KEY,
            "Ocp-Apim-Subscription-Region": MICROSOFT_TRANSLATOR_REGION,
            "Content-Type": "application/json",
            "X-ClientTraceId": str(uuid.uuid4()),
        }

        body = [{"Text": text}]

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, params=params, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()

        try:
            return data[0]["translations"][0]["text"]
        except Exception:
            raise RuntimeError(f"Unexpected Translator response: {data!r}")
