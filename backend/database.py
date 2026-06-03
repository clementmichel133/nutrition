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

        CREATE TABLE IF NOT EXISTS food_library (
            id                INTEGER PRIMARY KEY,
            name              TEXT UNIQUE,
            qty_ref_g         REAL,
            kcal              REAL,
            prot_g            REAL,
            carb_g            REAL,
            carb_simple_g     REAL,
            carb_complex_g    REAL,
            fat_g             REAL,
            fat_saturated_g   REAL,
            fat_unsaturated_g REAL,
            fiber_g           REAL,
            sodium_mg         REAL,
            calcium_mg        REAL,
            iron_mg           REAL,
            vitamin_c_mg      REAL,
            potassium_mg      REAL,
            use_count         INTEGER DEFAULT 1,
            last_used         TEXT
        );

        CREATE TABLE IF NOT EXISTS meals (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            date              TEXT NOT NULL,
            meal_type         TEXT NOT NULL,
            description       TEXT,
            meal_name         TEXT DEFAULT '',
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
    populate_food_library()


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
        ("meal_name",          "TEXT DEFAULT ''"),
    ]
    conn = get_db()
    for col, typ in new_cols:
        try:
            conn.execute(f"ALTER TABLE meals ADD COLUMN {col} {typ}")
        except Exception:
            pass  # colonne déjà présente
    conn.commit()
    conn.close()


# ── Food library ──────────────────────────────────────────────────────────────

_FOOD_KEYS = [
    "kcal", "prot_g", "carb_g", "carb_simple_g", "carb_complex_g",
    "fat_g", "fat_saturated_g", "fat_unsaturated_g", "fiber_g",
    "sodium_mg", "calcium_mg", "iron_mg", "vitamin_c_mg", "potassium_mg",
]

_UPSERT_SQL = """
    INSERT INTO food_library (
        name, qty_ref_g, kcal, prot_g, carb_g, carb_simple_g, carb_complex_g,
        fat_g, fat_saturated_g, fat_unsaturated_g, fiber_g,
        sodium_mg, calcium_mg, iron_mg, vitamin_c_mg, potassium_mg,
        use_count, last_used)
    VALUES (
        :name, :qty_ref_g, :kcal, :prot_g, :carb_g, :carb_simple_g, :carb_complex_g,
        :fat_g, :fat_saturated_g, :fat_unsaturated_g, :fiber_g,
        :sodium_mg, :calcium_mg, :iron_mg, :vitamin_c_mg, :potassium_mg,
        1, :last_used)
    ON CONFLICT(name) DO UPDATE SET
        qty_ref_g         = ROUND((qty_ref_g * use_count + excluded.qty_ref_g) / (use_count + 1), 1),
        kcal              = ROUND((kcal * use_count + excluded.kcal) / (use_count + 1), 2),
        prot_g            = ROUND((prot_g * use_count + excluded.prot_g) / (use_count + 1), 2),
        carb_g            = ROUND((carb_g * use_count + excluded.carb_g) / (use_count + 1), 2),
        carb_simple_g     = ROUND((carb_simple_g * use_count + excluded.carb_simple_g) / (use_count + 1), 2),
        carb_complex_g    = ROUND((carb_complex_g * use_count + excluded.carb_complex_g) / (use_count + 1), 2),
        fat_g             = ROUND((fat_g * use_count + excluded.fat_g) / (use_count + 1), 2),
        fat_saturated_g   = ROUND((fat_saturated_g * use_count + excluded.fat_saturated_g) / (use_count + 1), 2),
        fat_unsaturated_g = ROUND((fat_unsaturated_g * use_count + excluded.fat_unsaturated_g) / (use_count + 1), 2),
        fiber_g           = ROUND((fiber_g * use_count + excluded.fiber_g) / (use_count + 1), 2),
        sodium_mg         = ROUND((sodium_mg * use_count + excluded.sodium_mg) / (use_count + 1), 2),
        calcium_mg        = ROUND((calcium_mg * use_count + excluded.calcium_mg) / (use_count + 1), 2),
        iron_mg           = ROUND((iron_mg * use_count + excluded.iron_mg) / (use_count + 1), 3),
        vitamin_c_mg      = ROUND((vitamin_c_mg * use_count + excluded.vitamin_c_mg) / (use_count + 1), 2),
        potassium_mg      = ROUND((potassium_mg * use_count + excluded.potassium_mg) / (use_count + 1), 2),
        use_count         = use_count + 1,
        last_used         = excluded.last_used
"""


def upsert_food_item(name: str, qty_g: float, item: dict, meal_date: str | None = None) -> None:
    """Insère ou met à jour un aliment (valeurs normalisées à 100g, moyenne pondérée)."""
    name = name.strip()
    if not name or not qty_g or qty_g <= 0:
        return
    today = meal_date or datetime.utcnow().date().isoformat()
    scale = 100.0 / qty_g
    per100 = {k: round((item.get(k) or 0) * scale, 3) for k in _FOOD_KEYS}
    conn = get_db()
    conn.execute(_UPSERT_SQL, {"name": name, "qty_ref_g": round(qty_g, 1),
                                "last_used": today, **per100})
    conn.commit()
    conn.close()


def populate_food_library() -> int:
    """Construit la bibliothèque depuis l'historique — seulement si la table est vide."""
    conn = get_db()
    existing = conn.execute("SELECT COUNT(*) FROM food_library").fetchone()[0]
    if existing > 0:
        conn.close()
        return existing

    rows = conn.execute(
        "SELECT items, date FROM meals WHERE items IS NOT NULL ORDER BY date"
    ).fetchall()
    conn.close()

    # Accumulateur par nom d'aliment
    acc: dict[str, dict] = {}
    for items_json, meal_date in rows:
        if not items_json:
            continue
        try:
            items = json.loads(items_json)
        except json.JSONDecodeError:
            continue
        for it in items:
            name = (it.get("name") or "").strip()
            qty  = it.get("qty_g") or 0
            if not name or qty <= 0:
                continue
            scale = 100.0 / qty
            if name not in acc:
                acc[name] = {"n": 0, "qty_sum": 0.0, "last_used": meal_date,
                             **{k: 0.0 for k in _FOOD_KEYS}}
            a = acc[name]
            a["n"]       += 1
            a["qty_sum"] += qty
            a["last_used"] = meal_date
            for k in _FOOD_KEYS:
                a[k] += (it.get(k) or 0) * scale

    conn = get_db()
    for name, a in acc.items():
        n = a["n"]
        per100 = {k: round(a[k] / n, 3) for k in _FOOD_KEYS}
        conn.execute(_UPSERT_SQL, {
            "name": name, "qty_ref_g": round(a["qty_sum"] / n, 1),
            "last_used": a["last_used"], **per100,
        })
    conn.commit()
    inserted = conn.execute("SELECT COUNT(*) FROM food_library").fetchone()[0]
    conn.close()
    if inserted:
        print(f"[db] food_library : {inserted} aliments indexés depuis l'historique")
    return inserted


def get_food_from_library(name: str) -> dict | None:
    """Correspondance insensible à la casse."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM food_library WHERE lower(name) = lower(?)", (name,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_food_library() -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM food_library ORDER BY use_count DESC, name ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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
        INSERT INTO meals (date, meal_type, description, meal_name, items,
                           total_kcal, total_prot, total_carb, total_fat,
                           total_fiber, total_carb_simple, total_carb_complex,
                           total_fat_sat, total_fat_unsat,
                           total_sodium, total_calcium, total_iron,
                           total_vit_c, total_potassium,
                           created_at)
        VALUES (:date, :meal_type, :description, :meal_name, :items,
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
        "meal_name":          data.get("meal_name", ""),
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


def update_meal_items(meal_id: int, items: list[dict]) -> dict | None:
    """Remplace les items d'un repas et recalcule tous les totaux."""
    items_json = json.dumps(items, ensure_ascii=False)
    conn = get_db()
    conn.execute("""
        UPDATE meals SET
            items             = :items,
            total_kcal        = :total_kcal,
            total_prot        = :total_prot,
            total_carb        = :total_carb,
            total_fat         = :total_fat,
            total_fiber       = :total_fiber,
            total_carb_simple = :total_carb_simple,
            total_carb_complex= :total_carb_complex,
            total_fat_sat     = :total_fat_sat,
            total_fat_unsat   = :total_fat_unsat,
            total_sodium      = :total_sodium,
            total_calcium     = :total_calcium,
            total_iron        = :total_iron,
            total_vit_c       = :total_vit_c,
            total_potassium   = :total_potassium
        WHERE id = :meal_id
    """, {
        "items":             items_json,
        "meal_id":           meal_id,
        "total_kcal":        _sum(items, "kcal"),
        "total_prot":        _sum(items, "prot_g"),
        "total_carb":        _sum(items, "carb_g"),
        "total_fat":         _sum(items, "fat_g"),
        "total_fiber":       _sum(items, "fiber_g"),
        "total_carb_simple": _sum(items, "carb_simple_g"),
        "total_carb_complex":_sum(items, "carb_complex_g"),
        "total_fat_sat":     _sum(items, "fat_saturated_g"),
        "total_fat_unsat":   _sum(items, "fat_unsaturated_g"),
        "total_sodium":      _sum(items, "sodium_mg"),
        "total_calcium":     _sum(items, "calcium_mg"),
        "total_iron":        _sum(items, "iron_mg"),
        "total_vit_c":       _sum(items, "vitamin_c_mg"),
        "total_potassium":   _sum(items, "potassium_mg"),
    })
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
