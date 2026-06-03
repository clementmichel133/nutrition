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
{
  "meal_name": "Nom court du plat (4-5 mots)",
  "items": [
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
}
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
    """Extrait une liste JSON (plan semaine). Toujours une liste."""
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
    return data


def _parse_json_meal(raw: str) -> dict:
    """Parse {"meal_name": "...", "items": [...]} — rétrocompatible avec l'ancien format liste."""
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Réponse Claude non parsable : {exc} — reçu : {raw[:200]}",
        )
    if isinstance(data, list):
        return {"meal_name": "", "items": data}
    if isinstance(data, dict) and "items" in data:
        return {"meal_name": (data.get("meal_name") or "").strip(), "items": data["items"]}
    raise HTTPException(status_code=502, detail="Format JSON inattendu de Claude.")


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

    raw    = message.content[0].text
    result = _parse_json_meal(raw)
    print("[ai] meal_name:", result.get("meal_name"), "| items:", len(result.get("items", [])))
    _update_library(result["items"])
    result["items"] = _enrich_with_library(result["items"])
    return result


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

    raw    = message.content[0].text
    result = _parse_json_meal(raw)
    print("[ai] vision meal_name:", result.get("meal_name"), "| items:", len(result.get("items", [])))
    _update_library(result["items"])
    result["items"] = _enrich_with_library(result["items"])
    return result


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
        "petit_dej": "petit déjeuner",
        "dejeuner":  "déjeuner",
        "gouter":    "goûter",
        "diner":     "dîner",
    }
    valid     = [m for m in meal_types if m in LABELS]
    meals_str = ", ".join(LABELS[m] for m in valid)

    # ── Exemple de sessions selon batch_size ──────────────────────────────────
    DAYS      = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
    batch_n   = min(batch_size, 5)
    b_days    = DAYS[:batch_n]
    rem_days  = DAYS[batch_n:]

    # Construire les exemples de sessions (évite les {{}} dans les f-strings)
    sessions_parts = []

    if "dejeuner" in valid:
        dej_serves = json.dumps([f"{d} déjeuner" for d in b_days], ensure_ascii=False)
        sessions_parts.append(
            '    {\n'
            '      "cook_on": "Dimanche soir",\n'
            f'      "serves": {dej_serves},\n'
            '      "recipe": "Bol riz poulet brocolis",\n'
            '      "ingredients": [\n'
            f'        {{"item": "Poulet (filets)", "qty": "{150 * batch_n}g"}},\n'
            f'        {{"item": "Riz blanc cru", "qty": "{200 * batch_n}g"}},\n'
            f'        {{"item": "Brocolis", "qty": "{100 * batch_n}g"}}\n'
            '      ],\n'
            f'      "portions": {batch_n},\n'
            '      "macros_per_portion": {"kcal": 580, "prot_g": 55, "carb_g": 70, "fat_g": 15}\n'
            '    }'
        )
        if rem_days:
            rem_serves = json.dumps([f"{d} déjeuner" for d in rem_days], ensure_ascii=False)
            sessions_parts.append(
                '    {\n'
                f'      "cook_on": "{DAYS[batch_n - 1]} soir",\n'
                f'      "serves": {rem_serves},\n'
                '      "recipe": "Lentilles thon épinards",\n'
                '      "ingredients": [\n'
                f'        {{"item": "Lentilles cuites", "qty": "{200 * len(rem_days)}g"}},\n'
                f'        {{"item": "Thon en boîte", "qty": "{120 * len(rem_days)}g"}}\n'
                '      ],\n'
                f'      "portions": {len(rem_days)},\n'
                '      "macros_per_portion": {"kcal": 510, "prot_g": 48, "carb_g": 52, "fat_g": 10}\n'
                '    }'
            )

    if "diner" in valid:
        sessions_parts.append(
            '    {\n'
            '      "cook_on": "Dimanche soir",\n'
            '      "serves": ["Lundi dîner"],\n'
            '      "recipe": "Saumon vapeur + épinards",\n'
            '      "ingredients": [\n'
            '        {"item": "Saumon", "qty": "130g"},\n'
            '        {"item": "Épinards", "qty": "150g"}\n'
            '      ],\n'
            '      "portions": 1,\n'
            '      "macros_per_portion": {"kcal": 390, "prot_g": 37, "carb_g": 7, "fat_g": 21}\n'
            '    },\n'
            '    {\n'
            '      "cook_on": "Lundi soir",\n'
            '      "serves": ["Mardi dîner"],\n'
            '      "recipe": "Poulet ratatouille",\n'
            '      "ingredients": [\n'
            '        {"item": "Poulet (filets)", "qty": "140g"},\n'
            '        {"item": "Ratatouille maison", "qty": "200g"}\n'
            '      ],\n'
            '      "portions": 1,\n'
            '      "macros_per_portion": {"kcal": 440, "prot_g": 45, "carb_g": 28, "fat_g": 12}\n'
            '    }'
        )

    if "petit_dej" in valid:
        pdj_serves = json.dumps(
            [f"{d} petit déjeuner" for d in DAYS[:3]], ensure_ascii=False
        )
        sessions_parts.append(
            '    {\n'
            '      "cook_on": "Dimanche soir (prép.)",\n'
            f'      "serves": {pdj_serves},\n'
            '      "recipe": "Overnight oats yaourt banane × 3 bocaux",\n'
            '      "ingredients": [\n'
            '        {"item": "Flocons d\'avoine", "qty": "180g"},\n'
            '        {"item": "Yaourt grec 0%", "qty": "450g"},\n'
            '        {"item": "Bananes", "qty": "3 pièces"}\n'
            '      ],\n'
            '      "portions": 3,\n'
            '      "macros_per_portion": {"kcal": 420, "prot_g": 28, "carb_g": 58, "fat_g": 9}\n'
            '    }'
        )

    sessions_json = ",\n".join(sessions_parts)

    json_schema = (
        '{\n'
        '  "cooking_sessions": [\n'
        + sessions_json + '\n'
        '  ],\n'
        '  "shopping_list": {\n'
        '    "Viandes & Poissons": [{"item": "Poulet (filets)", "qty": "' + str(150 * batch_n) + 'g", "note": "batch déjeuners"}],\n'
        '    "Légumes":            [{"item": "Brocolis", "qty": "' + str(100 * batch_n) + 'g", "note": ""}],\n'
        '    "Féculents":          [{"item": "Riz blanc", "qty": "' + str(200 * batch_n) + 'g cru", "note": ""}],\n'
        '    "Produits laitiers":  [{"item": "Yaourt grec 0%", "qty": "1 kg", "note": ""}],\n'
        '    "Fruits":             [{"item": "Bananes", "qty": "5 pièces", "note": ""}],\n'
        '    "Épicerie":           [{"item": "Flocons d\'avoine", "qty": "250g", "note": ""}]\n'
        '  }\n'
        '}'
    )

    return (
        f"Tu es un expert en nutrition et en meal prep (batch cooking hebdomadaire).\n\n"
        f"Profil : {gender}, {age} ans, {weight} kg, objectif {goal_label}.\n"
        f"Objectifs par jour : {kcal_t} kcal · {prot_t}g protéines · {carb_t}g glucides · {fat_t}g lipides.\n"
        f"Repas à planifier (Lundi–Vendredi) : {meals_str}.\n\n"
        "═══ RÈGLES DU BATCH COOKING ═══\n\n"
        f"batch_size = {batch_size} → nombre de portions IDENTIQUES préparées en une seule session de cuisine.\n\n"
        "Déjeuners :\n"
        f"  • Cuisiner {batch_n} portions en une seule session (ex : dimanche soir → déjeuners Lun à {b_days[-1]}).\n"
        f"  • Si batch_size < 5, une 2e session couvre les jours restants.\n"
        "  • Choisir des plats qui se conservent 3-4 jours au réfrigérateur (riz, légumineuses, viandes cuites).\n\n"
        "Dîners :\n"
        "  • Cuisiner 1 portion la veille au soir (dimanche soir → lundi dîner, lundi soir → mardi dîner, etc.).\n"
        "  • Plats rapides 20-30 min, conservation 24h.\n\n"
        "Petits déjeuners (si inclus) :\n"
        "  • Si batchable (overnight oats, etc.) : préparer 3-5 bocaux le dimanche soir.\n"
        "  • Si non batchable (œufs, etc.) : créer une session par jour, cook_on = \"Matin\".\n\n"
        "═══ STRUCTURE JSON ATTENDUE ═══\n\n"
        "Organise par SESSION DE CUISINE (quand préparer), PAS par jour de consommation.\n"
        "  • cook_on  : QUAND cuisiner (ex : \"Dimanche soir\", \"Lundi soir\", \"Matin\")\n"
        "  • serves   : liste de TOUS les repas couverts par cette session, format \"Jour repas\"\n"
        "               (ex : \"Lundi déjeuner\", \"Mardi dîner\", \"Mercredi petit déjeuner\")\n"
        "  • recipe   : nom court de la recette\n"
        "  • ingredients : quantités TOTALES pour toutes les portions de cette session\n"
        "  • portions : nombre de portions cuisinées dans cette session\n"
        "  • macros_per_portion : macros pour UNE portion (ce qu'une personne mange à un repas)\n\n"
        f"Aliments : riz blanc, poulet, saumon, œufs, patate douce, brocolis, épinards, avocat, "
        f"fromage blanc 0%, banane, pomme, amandes, pain complet, houmous, thon en boîte, lentilles, yaourt grec 0%.\n"
        f"Varie les protéines : poulet 2-3×, saumon 1-2×, thon 1×, œufs 2× max.\n"
        f"Chaque jour : {kcal_t}±200 kcal et {prot_t}±15 g protéines (somme de toutes les macros_per_portion du jour).\n\n"
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
