"""Generate EcoMetric's synthetic sample datasets.

All values are synthetic and clearly labelled as such. Each dataset contains a few
deliberate data-quality problems (missing readings, an outlier) so the health check
and caveat engine have something real to detect.

Run from the project root:
    python scripts/generate_samples.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "samples"
MONTHS = [f"2026-{m:02d}" for m in range(1, 10)]  # January to September 2026
RNG = np.random.default_rng(20261023)

# Seasonal profile for North India: low in winter, peak in May-June, high through monsoon.
SEASON = dict(zip(MONTHS, [0.78, 0.80, 0.90, 1.05, 1.22, 1.25, 1.12, 1.10, 1.02]))


def jitter(scale: float = 0.04) -> float:
    return float(1 + RNG.normal(0, scale))


def write(name: str, df: pd.DataFrame, meta: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / f"{name}.csv", index=False)
    (OUT / f"{name}.dict.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {name}: {len(df)} rows")


def electricity() -> None:
    buildings = {
        # name: (base kWh per month, base occupancy, floor area sq ft)
        "Academic Block": (42000, 1800, 120000),
        "Engineering Block": (55000, 2200, 150000),
        "Hostel A": (38000, 600, 80000),
        "Hostel B": (46000, 750, 95000),
        "Library": (18000, 400, 45000),
        "Admin Block": (12000, 150, 30000),
    }
    rows, rid = [], 1
    for month in MONTHS:
        for b, (kwh, occ, area) in buildings.items():
            o = occ
            if b.startswith("Hostel") and month == "2026-06":
                o = int(occ * 0.35)  # summer vacation
            elif month == "2026-06":
                o = int(occ * 0.6)
            k = kwh * SEASON[month] * jitter()
            if b.startswith("Hostel") and month == "2026-06":
                k *= 0.55
            rows.append([f"E{rid:03d}", month, b, round(k), int(o * jitter(0.02)), area, "synthetic"])
            rid += 1
    df = pd.DataFrame(rows, columns=["record_id", "month", "building", "kwh", "occupancy", "floor_area_sqft", "data_source"])
    # Deliberate problems: a missing Library reading and a July meter spike in Hostel B.
    df["kwh"] = df["kwh"].astype("float64")
    df.loc[(df.building == "Library") & (df.month == "2026-06"), "kwh"] = np.nan
    df.loc[(df.building == "Hostel B") & (df.month == "2026-07"), "kwh"] = 118500
    df["kwh"] = df["kwh"].astype("Int64")
    write("campus_electricity", df, {
        "id": "campus_electricity",
        "title": "Campus electricity",
        "title_hi": "कैंपस बिजली खपत",
        "issue": "electricity",
        "source": "synthetic",
        "description": "Monthly electricity use per campus building, January to September 2026.",
        "time_column": "month",
        "entity_columns": ["building"],
        "primary_metric": "kwh",
        "columns": {
            "record_id": {"role": "id", "label": "record id"},
            "month": {"role": "time", "label": "month", "label_hi": "महीना"},
            "building": {"role": "entity", "label": "building", "label_hi": "भवन"},
            "kwh": {"role": "metric", "label": "electricity use", "label_hi": "बिजली खपत", "unit": "kWh",
                    "additive": True, "seasonal": True,
                    "keywords": ["electricity", "power", "energy", "kwh", "consumption", "बिजली", "ऊर्जा"]},
            "occupancy": {"role": "denominator", "label": "occupancy", "label_hi": "रहने वाले लोग", "unit": "people",
                          "per_label": "occupant", "per_label_hi": "व्यक्ति", "additive": True,
                          "keywords": ["occupant", "occupancy", "person", "people", "capita", "student", "व्यक्ति", "प्रति व्यक्ति"]},
            "floor_area_sqft": {"role": "denominator", "label": "floor area", "label_hi": "फ्लोर एरिया", "unit": "sq ft",
                                "per_label": "sq ft", "per_label_hi": "वर्ग फुट", "additive": True,
                                "keywords": ["area", "sq ft", "square foot", "square feet", "sqft", "वर्ग फुट"]},
            "data_source": {"role": "source", "label": "data source"},
        },
        "entity_aliases": {"Hostel A": ["हॉस्टल ए", "हॉस्टल a"], "Hostel B": ["हॉस्टल बी", "हॉस्टल b"],
                           "Library": ["लाइब्रेरी", "पुस्तकालय"], "Admin Block": ["एडमिन ब्लॉक"],
                           "Academic Block": ["एकेडमिक ब्लॉक"], "Engineering Block": ["इंजीनियरिंग ब्लॉक"]},
        "examples": {
            "en": ["Which building used the most electricity in September 2026?",
                   "How has Hostel B electricity changed since January?",
                   "Which building is most efficient per occupant?",
                   "What was the electricity cost last month?"],
            "hi": ["सितंबर 2026 में सबसे ज्यादा बिजली किस भवन ने इस्तेमाल की?",
                   "जनवरी से हॉस्टल बी की बिजली खपत कैसे बदली?",
                   "प्रति व्यक्ति सबसे कम बिजली किस भवन की है?",
                   "पिछले महीने बिजली का बिल कितना था?"],
        },
    })


def water() -> None:
    buildings = {"Academic Block": (950000, 1800), "Engineering Block": (1100000, 2200), "Hostel A": (1650000, 600),
                 "Hostel B": (1900000, 750), "Library": (210000, 400), "Admin Block": (140000, 150)}
    rows, rid = [], 1
    for month in MONTHS:
        for b, (litres, occ) in buildings.items():
            factor = 0.9 + 0.25 * (SEASON[month] - 0.78) / 0.47
            o = occ * (0.35 if b.startswith("Hostel") and month == "2026-06" else 1)
            lit = litres * factor * jitter() * (0.45 if b.startswith("Hostel") and month == "2026-06" else 1)
            rows.append([f"W{rid:03d}", month, b, round(lit), int(o * jitter(0.02)), "synthetic"])
            rid += 1
    df = pd.DataFrame(rows, columns=["record_id", "month", "building", "litres", "occupancy", "data_source"])
    df["occupancy"] = df["occupancy"].astype("float64")
    df.loc[(df.building == "Engineering Block") & (df.month == "2026-04"), "occupancy"] = np.nan
    df["occupancy"] = df["occupancy"].astype("Int64")
    write("water_usage", df, {
        "id": "water_usage", "title": "Campus water usage", "title_hi": "कैंपस पानी उपयोग", "issue": "water",
        "source": "synthetic", "description": "Monthly water use per campus building, January to September 2026.",
        "time_column": "month", "entity_columns": ["building"], "primary_metric": "litres",
        "columns": {
            "record_id": {"role": "id", "label": "record id"},
            "month": {"role": "time", "label": "month", "label_hi": "महीना"},
            "building": {"role": "entity", "label": "building", "label_hi": "भवन"},
            "litres": {"role": "metric", "label": "water use", "label_hi": "पानी उपयोग", "unit": "litres", "additive": True,
                       "seasonal": True, "keywords": ["water", "litre", "liter", "litres", "पानी", "जल"]},
            "occupancy": {"role": "denominator", "label": "occupancy", "label_hi": "रहने वाले लोग", "unit": "people",
                          "per_label": "occupant", "per_label_hi": "व्यक्ति", "additive": True,
                          "keywords": ["occupant", "occupancy", "person", "people", "capita", "व्यक्ति", "प्रति व्यक्ति"]},
            "data_source": {"role": "source", "label": "data source"},
        },
        "entity_aliases": {"Hostel A": ["हॉस्टल ए"], "Hostel B": ["हॉस्टल बी"], "Library": ["लाइब्रेरी"]},
        "examples": {"en": ["Which building used the most water in August 2026?",
                            "How has Hostel A water use changed since January?",
                            "Which building uses the least water per occupant?",
                            "What was the total water use in 2026?"],
                     "hi": ["अगस्त 2026 में सबसे ज्यादा पानी किस भवन ने इस्तेमाल किया?",
                            "प्रति व्यक्ति सबसे कम पानी किस भवन में है?"]},
    })


def waste() -> None:
    wards = {"Ward 1": (42000, 5200), "Ward 2": (51000, 6100), "Ward 3": (36000, 4300), "Ward 4": (60000, 7400),
             "Ward 5": (29000, 3600), "Ward 6": (47000, 5800)}
    seg_rate = {"Ward 1": 0.42, "Ward 2": 0.55, "Ward 3": 0.61, "Ward 4": 0.38, "Ward 5": 0.67, "Ward 6": 0.49}
    rows, rid = [], 1
    for i, month in enumerate(MONTHS):
        for w, (kg, hh) in wards.items():
            total = kg * jitter(0.05) * (1.08 if month in ("2026-03", "2026-08") else 1)
            seg = total * min(0.95, seg_rate[w] + 0.01 * i) * jitter(0.03)
            trips = int(total / 1800 * jitter(0.05))
            rows.append([f"S{rid:03d}", month, w, round(total), round(seg), hh, trips, "synthetic"])
            rid += 1
    df = pd.DataFrame(rows, columns=["record_id", "month", "ward", "total_waste_kg", "segregated_kg", "households",
                                     "collection_trips", "data_source"])
    df = df[~((df.ward == "Ward 3") & (df.month == "2026-05"))].reset_index(drop=True)  # missing report
    write("waste_collection", df, {
        "id": "waste_collection", "title": "Ward waste collection", "title_hi": "वार्ड कचरा संग्रह", "issue": "waste",
        "source": "synthetic", "description": "Monthly waste collected and segregated per ward, January to September 2026.",
        "time_column": "month", "entity_columns": ["ward"], "primary_metric": "total_waste_kg",
        "columns": {
            "record_id": {"role": "id", "label": "record id"},
            "month": {"role": "time", "label": "month", "label_hi": "महीना"},
            "ward": {"role": "entity", "label": "ward", "label_hi": "वार्ड"},
            "total_waste_kg": {"role": "metric", "label": "waste collected", "label_hi": "एकत्रित कचरा", "unit": "kg",
                               "additive": True, "per_label": "kg of waste", "per_label_hi": "किलो कचरा",
                               "keywords": ["waste", "garbage", "collected", "कचरा", "कूड़ा"]},
            "segregated_kg": {"role": "metric", "label": "segregated waste", "label_hi": "अलग किया गया कचरा", "unit": "kg",
                              "additive": True, "keywords": ["segregated", "segregation", "sorted", "अलग"]},
            "households": {"role": "denominator", "label": "households", "label_hi": "घर", "unit": "households",
                           "per_label": "household", "per_label_hi": "घर", "additive": True,
                           "keywords": ["household", "households", "home", "घर", "प्रति घर"]},
            "collection_trips": {"role": "metric", "label": "collection trips", "label_hi": "संग्रह फेरे", "unit": "trips",
                                 "additive": True, "keywords": ["trip", "trips", "vehicle", "फेरे"]},
            "data_source": {"role": "source", "label": "data source"},
        },
        "examples": {"en": ["Which ward collected the most waste in September 2026?",
                            "Which ward has the highest segregation rate?",
                            "How has Ward 4 waste changed since January?",
                            "Which ward produces the least waste per household?"],
                     "hi": ["सितंबर 2026 में सबसे ज्यादा कचरा किस वार्ड में एकत्र हुआ?",
                            "प्रति घर सबसे कम कचरा किस वार्ड में है?"]},
    })


def air() -> None:
    stations = {"Station Central": 112, "Station North": 88, "Station South": 97, "Station East": 76}
    pm_season = dict(zip(MONTHS, [1.55, 1.3, 1.0, 0.85, 0.9, 0.8, 0.55, 0.5, 0.65]))
    rows, rid = [], 1
    for month in MONTHS:
        for s, base in stations.items():
            pm25 = base * pm_season[month] * jitter(0.06)
            rows.append([f"A{rid:03d}", month, s, round(pm25, 1), round(pm25 * 1.75 * jitter(0.05), 1),
                         round(32 * jitter(0.1), 1), "synthetic"])
            rid += 1
    df = pd.DataFrame(rows, columns=["record_id", "month", "station", "pm25", "pm10", "no2", "data_source"])
    df["pm25"] = df["pm25"].astype("float64")
    df.loc[(df.station == "Station East") & (df.month == "2026-08"), "pm25"] = np.nan
    df.loc[(df.station == "Station Central") & (df.month == "2026-08"), "pm25"] = 312.0  # sensor spike
    write("air_quality", df, {
        "id": "air_quality", "title": "City air quality", "title_hi": "शहर वायु गुणवत्ता", "issue": "air",
        "source": "synthetic", "description": "Monthly average pollutant concentrations per monitoring station, January to September 2026.",
        "time_column": "month", "entity_columns": ["station"], "primary_metric": "pm25",
        "columns": {
            "record_id": {"role": "id", "label": "record id"},
            "month": {"role": "time", "label": "month", "label_hi": "महीना"},
            "station": {"role": "entity", "label": "station", "label_hi": "स्टेशन"},
            "pm25": {"role": "metric", "label": "PM2.5", "label_hi": "PM2.5", "unit": "µg/m³", "additive": False,
                     "seasonal": True, "keywords": ["pm2.5", "pm 2.5", "pm25", "air", "pollution", "aqi", "प्रदूषण", "हवा"]},
            "pm10": {"role": "metric", "label": "PM10", "label_hi": "PM10", "unit": "µg/m³", "additive": False,
                     "seasonal": True, "keywords": ["pm10", "pm 10", "dust", "धूल"]},
            "no2": {"role": "metric", "label": "NO2", "label_hi": "NO2", "unit": "µg/m³", "additive": False,
                    "keywords": ["no2", "nitrogen"]},
            "data_source": {"role": "source", "label": "data source"},
        },
        "entity_aliases": {"Station Central": ["सेंट्रल"], "Station North": ["नॉर्थ"], "Station South": ["साउथ"], "Station East": ["ईस्ट"]},
        "examples": {"en": ["Which station had the worst PM2.5 in January 2026?",
                            "How has PM2.5 at Station North changed since January?",
                            "What was the average PM10 across all stations in 2026?",
                            "Compare Station Central and Station East PM2.5 in September 2026"],
                     "hi": ["जनवरी 2026 में सबसे ज्यादा PM2.5 किस स्टेशन पर था?",
                            "जनवरी से स्टेशन नॉर्थ पर PM2.5 कैसे बदला?"]},
    })


def mobility() -> None:
    routes = {"Route 1 Campus to City": (21000, 620), "Route 2 Campus to Railway Station": (16500, 480),
              "Route 3 Hostel Shuttle": (24000, 900), "Route 4 Campus to Bus Stand": (12800, 450)}
    rows, rid = [], 1
    for month in MONTHS:
        for r, (riders, trips) in routes.items():
            vac = 0.3 if month == "2026-06" else (0.7 if month == "2026-05" else 1)
            rows.append([f"M{rid:03d}", month, r, round(riders * vac * jitter(0.05)), round(trips * max(vac, 0.5) * jitter(0.03)),
                         "synthetic"])
            rid += 1
    df = pd.DataFrame(rows, columns=["record_id", "month", "route", "riders", "trips", "data_source"])
    write("campus_mobility", df, {
        "id": "campus_mobility", "title": "Campus bus ridership", "title_hi": "कैंपस बस यात्री", "issue": "mobility",
        "source": "synthetic", "description": "Monthly riders and trips per campus bus route, January to September 2026.",
        "time_column": "month", "entity_columns": ["route"], "primary_metric": "riders",
        "columns": {
            "record_id": {"role": "id", "label": "record id"},
            "month": {"role": "time", "label": "month", "label_hi": "महीना"},
            "route": {"role": "entity", "label": "route", "label_hi": "रूट"},
            "riders": {"role": "metric", "label": "riders", "label_hi": "यात्री", "unit": "riders", "additive": True,
                       "seasonal": True, "keywords": ["rider", "riders", "ridership", "passenger", "passengers", "यात्री"]},
            "trips": {"role": "denominator", "label": "bus trips", "label_hi": "बस फेरे", "unit": "trips",
                      "per_label": "trip", "per_label_hi": "फेरा", "additive": True,
                      "keywords": ["trip", "trips", "per trip", "फेरा", "फेरे"]},
            "data_source": {"role": "source", "label": "data source"},
        },
        "examples": {"en": ["Which route had the most riders in September 2026?",
                            "Which route carries the most riders per trip?",
                            "How has Route 3 Hostel Shuttle ridership changed since January?",
                            "What was the total ridership in 2026?"],
                     "hi": ["सितंबर 2026 में सबसे ज्यादा यात्री किस रूट पर थे?"]},
    })


def resources() -> None:
    facilities = {"Main Auditorium": (34, 120, 300), "Seminar Hall": (58, 190, 300), "Computer Lab 1": (80, 245, 320),
                  "Computer Lab 2": (61, 170, 320), "Sports Complex": (95, 260, 360)}
    rows, rid = [], 1
    for month in MONTHS:
        for f, (bookings, used, avail) in facilities.items():
            vac = 0.35 if month == "2026-06" else 1
            u = min(avail, used * vac * jitter(0.06))
            rows.append([f"R{rid:03d}", month, f, round(bookings * vac * jitter(0.06)), round(u), avail, "synthetic"])
            rid += 1
    df = pd.DataFrame(rows, columns=["record_id", "month", "facility", "bookings", "hours_used", "hours_available", "data_source"])
    write("campus_resources", df, {
        "id": "campus_resources", "title": "Campus facility use", "title_hi": "कैंपस सुविधा उपयोग", "issue": "resources",
        "source": "synthetic", "description": "Monthly bookings and hours used per campus facility, January to September 2026.",
        "time_column": "month", "entity_columns": ["facility"], "primary_metric": "hours_used",
        "columns": {
            "record_id": {"role": "id", "label": "record id"},
            "month": {"role": "time", "label": "month", "label_hi": "महीना"},
            "facility": {"role": "entity", "label": "facility", "label_hi": "सुविधा"},
            "bookings": {"role": "metric", "label": "bookings", "label_hi": "बुकिंग", "unit": "bookings", "additive": True,
                         "keywords": ["booking", "bookings", "बुकिंग"]},
            "hours_used": {"role": "metric", "label": "hours used", "label_hi": "उपयोग के घंटे", "unit": "hours",
                           "additive": True, "keywords": ["hours used", "usage", "used", "utilisation", "utilization", "उपयोग"]},
            "hours_available": {"role": "denominator", "label": "hours available", "label_hi": "उपलब्ध घंटे", "unit": "hours",
                                "per_label": "available hour", "per_label_hi": "उपलब्ध घंटा", "additive": True,
                                "keywords": ["available", "capacity", "utilisation", "utilization", "उपलब्ध", "क्षमता"]},
            "data_source": {"role": "source", "label": "data source"},
        },
        "examples": {"en": ["Which facility had the most bookings in September 2026?",
                            "Which facility has the highest utilisation?",
                            "How have Computer Lab 1 hours used changed since January?",
                            "Compare Seminar Hall and Main Auditorium bookings in 2026"],
                     "hi": ["सितंबर 2026 में सबसे ज्यादा बुकिंग किस सुविधा की हुई?"]},
    })


if __name__ == "__main__":
    electricity()
    water()
    waste()
    air()
    mobility()
    resources()
