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


# ── Helpers food_library ──────────────────────────────────────────────────────

def _enrich_with_library(items: list[dict]) -> list[dict]:
    """
    Pour chaque item retourné par Claude :
    si l'aliment est connu en bibliothèque (use_count > 2),
    remplace ses valeurs nutritionnelles par celles de la bibliothèque (scalées à qty_g).
    """
    import database as _db
    enriched = []
    for it in items:
        name = it.get("name", "").strip()
        qty  = it.get("qty_g") or 0
        lib  = _db.get_food_from_library(name) if name else None
        if lib and lib["use_count"] > 2 and qty > 0:
            s = qty / 100.0
            it = {
                "name":              name,
                "qty_g":             qty,
                "kcal":              round(lib["kcal"]              * s, 1),
                "prot_g":            round(lib["prot_g"]            * s, 1),
                "carb_g":            round(lib["carb_g"]            * s, 1),
                "carb_simple_g":     round(lib["carb_simple_g"]     * s, 1),
                "carb_complex_g":    round(lib["carb_complex_g"]    * s, 1),
                "fat_g":             round(lib["fat_g"]             * s, 1),
                "fat_saturated_g":   round(lib["fat_saturated_g"]   * s, 1),
                "fat_unsaturated_g": round(lib["fat_unsaturated_g"] * s, 1),
                "fiber_g":           round(lib["fiber_g"]           * s, 1),
                "sodium_mg":         round(lib["sodium_mg"]         * s, 1),
                "calcium_mg":        round(lib["calcium_mg"]        * s, 1),
                "iron_mg":           round(lib["iron_mg"]           * s, 2),
                "vitamin_c_mg":      round(lib["vitamin_c_mg"]      * s, 1),
                "potassium_mg":      round(lib["potassium_mg"]      * s, 1),
            }
        enriched.append(it)
    return enriched


def _update_library(items: list[dict]) -> None:
    """Met à jour food_library après un appel Claude réussi."""
    import database as _db
    from datetime import datetime as _dt
    today = _dt.utcnow().date().isoformat()
    for it in items:
        _db.upsert_food_item(
            name=(it.get("name") or "").strip(),
            qty_g=it.get("qty_g") or 0,
            item=it,
            meal_date=today,
        )


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
    items = _parse_json_items(raw)
    _update_library(items)
    return _enrich_with_library(items)


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
    items = _parse_json_items(raw)
    _update_library(items)
    return _enrich_with_library(items)


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


def _weekly_plan_prompt(
    profile: dict | None,
    meal_types: list[str] | None = None,
    batch_size: int = 4,
) -> str:
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

    if not meal_types:
        meal_types = ["petit_dej", "dejeuner", "diner"]

    LABELS = {
        "petit_dej": "Petit déjeuner",
        "dejeuner":  "Déjeuner",
        "gouter":    "Goûter",
        "diner":     "Dîner",
    }
    # Valeurs approximatives par repas (kcal, prot, carb, fat)
    APPROX = {
        "petit_dej": (420, 28, 45, 12),
        "dejeuner":  (580, 55, 70, 15),
        "gouter":    (200, 10, 25,  8),
        "diner":     (450, 42, 40, 14),
    }

    valid = [m for m in meal_types if m in LABELS]
    meals_str = ", ".join(LABELS[m] for m in valid)
    batch_types = [m for m in valid if m == "dejeuner"]  # déjeuner = batch par défaut

    # Construction du template JSON sans f-string (évite les conflits de braces)
    meal_entries = []
    for m in valid:
        kcal, prot, carb, fat = APPROX.get(m, (400, 30, 45, 12))
        is_batch = "true" if m in batch_types else "false"
        meal_entries.append(
            f'        "{m}": {{"name": "...", "items": ["Aliment 1 quantité", "Aliment 2 quantité"], '
            f'"kcal": {kcal}, "prot_g": {prot}, "carb_g": {carb}, "fat_g": {fat}, "batch": {is_batch}}}'
        )
    meals_tpl = ",\n".join(meal_entries)
    total_kcal = sum(APPROX.get(m, (400,))[0] for m in valid)
    total_prot = sum(APPROX.get(m, (0, 30))[1] for m in valid)

    json_schema = (
        '{\n  "days": [\n    {\n      "day": "Lundi",\n      "meals": {\n'
        + meals_tpl
        + f'\n      }},\n      "total_kcal": {total_kcal}, "total_prot": {total_prot}\n    }}\n  ],\n'
        '  "shopping_list": {\n'
        '    "Viandes & Poissons": [{"item": "Poulet (filets)", "qty": "750g", "note": "5 portions batch"}],\n'
        '    "Légumes":            [{"item": "Brocolis", "qty": "500g", "note": ""}],\n'
        '    "Féculents":          [{"item": "Riz blanc", "qty": "600g", "note": ""}],\n'
        '    "Produits laitiers":  [{"item": "Yaourt grec 0%", "qty": "1 kg", "note": ""}],\n'
        '    "Fruits":             [{"item": "Bananes", "qty": "5 pièces", "note": ""}],\n'
        '    "Épicerie":           [{"item": "Flocons d\'avoine", "qty": "250g", "note": ""}]\n'
        '  }\n}'
    )

    return (
        f"Tu es nutritionniste et meal planner expert en batch cooking.\n\n"
        f"Profil : {gender}, {age} ans, {weight} kg, objectif {goal_label}.\n"
        f"Objectifs journaliers : {kcal_t} kcal, {prot_t}g protéines, {carb_t}g glucides, {fat_t}g lipides.\n"
        f"Repas à planifier cette semaine : {meals_str}.\n"
        f"Taille des batchs : {batch_size} portions — cuisinées la veille au soir "
        f"(dimanche soir → semaine, lundi soir → mardi, etc.).\n\n"
        "Génère un plan alimentaire Lundi-Vendredi.\n"
        "Règles absolues :\n"
        f"- N'inclure QUE les repas : {meals_str}\n"
        f"- Les déjeuners sont \"batch\": true, cuisinés en {batch_size} portions conservées 24-48h au frigo\n"
        "- Propose uniquement des plats qui se conservent bien au réfrigérateur\n"
        "- Varie les protéines : poulet 2-3×, saumon 1-2×, thon 1×, œufs 2× max\n"
        f"- Chaque jour : {kcal_t}±200 kcal et {prot_t}±15 g protéines\n"
        "- Aliments : riz blanc, poulet, saumon, œufs, patate douce, brocolis, épinards, avocat, "
        "fromage blanc 0%, banane, pomme, amandes, pain complet, houmous, thon en boîte, lentilles, yaourt grec 0%\n\n"
        "Retourne UNIQUEMENT ce JSON valide, sans texte autour :\n"
        + json_schema
    )


# ── 4. Plan semaine → Claude ───────────────────────────────────────────────────

async def generate_weekly_plan(
    profile: dict | None,
    history: list[dict],
    meal_types: list[str] | None = None,
    batch_size: int = 4,
) -> dict:
    prompt = _weekly_plan_prompt(profile, meal_types, batch_size)
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
