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


# ── Helpers pour plan semaine ──────────────────────────────────────────────────

def _parse_json_dict(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Réponse Claude non parsable : {exc} — reçu : {raw[:200]}",
        )
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Claude n'a pas renvoyé un objet JSON.")
    return data


def _weekly_plan_prompt(profile: dict | None) -> str:
    if profile:
        kcal_t = round(profile.get("target_kcal", 1850))
        prot_t = round(profile.get("target_prot", 156))
        carb_t = round(profile.get("target_carb", 208))
        fat_t  = round(profile.get("target_fat",  52))
        gender = profile.get("gender", "homme")
        age    = profile.get("age",    28)
        weight = profile.get("weight_kg", 78)
        goal   = profile.get("goal", "recompo")
        goal_label = {"masse": "prise de masse", "graisse": "perte de graisse",
                      "recompo": "recomposition"}.get(goal, goal)
    else:
        kcal_t, prot_t, carb_t, fat_t = 1850, 156, 208, 52
        gender, age, weight, goal_label = "homme", 28, 78, "recomposition"

    return f"""Tu es nutritionniste et meal planner expert en batch cooking.

Profil : {gender}, {age} ans, {weight} kg, objectif {goal_label}.
Objectifs journaliers : {kcal_t} kcal, {prot_t}g protéines, {carb_t}g glucides, {fat_t}g lipides.
Contraintes : cuisine seul, batch cooking le dimanche pour toute la semaine.

Génère un plan alimentaire Lundi-Vendredi, 3 repas/jour.
Règles absolues :
- Déjeuners TOUJOURS "batch": true (tous préparés en lot le dimanche)
- Varie les protéines : poulet 2-3×, saumon 1-2×, thon 1×, œufs 2× max
- Chaque jour : {kcal_t}±200 kcal et {prot_t}±15 g protéines
- Aliments : riz blanc, poulet, saumon, œufs, patate douce, brocolis, épinards, avocat, fromage blanc 0%, banane, pomme, amandes, pain complet, houmous, thon en boîte, lentilles, yaourt grec 0%

Retourne UNIQUEMENT ce JSON valide, sans texte autour :
{{
  "days": [
    {{
      "day": "Lundi",
      "meals": {{
        "petit_dej": {{"name": "...", "items": ["Aliment quantité"], "kcal": 420, "prot_g": 28, "batch": false}},
        "dejeuner":  {{"name": "...", "items": ["Aliment quantité"], "kcal": 580, "prot_g": 55, "batch": true}},
        "diner":     {{"name": "...", "items": ["Aliment quantité"], "kcal": 450, "prot_g": 42, "batch": false}}
      }},
      "total_kcal": 1450,
      "total_prot": 125
    }}
  ],
  "shopping_list": {{
    "Viandes & Poissons": [{{"item": "Poulet (filets)", "qty": "750g", "note": "5 portions batch"}}],
    "Légumes":            [{{"item": "Brocolis", "qty": "500g", "note": ""}}],
    "Féculents":          [{{"item": "Riz blanc", "qty": "600g", "note": ""}}],
    "Produits laitiers":  [{{"item": "Yaourt grec 0%", "qty": "1 kg", "note": ""}}],
    "Fruits":             [{{"item": "Bananes", "qty": "5 pièces", "note": ""}}],
    "Épicerie":           [{{"item": "Flocons d'avoine", "qty": "250g", "note": ""}}]
  }}
}}"""


# ── 4. Plan semaine → Claude ───────────────────────────────────────────────────

async def generate_weekly_plan(profile: dict | None, history: list[dict]) -> dict:
    prompt = _weekly_plan_prompt(profile)
    try:
        message = await claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Claude API error : {exc}")

    raw = message.content[0].text
    print("[ai] weekly-plan brut :", raw[:300])
    return _parse_json_dict(raw)
