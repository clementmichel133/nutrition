import sqlite3
import json
from datetime import datetime, date
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "nutrition.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS profile (
            id          INTEGER PRIMARY KEY,
            name        TEXT,
            gender      TEXT,
            age         INTEGER,
            weight_kg   REAL,
            height_cm   REAL,
            goal        TEXT,
            target_kcal REAL,
            target_prot REAL,
            target_carb REAL,
            target_fat  REAL,
            updated_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS meals (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            date              TEXT NOT NULL,
            meal_type         TEXT NOT NULL,
            description       TEXT,
            items             TEXT,
            total_kcal        REAL,
            total_prot        REAL,
            total_carb        REAL,
            total_fat         REAL,
            total_fiber       REAL DEFAULT 0,
            total_carb_simple REAL DEFAULT 0,
            total_carb_complex REAL DEFAULT 0,
            total_fat_sat     REAL DEFAULT 0,
            total_fat_unsat   REAL DEFAULT 0,
            total_sodium      REAL DEFAULT 0,
            total_calcium     REAL DEFAULT 0,
            total_iron        REAL DEFAULT 0,
            total_vit_c       REAL DEFAULT 0,
            total_potassium   REAL DEFAULT 0,
            created_at        TEXT
        );
    """)
    conn.commit()
    conn.close()
    _migrate_meals()


def _migrate_meals():
    """Ajoute les nouvelles colonnes aux bases existantes sans les écraser."""
    new_cols = [
        ("total_fiber",        "REAL DEFAULT 0"),
        ("total_carb_simple",  "REAL DEFAULT 0"),
        ("total_carb_complex", "REAL DEFAULT 0"),
        ("total_fat_sat",      "REAL DEFAULT 0"),
        ("total_fat_unsat",    "REAL DEFAULT 0"),
        ("total_sodium",       "REAL DEFAULT 0"),
        ("total_calcium",      "REAL DEFAULT 0"),
        ("total_iron",         "REAL DEFAULT 0"),
        ("total_vit_c",        "REAL DEFAULT 0"),
        ("total_potassium",    "REAL DEFAULT 0"),
    ]
    conn = get_db()
    for col, typ in new_cols:
        try:
            conn.execute(f"ALTER TABLE meals ADD COLUMN {col} {typ}")
        except Exception:
            pass  # colonne déjà présente
    conn.commit()
    conn.close()


# ── Macro calculation ─────────────────────────────────────────────────────────

def compute_targets(gender: str, age: int, weight_kg: float, height_cm: float, goal: str) -> dict:
    if gender == "homme":
        bmr = 88.36 + (13.4 * weight_kg) + (4.8 * height_cm) - (5.7 * age)
    else:
        bmr = 447.6 + (9.2 * weight_kg) + (3.1 * height_cm) - (4.3 * age)

    multipliers = {"masse": 1.15, "graisse": 0.85, "recompo": 1.0}
    prot_per_kg = {"masse": 2.0, "graisse": 2.2, "recompo": 2.0}
    carb_pct    = {"masse": 0.50, "graisse": 0.40, "recompo": 0.45}

    target_kcal = bmr * multipliers[goal]
    target_prot = prot_per_kg[goal] * weight_kg          # g
    target_fat  = (target_kcal * 0.25) / 9               # g  (9 kcal/g)
    target_carb = (target_kcal * carb_pct[goal]) / 4     # g  (4 kcal/g)

    return {
        "target_kcal": round(target_kcal, 1),
        "target_prot": round(target_prot, 1),
        "target_carb": round(target_carb, 1),
        "target_fat":  round(target_fat, 1),
    }


# ── Profile CRUD ──────────────────────────────────────────────────────────────

def get_profile() -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_profile(data: dict) -> dict:
    targets = compute_targets(
        gender=data["gender"],
        age=data["age"],
        weight_kg=data["weight_kg"],
        height_cm=data["height_cm"],
        goal=data["goal"],
    )
    now = datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute("""
        INSERT INTO profile (id, name, gender, age, weight_kg, height_cm, goal,
                             target_kcal, target_prot, target_carb, target_fat, updated_at)
        VALUES (1, :name, :gender, :age, :weight_kg, :height_cm, :goal,
                :target_kcal, :target_prot, :target_carb, :target_fat, :updated_at)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, gender=excluded.gender, age=excluded.age,
            weight_kg=excluded.weight_kg, height_cm=excluded.height_cm, goal=excluded.goal,
            target_kcal=excluded.target_kcal, target_prot=excluded.target_prot,
            target_carb=excluded.target_carb, target_fat=excluded.target_fat,
            updated_at=excluded.updated_at
    """, {**data, **targets, "updated_at": now})
    conn.commit()
    conn.close()
    return get_profile()


# ── Meals CRUD ────────────────────────────────────────────────────────────────

def _meal_row_to_dict(row) -> dict:
    d = dict(row)
    if d.get("items"):
        d["items"] = json.loads(d["items"])
    return d


def get_recent_meals_by_type(meal_type: str, limit: int = 5) -> list[dict]:
    """Derniers repas distincts pour ce type, hors aujourd'hui, dédupliqués par contenu."""
    today = date.today().isoformat()
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM meals
        WHERE meal_type = ? AND date < ?
        ORDER BY date DESC, created_at DESC
        LIMIT 30
    """, (meal_type, today)).fetchall()
    conn.close()

    meals = [_meal_row_to_dict(r) for r in rows]

    seen: set[str] = set()
    unique: list[dict] = []
    for m in meals:
        items = m.get("items") or []
        key = json.dumps(
            [(it.get("name", ""), it.get("qty_g", 0)) for it in items],
            ensure_ascii=False,
        )
        if key not in seen:
            seen.add(key)
            unique.append(m)
        if len(unique) >= limit:
            break

    return unique


def get_meals_by_date(target_date: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM meals WHERE date = ? ORDER BY created_at", (target_date,)
    ).fetchall()
    conn.close()
    return [_meal_row_to_dict(r) for r in rows]


def get_meal(meal_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    conn.close()
    return _meal_row_to_dict(row) if row else None


def get_meal_by_type(target_date: str, meal_type: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM meals WHERE date = ? AND meal_type = ?", (target_date, meal_type)
    ).fetchone()
    conn.close()
    return _meal_row_to_dict(row) if row else None


def _sum(items: list, key: str) -> float:
    return round(sum((it.get(key) or 0) for it in items), 2)


def insert_meal(data: dict) -> dict:
    items = data.get("items", [])
    items_json = json.dumps(items, ensure_ascii=False)
    now = datetime.utcnow().isoformat()

    conn = get_db()
    cur = conn.execute("""
        INSERT INTO meals (date, meal_type, description, items,
                           total_kcal, total_prot, total_carb, total_fat,
                           total_fiber, total_carb_simple, total_carb_complex,
                           total_fat_sat, total_fat_unsat,
                           total_sodium, total_calcium, total_iron,
                           total_vit_c, total_potassium,
                           created_at)
        VALUES (:date, :meal_type, :description, :items,
                :total_kcal, :total_prot, :total_carb, :total_fat,
                :total_fiber, :total_carb_simple, :total_carb_complex,
                :total_fat_sat, :total_fat_unsat,
                :total_sodium, :total_calcium, :total_iron,
                :total_vit_c, :total_potassium,
                :created_at)
    """, {
        "date":               data["date"],
        "meal_type":          data["meal_type"],
        "description":        data.get("description", ""),
        "items":              items_json,
        "total_kcal":         data.get("total_kcal", 0),
        "total_prot":         data.get("total_prot", 0),
        "total_carb":         data.get("total_carb", 0),
        "total_fat":          data.get("total_fat", 0),
        "total_fiber":        _sum(items, "fiber_g"),
        "total_carb_simple":  _sum(items, "carb_simple_g"),
        "total_carb_complex": _sum(items, "carb_complex_g"),
        "total_fat_sat":      _sum(items, "fat_saturated_g"),
        "total_fat_unsat":    _sum(items, "fat_unsaturated_g"),
        "total_sodium":       _sum(items, "sodium_mg"),
        "total_calcium":      _sum(items, "calcium_mg"),
        "total_iron":         _sum(items, "iron_mg"),
        "total_vit_c":        _sum(items, "vitamin_c_mg"),
        "total_potassium":    _sum(items, "potassium_mg"),
        "created_at":         now,
    })
    meal_id = cur.lastrowid
    conn.commit()
    conn.close()
    return get_meal(meal_id)


def delete_meal(meal_id: int) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ── Daily summary ─────────────────────────────────────────────────────────────

def get_daily_summary(target_date: str) -> dict:
    meals = get_meals_by_date(target_date)
    totals = {k: 0.0 for k in [
        "kcal", "prot", "carb", "fat",
        "fiber", "carb_simple", "carb_complex",
        "fat_sat", "fat_unsat",
        "sodium", "calcium", "iron", "vit_c", "potassium",
    ]}
    for m in meals:
        totals["kcal"]         += m.get("total_kcal")          or 0
        totals["prot"]         += m.get("total_prot")          or 0
        totals["carb"]         += m.get("total_carb")          or 0
        totals["fat"]          += m.get("total_fat")           or 0
        totals["fiber"]        += m.get("total_fiber")         or 0
        totals["carb_simple"]  += m.get("total_carb_simple")   or 0
        totals["carb_complex"] += m.get("total_carb_complex")  or 0
        totals["fat_sat"]      += m.get("total_fat_sat")       or 0
        totals["fat_unsat"]    += m.get("total_fat_unsat")     or 0
        totals["sodium"]       += m.get("total_sodium")        or 0
        totals["calcium"]      += m.get("total_calcium")       or 0
        totals["iron"]         += m.get("total_iron")          or 0
        totals["vit_c"]        += m.get("total_vit_c")         or 0
        totals["potassium"]    += m.get("total_potassium")     or 0
    return {"date": target_date, "meals": meals, "totals": totals}


# ── History ───────────────────────────────────────────────────────────────────

def get_history(days: int = 7) -> list[dict]:
    conn = get_db()
    rows = conn.execute("""
        SELECT date,
               SUM(total_kcal) AS kcal,
               SUM(total_prot) AS prot,
               SUM(total_carb) AS carb,
               SUM(total_fat)  AS fat
        FROM meals
        GROUP BY date
        ORDER BY date DESC
        LIMIT ?
    """, (days,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Bootstrap ─────────────────────────────────────────────────────────────────
init_db()
