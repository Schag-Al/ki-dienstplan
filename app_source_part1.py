from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from ortools.sat.python import cp_model


st.set_page_config(page_title="KI-Dienstplan MVP", layout="wide")


SHIFT_COLORS = [
    "#d8f3dc",
    "#fff3b0",
    "#cddafd",
    "#ffd6a5",
    "#e9d5ff",
    "#bae6fd",
    "#fecdd3",
    "#ccfbf1",
]
FREE_SHIFT_COLOR = "#f1f3f5"
DAY_TYPE_ORDER = ["Werktag", "Samstag", "Sonntag/Feiertag"]
MONTH_NAMES = {
    1: "Januar",
    2: "Februar",
    3: "Maerz",
    4: "April",
    5: "Mai",
    6: "Juni",
    7: "Juli",
    8: "August",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Dezember",
}
WEEKDAY_NAMES = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
PRIORITY_LEVELS = {
    "1 - muss immer zutreffen": 1,
    "2 - nur im Ausnahmefall verletzen": 2,
    "3 - wenn moeglich beachten": 3,
    "4 - geringe Prioritaet": 4,
    "5 - fair verteilen": 5,
}
PRIORITY_WEIGHTS = {1: 1000, 2: 60, 3: 25, 4: 10, 5: 4}
DEFAULT_PRIORITY_LABEL = "3 - wenn moeglich beachten"
SHIFT_PRIORITY_LEVELS = {
    "1 - muss immer besetzt werden": 1,
    "2 - sollte besetzt sein": 2,
    "3 - nur wenn genug Mitarbeiter vorhanden": 3,
}
DEFAULT_SHIFT_PRIORITY_LABEL = "1 - muss immer besetzt werden"


@dataclass(frozen=True)
class Employee:
    name: str
    qualification: str
    weekly_hours_target: int
    max_shifts_per_week: int
    max_nights_per_month: int
    likes_nights: bool
    double_nights_only: bool
    rest_after_night: int
    prefers_weekends_off: bool
    night_priority: int
    double_night_priority: int
    rest_priority: int
    weekend_priority: int
    wish_free_priority: int
    blocked_days: tuple[int, ...] = ()


SAMPLE_EMPLOYEES = [
    Employee("Martina Hofer", "Leitung / Buero - nicht dienstplanrelevant", 1, 1, 0, False, False, 1, True, 1, 5, 5, 1, 1, tuple(range(31))),
    Employee("Sabine Gruber", "Krankenstand ganzer Monat", 1, 1, 0, False, False, 1, True, 1, 5, 5, 1, 1, tuple(range(31))),
    Employee("Julia Berger", "Pflege - keine Nacht", 32, 4, 0, False, False, 2, True, 1, 4, 2, 2, 1, (4, 5)),
    Employee("Lukas Steiner", "Pflege - keine Nacht", 40, 5, 0, False, False, 2, False, 1, 4, 2, 4, 2, (12,)),
    Employee("Nadine Leitner", "Pflege - keine Nacht", 30, 4, 0, False, False, 2, True, 1, 4, 2, 2, 1, (8, 9)),
    Employee("Paul Wagner", "Springer - keine Nacht", 36, 4, 0, False, False, 1, False, 1, 4, 3, 4, 2, (17,)),
    Employee("Eva Schmid", "Pflege - keine Nacht", 24, 3, 0, False, False, 2, True, 1, 4, 2, 2, 1, (22, 23)),
    Employee("Thomas Bauer", "Teamleitung - keine Nacht", 40, 5, 0, False, False, 1, False, 1, 4, 3, 5, 2, (2,)),
    Employee("Miriam Weiss", "Wechseldienst ohne Nacht/Wochenende", 15, 3, 0, False, False, 1, True, 1, 5, 3, 1, 1, (6,)),
    Employee("Georg Moser", "Wechseldienst ohne Nacht/Wochenende", 15, 3, 0, False, False, 1, True, 1, 5, 3, 1, 1, (14,)),
    Employee("Karin Fuchs", "Wechseldienst ohne Nacht/Wochenende", 15, 3, 0, False, False, 1, True, 1, 5, 3, 1, 1, (20,)),
    Employee("Daniel Novak", "Nur Nachtdienst", 36, 4, 16, True, True, 2, False, 1, 1, 2, 5, 2, (11,)),
    Employee("Anna Huber", "Pflege", 40, 5, 5, False, False, 2, True, 2, 3, 2, 2, 1, (3, 4)),
    Employee("Ben Fischer", "Pflege", 40, 5, 8, True, True, 1, False, 3, 2, 3, 5, 2, (18,)),
    Employee("Clara Winkler", "Pflege", 32, 4, 4, False, False, 2, True, 2, 3, 2, 2, 1, (9, 10)),
    Employee("David Eder", "Springer", 40, 5, 8, True, False, 1, False, 4, 4, 4, 5, 2, (24,)),
    Employee("Elif Yilmaz", "Pflege", 36, 4, 4, False, False, 2, True, 2, 3, 2, 2, 1, (15,)),
    Employee("Felix Brandner", "Pflege", 40, 5, 7, True, True, 1, False, 3, 2, 4, 5, 2, (7,)),
    Employee("Greta Pichler", "Teamleitung", 32, 4, 3, False, False, 2, True, 2, 3, 2, 2, 1, (21, 22)),
    Employee("Hannah Lang", "Springer", 24, 3, 5, True, False, 1, False, 4, 4, 4, 5, 2, (13,)),
    Employee("Ivan Horvat", "Pflege", 40, 5, 6, True, False, 1, False, 3, 3, 3, 4, 2, (26,)),
    Employee("Laura Klein", "Pflege", 30, 4, 3, False, False, 2, True, 2, 4, 2, 2, 1, (16, 17)),
    Employee("Marco Seidl", "Pflege", 36, 4, 6, True, True, 2, False, 3, 2, 2, 5, 2, (5,)),
    Employee("Nora Reiter", "Pflege", 24, 3, 2, False, False, 2, True, 2, 4, 2, 2, 1, (19,)),
    Employee("Omar Haddad", "Springer", 40, 5, 8, True, False, 1, False, 4, 4, 4, 5, 2, (27,)),
    Employee("Petra Auer", "Teamleitung", 32, 4, 4, False, False, 2, True, 2, 3, 2, 2, 1, (1, 2)),
    Employee("Rafael Kern", "Pflege", 40, 5, 7, True, True, 1, False, 3, 2, 3, 5, 2, (29,)),
    Employee("Selina Mayer", "Pflege", 28, 4, 3, False, False, 2, True, 2, 4, 2, 2, 1, (10,)),
    Employee("Tobias Leitgeb", "Pflege", 36, 4, 6, True, False, 1, False, 3, 4, 3, 4, 2, (23,)),
    Employee("Ulrike Haas", "Pflege", 24, 3, 2, False, False, 2, True, 2, 4, 2, 2, 1, (28,)),
    Employee("Viktor Gruber", "Springer", 40, 5, 8, True, False, 1, False, 4, 4, 4, 5, 2, (6,)),
    Employee("Yasmin Cakir", "Pflege", 32, 4, 5, True, True, 2, True, 3, 2, 2, 3, 1, (12, 13)),
    Employee("Zoe Renner", "Pflege", 30, 4, 4, False, False, 2, True, 2, 3, 2, 2, 1, (25,)),
    Employee("Simon Koller", "Pflege", 40, 5, 6, True, False, 1, False, 3, 3, 3, 4, 2, (8,)),
    Employee("Theresa Baumgartner", "Pflege", 36, 4, 5, False, False, 2, False, 2, 3, 2, 4, 1, (30,)),
    Employee("Michael Schuster", "Springer", 24, 3, 4, True, False, 1, False, 4, 4, 4, 5, 2, (14, 15)),
]


def build_dates(start_date: date, weeks: int) -> list[date]:
    return [start_date + timedelta(days=i) for i in range(weeks * 7)]


def easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def austrian_holidays(year: int) -> dict[date, str]:
    easter = easter_sunday(year)
    holidays = {
        date(year, 1, 1): "Neujahr",
        date(year, 1, 6): "Heilige Drei Koenige",
        easter + timedelta(days=1): "Ostermontag",
        date(year, 5, 1): "Staatsfeiertag",
        easter + timedelta(days=39): "Christi Himmelfahrt",
        easter + timedelta(days=50): "Pfingstmontag",
        easter + timedelta(days=60): "Fronleichnam",
        date(year, 8, 15): "Mariae Himmelfahrt",
        date(year, 10, 26): "Nationalfeiertag",
        date(year, 11, 1): "Allerheiligen",
        date(year, 12, 8): "Mariae Empfaengnis",
        date(year, 12, 25): "Christtag",
        date(year, 12, 26): "Stefanitag",
    }
    return holidays


def build_month_dates(year: int, month: int) -> list[date]:
    day_count = calendar.monthrange(year, month)[1]
    return [date(year, month, day) for day in range(1, day_count + 1)]


def day_type(current_day: date, holidays: dict[date, str]) -> str:
    if current_day in holidays or current_day.weekday() == 6:
        return "Sonntag/Feiertag"
    if current_day.weekday() == 5:
        return "Samstag"
    return "Werktag"


def weekend_indices(days: list[date], holidays: dict[date, str] | None = None) -> list[int]:
    holidays = holidays or {}
    return [
        i
        for i, day in enumerate(days)
        if day.weekday() >= 5 or day in holidays
    ]


def default_shift_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Kuerzel": "D19", "Name": "19-23", "Stunden": 4, "Nacht": False, "Prioritaet": 1, "Farbe": "#fde68a"},
            {"Kuerzel": "D6", "Name": "6-18", "Stunden": 12, "Nacht": False, "Prioritaet": 1, "Farbe": "#bbf7d0"},
            {"Kuerzel": "D7", "Name": "7-13", "Stunden": 6, "Nacht": False, "Prioritaet": 2, "Farbe": "#d9f99d"},
            {"Kuerzel": "D8", "Name": "8-20", "Stunden": 12, "Nacht": False, "Prioritaet": 1, "Farbe": "#bae6fd"},
            {"Kuerzel": "D14", "Name": "14-22", "Stunden": 8, "Nacht": False, "Prioritaet": 1, "Farbe": "#fed7aa"},
            {"Kuerzel": "N18", "Name": "18-6", "Stunden": 12, "Nacht": True, "Prioritaet": 1, "Farbe": "#c7d2fe"},
            {"Kuerzel": "D15", "Name": "15-23", "Stunden": 8, "Nacht": False, "Prioritaet": 1, "Farbe": "#fecdd3"},
            {"Kuerzel": "D715", "Name": "7-15", "Stunden": 8, "Nacht": False, "Prioritaet": 2, "Farbe": "#ccfbf1"},
            {"Kuerzel": "D718", "Name": "7-18", "Stunden": 11, "Nacht": False, "Prioritaet": 1, "Farbe": "#e9d5ff"},
            {"Kuerzel": "D614", "Name": "6-14", "Stunden": 8, "Nacht": False, "Prioritaet": 2, "Farbe": "#fbcfe8"},
        ]
    )


def shift_definitions_from_editor(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    used_codes = set()
    for index, row in df.fillna("").iterrows():
        raw_code = str(row.get("Kuerzel", "")).strip().upper()
        code = "".join(character for character in raw_code if character.isalnum())[:4]
        if not code:
            code = f"D{index + 1}"
        original_code = code
        duplicate_index = 2
        while code in used_codes or code == "-":
            code = f"{original_code}{duplicate_index}"[:4]
            duplicate_index += 1
        used_codes.add(code)

        name = str(row.get("Name", "")).strip() or f"Dienst {index + 1}"
        rows.append(
            {
                "Kuerzel": code,
                "Name": name,
                "Stunden": max(1, int(row.get("Stunden", 8) or 8)),
                "Nacht": bool(row.get("Nacht", False)),
                "Prioritaet": min(3, max(1, int(row.get("Prioritaet", 1) or 1))),
                "Farbe": str(row.get("Farbe", "")).strip()
                or SHIFT_COLORS[index % len(SHIFT_COLORS)],
            }
        )

    if not rows:
        return default_shift_dataframe()
    return pd.DataFrame(rows)


def shift_codes(shift_df: pd.DataFrame) -> list[str]:
    return shift_definitions_from_editor(shift_df)["Kuerzel"].tolist()


def night_shift_codes(shift_df: pd.DataFrame) -> list[str]:
    cleaned = shift_definitions_from_editor(shift_df)
    return cleaned.loc[cleaned["Nacht"], "Kuerzel"].tolist()


def shift_priorities(shift_df: pd.DataFrame) -> dict[str, int]:
    cleaned = shift_definitions_from_editor(shift_df)
    return {str(row["Kuerzel"]): int(row["Prioritaet"]) for _, row in cleaned.iterrows()}


def shift_hours(shift_df: pd.DataFrame) -> dict[str, int]:
    cleaned = shift_definitions_from_editor(shift_df)
    return {str(row["Kuerzel"]): int(row["Stunden"]) for _, row in cleaned.iterrows()}


def default_shift_code(shift_df: pd.DataFrame, fallback_position: int = 0) -> str:
    codes = shift_codes(shift_df)
    if not codes:
        return ""
    return codes[min(fallback_position, len(codes) - 1)]


def default_resource_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Tagesart": "Werktag",
                "D19": 1,
                "D6": 2,
                "D7": 1,
                "D8": 2,
                "D14": 1,
                "N18": 2,
                "D15": 0,
                "D715": 0,
                "D718": 0,
                "D614": 0,
            },
            {
                "Tagesart": "Samstag",
                "D19": 0,
                "D6": 2,
                "D7": 0,
                "D8": 2,
                "D14": 1,
                "N18": 2,
                "D15": 3,
                "D715": 2,
                "D718": 1,
                "D614": 1,
            },
            {
                "Tagesart": "Sonntag/Feiertag",
                "D19": 0,
                "D6": 2,
                "D7": 0,
                "D8": 2,
                "D14": 1,
                "N18": 2,
                "D15": 3,
                "D715": 2,
                "D718": 1,
                "D614": 1,
            },
        ]
    )


def normalize_resource_dataframe(resource_df: pd.DataFrame, shifts: list[str]) -> pd.DataFrame:
    rows = []
    source = resource_df.set_index("Tagesart", drop=False) if "Tagesart" in resource_df.columns else pd.DataFrame()
    for type_name in DAY_TYPE_ORDER:
        row = {"Tagesart": type_name}
        for shift in shifts:
            if not source.empty and type_name in source.index and shift in source.columns:
                value = source.loc[type_name, shift]
            else:
                value = 1
            row[shift] = max(0, int(value or 0))
        rows.append(row)
    return pd.DataFrame(rows)


def resource_requirements_from_editor(df: pd.DataFrame, shifts: list[str]) -> dict[str, dict[str, int]]:
    requirements = {}
    for _, row in df.fillna(0).iterrows():
        type_name = str(row.get("Tagesart", "")).strip()
        if type_name not in DAY_TYPE_ORDER:
            continue
        requirements[type_name] = {shift: max(0, int(row.get(shift, 0) or 0)) for shift in shifts}

    for type_name in DAY_TYPE_ORDER:
        requirements.setdefault(type_name, {shift: 1 for shift in shifts})
    return requirements


def requirements_for_days(
    days: list[date],
    holidays: dict[date, str],
    resource_requirements: dict[str, dict[str, int]],
    shifts: list[str],
) -> dict[tuple[int, str], int]:
    requirements = {}
    for d, current_day in enumerate(days):
        type_name = day_type(current_day, holidays)
        for shift in shifts:
            requirements[(d, shift)] = resource_requirements[type_name][shift]
    return requirements


def day_requirements_dataframe(
    days: list[date],
    holidays: dict[date, str],
    daily_requirements: dict[tuple[int, str], int],
    shifts: list[str],
) -> pd.DataFrame:
    rows = []
    for day_index, current_day in enumerate(days):
        row = {
            "Tag": day_label(current_day),
            "Tagesart": day_type(current_day, holidays),
            "Feiertag": holidays.get(current_day, ""),
        }
        for shift in shifts:
            row[shift] = daily_requirements.get((day_index, shift), 0)
        rows.append(row)
    return pd.DataFrame(rows)


def day_requirements_from_editor(df: pd.DataFrame, shifts: list[str]) -> dict[tuple[int, str], int]:
    requirements = {}
    for day_index, row in df.fillna(0).iterrows():
        for shift in shifts:
            requirements[(day_index, shift)] = max(0, int(row.get(shift, 0) or 0))
    return requirements


def apply_day_overrides(
    daily_requirements: dict[tuple[int, str], int],
    month_key: str,
    shifts: list[str],
) -> dict[tuple[int, str], int]:
    updated_requirements = dict(daily_requirements)
    overrides = st.session_state.get("day_requirement_overrides", {}).get(month_key, {})
    for day_index, shift_values in overrides.items():
        for shift in shifts:
            if shift in shift_values:
                updated_requirements[(int(day_index), shift)] = max(0, int(shift_values[shift]))
    return updated_requirements


def day_label(current_day: date) -> str:
    return f"{WEEKDAY_NAMES[current_day.weekday()]} {current_day.strftime('%d.%m.')}"


def priority_label(value: object) -> str:
    if isinstance(value, str) and value in PRIORITY_LEVELS:
        return value
    try:
        numeric_value = int(value)
    except (TypeError, ValueError):
        numeric_value = PRIORITY_LEVELS[DEFAULT_PRIORITY_LABEL]
    for label, option_value in PRIORITY_LEVELS.items():
        if option_value == numeric_value:
            return label
    return DEFAULT_PRIORITY_LABEL


def priority_value(value: object) -> int:
    if isinstance(value, str):
        return PRIORITY_LEVELS.get(value, PRIORITY_LEVELS[DEFAULT_PRIORITY_LABEL])
    try:
        numeric_value = int(value)
    except (TypeError, ValueError):
        return PRIORITY_LEVELS[DEFAULT_PRIORITY_LABEL]
    return min(5, max(1, numeric_value))


def priority_weight(value: object) -> int:
    return PRIORITY_WEIGHTS[priority_value(value)]


def shift_priority_label(value: object) -> str:
    try:
        numeric_value = int(value)
    except (TypeError, ValueError):
        numeric_value = 1
    for label, option_value in SHIFT_PRIORITY_LEVELS.items():
        if option_value == numeric_value:
            return label
    return DEFAULT_SHIFT_PRIORITY_LABEL


def color_swatch(color: str) -> str:
    safe_color = str(color).strip() or FREE_SHIFT_COLOR
    return (
        f'<span style="display:inline-flex;align-items:center;gap:8px;">'
        f'<span style="display:inline-block;width:18px;height:18px;border-radius:4px;'
        f'border:1px solid #cbd5e1;background:{safe_color};"></span>'
        f'</span>'
    )


def display_employee_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    display_df = normalize_employee_dataframe(df).copy()
    for column in ["Gerne Nacht", "Nur Doppelnaechte", "Wochenende frei"]:
        display_df[column] = display_df[column].map(lambda value: "Ja" if bool(value) else "Nein")
    for column in [
        "Prio Nacht",
        "Prio Doppelnaechte",
        "Prio frei nach Nacht",
        "Prio Wochenende",
        "Prio Wunschfrei",
    ]:
        display_df[column] = display_df[column].map(priority_value)