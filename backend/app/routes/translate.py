import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.translators.microsoft import MicrosoftTranslator

router = APIRouter()


class TranslateIn(BaseModel):
    text: str
    from_lang: str = Field(default="auto")
    to_lang: str

    # also accept { "from": "...", "to": "..." }
    from_: str | None = Field(default=None, alias="from")
    to: str | None = Field(default=None, alias="to")

    class Config:
        populate_by_name = True


@router.post("/translate")
async def translate(payload: TranslateIn):
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is required")

    from_lang = (payload.from_ or payload.from_lang or "auto").strip()
    to_lang = (payload.to or payload.to_lang or "").strip()
    if not to_lang:
        raise HTTPException(status_code=400, detail="to_lang is required")

    # Treat "auto" as auto-detect (Microsoft: omit "from")
    from_is_auto = from_lang.lower() in ("auto", "detect", "")
    if (not from_is_auto) and from_lang.lower() == to_lang.lower():
        raise HTTPException(
            status_code=400,
            detail="From and To languages cannot be the same",
        )

    try:
        translator = MicrosoftTranslator()
        translated = await translator.translate(
            text=text,
            from_lang=None if from_is_auto else from_lang,
            to_lang=to_lang,
        )
        return {"translatedText": translated}

    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code == 429:
            raise HTTPException(status_code=429, detail="Quota exceeded. Try again later.")
        if code in (401, 403):
            raise HTTPException(status_code=403, detail="Translator key/region not authorized.")
        if 400 <= code < 500:
            raise HTTPException(status_code=400, detail="Bad request to translator service.")
        raise HTTPException(status_code=502, detail="Translator service error.")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Translation failed: {e}")
