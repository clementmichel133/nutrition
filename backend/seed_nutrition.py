#!/usr/bin/env python3
"""
Seed script — historique nutritionnel Clément
02/02/2026 → 02/06/2026 (~120 jours)

Usage : python backend/seed_nutrition.py
"""

import sys
import sqlite3
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent))
import database as db

# ─── Constantes ───────────────────────────────────────────────────────────────

START = date(2026, 2, 2)
END   = date(2026, 6, 2)

# Jours sans saisie (vacances, oublis)
SKIP = {
    date(2026, 2, 14), date(2026, 2, 15), date(2026, 2, 16),  # week-end St-Valentin
    date(2026, 3, 21),                                          # oubli
    date(2026, 4, 4),  date(2026, 4, 5),  date(2026, 4, 6),   # Pâques
    date(2026, 5, 1),                                           # Fête du Travail
    date(2026, 5, 29),                                          # Ascension
}

# ─── Base nutritionnelle (valeurs pour 100 g / 100 ml) ───────────────────────

FOODS: dict[str, dict] = {
    "riz_blanc_cuit": {
        "name": "Riz blanc cuit",
        "kcal": 130, "prot_g": 2.7, "carb_g": 28.2, "fat_g": 0.3,
        "carb_simple_g": 0.1, "carb_complex_g": 28.1,
        "fat_saturated_g": 0.1, "fat_unsaturated_g": 0.2,
        "fiber_g": 0.4, "sodium_mg": 1,   "calcium_mg": 10,  "iron_mg": 0.20,
        "vitamin_c_mg": 0,   "potassium_mg": 35,
    },
    "poulet_grille": {
        "name": "Poulet grillé",
        "kcal": 165, "prot_g": 31.0, "carb_g": 0.0, "fat_g": 3.6,
        "carb_simple_g": 0.0, "carb_complex_g": 0.0,
        "fat_saturated_g": 1.0, "fat_unsaturated_g": 2.6,
        "fiber_g": 0.0, "sodium_mg": 74,  "calcium_mg": 15,  "iron_mg": 1.00,
        "vitamin_c_mg": 0,   "potassium_mg": 256,
    },
    "saumon": {
        "name": "Saumon",
        "kcal": 208, "prot_g": 20.0, "carb_g": 0.0, "fat_g": 13.0,
        "carb_simple_g": 0.0, "carb_complex_g": 0.0,
        "fat_saturated_g": 2.5, "fat_unsaturated_g": 10.5,
        "fiber_g": 0.0, "sodium_mg": 59,  "calcium_mg": 13,  "iron_mg": 0.30,
        "vitamin_c_mg": 3,   "potassium_mg": 363,
    },
    "oeuf_entier": {
        "name": "Œuf entier",
        "kcal": 155, "prot_g": 13.0, "carb_g": 1.1, "fat_g": 11.0,
        "carb_simple_g": 1.1, "carb_complex_g": 0.0,
        "fat_saturated_g": 3.3, "fat_unsaturated_g": 7.7,
        "fiber_g": 0.0, "sodium_mg": 124, "calcium_mg": 56,  "iron_mg": 1.80,
        "vitamin_c_mg": 0,   "potassium_mg": 138,
    },
    "patate_douce": {
        "name": "Patate douce cuite",
        "kcal": 86,  "prot_g": 1.6,  "carb_g": 20.0, "fat_g": 0.1,
        "carb_simple_g": 4.2, "carb_complex_g": 15.8,
        "fat_saturated_g": 0.0, "fat_unsaturated_g": 0.1,
        "fiber_g": 3.0, "sodium_mg": 36,  "calcium_mg": 30,  "iron_mg": 0.70,
        "vitamin_c_mg": 13,  "potassium_mg": 337,
    },
    "brocolis": {
        "name": "Brocolis",
        "kcal": 34,  "prot_g": 2.8,  "carb_g": 6.6,  "fat_g": 0.4,
        "carb_simple_g": 1.7, "carb_complex_g": 4.9,
        "fat_saturated_g": 0.1, "fat_unsaturated_g": 0.3,
        "fiber_g": 2.6, "sodium_mg": 33,  "calcium_mg": 47,  "iron_mg": 0.70,
        "vitamin_c_mg": 89,  "potassium_mg": 316,
    },
    "epinards": {
        "name": "Épinards sautés",
        "kcal": 23,  "prot_g": 2.9,  "carb_g": 3.6,  "fat_g": 0.4,
        "carb_simple_g": 0.4, "carb_complex_g": 3.2,
        "fat_saturated_g": 0.1, "fat_unsaturated_g": 0.3,
        "fiber_g": 2.2, "sodium_mg": 79,  "calcium_mg": 99,  "iron_mg": 2.70,
        "vitamin_c_mg": 28,  "potassium_mg": 558,
    },
    "avocat": {
        "name": "Avocat",
        "kcal": 160, "prot_g": 2.0,  "carb_g": 9.0,  "fat_g": 15.0,
        "carb_simple_g": 0.7, "carb_complex_g": 8.3,
        "fat_saturated_g": 2.1, "fat_unsaturated_g": 12.9,
        "fiber_g": 6.7, "sodium_mg": 7,   "calcium_mg": 12,  "iron_mg": 0.60,
        "vitamin_c_mg": 10,  "potassium_mg": 485,
    },
    "fromage_blanc": {
        "name": "Fromage blanc 0%",
        "kcal": 45,  "prot_g": 8.0,  "carb_g": 4.6,  "fat_g": 0.2,
        "carb_simple_g": 4.6, "carb_complex_g": 0.0,
        "fat_saturated_g": 0.1, "fat_unsaturated_g": 0.1,
        "fiber_g": 0.0, "sodium_mg": 40,  "calcium_mg": 120, "iron_mg": 0.10,
        "vitamin_c_mg": 0,   "potassium_mg": 155,
    },
    "banane": {
        "name": "Banane",
        "kcal": 89,  "prot_g": 1.1,  "carb_g": 23.0, "fat_g": 0.3,
        "carb_simple_g": 12.0,"carb_complex_g": 11.0,
        "fat_saturated_g": 0.1, "fat_unsaturated_g": 0.2,
        "fiber_g": 2.6, "sodium_mg": 1,   "calcium_mg": 5,   "iron_mg": 0.30,
        "vitamin_c_mg": 9,   "potassium_mg": 358,
    },
    "pomme": {
        "name": "Pomme",
        "kcal": 52,  "prot_g": 0.3,  "carb_g": 14.0, "fat_g": 0.2,
        "carb_simple_g": 10.0,"carb_complex_g": 4.0,
        "fat_saturated_g": 0.0, "fat_unsaturated_g": 0.2,
        "fiber_g": 2.4, "sodium_mg": 1,   "calcium_mg": 6,   "iron_mg": 0.10,
        "vitamin_c_mg": 6,   "potassium_mg": 107,
    },
    "amandes": {
        "name": "Amandes",
        "kcal": 579, "prot_g": 21.0, "carb_g": 22.0, "fat_g": 49.0,
        "carb_simple_g": 4.4, "carb_complex_g": 17.6,
        "fat_saturated_g": 3.7, "fat_unsaturated_g": 45.3,
        "fiber_g": 12.5,"sodium_mg": 1,   "calcium_mg": 264, "iron_mg": 3.70,
        "vitamin_c_mg": 0,   "potassium_mg": 705,
    },
    "pain_complet": {
        "name": "Pain complet",
        "kcal": 247, "prot_g": 9.0,  "carb_g": 41.0, "fat_g": 3.4,
        "carb_simple_g": 4.2, "carb_complex_g": 36.8,
        "fat_saturated_g": 0.7, "fat_unsaturated_g": 2.7,
        "fiber_g": 7.0, "sodium_mg": 450, "calcium_mg": 35,  "iron_mg": 2.70,
        "vitamin_c_mg": 0,   "potassium_mg": 248,
    },
    "houmous": {
        "name": "Houmous",
        "kcal": 166, "prot_g": 7.9,  "carb_g": 14.0, "fat_g": 9.6,
        "carb_simple_g": 1.5, "carb_complex_g": 12.5,
        "fat_saturated_g": 1.4, "fat_unsaturated_g": 8.2,
        "fiber_g": 6.0, "sodium_mg": 379, "calcium_mg": 49,  "iron_mg": 2.40,
        "vitamin_c_mg": 0,   "potassium_mg": 228,
    },
    "thon": {
        "name": "Thon en boîte (naturel)",
        "kcal": 116, "prot_g": 26.0, "carb_g": 0.0,  "fat_g": 1.0,
        "carb_simple_g": 0.0, "carb_complex_g": 0.0,
        "fat_saturated_g": 0.3, "fat_unsaturated_g": 0.7,
        "fiber_g": 0.0, "sodium_mg": 333, "calcium_mg": 12,  "iron_mg": 1.30,
        "vitamin_c_mg": 0,   "potassium_mg": 384,
    },
    "lentilles": {
        "name": "Lentilles cuites",
        "kcal": 116, "prot_g": 9.0,  "carb_g": 20.0, "fat_g": 0.4,
        "carb_simple_g": 1.8, "carb_complex_g": 18.2,
        "fat_saturated_g": 0.1, "fat_unsaturated_g": 0.3,
        "fiber_g": 7.9, "sodium_mg": 2,   "calcium_mg": 19,  "iron_mg": 3.30,
        "vitamin_c_mg": 2,   "potassium_mg": 369,
    },
    "avoine": {
        "name": "Flocons d'avoine",
        "kcal": 389, "prot_g": 17.0, "carb_g": 66.0, "fat_g": 7.0,
        "carb_simple_g": 1.1, "carb_complex_g": 64.9,
        "fat_saturated_g": 1.2, "fat_unsaturated_g": 5.8,
        "fiber_g": 10.6,"sodium_mg": 2,   "calcium_mg": 52,  "iron_mg": 4.70,
        "vitamin_c_mg": 0,   "potassium_mg": 361,
    },
    "yaourt_grec": {
        "name": "Yaourt grec 0%",
        "kcal": 59,  "prot_g": 10.0, "carb_g": 3.6,  "fat_g": 0.4,
        "carb_simple_g": 3.6, "carb_complex_g": 0.0,
        "fat_saturated_g": 0.2, "fat_unsaturated_g": 0.2,
        "fiber_g": 0.0, "sodium_mg": 46,  "calcium_mg": 110, "iron_mg": 0.10,
        "vitamin_c_mg": 0,   "potassium_mg": 141,
    },
    # Bière : valeurs pour 100 ml
    "biere": {
        "name": "Bière blonde",
        "kcal": 45,  "prot_g": 0.5,  "carb_g": 4.2,  "fat_g": 0.0,
        "carb_simple_g": 0.0, "carb_complex_g": 4.2,
        "fat_saturated_g": 0.0, "fat_unsaturated_g": 0.0,
        "fiber_g": 0.0, "sodium_mg": 5,   "calcium_mg": 7,   "iron_mg": 0.00,
        "vitamin_c_mg": 0,   "potassium_mg": 30,
    },
    "pizza": {
        "name": "Pizza margherita",
        "kcal": 266, "prot_g": 11.0, "carb_g": 33.0, "fat_g": 10.0,
        "carb_simple_g": 3.6, "carb_complex_g": 29.4,
        "fat_saturated_g": 4.1, "fat_unsaturated_g": 5.9,
        "fiber_g": 2.3, "sodium_mg": 620, "calcium_mg": 188, "iron_mg": 1.70,
        "vitamin_c_mg": 7,   "potassium_mg": 240,
    },
    "kebab": {
        "name": "Kebab (pain + viande + légumes)",
        "kcal": 240, "prot_g": 16.0, "carb_g": 28.0, "fat_g": 7.0,
        "carb_simple_g": 3.0, "carb_complex_g": 25.0,
        "fat_saturated_g": 2.5, "fat_unsaturated_g": 4.5,
        "fiber_g": 2.0, "sodium_mg": 580, "calcium_mg": 50,  "iron_mg": 2.10,
        "vitamin_c_mg": 8,   "potassium_mg": 280,
    },
    "huile_olive": {
        "name": "Huile d'olive",
        "kcal": 884, "prot_g": 0.0,  "carb_g": 0.0,  "fat_g": 100.0,
        "carb_simple_g": 0.0, "carb_complex_g": 0.0,
        "fat_saturated_g": 13.8,"fat_unsaturated_g": 86.2,
        "fiber_g": 0.0, "sodium_mg": 2,   "calcium_mg": 1,   "iron_mg": 0.60,
        "vitamin_c_mg": 0,   "potassium_mg": 1,
    },
    "salade": {
        "name": "Salade verte mélangée",
        "kcal": 20,  "prot_g": 1.5,  "carb_g": 3.0,  "fat_g": 0.2,
        "carb_simple_g": 1.5, "carb_complex_g": 1.5,
        "fat_saturated_g": 0.0, "fat_unsaturated_g": 0.2,
        "fiber_g": 1.5, "sodium_mg": 10,  "calcium_mg": 30,  "iron_mg": 0.50,
        "vitamin_c_mg": 15,  "potassium_mg": 150,
    },
    "ratatouille": {
        "name": "Ratatouille maison",
        "kcal": 62,  "prot_g": 2.0,  "carb_g": 12.0, "fat_g": 1.2,
        "carb_simple_g": 7.0, "carb_complex_g": 5.0,
        "fat_saturated_g": 0.2, "fat_unsaturated_g": 1.0,
        "fiber_g": 3.5, "sodium_mg": 120, "calcium_mg": 35,  "iron_mg": 0.80,
        "vitamin_c_mg": 20,  "potassium_mg": 350,
    },
}

MACRO_KEYS = [
    "kcal", "prot_g", "carb_g", "carb_simple_g", "carb_complex_g",
    "fat_g", "fat_saturated_g", "fat_unsaturated_g",
    "fiber_g", "sodium_mg", "calcium_mg", "iron_mg",
    "vitamin_c_mg", "potassium_mg",
]

# ─── Helpers ──────────────────────────────────────────────────────────────────

def item(food_key: str, qty_g: float) -> dict:
    """Retourne un item nutritionnel pour qty_g grammes (ou ml) de food_key."""
    f = FOODS[food_key]
    s = qty_g / 100
    return {"name": f["name"], "qty_g": round(qty_g, 1),
            **{k: round(f[k] * s, 2) for k in MACRO_KEYS}}


def beers(n: int) -> dict:
    """n canettes de bière 33cl groupées en un item."""
    ml = 330 * n
    it = item("biere", ml)
    it["name"] = f"Bière blonde ({n}×33cl)"
    return it


# Aliments protéinés dont la quantité suit la progression mensuelle
PROTEIN_FOODS = {"poulet_grille", "saumon", "thon", "oeuf_entier"}


def make_meal(recipe: list[tuple], prot_scale: float = 1.0) -> list[dict]:
    """
    recipe : [(food_key, qty_g), ...]
    prot_scale : multiplicateur appliqué aux aliments protéinés uniquement.
    """
    result = []
    for food_key, qty_g in recipe:
        if food_key in PROTEIN_FOODS:
            qty_g = round(qty_g * prot_scale)
        result.append(item(food_key, qty_g))
    return result


# ─── Recettes ─────────────────────────────────────────────────────────────────

PETIT_DEJ_OPTS = [
    # A — Yaourt + Avoine + Banane
    [("yaourt_grec", 200), ("avoine", 60), ("banane", 100)],
    # B — Œufs + Pain + Avocat
    [("oeuf_entier", 150), ("pain_complet", 60), ("avocat", 50)],
    # C — Fromage blanc + Avoine + Pomme
    [("fromage_blanc", 200), ("avoine", 50), ("pomme", 130)],
]

DEJEUNER_OPTS = [
    # A — Riz + Poulet + Brocolis
    [("riz_blanc_cuit", 200), ("poulet_grille", 150), ("brocolis", 100), ("huile_olive", 10)],
    # B — Riz + Thon + Salade + Houmous
    [("riz_blanc_cuit", 180), ("thon", 120), ("salade", 100), ("houmous", 40)],
    # C — Lentilles + Poulet + Épinards
    [("lentilles", 200), ("poulet_grille", 120), ("epinards", 100)],
    # D — Patate douce + Saumon + Brocolis
    [("patate_douce", 200), ("saumon", 130), ("brocolis", 100)],
]

GOUTER_OPTS = [
    [("pomme", 150), ("amandes", 25)],
    [("banane", 130), ("amandes", 20)],
    [("fromage_blanc", 150), ("banane", 80)],
]

DINER_OPTS = [
    # A — Saumon + Épinards + Riz
    [("saumon", 130), ("epinards", 150), ("riz_blanc_cuit", 100)],
    # B — Poulet + Ratatouille
    [("poulet_grille", 140), ("ratatouille", 200)],
    # C — Œufs + Épinards + Pain
    [("oeuf_entier", 150), ("epinards", 150), ("pain_complet", 40)],
    # D — Thon + Salade + Pain + Houmous
    [("thon", 120), ("salade", 150), ("pain_complet", 40), ("houmous", 30)],
]

# ─── Logique temporelle ───────────────────────────────────────────────────────

def prot_scale(d: date) -> float:
    """Légère progression des apports protéinés sur 4 mois."""
    if d.month == 2: return 1.00
    if d.month == 3: return 1.04
    if d.month == 4: return 1.08
    return 1.12   # mai-juin


def beer_evening(d: date) -> int | None:
    """
    Retourne le weekday (lun=0) de la soirée bières cette semaine,
    alternance mercr (2) / vendr (4).
    Renvoie None → pas de soirée bières cette semaine.
    """
    week = d.isocalendar()[1]
    return 2 if week % 2 == 0 else 4


# ─── Insertion ────────────────────────────────────────────────────────────────

def insert_record(date_str: str, meal_type: str, items: list[dict]) -> None:
    db.insert_meal({
        "date":       date_str,
        "meal_type":  meal_type,
        "description": "",
        "items":      items,
        "total_kcal": round(sum(i["kcal"]   for i in items), 1),
        "total_prot": round(sum(i["prot_g"] for i in items), 1),
        "total_carb": round(sum(i["carb_g"] for i in items), 1),
        "total_fat":  round(sum(i["fat_g"]  for i in items), 1),
    })


# ─── Seed principal ───────────────────────────────────────────────────────────

def seed_profile() -> None:
    db.upsert_profile({
        "name": "Clément", "gender": "homme",
        "age": 28, "weight_kg": 78, "height_cm": 183, "goal": "recompo",
    })
    p = db.get_profile()
    print(f"[OK] Profil : {p['name']} -- "
          f"{p['target_kcal']} kcal | {p['target_prot']}g P | "
          f"{p['target_carb']}g G | {p['target_fat']}g L")


def clear_range() -> None:
    conn = sqlite3.connect(db.DB_PATH)
    deleted = conn.execute(
        "DELETE FROM meals WHERE date BETWEEN ? AND ?",
        (START.isoformat(), END.isoformat()),
    ).rowcount
    conn.commit()
    conn.close()
    if deleted:
        print(f"[DEL] {deleted} repas existants effaces sur la periode")


def seed_meals() -> None:
    inserted_days = 0
    idx = 0   # compteur de jours non sautés, pour cycler les recettes

    current = START
    while current <= END:
        if current in SKIP:
            current += timedelta(days=1)
            continue

        d_str = current.isoformat()
        wd    = current.weekday()   # 0=lun … 6=dim
        week  = current.isocalendar()[1]
        ps    = prot_scale(current)
        beer_wd = beer_evening(current)

        # ── Lundi – Vendredi ──────────────────────────────────────────────────
        if wd <= 4:
            insert_record(d_str, "petit_dej",
                          make_meal(PETIT_DEJ_OPTS[idx % 3], ps))

            insert_record(d_str, "dejeuner",
                          make_meal(DEJEUNER_OPTS[idx % 4], ps))

            insert_record(d_str, "gouter",
                          make_meal(GOUTER_OPTS[idx % 3]))

            # Dîner ± bières
            diner_items = make_meal(DINER_OPTS[idx % 4], ps)
            if wd == beer_wd:
                n = 3 if idx % 3 == 0 else 2
                diner_items.append(beers(n))
            insert_record(d_str, "diner", diner_items)

        # ── Samedi ────────────────────────────────────────────────────────────
        elif wd == 5:
            # Petit déjeuner (option suivante pour varier)
            insert_record(d_str, "petit_dej",
                          make_meal(PETIT_DEJ_OPTS[(idx + 1) % 3], ps))

            # Déjeuner
            insert_record(d_str, "dejeuner",
                          make_meal(DEJEUNER_OPTS[(idx + 2) % 4], ps))

            # Pas de goûter — soirée chargée

            # Dîner cheat : pizza ou kebab + 3-4 bières
            n_beers = 4 if week % 3 == 0 else 3
            if week % 2 == 0:
                evening = [item("pizza", 350), beers(n_beers)]
            else:
                evening = [item("kebab", 400), beers(n_beers)]
            insert_record(d_str, "diner", evening)

        # ── Dimanche ──────────────────────────────────────────────────────────
        else:
            # Brunch tardif (~11h) — pas de goûter
            brunch = [item("oeuf_entier", 150),
                      item("pain_complet", 80),
                      item("avocat", 70)]
            insert_record(d_str, "petit_dej", brunch)

            # Dîner léger
            diner_items = make_meal(DINER_OPTS[(idx + 1) % 4], ps * 0.85)
            insert_record(d_str, "diner", diner_items)

        inserted_days += 1
        idx += 1
        current += timedelta(days=1)

    print(f"[OK] {inserted_days} jours inseres "
          f"({(END - START).days + 1 - len(SKIP)} attendus)")


# ─── Résumé stats ─────────────────────────────────────────────────────────────

def print_stats() -> None:
    conn = sqlite3.connect(db.DB_PATH)
    rows = conn.execute("""
        SELECT
            COUNT(DISTINCT date)        AS jours,
            ROUND(AVG(daily_kcal))      AS moy_kcal,
            ROUND(MIN(daily_kcal))      AS min_kcal,
            ROUND(MAX(daily_kcal))      AS max_kcal,
            ROUND(AVG(daily_prot))      AS moy_prot
        FROM (
            SELECT date,
                   SUM(total_kcal) AS daily_kcal,
                   SUM(total_prot) AS daily_prot
            FROM meals
            WHERE date BETWEEN ? AND ?
            GROUP BY date
        )
    """, (START.isoformat(), END.isoformat())).fetchone()
    conn.close()
    jours, moy_kcal, min_kcal, max_kcal, moy_prot = rows
    print(f"\n[STATS] {jours} jours")
    print(f"  Calories  : moy {moy_kcal} kcal | min {min_kcal} | max {max_kcal}")
    print(f"  Proteines : moy {moy_prot} g / jour")


# ─── Entrée ───────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n=== Seed nutritionnel {START} -> {END} ===\n")
    seed_profile()
    clear_range()
    seed_meals()
    print_stats()
    print("\n=== Base de donnees prete ! ===\n")


if __name__ == "__main__":
    main()
