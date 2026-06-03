from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import base64
from datetime import date as date_type

from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

import database as db

app = FastAPI(title="Suivi Nutrition", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ───────────────────────────────────────────────────────────

class ProfileIn(BaseModel):
    name: str
    gender: str       # 'homme' / 'femme'
    age: int
    weight_kg: float
    height_cm: float
    goal: str         # 'masse' / 'graisse' / 'recompo'

    @field_validator("gender")
    @classmethod
    def check_gender(cls, v):
        if v not in ("homme", "femme"):
            raise ValueError("gender doit être 'homme' ou 'femme'")
        return v

    @field_validator("goal")
    @classmethod
    def check_goal(cls, v):
        if v not in ("masse", "graisse", "recompo"):
            raise ValueError("goal doit être 'masse', 'graisse' ou 'recompo'")
        return v


class FoodItem(BaseModel):
    name: str
    qty_g: float
    kcal: float
    prot_g: float
    carb_g: float
    fat_g: float
    # Champs enrichis — Claude les retourne, Pydantic les conservait pas avant
    carb_simple_g:     float = 0
    carb_complex_g:    float = 0
    fat_saturated_g:   float = 0
    fat_unsaturated_g: float = 0
    fiber_g:           float = 0
    sodium_mg:         float = 0
    calcium_mg:        float = 0
    iron_mg:           float = 0
    vitamin_c_mg:      float = 0
    potassium_mg:      float = 0


class MealConfirmIn(BaseModel):
    date: str
    meal_type: str
    description: str = ""
    meal_name: str = ""
    items: list[FoodItem]

    @field_validator("meal_type")
    @classmethod
    def check_meal_type(cls, v):
        valid = ("petit_dej", "dejeuner", "gouter", "diner")
        if v not in valid:
            raise ValueError(f"meal_type doit être l'un de {valid}")
        return v


# ── Profile ───────────────────────────────────────────────────────────────────

@app.get("/profile")
def get_profile():
    profile = db.get_profile()
    if not profile:
        raise HTTPException(status_code=404, detail="Profil non trouvé")
    return profile


@app.post("/profile")
def upsert_profile(data: ProfileIn):
    return db.upsert_profile(data.model_dump())


# ── Today ─────────────────────────────────────────────────────────────────────

@app.get("/today")
def get_today():
    today = date_type.today().isoformat()
    summary = db.get_daily_summary(today)
    profile = db.get_profile()
    if profile:
        summary["targets"] = {
            "kcal": profile["target_kcal"],
            "prot": profile["target_prot"],
            "carb": profile["target_carb"],
            "fat":  profile["target_fat"],
        }
    return summary


# ── Meals — read ──────────────────────────────────────────────────────────────

# DOIT être déclaré AVANT /meals/{target_date}/{meal_type} (FastAPI match en ordre)
@app.get("/meals/recent/{meal_type}")
def get_recent_meals(meal_type: str, limit: int = Query(default=5, ge=1, le=10)):
    return db.get_recent_meals_by_type(meal_type, limit)


@app.get("/meals/{target_date}/{meal_type}")
def get_meal_by_type(target_date: str, meal_type: str):
    meal = db.get_meal_by_type(target_date, meal_type)
    if not meal:
        raise HTTPException(status_code=404, detail="Repas non trouvé")
    return meal


# ── Meals — AI input (voice / photo / text) ──────────────────────────────────

class TextMealIn(BaseModel):
    text: str


@app.post("/meals/text")
async def meals_text(data: TextMealIn):
    import ai
    return await ai.analyze_food_text(data.text)  # {meal_name, items}


@app.post("/meals/voice")
async def meals_voice(audio: UploadFile = File(...)):
    import ai
    audio_bytes = await audio.read()
    mime_type = audio.content_type or "audio/webm"
    text   = await ai.transcribe_voice(audio_bytes, mime_type=mime_type)
    result = await ai.analyze_food_text(text)      # {meal_name, items}
    return {"transcription": text, **result}


@app.post("/meals/photo")
async def meals_photo(image: UploadFile = File(...)):
    import ai
    image_bytes = await image.read()
    image_b64   = base64.b64encode(image_bytes).decode()
    media_type  = image.content_type or "image/jpeg"
    return await ai.analyze_food_photo(image_b64, media_type=media_type)  # {meal_name, items}


# ── Meals — confirm & delete ──────────────────────────────────────────────────

@app.post("/meals/confirm")
def meals_confirm(data: MealConfirmIn):
    items = [item.model_dump() for item in data.items]
    total_kcal = sum(i["kcal"]   for i in items)
    total_prot = sum(i["prot_g"] for i in items)
    total_carb = sum(i["carb_g"] for i in items)
    total_fat  = sum(i["fat_g"]  for i in items)

    meal = db.insert_meal({
        "date":        data.date,
        "meal_type":   data.meal_type,
        "description": data.description,
        "meal_name":   data.meal_name,
        "items":       items,
        "total_kcal":  round(total_kcal, 1),
        "total_prot":  round(total_prot, 1),
        "total_carb":  round(total_carb, 1),
        "total_fat":   round(total_fat, 1),
    })
    return meal


@app.delete("/meals/{meal_id}")
def delete_meal(meal_id: int):
    if not db.delete_meal(meal_id):
        raise HTTPException(status_code=404, detail="Repas non trouvé")
    return {"deleted": meal_id}


@app.delete("/meals/{meal_id}/items/{item_index}")
def delete_meal_item(meal_id: int, item_index: int):
    meal = db.get_meal(meal_id)
    if not meal:
        raise HTTPException(status_code=404, detail="Repas non trouvé")
    items = list(meal.get("items") or [])
    if not (0 <= item_index < len(items)):
        raise HTTPException(status_code=404, detail="Ingrédient non trouvé")
    items.pop(item_index)
    if not items:
        db.delete_meal(meal_id)
        return {"deleted_meal": meal_id}
    return db.update_meal_items(meal_id, items)


# ── History ───────────────────────────────────────────────────────────────────

@app.get("/history")
def get_history(days: int = Query(default=7, ge=1, le=30)):
    return db.get_history(days)


# ── Food library ─────────────────────────────────────────────────────────────

@app.get("/food-library")
def food_library():
    return db.get_food_library()


# ── Admin ────────────────────────────────────────────────────────────────────

ADMIN_KEY = "nutrition-seed-2026"


@app.post("/admin/seed")
def admin_seed(x_admin_key: str | None = Header(default=None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Clé admin invalide")
    import seed_nutrition
    days = seed_nutrition.run_seed()
    return {"status": "ok", "message": f"{days} jours insérés"}


# ── Plan semaine ─────────────────────────────────────────────────────────────

class WeeklyPlanRequest(BaseModel):
    meal_types: list[str] = ["petit_dej", "dejeuner", "diner"]
    batch_size: int = 4


@app.post("/weekly-plan")
async def weekly_plan(req: WeeklyPlanRequest = WeeklyPlanRequest()):
    import ai
    profile = db.get_profile()
    history = db.get_history(14)
    return await ai.generate_weekly_plan(profile, history, req.meal_types, req.batch_size)


# ── Frontend statique ─────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.parent
app.mount("/", StaticFiles(directory=BASE_DIR / "frontend", html=True), name="static")
