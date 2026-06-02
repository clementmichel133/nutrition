import io
import json
import os
import re

import anthropic
from fastapi import HTTPException
from openai import AsyncOpenAI

# ── Clients ───────────────────────────────────────────────────────────────────

groq_client = AsyncOpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
)

claude_client = anthropic.AsyncAnthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
)

# ── Prompt commun (SPEC.md verbatim) ──────────────────────────────────────────

NUTRITION_PROMPT = """Tu es un expert en nutrition. Analyse ce repas et retourne \
UNIQUEMENT un JSON valide, sans texte autour :
[
  {
    "name": "nom de l'aliment",
    "qty_g": 150,
    "kcal": 165,
    "prot_g": 31,
    "carb_g": 12,
    "carb_simple_g": 2,
    "carb_complex_g": 10,
    "fat_g": 3.6,
    "fat_saturated_g": 1.1,
    "fat_unsaturated_g": 2.5,
    "fiber_g": 1.2,
    "sodium_mg": 80,
    "calcium_mg": 15,
    "iron_mg": 1.2,
    "vitamin_c_mg": 0,
    "potassium_mg": 320
  }
]
Utilise des valeurs nutritionnelles standard pour 100g.
Si la quantité n'est pas précisée, estime une portion normale.
Valeurs approximatives acceptées. Mets 0 si impossible à estimer."""

# Extension par défaut selon le MIME type
_MIME_TO_EXT: dict[str, str] = {
    "audio/webm":  "webm",
    "audio/mp4":   "mp4",
    "audio/mpeg":  "mp3",
    "audio/mp3":   "mp3",
    "audio/wav":   "wav",
    "audio/x-wav": "wav",
    "audio/ogg":   "ogg",
    "audio/flac":  "flac",
    "audio/m4a":   "m4a",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json_items(raw: str) -> list[dict]:
    """Extrait le JSON même si Claude l'enveloppe dans un bloc markdown."""
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Réponse Claude non parsable : {exc} — reçu : {raw[:200]}",
        )
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="Claude n'a pas renvoyé une liste JSON.")
    print("[ai] Claude JSON brut :", json.dumps(data, ensure_ascii=False, indent=2))
    return data


# ── 1. Transcription vocale via Groq Whisper ──────────────────────────────────

async def transcribe_voice(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    ext = _MIME_TO_EXT.get(mime_type, "webm")
    file_tuple = (f"audio.{ext}", io.BytesIO(audio_bytes), mime_type)
    try:
        response = await groq_client.audio.transcriptions.create(
            model="whisper-large-v3-turbo",
            file=file_tuple,
            language="fr",
            response_format="text",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Groq Whisper error : {exc}")
    # response est une str quand response_format="text"
    return response.strip()


# ── 2. Analyse texte → macros via Claude ─────────────────────────────────────

async def analyze_food_text(text: str) -> list[dict]:
    try:
        message = await claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": f"{NUTRITION_PROMPT}\n\nRepas : {text}",
                }
            ],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Claude API error : {exc}")

    raw = message.content[0].text
    return _parse_json_items(raw)


# ── 3. Analyse photo → macros via Claude Vision ───────────────────────────────

async def analyze_food_photo(image_b64: str, media_type: str = "image/jpeg") -> list[dict]:
    try:
        message = await claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": NUTRITION_PROMPT,
                        },
                    ],
                }
            ],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Claude Vision error : {exc}")

    raw = message.content[0].text
    return _parse_json_items(raw)
