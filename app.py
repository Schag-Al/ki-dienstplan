from __future__ import annotations

import calendar
import copy
import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from ortools.sat.python import cp_model

try:
    from app_version import APP_NAME, APP_VERSION
except Exception:
    APP_NAME = "KI-Dienstplan"
    APP_VERSION = "lokal"

st.set_page_config(page_title=f"{APP_NAME} {APP_VERSION}", layout="wide")


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
    3: "März",
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
    "3 - wenn möglich beachten": 3,
    "4 - geringe Priorität": 4,
    "5 - fair verteilen": 5,
}
PRIORITY_WEIGHTS = {1: 1000, 2: 60, 3: 25, 4: 10, 5: 4}
DEFAULT_PRIORITY_LABEL = "3 - wenn möglich beachten"
NIGHT_PRIORITY_LABELS_WANTED = {
    "1 - muss immer zutreffen": "1 - Nachtwunsch sehr stark berücksichtigen",
    "2 - nur im Ausnahmefall verletzen": "2 - Nachtwunsch stark berücksichtigen",
    "3 - wenn möglich beachten": "3 - Nachtwunsch wenn möglich berücksichtigen",
    "4 - geringe Priorität": "4 - Nachtwunsch nur leicht berücksichtigen",
    "5 - fair verteilen": "5 - normal fair verteilen",
}
NIGHT_PRIORITY_LABELS_AVOIDED = {
    "3 - wenn möglich beachten": "3 - Nachtdienste möglichst vermeiden, bei Bedarf möglich",
    "4 - geringe Priorität": "4 - Nachtdienste eher vermeiden",
    "5 - fair verteilen": "5 - Nachtdienste normal fair mitverteilen",
}
DOUBLE_NIGHT_PRIORITY_LABELS = {
    "1 - muss immer zutreffen": "1 - Doppelnächte sehr stark berücksichtigen",
    "2 - nur im Ausnahmefall verletzen": "2 - Doppelnächte stark berücksichtigen",
    "3 - wenn möglich beachten": "3 - Doppelnächte wenn möglich berücksichtigen",
    "4 - geringe Priorität": "4 - Doppelnächte nur leicht berücksichtigen",
    "5 - fair verteilen": "5 - Doppelnächte normal fair verteilen",
}
SHIFT_PRIORITY_LEVELS = {
    "1 - muss immer besetzt werden": 1,
    "2 - sollte besetzt sein": 2,
    "3 - nur wenn genug Mitarbeiter vorhanden": 3,
}
DEFAULT_SHIFT_PRIORITY_LABEL = "1 - muss immer besetzt werden"
PLAN_OPTIMIZATION_MODES = ["Zufriedenheit zuerst", "Ausgewogen", "Abdeckung zuerst"]
DEFAULT_PLAN_OPTIMIZATION_MODE = "Zufriedenheit zuerst"
DEFAULT_CALCULATION_MODE = "Aktuelle Berechnung"
CACHE_ALGORITHM_VERSION = "bestplan-cache-2026-04-30-zeitkonto-prioritaet"
PAUSE_POLICY_OPTIONS = [
    "Pause bezahlt und in Dienstzeit enthalten",
    "Pause unbezahlt und von Dienstzeit abziehen",
]
DEFAULT_PAUSE_POLICY = PAUSE_POLICY_OPTIONS[0]
DEFAULT_PAUSE_THRESHOLD_HOURS = 6.0
DEFAULT_PAUSE_DURATION_MINUTES = 30
REPLACEMENT_REST_SCOPE_OPTIONS = [
    "Keine Ersatzruhe",
    "Nur Feiertage",
    "Sonntage und Feiertage",
    "Samstage, Sonntage und Feiertage",
]
DEFAULT_REPLACEMENT_REST_SCOPE = "Nur Feiertage"
REPLACEMENT_REST_KIND_OPTIONS = [
    "Gesetzliche Ersatzruhe",
    "Vertraglicher Zeitausgleich",
]
DEFAULT_REPLACEMENT_REST_KIND = "Vertraglicher Zeitausgleich"
NIGHT_CREDIT_MODE_OPTIONS = [
    "Keine Nachtgutschrift",
    "Nachtgutschrift ins Zeitkonto",
    "Nachtgutschrift als Dienststunden",
]
DEFAULT_NIGHT_CREDIT_MODE = "Nachtgutschrift ins Zeitkonto"
DEFAULT_NIGHT_CREDIT_HOURS = 2.0
TIME_ACCOUNT_USAGE_OPTIONS = [
    "Vorrangig abbauen (sobald möglich)",
    "Sobald passend abbauen",
    "Nachrangig abbauen (nur bei genug Kapazität)",
]
DEFAULT_TIME_ACCOUNT_USAGE = "Sobald passend abbauen"
VACATION_WEEKEND_POLICY_OPTIONS = [
    "Nur eingetragene Urlaubstage",
    "Wochenende nach Urlaub",
    "Wochenende vor und nach Urlaub",
]
DEFAULT_VACATION_WEEKEND_POLICY = "Wochenende nach Urlaub"
DEFAULT_ANNUAL_VACATION_WEEKS = 5.0
DEFAULT_ANNUAL_VACATION_WORKDAYS = 25.0
DEFAULT_VACATION_DAY_HOURS = 0.0
DEFAULT_VACATION_START_DATE = date(2026, 1, 1)
DEFAULT_FULL_TIME_WEEKLY_HOURS = 40.0
LEGAL_PROFILE_OPTIONS = [
    "AZG allgemein",
    "Schichtbetrieb Österreich",
    "KA-AZG / Krankenanstalt",
    "KV/Betriebsvereinbarung",
]
DEFAULT_LEGAL_PROFILE = "Schichtbetrieb Österreich"
TAKEOVER_PREVIOUS_SERVICE_OPTIONS = ["Frei", "Tagdienst", "Nachtdienst"]
SAVED_SCHEDULES_FILE = Path(__file__).with_name("saved_schedules.json")
BEST_PLAN_CACHE_FILE = Path(__file__).with_name("best_plan_cache.json")


@dataclass(frozen=True)
class Employee:
    name: str
    qualification: str
    weekly_hours_target: float
    max_shifts_per_week: int
    max_nights_per_month: int
    likes_nights: bool
    double_nights_only: bool
    allow_three_consecutive_nights: bool
    rest_after_night: int
    prefers_weekends_off: bool
    night_priority: int
    double_night_priority: int
    rest_priority: int
    weekend_priority: int
    wish_free_priority: int
    blocked_days: tuple[int, ...] = ()
    max_consecutive_workdays: int = 6
    max_weekly_planned_hours: float = 48
    planned_sick_days: tuple[int, ...] = ()
    vacation_days: tuple[int, ...] = ()
    annual_vacation_weeks: float = DEFAULT_ANNUAL_VACATION_WEEKS
    vacation_start_date: str = DEFAULT_VACATION_START_DATE.isoformat()
    annual_vacation_workdays: float = DEFAULT_ANNUAL_VACATION_WORKDAYS
    vacation_day_hours: float = DEFAULT_VACATION_DAY_HOURS
    prefers_joint_weekends: bool = True
    joint_weekend_priority: int = 3
    participates_in_schedule: bool = True
    takeover_confirmed: bool = False
    takeover_start_date: str = ""
    takeover_vacation_hours: float = 0.0
    takeover_time_balance_hours: float = 0.0
    takeover_replacement_rest_hours: float = 0.0
    takeover_previous_day_service: str = "Frei"
    takeover_second_previous_day_service: str = "Frei"
    takeover_previous_work_streak: int = 0


SAMPLE_EMPLOYEE_SET_VERSION = "turnus-balanced-2026-04d-monatsabwesenheiten"
SAMPLE_EMPLOYEES = [
    Employee("Martina Hofer", "Leitung / Büro - nicht dienstplanrelevant", 0.25, 1, 0, False, False, False, 1, True, 1, 5, 5, 1, 1, tuple(range(31)), participates_in_schedule=False),
    Employee("Sabine Gruber", "Krankenstand geplant", 0.25, 1, 0, False, False, False, 1, True, 1, 5, 5, 1, 1, planned_sick_days=tuple(range(31)), participates_in_schedule=False),
    Employee("Julia Berger", "Pflege 40 h - keine Nacht", 40, 5, 0, False, False, False, 2, True, 1, 4, 2, 2, 1, (4, 5), vacation_days=tuple(range(5, 10))),
    Employee("Lukas Steiner", "Pflege 40 h - Tag/Abend", 40, 5, 2, False, False, False, 2, False, 2, 4, 2, 4, 2, (12,)),
    Employee("Nadine Leitner", "Pflege 40 h - keine Nacht", 40, 5, 0, False, False, False, 2, True, 1, 4, 2, 2, 1, (8, 9), vacation_days=tuple(range(12, 17))),
    Employee("Paul Wagner", "Springer 40 h", 40, 5, 6, True, False, False, 1, False, 3, 4, 3, 4, 2, (17,), vacation_days=tuple(range(26, 30))),
    Employee("David Eder", "Springer 40 h - gerne Nacht", 40, 5, 8, True, False, False, 1, False, 4, 4, 4, 5, 2, (24,)),
    Employee("Omar Haddad", "Springer 40 h - gerne Nacht", 40, 5, 8, True, False, False, 1, False, 4, 4, 4, 5, 2, (27,)),
    Employee("Anna Huber", "Pflege 36 h", 36, 4, 4, False, False, False, 2, False, 2, 3, 2, 5, 1, (3, 4), vacation_days=tuple(range(19, 24))),
    Employee("Ben Fischer", "Pflege 36 h - Doppelnächte", 36, 4, 8, True, True, False, 1, False, 3, 2, 3, 5, 2, (18,)),
    Employee("Elif Yilmaz", "Pflege 36 h", 36, 4, 4, False, False, False, 2, False, 2, 3, 2, 5, 1, (15,)),
    Employee("Marco Seidl", "Pflege 36 h - Doppelnächte", 36, 4, 8, True, True, False, 2, False, 3, 2, 2, 5, 2, (5,)),
    Employee("Simon Koller", "Pflege 36 h - gerne Nacht", 36, 4, 6, True, False, False, 1, False, 3, 3, 3, 4, 2, (8,)),
    Employee("Clara Winkler", "Pflege 32 h", 32, 4, 3, False, False, False, 2, False, 2, 3, 2, 5, 1, (9, 10), vacation_days=tuple(range(1, 5))),
    Employee("Greta Pichler", "Teamleitung 32 h", 32, 4, 2, False, False, False, 2, False, 2, 3, 2, 5, 1, (21, 22)),
    Employee("Petra Auer", "Pflege 32 h", 32, 4, 3, False, False, False, 2, False, 2, 3, 2, 5, 1, (1, 2)),
    Employee("Yasmin Cakir", "Pflege 32 h - gerne Nacht", 32, 4, 5, True, True, False, 2, True, 3, 2, 2, 3, 1, (12, 13)),
    Employee("Rafael Kern", "Pflege 32 h - gerne Nacht", 32, 4, 6, True, True, False, 1, False, 3, 2, 3, 5, 2, (29,)),
    Employee("Laura Klein", "Pflege 32 h", 32, 4, 2, False, False, False, 2, True, 2, 4, 2, 2, 1, (16, 17)),
    Employee("Zoe Renner", "Pflege 32 h", 32, 4, 2, False, False, False, 2, True, 2, 3, 2, 2, 1, (25,)),
    Employee("Eva Schmid", "Pflege 28 h - keine Nacht", 28, 4, 0, False, False, False, 2, True, 1, 4, 2, 2, 1, (22, 23)),
    Employee("Hannah Lang", "Springer 24 h", 24, 3, 4, True, False, False, 1, False, 4, 4, 4, 5, 2, (13,)),
    Employee("Nora Reiter", "Pflege 24 h", 24, 3, 2, False, False, False, 2, True, 2, 4, 2, 2, 1, (19,)),
    Employee("Michael Schuster", "Springer 24 h - gerne Nacht", 24, 3, 4, True, False, False, 1, False, 4, 4, 4, 5, 2, (14, 15)),
    Employee("Daniel Novak", "Nur Nachtdienst 16 h", 16, 2, 12, True, True, True, 2, False, 1, 1, 2, 5, 2, (11,)),
]

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
        date(year, 1, 6): "Heilige Drei Könige",
        easter + timedelta(days=1): "Ostermontag",
        date(year, 5, 1): "Staatsfeiertag",
        easter + timedelta(days=39): "Christi Himmelfahrt",
        easter + timedelta(days=50): "Pfingstmontag",
        easter + timedelta(days=60): "Fronleichnam",
        date(year, 8, 15): "Mariä Himmelfahrt",
        date(year, 10, 26): "Nationalfeiertag",
        date(year, 11, 1): "Allerheiligen",
        date(year, 12, 8): "Mariä Empfängnis",
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


def normalize_replacement_rest_scope(value: object, enabled: bool = True) -> str:
    scope = str(value or "").strip()
    legacy = {
        "Aus": "Keine Ersatzruhe",
        "Deaktiviert": "Keine Ersatzruhe",
        "Feiertage": "Nur Feiertage",
        "Sonntag und Feiertag": "Sonntage und Feiertage",
        "Sonn-/Feiertage": "Sonntage und Feiertage",
        "Sonntag/Feiertag": "Sonntage und Feiertage",
    }
    scope = legacy.get(scope, scope)
    if scope not in REPLACEMENT_REST_SCOPE_OPTIONS:
        return DEFAULT_REPLACEMENT_REST_SCOPE if enabled else "Keine Ersatzruhe"
    return scope


def normalize_replacement_rest_kind(value: object) -> str:
    text = str(value or "").strip()
    legacy = {
        "Ersatzruhe": "Gesetzliche Ersatzruhe",
        "Freizeitausgleich": "Vertraglicher Zeitausgleich",
        "Ausgleich": "Vertraglicher Zeitausgleich",
    }
    text = legacy.get(text, text)
    return text if text in REPLACEMENT_REST_KIND_OPTIONS else DEFAULT_REPLACEMENT_REST_KIND


def normalize_night_credit_mode(value: object) -> str:
    text = str(value or "").strip()
    legacy = {
        "Aus": "Keine Nachtgutschrift",
        "Keine": "Keine Nachtgutschrift",
        "Zeitkonto": "Nachtgutschrift ins Zeitkonto",
        "Dienststunden": "Nachtgutschrift als Dienststunden",
    }
    text = legacy.get(text, text)
    return text if text in NIGHT_CREDIT_MODE_OPTIONS else DEFAULT_NIGHT_CREDIT_MODE


def normalize_time_account_usage(value: object) -> str:
    text = str(value or "").strip()
    legacy = {
        "Vorrangig": "Vorrangig abbauen (sobald möglich)",
        "Vorrangig abbauen": "Vorrangig abbauen (sobald möglich)",
        "Sofort": "Vorrangig abbauen (sobald möglich)",
        "Sobald möglich": "Vorrangig abbauen (sobald möglich)",
        "Normal": "Sobald passend abbauen",
        "Passend": "Sobald passend abbauen",
        "Nachrang": "Nachrangig abbauen (nur bei genug Kapazität)",
        "Nachrangig": "Nachrangig abbauen (nur bei genug Kapazität)",
        "Nachrangig abbauen": "Nachrangig abbauen (nur bei genug Kapazität)",
    }
    text = legacy.get(text, text)
    return text if text in TIME_ACCOUNT_USAGE_OPTIONS else DEFAULT_TIME_ACCOUNT_USAGE


def time_account_usage_weight(value: object) -> tuple[int, int]:
    usage = normalize_time_account_usage(value)
    if usage == "Vorrangig abbauen (sobald möglich)":
        return 900, 260
    if usage == "Nachrangig abbauen (nur bei genug Kapazität)":
        return 170, 45
    return 520, 130


def normalize_pause_policy(value: object) -> str:
    text = str(value or "").strip()
    legacy = {
        "Brutto": "Pause bezahlt und in Dienstzeit enthalten",
        "bezahlt": "Pause bezahlt und in Dienstzeit enthalten",
        "inkludiert": "Pause bezahlt und in Dienstzeit enthalten",
        "Netto": "Pause unbezahlt und von Dienstzeit abziehen",
        "unbezahlt": "Pause unbezahlt und von Dienstzeit abziehen",
        "abziehen": "Pause unbezahlt und von Dienstzeit abziehen",
    }
    text = legacy.get(text, text)
    return text if text in PAUSE_POLICY_OPTIONS else DEFAULT_PAUSE_POLICY


def replacement_rest_applies(
    current_day: date,
    holidays: dict[date, str],
    scope: str,
) -> bool:
    normalized_scope = normalize_replacement_rest_scope(scope)
    is_holiday = current_day in holidays
    is_saturday = current_day.weekday() == 5
    is_sunday = current_day.weekday() == 6
    if normalized_scope == "Keine Ersatzruhe":
        return False
    if normalized_scope == "Nur Feiertage":
        return is_holiday
    if normalized_scope == "Sonntage und Feiertage":
        return is_sunday or is_holiday
    if normalized_scope == "Samstage, Sonntage und Feiertage":
        return is_saturday or is_sunday or is_holiday
    return False


def normalize_vacation_weekend_policy(value: object) -> str:
    policy = str(value or "").strip()
    legacy = {
        "Nur danach": "Wochenende nach Urlaub",
        "Danach": "Wochenende nach Urlaub",
        "Vorher und nachher": "Wochenende vor und nach Urlaub",
        "Kein Wochenende": "Nur eingetragene Urlaubstage",
    }
    policy = legacy.get(policy, policy)
    if policy not in VACATION_WEEKEND_POLICY_OPTIONS:
        return DEFAULT_VACATION_WEEKEND_POLICY
    return policy


def vacation_daily_minutes(employee: Employee) -> int:
    day_hours = float(employee.vacation_day_hours or 0)
    if day_hours <= 0:
        day_hours = float(employee.weekly_hours_target) / 5
    return int(round(day_hours * 60))


def vacation_entitlement_hours(employee: Employee) -> float:
    annual_workdays = float(employee.annual_vacation_workdays or 0)
    if annual_workdays > 0:
        return round(annual_workdays * format_minutes_as_hours(vacation_daily_minutes(employee)), 2)
    return round(float(employee.weekly_hours_target) * float(employee.annual_vacation_weeks), 2)


def parse_date_value(value: object, default: date = DEFAULT_VACATION_START_DATE) -> date:
    if isinstance(value, date):
        return value
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value or "").strip()
    if not text:
        return default
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return pd.to_datetime(text, format=pattern).date()
        except (TypeError, ValueError):
            continue
    try:
        return pd.to_datetime(text, dayfirst=True).date()
    except (TypeError, ValueError):
        return default


def employee_vacation_start_date(employee_or_row: Employee | dict | pd.Series) -> date:
    if isinstance(employee_or_row, Employee):
        value = employee_or_row.vacation_start_date
    else:
        value = employee_or_row.get("Urlaubs-Stichtag", DEFAULT_VACATION_START_DATE.isoformat())
    return parse_date_value(value, DEFAULT_VACATION_START_DATE)


def anniversary_date(start_date: date, year: int) -> date:
    try:
        return date(year, start_date.month, start_date.day)
    except ValueError:
        return date(year, 2, 28)


def vacation_period_for_month(employee_or_row: Employee | dict | pd.Series, year: int, month: int) -> tuple[date, date]:
    start_date = employee_vacation_start_date(employee_or_row)
    reference_day = date(int(year), int(month), 1)
    if reference_day < start_date:
        return start_date, anniversary_date(start_date, start_date.year + 1) - timedelta(days=1)
    anniversary_this_year = anniversary_date(start_date, reference_day.year)
    period_start = anniversary_this_year if reference_day >= anniversary_this_year else anniversary_date(start_date, reference_day.year - 1)
    period_end = anniversary_date(start_date, period_start.year + 1) - timedelta(days=1)
    if period_start < start_date <= period_end:
        period_start = start_date
    return period_start, period_end


def vacation_period_label(period_start: date, period_end: date) -> str:
    return f"{period_start.strftime('%d.%m.%Y')} bis {period_end.strftime('%d.%m.%Y')}"


def vacation_paid_minutes_for_day(employee: Employee, day_index: int, days: list[date]) -> int:
    if day_index not in employee.vacation_days or day_index >= len(days):
        return 0
    return vacation_daily_minutes(employee) if days[day_index].weekday() < 5 else 0


def vacation_paid_minutes_for_month(employee: Employee, days: list[date], counts_as_hours: bool = True) -> int:
    if not counts_as_hours:
        return 0
    return sum(
        vacation_paid_minutes_for_day(employee, day_index, days)
        for day_index in employee.vacation_days
        if 0 <= day_index < len(days)
    )


def vacation_protected_day_indices(
    employee: Employee,
    days: list[date],
    weekend_policy: str,
) -> set[int]:
    protected = {day_index for day_index in employee.vacation_days if 0 <= day_index < len(days)}
    policy = normalize_vacation_weekend_policy(weekend_policy)
    if policy == "Nur eingetragene Urlaubstage":
        return protected

    vacation_weekdays = [
        day_index
        for day_index in employee.vacation_days
        if 0 <= day_index < len(days) and days[day_index].weekday() < 5
    ]
    vacation_set = set(vacation_weekdays)
    for day_index in vacation_weekdays:
        current_day = days[day_index]
        if current_day.weekday() == 4:
            for weekend_index in (day_index + 1, day_index + 2):
                if weekend_index < len(days):
                    protected.add(weekend_index)
        if policy == "Wochenende vor und nach Urlaub" and current_day.weekday() == 0:
            previous_friday = day_index - 3
            if previous_friday in vacation_set:
                continue
            for weekend_index in (day_index - 2, day_index - 1):
                if 0 <= weekend_index < len(days):
                    protected.add(weekend_index)
    return protected


def weekend_indices(days: list[date], holidays: dict[date, str] | None = None) -> list[int]:
    holidays = holidays or {}
    return [
        i
        for i, day in enumerate(days)
        if day.weekday() >= 5 or day in holidays
    ]


def saturday_sunday_pairs(days: list[date]) -> list[tuple[int, int]]:
    return [
        (index, index + 1)
        for index, current_day in enumerate(days[:-1])
        if current_day.weekday() == 5 and days[index + 1].weekday() == 6
    ]


def calendar_week_day_indices(days: list[date]) -> list[list[int]]:
    weeks: dict[tuple[int, int], list[int]] = {}
    for index, current_day in enumerate(days):
        iso_year, iso_week, _weekday = current_day.isocalendar()
        weeks.setdefault((iso_year, iso_week), []).append(index)
    return list(weeks.values())


def parse_bool_value(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return default
    text = str(value).strip().lower()
    if text in {"ja", "yes", "true", "1", "x"}:
        return True
    if text in {"nein", "no", "false", "0", "-"}:
        return False
    return bool(value)


def schedule_relevant_default(row: pd.Series | dict) -> bool:
    qualification = str(row.get("Qualifikation", "")).lower()
    if "nicht dienstplanrelevant" in qualification:
        return False
    sick_days = parse_blocked_days(row.get("Krankenstand-Tage", ""))
    if "krankenstand geplant" in qualification and len(sick_days) >= 28:
        return False
    return True


def active_schedule_employees(employees: list[Employee]) -> list[Employee]:
    return [employee for employee in employees if employee.participates_in_schedule]


def default_shift_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Kuerzel": "D19", "Name": "Abend kurz", "Beginn": "19:00", "Ende": "23:00", "Stunden": 4.0, "Nacht": False, "Prioritaet": 1, "Farbe": "#fde68a"},
            {"Kuerzel": "D6", "Name": "Frühdienst lang", "Beginn": "06:00", "Ende": "18:00", "Stunden": 12.0, "Nacht": False, "Prioritaet": 1, "Farbe": "#bbf7d0"},
            {"Kuerzel": "D7", "Name": "Frühdienst kurz", "Beginn": "07:00", "Ende": "13:00", "Stunden": 6.0, "Nacht": False, "Prioritaet": 2, "Farbe": "#d9f99d"},
            {"Kuerzel": "D8", "Name": "Tagdienst lang", "Beginn": "08:00", "Ende": "20:00", "Stunden": 12.0, "Nacht": False, "Prioritaet": 1, "Farbe": "#bae6fd"},
            {"Kuerzel": "D14", "Name": "Spätdienst", "Beginn": "14:00", "Ende": "22:00", "Stunden": 8.0, "Nacht": False, "Prioritaet": 1, "Farbe": "#fed7aa"},
            {"Kuerzel": "N18", "Name": "Nachtdienst", "Beginn": "18:00", "Ende": "06:00", "Stunden": 12.0, "Nacht": True, "Prioritaet": 1, "Farbe": "#c7d2fe"},
            {"Kuerzel": "D15", "Name": "Spätdienst kurz", "Beginn": "15:00", "Ende": "23:00", "Stunden": 8.0, "Nacht": False, "Prioritaet": 1, "Farbe": "#fecdd3"},
            {"Kuerzel": "D715", "Name": "Frühdienst 7-15", "Beginn": "07:00", "Ende": "15:00", "Stunden": 8.0, "Nacht": False, "Prioritaet": 2, "Farbe": "#ccfbf1"},
            {"Kuerzel": "D718", "Name": "Tagdienst 7-18", "Beginn": "07:00", "Ende": "18:00", "Stunden": 11.0, "Nacht": False, "Prioritaet": 1, "Farbe": "#e9d5ff"},
            {"Kuerzel": "D614", "Name": "Frühdienst 6-14", "Beginn": "06:00", "Ende": "14:00", "Stunden": 8.0, "Nacht": False, "Prioritaet": 2, "Farbe": "#fbcfe8"},
        ]
    )


def parse_clock_to_minutes(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace(".", ":")
    time_separator = str(st.session_state.get("time_separator", ":"))
    if time_separator and time_separator != ":":
        normalized = normalized.replace(time_separator, ":")
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", normalized)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return None
    return hours * 60 + minutes


def format_minutes_as_clock(total_minutes: int) -> str:
    normalized = total_minutes % (24 * 60)
    separator = str(st.session_state.get("time_separator", ":"))
    return f"{normalized // 60:02d}{separator}{normalized % 60:02d}"


def format_minutes_as_hours(total_minutes: int) -> float:
    return round(total_minutes / 60, 2)


def allowed_variance_minutes(target_minutes: int, percent_limit: float, hours_limit: float) -> int:
    limits = []
    percent_value = max(0.0, float(percent_limit))
    hours_value = max(0.0, float(hours_limit))
    if percent_value > 0:
        limits.append(round(target_minutes * percent_value / 100))
    if hours_value > 0:
        limits.append(round(hours_value * 60))
    return int(min(limits)) if limits else 0


def open_shift_penalties(open_shift_codes: list[str] | None) -> dict[str, int]:
    return {
        shift: max(50, 5000 - index * 500)
        for index, shift in enumerate(open_shift_codes or [])
    }


def shortage_penalty_for_shift(shift: str, priority: int, open_shift_codes: list[str] | None) -> int:
    if shift in set(open_shift_codes or []):
        return 350000 + open_shift_penalties(open_shift_codes).get(shift, 900)
    if priority == 1:
        return 900000
    if priority == 2:
        return 220000
    return 70000


def format_hour_value(value: object) -> str:
    try:
        text = f"{float(value):.2f}"
        separator = str(st.session_state.get("decimal_separator", ","))
        return text.replace(".", separator)
    except (TypeError, ValueError):
        return str(value)


def parse_hour_value(value: object, default: float) -> float:
    text = str(value or "").strip()
    if not text:
        return float(default)
    decimal_separator = str(st.session_state.get("decimal_separator", ","))
    normalized = text
    if decimal_separator and decimal_separator != ".":
        normalized = normalized.replace(decimal_separator, ".")
    normalized = normalized.replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return float(default)


def format_display_hours(value: object) -> str:
    try:
        numeric_value = round(float(value), 2)
    except (TypeError, ValueError):
        return str(value)
    text = f"{numeric_value:.2f}".rstrip("0").rstrip(".")
    separator = str(st.session_state.get("decimal_separator", ","))
    return text.replace(".", separator)


def duration_minutes_between(start_minutes: int, end_minutes: int) -> int:
    if end_minutes <= start_minutes:
        end_minutes += 24 * 60
    return end_minutes - start_minutes


def derive_shift_times(row: pd.Series | dict, fallback_minutes: int = 8 * 60) -> tuple[str, str]:
    start_minutes = parse_clock_to_minutes(row.get("Beginn", ""))
    end_minutes = parse_clock_to_minutes(row.get("Ende", ""))
    if start_minutes is not None and end_minutes is not None:
        return format_minutes_as_clock(start_minutes), format_minutes_as_clock(end_minutes)
    parsed_name = parse_shift_time_range(row.get("Name", ""))
    if parsed_name is not None:
        start_hour, end_absolute = parsed_name
        return format_minutes_as_clock(start_hour * 60), format_minutes_as_clock(end_absolute * 60)
    start_minutes = 8 * 60
    duration_minutes = max(60, int(float(row.get("Stunden", fallback_minutes / 60) or (fallback_minutes / 60)) * 60))
    end_minutes = start_minutes + duration_minutes
    return format_minutes_as_clock(start_minutes), format_minutes_as_clock(end_minutes)


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
        start_text, end_text = derive_shift_times(row)
        start_minutes = parse_clock_to_minutes(start_text) or 0
        end_minutes = parse_clock_to_minutes(end_text) or 0
        duration_minutes = duration_minutes_between(start_minutes, end_minutes)
        rows.append(
            {
                "Kuerzel": code,
                "Name": name,
                "Beginn": start_text,
                "Ende": end_text,
                "Stunden": round(duration_minutes / 60, 2),
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


def shift_minutes(shift_df: pd.DataFrame) -> dict[str, int]:
    cleaned = shift_definitions_from_editor(shift_df)
    return {
        str(row["Kuerzel"]): duration_minutes_between(
            parse_clock_to_minutes(row["Beginn"]) or 0,
            parse_clock_to_minutes(row["Ende"]) or 0,
        )
        for _, row in cleaned.iterrows()
    }


def shift_hours(shift_df: pd.DataFrame) -> dict[str, float]:
    return {
        code: round(minutes / 60, 2)
        for code, minutes in shift_minutes(shift_df).items()
    }


def effective_shift_minutes_by_pause_policy(
    raw_shift_minutes_by_code: dict[str, int],
    pause_policy: object,
    pause_threshold_hours: object,
    pause_duration_minutes: object,
) -> dict[str, int]:
    policy = normalize_pause_policy(pause_policy)
    if policy != "Pause unbezahlt und von Dienstzeit abziehen":
        return dict(raw_shift_minutes_by_code)
    try:
        threshold_minutes = int(round(max(0.0, float(pause_threshold_hours)) * 60))
    except (TypeError, ValueError):
        threshold_minutes = int(round(DEFAULT_PAUSE_THRESHOLD_HOURS * 60))
    try:
        pause_minutes = int(round(max(0.0, float(pause_duration_minutes))))
    except (TypeError, ValueError):
        pause_minutes = int(DEFAULT_PAUSE_DURATION_MINUTES)
    if pause_minutes <= 0:
        return dict(raw_shift_minutes_by_code)
    return {
        code: max(0, int(minutes) - pause_minutes) if int(minutes) >= threshold_minutes else int(minutes)
        for code, minutes in raw_shift_minutes_by_code.items()
    }


def pause_policy_description(
    pause_policy: object,
    pause_threshold_hours: object,
    pause_duration_minutes: object,
) -> str:
    policy = normalize_pause_policy(pause_policy)
    if policy == "Pause unbezahlt und von Dienstzeit abziehen":
        try:
            duration_minutes = int(round(float(pause_duration_minutes)))
        except (TypeError, ValueError):
            duration_minutes = DEFAULT_PAUSE_DURATION_MINUTES
        return (
            f"{policy}, ab {format_display_hours(pause_threshold_hours)} h "
            f"{duration_minutes} min"
        )
    return policy


def parse_shift_time_range(value: object) -> tuple[int, int] | None:
    match = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})", str(value or ""))
    if not match:
        return None
    start_hour = int(match.group(1))
    end_hour = int(match.group(2))
    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
        return None
    end_absolute = end_hour if end_hour > start_hour else end_hour + 24
    return start_hour, end_absolute


def shift_time_windows(shift_df: pd.DataFrame) -> dict[str, tuple[int, int]]:
    cleaned = shift_definitions_from_editor(shift_df)
    windows = {}
    for _, row in cleaned.iterrows():
        start_minutes = parse_clock_to_minutes(row.get("Beginn", ""))
        end_minutes = parse_clock_to_minutes(row.get("Ende", ""))
        if start_minutes is not None and end_minutes is not None:
            windows[str(row["Kuerzel"])] = (start_minutes, start_minutes + duration_minutes_between(start_minutes, end_minutes))
    return windows


def has_required_rest_between(
    previous_shift: str,
    next_shift: str,
    shift_time_by_code: dict[str, tuple[int, int]],
    required_hours: int = 11,
) -> bool:
    previous_window = shift_time_by_code.get(previous_shift)
    next_window = shift_time_by_code.get(next_shift)
    if previous_window is None or next_window is None:
        return True
    _previous_start, previous_end = previous_window
    next_start, _next_end = next_window
    rest_minutes = (24 * 60 + next_start) - previous_end
    return rest_minutes >= required_hours * 60


def legal_profile_defaults(profile: object) -> dict[str, object]:
    normalized = str(profile or DEFAULT_LEGAL_PROFILE).strip()
    if normalized not in LEGAL_PROFILE_OPTIONS:
        normalized = DEFAULT_LEGAL_PROFILE
    defaults = {
        "legal_profile": normalized,
        "daily_max_hours": 12.0,
        "weekly_average_max_hours": 48.0,
        "weekly_average_period_weeks": 17,
        "weekly_rest_hours": 36.0,
        "reduced_weekly_rest_hours": 24.0,
        "allow_reduced_weekly_rest": False,
        "pause_after_hours": DEFAULT_PAUSE_THRESHOLD_HOURS,
        "pause_minutes": DEFAULT_PAUSE_DURATION_MINUTES,
    }
    if normalized == "Schichtbetrieb Österreich":
        defaults["allow_reduced_weekly_rest"] = True
    elif normalized == "KA-AZG / Krankenanstalt":
        defaults["daily_max_hours"] = 13.0
        defaults["allow_reduced_weekly_rest"] = True
    elif normalized == "KV/Betriebsvereinbarung":
        defaults["allow_reduced_weekly_rest"] = True
        defaults["weekly_average_period_weeks"] = 26
    return defaults


def normalize_legal_profile(value: object) -> str:
    text = str(value or DEFAULT_LEGAL_PROFILE).strip()
    legacy = {
        "Schicht": "Schichtbetrieb Österreich",
        "KA-AZG": "KA-AZG / Krankenanstalt",
        "Krankenanstalt": "KA-AZG / Krankenanstalt",
        "KV": "KV/Betriebsvereinbarung",
    }
    text = legacy.get(text, text)
    return text if text in LEGAL_PROFILE_OPTIONS else DEFAULT_LEGAL_PROFILE


def rest_minutes_over_free_day(
    previous_shift: str,
    next_shift: str,
    shift_time_by_code: dict[str, tuple[int, int]],
) -> int | None:
    previous_window = shift_time_by_code.get(previous_shift)
    next_window = shift_time_by_code.get(next_shift)
    if previous_window is None or next_window is None:
        return None
    _previous_start, previous_end = previous_window
    next_start, _next_end = next_window
    return (2 * 24 * 60 + next_start) - previous_end


def assignment_work_intervals(
    assignments: list[str],
    days: list[date],
    shift_time_by_code: dict[str, tuple[int, int]],
    *,
    previous_assignments: list[str] | None = None,
) -> list[tuple[datetime, datetime]]:
    intervals: list[tuple[datetime, datetime]] = []
    previous_assignments = previous_assignments or []
    if days:
        first_day = days[0]
        for offset, assignment in enumerate(reversed(previous_assignments[-21:]), start=1):
            shift = first_real_shift(assignment)
            window = shift_time_by_code.get(shift)
            if window is None:
                continue
            start_minutes, end_minutes = window
            work_day = first_day - timedelta(days=offset)
            start_dt = datetime.combine(work_day, dt_time()) + timedelta(minutes=start_minutes)
            end_dt = datetime.combine(work_day, dt_time()) + timedelta(minutes=end_minutes)
            intervals.append((start_dt, end_dt))
    for day_index, assignment in enumerate(assignments):
        if day_index >= len(days):
            continue
        shift = first_real_shift(assignment)
        window = shift_time_by_code.get(shift)
        if window is None:
            continue
        start_minutes, end_minutes = window
        start_dt = datetime.combine(days[day_index], dt_time()) + timedelta(minutes=start_minutes)
        end_dt = datetime.combine(days[day_index], dt_time()) + timedelta(minutes=end_minutes)
        intervals.append((start_dt, end_dt))
    return sorted(intervals)


def max_free_minutes_in_window(
    intervals: list[tuple[datetime, datetime]],
    window_start: datetime,
    window_end: datetime,
) -> int:
    relevant = sorted(
        (
            max(start, window_start),
            min(end, window_end),
        )
        for start, end in intervals
        if end > window_start and start < window_end
    )
    cursor = window_start
    max_gap = 0
    for start, end in relevant:
        if start > cursor:
            max_gap = max(max_gap, int((start - cursor).total_seconds() // 60))
        if end > cursor:
            cursor = end
    if cursor < window_end:
        max_gap = max(max_gap, int((window_end - cursor).total_seconds() // 60))
    return max_gap


def iso_week_start(current_day: date) -> date:
    return current_day - timedelta(days=current_day.weekday())

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


def apply_global_plan_scope(
    daily_requirements: dict[tuple[int, str], int],
    days: list[date],
    shifts: list[str],
    night_shifts: list[str],
    holidays: dict[date, str],
    include_nights: bool,
    include_weekends: bool,
) -> dict[tuple[int, str], int]:
    updated_requirements = dict(daily_requirements)
    for day_index, current_day in enumerate(days):
        if not include_weekends and (current_day.weekday() >= 5 or current_day in holidays):
            for shift in shifts:
                updated_requirements[(day_index, shift)] = 0
        if not include_nights:
            for shift in night_shifts:
                updated_requirements[(day_index, shift)] = 0
    return updated_requirements


def plan_month_key(year: int, month: int) -> str:
    return f"{int(year)}-{int(month):02d}"


def month_sequence_number(year: int, month: int) -> int:
    return int(year) * 12 + int(month)


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    position = month_sequence_number(year, month) - 1 + int(delta)
    return position // 12, position % 12 + 1


def previous_plan_month_key(year: int, month: int) -> str:
    if month == 1:
        return plan_month_key(year - 1, 12)
    return plan_month_key(year, month - 1)


def next_open_plan_month(saved_plans: dict, start_year: int, start_month: int) -> tuple[int, int]:
    year = int(start_year)
    month = int(start_month)
    guard = 0
    while plan_month_key(year, month) in (saved_plans or {}) and guard < 180:
        year, month = shift_month(year, month, 1)
        guard += 1
    return year, month


def can_generate_month(
    saved_plans: dict,
    year: int,
    month: int,
    start_year: int,
    start_month: int,
) -> tuple[bool, str]:
    selected_position = month_sequence_number(year, month)
    start_position = month_sequence_number(start_year, start_month)
    if selected_position < start_position:
        return False, "Dieser Monat liegt vor dem eingestellten Planungsstart."
    if selected_position == start_position:
        return True, "Startmonat: kann ohne fixierten Vormonat generiert werden."
    previous_key = previous_plan_month_key(year, month)
    if previous_key not in saved_plans:
        previous_year, previous_month = previous_key.split("-")
        return (
            False,
            f"Bitte zuerst {MONTH_NAMES[int(previous_month)]} {previous_year} speichern und fixieren.",
        )
    return True, "Der Vormonat ist fixiert."


def load_saved_schedules() -> dict:
    if not SAVED_SCHEDULES_FILE.exists():
        return {}
    try:
        data = json.loads(SAVED_SCHEDULES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data.get("plans", {}) if isinstance(data.get("plans", {}), dict) else {}


def save_saved_schedules(plans: dict) -> None:
    payload = {"plans": plans}
    SAVED_SCHEDULES_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def first_real_shift(value: object) -> str:
    text = str(value or "-").strip()
    if not text or text == "-":
        return "-"
    first_part = text.split()[0]
    if first_part.startswith("ER"):
        return "-"
    return first_part


def is_night_assignment(value: object, night_shifts: list[str]) -> bool:
    return first_real_shift(value) in set(night_shifts)


def takeover_service_label(value: object) -> str:
    text = str(value or "").strip()
    if text in TAKEOVER_PREVIOUS_SERVICE_OPTIONS:
        return text
    lowered = text.lower()
    if "nacht" in lowered:
        return "Nachtdienst"
    if "tag" in lowered or "dienst" in lowered:
        return "Tagdienst"
    return "Frei"


def takeover_assignment_code(
    service_label: object,
    day_shifts: list[str],
    night_shifts: list[str],
) -> str:
    normalized = takeover_service_label(service_label)
    if normalized == "Nachtdienst":
        return night_shifts[0] if night_shifts else "-"
    if normalized == "Tagdienst":
        return day_shifts[0] if day_shifts else "-"
    return "-"


def trailing_workday_count(assignments: list[str]) -> int:
    count = 0
    for assignment in reversed(assignments or []):
        if first_real_shift(assignment) == "-":
            break
        count += 1
    return count


def confirmed_takeover_previous_assignments(
    employees_df: pd.DataFrame,
    year: int,
    month: int,
    shifts: list[str],
    night_shifts: list[str],
) -> dict[str, list[str]]:
    if employees_df is None or employees_df.empty:
        return {}
    day_shifts = [shift for shift in shifts if shift not in set(night_shifts)]
    month_start = date(int(year), int(month), 1)
    result: dict[str, list[str]] = {}
    for _, row in employees_df.fillna("").iterrows():
        if not parse_bool_value(row.get("Übernahme bestätigt", False), False):
            continue
        employee_name = str(row.get("Name", "")).strip()
        if not employee_name:
            continue
        takeover_start = parse_date_value(
            row.get("Übernahme Startdatum", month_start.isoformat()),
            month_start,
        )
        if takeover_start.year != int(year) or takeover_start.month != int(month):
            continue
        previous_day = takeover_assignment_code(
            row.get("Übernahme Vortag", "Frei"),
            day_shifts,
            night_shifts,
        )
        second_previous_day = takeover_assignment_code(
            row.get("Übernahme Vor-Vortag", "Frei"),
            day_shifts,
            night_shifts,
        )
        previous_work_streak = max(0, int(parse_hour_value(row.get("Übernahme Arbeitstage in Folge", 0), 0)))
        assignments = [second_previous_day, previous_day]
        explicit_trailing_count = trailing_workday_count(assignments)
        if previous_day != "-" and previous_work_streak > explicit_trailing_count:
            fill_code = second_previous_day if second_previous_day != "-" else previous_day
            assignments = [fill_code] * (previous_work_streak - explicit_trailing_count) + assignments
        result[employee_name] = assignments
    return result


def previous_assignments_for_generation(
    saved_plans: dict,
    employees_df: pd.DataFrame,
    year: int,
    month: int,
    start_year: int,
    start_month: int,
    shifts: list[str],
    night_shifts: list[str],
) -> dict[str, list[str]]:
    saved_assignments = saved_previous_assignments(saved_plans, year, month)
    if saved_assignments:
        return saved_assignments
    if month_sequence_number(year, month) != month_sequence_number(start_year, start_month):
        return {}
    return confirmed_takeover_previous_assignments(employees_df, year, month, shifts, night_shifts)


def saved_previous_assignments(
    saved_plans: dict,
    year: int,
    month: int,
) -> dict[str, list[str]]:
    previous_plan = saved_plans.get(previous_plan_month_key(year, month), {})
    schedule = previous_plan.get("schedule", {}) if isinstance(previous_plan, dict) else {}
    if not isinstance(schedule, dict):
        return {}
    return {
        str(employee_name): list(assignments)
        for employee_name, assignments in schedule.items()
        if isinstance(assignments, list)
    }


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


def normalize_night_priority_value(max_nights_per_month: int, likes_nights: bool, priority: object) -> int:
    current_priority = priority_value(priority)
    if max_nights_per_month > 0 and not likes_nights and current_priority <= 2:
        return 3
    return current_priority


def priority_weight(value: object) -> int:
    return PRIORITY_WEIGHTS[priority_value(value)]


def normalize_plan_optimization_mode(value: object) -> str:
    text = str(value or "").strip()
    legacy = {
        "Fair": "Ausgewogen",
        "Fair verteilt": "Ausgewogen",
        "Zufriedenheit": "Zufriedenheit zuerst",
        "Satisfaction": "Zufriedenheit zuerst",
        "Coverage": "Abdeckung zuerst",
        "Dienste zuerst": "Abdeckung zuerst",
    }
    text = legacy.get(text, text)
    if text not in PLAN_OPTIMIZATION_MODES:
        return DEFAULT_PLAN_OPTIMIZATION_MODE
    return text


def normalize_calculation_mode(value: object) -> str:
    text = str(value or "").strip()
    legacy = {
        "Aktuell": "Aktuelle Berechnung",
        "Variantenvergleich": "Aktuelle Berechnung",
        "Strategisch": "Aktuelle Berechnung",
        "Hierarchisch": "Aktuelle Berechnung",
        "Test: strategisch hierarchisch": "Aktuelle Berechnung",
    }
    text = legacy.get(text, text)
    return DEFAULT_CALCULATION_MODE if text != DEFAULT_CALCULATION_MODE else text


def optimization_profile(value: object) -> dict[str, int]:
    profile_name = str(value or DEFAULT_PLAN_OPTIMIZATION_MODE).strip()
    profiles = {
        "Abdeckung zuerst": {
            "coverage_factor_percent": 120,
            "min_satisfaction_weight": 2,
            "avg_satisfaction_weight": 1,
            "hour_weight_percent": 115,
            "max_hour_deviation_weight": 1900,
            "weekend_block_weight": 1,
            "replacement_rest_weight": 1,
            "night_preference_weight": 1,
            "ranking_open_weight_percent": 120,
            "ranking_min_satisfaction_weight": 45,
            "ranking_warning_weight": 460,
            "ranking_hour_weight": 35,
        },
        "Ausgewogen": {
            "coverage_factor_percent": 90,
            "min_satisfaction_weight": 10,
            "avg_satisfaction_weight": 1,
            "hour_weight_percent": 80,
            "max_hour_deviation_weight": 900,
            "weekend_block_weight": 2,
            "replacement_rest_weight": 2,
            "night_preference_weight": 1,
            "ranking_open_weight_percent": 65,
            "ranking_min_satisfaction_weight": 110,
            "ranking_warning_weight": 360,
            "ranking_hour_weight": 25,
        },
        "Zufriedenheit zuerst": {
            "coverage_factor_percent": 1,
            "min_satisfaction_weight": 35,
            "avg_satisfaction_weight": 3,
            "hour_weight_percent": 45,
            "max_hour_deviation_weight": 350,
            "weekend_block_weight": 4,
            "replacement_rest_weight": 3,
            "night_preference_weight": 2,
            "ranking_open_weight_percent": 0,
            "ranking_min_satisfaction_weight": 260,
            "ranking_warning_weight": 520,
            "ranking_hour_weight": 15,
        },
        "Wunschfrei schützen": {
            "coverage_factor_percent": 1,
            "min_satisfaction_weight": 45,
            "avg_satisfaction_weight": 3,
            "hour_weight_percent": 35,
            "max_hour_deviation_weight": 320,
            "weekend_block_weight": 5,
            "replacement_rest_weight": 4,
            "night_preference_weight": 2,
            "ranking_open_weight_percent": 0,
            "ranking_min_satisfaction_weight": 320,
            "ranking_warning_weight": 900,
            "ranking_hour_weight": 10,
        },
        "Warnungen minimieren": {
            "coverage_factor_percent": 2,
            "min_satisfaction_weight": 50,
            "avg_satisfaction_weight": 2,
            "hour_weight_percent": 35,
            "max_hour_deviation_weight": 360,
            "weekend_block_weight": 5,
            "replacement_rest_weight": 4,
            "night_preference_weight": 2,
            "ranking_open_weight_percent": 0,
            "ranking_min_satisfaction_weight": 340,
            "ranking_warning_weight": 1100,
            "ranking_hour_weight": 10,
        },
        "Feiertage robust": {
            "coverage_factor_percent": 6,
            "min_satisfaction_weight": 40,
            "avg_satisfaction_weight": 3,
            "hour_weight_percent": 45,
            "max_hour_deviation_weight": 420,
            "weekend_block_weight": 6,
            "replacement_rest_weight": 6,
            "night_preference_weight": 1,
            "ranking_open_weight_percent": 5,
            "ranking_min_satisfaction_weight": 280,
            "ranking_warning_weight": 780,
            "ranking_hour_weight": 14,
        },
        "Schlechteste Person schützen": {
            "coverage_factor_percent": 1,
            "min_satisfaction_weight": 65,
            "avg_satisfaction_weight": 1,
            "hour_weight_percent": 35,
            "max_hour_deviation_weight": 300,
            "weekend_block_weight": 5,
            "replacement_rest_weight": 4,
            "night_preference_weight": 2,
            "ranking_open_weight_percent": 0,
            "ranking_min_satisfaction_weight": 420,
            "ranking_warning_weight": 850,
            "ranking_hour_weight": 9,
        },
        "Stunden sanft glätten": {
            "coverage_factor_percent": 3,
            "min_satisfaction_weight": 34,
            "avg_satisfaction_weight": 3,
            "hour_weight_percent": 62,
            "max_hour_deviation_weight": 520,
            "weekend_block_weight": 4,
            "replacement_rest_weight": 4,
            "night_preference_weight": 2,
            "ranking_open_weight_percent": 0,
            "ranking_min_satisfaction_weight": 260,
            "ranking_warning_weight": 760,
            "ranking_hour_weight": 22,
        },
        "Wochenenden schützen": {
            "coverage_factor_percent": 5,
            "min_satisfaction_weight": 32,
            "avg_satisfaction_weight": 3,
            "hour_weight_percent": 50,
            "max_hour_deviation_weight": 420,
            "weekend_block_weight": 6,
            "replacement_rest_weight": 3,
            "night_preference_weight": 1,
            "ranking_open_weight_percent": 0,
            "ranking_min_satisfaction_weight": 240,
            "ranking_warning_weight": 90,
            "ranking_hour_weight": 16,
        },
        "Stunden fair": {
            "coverage_factor_percent": 95,
            "min_satisfaction_weight": 9,
            "avg_satisfaction_weight": 1,
            "hour_weight_percent": 130,
            "max_hour_deviation_weight": 1700,
            "weekend_block_weight": 2,
            "replacement_rest_weight": 2,
            "night_preference_weight": 1,
            "ranking_open_weight_percent": 85,
            "ranking_min_satisfaction_weight": 100,
            "ranking_warning_weight": 350,
            "ranking_hour_weight": 38,
        },
        "Nachtwünsche": {
            "coverage_factor_percent": 85,
            "min_satisfaction_weight": 12,
            "avg_satisfaction_weight": 2,
            "hour_weight_percent": 65,
            "max_hour_deviation_weight": 600,
            "weekend_block_weight": 2,
            "replacement_rest_weight": 2,
            "night_preference_weight": 3,
            "ranking_open_weight_percent": 60,
            "ranking_min_satisfaction_weight": 130,
            "ranking_warning_weight": 330,
            "ranking_hour_weight": 22,
        },
    }
    return dict(profiles.get(profile_name, profiles[DEFAULT_PLAN_OPTIMIZATION_MODE]))


def holiday_pressure_level(days: list[date] | None, holidays: dict[date, str] | None) -> int:
    if not days:
        return 0
    holiday_set = set((holidays or {}).keys())
    return sum(1 for current_day in days if current_day.weekday() == 6 or current_day in holiday_set)


def generation_variant_profiles(
    selected_mode: object,
    days: list[date] | None = None,
    holidays: dict[date, str] | None = None,
) -> list[tuple[str, str, int]]:
    mode = normalize_plan_optimization_mode(selected_mode)
    holiday_heavy = holiday_pressure_level(days, holidays) >= 6
    variants = [
        ("Abdeckung prüfen", "Abdeckung zuerst", 0),
        ("Gewichtet ausgleichen", "Ausgewogen", 11),
        ("Zufriedenheit erhöhen", "Zufriedenheit zuerst", 29),
        ("Wochenenden schützen", "Wochenenden schützen", 47),
        ("Stunden fair verteilen", "Stunden fair", 61),
        ("Zufriedenheit stabilisieren", "Zufriedenheit zuerst", 83),
        ("Wünsche stärker schützen", "Zufriedenheit zuerst", 107),
        ("Wochenenden feinjustieren", "Wochenenden schützen", 131),
        ("Wunschfrei absichern", "Wunschfrei schützen", 157),
        ("Warnungen bremsen", "Warnungen minimieren", 181),
        ("Schlechteste Person anheben", "Schlechteste Person schützen", 211),
        ("Stunden sanft glätten", "Stunden sanft glätten", 241),
        ("Feiertage robust behandeln", "Feiertage robust", 271),
    ]
    if mode == "Abdeckung zuerst":
        return [variants[0], variants[1], variants[4], variants[9]]
    if mode == "Zufriedenheit zuerst":
        selected = [
            variants[2],
            variants[8],
            variants[9],
            variants[10],
            variants[5],
            variants[6],
            variants[3],
            variants[7],
            variants[11],
            variants[1],
        ]
        if holiday_heavy:
            selected.insert(4, variants[12])
        return selected
    selected = [variants[1], variants[2], variants[8], variants[9], variants[5], variants[4], variants[3], variants[11]]
    if holiday_heavy:
        selected.insert(3, variants[12])
    return selected


def plan_improvement_profiles(
    selected_mode: object,
    *,
    holiday_heavy: bool = False,
) -> list[tuple[str, str, int, int]]:
    mode = normalize_plan_optimization_mode(selected_mode)
    profiles = [
        ("Zufriedenheit vertiefen", "Zufriedenheit zuerst", 907, 70),
        ("Warnungen reduzieren", "Warnungen minimieren", 941, 65),
        ("Schlechteste Person verbessern", "Schlechteste Person schützen", 977, 65),
        ("Stunden fairer glätten", "Stunden sanft glätten", 1009, 55),
        ("Wunschfrei absichern", "Wunschfrei schützen", 1049, 55),
        ("Wochenenden verbessern", "Wochenenden schützen", 1091, 55),
        ("Nachtwünsche nachziehen", "Nachtwünsche", 1129, 50),
    ]
    if mode == "Abdeckung zuerst":
        profiles = [
            ("Abdeckung stabilisieren", "Abdeckung zuerst", 887, 55),
            *profiles[:4],
        ]
    if holiday_heavy:
        profiles.append(("Feiertage robuster verteilen", "Feiertage robust", 1171, 65))
    return profiles


def allowed_shortage_penalty_for_mode(mode: object, best_shortage_penalty: int) -> int | None:
    normalized_mode = normalize_plan_optimization_mode(mode)
    if normalized_mode == "Abdeckung zuerst":
        return int(best_shortage_penalty)
    if normalized_mode == "Zufriedenheit zuerst":
        return int(best_shortage_penalty + 3_500_000)
    return int(best_shortage_penalty + 700_000)


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


def format_day_ranges(value: object) -> str:
    days = [day + 1 for day in parse_blocked_days(value)]
    if not days:
        return "-"
    ranges = []
    start = previous = days[0]
    for day in days[1:]:
        if day == previous + 1:
            previous = day
            continue
        ranges.append(f"{start}" if start == previous else f"{start}-{previous}")
        start = previous = day
    ranges.append(f"{start}" if start == previous else f"{start}-{previous}")
    return ", ".join(ranges)

def priority_short_label(value: object) -> str:
    priority = priority_value(value)
    labels = {
        1: "1 Muss",
        2: "2 sehr wichtig",
        3: "3 wenn möglich",
        4: "4 locker",
        5: "5 fair",
    }
    return labels.get(priority, "3 wenn möglich")


def employee_hint_list(employee: Employee) -> list[str]:
    hints = []
    if not employee.participates_in_schedule:
        hints.append("nicht dienstplanrelevant")
    if employee.weekly_hours_target > employee.max_weekly_planned_hours:
        hints.append("Wochenstunden über Max.")
    if employee.max_nights_per_month > 0 and not employee.likes_nights and employee.night_priority <= 2:
        hints.append("Nächte erlaubt, aber Nachtwunsch stark dagegen")
    if employee.weekly_hours_target <= 1 and "nicht dienstplanrelevant" not in employee.qualification.lower():
        hints.append("sehr niedrige Stunden")
    if len(employee.blocked_days) + len(employee.planned_sick_days) + len(employee.vacation_days) >= 20:
        hints.append("viele Sperrtage")
    has_takeover_values = (
        abs(employee.takeover_vacation_hours) > 0
        or abs(employee.takeover_time_balance_hours) > 0
        or abs(employee.takeover_replacement_rest_hours) > 0
        or employee.takeover_previous_day_service != "Frei"
        or employee.takeover_second_previous_day_service != "Frei"
        or employee.takeover_previous_work_streak > 0
    )
    if has_takeover_values and not employee.takeover_confirmed:
        hints.append("Übernahme nicht bestätigt")
    return hints


def employee_remaining_vacation_hours(employee: Employee) -> float:
    year = int(st.session_state.get("selected_year", date.today().year))
    month = int(st.session_state.get("selected_month", date.today().month))
    period_start, period_end = vacation_period_for_month(employee, year, month)
    employee_row = {
        "Urlaub je Monat": serialize_monthly_day_map(
            {plan_month_key(year, month): format_day_number_list(employee.vacation_days)}
        ),
        "Urlaubs-Stichtag": employee.vacation_start_date,
    }
    fixed_vacation_df = fixed_vacation_usage_dataframe(
        employee.name,
        employee_row,
        st.session_state.get("saved_schedules", {}),
        period_start,
        period_end,
    )
    fixed_hours = (
        sum(parse_hour_value(row.get("Fixiert verbraucht h", 0), 0) for _, row in fixed_vacation_df.iterrows())
        if not fixed_vacation_df.empty
        else 0
    )
    current_month_key = plan_month_key(year, month)
    current_month_fixed = current_month_key in st.session_state.get("saved_schedules", {})
    pending_hours = 0
    current_month_days = st.session_state.get("current_month_days", [])
    if not current_month_fixed and current_month_days:
        pending_hours = format_minutes_as_hours(vacation_paid_minutes_for_month(employee, current_month_days, True))
    vacation_base_hours = (
        employee.takeover_vacation_hours
        if employee.takeover_confirmed
        else vacation_entitlement_hours(employee)
    )
    return max(0.0, round(vacation_base_hours - fixed_hours - pending_hours, 2))


def employee_compact_dataframe(
    employees: list[Employee],
    visible_indices: list[int] | None = None,
) -> pd.DataFrame:
    selected_indices = visible_indices if visible_indices is not None else list(range(len(employees)))
    rows = []
    for original_index in selected_indices:
        if original_index < 0 or original_index >= len(employees):
            continue
        employee = employees[original_index]
        hints = employee_hint_list(employee)
        rows.append(
            {
                "Nr": original_index + 1,
                "MitarbeiterIn": employee.name,
                "Status": "aktiv" if employee.participates_in_schedule else "ausgeschlossen",
                "Wochenstunden": format_display_hours(employee.weekly_hours_target),
                "Nacht": (
                    f"gern, max. {employee.max_nights_per_month}"
                    if employee.likes_nights
                    else f"nein, max. {employee.max_nights_per_month}"
                ),
                "Wochenende": (
                    f"frei ({priority_short_label(employee.weekend_priority)})"
                    if employee.prefers_weekends_off
                    else "flexibel"
                ),
                "Wunschfrei": format_day_ranges(", ".join(str(day + 1) for day in employee.blocked_days)),
                "Krankenstand": format_day_ranges(", ".join(str(day + 1) for day in employee.planned_sick_days)),
                "Urlaub": format_day_ranges(", ".join(str(day + 1) for day in employee.vacation_days)),
                "Resturlaub h": format_display_hours(employee_remaining_vacation_hours(employee)),
                "Hinweise": "; ".join(hints) if hints else "OK",
                "Aktion": "unten auswählen",
            }
        )
    return pd.DataFrame(rows)


def calendar_day_checkbox_grid(
    title: str,
    month_days: list[date],
    selected_day_numbers: set[int],
    key_prefix: str,
) -> list[int]:
    if not month_days:
        return []

    st.markdown(f"**{title}**")
    st.caption("Kalendertage anklicken. Wochenenden sind rechts angeordnet.")
    header_cols = st.columns(7)
    for weekday_index, weekday_name in enumerate(WEEKDAY_NAMES):
        with header_cols[weekday_index]:
            st.markdown(f"**{weekday_name}**")

    month = month_days[0].month
    year = month_days[0].year
    calendar_weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    selected = []
    for week in calendar_weeks:
        cols = st.columns(7)
        for offset, current_day in enumerate(week):
            with cols[offset]:
                if current_day.month != month:
                    st.markdown("&nbsp;", unsafe_allow_html=True)
                    continue
                label = str(current_day.day)
                if st.checkbox(
                    label,
                    value=current_day.day in selected_day_numbers,
                    key=f"{key_prefix}_{current_day.day}",
                    help=f"{current_day.day}. {MONTH_NAMES[current_day.month]} {current_day.year}",
                ):
                    selected.append(current_day.day)
    return sorted(selected)


def display_employee_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    display_df = normalize_employee_dataframe(df).copy()
    for column in [
        "Wochenstunden",
        "Max. Wochenstunden",
        "Urlaubswochen/Jahr",
        "Urlaubstage/Jahr",
        "Urlaubstag h",
        "Übernahme Resturlaub h",
        "Übernahme Zeitkonto h",
        "Übernahme Ersatzruhe h",
    ]:
        display_df[column] = display_df[column].map(format_hour_value)
    for column in ["Wunschfrei-Tage", "Krankenstand-Tage", "Urlaub-Tage"]:
        display_df[column] = display_df[column].map(format_day_ranges)
    for column in [
        "Dienstplanrelevant",
        "Gerne Nacht",
        "Nur Doppelnaechte",
        "3 Naechte erlaubt",
        "Wochenende frei",
        "Übernahme bestätigt",
    ]:
        display_df[column] = display_df[column].map(lambda value: "Ja" if parse_bool_value(value) else "Nein")
    if "Gemeinsame Wochenenden" in display_df.columns:
        display_df["Gemeinsame Wochenenden"] = display_df["Gemeinsame Wochenenden"].map(lambda value: "Ja" if bool(value) else "Nein")
    for column in [
        "Prio Nacht",
        "Prio Doppelnaechte",
        "Prio frei nach Nacht",
        "Prio Wochenende",
        "Prio gemeinsame Wochenenden",
        "Prio Wunschfrei",
    ]:
        if column in display_df.columns:
            display_df[column] = display_df[column].map(priority_value)
    display_df = display_df.rename(
        columns={
            "Gemeinsame Wochenenden": "Wochenende nicht teilen",
            "Prio gemeinsame Wochenenden": "Prio Wochenende nicht teilen",
        }
    )
    display_df = display_df.drop(
        columns=["Wunschfrei je Monat", "Krankenstand je Monat", "Urlaub je Monat"],
        errors="ignore",
    )
    return display_df


def display_shift_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    display_df = shift_definitions_from_editor(df).copy()
    display_df["Nacht"] = display_df["Nacht"].map(lambda value: "Ja" if bool(value) else "Nein")
    display_df["Beginn"] = display_df["Beginn"].map(lambda value: str(value).replace(":", str(st.session_state.get("time_separator", ":"))))
    display_df["Ende"] = display_df["Ende"].map(lambda value: str(value).replace(":", str(st.session_state.get("time_separator", ":"))))
    display_df["Stunden"] = display_df["Stunden"].map(lambda value: f"{float(value):.2f}")
    display_df["Stunden"] = display_df["Stunden"].map(format_hour_value)
    display_df["Farbe"] = display_df["Farbe"].map(color_swatch)
    return display_df


def render_static_table(df: pd.DataFrame, height_limit: int | None = None) -> None:
    table_df = germanize_dataframe(df.copy()).fillna("")
    html = table_df.to_html(index=False, escape=False)
    max_height = f"max-height:{height_limit}px; overflow:auto;" if height_limit else ""
    st.markdown(
        f"""
        <div class="static-table-wrap" style="{max_height}">
            {html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def replace_display_text(value: object, replacements: dict[str, str]) -> object:
    if not isinstance(value, str):
        return value
    text = value
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def germanize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    replacements = {
        "Naechte": "Nächte",
        "Doppelnaechte": "Doppelnächte",
        "Wuensche": "Wünsche",
        "Erfuellte": "Erfüllte",
        "Prioritaet": "Priorität",
        "Kuerzel": "Kürzel",
        "Verstoss": "Verstoß",
        "moeglich": "möglich",
        "Ueberstunden": "Überstunden",
        "ueberschritten": "überschritten",
        "zaehlt": "zählt",
        "Benoetigte": "Benötigte",
        "fuer": "für",
        "Waehle": "Wähle",
        "gueltig": "gültig",
        "hinzufuegen": "hinzufügen",
        "auswaehlen": "auswählen",
    }
    renamed = {}
    for column in df.columns:
        new_column = str(column)
        for old, new in replacements.items():
            new_column = new_column.replace(old, new)
        renamed[column] = new_column
    display_df = df.rename(columns=renamed)
    hour_columns = {
        "Soll h",
        "Ist h",
        "+/- h",
        "Sollstunden",
        "Geplante Stunden",
        "Plus/Minus Stunden",
        "Stundenabweichung h",
        "Ersatzruhe-Stunden",
        "Ersatzruhe-offen-Stunden",
        "Ersatzruhe-offen gesamt h",
        "Urlaub-Startsaldo h",
        "Urlaub-Rest h",
        "Start-Zeitkonto h",
        "Zeitkonto nach Plan h",
        "Zusatz h",
        "Monats +/- aktuell h",
        "Monats +/- nach Einsatz h",
        "Zeitkonto gesamt aktuell h",
        "Zeitkonto gesamt nach Einsatz h",
        "Start-Ersatzruhe h",
    }
    for column in display_df.columns:
        if str(column) in hour_columns:
            display_df[column] = display_df[column].map(format_display_hours)
        elif display_df[column].dtype == "object":
            display_df[column] = display_df[column].map(
                lambda value: replace_display_text(value, replacements)
            )
    return display_df


def solve_schedule(
    employees: list[Employee],
    days: list[date],
    shifts: list[str],
    night_shifts: list[str],
    daily_requirements: dict[tuple[int, str], int] | None = None,
    holidays: dict[date, str] | None = None,
    shift_priority_by_code: dict[str, int] | None = None,
    shift_minutes_by_code: dict[str, int] | None = None,
    previous_assignments: dict[str, list[str]] | None = None,
    max_overtime_percent: int = 10,
    max_overtime_hours: int = 12,
    max_undertime_percent: int = 10,
    max_undertime_hours: int = 12,
    open_shift_codes: list[str] | None = None,
    replacement_rest_scope: str = DEFAULT_REPLACEMENT_REST_SCOPE,
    compensatory_rest_counts_as_hours: bool = True,
    vacation_counts_as_hours: bool = True,
    vacation_weekend_policy: str = DEFAULT_VACATION_WEEKEND_POLICY,
    shift_time_by_code: dict[str, tuple[int, int]] | None = None,
    block_night_before_wish_free: bool = True,
    daily_max_work_hours: float = 12.0,
    weekly_rest_hours: float = 36.0,
    reduced_weekly_rest_hours: float = 24.0,
    allow_reduced_weekly_rest: bool = True,
    night_credit_mode: str = DEFAULT_NIGHT_CREDIT_MODE,
    night_credit_hours: float = DEFAULT_NIGHT_CREDIT_HOURS,
    time_account_usage: str = DEFAULT_TIME_ACCOUNT_USAGE,
    plan_strategy: str = DEFAULT_PLAN_OPTIMIZATION_MODE,
    max_time_seconds: int = 120,
    optimize_for_fairness: bool = True,
    random_seed: int = 7,
    deterministic_search: bool = True,
    max_shortage_penalty: int | None = None,
    assignment_hint: dict[str, list[str]] | None = None,
) -> tuple[str, dict, dict]:
    model = cp_model.CpModel()
    employee_count = len(employees)
    day_count = len(days)
    holidays = holidays or {}
    if daily_requirements is None:
        daily_requirements = {(d, shift): 1 for d in range(day_count) for shift in shifts}
    shift_priority_by_code = shift_priority_by_code or {shift: 1 for shift in shifts}
    shift_minutes_by_code = shift_minutes_by_code or {shift: 8 * 60 for shift in shifts}
    shift_time_by_code = shift_time_by_code or {}
    previous_assignments = previous_assignments or {}
    day_shifts = [shift for shift in shifts if shift not in night_shifts]
    open_shift_codes = open_shift_codes or []
    open_shift_set = set(open_shift_codes)
    replacement_rest_scope = normalize_replacement_rest_scope(replacement_rest_scope)
    vacation_weekend_policy = normalize_vacation_weekend_policy(vacation_weekend_policy)
    plan_strategy = str(plan_strategy or DEFAULT_PLAN_OPTIMIZATION_MODE).strip()
    daily_max_minutes = int(round(max(1.0, float(daily_max_work_hours)) * 60))
    weekly_rest_minutes = int(round(max(1.0, float(weekly_rest_hours)) * 60))
    reduced_weekly_rest_minutes = int(round(max(1.0, float(reduced_weekly_rest_hours)) * 60))
    hard_weekly_rest_minutes = reduced_weekly_rest_minutes if allow_reduced_weekly_rest else weekly_rest_minutes
    if plan_strategy not in {
        *PLAN_OPTIMIZATION_MODES,
        "Wochenenden schützen",
        "Stunden fair",
        "Nachtwünsche",
        "Wunschfrei schützen",
        "Warnungen minimieren",
        "Feiertage robust",
        "Schlechteste Person schützen",
        "Stunden sanft glätten",
    }:
        plan_strategy = normalize_plan_optimization_mode(plan_strategy)
    profile = optimization_profile(plan_strategy)
    night_credit_mode = normalize_night_credit_mode(night_credit_mode)
    night_credit_minutes = int(round(max(0.0, float(night_credit_hours)) * 60))
    time_account_weight, time_account_positive_weight = time_account_usage_weight(time_account_usage)
    objective_terms = []
    coverage_objective_terms = []
    shortage_penalty_terms = []
    satisfaction_score_vars = []
    satisfaction_loss_terms_by_employee = [[] for _ in range(employee_count)]

    x = {}
    for e in range(employee_count):
        for d in range(day_count):
            for shift in shifts:
                x[(e, d, shift)] = model.NewBoolVar(f"x_e{e}_d{d}_{shift}")

    if assignment_hint:
        for e, employee in enumerate(employees):
            hinted_row = assignment_hint.get(employee.name, [])
            if not isinstance(hinted_row, list):
                continue
            for d in range(min(day_count, len(hinted_row))):
                hinted_shift = first_real_shift(hinted_row[d])
                for shift in shifts:
                    model.AddHint(x[(e, d, shift)], 1 if hinted_shift == shift else 0)

    # Harte Regel: Jede echte Schicht wird gemaess Ressourcenbedarf besetzt.
    for d in range(day_count):
        for shift in shifts:
            demand = daily_requirements.get((d, shift), 1)
            assigned = sum(x[(e, d, shift)] for e in range(employee_count))
            shift_priority = shift_priority_by_code.get(shift, 1)
            can_remain_open = shift in open_shift_set
            if shift_priority == 1 and not can_remain_open:
                model.Add(assigned == demand)
            else:
                shortage = model.NewIntVar(0, demand, f"shortage_d{d}_{shift}")
                model.Add(assigned + shortage == demand)
                model.Add(assigned <= demand)
                raw_shortage_penalty = shortage_penalty_for_shift(
                    shift,
                    shift_priority,
                    open_shift_codes,
                )
                shortage_penalty = max(
                    1,
                    int(raw_shortage_penalty * profile["coverage_factor_percent"] / 100),
                )
                raw_shortage_penalty_term = shortage * raw_shortage_penalty
                shortage_penalty_term = shortage * shortage_penalty
                shortage_penalty_terms.append(raw_shortage_penalty_term)
                coverage_objective_terms.append(-shortage_penalty_term)
                objective_terms.append(-shortage_penalty_term)

    if max_shortage_penalty is not None and shortage_penalty_terms:
        model.Add(sum(shortage_penalty_terms) <= int(max_shortage_penalty))

    # Harte Regeln je Mitarbeiter.
    for e, employee in enumerate(employees):
        for d in range(day_count):
            model.AddAtMostOne(x[(e, d, shift)] for shift in shifts)

            if d in employee.blocked_days:
                if employee.wish_free_priority == 1:
                    for shift in shifts:
                        model.Add(x[(e, d, shift)] == 0)
                    if block_night_before_wish_free and d > 0:
                        for night_shift in night_shifts:
                            model.Add(x[(e, d - 1, night_shift)] == 0)

            if d in employee.planned_sick_days:
                for shift in shifts:
                    model.Add(x[(e, d, shift)] == 0)

            if d in vacation_protected_day_indices(employee, days, vacation_weekend_policy):
                for shift in shifts:
                    model.Add(x[(e, d, shift)] == 0)

            if d < day_count - 1:
                for current_shift in shifts:
                    for next_shift in shifts:
                        if not has_required_rest_between(current_shift, next_shift, shift_time_by_code):
                            model.Add(x[(e, d, current_shift)] + x[(e, d + 1, next_shift)] <= 1)
                for night_shift in night_shifts:
                    for day_shift in day_shifts:
                        model.Add(x[(e, d, night_shift)] + x[(e, d + 1, day_shift)] <= 1)

        model.Add(
            sum(x[(e, d, shift)] for d in range(day_count) for shift in night_shifts)
            <= employee.max_nights_per_month
        )

        for d in range(day_count):
            for shift in shifts:
                if shift_minutes_by_code.get(shift, 8 * 60) > daily_max_minutes:
                    model.Add(x[(e, d, shift)] == 0)

        if not employee.allow_three_consecutive_nights:
            for d in range(day_count - 2):
                model.Add(
                    sum(
                        x[(e, check_day, night_shift)]
                        for check_day in range(d, d + 3)
                        for night_shift in night_shifts
                    )
                    <= 2
                )

        previous_plan = previous_assignments.get(employee.name, [])
        previous_last_is_night = bool(previous_plan) and is_night_assignment(previous_plan[-1], night_shifts)
        previous_second_last_is_night = (
            len(previous_plan) >= 2 and is_night_assignment(previous_plan[-2], night_shifts)
        )
        if previous_last_is_night:
            for day_shift in day_shifts:
                model.Add(x[(e, 0, day_shift)] == 0)
            if not employee.allow_three_consecutive_nights and day_count >= 2:
                model.Add(
                    sum(x[(e, d, night_shift)] for d in range(2) for night_shift in night_shifts)
                    <= 1
                )
            if employee.rest_after_night == 2 and employee.rest_priority == 1 and day_count >= 1:
                night_on_first_day = sum(x[(e, 0, night_shift)] for night_shift in night_shifts)
                previous_chain_ended_before_month = model.NewBoolVar(f"previous_night_chain_ended_e{e}")
                model.Add(previous_chain_ended_before_month + night_on_first_day == 1)
                for rest_day in (0, 1):
                    if rest_day < day_count:
                        for shift in shifts:
                            model.Add(x[(e, rest_day, shift)] == 0).OnlyEnforceIf(
                                previous_chain_ended_before_month
                            )
        if previous_last_is_night and previous_second_last_is_night and not employee.allow_three_consecutive_nights:
            for night_shift in night_shifts:
                model.Add(x[(e, 0, night_shift)] == 0)
        previous_last_shift = first_real_shift(previous_plan[-1]) if previous_plan else "-"
        if previous_last_shift != "-":
            for shift in shifts:
                if not has_required_rest_between(previous_last_shift, shift, shift_time_by_code):
                    model.Add(x[(e, 0, shift)] == 0)
        previous_work_streak = trailing_workday_count(previous_plan)
        if previous_work_streak > 0:
            remaining_workdays = employee.max_consecutive_workdays - previous_work_streak
            if remaining_workdays <= 0:
                for shift in shifts:
                    model.Add(x[(e, 0, shift)] == 0)
            elif remaining_workdays < day_count:
                model.Add(
                    sum(
                        x[(e, d, shift)]
                        for d in range(0, remaining_workdays + 1)
                        for shift in shifts
                    )
                    <= remaining_workdays
                )

        if not employee.likes_nights and employee.night_priority <= 2:
            for d in range(day_count):
                for night_shift in night_shifts:
                    model.Add(x[(e, d, night_shift)] == 0)

        if "nur nachtdienst" in employee.qualification.lower():
            for d in range(day_count):
                for shift in shifts:
                    if shift not in night_shifts:
                        model.Add(x[(e, d, shift)] == 0)

        if employee.prefers_weekends_off and employee.weekend_priority == 1:
            for d in weekend_indices(days, holidays):
                for shift in shifts:
                    model.Add(x[(e, d, shift)] == 0)

        if employee.rest_after_night == 2 and employee.rest_priority == 1:
            for d in range(day_count):
                night_today = sum(x[(e, d, night_shift)] for night_shift in night_shifts)
                night_tomorrow = (
                    sum(x[(e, d + 1, night_shift)] for night_shift in night_shifts)
                    if d + 1 < day_count
                    else 0
                )
                last_night_in_chain = model.NewBoolVar(f"last_night_chain_e{e}_d{d}")
                model.Add(last_night_in_chain <= night_today)
                if d + 1 < day_count:
                    model.Add(last_night_in_chain <= 1 - night_tomorrow)
                    model.Add(last_night_in_chain >= night_today - night_tomorrow)
                else:
                    model.Add(last_night_in_chain == night_today)
                for rest_day in (d + 1, d + 2):
                    if rest_day < day_count:
                        for shift in shifts:
                            model.Add(x[(e, rest_day, shift)] == 0).OnlyEnforceIf(last_night_in_chain)

        for week_days in calendar_week_day_indices(days):
            max_weekly_minutes = int(round(float(employee.max_weekly_planned_hours) * 60))
            model.Add(
                sum(x[(e, d, shift)] for d in week_days for shift in shifts)
                <= employee.max_shifts_per_week
            )
            model.Add(
                sum(
                    x[(e, d, shift)] * shift_minutes_by_code.get(shift, 8 * 60)
                    for d in week_days
                    for shift in shifts
                )
                <= max_weekly_minutes
            )
            if len(week_days) >= 2:
                required_free_days = 1 if hard_weekly_rest_minutes <= 24 * 60 else 2
                model.Add(
                    sum(x[(e, d, shift)] for d in week_days for shift in shifts)
                    <= max(0, len(week_days) - required_free_days)
                )

        max_workdays = max(1, min(day_count, employee.max_consecutive_workdays))
        for start_day in range(0, day_count - max_workdays):
            model.Add(
                sum(
                    x[(e, d, shift)]
                    for d in range(start_day, start_day + max_workdays + 1)
                    for shift in shifts
                )
                <= max_workdays
            )

    weekend_days = weekend_indices(days, holidays)
    weekend_pairs = saturday_sunday_pairs(days)
    weekend_pair_day_indices = {day_index for pair in weekend_pairs for day_index in pair}
    standalone_weekend_indices = [
        day_index for day_index in weekend_days if day_index not in weekend_pair_day_indices
    ]
    total_weekend_blocks = len(weekend_pairs) + len(standalone_weekend_indices)
    total_weekend_required = sum(
        daily_requirements.get((d, shift), 0) for d in weekend_days for shift in shifts
    )
    average_weekend_shifts = (
        max(1, total_weekend_required // employee_count)
        if total_weekend_required > 0 and employee_count > 0
        else 0
    )
    total_required_minutes = sum(
        daily_requirements.get((d, shift), 0) * shift_minutes_by_code.get(shift, 8 * 60)
        for d in range(day_count)
        for shift in shifts
    )
    if compensatory_rest_counts_as_hours:
        total_required_minutes += sum(
            daily_requirements.get((d, shift), 0) * shift_minutes_by_code.get(shift, 8 * 60)
            for d, current_day in enumerate(days)
            if replacement_rest_applies(current_day, holidays, replacement_rest_scope)
            for shift in shifts
        )
    if vacation_counts_as_hours:
        total_required_minutes += sum(
            vacation_paid_minutes_for_month(employee, days, True)
            for employee in employees
        )
    total_required_nights = sum(
        daily_requirements.get((d, shift), 0)
        for d in range(day_count)
        for shift in night_shifts
    )
    total_weekly_target_minutes = sum(employee.weekly_hours_target * 60 for employee in employees)
    month_factor = day_count / 7

    def night_distribution_weight(employee: Employee) -> float:
        if employee.max_nights_per_month <= 0:
            return 0.0
        if not employee.likes_nights and employee.night_priority <= 2:
            return 0.0
        qualification = employee.qualification.lower()
        if "nur nachtdienst" in qualification:
            return employee.weekly_hours_target * 4.0
        if employee.likes_nights:
            factor_by_priority = {1: 3.8, 2: 3.2, 3: 2.6, 4: 2.0, 5: 1.6}
        else:
            factor_by_priority = {1: 0.0, 2: 0.0, 3: 0.25, 4: 0.45, 5: 0.8}
        return employee.weekly_hours_target * factor_by_priority.get(employee.night_priority, 1.0)

    def weekend_distribution_weight(employee: Employee) -> float:
        if employee.prefers_weekends_off and employee.weekend_priority == 1:
            return 0.0
        if employee.prefers_weekends_off:
            factor_by_priority = {2: 0.35, 3: 0.55, 4: 0.75, 5: 0.95}
            return employee.weekly_hours_target * factor_by_priority.get(employee.weekend_priority, 0.7)
        return employee.weekly_hours_target * 1.15

    eligible_night_weight = sum(night_distribution_weight(employee) for employee in employees)
    eligible_weekend_weight = sum(weekend_distribution_weight(employee) for employee in employees)
    hour_deviations = []
    hour_deviation_bounds = []
    night_deviations = []
    weekend_deviations = []
    weekend_block_deviations = []

    def satisfaction_loss_weight(priority: int, base: int) -> int:
        priority = priority_value(priority)
        return int(base * (6 - priority))

    for e, employee in enumerate(employees):
        night_priority = priority_weight(employee.night_priority)
        double_night_priority = priority_weight(employee.double_night_priority)
        rest_priority = priority_weight(employee.rest_priority)
        weekend_priority = priority_weight(employee.weekend_priority)
        wish_free_priority = priority_weight(employee.wish_free_priority)
        employee_satisfaction_loss_terms = satisfaction_loss_terms_by_employee[e]
        vacation_minutes = vacation_paid_minutes_for_month(employee, days, vacation_counts_as_hours)
        employee_night_shifts = sum(x[(e, d, shift)] for d in range(day_count) for shift in night_shifts)
        total_minutes = vacation_minutes + sum(
            x[(e, d, shift)] * shift_minutes_by_code.get(shift, 8 * 60)
            for d in range(day_count)
            for shift in shifts
        )
        if compensatory_rest_counts_as_hours:
            total_minutes += sum(
                x[(e, d, shift)] * shift_minutes_by_code.get(shift, 8 * 60)
                for d, current_day in enumerate(days)
                if replacement_rest_applies(current_day, holidays, replacement_rest_scope)
                for shift in shifts
            )
        if night_credit_mode == "Nachtgutschrift als Dienststunden" and night_credit_minutes > 0:
            total_minutes += employee_night_shifts * night_credit_minutes
        weekend_shifts = sum(x[(e, d, shift)] for d in weekend_days for shift in shifts)
        weekend_block_vars = []
        for saturday_index, sunday_index in weekend_pairs:
            saturday_work = model.NewBoolVar(f"saturday_work_e{e}_d{saturday_index}")
            sunday_work = model.NewBoolVar(f"sunday_work_e{e}_d{sunday_index}")
            model.Add(saturday_work == sum(x[(e, saturday_index, shift)] for shift in shifts))
            model.Add(sunday_work == sum(x[(e, sunday_index, shift)] for shift in shifts))
            weekend_block = model.NewBoolVar(f"weekend_block_e{e}_d{saturday_index}")
            model.AddMaxEquality(weekend_block, [saturday_work, sunday_work])
            weekend_block_vars.append(weekend_block)
        for weekend_index in standalone_weekend_indices:
            weekend_block_vars.append(sum(x[(e, weekend_index, shift)] for shift in shifts))
        weekend_blocks = sum(weekend_block_vars) if weekend_block_vars else 0

        employee_night_weight = night_distribution_weight(employee)
        if employee.likes_nights and employee.max_nights_per_month >= 2 and eligible_night_weight > 0 and total_required_nights > 0:
            preferred_target = round(total_required_nights * employee_night_weight / eligible_night_weight)
            preferred_target = min(employee.max_nights_per_month, max(0, preferred_target))
            if preferred_target:
                objective_terms.append(employee_night_shifts * (priority_weight(employee.night_priority) * 30))

        employee_weekend_weight = weekend_distribution_weight(employee)
        if eligible_weekend_weight > 0:
            target_weekends = round(total_weekend_required * employee_weekend_weight / eligible_weekend_weight)
        else:
            target_weekends = average_weekend_shifts
        if eligible_weekend_weight > 0:
            target_weekend_blocks = round(total_weekend_blocks * employee_weekend_weight / eligible_weekend_weight)
        else:
            target_weekend_blocks = 0
        if employee.prefers_weekends_off and employee.weekend_priority <= 3:
            allowed_extra = 1 if employee.weekend_priority == 2 else 2
            model.Add(weekend_shifts <= max(1, target_weekends + allowed_extra))

        target_minutes = round(employee.weekly_hours_target * 60 * month_factor)
        allowed_overtime_minutes = allowed_variance_minutes(
            target_minutes, max_overtime_percent, max_overtime_hours
        )
        allowed_undertime_minutes = allowed_variance_minutes(
            target_minutes, max_undertime_percent, max_undertime_hours
        )
        model.Add(total_minutes <= target_minutes + allowed_overtime_minutes)
        model.Add(total_minutes >= max(0, target_minutes - allowed_undertime_minutes))
        max_hour_deviation_minutes = max(
            1,
            total_required_minutes,
            target_minutes + allowed_overtime_minutes,
            target_minutes + allowed_undertime_minutes,
        )
        hour_deviation_bounds.append(max_hour_deviation_minutes)
        over_hours = model.NewIntVar(0, max_hour_deviation_minutes, f"over_hours_e{e}")
        under_hours = model.NewIntVar(0, max_hour_deviation_minutes, f"under_hours_e{e}")
        model.Add(total_minutes - target_minutes <= over_hours)
        model.Add(target_minutes - total_minutes <= under_hours)
        abs_hours = model.NewIntVar(0, max_hour_deviation_minutes, f"abs_hours_e{e}")
        model.AddMaxEquality(abs_hours, [over_hours, under_hours])
        hour_deviations.append(abs_hours)
        start_balance_minutes = int(round(float(employee.takeover_time_balance_hours or 0) * 60))
        if start_balance_minutes:
            balance_bound = max(
                1,
                max_hour_deviation_minutes + abs(start_balance_minutes) + day_count * night_credit_minutes,
            )
            final_time_balance = model.NewIntVar(-balance_bound, balance_bound, f"final_time_balance_e{e}")
            final_time_balance_expr = start_balance_minutes + total_minutes - target_minutes
            if night_credit_mode == "Nachtgutschrift ins Zeitkonto" and night_credit_minutes > 0:
                final_time_balance_expr += employee_night_shifts * night_credit_minutes
            model.Add(final_time_balance == final_time_balance_expr)
            final_time_balance_abs = model.NewIntVar(0, balance_bound, f"final_time_balance_abs_e{e}")
            model.AddAbsEquality(final_time_balance_abs, final_time_balance)
            positive_time_balance = model.NewIntVar(0, balance_bound, f"positive_time_balance_e{e}")
            model.AddMaxEquality(positive_time_balance, [final_time_balance, model.NewConstant(0)])
            objective_terms.append(final_time_balance_abs * -time_account_weight)
            objective_terms.append(positive_time_balance * -time_account_positive_weight)
        hour_weight_percent = profile["hour_weight_percent"]
        objective_terms.extend(
            [
                over_hours * -max(1, int(110 * hour_weight_percent / 100)),
                under_hours * -max(1, int(220 * hour_weight_percent / 100)),
                abs_hours * -max(1, int(140 * hour_weight_percent / 100)),
            ]
        )
        employee_satisfaction_loss_terms.append(abs_hours * 3)

        # Nachtwunsch.
        if employee.likes_nights:
            objective_terms.append(
                employee_night_shifts * (night_priority * 10 * profile["night_preference_weight"])
            )
        else:
            objective_terms.append(
                employee_night_shifts * (night_priority * -30 * profile["night_preference_weight"])
            )
            employee_satisfaction_loss_terms.append(
                employee_night_shifts
                * satisfaction_loss_weight(employee.night_priority, 180 * profile["night_preference_weight"])
            )

        # Wochenende fair und bei Wunsch eher frei.
        weekend_under = model.NewIntVar(0, max(1, total_weekend_required), f"weekend_under_e{e}")
        weekend_over = model.NewIntVar(0, max(1, total_weekend_required), f"weekend_over_e{e}")
        weekend_abs = model.NewIntVar(0, max(1, total_weekend_required), f"weekend_abs_e{e}")
        model.Add(weekend_shifts - target_weekends <= weekend_over)
        model.Add(target_weekends - weekend_shifts <= weekend_under)
        model.AddMaxEquality(weekend_abs, [weekend_over, weekend_under])
        weekend_deviations.append(weekend_abs)
        objective_terms.extend([weekend_over * -90, weekend_under * -35, weekend_abs * -40])
        if total_weekend_blocks:
            weekend_block_under = model.NewIntVar(0, total_weekend_blocks, f"weekend_block_under_e{e}")
            weekend_block_over = model.NewIntVar(0, total_weekend_blocks, f"weekend_block_over_e{e}")
            weekend_block_abs = model.NewIntVar(0, total_weekend_blocks, f"weekend_block_abs_e{e}")
            model.Add(weekend_blocks - target_weekend_blocks <= weekend_block_over)
            model.Add(target_weekend_blocks - weekend_blocks <= weekend_block_under)
            model.AddMaxEquality(weekend_block_abs, [weekend_block_over, weekend_block_under])
            weekend_block_deviations.append(weekend_block_abs)
            objective_terms.extend(
                [
                    weekend_block_over * (-180 * profile["weekend_block_weight"]),
                    weekend_block_under * (-45 * profile["weekend_block_weight"]),
                    weekend_block_abs * (-80 * profile["weekend_block_weight"]),
                ]
            )
        if employee.prefers_weekends_off:
            objective_terms.append(weekend_shifts * (weekend_priority * -45 * profile["weekend_block_weight"]))
            employee_satisfaction_loss_terms.append(
                weekend_shifts
                * satisfaction_loss_weight(employee.weekend_priority, 260 * profile["weekend_block_weight"])
            )
            if weekend_block_vars:
                employee_satisfaction_loss_terms.append(
                    weekend_blocks
                    * satisfaction_loss_weight(employee.weekend_priority, 220 * profile["weekend_block_weight"])
                )

        if employee.prefers_joint_weekends:
            joint_weekend_priority = priority_weight(employee.joint_weekend_priority)
            split_weekends = []
            for saturday_index, sunday_index in weekend_pairs:
                saturday_work = sum(x[(e, saturday_index, shift)] for shift in shifts)
                sunday_work = sum(x[(e, sunday_index, shift)] for shift in shifts)
                split_weekend = model.NewBoolVar(f"split_weekend_e{e}_d{saturday_index}")
                model.Add(saturday_work - sunday_work <= split_weekend)
                model.Add(sunday_work - saturday_work <= split_weekend)
                split_weekends.append(split_weekend)
                objective_terms.append(split_weekend * (joint_weekend_priority * -120 * profile["weekend_block_weight"]))
                employee_satisfaction_loss_terms.append(
                    split_weekend
                    * satisfaction_loss_weight(employee.joint_weekend_priority, 240 * profile["weekend_block_weight"])
                )
            if split_weekends:
                if employee.joint_weekend_priority == 1:
                    model.Add(sum(split_weekends) == 0)
                elif employee.joint_weekend_priority == 2:
                    model.Add(sum(split_weekends) <= 1)

        if eligible_night_weight > 0 and employee.max_nights_per_month > 0:
            target_nights = round(total_required_nights * employee_night_weight / eligible_night_weight)
            target_nights = min(target_nights, employee.max_nights_per_month)
            night_over = model.NewIntVar(0, day_count, f"night_over_e{e}")
            night_under = model.NewIntVar(0, day_count, f"night_under_e{e}")
            night_abs = model.NewIntVar(0, day_count, f"night_abs_e{e}")
            model.Add(employee_night_shifts - target_nights <= night_over)
            model.Add(target_nights - employee_night_shifts <= night_under)
            model.AddMaxEquality(night_abs, [night_over, night_under])
            night_deviations.append(night_abs)
            if employee.likes_nights:
                objective_terms.extend([night_over * -25, night_under * -180, night_abs * -60])
                employee_satisfaction_loss_terms.append(
                    night_under
                    * satisfaction_loss_weight(employee.night_priority, 150 * profile["night_preference_weight"])
                )
            else:
                objective_terms.extend([night_over * -180, night_under * -8, night_abs * -45])
                employee_satisfaction_loss_terms.append(
                    night_over
                    * satisfaction_loss_weight(employee.night_priority, 120 * profile["night_preference_weight"])
                )

        if employee.wish_free_priority > 1 and employee.blocked_days:
            wish_free_assignments = []
            for d in employee.blocked_days:
                if d < day_count:
                    assigned_on_wish_free = sum(x[(e, d, shift)] for shift in shifts)
                    wish_free_assignments.append(assigned_on_wish_free)
                    objective_terms.append(assigned_on_wish_free * (wish_free_priority * -180))
                    employee_satisfaction_loss_terms.append(
                        assigned_on_wish_free
                        * satisfaction_loss_weight(employee.wish_free_priority, 320)
                    )
            if employee.wish_free_priority == 2 and wish_free_assignments:
                model.Add(sum(wish_free_assignments) <= 1)

        # Zwei freie Tage nach Nacht werden weich bevorzugt.
        if employee.rest_after_night == 2:
            for d in range(day_count - 2):
                night_today = sum(x[(e, d, night_shift)] for night_shift in night_shifts)
                night_tomorrow = sum(x[(e, d + 1, night_shift)] for night_shift in night_shifts)
                last_night_in_chain = model.NewBoolVar(f"soft_last_night_chain_e{e}_d{d}")
                model.Add(last_night_in_chain <= night_today)
                model.Add(last_night_in_chain <= 1 - night_tomorrow)
                model.Add(last_night_in_chain >= night_today - night_tomorrow)
                after_two_days = sum(x[(e, d + 2, shift)] for shift in shifts)
                violation = model.NewBoolVar(f"rest2_violation_e{e}_d{d}")
                model.Add(after_two_days <= violation).OnlyEnforceIf(last_night_in_chain)
                model.Add(violation == 0).OnlyEnforceIf(last_night_in_chain.Not())
                objective_terms.append(violation * (rest_priority * -25))
                employee_satisfaction_loss_terms.append(
                    violation * satisfaction_loss_weight(employee.rest_priority, 90)
                )

        if replacement_rest_scope != "Keine Ersatzruhe":
            for d, current_day in enumerate(days):
                if not replacement_rest_applies(current_day, holidays, replacement_rest_scope):
                    continue
                source_work = sum(x[(e, d, shift)] for shift in shifts)
                next_workdays = [
                    rest_day
                    for rest_day in range(d + 1, min(day_count, d + 8))
                    if day_type(days[rest_day], holidays) == "Werktag"
                ][:3]
                for order, rest_day in enumerate(next_workdays):
                    rest_day_work = sum(x[(e, rest_day, shift)] for shift in shifts)
                    delay = model.NewBoolVar(f"replacement_rest_delay_e{e}_d{d}_r{rest_day}")
                    model.Add(source_work + rest_day_work <= 1 + delay)
                    objective_terms.append(
                        delay * (-(260 - order * 70) * profile["replacement_rest_weight"])
                    )
                    employee_satisfaction_loss_terms.append(
                        delay * ((160 - order * 40) * profile["replacement_rest_weight"])
                    )

    # Doppelnacht-Wunsch: Einzelne Naechte werden auch ueber unterschiedliche Nachtformen hinweg gepaart.
    for e, employee in enumerate(employees):
        if not employee.double_nights_only:
            continue
        lonely_nights_for_employee = []
        for d in range(day_count):
            night_today = sum(x[(e, d, night_shift)] for night_shift in night_shifts)
            pair_score = []
            if d > 0:
                pair_score.extend(x[(e, d - 1, night_shift)] for night_shift in night_shifts)
            if d < day_count - 1:
                pair_score.extend(x[(e, d + 1, night_shift)] for night_shift in night_shifts)
            if pair_score:
                paired = model.NewBoolVar(f"paired_night_e{e}_d{d}")
                model.AddMaxEquality(paired, pair_score)
                lonely = model.NewBoolVar(f"soft_lonely_night_e{e}_d{d}")
                model.Add(lonely >= night_today - paired)
                model.Add(lonely <= night_today)
                model.Add(lonely <= 1 - paired)
                lonely_nights_for_employee.append(lonely)
                objective_terms.append(lonely * (double_night_priority * -220))
                objective_terms.append(paired * double_night_priority)
                satisfaction_loss_terms_by_employee[e].append(
                    lonely
                    * satisfaction_loss_weight(employee.double_night_priority, 260)
                )
        if lonely_nights_for_employee:
            if employee.double_night_priority == 1:
                model.Add(sum(lonely_nights_for_employee) == 0)
            elif employee.double_night_priority == 2:
                model.Add(sum(lonely_nights_for_employee) <= 1)
            elif employee.double_night_priority == 3:
                model.Add(sum(lonely_nights_for_employee) <= 2)

    for e, employee_loss_terms in enumerate(satisfaction_loss_terms_by_employee):
        if employee_loss_terms:
            satisfaction_score = model.NewIntVar(-1_000_000, 10_000, f"satisfaction_proxy_e{e}")
            model.Add(satisfaction_score + sum(employee_loss_terms) == 10_000)
        else:
            satisfaction_score = model.NewConstant(10_000)
        satisfaction_score_vars.append(satisfaction_score)

    if hour_deviations:
        max_hour_deviation = model.NewIntVar(
            0,
            max([1, total_required_minutes, *hour_deviation_bounds]),
            "max_hour_deviation",
        )
        model.AddMaxEquality(max_hour_deviation, hour_deviations)
        objective_terms.append(max_hour_deviation * -profile["max_hour_deviation_weight"])
    if night_deviations:
        max_night_deviation = model.NewIntVar(0, day_count, "max_night_deviation")
        model.AddMaxEquality(max_night_deviation, night_deviations)
        objective_terms.append(max_night_deviation * -500)
    if weekend_deviations:
        max_weekend_deviation = model.NewIntVar(0, len(weekend_days), "max_weekend_deviation")
        model.AddMaxEquality(max_weekend_deviation, weekend_deviations)
        objective_terms.append(max_weekend_deviation * -300)
    if weekend_block_deviations:
        max_weekend_block_deviation = model.NewIntVar(
            0,
            max(1, total_weekend_blocks),
            "max_weekend_block_deviation",
        )
        model.AddMaxEquality(max_weekend_block_deviation, weekend_block_deviations)
        objective_terms.append(max_weekend_block_deviation * (-250 * profile["weekend_block_weight"]))
    if satisfaction_score_vars:
        min_satisfaction_proxy = model.NewIntVar(-1_000_000, 10_000, "min_satisfaction_proxy")
        model.AddMinEquality(min_satisfaction_proxy, satisfaction_score_vars)
        objective_terms.append(min_satisfaction_proxy * profile["min_satisfaction_weight"])
        objective_terms.append(sum(satisfaction_score_vars) * profile["avg_satisfaction_weight"])

    if optimize_for_fairness and objective_terms:
        model.Maximize(sum(objective_terms))
    elif coverage_objective_terms:
        model.Maximize(sum(coverage_objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1, int(max_time_seconds))
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = int(random_seed)
    solver.parameters.randomize_search = False if deterministic_search else int(random_seed) != 7
    status = solver.Solve(model)
    status_name = solver.StatusName(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return status_name, {}, {}

    def build_priority_stats() -> dict[int, dict[str, object]]:
        return {priority: {"count": 0, "details": []} for priority in range(1, 6)}

    def add_priority_violation(
        stats: dict[int, dict[str, object]],
        priority: int,
        detail: str,
        count: int = 1,
    ) -> None:
        bucket = stats[priority]
        bucket["count"] = int(bucket["count"]) + max(0, int(count))
        if detail:
            bucket["details"] = [*bucket["details"], detail]

    schedule = {}
    metrics = {}
    for e, employee in enumerate(employees):
        row = []
        total = nights = weekends = fulfilled = violated = 0
        vacation_minutes = vacation_paid_minutes_for_month(employee, days, vacation_counts_as_hours)
        planned_minutes = vacation_minutes
        violation_details = []
        priority_stats = build_priority_stats()
        for d, current_day in enumerate(days):
            assigned = "-"
            for shift in shifts:
                if solver.Value(x[(e, d, shift)]) == 1:
                    assigned = shift
                    total += 1
                    planned_minutes += shift_minutes_by_code.get(shift, 8 * 60)
                    if compensatory_rest_counts_as_hours and replacement_rest_applies(
                        current_day,
                        holidays,
                        replacement_rest_scope,
                    ):
                        planned_minutes += shift_minutes_by_code.get(shift, 8 * 60)
                    if shift in night_shifts:
                        nights += 1
                    if current_day.weekday() >= 5 or current_day in holidays:
                        weekends += 1
            row.append(assigned)

        if employee.likes_nights:
            fulfilled += nights
            missing_nights = max(0, 2 - nights)
            if missing_nights:
                detail = f"wollte gerne Nachtdienste, bekam nur {nights}"
                add_priority_violation(priority_stats, employee.night_priority, detail, missing_nights)
                if employee.night_priority <= 3:
                    violated += missing_nights
                    violation_details.append(detail)
        else:
            fulfilled += max(0, 4 - nights)
            if nights:
                detail = f"wollte möglichst keine Nachtdienste, bekam {nights}"
                add_priority_violation(priority_stats, employee.night_priority, detail, nights)
                if employee.night_priority <= 3:
                    violated += nights
                    violation_details.append(detail)
        if employee.prefers_weekends_off:
            fulfilled += max(0, 2 - weekends)
            if weekends:
                detail = f"bevorzugt Wochenende frei, bekam {weekends} Wochenend-/Feiertagsdienste"
                add_priority_violation(priority_stats, employee.weekend_priority, detail, weekends)
                if employee.weekend_priority <= 3:
                    violated += weekends
                    violation_details.append(detail)
        if employee.prefers_joint_weekends:
            split_weekends_count = 0
            for saturday_index, sunday_index in saturday_sunday_pairs(days):
                saturday_worked = row[saturday_index] != "-"
                sunday_worked = row[sunday_index] != "-"
                if saturday_worked != sunday_worked:
                    split_weekends_count += 1
            if split_weekends_count:
                detail = f"wünscht gemeinsame Wochenenden, {split_weekends_count} Wochenende(n) waren geteilt"
                add_priority_violation(priority_stats, employee.joint_weekend_priority, detail, split_weekends_count)
                if employee.joint_weekend_priority <= 3:
                    violated += split_weekends_count
                    violation_details.append(detail)
        if employee.double_nights_only:
            lonely_count = 0
            for d, shift in enumerate(row):
                if shift not in night_shifts:
                    continue
                has_neighbor = (
                    (d > 0 and row[d - 1] in night_shifts)
                    or (d < day_count - 1 and row[d + 1] in night_shifts)
                )
                if not has_neighbor:
                    lonely_count += 1
            fulfilled += max(0, nights - lonely_count)
            if lonely_count:
                detail = f"wünscht Doppelnächte, {lonely_count} Nachtdienst(e) standen einzeln"
                add_priority_violation(priority_stats, employee.double_night_priority, detail, lonely_count)
                if employee.double_night_priority <= 3:
                    violated += lonely_count
                    violation_details.append(detail)

        wish_free_worked = [
            d + 1
            for d in employee.blocked_days
            if d < day_count and row[d] != "-"
        ]
        if employee.wish_free_priority > 1 and wish_free_worked:
            detail = "Wunschfrei nicht eingehalten an Tag(en): " + ", ".join(str(day) for day in wish_free_worked)
            add_priority_violation(priority_stats, employee.wish_free_priority, detail, len(wish_free_worked))
            if employee.wish_free_priority <= 3:
                violated += len(wish_free_worked)
                violation_details.append(detail)

        sick_worked = [
            d + 1
            for d in employee.planned_sick_days
            if d < day_count and row[d] != "-"
        ]
        if sick_worked:
            detail = "Geplanter Krankenstand nicht eingehalten an Tag(en): " + ", ".join(str(day) for day in sick_worked)
            add_priority_violation(priority_stats, 1, detail, len(sick_worked))
            violated += len(sick_worked)
            violation_details.append(detail)

        vacation_blocked_days = vacation_protected_day_indices(employee, days, vacation_weekend_policy)
        vacation_worked = [
            d + 1
            for d in vacation_blocked_days
            if d < day_count and row[d] != "-"
        ]
        if vacation_worked:
            detail = "Urlaub nicht eingehalten an Tag(en): " + ", ".join(str(day) for day in vacation_worked)
            add_priority_violation(priority_stats, 1, detail, len(vacation_worked))
            violated += len(vacation_worked)
            violation_details.append(detail)

        target_minutes = round(employee.weekly_hours_target * 60 * month_factor)
        hour_diff = planned_minutes - target_minutes
        weighted_violations = sum(
            int(priority_stats[priority]["count"]) * (6 - priority)
            for priority in range(1, 6)
        )
        satisfaction_score = max(
            0,
            min(
                100,
                round(100 - weighted_violations * 8 - abs(format_minutes_as_hours(hour_diff)) * 1.5),
            ),
        )

        schedule[employee.name] = row
        metrics[employee.name] = {
            "Qualifikation": employee.qualification,
            "Sollstunden": format_minutes_as_hours(target_minutes),
            "Geplante Stunden": format_minutes_as_hours(planned_minutes),
            "Plus/Minus Stunden": format_minutes_as_hours(hour_diff),
            "Stundenabweichung h": format_minutes_as_hours(abs(hour_diff)),
            "Urlaub-Stunden": format_minutes_as_hours(vacation_minutes),
            "Urlaub-Startsaldo h": (
                round(employee.takeover_vacation_hours, 2)
                if employee.takeover_confirmed
                else vacation_entitlement_hours(employee)
            ),
            "Urlaub-Rest h": max(
                0,
                round(
                    (
                        employee.takeover_vacation_hours
                        if employee.takeover_confirmed
                        else vacation_entitlement_hours(employee)
                    )
                    - format_minutes_as_hours(vacation_minutes),
                    2,
                ),
            ),
            "Start-Zeitkonto h": round(employee.takeover_time_balance_hours, 2) if employee.takeover_confirmed else 0,
            "Zeitkonto nach Plan h": round(
                (employee.takeover_time_balance_hours if employee.takeover_confirmed else 0)
                + format_minutes_as_hours(hour_diff),
                2,
            ),
            "Start-Ersatzruhe h": round(employee.takeover_replacement_rest_hours, 2) if employee.takeover_confirmed else 0,
            "Zufriedenheit %": satisfaction_score,
            "Dienste": total,
            "Nachtdienste": nights,
            "Wochenenddienste": weekends,
            "Erfuellte Wuensche": fulfilled,
            "Verletzte weiche Wuensche": violated,
            "Welche Wuensche verletzt": "; ".join(violation_details) if violation_details else "-",
            "Aktive Warnungen": violated,
            "Verletzungen Prio 1": int(priority_stats[1]["count"]),
            "Verletzungen Prio 2": int(priority_stats[2]["count"]),
            "Verletzungen Prio 3": int(priority_stats[3]["count"]),
            "Verletzungen Prio 4": int(priority_stats[4]["count"]),
            "Verletzungen Prio 5": int(priority_stats[5]["count"]),
            "Verstossdetails nach Prioritaet": {
                priority: {
                    "count": int(priority_stats[priority]["count"]),
                    "details": list(priority_stats[priority]["details"]),
                }
                for priority in range(1, 6)
            },
        }

    return status_name, schedule, metrics


def add_compensatory_rest_days(
    schedule: dict,
    metrics: dict,
    days: list[date],
    holidays: dict[date, str],
    shift_hours_by_code: dict[str, float],
    replacement_rest_scope: str,
    counts_as_hours: bool,
    source_hours_already_counted: bool = True,
    employees: list[Employee] | None = None,
    vacation_weekend_policy: str = DEFAULT_VACATION_WEEKEND_POLICY,
) -> tuple[dict, dict, list[str]]:
    updated_schedule = {name: list(plan) for name, plan in schedule.items()}
    updated_metrics = {name: dict(values) for name, values in metrics.items()}
    open_notes = []
    replacement_rest_scope = normalize_replacement_rest_scope(replacement_rest_scope)
    vacation_weekend_policy = normalize_vacation_weekend_policy(vacation_weekend_policy)
    employee_by_name = {employee.name: employee for employee in employees or []}

    for employee_name, assignments in updated_schedule.items():
        employee = employee_by_name.get(employee_name)
        vacation_protected_days = (
            vacation_protected_day_indices(employee, days, vacation_weekend_policy)
            if employee is not None
            else set()
        )
        rest_days_added = 0
        rest_hours_added = 0
        rest_hours_owed = 0
        for day_index, current_day in enumerate(days):
            if not replacement_rest_applies(current_day, holidays, replacement_rest_scope):
                continue
            worked_shift = first_real_shift(assignments[day_index])
            if worked_shift == "-":
                continue
            owed_hours = shift_hours_by_code.get(worked_shift, 8)
            rest_hours_owed += owed_hours
            placed = False
            for rest_day in range(day_index + 1, len(days)):
                if day_type(days[rest_day], holidays) != "Werktag":
                    continue
                if rest_day in vacation_protected_days:
                    continue
                if first_real_shift(assignments[rest_day]) != "-":
                    continue
                if str(assignments[rest_day]).startswith("ER"):
                    continue
                assignments[rest_day] = f"ER{owed_hours}"
                rest_days_added += 1
                rest_hours_added += owed_hours
                placed = True
                break
            if not placed:
                open_notes.append(
                    f"{employee_name}: {owed_hours} Ersatzruhe-Stunden aus {day_label(current_day)} offen"
                )

        if employee_name in updated_metrics:
            updated_metrics[employee_name]["Ersatzruhe-Tage"] = rest_days_added
            updated_metrics[employee_name]["Ersatzruhe-Stunden"] = rest_hours_added
            updated_metrics[employee_name]["Ersatzruhe-offen-Stunden"] = max(0, rest_hours_owed - rest_hours_added)
            if counts_as_hours and not source_hours_already_counted and rest_hours_added:
                planned_hours = float(updated_metrics[employee_name].get("Geplante Stunden", 0) or 0)
                target_hours = float(updated_metrics[employee_name].get("Sollstunden", 0) or 0)
                corrected_hours = planned_hours + rest_hours_added
                updated_metrics[employee_name]["Geplante Stunden"] = round(corrected_hours, 2)
                updated_metrics[employee_name]["Plus/Minus Stunden"] = round(corrected_hours - target_hours, 2)
                updated_metrics[employee_name]["Stundenabweichung h"] = round(abs(corrected_hours - target_hours), 2)
            elif counts_as_hours and rest_hours_owed != rest_hours_added:
                planned_hours = float(updated_metrics[employee_name].get("Geplante Stunden", 0) or 0)
                target_hours = float(updated_metrics[employee_name].get("Sollstunden", 0) or 0)
                corrected_hours = max(0, planned_hours - max(0, rest_hours_owed - rest_hours_added))
                updated_metrics[employee_name]["Geplante Stunden"] = round(corrected_hours, 2)
                updated_metrics[employee_name]["Plus/Minus Stunden"] = round(corrected_hours - target_hours, 2)
                updated_metrics[employee_name]["Stundenabweichung h"] = round(abs(corrected_hours - target_hours), 2)
            start_time_balance = float(updated_metrics[employee_name].get("Start-Zeitkonto h", 0) or 0)
            current_balance = float(updated_metrics[employee_name].get("Plus/Minus Stunden", 0) or 0)
            start_replacement_rest = float(updated_metrics[employee_name].get("Start-Ersatzruhe h", 0) or 0)
            open_replacement_rest = float(updated_metrics[employee_name].get("Ersatzruhe-offen-Stunden", 0) or 0)
            updated_metrics[employee_name]["Zeitkonto nach Plan h"] = round(start_time_balance + current_balance, 2)
            updated_metrics[employee_name]["Ersatzruhe-offen gesamt h"] = round(start_replacement_rest + open_replacement_rest, 2)

    return updated_schedule, updated_metrics, open_notes


def apply_night_credit_hours(
    schedule: dict,
    metrics: dict,
    night_shifts: list[str],
    credit_hours_per_night: float,
    counts_as_hours: bool,
) -> dict:
    if credit_hours_per_night <= 0 or not night_shifts:
        return metrics
    night_set = set(night_shifts)
    updated_metrics = {name: dict(values) for name, values in metrics.items()}
    for employee_name, assignments in (schedule or {}).items():
        if employee_name not in updated_metrics:
            continue
        night_count = sum(1 for assignment in assignments if first_real_shift(assignment) in night_set)
        credit_hours = round(night_count * float(credit_hours_per_night), 2)
        values = updated_metrics[employee_name]
        base_hours = float(values.get("Geplante Stunden vor Nachtgutschrift", values.get("Geplante Stunden", 0)) or 0)
        values["Geplante Stunden vor Nachtgutschrift"] = round(base_hours, 2)
        values["Nachtgutschrift h"] = credit_hours
        if counts_as_hours:
            target_hours = float(values.get("Sollstunden", 0) or 0)
            corrected_hours = round(base_hours + credit_hours, 2)
            values["Geplante Stunden"] = corrected_hours
            values["Plus/Minus Stunden"] = round(corrected_hours - target_hours, 2)
            values["Stundenabweichung h"] = round(abs(corrected_hours - target_hours), 2)
            start_time_balance = float(values.get("Start-Zeitkonto h", 0) or 0)
            values["Zeitkonto nach Plan h"] = round(start_time_balance + corrected_hours - target_hours, 2)
        else:
            start_time_balance = float(values.get("Start-Zeitkonto h", 0) or 0)
            current_balance = float(values.get("Plus/Minus Stunden", 0) or 0)
            values["Zeitkonto nach Plan h"] = round(start_time_balance + current_balance + credit_hours, 2)
    return updated_metrics


def open_services_dataframe(
    schedule: dict,
    days: list[date],
    daily_requirements: dict[tuple[int, str], int],
    shift_df: pd.DataFrame,
    open_shift_codes: list[str] | None = None,
    shift_priority_by_code: dict[str, int] | None = None,
) -> pd.DataFrame:
    cleaned_shifts = shift_definitions_from_editor(shift_df)
    shift_names = {row["Kuerzel"]: row["Name"] for _, row in cleaned_shifts.iterrows()}
    shifts = cleaned_shifts["Kuerzel"].tolist()
    open_shift_set = set(open_shift_codes or [])
    shift_priority_by_code = shift_priority_by_code or {
        row["Kuerzel"]: int(row["Prioritaet"]) for _, row in cleaned_shifts.iterrows()
    }
    rows = []
    for day_index, current_day in enumerate(days):
        for shift in shifts:
            demand = daily_requirements.get((day_index, shift), 0)
            assigned = sum(
                1
                for assignments in schedule.values()
                if day_index < len(assignments) and first_real_shift(assignments[day_index]) == shift
            )
            missing = max(0, demand - assigned)
            if missing:
                rows.append(
                    {
                        "Tag": day_label(current_day),
                        "Dienst": shift_names.get(shift, shift),
                        "Kuerzel": shift,
                        "Prioritaet": shift_priority_by_code.get(shift, 1),
                        "Offen": missing,
                        "Grund": (
                            "Darf laut Dienstform-Priorität offen bleiben."
                            if shift in open_shift_set or shift_priority_by_code.get(shift, 1) > 1
                            else "Konnte mit den harten Regeln nicht vollständig besetzt werden."
                        ),
                    }
                )
    return pd.DataFrame(rows)


def replacement_shift_options(
    schedule: dict,
    day_index: int,
    daily_requirements: dict[tuple[int, str], int],
    shift_df: pd.DataFrame,
    shifts: list[str],
) -> list[tuple[str, str]]:
    cleaned_shifts = shift_definitions_from_editor(shift_df)
    shift_names = {str(row["Kuerzel"]): str(row["Name"]) for _, row in cleaned_shifts.iterrows()}
    options = []
    for shift in shifts:
        demand = int(daily_requirements.get((day_index, shift), 0) or 0)
        assigned = sum(
            1
            for assignments in schedule.values()
            if day_index < len(assignments) and first_real_shift(assignments[day_index]) == shift
        )
        if demand > 0 or assigned > 0:
            label = f"{shift} - {shift_names.get(shift, shift)} ({assigned}/{demand} besetzt)"
            options.append((shift, label))
    if not options:
        options = [(shift, f"{shift} - {shift_names.get(shift, shift)}") for shift in shifts]
    return options


def assignment_display_state(value: object) -> str:
    text = str(value or "-").strip()
    if not text or text == "-":
        return "frei"
    return text


def simulated_work_run(assignments: list[str], day_index: int, target_shift: str) -> list[str]:
    simulated = [first_real_shift(value) for value in assignments]
    if 0 <= day_index < len(simulated):
        simulated[day_index] = target_shift
    return simulated


def longest_work_streak(real_assignments: list[str], previous_assignments: list[str] | None = None) -> int:
    combined = [first_real_shift(value) for value in (previous_assignments or [])[-14:]] + list(real_assignments)
    longest = 0
    current = 0
    for shift in combined:
        if shift != "-":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def week_indices_for_day(days: list[date], day_index: int) -> list[int]:
    if day_index >= len(days):
        return []
    iso_key = (days[day_index].isocalendar().year, days[day_index].isocalendar().week)
    return [
        index
        for index, current_day in enumerate(days)
        if (current_day.isocalendar().year, current_day.isocalendar().week) == iso_key
    ]


def replacement_extra_hours(
    target_shift: str,
    shift_minutes_by_code: dict[str, int],
    night_shifts: list[str],
    night_credit_mode: str,
    night_credit_hours: float,
) -> tuple[float, float]:
    base_hours = format_minutes_as_hours(shift_minutes_by_code.get(target_shift, 8 * 60))
    credit_hours = (
        max(0.0, float(night_credit_hours))
        if target_shift in set(night_shifts) and normalize_night_credit_mode(night_credit_mode) != "Keine Nachtgutschrift"
        else 0.0
    )
    month_extra = base_hours + (
        credit_hours if normalize_night_credit_mode(night_credit_mode) == "Nachtgutschrift als Dienststunden" else 0.0
    )
    time_account_extra = base_hours + credit_hours
    return round(month_extra, 2), round(time_account_extra, 2)


def replacement_candidate_dataframe(
    schedule: dict,
    metrics: dict,
    employees: list[Employee],
    days: list[date],
    day_index: int,
    target_shift: str,
    shifts: list[str],
    night_shifts: list[str],
    shift_minutes_by_code: dict[str, int],
    shift_time_by_code: dict[str, tuple[int, int]],
    previous_assignments: dict[str, list[str]] | None,
    *,
    vacation_weekend_policy: str,
    block_night_before_wish_free: bool,
    daily_max_work_hours: float,
    max_overtime_percent: float,
    max_overtime_hours: float,
    night_credit_mode: str,
    night_credit_hours: float,
) -> tuple[pd.DataFrame, int]:
    previous_assignments = previous_assignments or {}
    night_set = set(night_shifts)
    day_shift_set = set(shifts) - night_set
    rows = []
    hidden_count = 0
    target_minutes = shift_minutes_by_code.get(target_shift, 8 * 60)
    month_extra_hours, time_account_extra_hours = replacement_extra_hours(
        target_shift,
        shift_minutes_by_code,
        night_shifts,
        night_credit_mode,
        night_credit_hours,
    )

    for employee in employees:
        if not employee.participates_in_schedule:
            hidden_count += 1
            continue
        assignments = list(schedule.get(employee.name, ["-"] * len(days)))
        if len(assignments) < len(days):
            assignments = assignments + ["-"] * (len(days) - len(assignments))
        current_assignment = assignments[day_index] if day_index < len(assignments) else "-"
        current_shift = first_real_shift(current_assignment)
        hard_reasons: list[str] = []
        notes: list[str] = []
        score = 1000.0

        if current_shift == target_shift:
            hidden_count += 1
            continue
        if current_shift != "-":
            hard_reasons.append(f"hat bereits {current_shift}")
        if day_index in employee.planned_sick_days:
            hard_reasons.append("geplanter Krankenstand")
        vacation_protected = vacation_protected_day_indices(employee, days, vacation_weekend_policy)
        if day_index in vacation_protected:
            hard_reasons.append("Urlaub oder geschütztes Urlaubswochenende")
        if target_minutes > int(round(float(daily_max_work_hours) * 60)):
            hard_reasons.append("Dienst überschreitet Tageshöchstgrenze")

        previous_row = previous_assignments.get(employee.name, [])
        previous_shift = "-"
        if day_index > 0:
            previous_shift = first_real_shift(assignments[day_index - 1])
        elif previous_row:
            previous_shift = first_real_shift(previous_row[-1])
        next_shift = first_real_shift(assignments[day_index + 1]) if day_index + 1 < len(assignments) else "-"
        second_previous_shift = "-"
        if day_index > 1:
            second_previous_shift = first_real_shift(assignments[day_index - 2])
        elif day_index == 1 and previous_row:
            second_previous_shift = first_real_shift(previous_row[-1])
        elif day_index == 0 and len(previous_row) >= 2:
            second_previous_shift = first_real_shift(previous_row[-2])

        if previous_shift != "-" and not has_required_rest_between(previous_shift, target_shift, shift_time_by_code):
            hard_reasons.append("zu wenig Ruhezeit zum Vortag")
        if next_shift != "-" and not has_required_rest_between(target_shift, next_shift, shift_time_by_code):
            hard_reasons.append("zu wenig Ruhezeit zum Folgetag")
        if previous_shift in night_set and target_shift in day_shift_set:
            hard_reasons.append("Tagdienst direkt nach Nachtdienst")
        if target_shift in night_set and next_shift in day_shift_set:
            hard_reasons.append("Tagdienst direkt nach neuer Nacht")

        if (
            employee.rest_after_night >= 2
            and employee.rest_priority == 1
            and previous_shift in night_set
            and target_shift not in night_set
        ):
            hard_reasons.append("Ausschlaftag nach Nachtdienst")
        if (
            employee.rest_after_night >= 2
            and employee.rest_priority == 1
            and second_previous_shift in night_set
            and previous_shift not in night_set
            and target_shift not in night_set
        ):
            hard_reasons.append("zweiter freier Tag nach Nachtdienst")
        if (
            target_shift in night_set
            and employee.rest_after_night >= 2
            and employee.rest_priority == 1
            and next_shift not in {"-", *night_set}
        ):
            hard_reasons.append("Folgetag nach neuer Nacht ist besetzt")
        if (
            target_shift in night_set
            and employee.rest_after_night >= 2
            and employee.rest_priority == 1
            and next_shift not in night_set
            and day_index + 2 < len(assignments)
            and first_real_shift(assignments[day_index + 2]) != "-"
        ):
            hard_reasons.append("zweiter Folgetag nach neuer Nacht ist besetzt")
        if (
            block_night_before_wish_free
            and target_shift in night_set
            and day_index + 1 < len(days)
            and (day_index + 1) in employee.blocked_days
            and employee.wish_free_priority == 1
        ):
            hard_reasons.append("Nacht vor Wunschfrei Prio 1")

        simulated = simulated_work_run(assignments, day_index, target_shift)
        if longest_work_streak(simulated, previous_row) > employee.max_consecutive_workdays:
            hard_reasons.append("max. Tage in Folge überschritten")

        week_indices = week_indices_for_day(days, day_index)
        week_shift_count = sum(1 for index in week_indices if first_real_shift(assignments[index]) != "-") + 1
        if week_shift_count > employee.max_shifts_per_week:
            hard_reasons.append("max. Dienste/Woche überschritten")
        week_minutes = sum(
            shift_minutes_by_code.get(first_real_shift(assignments[index]), 0)
            for index in week_indices
            if first_real_shift(assignments[index]) != "-"
        ) + target_minutes
        if week_minutes > int(round(float(employee.max_weekly_planned_hours) * 60)):
            hard_reasons.append("max. Wochenstunden überschritten")

        current_nights = sum(1 for value in assignments if first_real_shift(value) in night_set)
        if target_shift in night_set:
            if current_nights + 1 > employee.max_nights_per_month:
                hard_reasons.append("max. Nächte/Monat überschritten")
            if not employee.allow_three_consecutive_nights:
                for start_index in range(max(0, day_index - 2), min(len(simulated) - 2, day_index) + 1):
                    if all(simulated[check_index] in night_set for check_index in range(start_index, start_index + 3)):
                        hard_reasons.append("3 Nächte in Folge nicht erlaubt")
                        break

        employee_metrics = metrics.get(employee.name, {})
        target_hours = float(employee_metrics.get("Sollstunden", 0) or 0)
        monthly_balance = float(employee_metrics.get("Plus/Minus Stunden", 0) or 0)
        start_balance = float(employee_metrics.get("Start-Zeitkonto h", 0) or 0)
        total_balance = float(employee_metrics.get("Zeitkonto nach Plan h", start_balance + monthly_balance) or 0)
        satisfaction = float(employee_metrics.get("Zufriedenheit %", 0) or 0)
        month_after = monthly_balance + month_extra_hours
        total_after = total_balance + time_account_extra_hours
        overtime_limit = format_minutes_as_hours(
            allowed_variance_minutes(round(target_hours * 60), max_overtime_percent, max_overtime_hours)
        )
        if overtime_limit > 0 and month_after > overtime_limit + 0.01:
            hard_reasons.append("Überstunden-Grenze würde überschritten")

        if hard_reasons:
            hidden_count += 1
            continue

        if day_index in employee.blocked_days:
            notes.append(f"Wunschfrei Prio {employee.wish_free_priority}")
            score -= {1: 420, 2: 300, 3: 180}.get(employee.wish_free_priority, 90)
        current_text = str(current_assignment or "-")
        if "ER" in current_text:
            notes.append("Ausgleich/Ersatzruhe eingetragen")
            score -= 260
        if target_shift in night_set:
            if employee.likes_nights:
                notes.append("übernimmt gerne Nächte")
                score += 90
            else:
                notes.append("möchte Nächte eher vermeiden")
                score -= {1: 360, 2: 260, 3: 160}.get(employee.night_priority, 80)
            if employee.double_nights_only:
                adjacent_night = previous_shift in night_set or next_shift in night_set
                if adjacent_night:
                    score += 60
                    notes.append("passt zu Doppelnacht")
                else:
                    score -= 120
                    notes.append("wäre einzelne Nacht")
        if days[day_index].weekday() >= 5 and employee.prefers_weekends_off:
            notes.append(f"Wochenende eher frei Prio {employee.weekend_priority}")
            score -= {1: 260, 2: 190, 3: 120}.get(employee.weekend_priority, 60)

        if abs(total_after) < abs(total_balance):
            score += min(140, abs(total_balance) * 4)
            notes.append("verbessert das Zeitkonto")
        else:
            score -= min(220, max(0.0, total_after) * 3)
        if satisfaction < 75:
            notes.append("Zufriedenheit bereits niedrig")
            score -= (75 - satisfaction) * 6
        elif satisfaction >= 90:
            score += 40
        score -= max(0.0, month_after) * 2
        score += max(0.0, -monthly_balance) * 1.5

        if score >= 850 and not any("Wunschfrei" in note or "Ersatzruhe" in note for note in notes):
            suitability = "1. sehr geeignet"
        elif score >= 650:
            suitability = "2. geeignet"
        else:
            suitability = "3. nur mit Konflikt"

        rows.append(
            {
                "Rangwert": round(score, 2),
                "Einschätzung": suitability,
                "MitarbeiterIn": employee.name,
                "Aktuell am Tag": assignment_display_state(current_assignment),
                "Regelcheck": "möglich" if suitability != "3. nur mit Konflikt" else "möglich, aber bewusst prüfen",
                "Begründung": "; ".join(notes) if notes else "frei, keine direkten Konflikte erkannt",
                "Zusatz h": month_extra_hours,
                "Monats +/- aktuell h": monthly_balance,
                "Monats +/- nach Einsatz h": round(month_after, 2),
                "Zeitkonto gesamt aktuell h": total_balance,
                "Zeitkonto gesamt nach Einsatz h": round(total_after, 2),
                "Zufriedenheit aktuell": f"{format_display_hours(satisfaction)} %",
            }
        )

    if not rows:
        return pd.DataFrame(), hidden_count
    result = pd.DataFrame(rows).sort_values(
        by=["Rangwert", "Zeitkonto gesamt nach Einsatz h"],
        ascending=[False, True],
    )
    result.insert(0, "Rang", range(1, len(result) + 1))
    return result.drop(columns=["Rangwert"]), hidden_count


def schedule_shortage_penalty(
    schedule: dict,
    days: list[date],
    daily_requirements: dict[tuple[int, str], int],
    shift_df: pd.DataFrame,
    open_shift_codes: list[str] | None,
    shift_priority_by_code: dict[str, int],
) -> int:
    open_services = open_services_dataframe(
        schedule,
        days,
        daily_requirements,
        shift_df,
        open_shift_codes=open_shift_codes,
        shift_priority_by_code=shift_priority_by_code,
    )
    if open_services.empty:
        return 0
    penalty = 0
    for _, row in open_services.iterrows():
        shift = str(row.get("Kuerzel", ""))
        priority = int(row.get("Prioritaet", shift_priority_by_code.get(shift, 1)) or 1)
        penalty += int(row.get("Offen", 0) or 0) * shortage_penalty_for_shift(
            shift,
            priority,
            open_shift_codes,
        )
    return penalty


def weekly_rest_findings(
    schedule: dict,
    employees: list[Employee],
    days: list[date],
    shift_time_by_code: dict[str, tuple[int, int]],
    previous_assignments: dict[str, list[str]] | None,
    weekly_rest_hours: float,
    reduced_weekly_rest_hours: float,
    allow_reduced_weekly_rest: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not days:
        return errors, warnings
    previous_assignments = previous_assignments or {}
    week_starts = sorted({iso_week_start(day) for day in days})
    target_minutes = int(round(float(weekly_rest_hours) * 60))
    reduced_minutes = int(round(float(reduced_weekly_rest_hours) * 60))
    for employee in employees:
        assignments = list(schedule.get(employee.name, []))
        intervals = assignment_work_intervals(
            assignments,
            days,
            shift_time_by_code,
            previous_assignments=previous_assignments.get(employee.name, []),
        )
        weekly_gaps: list[int] = []
        for week_start_day in week_starts:
            window_start = datetime.combine(week_start_day, dt_time())
            window_end = window_start + timedelta(days=7)
            max_gap = max_free_minutes_in_window(intervals, window_start, window_end)
            weekly_gaps.append(max_gap)
            if max_gap >= target_minutes:
                continue
            label = f"{employee.name}: KW {week_start_day.isocalendar().week} ({format_display_hours(format_minutes_as_hours(max_gap))} h)"
            if allow_reduced_weekly_rest and max_gap >= reduced_minutes:
                warnings.append(label + " verkürzte Wochenruhe")
            else:
                errors.append(label)
        if allow_reduced_weekly_rest and len(weekly_gaps) >= 4:
            for start_index in range(0, len(weekly_gaps) - 3):
                average_gap = sum(weekly_gaps[start_index:start_index + 4]) / 4
                if average_gap < target_minutes:
                    week_label = week_starts[start_index].isocalendar().week
                    errors.append(
                        f"{employee.name}: 4-Wochen-Schnitt ab KW {week_label} nur "
                        f"{format_display_hours(format_minutes_as_hours(round(average_gap)))} h Wochenruhe"
                    )
                    break
    return errors, warnings


def rolling_weekly_hours_findings(
    schedule: dict,
    employees: list[Employee],
    days: list[date],
    shift_minutes_by_code: dict[str, int],
    saved_schedules: dict | None,
    weekly_average_max_hours: float,
    weekly_average_period_weeks: int,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not days:
        return errors, warnings
    saved_schedules = saved_schedules or {}
    employee_names = {employee.name for employee in employees}
    current_weeks = sorted({(day.isocalendar().year, day.isocalendar().week) for day in days})
    weekly_minutes: dict[str, dict[tuple[int, int], int]] = {name: {} for name in employee_names}

    def add_month_schedule(month_schedule: dict, month_days: list[date]) -> None:
        if not isinstance(month_schedule, dict):
            return
        for employee_name, assignments in month_schedule.items():
            if employee_name not in weekly_minutes or not isinstance(assignments, list):
                continue
            for day_index, assignment in enumerate(assignments):
                if day_index >= len(month_days):
                    continue
                shift = first_real_shift(assignment)
                if shift == "-":
                    continue
                week_key = (month_days[day_index].isocalendar().year, month_days[day_index].isocalendar().week)
                weekly_minutes[employee_name][week_key] = (
                    weekly_minutes[employee_name].get(week_key, 0)
                    + shift_minutes_by_code.get(shift, 8 * 60)
                )

    for key, plan in sorted(saved_schedules.items()):
        if not isinstance(plan, dict) or not re.fullmatch(r"\d{4}-\d{2}", str(key)):
            continue
        year_text, month_text = str(key).split("-")
        month_days = build_month_dates(int(year_text), int(month_text))
        if not month_days:
            continue
        if month_days[-1] >= days[0] - timedelta(weeks=max(1, weekly_average_period_weeks)):
            add_month_schedule(plan.get("schedule", {}), month_days)
    add_month_schedule(schedule, days)

    for employee in employees:
        employee_weeks = weekly_minutes.get(employee.name, {})
        known_weeks = set(employee_weeks)
        for current_week in current_weeks:
            week_start = date.fromisocalendar(current_week[0], current_week[1], 1)
            for offset in range(max(1, weekly_average_period_weeks)):
                check_day = week_start - timedelta(weeks=offset)
                iso = check_day.isocalendar()
                known_weeks.add((iso.year, iso.week))
        if len(employee_weeks) < max(1, weekly_average_period_weeks) and current_weeks:
            warnings.append(
                f"{employee.name}: Durchrechnung nur mit {len(employee_weeks)} von {weekly_average_period_weeks} Wochen Daten prüfbar"
            )
        for current_week in current_weeks:
            week_start = date.fromisocalendar(current_week[0], current_week[1], 1)
            window_keys = []
            for offset in range(max(1, weekly_average_period_weeks)):
                check_day = week_start - timedelta(weeks=offset)
                iso = check_day.isocalendar()
                window_keys.append((iso.year, iso.week))
            if not window_keys:
                continue
            average_hours = format_minutes_as_hours(
                round(sum(employee_weeks.get(key, 0) for key in window_keys) / len(window_keys))
            )
            if average_hours > float(weekly_average_max_hours) + 0.01:
                errors.append(
                    f"{employee.name}: Ø {format_display_hours(average_hours)} h/Woche "
                    f"über {len(window_keys)} Woche(n)"
                )
                break
    return errors, warnings


def validate_schedule_rules(
    schedule: dict,
    metrics: dict,
    employees: list[Employee],
    days: list[date],
    night_shifts: list[str],
    shifts: list[str],
    holidays: dict[date, str],
    daily_requirements: dict[tuple[int, str], int],
    shift_df: pd.DataFrame,
    shift_minutes_by_code: dict[str, int],
    shift_time_by_code: dict[str, tuple[int, int]],
    max_overtime_percent: float,
    max_overtime_hours: float,
    max_undertime_percent: float,
    max_undertime_hours: float,
    block_night_before_wish_free: bool,
    previous_assignments: dict[str, list[str]] | None = None,
    open_shift_codes: list[str] | None = None,
    shift_priority_by_code: dict[str, int] | None = None,
    vacation_weekend_policy: str = DEFAULT_VACATION_WEEKEND_POLICY,
    legal_profile: str = DEFAULT_LEGAL_PROFILE,
    daily_max_work_hours: float = 12.0,
    weekly_average_max_hours: float = 48.0,
    weekly_average_period_weeks: int = 17,
    weekly_rest_hours: float = 36.0,
    reduced_weekly_rest_hours: float = 24.0,
    allow_reduced_weekly_rest: bool = True,
    saved_schedules: dict | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    previous_assignments = previous_assignments or {}

    def add(pruefung: str, status: str, ergebnis: str, empfehlung: str = "") -> None:
        rows.append(
            {
                "Status": status,
                "Prüfung": pruefung,
                "Ergebnis": ergebnis,
                "Was tun?": empfehlung or ("Keine Änderung nötig." if status == "OK" else "Einstellungen oder Bedarf prüfen."),
            }
        )

    employee_by_name = {employee.name: employee for employee in employees}
    night_set = set(night_shifts)
    day_shift_set = set(shifts) - night_set

    rest_errors = []
    night_day_errors = []
    wish_errors = []
    night_before_wish_errors = []
    sick_errors = []
    three_night_errors = []
    rest_after_night_errors = []
    hour_errors = []
    vacation_errors = []
    daily_limit_errors = []

    for employee_name, assignments in schedule.items():
        employee = employee_by_name.get(employee_name)
        if employee is None:
            continue
        real_assignments = [first_real_shift(value) for value in assignments]
        previous_plan = previous_assignments.get(employee_name, [])
        previous_shift = first_real_shift(previous_plan[-1]) if previous_plan else "-"
        if previous_shift != "-" and real_assignments:
            first_shift = real_assignments[0]
            if first_shift != "-" and not has_required_rest_between(previous_shift, first_shift, shift_time_by_code):
                rest_errors.append(f"{employee_name}: Monatswechsel vor {day_label(days[0])}")
            if previous_shift in night_set and first_shift in day_shift_set:
                night_day_errors.append(f"{employee_name}: Monatswechsel vor {day_label(days[0])}")
            if (
                block_night_before_wish_free
                and previous_shift in night_set
                and 0 in employee.blocked_days
                and employee.wish_free_priority == 1
            ):
                night_before_wish_errors.append(f"{employee_name}: Monatswechsel vor {day_label(days[0])}")
            if (
                previous_shift in night_set
                and employee.rest_after_night >= 2
                and employee.rest_priority == 1
                and first_shift not in night_set
            ):
                for rest_day in (0, 1):
                    if rest_day < len(real_assignments) and real_assignments[rest_day] != "-":
                        rest_after_night_errors.append(
                            f"{employee_name}: Monatswechsel vor {day_label(days[0])}"
                        )
                        break

        for day_index, shift in enumerate(real_assignments):
            if shift == "-":
                continue
            if day_index in employee.blocked_days and employee.wish_free_priority == 1:
                wish_errors.append(f"{employee_name}: {day_label(days[day_index])}")
            if day_index in employee.planned_sick_days:
                sick_errors.append(f"{employee_name}: {day_label(days[day_index])}")
            if day_index in vacation_protected_day_indices(employee, days, vacation_weekend_policy):
                vacation_errors.append(f"{employee_name}: {day_label(days[day_index])}")
            if shift_minutes_by_code.get(shift, 8 * 60) > int(round(float(daily_max_work_hours) * 60)):
                daily_limit_errors.append(
                    f"{employee_name}: {day_label(days[day_index])} {shift} "
                    f"({format_display_hours(format_minutes_as_hours(shift_minutes_by_code.get(shift, 0)))} h)"
                )
            if day_index < len(real_assignments) - 1:
                next_shift = real_assignments[day_index + 1]
                if next_shift != "-" and not has_required_rest_between(shift, next_shift, shift_time_by_code):
                    rest_errors.append(f"{employee_name}: {day_label(days[day_index])} auf {day_label(days[day_index + 1])}")
                if shift in night_set and next_shift in day_shift_set:
                    night_day_errors.append(f"{employee_name}: {day_label(days[day_index])} auf {day_label(days[day_index + 1])}")
            if block_night_before_wish_free and day_index < len(real_assignments) - 1:
                if shift in night_set and (day_index + 1) in employee.blocked_days and employee.wish_free_priority == 1:
                    night_before_wish_errors.append(f"{employee_name}: {day_label(days[day_index])}")
            if shift in night_set and employee.rest_after_night >= 2 and employee.rest_priority == 1:
                next_is_night = (
                    day_index + 1 < len(real_assignments)
                    and real_assignments[day_index + 1] in night_set
                )
                if not next_is_night:
                    for rest_day in (day_index + 1, day_index + 2):
                        if rest_day < len(real_assignments) and real_assignments[rest_day] != "-":
                            rest_after_night_errors.append(f"{employee_name}: {day_label(days[day_index])}")
                            break

        if not employee.allow_three_consecutive_nights:
            for day_index in range(max(0, len(real_assignments) - 2)):
                if all(real_assignments[check_day] in night_set for check_day in range(day_index, day_index + 3)):
                    three_night_errors.append(f"{employee_name}: ab {day_label(days[day_index])}")

        employee_metrics = metrics.get(employee_name, {})
        try:
            target_minutes = round(float(employee_metrics.get("Sollstunden", 0)) * 60)
            planned_minutes = round(float(employee_metrics.get("Geplante Stunden", 0)) * 60)
        except (TypeError, ValueError):
            continue
        overtime_limit = allowed_variance_minutes(target_minutes, max_overtime_percent, max_overtime_hours)
        undertime_limit = allowed_variance_minutes(target_minutes, max_undertime_percent, max_undertime_hours)
        if planned_minutes > target_minutes + overtime_limit:
            hour_errors.append(
                f"{employee_name}: {format_display_hours(format_minutes_as_hours(planned_minutes - target_minutes))} h Überstunden"
            )
        if planned_minutes < max(0, target_minutes - undertime_limit):
            hour_errors.append(
                f"{employee_name}: {format_display_hours(format_minutes_as_hours(target_minutes - planned_minutes))} h Minusstunden"
            )

    def details(values: list[str]) -> str:
        if not values:
            return "OK"
        suffix = "" if len(values) <= 5 else f" und {len(values) - 5} weitere"
        return "; ".join(values[:5]) + suffix

    add("11 Stunden Ruhezeit", "OK" if not rest_errors else "Fehler", details(rest_errors))
    add("Nach Nachtdienst kein Tagdienst", "OK" if not night_day_errors else "Fehler", details(night_day_errors))
    add("Wunschfrei Prio 1 bleibt frei", "OK" if not wish_errors else "Fehler", details(wish_errors))
    add("Geplanter Krankenstand bleibt frei", "OK" if not sick_errors else "Fehler", details(sick_errors))
    add("Urlaub bleibt frei", "OK" if not vacation_errors else "Fehler", details(vacation_errors))
    add(
        "Kein Nachtdienst vor Wunschfrei",
        "OK" if not night_before_wish_errors else "Fehler",
        details(night_before_wish_errors) if block_night_before_wish_free else "Regel ist deaktiviert.",
    )
    add("Freie Tage nach Nachtdienst", "OK" if not rest_after_night_errors else "Fehler", details(rest_after_night_errors))
    add("Max. 2 Nächte in Folge", "OK" if not three_night_errors else "Fehler", details(three_night_errors))
    add("Plus-/Minusstunden-Grenzen", "OK" if not hour_errors else "Fehler", details(hour_errors))
    add("Tageshöchstarbeitszeit", "OK" if not daily_limit_errors else "Fehler", details(daily_limit_errors))

    weekly_rest_errors, weekly_rest_warnings = weekly_rest_findings(
        schedule,
        employees,
        days,
        shift_time_by_code,
        previous_assignments,
        weekly_rest_hours,
        reduced_weekly_rest_hours,
        allow_reduced_weekly_rest,
    )
    if weekly_rest_errors:
        add("Wochenruhe", "Fehler", details(weekly_rest_errors), "Dienste so ändern, dass je Woche eine ausreichend lange Ruhephase entsteht.")
    elif weekly_rest_warnings:
        add(
            "Wochenruhe",
            "Hinweis",
            details(weekly_rest_warnings),
            "Bei Schichtarbeit prüfen, ob die verkürzte Wochenruhe im 4-Wochen-Schnitt ausgeglichen ist.",
        )
    else:
        add("Wochenruhe", "OK", f"{format_display_hours(weekly_rest_hours)} h Wochenruhe werden eingehalten.")

    rolling_errors, rolling_warnings = rolling_weekly_hours_findings(
        schedule,
        employees,
        days,
        shift_minutes_by_code,
        saved_schedules,
        weekly_average_max_hours,
        weekly_average_period_weeks,
    )
    if rolling_errors:
        add(
            "48h-Durchrechnung",
            "Fehler",
            details(rolling_errors),
            "Wochenstunden senken, Dienste verschieben oder Durchrechnungszeitraum/KV-Regel prüfen.",
        )
    elif rolling_warnings:
        add(
            "48h-Durchrechnung",
            "Hinweis",
            details(rolling_warnings),
            "Für eine vollständige Prüfung müssen genug fixierte Vormonate vorhanden sein.",
        )
    else:
        add(
            "48h-Durchrechnung",
            "OK",
            f"Ø-Grenze {format_display_hours(weekly_average_max_hours)} h über {weekly_average_period_weeks} Wochen im Profil {legal_profile}.",
        )

    open_services = open_services_dataframe(
        schedule,
        days,
        daily_requirements,
        shift_df,
        open_shift_codes=open_shift_codes,
        shift_priority_by_code=shift_priority_by_code,
    )
    hard_open_services = (
        open_services[open_services["Prioritaet"].astype(int) == 1]
        if not open_services.empty and "Prioritaet" in open_services.columns
        else pd.DataFrame()
    )
    if hard_open_services.empty:
        add("Offene Pflichtdienste", "OK", "Alle Prio-1-Dienste wurden besetzt.")
    else:
        add(
            "Offene Pflichtdienste",
            "Fehler",
            f"{int(hard_open_services['Offen'].sum())} Prio-1-Dienst(e) bleiben offen.",
            "Pflichtdienste prüfen, Personal erhöhen oder harte Grenzwerte lockern.",
        )

    return rows


def plan_quality_score(
    schedule: dict,
    metrics: dict,
    days: list[date],
    daily_requirements: dict[tuple[int, str], int],
    shift_df: pd.DataFrame,
    open_shift_codes: list[str],
    shift_priority_by_code: dict[str, int],
    plan_strategy: str = DEFAULT_PLAN_OPTIMIZATION_MODE,
) -> float:
    if not schedule:
        return -10_000_000
    profile = optimization_profile(plan_strategy)
    open_penalty = schedule_shortage_penalty(
        schedule,
        days,
        daily_requirements,
        shift_df,
        open_shift_codes,
        shift_priority_by_code,
    )
    metrics_df = pd.DataFrame.from_dict(metrics, orient="index") if metrics else pd.DataFrame()
    if metrics_df.empty:
        return -open_penalty
    active_warnings = float(metrics_df.get("Aktive Warnungen", pd.Series(dtype=float)).sum())
    max_hour_deviation = float(metrics_df.get("Stundenabweichung h", pd.Series([0])).max() or 0)
    satisfaction_series = pd.to_numeric(
        metrics_df.get("Zufriedenheit %", pd.Series([0])),
        errors="coerce",
    ).fillna(0)
    avg_satisfaction = float(satisfaction_series.mean() or 0)
    min_satisfaction = float(satisfaction_series.min() or 0)
    weighted_open_penalty = open_penalty * profile["ranking_open_weight_percent"] / 100
    return (
        avg_satisfaction * 100
        + min_satisfaction * profile["ranking_min_satisfaction_weight"]
        - weighted_open_penalty
        - active_warnings * profile["ranking_warning_weight"]
        - max_hour_deviation * profile["ranking_hour_weight"]
    )


def average_satisfaction_value(metrics: dict) -> float:
    metrics_df = pd.DataFrame.from_dict(metrics, orient="index") if metrics else pd.DataFrame()
    if metrics_df.empty or "Zufriedenheit %" not in metrics_df:
        return 0.0
    return float(
        pd.to_numeric(metrics_df["Zufriedenheit %"], errors="coerce").fillna(0).mean()
        or 0
    )


def min_satisfaction_value(metrics: dict) -> float:
    metrics_df = pd.DataFrame.from_dict(metrics, orient="index") if metrics else pd.DataFrame()
    if metrics_df.empty or "Zufriedenheit %" not in metrics_df:
        return 0.0
    return float(
        pd.to_numeric(metrics_df["Zufriedenheit %"], errors="coerce").fillna(0).min()
        or 0
    )


def active_warning_value(metrics: dict) -> int:
    metrics_df = pd.DataFrame.from_dict(metrics, orient="index") if metrics else pd.DataFrame()
    if metrics_df.empty or "Aktive Warnungen" not in metrics_df:
        return 0
    return int(pd.to_numeric(metrics_df["Aktive Warnungen"], errors="coerce").fillna(0).sum())


def traffic_light_label(level: str) -> str:
    return {
        "green": "Grün",
        "yellow": "Gelb",
        "red": "Rot",
        "neutral": "Info",
    }.get(str(level), "Info")


def traffic_light_class(level: str) -> str:
    return {
        "green": "#16a34a",
        "yellow": "#d97706",
        "red": "#dc2626",
        "neutral": "#64748b",
    }.get(str(level), "#64748b")


def render_traffic_light_cards(rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    st.markdown(
        """
<style>
.quality-light-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 0.75rem; margin: 0.25rem 0 1rem 0; }
.quality-light-card { border: 1px solid #e5e7eb; border-radius: 8px; background: #ffffff; padding: 0.85rem 0.95rem; min-height: 112px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }
.quality-light-top { display: flex; align-items: center; gap: 0.5rem; font-weight: 700; color: #111827; margin-bottom: 0.35rem; }
.quality-light-dot { width: 0.75rem; height: 0.75rem; border-radius: 999px; flex: 0 0 auto; }
.quality-light-status { color: #4b5563; font-size: 0.86rem; margin-bottom: 0.3rem; }
.quality-light-detail { color: #6b7280; font-size: 0.8rem; line-height: 1.35; }
</style>
""",
        unsafe_allow_html=True,
    )
    cards = []
    for row in rows:
        color = traffic_light_class(str(row.get("level", "neutral")))
        title = html.escape(str(row.get("title", "")))
        status = html.escape(str(row.get("status", "")))
        detail = html.escape(str(row.get("detail", "")))
        cards.append(
            f'<div class="quality-light-card">'
            f'<div class="quality-light-top">'
            f'<span class="quality-light-dot" style="background:{color}"></span>'
            f'<span>{title}</span>'
            f'</div>'
            f'<div class="quality-light-status">{status}</div>'
            f'<div class="quality-light-detail">{detail}</div>'
            f'</div>'
        )
    st.markdown('<div class="quality-light-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def plan_quality_signal_rows(
    metrics_df: pd.DataFrame,
    rule_checks: list[dict[str, str]] | None,
    open_service_count: int,
    solver_status: str | None,
) -> list[dict[str, str]]:
    rule_checks = rule_checks or []
    rule_error_count = sum(1 for check in rule_checks if check.get("Status") == "Fehler")
    rule_hint_count = sum(1 for check in rule_checks if check.get("Status") == "Hinweis")
    average_satisfaction = (
        float(pd.to_numeric(metrics_df.get("Zufriedenheit %", pd.Series([0])), errors="coerce").fillna(0).mean() or 0)
        if not metrics_df.empty
        else 0.0
    )
    minimum_satisfaction = (
        float(pd.to_numeric(metrics_df.get("Zufriedenheit %", pd.Series([0])), errors="coerce").fillna(0).min() or 0)
        if not metrics_df.empty
        else 0.0
    )
    active_warnings = (
        int(pd.to_numeric(metrics_df.get("Aktive Warnungen", pd.Series([0])), errors="coerce").fillna(0).sum())
        if not metrics_df.empty
        else 0
    )
    rows: list[dict[str, str]] = []
    if rule_error_count:
        rows.append(
            {
                "level": "red",
                "title": "Rechtliche Prüfung",
                "status": f"{rule_error_count} Fehler",
                "detail": "Plan nicht fixieren. Zuerst die Fehler in der Regelprüfung beheben.",
            }
        )
    elif rule_hint_count:
        rows.append(
            {
                "level": "yellow",
                "title": "Rechtliche Prüfung",
                "status": f"OK mit {rule_hint_count} Hinweis(en)",
                "detail": "Harte Regeln sind erfüllt. Hinweise wie Durchrechnung oder Wochenruhe bewusst prüfen.",
            }
        )
    else:
        rows.append(
            {
                "level": "green",
                "title": "Rechtliche Prüfung",
                "status": "OK",
                "detail": "Keine harten Regelverletzungen gefunden.",
            }
        )

    if average_satisfaction >= 90 and minimum_satisfaction >= 70 and active_warnings <= 10:
        quality_level = "green"
        quality_status = "sehr gut"
        quality_detail = "Zufriedenheit und schlechteste Einzelwerte liegen im Zielbereich."
    elif average_satisfaction >= 80 and minimum_satisfaction >= 55:
        quality_level = "yellow"
        quality_status = "brauchbar, aber verbesserbar"
        quality_detail = "Plan ist verwendbar. Die Handlungsanweisungen zeigen, wo Zufriedenheit verloren geht."
    else:
        quality_level = "red"
        quality_status = "zu niedrig"
        quality_detail = "Plan nicht vorschnell fixieren. Wünsche, Personalverfügbarkeit oder Bedarf prüfen."
    rows.append(
        {
            "level": quality_level,
            "title": "Planqualität",
            "status": f"{format_display_hours(round(average_satisfaction, 1))} % Ø, min. {format_display_hours(round(minimum_satisfaction, 1))} %",
            "detail": quality_detail if quality_status else "",
        }
    )

    if open_service_count == 0:
        rows.append(
            {
                "level": "green",
                "title": "Abdeckung",
                "status": "alles besetzt",
                "detail": "Alle angeforderten Dienste wurden besetzt.",
            }
        )
    elif open_service_count <= 10:
        rows.append(
            {
                "level": "yellow",
                "title": "Abdeckung",
                "status": f"{open_service_count} offene Dienste",
                "detail": "Offene Dienste prüfen. Sie können erlaubt sein, drücken aber die Planqualität.",
            }
        )
    else:
        rows.append(
            {
                "level": "red",
                "title": "Abdeckung",
                "status": f"{open_service_count} offene Dienste",
                "detail": "Viele Dienste bleiben offen. Bedarf, Prioritäten oder Personalbestand prüfen.",
            }
        )

    if solver_status == "OPTIMAL":
        rows.append(
            {
                "level": "green",
                "title": "Beweisgrad",
                "status": "optimal bewiesen",
                "detail": "Der Solver hat sein internes Ziel vollständig bewiesen.",
            }
        )
    elif solver_status == "FEASIBLE":
        rows.append(
            {
                "level": "yellow",
                "title": "Beweisgrad",
                "status": "gültig, nicht optimal bewiesen",
                "detail": "Der Plan ist gültig. Weiter optimieren kann noch bessere Varianten finden.",
            }
        )
    else:
        rows.append(
            {
                "level": "red",
                "title": "Beweisgrad",
                "status": solver_status_text(solver_status),
                "detail": solver_status_detail(solver_status),
            }
        )
    return rows


def scenario_readiness_dataframe(
    preflight_df: pd.DataFrame,
    service_diagnostics_df: pd.DataFrame,
    staffing_summary: dict[str, float],
    previous_assignments: dict[str, list[str]],
    employees: list[Employee],
    days: list[date],
    holidays: dict[date, str],
    vacation_weekend_policy: str,
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    blocker_count = int((preflight_df["Status"] == "Blocker").sum()) if not preflight_df.empty else 0
    service_conflicts = len(service_diagnostics_df) if service_diagnostics_df is not None else 0
    hard_margin = float(staffing_summary.get("hard_margin_hours", 0) or 0)
    too_many = float(staffing_summary.get("too_many_personnel_hours", 0) or 0)
    too_few = float(staffing_summary.get("too_few_personnel_hours", 0) or 0)

    if blocker_count:
        normal_level = "Rot"
        normal_result = f"{blocker_count} Blocker"
        normal_action = "Blocker vor dem Generieren beheben."
    elif service_conflicts:
        normal_level = "Gelb"
        normal_result = f"{service_conflicts} Engpass-Tage"
        normal_action = "Engpässe je Tag/Dienstform prüfen."
    else:
        normal_level = "Grün"
        normal_result = "keine schnellen Blocker"
        normal_action = "Generierung ist sinnvoll."
    rows.append(
        {
            "Szenario": "Normalmonat",
            "Ampel": normal_level,
            "Was geprüft wird": "Personalstunden, Pflichtdienste, Sperrtage, Nachtkapazität",
            "Ergebnis": normal_result,
            "Nächster Schritt": normal_action,
        }
    )

    protected_days = 0
    for employee in employees:
        protected_days += len(set(employee.blocked_days))
        protected_days += len(set(employee.planned_sick_days))
        protected_days += len(vacation_protected_day_indices(employee, days, vacation_weekend_policy))
    holiday_count = sum(1 for current_day in days if current_day in holidays)
    weekend_count = sum(1 for current_day in days if current_day.weekday() >= 5)
    protected_ratio = (
        protected_days / max(1, len(employees) * len(days))
        if employees and days
        else 0
    )
    if too_many > 0 or too_few > 0:
        stress_level = "Rot"
        stress_result = "Stundenrahmen passt nicht"
        stress_action = "Sollstunden, Dienstbedarf oder Plus-/Minusstunden-Grenzen anpassen."
    elif service_conflicts or hard_margin < 0 or protected_ratio >= 0.12 or holiday_count >= 3:
        stress_level = "Gelb"
        stress_result = "enger Monat"
        stress_action = "Vor dem Fixieren offene Dienste und Engpass-Tage prüfen."
    else:
        stress_level = "Grün"
        stress_result = "Stressfaktoren planbar"
        stress_action = "Generieren und danach Zufriedenheit prüfen."
    rows.append(
        {
            "Szenario": "Engpassmonat",
            "Ampel": stress_level,
            "Was geprüft wird": "Feiertage, Wochenenden, Urlaub, Wunschfrei, Krankenstand",
            "Ergebnis": f"{holiday_count} Feiertag(e), {weekend_count} Samstage/Sonntage, {protected_days} geschützte Personentage",
            "Nächster Schritt": stress_action,
        }
    )

    takeover_people = [name for name, plan in (previous_assignments or {}).items() if plan]
    if takeover_people:
        takeover_blockers = (
            preflight_df[
                preflight_df.get("Thema", pd.Series(dtype=str)).astype(str).str.contains("Monatsübergang|Übernahme", case=False, na=False)
            ]
            if not preflight_df.empty
            else pd.DataFrame()
        )
        takeover_level = "Rot" if not takeover_blockers.empty and (takeover_blockers["Status"] == "Blocker").any() else "Grün"
        takeover_result = f"{len(takeover_people)} Person(en) mit Vormonat/Übernahmestand"
        takeover_action = "Monatsübergang wird berücksichtigt." if takeover_level == "Grün" else "Übernahmestand/Vormonat prüfen."
    else:
        takeover_level = "Info"
        takeover_result = "nicht aktiv"
        takeover_action = "Für Start aus altem System Übernahmestände bestätigen."
    rows.append(
        {
            "Szenario": "Übernahme-/Startmonat",
            "Ampel": takeover_level,
            "Was geprüft wird": "Nachtdienst vor Start, Arbeitstage in Folge, Start-Zeitkonto",
            "Ergebnis": takeover_result,
            "Nächster Schritt": takeover_action,
        }
    )
    return pd.DataFrame(rows)


def legal_guardrail_dataframe(
    legal_profile: str,
    daily_max_work_hours: float,
    weekly_average_max_hours: float,
    weekly_average_period_weeks: int,
    weekly_rest_hours: float,
    reduced_weekly_rest_hours: float,
    allow_reduced_weekly_rest: bool,
    replacement_rest_kind: str,
    replacement_rest_scope: str,
    vacation_weekend_policy: str,
    night_credit_mode: str = DEFAULT_NIGHT_CREDIT_MODE,
    night_credit_hours: float = DEFAULT_NIGHT_CREDIT_HOURS,
    time_account_usage: str = DEFAULT_TIME_ACCOUNT_USAGE,
    pause_policy: str = DEFAULT_PAUSE_POLICY,
    pause_threshold_hours: float = DEFAULT_PAUSE_THRESHOLD_HOURS,
    pause_duration_minutes: int = DEFAULT_PAUSE_DURATION_MINUTES,
) -> pd.DataFrame:
    rest_text = (
        f"{format_display_hours(reduced_weekly_rest_hours)} h Mindestwert, "
        f"{format_display_hours(weekly_rest_hours)} h im Schnitt"
        if allow_reduced_weekly_rest
        else f"{format_display_hours(weekly_rest_hours)} h"
    )
    rows = [
        {
            "Leitplanke": "Rechtsprofil",
            "Aktuelle Einstellung": str(legal_profile),
            "Wirkt als": "Voreinstellung",
            "Hinweis für NutzerInnen": "Profil muss zu KV, Betriebsvereinbarung und Berufsgruppe passen.",
        },
        {
            "Leitplanke": "Tageshöchstarbeitszeit",
            "Aktuelle Einstellung": f"{format_display_hours(daily_max_work_hours)} h",
            "Wirkt als": "harte Regel",
            "Hinweis für NutzerInnen": "Dienstformen über dieser Grenze werden nicht eingeplant.",
        },
        {
            "Leitplanke": "Wöchentliche Ruhezeit",
            "Aktuelle Einstellung": rest_text,
            "Wirkt als": "harte Regel/Hinweis",
            "Hinweis für NutzerInnen": "Bei Schichtarbeit sind 24 h nur mit Ausgleich im 4-Wochen-Schnitt sauber.",
        },
        {
            "Leitplanke": "48h-Durchrechnung",
            "Aktuelle Einstellung": f"{format_display_hours(weekly_average_max_hours)} h über {weekly_average_period_weeks} Wochen",
            "Wirkt als": "Regelprüfung",
            "Hinweis für NutzerInnen": "Wird verlässlicher, sobald mehrere Monate fixiert sind.",
        },
        {
            "Leitplanke": "Ruhepause",
            "Aktuelle Einstellung": pause_policy_description(
                pause_policy,
                pause_threshold_hours,
                pause_duration_minutes,
            ),
            "Wirkt als": "Dienststundenberechnung",
            "Hinweis für NutzerInnen": "Pausenregel muss zu Vertrag, KV und gelebter Dienstform passen.",
        },
        {
            "Leitplanke": "Ersatzruhe/Zeitausgleich",
            "Aktuelle Einstellung": f"{replacement_rest_kind}, {replacement_rest_scope}",
            "Wirkt als": "Berechnung und Hinweis",
            "Hinweis für NutzerInnen": "Feiertags-Zeitausgleich braucht je nach Vertrag/KV eine saubere Grundlage.",
        },
        {
            "Leitplanke": "Nachtgutschrift",
            "Aktuelle Einstellung": f"{normalize_night_credit_mode(night_credit_mode)}, {format_display_hours(night_credit_hours)} h pro Nachtdienst",
            "Wirkt als": "Zeitkonto/Berechnung",
            "Hinweis für NutzerInnen": "Nachtgutschriften sind KV-/vertragsabhängig und hier bewusst einstellbar.",
        },
        {
            "Leitplanke": "Zeitkonto-Ausgleich",
            "Aktuelle Einstellung": normalize_time_account_usage(time_account_usage),
            "Wirkt als": "Optimierungsziel",
            "Hinweis für NutzerInnen": "Steuert, wie stark Plus-/Minusstunden aus dem Start-Zeitkonto in neuen Plänen abgebaut werden.",
        },
        {
            "Leitplanke": "Urlaub",
            "Aktuelle Einstellung": str(vacation_weekend_policy),
            "Wirkt als": "harte Abwesenheit",
            "Hinweis für NutzerInnen": "Urlaub zählt als bezahlte Dienstzeit; Anspruch läuft je Stichtag/Urlaubsjahr.",
        },
    ]
    return pd.DataFrame(rows)


def planning_workflow_dataframe(
    employee_count: int,
    employee_warning_count: int,
    blocker_count: int,
    warning_count: int,
    generated_plan_exists: bool,
    saved_plan_exists: bool,
    can_generate: bool,
) -> pd.DataFrame:
    rows = []
    rows.append(
        {
            "Schritt": "1. Mitarbeiter & Abwesenheiten",
            "Status": "prüfen" if employee_warning_count else "OK",
            "Was bedeutet das?": (
                f"{employee_count} dienstplanrelevante Personen, {employee_warning_count} Hinweis(e)"
                if employee_warning_count
                else f"{employee_count} dienstplanrelevante Personen bereit"
            ),
            "Nächster Klick": "Mitarbeiter & Wünsche öffnen" if employee_warning_count else "weiter",
        }
    )
    if blocker_count:
        setup_status = "Blocker"
        setup_next = "Blocker in der Machbarkeitsprüfung beheben"
    elif warning_count:
        setup_status = "Warnungen"
        setup_next = "Engpässe ansehen, dann bewusst generieren"
    else:
        setup_status = "OK"
        setup_next = "Dienstplan generieren"
    rows.append(
        {
            "Schritt": "2. Machbarkeit prüfen",
            "Status": setup_status,
            "Was bedeutet das?": f"{blocker_count} Blocker, {warning_count} Warnungen",
            "Nächster Klick": setup_next,
        }
    )
    rows.append(
        {
            "Schritt": "3. Dienstplan generieren",
            "Status": "bereit" if can_generate else "gesperrt",
            "Was bedeutet das?": "Monat darf geplant werden" if can_generate else "Vormonat fehlt oder Startmonat passt nicht",
            "Nächster Klick": "Dienstplan generieren" if can_generate and not generated_plan_exists else "Plan prüfen",
        }
    )
    rows.append(
        {
            "Schritt": "4. Qualität prüfen",
            "Status": "Plan vorhanden" if generated_plan_exists else "wartet",
            "Was bedeutet das?": "Qualitätsampel, Regelprüfung und Ursachen ansehen" if generated_plan_exists else "Noch kein Entwurf vorhanden",
            "Nächster Klick": "Weiter optimieren oder speichern" if generated_plan_exists else "erst generieren",
        }
    )
    rows.append(
        {
            "Schritt": "5. Fixieren",
            "Status": "fixiert" if saved_plan_exists else "offen",
            "Was bedeutet das?": "Monat ist gespeichert" if saved_plan_exists else "Plan ist noch nicht verbindlich",
            "Nächster Klick": "nächsten Monat planen" if saved_plan_exists else "Plan speichern und fixieren",
        }
    )
    return pd.DataFrame(rows)


def failure_next_steps_dataframe(
    preflight_df: pd.DataFrame,
    service_diagnostics_df: pd.DataFrame,
    diagnosis_reasons: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    if preflight_df is not None and not preflight_df.empty:
        blocker_df = preflight_df[preflight_df["Status"].isin(["Blocker", "Warnung"])]
        for _, row in blocker_df.head(5).iterrows():
            rows.append(
                {
                    "Priorität": "1" if row.get("Status") == "Blocker" else "2",
                    "Ursache": str(row.get("Thema", "")),
                    "Beleg": str(row.get("Hinweis", "")),
                    "Was tun?": str(row.get("Was tun?", "")),
                }
            )

    if service_diagnostics_df is not None and not service_diagnostics_df.empty:
        reason_counter: dict[str, int] = {}
        missing_total = int(pd.to_numeric(service_diagnostics_df.get("Fehlt", pd.Series(dtype=int)), errors="coerce").fillna(0).sum())
        for reason_text in service_diagnostics_df.get("Wichtigste Gründe", pd.Series(dtype=str)).fillna("-"):
            for part in str(reason_text).split(","):
                reason = part.split(":")[0].strip()
                if reason and reason != "-":
                    reason_counter[reason] = reason_counter.get(reason, 0) + 1
        main_reason = max(reason_counter.items(), key=lambda item: item[1])[0] if reason_counter else "zu wenige geeignete Personen"
        action = {
            "Urlaub": "Urlaubswochen verschieben oder Ersatzpersonal einplanen.",
            "Krankenstand": "Krankenstand bleibt frei; Bedarf an diesen Tagen senken oder anderes Personal freigeben.",
            "Wunschfrei Prio 1": "Prio-1-Wunschfrei nur bei wirklich zwingenden Tagen verwenden oder Bedarf senken.",
            "keine Nächte erlaubt": "Mehr Personen für Nachtdienste freigeben oder Nachtbedarf reduzieren.",
            "Nachtwunsch sperrt": "Nachtwunsch-Prioritäten prüfen oder Nachtgrenzen geeigneter Personen erhöhen.",
            "Nach Nacht aus Vormonat": "Vormonat/Übernahmestand prüfen; nach Nacht keinen Tagdienst planen.",
        }.get(main_reason, "Engpass-Tage öffnen und dort Bedarf, Urlaub, Wunschfrei und Nachtfähigkeit prüfen.")
        rows.append(
            {
                "Priorität": "1",
                "Ursache": "Konkrete Tages-/Dienstform-Engpässe",
                "Beleg": f"{len(service_diagnostics_df)} Engpass-Zeilen, {missing_total} fehlende Besetzungen; Hauptgrund: {main_reason}",
                "Was tun?": action,
            }
        )

    for reason in diagnosis_reasons:
        if reason.startswith("Hauptgrund:"):
            rows.insert(
                0,
                {
                    "Priorität": "1",
                    "Ursache": "Hauptgrund",
                    "Beleg": reason,
                    "Was tun?": "Diesen Punkt zuerst ändern und danach neu generieren.",
                },
            )
            break
    if not rows:
        rows.append(
            {
                "Priorität": "1",
                "Ursache": "Kombination harter Regeln",
                "Beleg": "Die Schnellprüfung findet keinen einzelnen einfachen Blocker.",
                "Was tun?": "Dienstbedarf testweise reduzieren oder Regeln schrittweise lockern, um den Konflikt einzugrenzen.",
            }
        )
    return pd.DataFrame(rows).drop_duplicates()


def variant_time_budget_seconds(
    best_metrics: dict,
    selected_mode: object,
    *,
    holiday_heavy: bool = False,
) -> int:
    average_satisfaction = average_satisfaction_value(best_metrics)
    minimum_satisfaction = min_satisfaction_value(best_metrics)
    active_warnings = active_warning_value(best_metrics)
    if active_warnings == 0 and average_satisfaction >= 95 and minimum_satisfaction >= 70:
        return 20 if not holiday_heavy else 26
    if normalize_plan_optimization_mode(selected_mode) == "Zufriedenheit zuerst":
        return 35 if not holiday_heavy else 45
    return 30 if not holiday_heavy else 38


def json_ready_value(value: object) -> object:
    if isinstance(value, (date, dt_time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_ready_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_ready_value(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def dataframe_cache_payload(df: pd.DataFrame) -> dict[str, object]:
    normalized_df = df.copy()
    return {
        "columns": [str(column) for column in normalized_df.columns],
        "rows": [
            {str(key): json_ready_value(value) for key, value in row.items()}
            for row in normalized_df.to_dict(orient="records")
        ],
    }


def load_best_plan_cache() -> dict:
    if not BEST_PLAN_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(BEST_PLAN_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("cache_version") != CACHE_ALGORITHM_VERSION:
        return {}
    plans = data.get("plans", {})
    return plans if isinstance(plans, dict) else {}


def prune_best_plan_cache(cache: dict, limit: int = 60) -> dict:
    if len(cache) <= limit:
        return dict(cache)
    return dict(list(cache.items())[-limit:])


def save_best_plan_cache(cache: dict) -> None:
    payload = {
        "cache_version": CACHE_ALGORITHM_VERSION,
        "plans": prune_best_plan_cache(cache),
    }
    try:
        BEST_PLAN_CACHE_FILE.write_text(
            json.dumps(json_ready_value(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def stable_seed_from_key(cache_key: str) -> int:
    return max(1, int(cache_key[:8], 16) % 1_000_000)


def generation_cache_key(
    *,
    year: int,
    month: int,
    calculation_mode: str,
    optimization_mode: str,
    employees_df: pd.DataFrame,
    shifts_df: pd.DataFrame,
    resources_df: pd.DataFrame,
    daily_requirements: dict[tuple[int, str], int],
    day_requirement_overrides: dict,
    month_key: str,
    open_shift_codes: list[str],
    previous_assignments: dict[str, list[str]],
    settings: dict[str, object],
) -> str:
    payload = {
        "algorithm": CACHE_ALGORITHM_VERSION,
        "year": int(year),
        "month": int(month),
        "calculation_mode": normalize_calculation_mode(calculation_mode),
        "optimization_mode": normalize_plan_optimization_mode(optimization_mode),
        "employees": dataframe_cache_payload(employees_df),
        "shifts": dataframe_cache_payload(shifts_df),
        "resources": dataframe_cache_payload(resources_df),
        "daily_requirements": [
            [int(day_index), str(shift), int(amount)]
            for (day_index, shift), amount in sorted(daily_requirements.items())
        ],
        "overrides": json_ready_value(day_requirement_overrides.get(month_key, {})),
        "open_shift_codes": list(open_shift_codes),
        "previous_assignments": json_ready_value(previous_assignments),
        "settings": json_ready_value(settings),
    }
    source = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def solver_status_rank(status: str | None) -> int:
    return 2 if status == "OPTIMAL" else 1 if status == "FEASIBLE" else 0


def solver_status_text(status: str | None) -> str:
    if status == "OPTIMAL":
        return "Optimal bewiesen"
    if status == "FEASIBLE":
        return "Gültig"
    if status:
        return {
            "INFEASIBLE": "Nicht möglich",
            "UNKNOWN": "Nicht bewiesen",
            "MODEL_INVALID": "Modellfehler",
        }.get(str(status), str(status))
    return "nicht bekannt"


def solver_status_detail(status: str | None) -> str:
    if status == "OPTIMAL":
        return "Internes Solver-Ziel vollständig bewiesen."
    if status == "FEASIBLE":
        return "Gültiger Plan gefunden, aber nicht optimal bewiesen."
    if status == "INFEASIBLE":
        return "Keine gültige Lösung für die harten Regeln."
    if status == "UNKNOWN":
        return "Suche ohne endgültigen Beweis beendet."
    return "Status der Optimierung."


def render_status_card(label: str, value: str, detail: str) -> None:
    st.markdown(
        f"""
        <div class="status-card">
            <div class="status-card-label">{html.escape(label)}</div>
            <div class="status-card-value">{html.escape(value)}</div>
            <div class="status-card-detail">{html.escape(detail)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def plan_comparison_key(
    schedule: dict,
    metrics: dict,
    days: list[date],
    daily_requirements: dict[tuple[int, str], int],
    shift_df: pd.DataFrame,
    open_shift_codes: list[str],
    shift_priority_by_code: dict[str, int],
    plan_strategy: str,
    calculation_mode: str,
    status: str | None = None,
) -> tuple[float, ...]:
    if not schedule:
        return (-1_000_000_000.0,)
    metrics_df = pd.DataFrame.from_dict(metrics, orient="index") if metrics else pd.DataFrame()
    open_penalty = float(
        schedule_shortage_penalty(
            schedule,
            days,
            daily_requirements,
            shift_df,
            open_shift_codes,
            shift_priority_by_code,
        )
    )
    if metrics_df.empty:
        return (-open_penalty, float(solver_status_rank(status)))
    satisfaction_series = pd.to_numeric(
        metrics_df.get("Zufriedenheit %", pd.Series([0])),
        errors="coerce",
    ).fillna(0)
    min_satisfaction = float(satisfaction_series.min() or 0)
    avg_satisfaction = float(satisfaction_series.mean() or 0)
    active_warnings = float(metrics_df.get("Aktive Warnungen", pd.Series(dtype=float)).sum())
    max_hour_deviation = float(
        pd.to_numeric(metrics_df.get("Stundenabweichung h", pd.Series([0])), errors="coerce").fillna(0).max()
    )
    priority_totals = [
        float(metrics_df.get(f"Verletzungen Prio {priority}", pd.Series(dtype=float)).sum())
        for priority in range(1, 6)
    ]
    quality_score = plan_quality_score(
        schedule,
        metrics,
        days,
        daily_requirements,
        shift_df,
        open_shift_codes,
        shift_priority_by_code,
        plan_strategy,
    )
    normalized_strategy = normalize_plan_optimization_mode(plan_strategy)
    if normalized_strategy == "Abdeckung zuerst":
        return (
            -open_penalty,
            -priority_totals[0],
            -active_warnings,
            min_satisfaction,
            avg_satisfaction,
            quality_score,
            -max_hour_deviation,
            float(solver_status_rank(status)),
        )
    return (
        -priority_totals[0],
        -active_warnings,
        min_satisfaction,
        avg_satisfaction,
        quality_score,
        -priority_totals[1],
        -priority_totals[2],
        -open_penalty,
        -max_hour_deviation,
        float(solver_status_rank(status)),
    )


def better_plan_payload(
    current_plan: dict | None,
    candidate_plan: dict,
    *,
    days: list[date],
    daily_requirements: dict[tuple[int, str], int],
    shift_df: pd.DataFrame,
    open_shift_codes: list[str],
    shift_priority_by_code: dict[str, int],
) -> dict:
    if not current_plan:
        return copy.deepcopy(candidate_plan)
    current_key = plan_comparison_key(
        current_plan.get("schedule", {}),
        current_plan.get("metrics", {}),
        days,
        daily_requirements,
        shift_df,
        open_shift_codes,
        shift_priority_by_code,
        current_plan.get("plan_optimization_mode", DEFAULT_PLAN_OPTIMIZATION_MODE),
        current_plan.get("calculation_mode", DEFAULT_CALCULATION_MODE),
        current_plan.get("status"),
    )
    candidate_key = plan_comparison_key(
        candidate_plan.get("schedule", {}),
        candidate_plan.get("metrics", {}),
        days,
        daily_requirements,
        shift_df,
        open_shift_codes,
        shift_priority_by_code,
        candidate_plan.get("plan_optimization_mode", DEFAULT_PLAN_OPTIMIZATION_MODE),
        candidate_plan.get("calculation_mode", DEFAULT_CALCULATION_MODE),
        candidate_plan.get("status"),
    )
    return copy.deepcopy(candidate_plan if candidate_key > current_key else current_plan)


def diagnose_no_plan(
    employees: list[Employee],
    days: list[date],
    holidays: dict[date, str],
    daily_requirements: dict[tuple[int, str], int],
    open_shift_codes: list[str],
    shifts: list[str],
    shift_priority_by_code: dict[str, int],
    shift_minutes_by_code: dict[str, int],
    night_shifts: list[str],
    max_overtime_percent: float,
    max_overtime_hours: float,
    max_undertime_percent: float,
    max_undertime_hours: float,
    replacement_rest_scope: str,
    compensatory_rest_counts_as_hours: bool,
) -> list[str]:
    reasons = []
    replacement_rest_scope = normalize_replacement_rest_scope(replacement_rest_scope)
    open_shift_set = set(open_shift_codes)
    day_count = max((day_index for day_index, _shift in daily_requirements.keys()), default=-1) + 1
    demanded_shifts = {
        shift
        for (_day_index, shift), demand in daily_requirements.items()
        if demand > 0
    }
    hard_mandatory_shifts = sorted(
        shift
        for shift in demanded_shifts
        if shift_priority_by_code.get(shift, 1) == 1 and shift not in open_shift_set
    )
    soft_optional_shifts = sorted(
        shift
        for shift in demanded_shifts
        if shift_priority_by_code.get(shift, 1) >= 2 and shift not in open_shift_set
    )
    if hard_mandatory_shifts:
        reasons.append(
            "Hart voll besetzt sein müssen aktuell nur diese Prio-1-Dienstformen: "
            + ", ".join(hard_mandatory_shifts)
            + "."
        )
    if open_shift_codes:
        reasons.append("Zusätzlich explizit offen erlaubt sind: " + ", ".join(open_shift_codes) + ".")
    if soft_optional_shifts:
        reasons.append(
            "Diese angeforderten Dienstformen haben Prio 2 bis 3 und dürfen grundsätzlich offen bleiben: "
            + ", ".join(soft_optional_shifts)
            + "."
        )

    mandatory_required_assignments = sum(
        demand
        for (_day_index, shift), demand in daily_requirements.items()
        if shift_priority_by_code.get(shift, 1) == 1 and shift not in open_shift_set
    )
    mandatory_required_minutes = sum(
        demand * shift_minutes_by_code.get(shift, 8 * 60)
        for (_day_index, shift), demand in daily_requirements.items()
        if shift_priority_by_code.get(shift, 1) == 1 and shift not in open_shift_set
    )
    shortest_shift_minutes = min(
        (shift_minutes_by_code.get(shift, 8 * 60) for shift in shifts),
        default=8 * 60,
    )
    max_possible_assignments = 0
    max_possible_minutes = 0
    for employee in employees:
        for week_days in calendar_week_day_indices(days):
            week_length = len(week_days)
            weekly_minutes_cap = int(round(float(employee.max_weekly_planned_hours) * 60))
            weekly_assignment_cap = (
                weekly_minutes_cap // shortest_shift_minutes if shortest_shift_minutes > 0 else week_length
            )
            max_possible_assignments += min(week_length, employee.max_shifts_per_week, weekly_assignment_cap)
            max_possible_minutes += min(weekly_minutes_cap, week_length * 24 * 60)

    if max_possible_assignments < mandatory_required_assignments:
        reasons.append(
            f"Die harten Prio-1-Dienste brauchen mindestens {mandatory_required_assignments} Einsätze, "
            f"mit den aktuellen Grenzen sind aber nur etwa {max_possible_assignments} Einsätze möglich."
        )
    if max_possible_minutes < mandatory_required_minutes:
        reasons.append(
            f"Die harten Prio-1-Dienste brauchen mindestens {format_minutes_as_hours(mandatory_required_minutes)} Stunden, "
            f"mit den aktuellen Wochenstunden-Grenzen sind aber nur etwa {format_minutes_as_hours(max_possible_minutes)} Stunden möglich."
        )

    mandatory_night_demand = sum(
        demand
        for (_day_index, shift), demand in daily_requirements.items()
        if shift in night_shifts and shift_priority_by_code.get(shift, 1) == 1 and shift not in open_shift_set
    )
    max_night_capacity = sum(
        employee.max_nights_per_month
        for employee in employees
        if employee.likes_nights or employee.night_priority >= 3 or "nur nachtdienst" in employee.qualification.lower()
    )
    if mandatory_night_demand > max_night_capacity:
        reasons.append(
            f"Für harte Nachtdienste werden mindestens {mandatory_night_demand} Nachteinsätze gebraucht, "
            f"erlaubt sind aktuell aber nur etwa {max_night_capacity}."
        )

    target_month_factor = day_count / 7 if day_count else 0
    total_target_minutes = sum(
        round(employee.weekly_hours_target * 60 * target_month_factor)
        for employee in employees
    )
    total_allowed_overtime = sum(
        allowed_variance_minutes(
            round(employee.weekly_hours_target * 60 * target_month_factor),
            max_overtime_percent,
            max_overtime_hours,
        )
        for employee in employees
    )
    total_allowed_undertime = sum(
        allowed_variance_minutes(
            round(employee.weekly_hours_target * 60 * target_month_factor),
            max_undertime_percent,
            max_undertime_hours,
        )
        for employee in employees
    )
    minimum_personnel_minutes = max(0, total_target_minutes - total_allowed_undertime)
    total_assignable_minutes = sum(
        demand * shift_minutes_by_code.get(shift, 8 * 60)
        for (_day_index, shift), demand in daily_requirements.items()
    )
    if compensatory_rest_counts_as_hours:
        total_assignable_minutes += sum(
            daily_requirements.get((day_index, shift), 0) * shift_minutes_by_code.get(shift, 8 * 60)
            for day_index, current_day in enumerate(days)
            if replacement_rest_applies(current_day, holidays, replacement_rest_scope)
            for shift in shifts
        )
    if total_target_minutes > 0:
        if minimum_personnel_minutes > total_assignable_minutes:
            missing_relief_hours = format_display_hours(
                format_minutes_as_hours(minimum_personnel_minutes - total_assignable_minutes)
            )
            reasons.insert(
                0,
                "Hauptgrund: Es sind zu viele Sollstunden im Personal hinterlegt. "
                f"Auch mit den erlaubten Minusstunden müssen mindestens {format_display_hours(format_minutes_as_hours(minimum_personnel_minutes))} h verplant werden, "
                f"es gibt aber nur etwa {format_display_hours(format_minutes_as_hours(total_assignable_minutes))} h planbare Dienststunden. "
                f"Es fehlen also rund {missing_relief_hours} h Spielraum. "
                "Lösung: mehr Dienste/Ressourcen einplanen, Minusstunden-Grenze erhöhen, einzelne Wochenstunden reduzieren oder nicht benötigte Testpersonen entfernen."
            )
        if mandatory_required_minutes > total_target_minutes + total_allowed_overtime:
            reasons.append("Die Überstunden-Grenzen sind für die zwingend zu besetzenden Dienste wahrscheinlich zu streng.")

    reasons.append(
        "Zusätzlich wirken harte Regeln gleichzeitig: 11 Stunden Ruhezeit, Max. Dienste/Woche, Max. Wochenstunden, Wunschfrei mit Priorität 1, kein Nachtdienst vor Wunschfrei sowie geplanter Krankenstand."
    )
    return reasons

def staffing_hours_overview(
    employees: list[Employee],
    daily_requirements: dict[tuple[int, str], int],
    shifts: list[str],
    shift_priority_by_code: dict[str, int],
    shift_minutes_by_code: dict[str, int],
    open_shift_codes: list[str],
    day_count: int,
    max_overtime_percent: float,
    max_overtime_hours: float,
    max_undertime_percent: float,
    max_undertime_hours: float,
    days: list[date] | None = None,
    holidays: dict[date, str] | None = None,
    replacement_rest_scope: str = DEFAULT_REPLACEMENT_REST_SCOPE,
    compensatory_rest_counts_as_hours: bool = False,
    vacation_counts_as_hours: bool = True,
) -> tuple[dict[str, float], pd.DataFrame]:
    month_factor = day_count / 7 if day_count else 0
    holidays = holidays or {}
    replacement_rest_scope = normalize_replacement_rest_scope(replacement_rest_scope)
    target_minutes_by_employee = [
        round(employee.weekly_hours_target * 60 * month_factor)
        for employee in employees
    ]
    personnel_target_minutes = sum(target_minutes_by_employee)
    personnel_min_minutes = sum(
        max(
            0,
            target_minutes
            - allowed_variance_minutes(target_minutes, max_undertime_percent, max_undertime_hours),
        )
        for target_minutes in target_minutes_by_employee
    )
    personnel_max_minutes = sum(
        target_minutes
        + allowed_variance_minutes(target_minutes, max_overtime_percent, max_overtime_hours)
        for target_minutes in target_minutes_by_employee
    )
    open_shift_set = set(open_shift_codes)
    service_required_minutes = 0
    hard_required_minutes = 0
    rows = []
    for priority in sorted({shift_priority_by_code.get(shift, 1) for shift in shifts}):
        priority_shifts = [shift for shift in shifts if shift_priority_by_code.get(shift, 1) == priority]
        service_count = sum(
            daily_requirements.get((day_index, shift), 0)
            for day_index in range(day_count)
            for shift in priority_shifts
        )
        required_minutes = sum(
            daily_requirements.get((day_index, shift), 0) * shift_minutes_by_code.get(shift, 8 * 60)
            for day_index in range(day_count)
            for shift in priority_shifts
        )
        open_minutes = sum(
            daily_requirements.get((day_index, shift), 0) * shift_minutes_by_code.get(shift, 8 * 60)
            for day_index in range(day_count)
            for shift in priority_shifts
            if shift in open_shift_set or priority > 1
        )
        hard_minutes = max(0, required_minutes - open_minutes)
        service_required_minutes += required_minutes
        hard_required_minutes += hard_minutes
        rows.append(
            {
                "Prioritaet": priority,
                "Dienstformen": ", ".join(priority_shifts),
                "Dienste": service_count,
                "Bedarf h": format_display_hours(format_minutes_as_hours(required_minutes)),
                "Muss h": format_display_hours(format_minutes_as_hours(hard_minutes)),
                "Darf offen h": format_display_hours(format_minutes_as_hours(open_minutes)),
            }
        )
    replacement_rest_credit_minutes = 0
    if compensatory_rest_counts_as_hours and days:
        replacement_rest_credit_minutes = sum(
            daily_requirements.get((day_index, shift), 0) * shift_minutes_by_code.get(shift, 8 * 60)
            for day_index, current_day in enumerate(days)
            if replacement_rest_applies(current_day, holidays, replacement_rest_scope)
            for shift in shifts
        )
    vacation_credit_minutes = (
        sum(vacation_paid_minutes_for_month(employee, days, True) for employee in employees)
        if vacation_counts_as_hours and days
        else 0
    )
    total_required_minutes = service_required_minutes + replacement_rest_credit_minutes + vacation_credit_minutes
    hard_required_with_absence_minutes = hard_required_minutes + replacement_rest_credit_minutes + vacation_credit_minutes
    full_time_month_minutes = int(round(DEFAULT_FULL_TIME_WEEKLY_HOURS * 60 * month_factor))
    personnel_fte = (
        personnel_target_minutes / full_time_month_minutes
        if full_time_month_minutes > 0
        else 0
    )
    service_required_fte = (
        service_required_minutes / full_time_month_minutes
        if full_time_month_minutes > 0
        else 0
    )
    summary = {
        "personnel_target_hours": format_minutes_as_hours(personnel_target_minutes),
        "personnel_min_hours": format_minutes_as_hours(personnel_min_minutes),
        "personnel_max_hours": format_minutes_as_hours(personnel_max_minutes),
        "service_required_hours": format_minutes_as_hours(service_required_minutes),
        "required_hours": format_minutes_as_hours(total_required_minutes),
        "replacement_rest_credit_hours": format_minutes_as_hours(replacement_rest_credit_minutes),
        "vacation_credit_hours": format_minutes_as_hours(vacation_credit_minutes),
        "hard_required_hours": format_minutes_as_hours(hard_required_minutes),
        "hard_margin_hours": format_minutes_as_hours(personnel_max_minutes - hard_required_with_absence_minutes),
        "too_many_personnel_hours": format_minutes_as_hours(max(0, personnel_min_minutes - total_required_minutes)),
        "too_few_personnel_hours": format_minutes_as_hours(max(0, hard_required_with_absence_minutes - personnel_max_minutes)),
        "full_time_weekly_hours": DEFAULT_FULL_TIME_WEEKLY_HOURS,
        "full_time_month_hours": format_minutes_as_hours(full_time_month_minutes),
        "personnel_fte": round(personnel_fte, 2),
        "service_required_fte": round(service_required_fte, 2),
        "fte_difference": round(personnel_fte - service_required_fte, 2),
    }
    return summary, pd.DataFrame(rows)


def build_preflight_checks(
    employees: list[Employee],
    days: list[date],
    holidays: dict[date, str],
    daily_requirements: dict[tuple[int, str], int],
    shifts: list[str],
    night_shifts: list[str],
    shift_priority_by_code: dict[str, int],
    open_shift_codes: list[str],
    staffing_summary: dict[str, float],
    vacation_weekend_policy: str = DEFAULT_VACATION_WEEKEND_POLICY,
    previous_assignments: dict[str, list[str]] | None = None,
    block_night_before_wish_free: bool = True,
    legal_profile: str = DEFAULT_LEGAL_PROFILE,
    daily_max_work_hours: float = 12.0,
    weekly_average_max_hours: float = 48.0,
    weekly_average_period_weeks: int = 17,
    weekly_rest_hours: float = 36.0,
    reduced_weekly_rest_hours: float = 24.0,
    allow_reduced_weekly_rest: bool = True,
    shift_minutes_by_code: dict[str, int] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    open_shift_set = set(open_shift_codes)
    employee_count = len(employees)
    previous_assignments = previous_assignments or {}
    shift_minutes_by_code = shift_minutes_by_code or {}

    def add(status: str, thema: str, hinweis: str, empfehlung: str) -> None:
        rows.append(
            {
                "Status": status,
                "Thema": thema,
                "Hinweis": hinweis,
                "Was tun?": empfehlung,
            }
        )

    if employee_count == 0:
        add("Blocker", "MitarbeiterInnen", "Es sind keine MitarbeiterInnen vorhanden.", "Mindestens eine Person anlegen.")
        return pd.DataFrame(rows)

    add(
        "OK",
        "Rechtsprofil",
        (
            f"{legal_profile}: Tagesgrenze {format_display_hours(daily_max_work_hours)} h, "
            f"Wochenruhe {format_display_hours(weekly_rest_hours)} h"
            + (
                f" (Schicht-Mindestwert {format_display_hours(reduced_weekly_rest_hours)} h)"
                if allow_reduced_weekly_rest
                else ""
            )
            + f", 48h-Durchrechnung über {weekly_average_period_weeks} Wochen."
        ),
        "KV/Betriebsvereinbarung prüfen und bei Bedarf Profilwerte anpassen.",
    )

    too_long_shifts = [
        f"{shift} ({format_display_hours(format_minutes_as_hours(minutes))} h)"
        for shift, minutes in sorted(shift_minutes_by_code.items())
        if minutes > int(round(float(daily_max_work_hours) * 60))
    ]
    if too_long_shifts:
        add(
            "Blocker",
            "Tageshöchstarbeitszeit",
            "Diese Dienstformen überschreiten die Tagesgrenze: " + ", ".join(too_long_shifts),
            "Dienstform kürzen, Profil prüfen oder passende KA-AZG/KV-Regel einstellen.",
        )

    too_many_hours = float(staffing_summary.get("too_many_personnel_hours", 0))
    too_few_hours = float(staffing_summary.get("too_few_personnel_hours", 0))
    if too_many_hours > 0:
        add(
            "Blocker",
            "Zu viele Sollstunden",
            (
                f"Nach den Minusstunden-Grenzen müssen mindestens "
                f"{format_display_hours(staffing_summary.get('personnel_min_hours', 0))} h verplant werden, "
                f"planbar sind aber nur {format_display_hours(staffing_summary.get('required_hours', 0))} h."
            ),
            "Minusstunden-Grenze erhöhen, Wochenstunden reduzieren, Personal entfernen oder mehr Dienste/Ressourcen einplanen.",
        )
    else:
        add(
            "OK",
            "Personal-Mindeststunden",
            "Die aktuellen Minusstunden-Grenzen passen grundsätzlich zum Dienstbedarf.",
            "Keine Änderung nötig.",
        )

    if too_few_hours > 0:
        add(
            "Blocker",
            "Zu wenig Arbeitszeit",
            (
                f"Pflichtdienste brauchen mindestens "
                f"{format_display_hours(staffing_summary.get('hard_required_hours', 0))} h, "
                f"mit Überstunden-Grenzen sind aber nur "
                f"{format_display_hours(staffing_summary.get('personnel_max_hours', 0))} h möglich."
            ),
            "Überstunden-Grenze erhöhen, mehr Personal einplanen oder Pflichtbedarf reduzieren.",
        )
    else:
        add(
            "OK",
            "Überstunden-Grenze",
            "Die eingestellten Überstunden reichen rechnerisch für die Pflichtdienste.",
            "Keine Änderung nötig.",
        )

    max_shift_demand = max(
        (
            demand
            for (_day_index, shift), demand in daily_requirements.items()
            if shift_priority_by_code.get(shift, 1) == 1 and shift not in open_shift_set
        ),
        default=0,
    )
    max_day_demand = max(
        (
            sum(
                daily_requirements.get((day_index, shift), 0)
                for shift in shifts
                if shift_priority_by_code.get(shift, 1) == 1 and shift not in open_shift_set
            )
            for day_index in range(len(days))
        ),
        default=0,
    )
    if max_shift_demand > employee_count or max_day_demand > employee_count:
        add(
            "Blocker",
            "Tagesbedarf",
            (
                f"An einem Tag werden bis zu {max_day_demand} gleichzeitige Dienste gebraucht, "
                f"es gibt aber nur {employee_count} MitarbeiterInnen."
            ),
            "Mehr MitarbeiterInnen einplanen oder den Tagesbedarf reduzieren.",
        )

    hard_day_conflicts = []
    for day_index, current_day in enumerate(days):
        hard_demand = sum(
            daily_requirements.get((day_index, shift), 0)
            for shift in shifts
            if shift_priority_by_code.get(shift, 1) == 1 and shift not in open_shift_set
        )
        if hard_demand <= 0:
            continue
        available = sum(
            1
            for employee in employees
            if day_index not in employee.planned_sick_days
            and day_index not in vacation_protected_day_indices(employee, days, vacation_weekend_policy)
            and not (day_index in employee.blocked_days and employee.wish_free_priority == 1)
        )
        if available < hard_demand:
            hard_day_conflicts.append(f"{day_label(current_day)}: {available}/{hard_demand}")
    if hard_day_conflicts:
        add(
            "Blocker",
            "Sperrtage und Krankenstand",
            "An Pflicht-Tagen sind zu wenige Personen verfügbar: " + "; ".join(hard_day_conflicts[:6]),
            "Wunschfrei/Krankenstand prüfen, Bedarf reduzieren oder Dienstformen offen erlauben.",
        )
    else:
        add(
            "OK",
            "Sperrtage und Krankenstand",
            "An Pflicht-Tagen sind rechnerisch genug Personen verfügbar.",
            "Keine Änderung nötig.",
        )

    month_boundary_wish_conflicts = []
    if block_night_before_wish_free and days:
        for employee in employees:
            previous_plan = previous_assignments.get(employee.name, [])
            if not previous_plan:
                continue
            if (
                is_night_assignment(previous_plan[-1], night_shifts)
                and 0 in employee.blocked_days
                and employee.wish_free_priority == 1
            ):
                month_boundary_wish_conflicts.append(employee.name)
    if month_boundary_wish_conflicts:
        add(
            "Blocker",
            "Monatsübergang Wunschfrei",
            (
                "Bei diesen Personen liegt direkt vor Wunschfrei am Monatsersten ein Nachtdienst: "
                + ", ".join(month_boundary_wish_conflicts[:6])
            ),
            "Vormonat/Übernahmestand prüfen oder Wunschfrei am Monatsersten anpassen.",
        )

    hard_night_demand = sum(
        demand
        for (_day_index, shift), demand in daily_requirements.items()
        if shift in night_shifts and shift_priority_by_code.get(shift, 1) == 1 and shift not in open_shift_set
    )
    night_capacity = sum(
        employee.max_nights_per_month
        for employee in employees
        if employee.max_nights_per_month > 0
        and (employee.likes_nights or employee.night_priority >= 3 or "nur nachtdienst" in employee.qualification.lower())
    )
    if hard_night_demand > night_capacity:
        add(
            "Blocker",
            "Nachtdienste",
            f"Pflicht-Nachtdienste brauchen {hard_night_demand} Einsätze, erlaubt sind aktuell nur etwa {night_capacity}.",
            "Mehr nachtgeeignete Personen, höhere Nachtgrenzen oder Nachtbedarf reduzieren.",
        )
    elif hard_night_demand > 0:
        add(
            "OK",
            "Nachtdienste",
            "Die Nachtkapazität reicht rechnerisch für die Pflicht-Nachtdienste.",
            "Keine Änderung nötig.",
        )

    if not rows:
        add("OK", "Machbarkeit", "Es wurden keine rechnerischen Blocker gefunden.", "Du kannst den Dienstplan generieren.")
    return pd.DataFrame(rows)


def service_level_diagnostics(
    employees: list[Employee],
    days: list[date],
    holidays: dict[date, str],
    daily_requirements: dict[tuple[int, str], int],
    shifts: list[str],
    night_shifts: list[str],
    shift_df: pd.DataFrame,
    shift_priority_by_code: dict[str, int],
    open_shift_codes: list[str],
    previous_assignments: dict[str, list[str]] | None = None,
    block_night_before_wish_free: bool = True,
    vacation_weekend_policy: str = DEFAULT_VACATION_WEEKEND_POLICY,
) -> pd.DataFrame:
    previous_assignments = previous_assignments or {}
    open_shift_set = set(open_shift_codes)
    shift_names = {
        row["Kuerzel"]: row["Name"]
        for _, row in shift_definitions_from_editor(shift_df).iterrows()
    }
    rows = []
    for day_index, current_day in enumerate(days):
        for shift in shifts:
            demand = daily_requirements.get((day_index, shift), 0)
            if demand <= 0:
                continue
            is_hard = shift_priority_by_code.get(shift, 1) == 1 and shift not in open_shift_set
            if not is_hard:
                continue
            eligible = 0
            reason_counts: dict[str, int] = {}
            for employee in employees:
                reason = ""
                if day_index in employee.planned_sick_days:
                    reason = "Krankenstand"
                elif day_index in vacation_protected_day_indices(employee, days, vacation_weekend_policy):
                    reason = "Urlaub"
                elif day_index in employee.blocked_days and employee.wish_free_priority == 1:
                    reason = "Wunschfrei Prio 1"
                elif current_day.weekday() >= 5 and employee.prefers_weekends_off and employee.weekend_priority == 1:
                    reason = "Wochenende gesperrt"
                elif current_day in holidays and employee.prefers_weekends_off and employee.weekend_priority == 1:
                    reason = "Feiertag gesperrt"
                elif shift in night_shifts and employee.max_nights_per_month <= 0:
                    reason = "keine Nächte erlaubt"
                elif shift in night_shifts and not employee.likes_nights and employee.night_priority <= 2:
                    reason = "Nachtwunsch sperrt"
                elif shift not in night_shifts and "nur nachtdienst" in employee.qualification.lower():
                    reason = "nur Nachtdienst"
                elif (
                    block_night_before_wish_free
                    and shift in night_shifts
                    and day_index + 1 < len(days)
                    and (day_index + 1) in employee.blocked_days
                    and employee.wish_free_priority == 1
                ):
                    reason = "Nacht vor Wunschfrei"
                elif day_index == 0:
                    previous_plan = previous_assignments.get(employee.name, [])
                    if previous_plan and is_night_assignment(previous_plan[-1], night_shifts) and shift not in night_shifts:
                        reason = "Nach Nacht aus Vormonat"
                if reason:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                else:
                    eligible += 1
            if eligible < demand:
                rows.append(
                    {
                        "Tag": day_label(current_day),
                        "Dienst": f"{shift} - {shift_names.get(shift, shift)}",
                        "Bedarf": demand,
                        "Geeignet": eligible,
                        "Fehlt": demand - eligible,
                        "Wichtigste Gründe": ", ".join(
                            f"{reason}: {count}"
                            for reason, count in sorted(reason_counts.items(), key=lambda item: item[1], reverse=True)[:4]
                        ) or "-",
                    }
                )
    return pd.DataFrame(rows)


def employee_warning_dataframe(employees: list[Employee]) -> pd.DataFrame:
    rows = []
    for employee in employees:
        hints = []
        if employee.weekly_hours_target > employee.max_weekly_planned_hours:
            hints.append("Wochenstunden-Ziel liegt über Max. Wochenstunden")
        if employee.max_nights_per_month > 0 and not employee.likes_nights and employee.night_priority <= 2:
            hints.append("Nächte erlaubt, aber Nachtwunsch stark dagegen")
        if employee.weekly_hours_target <= 1 and "nicht dienstplanrelevant" not in employee.qualification.lower():
            hints.append("Sehr niedrige Wochenstunden; prüfen, ob die Person wirklich eingeplant werden soll")
        if len(employee.blocked_days) + len(employee.planned_sick_days) + len(employee.vacation_days) >= 20:
            hints.append("Viele Wunschfrei-/Krankenstands-/Urlaubstage im Monat")
        if "Übernahme nicht bestätigt" in employee_hint_list(employee):
            hints.append("Übernahmestand ist vorbereitet, aber noch nicht endgültig bestätigt")
        if hints:
            rows.append({"MitarbeiterIn": employee.name, "Hinweis": "; ".join(hints)})
    return pd.DataFrame(rows)


def schedule_dataframe(
    schedule: dict,
    days: list[date],
    employees: list[Employee] | None = None,
    metrics: dict | None = None,
) -> pd.DataFrame:
    columns = [day_label(day) for day in days]
    employee_by_name = {employee.name: employee for employee in employees or []}
    rows = []
    for name, plan in schedule.items():
        employee = employee_by_name.get(name)
        employee_metrics = (metrics or {}).get(name, {})
        row = {
            "Mitarbeiter": name,
            "Soll h": format_display_hours(employee_metrics.get("Sollstunden", "")),
            "Ist h": format_display_hours(employee_metrics.get("Geplante Stunden", "")),
            "+/- h": format_display_hours(employee_metrics.get("Plus/Minus Stunden", "")),
        }
        for day_index, current_day in enumerate(days):
            value = plan[day_index]
            is_wish_free = employee is not None and day_index in employee.blocked_days
            is_sick = employee is not None and day_index in employee.planned_sick_days
            is_vacation = employee is not None and day_index in employee.vacation_days
            is_vacation_protected = (
                employee is not None
                and day_index in vacation_protected_day_indices(
                    employee,
                    days,
                    st.session_state.get("vacation_weekend_policy", DEFAULT_VACATION_WEEKEND_POLICY),
                )
            )
            vacation_hours = (
                format_minutes_as_hours(vacation_paid_minutes_for_day(employee, day_index, days))
                if employee is not None
                else 0
            )
            if is_sick and value == "-":
                value = "KS"
            elif is_sick:
                value = f"{value} KS"
            elif is_vacation and value == "-":
                value = f"UR{format_display_hours(vacation_hours)}" if vacation_hours else "UR"
            elif is_vacation:
                value = f"{value} UR"
            elif is_vacation_protected and value == "-":
                value = "UR"
            elif is_vacation_protected:
                value = f"{value} UR"
            elif is_wish_free and value == "-":
                value = "WF"
            elif is_wish_free:
                value = f"{value} WF"
            row[day_label(current_day)] = value
        rows.append(row)
    return pd.DataFrame(rows)


def shift_style_map(shift_df: pd.DataFrame) -> dict[str, str]:
    cleaned = shift_definitions_from_editor(shift_df)
    return {row["Kuerzel"]: row["Farbe"] for _, row in cleaned.iterrows()}


def style_schedule(df: pd.DataFrame, shift_df: pd.DataFrame):
    colors = shift_style_map(shift_df)

    def color_shift(value: str) -> str:
        value_text = str(value)
        if value_text == "WF":
            return "background-color: #fee2e2; color: #991b1b; text-align: center; font-weight: 800;"
        if value_text == "KS":
            return "background-color: #e0e7ff; color: #3730a3; text-align: center; font-weight: 800;"
        if value_text.startswith("UR"):
            return "background-color: #fef3c7; color: #92400e; text-align: center; font-weight: 800;"
        if value_text.startswith("ER"):
            return "background-color: #dcfce7; color: #166534; text-align: center; font-weight: 800;"
        shift_code = value_text.split(" ")[0]
        color = colors.get(shift_code, FREE_SHIFT_COLOR)
        border = " border: 2px solid #ef4444;" if "WF" in value_text.split(" ") else ""
        border = " border: 2px solid #4f46e5;" if "KS" in value_text.split(" ") else border
        border = " border: 2px solid #f59e0b;" if "UR" in value_text.split(" ") else border
        return f"background-color: {color}; text-align: center; font-weight: 700;{border}"

    day_columns = [column for column in df.columns if column not in {"Mitarbeiter", "Soll h", "Ist h", "+/- h"}]
    return df.style.map(color_shift, subset=day_columns)


def preview_schedule_html(
    df: pd.DataFrame,
    shift_df: pd.DataFrame,
    height: int,
    working: bool,
) -> str:
    colors = shift_style_map(shift_df)
    fixed_columns = {"Mitarbeiter", "Soll h", "Ist h", "+/- h"}

    def cell_style(column: str, value: object) -> str:
        base = "padding: 9px 10px; border: 1px solid #e5e7eb; white-space: nowrap;"
        if column in fixed_columns:
            return base + " background: #ffffff; color: #0f172a;"
        value_text = str(value)
        if value_text == "WF":
            return base + " background: #fee2e2; color: #991b1b; font-weight: 800; text-align: center;"
        if value_text == "KS":
            return base + " background: #e0e7ff; color: #3730a3; font-weight: 800; text-align: center;"
        if value_text.startswith("UR"):
            return base + " background: #fef3c7; color: #92400e; font-weight: 800; text-align: center;"
        if value_text.startswith("ER"):
            return base + " background: #dcfce7; color: #166534; font-weight: 800; text-align: center;"
        shift_code = value_text.split(" ")[0]
        color = colors.get(shift_code, FREE_SHIFT_COLOR)
        border = " border: 2px solid #ef4444;" if "WF" in value_text.split(" ") else ""
        border = " border: 2px solid #4f46e5;" if "KS" in value_text.split(" ") else border
        border = " border: 2px solid #f59e0b;" if "UR" in value_text.split(" ") else border
        return base + f" background: {color}; color: #0f172a; font-weight: 700; text-align: center;{border}"

    table_rows = []
    header_cells = ['<th class="index-col"></th>']
    for column in df.columns:
        header_cells.append(f"<th>{html.escape(str(column))}</th>")
    table_rows.append("<tr>" + "".join(header_cells) + "</tr>")

    for index, row in df.reset_index(drop=True).iterrows():
        cells = [f'<td class="index-col">{index}</td>']
        for column in df.columns:
            value = row[column]
            cells.append(
                f'<td style="{cell_style(str(column), value)}">{html.escape(str(value))}</td>'
            )
        table_rows.append("<tr>" + "".join(cells) + "</tr>")

    working_class = " live-preview-working" if working else ""
    overlay = ""
    if working:
        overlay = (
            '<div class="live-preview-overlay">'
            '<div class="live-preview-overlay-card">'
            '<span class="live-preview-overlay-spinner"></span>'
            "<span>Dienstplan wird optimiert...</span>"
            "</div>"
            "</div>"
        )
    return (
        f'<div class="live-preview-plan-shell{working_class}" style="max-height: {height}px;">'
        '<table class="live-preview-plan-table">'
        f'{"".join(table_rows)}'
        "</table>"
        f"{overlay}"
        "</div>"
    )


def render_generation_preview(
    preview_slot,
    title: str,
    schedule: dict | None,
    metrics: dict | None,
    days: list[date],
    employees: list[Employee],
    daily_requirements: dict[tuple[int, str], int],
    shift_df: pd.DataFrame,
    open_shift_codes: list[str],
    shift_priority_by_code: dict[str, int],
    score: float | None = None,
    status: str | None = None,
    working: bool = True,
) -> None:
    with preview_slot.container():
        st.subheader("Live-Vorschau")
        st.caption("Gezeigt wird immer die beste bisher gefundene gültige Variante.")
        if not schedule:
            st.info(title)
            return

        metrics_df = pd.DataFrame.from_dict(metrics or {}, orient="index")
        open_services = open_services_dataframe(
            schedule,
            days,
            daily_requirements,
            shift_df,
            open_shift_codes=open_shift_codes,
            shift_priority_by_code=shift_priority_by_code,
        )
        open_count = int(open_services["Offen"].sum()) if not open_services.empty else 0
        warning_count = (
            int(metrics_df.get("Aktive Warnungen", pd.Series(dtype=float)).sum())
            if not metrics_df.empty
            else 0
        )
        max_deviation = (
            float(metrics_df.get("Stundenabweichung h", pd.Series([0])).max() or 0)
            if not metrics_df.empty
            else 0
        )
        satisfaction = (
            float(metrics_df.get("Zufriedenheit %", pd.Series([0])).mean() or 0)
            if not metrics_df.empty
            else 0
        )

        st.info(title)
        preview_cols = st.columns(5)
        preview_cols[0].metric("Offene Dienste", open_count)
        preview_cols[1].metric("Warnungen", warning_count)
        preview_cols[2].metric("Max. Abweichung", f"{format_display_hours(max_deviation)} h")
        preview_cols[3].metric("Zufriedenheit Ø", f"{format_display_hours(round(satisfaction, 1))} %")
        preview_cols[4].metric("Status", solver_status_text(status))
        if score is not None:
            st.caption(f"Vergleichswert dieser Variante: {format_display_hours(round(score, 1))}")

        preview_df = schedule_dataframe(schedule, days, employees, metrics)
        preview_height = min(540, 90 + (len(preview_df) + 1) * 34)
        st.markdown(
            preview_schedule_html(preview_df, shift_df, preview_height, working),
            unsafe_allow_html=True,
        )

def editor_dataframe(employees: list[Employee]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Name": e.name,
                "Qualifikation": e.qualification,
                "Dienstplanrelevant": e.participates_in_schedule,
                "Wochenstunden": e.weekly_hours_target,
                "Max. Dienste/Woche": e.max_shifts_per_week,
                "Max. Tage in Folge": e.max_consecutive_workdays,
                "Max. Wochenstunden": e.max_weekly_planned_hours,
                "Max. Naechte/Monat": e.max_nights_per_month,
                "Gerne Nacht": e.likes_nights,
                "Nur Doppelnaechte": e.double_nights_only,
                "3 Naechte erlaubt": e.allow_three_consecutive_nights,
                "Frei nach Nacht": e.rest_after_night,
                "Wochenende frei": e.prefers_weekends_off,
                "Gemeinsame Wochenenden": e.prefers_joint_weekends,
                "Prio Nacht": priority_label(e.night_priority),
                "Prio Doppelnaechte": priority_label(e.double_night_priority),
                "Prio frei nach Nacht": priority_label(e.rest_priority),
                "Prio Wochenende": priority_label(e.weekend_priority),
                "Prio gemeinsame Wochenenden": priority_label(e.joint_weekend_priority),
                "Prio Wunschfrei": priority_label(e.wish_free_priority),
                "Wunschfrei-Tage": ", ".join(str(day + 1) for day in e.blocked_days),
                "Krankenstand-Tage": ", ".join(str(day + 1) for day in e.planned_sick_days),
                "Urlaub-Tage": ", ".join(str(day + 1) for day in e.vacation_days),
                "Wunschfrei je Monat": "",
                "Krankenstand je Monat": "",
                "Urlaub je Monat": "",
                "Urlaubswochen/Jahr": e.annual_vacation_weeks,
                "Urlaubstage/Jahr": e.annual_vacation_workdays,
                "Urlaubstag h": e.vacation_day_hours,
                "Urlaubs-Stichtag": e.vacation_start_date,
                "Übernahme bestätigt": e.takeover_confirmed,
                "Übernahme Startdatum": e.takeover_start_date,
                "Übernahme Resturlaub h": e.takeover_vacation_hours,
                "Übernahme Zeitkonto h": e.takeover_time_balance_hours,
                "Übernahme Ersatzruhe h": e.takeover_replacement_rest_hours,
                "Übernahme Vortag": e.takeover_previous_day_service,
                "Übernahme Vor-Vortag": e.takeover_second_previous_day_service,
                "Übernahme Arbeitstage in Folge": e.takeover_previous_work_streak,
            }
            for e in employees
        ]
    )


def normalize_employee_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    defaults = {
        "Name": "",
        "Qualifikation": "Pflege",
        "Dienstplanrelevant": True,
        "Wochenstunden": 30,
        "Max. Dienste/Woche": 4,
        "Max. Tage in Folge": 6,
        "Max. Wochenstunden": 48,
        "Max. Naechte/Monat": 4,
        "Gerne Nacht": False,
        "Nur Doppelnaechte": False,
        "3 Naechte erlaubt": False,
        "Frei nach Nacht": 1,
        "Wochenende frei": True,
        "Gemeinsame Wochenenden": True,
        "Prio Nacht": DEFAULT_PRIORITY_LABEL,
        "Prio Doppelnaechte": DEFAULT_PRIORITY_LABEL,
        "Prio frei nach Nacht": DEFAULT_PRIORITY_LABEL,
        "Prio Wochenende": DEFAULT_PRIORITY_LABEL,
        "Prio gemeinsame Wochenenden": DEFAULT_PRIORITY_LABEL,
        "Prio Wunschfrei": "1 - muss immer zutreffen",
        "Wunschfrei-Tage": "",
        "Krankenstand-Tage": "",
        "Urlaub-Tage": "",
        "Wunschfrei je Monat": "",
        "Krankenstand je Monat": "",
        "Urlaub je Monat": "",
        "Urlaubswochen/Jahr": DEFAULT_ANNUAL_VACATION_WEEKS,
        "Urlaubstage/Jahr": DEFAULT_ANNUAL_VACATION_WORKDAYS,
        "Urlaubstag h": DEFAULT_VACATION_DAY_HOURS,
        "Urlaubs-Stichtag": DEFAULT_VACATION_START_DATE.isoformat(),
        "Übernahme bestätigt": False,
        "Übernahme Startdatum": "",
        "Übernahme Resturlaub h": 0.0,
        "Übernahme Zeitkonto h": 0.0,
        "Übernahme Ersatzruhe h": 0.0,
        "Übernahme Vortag": "Frei",
        "Übernahme Vor-Vortag": "Frei",
        "Übernahme Arbeitstage in Folge": 0,
    }
    if "Wunschfrei-Tage" not in normalized.columns and "Gesperrte Tage" in normalized.columns:
        normalized["Wunschfrei-Tage"] = normalized["Gesperrte Tage"]
    if "Prio Nacht" not in normalized.columns and "Prioritaet" in normalized.columns:
        normalized["Prio Nacht"] = normalized["Prioritaet"].map(priority_label)
        normalized["Prio Doppelnaechte"] = normalized["Prioritaet"].map(priority_label)
        normalized["Prio frei nach Nacht"] = normalized["Prioritaet"].map(priority_label)
        normalized["Prio Wochenende"] = normalized["Prioritaet"].map(priority_label)
        normalized["Prio gemeinsame Wochenenden"] = normalized["Prioritaet"].map(priority_label)
        normalized["Prio Wunschfrei"] = "1 - muss immer zutreffen"

    for column, default in defaults.items():
        if column not in normalized.columns:
            normalized[column] = default
    if "Dienstplanrelevant" in normalized.columns:
        normalized["Dienstplanrelevant"] = normalized.apply(
            lambda row: parse_bool_value(row.get("Dienstplanrelevant"), schedule_relevant_default(row)),
            axis=1,
        )
    normalized["Prio Nacht"] = normalized.apply(
        lambda row: priority_label(
            normalize_night_priority_value(
                max(0, int(row.get("Max. Naechte/Monat", 0) or 0)),
                parse_bool_value(row.get("Gerne Nacht", False), False),
                row.get("Prio Nacht", DEFAULT_PRIORITY_LABEL),
            )
        ),
        axis=1,
    )
    normalized["Urlaubs-Stichtag"] = normalized["Urlaubs-Stichtag"].map(
        lambda value: parse_date_value(value, DEFAULT_VACATION_START_DATE).isoformat()
    )
    normalized["Urlaubstage/Jahr"] = normalized["Urlaubstage/Jahr"].map(
        lambda value: max(0.0, parse_hour_value(value, DEFAULT_ANNUAL_VACATION_WORKDAYS))
    )
    normalized["Urlaubstag h"] = normalized["Urlaubstag h"].map(
        lambda value: max(0.0, parse_hour_value(value, DEFAULT_VACATION_DAY_HOURS))
    )
    normalized["Übernahme bestätigt"] = normalized["Übernahme bestätigt"].map(
        lambda value: parse_bool_value(value, False)
    )
    normalized["Übernahme Startdatum"] = normalized["Übernahme Startdatum"].map(
        lambda value: parse_date_value(value, DEFAULT_VACATION_START_DATE).isoformat() if str(value or "").strip() else ""
    )
    for hour_column in ["Übernahme Resturlaub h", "Übernahme Zeitkonto h", "Übernahme Ersatzruhe h"]:
        normalized[hour_column] = normalized[hour_column].map(lambda value: parse_hour_value(value, 0.0))
    for service_column in ["Übernahme Vortag", "Übernahme Vor-Vortag"]:
        normalized[service_column] = normalized[service_column].map(takeover_service_label)
    normalized["Übernahme Arbeitstage in Folge"] = normalized["Übernahme Arbeitstage in Folge"].map(
        lambda value: max(0, int(parse_hour_value(value, 0)))
    )

    normalized = normalized[list(defaults.keys())]
    for column in [
        "Prio Nacht",
        "Prio Doppelnaechte",
        "Prio frei nach Nacht",
        "Prio Wochenende",
        "Prio gemeinsame Wochenenden",
        "Prio Wunschfrei",
    ]:
        normalized[column] = normalized[column].map(priority_label)
    return normalized


def parse_blocked_days(value: object) -> tuple[int, ...]:
    if value is None or pd.isna(value):
        return ()

    blocked_days = []
    for raw_part in str(value).replace(";", ",").split(","):
        part = raw_part.strip()
        if not part:
            continue
        range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if range_match:
            start_day = int(range_match.group(1))
            end_day = int(range_match.group(2))
            if start_day > end_day:
                start_day, end_day = end_day, start_day
            blocked_days.extend(day - 1 for day in range(start_day, end_day + 1) if day > 0)
            continue
        try:
            day_number = int(part)
        except ValueError:
            continue
        if day_number > 0:
            blocked_days.append(day_number - 1)
    return tuple(sorted(set(blocked_days)))


def format_day_number_list(day_indices: tuple[int, ...] | list[int] | set[int]) -> str:
    return ", ".join(str(int(day_index) + 1) for day_index in sorted(set(day_indices)))


def parse_monthly_day_map(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, dict):
        raw_map = value
    else:
        try:
            if pd.isna(value):
                return {}
        except (TypeError, ValueError):
            pass
        text = str(value or "").strip()
        if not text:
            return {}
        try:
            raw_map = json.loads(text)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw_map, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key, raw_days in raw_map.items():
        month_key = str(key).strip()
        if not re.fullmatch(r"\d{4}-\d{2}", month_key):
            continue
        if isinstance(raw_days, (list, tuple, set)):
            day_text = ", ".join(str(day) for day in raw_days)
        else:
            day_text = str(raw_days or "")
        parsed_days = parse_blocked_days(day_text)
        if parsed_days:
            cleaned[month_key] = format_day_number_list(parsed_days)
    return cleaned


def serialize_monthly_day_map(monthly_map: dict[str, str]) -> str:
    cleaned = parse_monthly_day_map(monthly_map)
    return json.dumps(cleaned, ensure_ascii=False, sort_keys=True)


def month_absence_text(row: dict | pd.Series, monthly_column: str, fallback_column: str, year: int, month: int) -> str:
    month_key = plan_month_key(year, month)
    monthly_map = parse_monthly_day_map(row.get(monthly_column, ""))
    return str(monthly_map.get(month_key, "")).strip()


def updated_monthly_absence_payload(
    current_payload: object,
    year: int,
    month: int,
    selected_days: list[int] | set[int] | tuple[int, ...],
) -> str:
    month_key = plan_month_key(year, month)
    monthly_map = parse_monthly_day_map(current_payload)
    parsed_days = parse_blocked_days(", ".join(str(day) for day in selected_days))
    if parsed_days:
        monthly_map[month_key] = format_day_number_list(parsed_days)
    else:
        monthly_map.pop(month_key, None)
    return serialize_monthly_day_map(monthly_map)


def migrate_legacy_absence_columns_to_month(df: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    migrated = df.copy()
    month_key = plan_month_key(year, month)
    column_pairs = [
        ("Wunschfrei je Monat", "Wunschfrei-Tage"),
        ("Krankenstand je Monat", "Krankenstand-Tage"),
        ("Urlaub je Monat", "Urlaub-Tage"),
    ]
    for monthly_column, legacy_column in column_pairs:
        if monthly_column not in migrated.columns or legacy_column not in migrated.columns:
            continue
        for index, row in migrated.iterrows():
            monthly_map = parse_monthly_day_map(row.get(monthly_column, ""))
            legacy_days = parse_blocked_days(row.get(legacy_column, ""))
            if not monthly_map and legacy_days:
                monthly_map[month_key] = format_day_number_list(legacy_days)
                migrated.at[index, monthly_column] = serialize_monthly_day_map(monthly_map)
    return migrated


def sync_absence_display_columns_for_month(df: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    synced = df.copy()
    column_pairs = [
        ("Wunschfrei je Monat", "Wunschfrei-Tage"),
        ("Krankenstand je Monat", "Krankenstand-Tage"),
        ("Urlaub je Monat", "Urlaub-Tage"),
    ]
    for monthly_column, legacy_column in column_pairs:
        if monthly_column not in synced.columns or legacy_column not in synced.columns:
            continue
        synced[legacy_column] = synced.apply(
            lambda row: month_absence_text(row, monthly_column, legacy_column, year, month),
            axis=1,
        )
    return synced


def fixed_vacation_usage_dataframe(
    employee_name: str,
    employee_row: dict | pd.Series,
    saved_plans: dict,
    period_start: date | None = None,
    period_end: date | None = None,
) -> pd.DataFrame:
    monthly_vacation_map = parse_monthly_day_map(employee_row.get("Urlaub je Monat", ""))
    rows: list[dict[str, object]] = []
    for key, plan in sorted((saved_plans or {}).items()):
        if not re.fullmatch(r"\d{4}-\d{2}", str(key)):
            continue
        if not isinstance(plan, dict):
            continue
        metrics = plan.get("metrics", {})
        employee_metrics = metrics.get(employee_name, {}) if isinstance(metrics, dict) else {}
        vacation_hours = parse_hour_value(employee_metrics.get("Urlaub-Stunden", 0), 0)
        vacation_days = monthly_vacation_map.get(str(key), "")
        if vacation_hours <= 0 and not vacation_days:
            continue
        year_text, month_text = str(key).split("-")
        month_number = int(month_text)
        month_days = build_month_dates(int(year_text), month_number)
        if period_start is not None and period_end is not None:
            if not month_days or month_days[-1] < period_start or month_days[0] > period_end:
                continue
        rows.append(
            {
                "Monat": f"{MONTH_NAMES[month_number]} {year_text}",
                "Tage": format_day_ranges(vacation_days) if vacation_days else "-",
                "Fixiert verbraucht h": format_display_hours(vacation_hours),
            }
        )
    return pd.DataFrame(rows)


def employees_from_editor(
    df: pd.DataFrame,
    year: int | None = None,
    month: int | None = None,
) -> list[Employee]:
    year = int(year if year is not None else st.session_state.get("selected_year", date.today().year))
    month = int(month if month is not None else st.session_state.get("selected_month", date.today().month))
    employees = []
    for _, row in df.fillna("").iterrows():
        name = str(row.get("Name", "")).strip()
        if not name:
            continue
        max_nights_value = max(0, int(row.get("Max. Naechte/Monat", 4) or 4))
        likes_nights_value = parse_bool_value(row.get("Gerne Nacht", False), False)
        employees.append(
            Employee(
                name=name,
                qualification=str(row.get("Qualifikation", "Pflege")).strip() or "Pflege",
                participates_in_schedule=parse_bool_value(row.get("Dienstplanrelevant", True), True),
                weekly_hours_target=max(0.25, float(row.get("Wochenstunden", 30) or 30)),
                max_shifts_per_week=max(1, int(row.get("Max. Dienste/Woche", 5) or 5)),
                max_nights_per_month=max_nights_value,
                likes_nights=likes_nights_value,
                double_nights_only=bool(row.get("Nur Doppelnaechte", False)),
                allow_three_consecutive_nights=bool(row.get("3 Naechte erlaubt", False)),
                rest_after_night=int(row.get("Frei nach Nacht", 1) or 1),
                prefers_weekends_off=bool(row.get("Wochenende frei", False)),
                night_priority=normalize_night_priority_value(
                    max_nights_value,
                    likes_nights_value,
                    row.get("Prio Nacht", DEFAULT_PRIORITY_LABEL),
                ),
                double_night_priority=priority_value(row.get("Prio Doppelnaechte", DEFAULT_PRIORITY_LABEL)),
                rest_priority=priority_value(row.get("Prio frei nach Nacht", DEFAULT_PRIORITY_LABEL)),
                weekend_priority=priority_value(row.get("Prio Wochenende", DEFAULT_PRIORITY_LABEL)),
                wish_free_priority=priority_value(row.get("Prio Wunschfrei", "1 - muss immer zutreffen")),
                blocked_days=parse_blocked_days(
                    month_absence_text(row, "Wunschfrei je Monat", "Wunschfrei-Tage", year, month)
                ),
                max_consecutive_workdays=max(1, int(row.get("Max. Tage in Folge", 6) or 6)),
                max_weekly_planned_hours=max(0.25, float(row.get("Max. Wochenstunden", 48) or 48)),
                planned_sick_days=parse_blocked_days(
                    month_absence_text(row, "Krankenstand je Monat", "Krankenstand-Tage", year, month)
                ),
                vacation_days=parse_blocked_days(
                    month_absence_text(row, "Urlaub je Monat", "Urlaub-Tage", year, month)
                ),
                annual_vacation_weeks=max(0.0, float(row.get("Urlaubswochen/Jahr", DEFAULT_ANNUAL_VACATION_WEEKS) or DEFAULT_ANNUAL_VACATION_WEEKS)),
                vacation_start_date=parse_date_value(row.get("Urlaubs-Stichtag", DEFAULT_VACATION_START_DATE.isoformat())).isoformat(),
                annual_vacation_workdays=max(0.0, parse_hour_value(row.get("Urlaubstage/Jahr", DEFAULT_ANNUAL_VACATION_WORKDAYS), DEFAULT_ANNUAL_VACATION_WORKDAYS)),
                vacation_day_hours=max(0.0, parse_hour_value(row.get("Urlaubstag h", DEFAULT_VACATION_DAY_HOURS), DEFAULT_VACATION_DAY_HOURS)),
                prefers_joint_weekends=bool(row.get("Gemeinsame Wochenenden", True)),
                joint_weekend_priority=priority_value(row.get("Prio gemeinsame Wochenenden", DEFAULT_PRIORITY_LABEL)),
                takeover_confirmed=parse_bool_value(row.get("Übernahme bestätigt", False), False),
                takeover_start_date=str(row.get("Übernahme Startdatum", "") or ""),
                takeover_vacation_hours=parse_hour_value(row.get("Übernahme Resturlaub h", 0), 0.0),
                takeover_time_balance_hours=parse_hour_value(row.get("Übernahme Zeitkonto h", 0), 0.0),
                takeover_replacement_rest_hours=parse_hour_value(row.get("Übernahme Ersatzruhe h", 0), 0.0),
                takeover_previous_day_service=takeover_service_label(row.get("Übernahme Vortag", "Frei")),
                takeover_second_previous_day_service=takeover_service_label(row.get("Übernahme Vor-Vortag", "Frei")),
                takeover_previous_work_streak=max(0, int(parse_hour_value(row.get("Übernahme Arbeitstage in Folge", 0), 0))),
            )
        )
    return employees

def close_employee_dialog_state() -> None:
    st.session_state.employee_dialog_open = False
    st.session_state.employee_dialog_row_index = None


def request_employee_dialog(row_index: int | None = None) -> None:
    st.session_state.employee_dialog_open = True
    st.session_state.employee_dialog_row_index = row_index
    st.rerun()


@st.dialog("Mitarbeiter", width="large", dismissible=False)
def employee_dialog(row_index: int | None = None) -> None:
    is_edit = row_index is not None
    if is_edit:
        current = st.session_state.employees_df.iloc[row_index].to_dict()
    else:
        next_number = len(st.session_state.employees_df) + 1
        current = {
            "Name": f"Testperson {next_number}",
            "Qualifikation": "Pflege",
            "Dienstplanrelevant": True,
            "Wochenstunden": 30.0,
            "Max. Dienste/Woche": 4,
            "Max. Tage in Folge": int(st.session_state.get("global_max_consecutive_workdays", 6)),
            "Max. Wochenstunden": 48.0,
            "Max. Naechte/Monat": int(st.session_state.get("global_max_nights_per_month", 4)),
            "Gerne Nacht": False,
            "Nur Doppelnaechte": False,
            "3 Naechte erlaubt": bool(st.session_state.get("global_allow_three_nights", False)),
            "Frei nach Nacht": int(st.session_state.get("global_rest_after_night", 1)),
            "Wochenende frei": bool(st.session_state.get("global_weekends_off", True)),
            "Gemeinsame Wochenenden": bool(st.session_state.get("global_joint_weekends", True)),
            "Prio Nacht": DEFAULT_PRIORITY_LABEL,
            "Prio Doppelnaechte": DEFAULT_PRIORITY_LABEL,
            "Prio frei nach Nacht": DEFAULT_PRIORITY_LABEL,
            "Prio Wochenende": DEFAULT_PRIORITY_LABEL,
            "Prio gemeinsame Wochenenden": st.session_state.get("global_joint_weekends_priority", DEFAULT_PRIORITY_LABEL),
            "Prio Wunschfrei": "1 - muss immer zutreffen",
            "Wunschfrei-Tage": "",
            "Krankenstand-Tage": "",
            "Urlaub-Tage": "",
            "Wunschfrei je Monat": "",
            "Krankenstand je Monat": "",
            "Urlaub je Monat": "",
            "Urlaubswochen/Jahr": float(st.session_state.get("global_annual_vacation_weeks", DEFAULT_ANNUAL_VACATION_WEEKS)),
            "Urlaubstage/Jahr": float(st.session_state.get("global_annual_vacation_workdays", DEFAULT_ANNUAL_VACATION_WORKDAYS)),
            "Urlaubstag h": float(st.session_state.get("global_vacation_day_hours", DEFAULT_VACATION_DAY_HOURS)),
            "Urlaubs-Stichtag": DEFAULT_VACATION_START_DATE.isoformat(),
            "Übernahme bestätigt": False,
            "Übernahme Startdatum": "",
            "Übernahme Resturlaub h": 0.0,
            "Übernahme Zeitkonto h": 0.0,
            "Übernahme Ersatzruhe h": 0.0,
            "Übernahme Vortag": "Frei",
            "Übernahme Vor-Vortag": "Frei",
            "Übernahme Arbeitstage in Folge": 0,
        }

    absence_key_base = f"employee_absence_month_{row_index if is_edit else 'new'}"
    if f"{absence_key_base}_year" not in st.session_state:
        st.session_state[f"{absence_key_base}_year"] = int(st.session_state.get("selected_year", date.today().year))
    if f"{absence_key_base}_month" not in st.session_state:
        st.session_state[f"{absence_key_base}_month"] = int(st.session_state.get("selected_month", date.today().month))
    absence_month_cols = st.columns([0.35, 0.65])
    with absence_month_cols[0]:
        absence_year = st.number_input(
            "Abwesenheits-Jahr",
            min_value=int(st.session_state.get("selected_year", date.today().year)) - 1,
            max_value=int(st.session_state.get("selected_year", date.today().year)) + 3,
            value=int(st.session_state[f"{absence_key_base}_year"]),
            step=1,
            key=f"{absence_key_base}_year_input",
        )
    with absence_month_cols[1]:
        absence_month_label = st.selectbox(
            "Abwesenheits-Monat",
            options=[f"{month:02d} - {MONTH_NAMES[month]}" for month in range(1, 13)],
            index=int(st.session_state[f"{absence_key_base}_month"]) - 1,
            key=f"{absence_key_base}_month_input",
        )
    absence_month = int(absence_month_label.split(" - ")[0])
    if (
        int(st.session_state[f"{absence_key_base}_year"]) != int(absence_year)
        or int(st.session_state[f"{absence_key_base}_month"]) != int(absence_month)
    ):
        st.session_state[f"{absence_key_base}_year"] = int(absence_year)
        st.session_state[f"{absence_key_base}_month"] = int(absence_month)
        st.rerun()
    st.caption(
        f"Abwesenheiten werden für {MONTH_NAMES[absence_month]} {int(absence_year)} gespeichert, nicht für jeden Monat."
    )

    with st.form(f"employee_form_{row_index if is_edit else 'new'}"):
        (
            stammdaten_tab,
            takeover_tab,
            hours_tab,
            night_tab,
            weekend_tab,
            wish_free_tab,
            vacation_tab,
            sick_tab,
            rules_tab,
        ) = st.tabs(
            [
                "Stammdaten",
                "Übernahme",
                "Stunden",
                "Nacht",
                "Wochenende",
                "Wunschfrei",
                "Urlaub",
                "Krankenstand",
                "Regeln",
            ]
        )
        month_days = build_month_dates(
            int(absence_year),
            int(absence_month),
        )
        key_base = f"employee_{row_index if is_edit else 'new'}_{int(absence_year)}_{absence_month}"
        blocked_day_numbers = {
            day + 1
            for day in parse_blocked_days(
                month_absence_text(current, "Wunschfrei je Monat", "Wunschfrei-Tage", int(absence_year), absence_month)
            )
        }
        sick_day_numbers = {
            day + 1
            for day in parse_blocked_days(
                month_absence_text(current, "Krankenstand je Monat", "Krankenstand-Tage", int(absence_year), absence_month)
            )
        }
        vacation_day_numbers = {
            day + 1
            for day in parse_blocked_days(
                month_absence_text(current, "Urlaub je Monat", "Urlaub-Tage", int(absence_year), absence_month)
            )
        }

        with stammdaten_tab:
            name = st.text_input("Name", value=str(current["Name"]))
            qualification = st.text_input("Qualifikation", value=str(current["Qualifikation"]))
            participates_in_schedule = st.checkbox(
                "In diesem Dienstplan berücksichtigen",
                value=parse_bool_value(current.get("Dienstplanrelevant", True), True),
                help="Nur aktive Personen werden in der Generierung und Stundenberechnung berücksichtigt.",
            )

        takeover_default_start = date(
            int(st.session_state.get("planning_start_year", st.session_state.get("selected_year", date.today().year))),
            int(st.session_state.get("planning_start_month", st.session_state.get("selected_month", date.today().month))),
            1,
        )
        takeover_confirmed = parse_bool_value(current.get("Übernahme bestätigt", False), False)
        takeover_start_date = parse_date_value(
            current.get("Übernahme Startdatum", ""),
            takeover_default_start,
        )
        takeover_vacation_text = format_hour_value(current.get("Übernahme Resturlaub h", 0))
        takeover_time_balance_text = format_hour_value(current.get("Übernahme Zeitkonto h", 0))
        takeover_replacement_rest_text = format_hour_value(current.get("Übernahme Ersatzruhe h", 0))
        takeover_previous_day = takeover_service_label(current.get("Übernahme Vortag", "Frei"))
        takeover_second_previous_day = takeover_service_label(current.get("Übernahme Vor-Vortag", "Frei"))
        takeover_previous_work_streak = max(0, int(parse_hour_value(current.get("Übernahme Arbeitstage in Folge", 0), 0)))
        with takeover_tab:
            st.caption(
                "Hier wird ein bestehender Dienstplanstand einmalig übernommen. "
                "Nach der Bestätigung ist dieser Stand gesperrt und dient nur noch als Startwert."
            )
            if takeover_confirmed:
                st.success("Übernahmestand ist bestätigt und kann nicht mehr geändert werden.")
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"Wert": "Startdatum", "Übernommen": takeover_start_date.strftime("%d.%m.%Y")},
                            {"Wert": "Resturlaub", "Übernommen": f"{format_display_hours(parse_hour_value(takeover_vacation_text, 0))} h"},
                            {"Wert": "Zeitkonto", "Übernommen": f"{format_display_hours(parse_hour_value(takeover_time_balance_text, 0))} h"},
                            {"Wert": "Offene Ersatzruhe", "Übernommen": f"{format_display_hours(parse_hour_value(takeover_replacement_rest_text, 0))} h"},
                            {"Wert": "Vortag vor Start", "Übernommen": takeover_previous_day},
                            {"Wert": "Vor-Vortag vor Start", "Übernommen": takeover_second_previous_day},
                            {"Wert": "Arbeitstage in Folge vor Start", "Übernommen": takeover_previous_work_streak},
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )
                takeover_review_rows = []
                if parse_hour_value(takeover_time_balance_text, 0) > 0:
                    takeover_review_rows.append({"Prüfung": "Zeitkonto", "Hinweis": "Person startet mit Plusstunden."})
                elif parse_hour_value(takeover_time_balance_text, 0) < 0:
                    takeover_review_rows.append({"Prüfung": "Zeitkonto", "Hinweis": "Person startet mit Minusstunden."})
                if parse_hour_value(takeover_replacement_rest_text, 0) > 0:
                    takeover_review_rows.append({"Prüfung": "Ersatzruhe", "Hinweis": "Es gibt offene Ersatzruhe aus dem alten System."})
                if takeover_previous_day == "Nachtdienst":
                    takeover_review_rows.append({"Prüfung": "Monatsübergang", "Hinweis": "Achtung: Nachtdienst am Vortag wird beim Start berücksichtigt."})
                if takeover_review_rows:
                    st.dataframe(pd.DataFrame(takeover_review_rows), width="stretch", hide_index=True)
            else:
                st.warning(
                    "Bitte sorgfältig prüfen: Wenn dieser Übernahmestand gespeichert und bestätigt wird, "
                    "kann er in diesem Mitarbeiterdatensatz nicht mehr geändert werden."
                )
                takeover_cols = st.columns(3)
                with takeover_cols[0]:
                    takeover_start_date = st.date_input(
                        "Startdatum",
                        value=takeover_start_date,
                        min_value=date(date.today().year - 1, 1, 1),
                        max_value=date(date.today().year + 5, 12, 31),
                        help="Normalerweise der erste Tag des Monats, ab dem mit diesem Programm geplant wird.",
                    )
                    takeover_vacation_text = st.text_input(
                        "Resturlaub zum Start in Stunden",
                        value=takeover_vacation_text,
                        help="Am besten in Stunden eintragen, damit Teilzeit korrekt bleibt.",
                    )
                with takeover_cols[1]:
                    takeover_time_balance_text = st.text_input(
                        "Zeitkonto zum Start in Stunden",
                        value=takeover_time_balance_text,
                        help="Plusstunden positiv, Minusstunden negativ eintragen.",
                    )
                    takeover_replacement_rest_text = st.text_input(
                        "Offene Ersatzruhe zum Start in Stunden",
                        value=takeover_replacement_rest_text,
                    )
                with takeover_cols[2]:
                    takeover_previous_day = st.selectbox(
                        "Vortag vor Start",
                        options=TAKEOVER_PREVIOUS_SERVICE_OPTIONS,
                        index=TAKEOVER_PREVIOUS_SERVICE_OPTIONS.index(takeover_previous_day),
                        help="Wichtig für Ruhezeit und Nacht-auf-Tag-Verbot beim Start.",
                    )
                    takeover_second_previous_day = st.selectbox(
                        "Vor-Vortag vor Start",
                        options=TAKEOVER_PREVIOUS_SERVICE_OPTIONS,
                        index=TAKEOVER_PREVIOUS_SERVICE_OPTIONS.index(takeover_second_previous_day),
                        help="Wichtig, wenn vor dem Start schon Nachtdienste in Folge waren.",
                    )
                takeover_previous_work_streak = st.number_input(
                    "Arbeitstage in Folge direkt vor dem Start",
                    min_value=0,
                    max_value=14,
                    value=takeover_previous_work_streak,
                    step=1,
                    help="Damit die maximale Anzahl an Arbeitstagen in Folge am Start nicht überschritten wird.",
                )
                st.info(
                    "Bereits genehmigte zukünftige Wunschfrei-, Urlaubs- und Krankenstandstage werden in den jeweiligen Reitern eingetragen."
                )
                takeover_confirmed = st.checkbox(
                    "Übernahmestand endgültig bestätigen",
                    value=False,
                    help="Erst nach dieser Bestätigung wird der Übernahmestand gesperrt und für den Startmonat verwendet.",
                )

        with hours_tab:
            st.caption("Diese Werte steuern die Stunden- und Belastungsgrenzen dieser Person.")
            hours_cols = st.columns(2)
            with hours_cols[0]:
                weekly_hours_text = st.text_input("Wochenstunden", value=format_hour_value(current["Wochenstunden"]))
                max_shifts = st.number_input(
                    "Max. Dienste pro Woche",
                    min_value=1,
                    max_value=7,
                    value=int(current["Max. Dienste/Woche"]),
                    step=1,
                )
            with hours_cols[1]:
                max_weekly_hours_text = st.text_input(
                    "Max. Wochenstunden",
                    value=format_hour_value(current["Max. Wochenstunden"]),
                )
                max_consecutive_workdays = st.number_input(
                    "Max. Tage in Folge",
                    min_value=1,
                    max_value=14,
                    value=int(current["Max. Tage in Folge"]),
                    step=1,
                )
                annual_vacation_weeks = st.number_input(
                    "Urlaubswochen pro Jahr",
                    min_value=0.0,
                    max_value=10.0,
                    value=float(current.get("Urlaubswochen/Jahr", DEFAULT_ANNUAL_VACATION_WEEKS)),
                    step=0.5,
                    help="Orientierung in Wochen. Die genaue Stundenrechnung nutzt die Urlaubstage und den Stundenwert darunter.",
                )
                vacation_workdays = st.number_input(
                    "Urlaubstage pro Urlaubsjahr",
                    min_value=0.0,
                    max_value=60.0,
                    value=float(current.get("Urlaubstage/Jahr", DEFAULT_ANNUAL_VACATION_WORKDAYS)),
                    step=1.0,
                    help="Bei 5 Wochen und 5-Tage-Woche sind das meist 25 Arbeitstage.",
                )
                vacation_day_hours_text = st.text_input(
                    "Stundenwert pro Urlaubstag",
                    value=format_hour_value(current.get("Urlaubstag h", DEFAULT_VACATION_DAY_HOURS)),
                    help="0 bedeutet automatisch: Wochenstunden / 5. Für andere Modelle hier den fixen Tageswert eintragen.",
                )
                vacation_start_date = st.date_input(
                    "Urlaubs-Stichtag / Eintrittsdatum",
                    value=parse_date_value(current.get("Urlaubs-Stichtag", DEFAULT_VACATION_START_DATE.isoformat())),
                    min_value=date(1970, 1, 1),
                    max_value=date(current_year + 5, 12, 31),
                    help="Ab diesem Datum läuft der persönliche Urlaubsanspruch jeweils für ein Jahr.",
                )

        with night_tab:
            st.caption(
                "Hier wird festgelegt, ob Nachtdienste ausgeschlossen, nur möglich oder bevorzugt sind. "
                "Die maximale Anzahl ist immer die harte Grenze."
            )
            night_cols = st.columns(2)
            with night_cols[0]:
                night_wish_choice = st.radio(
                    "Nachtwunsch",
                    options=[
                        "Nachtdienste möglichst vermeiden",
                        "Nachtdienste bevorzugt einteilen",
                    ],
                    index=1 if bool(current["Gerne Nacht"]) else 0,
                    help=(
                        "Das ist ein Wunsch für die Optimierung. Ob Nachtdienste überhaupt möglich sind, "
                        "entscheidet die maximale Anzahl darunter."
                    ),
                )
                likes_nights = night_wish_choice == "Nachtdienste bevorzugt einteilen"
                max_nights = st.number_input(
                    "Max. Nachtdienste im Monat",
                    min_value=0,
                    max_value=31,
                    value=int(current["Max. Naechte/Monat"]),
                    step=1,
                    help="Harte Obergrenze. 0 bedeutet: Diese Person bekommt keine Nachtdienste.",
                )
                night_priority_help = (
                    "Bewertet nur den Wunsch, diese Person bevorzugt für Nachtdienste einzuplanen. "
                    "Die maximale Anzahl bleibt trotzdem die harte Grenze."
                    if likes_nights
                    else "Bewertet nur den Wunsch, Nachtdienste möglichst zu vermeiden. "
                    "Die maximale Anzahl bleibt trotzdem die harte Grenze."
                )
                if int(max_nights) == 0:
                    st.info(
                        "Max. Nachtdienste ist 0. Diese Person wird nie für Nachtdienste eingeplant; "
                        "eine Priorität ist dafür nicht nötig."
                    )
                    likes_nights = False
                    night_priority = priority_label(current.get("Prio Nacht", DEFAULT_PRIORITY_LABEL))
                else:
                    night_priority_labels = (
                        NIGHT_PRIORITY_LABELS_WANTED if likes_nights else NIGHT_PRIORITY_LABELS_AVOIDED
                    )
                    night_priority_options = list(night_priority_labels.values())
                    night_priority_lookup = {
                        display_label: saved_label
                        for saved_label, display_label in night_priority_labels.items()
                    }
                    if not likes_nights:
                        st.caption(
                            "Wenn Nachtdienste erlaubt sind, aber vermieden werden sollen, sind die Stufen 1 und 2 "
                            "nicht auswählbar. Sonst wäre der Dienstplan logisch widersprüchlich."
                        )
                    default_night_priority = priority_label(
                        normalize_night_priority_value(
                            int(max_nights),
                            bool(likes_nights),
                            current.get("Prio Nacht", DEFAULT_PRIORITY_LABEL),
                        )
                    )
                    default_night_priority_display = night_priority_labels.get(
                        default_night_priority,
                        next(iter(night_priority_labels.values())),
                    )
                    selected_night_priority = st.selectbox(
                        "Wie wichtig ist dieser Nachtwunsch?",
                        options=night_priority_options,
                        index=night_priority_options.index(default_night_priority_display),
                        help=night_priority_help,
                    )
                    night_priority = night_priority_lookup[selected_night_priority]
            with night_cols[1]:
                double_nights = st.checkbox("Doppelnächte bevorzugt einteilen", value=bool(current["Nur Doppelnaechte"]))
                double_night_priority_options = list(DOUBLE_NIGHT_PRIORITY_LABELS.values())
                double_night_priority_lookup = {
                    display_label: saved_label
                    for saved_label, display_label in DOUBLE_NIGHT_PRIORITY_LABELS.items()
                }
                default_double_night_priority = priority_label(
                    current.get("Prio Doppelnaechte", DEFAULT_PRIORITY_LABEL)
                )
                default_double_night_display = DOUBLE_NIGHT_PRIORITY_LABELS.get(
                    default_double_night_priority,
                    DOUBLE_NIGHT_PRIORITY_LABELS[DEFAULT_PRIORITY_LABEL],
                )
                selected_double_night_priority = st.selectbox(
                    "Wie wichtig ist der Wunsch nach Doppelnächten?",
                    options=double_night_priority_options,
                    index=double_night_priority_options.index(default_double_night_display),
                    help=(
                        "Bewertet nur den Wunsch, Nachtdienste eher als Doppelnacht zu planen. "
                        "Max. Nachtdienste im Monat bleibt die harte Grenze."
                    ),
                )
                double_night_priority = double_night_priority_lookup[selected_double_night_priority]
                allow_three_nights = st.checkbox(
                    "3 Nächte in Folge erlauben",
                    value=bool(current.get("3 Naechte erlaubt", False)),
                )

        with weekend_tab:
            st.caption("Turnusdienst bedeutet oft Wochenendarbeit. 'Wochenende frei' sollte nur gesetzt werden, wenn es wirklich wichtig ist.")
            weekend_cols = st.columns(2)
            with weekend_cols[0]:
                weekends_off = st.checkbox("Wochenende bevorzugt frei", value=bool(current["Wochenende frei"]))
                weekend_priority = st.selectbox(
                    "Wichtigkeit Wochenende frei",
                    options=list(PRIORITY_LEVELS.keys()),
                    index=list(PRIORITY_LEVELS.keys()).index(priority_label(current.get("Prio Wochenende", DEFAULT_PRIORITY_LABEL))),
                )
            with weekend_cols[1]:
                joint_weekends = st.checkbox(
                    "Samstag/Sonntag nicht teilen",
                    value=bool(current.get("Gemeinsame Wochenenden", True)),
                    help="Samstag und Sonntag sollen möglichst gemeinsam frei oder gemeinsam gearbeitet sein.",
                )
                joint_weekend_priority = st.selectbox(
                    "Wichtigkeit Wochenende nicht teilen",
                    options=list(PRIORITY_LEVELS.keys()),
                    index=list(PRIORITY_LEVELS.keys()).index(priority_label(current.get("Prio gemeinsame Wochenenden", DEFAULT_PRIORITY_LABEL))),
                )

        with wish_free_tab:
            st.caption(
                f"Wunschfrei für {MONTH_NAMES[absence_month]} {int(absence_year)} auswählen. "
                "Wunschfrei mit Priorität 1 blockiert auch den Nachtdienst davor, wenn diese globale Regel aktiv ist."
            )
            wish_free_selected_days = calendar_day_checkbox_grid(
                "Wunschfrei",
                month_days,
                blocked_day_numbers,
                f"{key_base}_wf",
            )

        with vacation_tab:
            st.caption(
                f"Urlaub für {MONTH_NAMES[absence_month]} {int(absence_year)} auswählen. "
                "Urlaub zählt immer als bezahlte Stunden."
            )
            vacation_selected_days = calendar_day_checkbox_grid(
                "Urlaub",
                month_days,
                vacation_day_numbers,
                f"{key_base}_ur",
            )
            vacation_preview_employee = Employee(
                name=str(current["Name"]),
                qualification=str(current["Qualifikation"]),
                weekly_hours_target=parse_hour_value(weekly_hours_text, float(current.get("Wochenstunden", 30) or 30)),
                max_shifts_per_week=1,
                max_nights_per_month=0,
                likes_nights=False,
                double_nights_only=False,
                allow_three_consecutive_nights=False,
                rest_after_night=1,
                prefers_weekends_off=False,
                night_priority=3,
                double_night_priority=3,
                rest_priority=3,
                weekend_priority=3,
                wish_free_priority=1,
                vacation_days=tuple(day - 1 for day in vacation_selected_days),
                annual_vacation_weeks=annual_vacation_weeks,
                vacation_start_date=vacation_start_date.isoformat(),
                annual_vacation_workdays=vacation_workdays,
                vacation_day_hours=max(0.0, parse_hour_value(vacation_day_hours_text, DEFAULT_VACATION_DAY_HOURS)),
            )
            vacation_used_hours = format_minutes_as_hours(
                vacation_paid_minutes_for_month(vacation_preview_employee, month_days, True)
            )
            vacation_entitlement = vacation_entitlement_hours(vacation_preview_employee)
            vacation_period_start, vacation_period_end = vacation_period_for_month(
                vacation_preview_employee,
                int(absence_year),
                absence_month,
            )
            fixed_vacation_df = fixed_vacation_usage_dataframe(
                str(current["Name"]),
                {**current, "Urlaubs-Stichtag": vacation_start_date.isoformat()},
                st.session_state.get("saved_schedules", {}),
                vacation_period_start,
                vacation_period_end,
            )
            fixed_vacation_hours = (
                sum(
                    parse_hour_value(row.get("Fixiert verbraucht h", 0), 0)
                    for _, row in fixed_vacation_df.iterrows()
                )
                if not fixed_vacation_df.empty
                else 0
            )
            current_month_is_fixed = plan_month_key(int(absence_year), absence_month) in st.session_state.get("saved_schedules", {})
            pending_vacation_hours = 0 if current_month_is_fixed else vacation_used_hours
            vacation_info_cols = st.columns(3)
            vacation_info_cols[0].metric("Dieser Monat", f"{format_display_hours(vacation_used_hours)} h")
            vacation_info_cols[1].metric("Fixiert verbraucht", f"{format_display_hours(fixed_vacation_hours)} h")
            vacation_info_cols[2].metric(
                "Restanspruch",
                f"{format_display_hours(max(0, vacation_entitlement - fixed_vacation_hours - pending_vacation_hours))} h",
            )
            st.caption(
                f"Urlaubsjahr: {vacation_period_label(vacation_period_start, vacation_period_end)}. "
                f"Anspruch in diesem Zeitraum: {format_display_hours(vacation_entitlement)} h."
            )
            if fixed_vacation_df.empty:
                st.info("Für diese Person ist noch kein Urlaub in fixierten Dienstplänen verbraucht.")
            else:
                st.markdown("**Urlaub in fixierten Dienstplänen**")
                render_static_table(fixed_vacation_df, height_limit=180)

        with sick_tab:
            st.caption(f"Geplanten Krankenstand für {MONTH_NAMES[absence_month]} {int(absence_year)} auswählen.")
            sick_selected_days = calendar_day_checkbox_grid(
                "Krankenstand geplant",
                month_days,
                sick_day_numbers,
                f"{key_base}_ks",
            )

        with rules_tab:
            st.caption("Zusätzliche persönliche Regeln. Die rechtlichen Mindestregeln bleiben immer aktiv.")
            rules_cols = st.columns(2)
            with rules_cols[0]:
                rest_after_night = st.number_input(
                    "Freie Tage nach Nachtdienst",
                    min_value=1,
                    max_value=2,
                    value=int(current["Frei nach Nacht"]),
                    step=1,
                )
                rest_priority = st.selectbox(
                    "Wichtigkeit freie Tage nach Nacht",
                    options=list(PRIORITY_LEVELS.keys()),
                    index=list(PRIORITY_LEVELS.keys()).index(priority_label(current.get("Prio frei nach Nacht", DEFAULT_PRIORITY_LABEL))),
                )
            with rules_cols[1]:
                wish_free_priority = st.selectbox(
                    "Wichtigkeit Wunschfrei",
                    options=list(PRIORITY_LEVELS.keys()),
                    index=list(PRIORITY_LEVELS.keys()).index(priority_label(current.get("Prio Wunschfrei", "1 - muss immer zutreffen"))),
                )

        submitted = st.form_submit_button("Speichern", type="primary")

    if st.button("Schließen ohne Speichern"):
        close_employee_dialog_state()
        st.rerun()

    if submitted:
        weekly_hours = max(0.25, parse_hour_value(weekly_hours_text, float(current["Wochenstunden"])))
        max_weekly_hours = max(0.25, parse_hour_value(max_weekly_hours_text, float(current["Max. Wochenstunden"])))
        updated_wish_free_months = updated_monthly_absence_payload(
            current.get("Wunschfrei je Monat", ""),
            int(absence_year),
            absence_month,
            wish_free_selected_days,
        )
        updated_sick_months = updated_monthly_absence_payload(
            current.get("Krankenstand je Monat", ""),
            int(absence_year),
            absence_month,
            sick_selected_days,
        )
        updated_vacation_months = updated_monthly_absence_payload(
            current.get("Urlaub je Monat", ""),
            int(absence_year),
            absence_month,
            vacation_selected_days,
        )
        display_year = int(st.session_state.get("selected_year", date.today().year))
        display_month = int(st.session_state.get("selected_month", date.today().month))
        display_month_key = plan_month_key(display_year, display_month)
        new_row = {
            "Name": name.strip() or "Ohne Name",
            "Qualifikation": qualification,
            "Dienstplanrelevant": participates_in_schedule,
            "Wochenstunden": weekly_hours,
            "Max. Dienste/Woche": max_shifts,
            "Max. Tage in Folge": max_consecutive_workdays,
            "Max. Wochenstunden": max_weekly_hours,
            "Max. Naechte/Monat": max_nights,
            "Gerne Nacht": likes_nights,
            "Nur Doppelnaechte": double_nights,
            "3 Naechte erlaubt": allow_three_nights,
            "Frei nach Nacht": rest_after_night,
            "Wochenende frei": weekends_off,
            "Gemeinsame Wochenenden": joint_weekends,
            "Prio Nacht": night_priority,
            "Prio Doppelnaechte": double_night_priority,
            "Prio frei nach Nacht": rest_priority,
            "Prio Wochenende": weekend_priority,
            "Prio gemeinsame Wochenenden": joint_weekend_priority,
            "Prio Wunschfrei": wish_free_priority,
            "Wunschfrei-Tage": parse_monthly_day_map(updated_wish_free_months).get(display_month_key, ""),
            "Krankenstand-Tage": parse_monthly_day_map(updated_sick_months).get(display_month_key, ""),
            "Urlaub-Tage": parse_monthly_day_map(updated_vacation_months).get(display_month_key, ""),
            "Wunschfrei je Monat": updated_wish_free_months,
            "Krankenstand je Monat": updated_sick_months,
            "Urlaub je Monat": updated_vacation_months,
            "Urlaubswochen/Jahr": annual_vacation_weeks,
            "Urlaubstage/Jahr": vacation_workdays,
            "Urlaubstag h": max(0.0, parse_hour_value(vacation_day_hours_text, DEFAULT_VACATION_DAY_HOURS)),
            "Urlaubs-Stichtag": vacation_start_date.isoformat(),
            "Übernahme bestätigt": takeover_confirmed,
            "Übernahme Startdatum": takeover_start_date.isoformat() if takeover_start_date else "",
            "Übernahme Resturlaub h": parse_hour_value(takeover_vacation_text, 0.0),
            "Übernahme Zeitkonto h": parse_hour_value(takeover_time_balance_text, 0.0),
            "Übernahme Ersatzruhe h": parse_hour_value(takeover_replacement_rest_text, 0.0),
            "Übernahme Vortag": takeover_previous_day,
            "Übernahme Vor-Vortag": takeover_second_previous_day,
            "Übernahme Arbeitstage in Folge": int(takeover_previous_work_streak),
        }
        if is_edit:
            st.session_state.employees_df.loc[row_index, list(new_row.keys())] = list(new_row.values())
        else:
            st.session_state.employees_df = pd.concat(
                [st.session_state.employees_df, pd.DataFrame([new_row])],
                ignore_index=True,
            )
        st.session_state.sample_employee_set_version = "eigene-daten"
        st.session_state.generated_plan = None
        close_employee_dialog_state()
        st.rerun()


@st.dialog("Mitarbeiter löschen?")
def delete_employee_dialog(row_index: int) -> None:
    if row_index < 0 or row_index >= len(st.session_state.employees_df):
        st.error("Diese Person wurde nicht gefunden.")
        return
    employee_name = str(st.session_state.employees_df.iloc[row_index].get("Name", "MitarbeiterIn"))
    st.warning(f"{employee_name} wirklich aus der Mitarbeiterliste löschen?")
    st.caption("Gespeicherte, bereits fixierte Dienstpläne bleiben unverändert. Ein aktueller Entwurf wird verworfen.")
    delete_left, delete_right = st.columns(2)
    with delete_left:
        if st.button("Ja, löschen", type="primary"):
            st.session_state.employees_df = (
                st.session_state.employees_df
                .drop(index=row_index)
                .reset_index(drop=True)
            )
            st.session_state.sample_employee_set_version = "eigene-daten"
            st.session_state.generated_plan = None
            st.success("MitarbeiterIn wurde gelöscht.")
            st.rerun()
    with delete_right:
        if st.button("Abbrechen"):
            st.rerun()


@st.dialog("Dienstform")
def shift_dialog(row_index: int | None = None) -> None:
    is_edit = row_index is not None
    if is_edit:
        current = st.session_state.shifts_df.iloc[row_index].to_dict()
    else:
        next_number = len(st.session_state.shifts_df) + 1
        current = {
            "Kuerzel": f"D{next_number}",
            "Name": f"Zusatzdienst {next_number}",
            "Beginn": "08:00",
            "Ende": "16:00",
            "Stunden": 8.0,
            "Nacht": False,
            "Prioritaet": 1,
            "Farbe": SHIFT_COLORS[(next_number - 1) % len(SHIFT_COLORS)],
        }

    with st.form(f"shift_form_{row_index if is_edit else 'new'}"):
        code = st.text_input("Kürzel", value=str(current["Kuerzel"]), max_chars=4)
        name = st.text_input("Name", value=str(current["Name"]))
        start_text, end_text = derive_shift_times(current)
        start_input = st.text_input("Beginn", value=start_text.replace(":", str(st.session_state.get("time_separator", ":"))))
        end_input = st.text_input("Ende", value=end_text.replace(":", str(st.session_state.get("time_separator", ":"))))
        start_minutes_value = parse_clock_to_minutes(start_input)
        end_minutes_value = parse_clock_to_minutes(end_input)
        if start_minutes_value is None or end_minutes_value is None:
            st.warning("Zeitformat bitte als Uhrzeit wie 12:15 eingeben.")
            duration_hours = float(current.get("Stunden", 8.0))
        else:
            duration_hours = round(
                duration_minutes_between(start_minutes_value, end_minutes_value) / 60,
                2,
            )
        st.caption(f"Berechnete Dauer: {duration_hours:.2f} Stunden")
        is_night = st.checkbox("Ist Nachtdienst", value=bool(current["Nacht"]))
        shift_priority = st.selectbox(
            "Priorität",
            options=list(SHIFT_PRIORITY_LEVELS.keys()),
            index=list(SHIFT_PRIORITY_LEVELS.keys()).index(shift_priority_label(current.get("Prioritaet", 1))),
        )
        color = st.color_picker("Farbe", value=str(current["Farbe"]) or SHIFT_COLORS[0])
        submitted = st.form_submit_button("Speichern", type="primary")

    if submitted:
        start_minutes_value = parse_clock_to_minutes(start_input)
        end_minutes_value = parse_clock_to_minutes(end_input)
        if start_minutes_value is None or end_minutes_value is None:
            st.error("Beginn und Ende müssen als Uhrzeit wie 12:15 eingegeben werden.")
            st.stop()
        new_row = {
            "Kuerzel": code.strip().upper() or f"D{len(st.session_state.shifts_df) + 1}",
            "Name": name.strip() or "Dienst",
            "Beginn": f"{start_minutes_value // 60:02d}:{start_minutes_value % 60:02d}",
            "Ende": f"{end_minutes_value // 60:02d}:{end_minutes_value % 60:02d}",
            "Stunden": duration_hours,
            "Nacht": is_night,
            "Prioritaet": SHIFT_PRIORITY_LEVELS[shift_priority],
            "Farbe": color.strip() or SHIFT_COLORS[0],
        }
        if is_edit:
            st.session_state.shifts_df.loc[row_index, list(new_row.keys())] = list(new_row.values())
        else:
            st.session_state.shifts_df = pd.concat(
                [st.session_state.shifts_df, pd.DataFrame([new_row])],
                ignore_index=True,
            )
        st.session_state.shifts_df = shift_definitions_from_editor(st.session_state.shifts_df)
        st.rerun()


@st.dialog("Standardbedarf")
def resource_dialog(type_name: str, shifts: list[str]) -> None:
    resource_df = normalize_resource_dataframe(st.session_state.resources_df, shifts)
    current_row = resource_df[resource_df["Tagesart"] == type_name].iloc[0].to_dict()

    with st.form(f"resource_form_{type_name}"):
        values = {}
        for shift in shifts:
            values[shift] = st.number_input(shift, min_value=0, max_value=20, value=int(current_row[shift]), step=1)
        submitted = st.form_submit_button("Speichern", type="primary")

    if submitted:
        row_index = resource_df.index[resource_df["Tagesart"] == type_name][0]
        for shift, value in values.items():
            resource_df.loc[row_index, shift] = value
        st.session_state.resources_df = normalize_resource_dataframe(resource_df, shifts)
        st.rerun()


@st.dialog("Tagesbedarf")
def day_requirement_dialog(
    day_index: int,
    month_key: str,
    shifts: list[str],
    current_values: dict[str, int],
) -> None:
    with st.form(f"day_requirement_form_{month_key}_{day_index}"):
        values = {}
        for shift in shifts:
            values[shift] = st.number_input(shift, min_value=0, max_value=20, value=int(current_values[shift]), step=1)
        submitted = st.form_submit_button("Speichern", type="primary")

    if submitted:
        overrides = st.session_state.setdefault("day_requirement_overrides", {})
        month_overrides = overrides.setdefault(month_key, {})
        month_overrides[int(day_index)] = values
        st.rerun()


@st.dialog("Alle gespeicherten Dienstpläne löschen?")
def clear_saved_schedules_dialog() -> None:
    st.warning("Wirklich löschen? Alle gespeicherten und fixierten Dienstpläne werden entfernt.")
    confirm_left, confirm_right = st.columns(2)
    with confirm_left:
        if st.button("Ja, löschen", type="primary", width="stretch"):
            st.session_state.saved_schedules = {}
            st.session_state.generated_plan = None
            save_saved_schedules({})
            st.rerun()
    with confirm_right:
        if st.button("Nein", width="stretch"):
            st.rerun()


def daily_coverage_dataframe(
    schedule: dict,
    days: list[date],
    holidays: dict[date, str],
    daily_requirements: dict[tuple[int, str], int],
    shift_df: pd.DataFrame,
) -> pd.DataFrame:
    cleaned_shifts = shift_definitions_from_editor(shift_df)
    shift_names = {row["Kuerzel"]: row["Name"] for _, row in cleaned_shifts.iterrows()}
    shifts = cleaned_shifts["Kuerzel"].tolist()
    rows = []
    for day_index, current_day in enumerate(days):
        holiday_name = holidays.get(current_day, "")
        row = {
            "Tag": day_label(current_day),
            "Kalender": day_type(current_day, holidays),
            "Feiertag": holiday_name,
        }
        assigned_by_shift = {shift: [] for shift in shifts}
        for employee_name, assignments in schedule.items():
            shift = assignments[day_index]
            if shift in assigned_by_shift:
                assigned_by_shift[shift].append(employee_name)
        for shift in shifts:
            assigned_text = ", ".join(assigned_by_shift[shift])
            missing = max(0, daily_requirements.get((day_index, shift), 0) - len(assigned_by_shift[shift]))
            if missing:
                assigned_text = f"{assigned_text} | OFFEN: {missing}" if assigned_text else f"OFFEN: {missing}"
            row[shift_names[shift]] = assigned_text
        row["Bedarf"] = " / ".join(
            f"{shift}:{daily_requirements[(day_index, shift)]}" for shift in shifts
        )
        rows.append(row)
    return pd.DataFrame(rows)


def style_daily_calendar(df: pd.DataFrame, shift_df: pd.DataFrame):
    shift_columns = shift_definitions_from_editor(shift_df)["Name"].tolist()

    def color_cells(value: str) -> str:
        if value == "":
            return ""
        if "OFFEN" in str(value):
            return "background-color: #fee2e2; color: #991b1b; font-weight: 800;"
        return "background-color: #eef2ff; color: #1f2937; font-weight: 650;"

    def color_day_type(value: str) -> str:
        if value == "Sonntag/Feiertag":
            return "background-color: #fee2e2; color: #991b1b; font-weight: 700;"
        if value == "Samstag":
            return "background-color: #fef3c7; color: #92400e; font-weight: 700;"
        return "background-color: #f8fafc; color: #334155;"

    return (
        df.style.map(color_cells, subset=shift_columns)
        .map(color_day_type, subset=["Kalender"])
    )


def satisfaction_detail_action(detail: str) -> tuple[str, str]:
    lower_detail = detail.lower()
    if "möglichst keine nachtdienste" in lower_detail:
        return (
            "Nachtdienste gegen Wunsch",
            "Mehr nachtgeeignete Personen einplanen, Nachtbedarf reduzieren oder bei diesen Personen Nachtwunsch auf Priorität 1 setzen.",
        )
    if "gerne nachtdienste" in lower_detail:
        return (
            "Gewünschte Nachtdienste fehlen",
            "Nachtdienste stärker an Personen mit Nachtwunsch geben oder Nachtgrenzen dieser Personen erhöhen.",
        )
    if "wochenende frei" in lower_detail:
        return (
            "Wochenend-/Feiertagswünsche verletzt",
            "Mehr Wochenend-personal freigeben, Wochenendbedarf senken oder wichtige Wochenendfrei-Wünsche auf Priorität 1 setzen.",
        )
    if "gemeinsame wochenenden" in lower_detail or "geteilt" in lower_detail:
        return (
            "Wochenenden geteilt",
            "Priorität für gemeinsame Wochenenden erhöhen oder Samstag/Sonntag-Bedarf stärker zusammen planen.",
        )
    if "doppelnächte" in lower_detail or "standen einzeln" in lower_detail:
        return (
            "Einzelne Nachtdienste trotz Doppelnacht-Wunsch",
            "Doppelnacht-Priorität erhöhen, zwei Nächte in Folge ermöglichen oder einzelne Nachtdienste auf andere Personen verschieben.",
        )
    if "wunschfrei nicht eingehalten" in lower_detail:
        return (
            "Wunschfrei verletzt",
            "Wichtige Wunschfrei-Tage auf Priorität 1 setzen oder Tagesbedarf an diesen Tagen reduzieren.",
        )
    if "krankenstand" in lower_detail:
        return (
            "Geplanter Krankenstand betroffen",
            "Krankenstand muss frei bleiben; Bedarf reduzieren oder anderes Personal für diese Tage freigeben.",
        )
    return (
        "Weiche Wünsche verletzt",
        "Priorität der wirklich wichtigen Wünsche erhöhen oder mehr planbare Alternativen schaffen.",
    )


def satisfaction_action_dataframe(metrics_df: pd.DataFrame, open_services: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if metrics_df.empty:
        return pd.DataFrame(rows)

    average_satisfaction = float(metrics_df.get("Zufriedenheit %", pd.Series([0])).mean() or 0)
    if average_satisfaction < 50:
        rows.append(
            {
                "Dringlichkeit": "hoch",
                "Thema": "Zufriedenheit sehr niedrig",
                "Betroffen": "alle",
                "Was tun?": "Nicht sofort fixieren. Zuerst die größten Wunschverletzungen unten bearbeiten und danach neu generieren.",
            }
        )
    elif average_satisfaction < 75:
        rows.append(
            {
                "Dringlichkeit": "mittel",
                "Thema": "Zufriedenheit ausbaufähig",
                "Betroffen": "alle",
                "Was tun?": "Die schlechtesten Einzelwerte prüfen und gezielt Wünsche oder Personalverfügbarkeit anpassen.",
            }
        )

    if not open_services.empty:
        rows.append(
            {
                "Dringlichkeit": "hoch",
                "Thema": "Offene Dienste",
                "Betroffen": f"{int(open_services['Offen'].sum())} Dienst(e)",
                "Was tun?": "Pflichtbedarf senken, mehr Personal freigeben oder Überstunden-Grenzen gezielt erhöhen. Offene Dienste drücken die Planqualität stark.",
            }
        )

    grouped_actions: dict[tuple[str, str], dict[str, object]] = {}
    for _, row in metrics_df.iterrows():
        employee_name = str(row.get("Name", ""))
        details_by_priority = row.get("Verstossdetails nach Prioritaet", {}) or {}
        if not isinstance(details_by_priority, dict):
            continue
        for priority in range(1, 6):
            priority_info = details_by_priority.get(priority) or details_by_priority.get(str(priority)) or {}
            if not isinstance(priority_info, dict):
                continue
            for detail in priority_info.get("details", []) or []:
                topic, action = satisfaction_detail_action(str(detail))
                key = (topic, action)
                grouped = grouped_actions.setdefault(
                    key,
                    {"count": 0, "priority": priority, "people": []},
                )
                grouped["count"] = int(grouped["count"]) + 1
                grouped["priority"] = min(int(grouped["priority"]), priority)
                if employee_name and employee_name not in grouped["people"]:
                    grouped["people"].append(employee_name)

    for (topic, action), info in sorted(
        grouped_actions.items(),
        key=lambda item: (int(item[1]["priority"]), -int(item[1]["count"]), item[0][0]),
    )[:8]:
        people = list(info["people"])
        rows.append(
            {
                "Dringlichkeit": "hoch" if int(info["priority"]) <= 2 else "mittel",
                "Thema": topic,
                "Betroffen": ", ".join(people[:4]) + (f" und {len(people) - 4} weitere" if len(people) > 4 else ""),
                "Was tun?": action,
            }
        )

    deviation_df = metrics_df.copy()
    if "Stundenabweichung h" in deviation_df.columns:
        deviation_df["Stundenabweichung h"] = pd.to_numeric(deviation_df["Stundenabweichung h"], errors="coerce").fillna(0)
        max_deviation = float(deviation_df["Stundenabweichung h"].max() or 0)
        if max_deviation >= 8:
            affected = deviation_df.sort_values("Stundenabweichung h", ascending=False).head(4)["Name"].tolist()
            rows.append(
                {
                    "Dringlichkeit": "mittel",
                    "Thema": "Stunden ungleich verteilt",
                    "Betroffen": ", ".join(str(name) for name in affected),
                    "Was tun?": "Sollstunden, Minusstunden-/Überstunden-Grenzen und Dienstbedarf abgleichen. Bei zu vielen Plusstunden mehr Personal oder weniger Pflichtdienste einplanen.",
                }
            )

    return pd.DataFrame(rows).drop_duplicates()


def low_satisfaction_people_dataframe(metrics_df: pd.DataFrame, limit: int = 6) -> pd.DataFrame:
    if metrics_df.empty or "Zufriedenheit %" not in metrics_df.columns:
        return pd.DataFrame()
    display_df = metrics_df.copy()
    display_df["Zufriedenheit %"] = pd.to_numeric(display_df["Zufriedenheit %"], errors="coerce").fillna(0)
    low_df = display_df.sort_values("Zufriedenheit %", ascending=True).head(limit)
    rows = []
    for _, row in low_df.iterrows():
        satisfaction = float(row.get("Zufriedenheit %", 0) or 0)
        if satisfaction >= 75:
            continue
        wishes = str(row.get("Welche Wuensche verletzt", "-"))
        if wishes == "-":
            deviation = float(row.get("Stundenabweichung h", 0) or 0)
            wishes = f"Stundenabweichung {format_display_hours(deviation)} h" if deviation else "Keine Hauptursache erkannt"
        rows.append(
            {
                "MitarbeiterIn": row.get("Name", ""),
                "Zufriedenheit": f"{format_display_hours(satisfaction)} %",
                "+/- h": format_display_hours(row.get("Plus/Minus Stunden", 0)),
                "Hauptgrund": wishes,
                "Was tun?": "Diese Person zuerst prüfen: Wunsch-Prioritäten, Nacht-/Wochenend-Eignung und Stundenrahmen anpassen.",
            }
        )
    return pd.DataFrame(rows)


def plan_explanation_dataframe(
    metrics_df: pd.DataFrame,
    open_services: pd.DataFrame,
    rule_checks: list[dict[str, str]] | None,
    solver_status: str | None,
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    rule_checks = rule_checks or []
    if metrics_df.empty:
        return pd.DataFrame(rows)

    satisfaction_series = pd.to_numeric(
        metrics_df.get("Zufriedenheit %", pd.Series([0])),
        errors="coerce",
    ).fillna(0)
    average_satisfaction = float(satisfaction_series.mean() or 0)
    minimum_satisfaction = float(satisfaction_series.min() or 0)
    warning_count = int(pd.to_numeric(metrics_df.get("Aktive Warnungen", pd.Series([0])), errors="coerce").fillna(0).sum())
    rule_error_count = sum(1 for check in rule_checks if check.get("Status") == "Fehler")
    rule_hint_count = sum(1 for check in rule_checks if check.get("Status") == "Hinweis")
    open_count = int(open_services["Offen"].sum()) if open_services is not None and not open_services.empty else 0

    if rule_error_count:
        rows.append(
            {
                "Bereich": "Rechtliche Sicherheit",
                "Bewertung": "rot",
                "Warum?": f"{rule_error_count} harte Regelverletzung(en)",
                "Was tun?": "Nicht fixieren. Regelprüfung öffnen und diese Fehler zuerst beheben.",
            }
        )
    elif rule_hint_count:
        rows.append(
            {
                "Bereich": "Rechtliche Sicherheit",
                "Bewertung": "gelb",
                "Warum?": f"Harte Regeln OK, aber {rule_hint_count} Hinweis(e)",
                "Was tun?": "Hinweise wie Durchrechnung oder verkürzte Wochenruhe bewusst prüfen.",
            }
        )
    else:
        rows.append(
            {
                "Bereich": "Rechtliche Sicherheit",
                "Bewertung": "grün",
                "Warum?": "Keine harten Regelverletzungen gefunden",
                "Was tun?": "Plan kann fachlich weiter geprüft werden.",
            }
        )

    if average_satisfaction >= 90 and minimum_satisfaction >= 70:
        satisfaction_action = "Plan ist aus Zufriedenheitssicht stark. Nur offene Dienste und Hinweise prüfen."
    elif average_satisfaction >= 80:
        satisfaction_action = "Schlechteste Personen und wichtigste Wunschverletzungen prüfen."
    else:
        satisfaction_action = "Nicht sofort fixieren. Wünsche, Nacht-/Wochenendfähigkeit und Bedarf gezielt anpassen."
    rows.append(
        {
            "Bereich": "Mitarbeiterzufriedenheit",
            "Bewertung": "grün" if average_satisfaction >= 90 and minimum_satisfaction >= 70 else ("gelb" if average_satisfaction >= 80 else "rot"),
            "Warum?": f"{format_display_hours(round(average_satisfaction, 1))} % Durchschnitt, schlechtester Wert {format_display_hours(round(minimum_satisfaction, 1))} %",
            "Was tun?": satisfaction_action,
        }
    )

    if open_count:
        open_by_priority = ""
        if "Prioritaet" in open_services.columns:
            grouped = (
                open_services.groupby("Prioritaet")["Offen"].sum().sort_index()
                if not open_services.empty
                else pd.Series(dtype=int)
            )
            open_by_priority = ", ".join(f"Prio {priority}: {int(count)}" for priority, count in grouped.items())
        rows.append(
            {
                "Bereich": "Abdeckung",
                "Bewertung": "gelb" if open_count <= 10 else "rot",
                "Warum?": f"{open_count} offene Dienste" + (f" ({open_by_priority})" if open_by_priority else ""),
                "Was tun?": "Offene Dienste nach Priorität prüfen. Bei Prio-1-Offenstand Bedarf, Regeln oder Personal korrigieren.",
            }
        )
    else:
        rows.append(
            {
                "Bereich": "Abdeckung",
                "Bewertung": "grün",
                "Warum?": "Alle Dienste besetzt",
                "Was tun?": "Keine Änderung nötig.",
            }
        )

    if warning_count:
        rows.append(
            {
                "Bereich": "Wunschverletzungen",
                "Bewertung": "gelb" if warning_count <= 20 else "rot",
                "Warum?": f"{warning_count} aktive Warnung(en)",
                "Was tun?": "Handlungsanweisungen öffnen und zuerst Priorität 1 bis 3 bearbeiten.",
            }
        )

    rows.append(
        {
            "Bereich": "Optimierungsbeweis",
            "Bewertung": "grün" if solver_status == "OPTIMAL" else "gelb",
            "Warum?": solver_status_detail(solver_status),
            "Was tun?": "Bei gültig, nicht optimal bewiesen: Weiter optimieren verwenden, wenn Zeit bleibt." if solver_status != "OPTIMAL" else "Kein weiterer Optimierungsschritt nötig.",
        }
    )
    return pd.DataFrame(rows)


def render_replacement_search(
    schedule: dict,
    metrics: dict,
    days: list[date],
    employees: list[Employee],
    daily_requirements: dict[tuple[int, str], int],
    shift_df: pd.DataFrame,
    shifts: list[str],
    night_shifts: list[str],
    shift_minutes_by_code: dict[str, int],
    shift_time_by_code: dict[str, tuple[int, int]],
    previous_assignments: dict[str, list[str]] | None,
    *,
    key_prefix: str,
) -> None:
    if not schedule or not days or not shifts:
        return
    with st.expander("Ersatz suchen / Dienst tauschen", expanded=False):
        st.caption(
            "Diese Liste ist nur eine Entscheidungshilfe. Der Dienstplan wird dadurch noch nicht geändert."
        )
        date_labels = [day_label(current_day) for current_day in days]
        search_cols = st.columns([0.35, 0.65])
        with search_cols[0]:
            selected_date_label = st.selectbox(
                "Datum",
                options=date_labels,
                index=0,
                key=f"{key_prefix}_replacement_date",
            )
        day_index = date_labels.index(selected_date_label)
        shift_options = replacement_shift_options(
            schedule,
            day_index,
            daily_requirements,
            shift_df,
            shifts,
        )
        shift_labels = [label for _, label in shift_options]
        with search_cols[1]:
            selected_shift_label = st.selectbox(
                "Dienst",
                options=shift_labels,
                index=0,
                key=f"{key_prefix}_replacement_shift_{day_index}",
            )
        target_shift = dict((label, shift) for shift, label in shift_options)[selected_shift_label]
        demand = int(daily_requirements.get((day_index, target_shift), 0) or 0)
        assigned_names = [
            str(employee_name)
            for employee_name, assignments in schedule.items()
            if day_index < len(assignments) and first_real_shift(assignments[day_index]) == target_shift
        ]
        missing_count = max(0, demand - len(assigned_names))
        if assigned_names:
            st.caption(
                "Aktuell eingeteilt: "
                + ", ".join(assigned_names[:6])
                + (f" und {len(assigned_names) - 6} weitere" if len(assigned_names) > 6 else "")
            )
        if missing_count:
            st.warning(f"Für diesen Dienst sind aktuell {missing_count} Position(en) offen.")

        candidate_df, hidden_count = replacement_candidate_dataframe(
            schedule=schedule,
            metrics=metrics,
            employees=employees,
            days=days,
            day_index=day_index,
            target_shift=target_shift,
            shifts=shifts,
            night_shifts=night_shifts,
            shift_minutes_by_code=shift_minutes_by_code,
            shift_time_by_code=shift_time_by_code,
            previous_assignments=previous_assignments,
            vacation_weekend_policy=st.session_state.get("vacation_weekend_policy", DEFAULT_VACATION_WEEKEND_POLICY),
            block_night_before_wish_free=bool(st.session_state.get("block_night_before_wish_free", True)),
            daily_max_work_hours=float(st.session_state.get("daily_max_work_hours", 12.0)),
            max_overtime_percent=float(st.session_state.get("max_overtime_percent", 10)),
            max_overtime_hours=float(st.session_state.get("max_overtime_hours", 12)),
            night_credit_mode=str(st.session_state.get("night_credit_mode", DEFAULT_NIGHT_CREDIT_MODE)),
            night_credit_hours=float(st.session_state.get("night_credit_hours", DEFAULT_NIGHT_CREDIT_HOURS)),
        )
        if candidate_df.empty:
            st.error(
                "Für diesen Dienst wurde keine rechtlich/regellogisch passende Ersatzperson gefunden."
            )
        else:
            st.dataframe(germanize_dataframe(candidate_df), width="stretch", hide_index=True)
            st.caption(
                "Sortiert nach Regelcheck, Wunschkonflikten, Monatsstunden und gesamtem Zeitkonto nach Plan."
            )
        if hidden_count:
            st.caption(
                f"{hidden_count} Person(en) werden nicht angezeigt, weil sie bereits eingeteilt, abwesend "
                "oder nach harten Regeln nicht passend sind."
            )


def render_plan_result(
    schedule: dict,
    metrics: dict,
    days: list[date],
    employees: list[Employee],
    holidays: dict[date, str],
    daily_requirements: dict[tuple[int, str], int],
    shift_df: pd.DataFrame,
    fixed: bool = False,
    open_rest_notes: list[str] | None = None,
    rule_checks: list[dict[str, str]] | None = None,
    open_shift_codes: list[str] | None = None,
    shift_priority_by_code: dict[str, int] | None = None,
    solver_status: str | None = None,
    calculation_mode: str | None = None,
    shifts: list[str] | None = None,
    night_shifts: list[str] | None = None,
    shift_minutes_by_code: dict[str, int] | None = None,
    shift_time_by_code: dict[str, tuple[int, int]] | None = None,
    previous_assignments: dict[str, list[str]] | None = None,
) -> None:
    shifts = shifts or shift_codes(shift_df)
    night_shifts = night_shifts or night_shift_codes(shift_df)
    shift_minutes_by_code = shift_minutes_by_code or shift_minutes(shift_df)
    shift_time_by_code = shift_time_by_code or shift_time_windows(shift_df)
    metrics_df = pd.DataFrame.from_dict(metrics, orient="index").reset_index(names="Name")
    for column in [
        "Aktive Warnungen",
        "Verletzungen Prio 1",
        "Verletzungen Prio 2",
        "Verletzungen Prio 3",
        "Verletzungen Prio 4",
        "Verletzungen Prio 5",
    ]:
        if column not in metrics_df.columns:
            metrics_df[column] = 0
    if "Verstossdetails nach Prioritaet" not in metrics_df.columns:
        metrics_df["Verstossdetails nach Prioritaet"] = [{} for _ in range(len(metrics_df))]
    total_violations = int(metrics_df["Aktive Warnungen"].sum()) if not metrics_df.empty else 0
    open_services = open_services_dataframe(
        schedule,
        days,
        daily_requirements,
        shift_df,
        open_shift_codes=open_shift_codes,
        shift_priority_by_code=shift_priority_by_code,
    )
    cleaned_rule_checks = []
    for check in rule_checks or []:
        pruefung = str(check.get("Prüfung", ""))
        status = str(check.get("Status", ""))
        if pruefung == "Ruhepause" and status == "Hinweis":
            continue
        if pruefung == "Offene Dienste" and status == "Hinweis":
            continue
        cleaned_rule_checks.append(dict(check))
    hard_open_count = 0
    if not open_services.empty and "Prioritaet" in open_services.columns:
        hard_open_count = int(open_services[open_services["Prioritaet"].astype(int) == 1]["Offen"].sum())
    if hard_open_count and not any(check.get("Prüfung") == "Offene Pflichtdienste" for check in cleaned_rule_checks):
        cleaned_rule_checks.append(
            {
                "Status": "Fehler",
                "Prüfung": "Offene Pflichtdienste",
                "Ergebnis": f"{hard_open_count} Prio-1-Dienst(e) bleiben offen.",
                "Was tun?": "Pflichtdienste prüfen, Personal erhöhen oder harte Grenzwerte lockern.",
            }
        )
    rule_checks = cleaned_rule_checks
    rule_error_count = sum(1 for check in rule_checks if check.get("Status") == "Fehler")
    open_service_count = int(open_services["Offen"].sum()) if not open_services.empty else 0
    average_satisfaction = (
        round(float(metrics_df["Zufriedenheit %"].mean()), 1)
        if "Zufriedenheit %" in metrics_df and not metrics_df.empty
        else 0
    )
    max_hour_deviation = (
        float(pd.to_numeric(metrics_df.get("Stundenabweichung h", pd.Series([0])), errors="coerce").fillna(0).max())
        if not metrics_df.empty
        else 0
    )

    st.markdown("**Qualitätsampel**")
    render_traffic_light_cards(
        plan_quality_signal_rows(
            metrics_df,
            rule_checks,
            open_service_count,
            solver_status,
        )
    )

    summary_cols = st.columns(6)
    summary_cols[0].metric("Zufriedenheit Ø", f"{format_display_hours(average_satisfaction)} %")
    summary_cols[1].metric("Aktive Warnungen", total_violations)
    summary_cols[2].metric("Offene Dienste", open_service_count)
    summary_cols[3].metric("Max. Abweichung", f"{format_display_hours(max_hour_deviation)} h")
    summary_cols[4].metric("Geplante Dienste", int(metrics_df["Dienste"].sum()))
    with summary_cols[5]:
        render_status_card("Optimalität", solver_status_text(solver_status), solver_status_detail(solver_status))

    if fixed:
        st.success("Dieser Monat ist gespeichert und für die MitarbeiterInnen fixiert.")
    if solver_status == "OPTIMAL":
        st.info(
            "Der interne Solverlauf wurde optimal abgeschlossen. "
            "Der angezeigte Plan ist die beste geprüfte Variante nach den aktuellen Bewertungskriterien."
        )
    elif solver_status == "FEASIBLE":
        st.warning(
            "Der Plan ist gültig, aber der Solver konnte innerhalb der Suche nicht beweisen, "
            "dass dieser interne Rechenschritt optimal ist."
        )
    if calculation_mode:
        st.caption(f"Berechnungsart: {normalize_calculation_mode(calculation_mode)}")

    if rule_checks:
        rule_df = pd.DataFrame(rule_checks)
        problem_rules = rule_df[rule_df["Status"].isin(["Fehler", "Hinweis"])]
        if not problem_rules.empty:
            with st.expander(
                f"Rechtliche Hinweise anzeigen ({len(problem_rules)})",
                expanded=rule_error_count > 0,
            ):
                st.dataframe(germanize_dataframe(problem_rules), width="stretch", hide_index=True)

    explanation_df = plan_explanation_dataframe(
        metrics_df,
        open_services,
        rule_checks,
        solver_status,
    )
    if not explanation_df.empty:
        with st.expander("Warum sieht dieser Plan so aus?", expanded=open_service_count > 0 or average_satisfaction < 85):
            st.caption(
                "Diese Erklärung übersetzt Kennzahlen in konkrete Bedeutung: rechtliche Sicherheit, Zufriedenheit, Abdeckung und Beweisgrad."
            )
            st.dataframe(germanize_dataframe(explanation_df), width="stretch", hide_index=True)

    action_df = satisfaction_action_dataframe(metrics_df, open_services)
    low_people_df = low_satisfaction_people_dataframe(metrics_df)
    needs_attention = (
        average_satisfaction < 85
        or open_service_count > 0
        or total_violations > 0
        or rule_error_count > 0
    )
    if average_satisfaction < 50:
        st.error(
            "Die Zufriedenheit ist sehr niedrig. Bitte diesen Plan erst fixieren, "
            "wenn die wichtigsten Ursachen darunter geprüft wurden."
        )
    elif average_satisfaction < 75:
        st.warning("Die Zufriedenheit ist noch ausbaufähig. Die folgenden Punkte erhöhen sie am schnellsten.")
    else:
        st.success("Die Zufriedenheit ist im guten Bereich.")

    if not action_df.empty or not low_people_df.empty:
        with st.expander("Zufriedenheit verbessern - konkrete Handlungsanweisungen", expanded=needs_attention):
            if not action_df.empty:
                st.dataframe(germanize_dataframe(action_df), width="stretch", hide_index=True)
            if not low_people_df.empty:
                st.markdown("**Personen zuerst prüfen**")
                st.dataframe(low_people_df, width="stretch", hide_index=True)

    render_replacement_search(
        schedule=schedule,
        metrics=metrics,
        days=days,
        employees=employees,
        daily_requirements=daily_requirements,
        shift_df=shift_df,
        shifts=shifts,
        night_shifts=night_shifts,
        shift_minutes_by_code=shift_minutes_by_code,
        shift_time_by_code=shift_time_by_code,
        previous_assignments=previous_assignments,
        key_prefix="fixed" if fixed else "draft",
    )

    employee_tab, calendar_tab, metrics_tab = st.tabs(
        ["Mitarbeiteransicht", "Kalenderansicht", "Auswertung"]
    )

    with employee_tab:
        df = schedule_dataframe(schedule, days, employees, metrics)
        employee_table_height = 90 + (len(df) + 1) * 38
        st.dataframe(style_schedule(df, shift_df), width="stretch", height=employee_table_height)

    with calendar_tab:
        control_cols = st.columns(3)
        control_cols[0].metric("Offene Dienste", open_service_count)
        control_cols[1].metric("Regelfehler", rule_error_count)
        control_cols[2].metric("Warnungen", total_violations)
        if rule_checks:
            rule_df = pd.DataFrame(rule_checks)
            problem_rules = rule_df[rule_df["Status"].isin(["Fehler", "Hinweis"])]
            if not problem_rules.empty:
                st.dataframe(germanize_dataframe(problem_rules), width="stretch", hide_index=True)
        if not open_services.empty:
            st.warning("Diese Dienste bleiben offen und müssen bewusst geprüft werden.")
            st.dataframe(germanize_dataframe(open_services), width="stretch", hide_index=True)
        daily_df = daily_coverage_dataframe(
            schedule,
            days,
            holidays,
            daily_requirements,
            shift_df,
        )
        for week_days in calendar_week_day_indices(days):
            week_number = days[week_days[0]].isocalendar().week
            st.markdown(f"**Kalenderwoche {week_number}**")
            st.dataframe(
                style_daily_calendar(daily_df.iloc[week_days], shift_df),
                width="stretch",
                hide_index=True,
            )

    with metrics_tab:
        display_metrics_df = metrics_df.drop(
            columns=[
                "Verstossdetails nach Prioritaet",
                "Verletzungen Prio 4",
                "Verletzungen Prio 5",
            ],
            errors="ignore",
        )
        st.dataframe(germanize_dataframe(display_metrics_df), width="stretch", hide_index=True)
        st.caption(
            "Sollstunden werden anteilig für den geplanten Monat berechnet. "
            "Plus/Minus zeigt die Abweichung vom fairen Monatsziel. ER steht für Ersatzruhetag."
        )
        if rule_checks:
            st.markdown("**Regelprüfung**")
            rule_df = pd.DataFrame(rule_checks)
            st.dataframe(germanize_dataframe(rule_df), width="stretch", hide_index=True)

    st.subheader("Warnungen und Hinweise")
    rule_error_count = sum(1 for check in (rule_checks or []) if check.get("Status") == "Fehler")
    if rule_error_count:
        st.error(
            f"Die Regelprüfung meldet {rule_error_count} Fehler. "
            "Bitte Plan und Einstellungen prüfen, bevor der Plan fixiert wird."
        )
    if total_violations == 0:
        st.info("Alle Prioritäten 1 bis 3 wurden eingehalten.")
    else:
        st.info(
            f"Es gibt {total_violations} aktive Verstöße in den Prioritäten 1 bis 3. "
            "Die wichtigsten Details stehen in den folgenden Bereichen."
        )
    for priority in range(1, 4):
        column_name = f"Verletzungen Prio {priority}"
        category_total = int(metrics_df[column_name].sum()) if column_name in metrics_df else 0
        title = f"Priorität {priority}: {category_total} Verstoß(e)"
        with st.expander(title, expanded=priority <= 3 and category_total > 0):
            if category_total == 0:
                st.caption("Keine Verstöße in dieser Kategorie.")
                continue
            category_rows = []
            for _, row in metrics_df.iterrows():
                details_by_priority = row.get("Verstossdetails nach Prioritaet", {}) or {}
                priority_info = (
                    (details_by_priority.get(priority) or details_by_priority.get(str(priority)) or {})
                    if isinstance(details_by_priority, dict)
                    else {}
                )
                if int(priority_info.get("count", 0)) <= 0:
                    continue
                category_rows.append(
                    {
                        "Name": row["Name"],
                        "Verstöße": int(priority_info.get("count", 0)),
                        "Details": "; ".join(priority_info.get("details", [])) or "-",
                    }
                )
            if category_rows:
                st.dataframe(germanize_dataframe(pd.DataFrame(category_rows)), width="stretch", hide_index=True)

    if open_rest_notes:
        st.warning("Nicht alle Ersatzruhetage konnten im aktuellen Monat eingetragen werden.")
        st.dataframe(pd.DataFrame({"Offen": open_rest_notes}), width="stretch", hide_index=True)

    if not open_services.empty:
        st.warning(
            f"{int(open_services['Offen'].sum())} Dienst(e) bleiben offen. "
            "Die aktuelle Kombination aus Verfügbarkeit, Ruhezeit, Wochenlimits und Überstunden-Grenzen lässt hier keine vollständige Besetzung zu."
        )
        st.dataframe(germanize_dataframe(open_services), width="stretch", hide_index=True)


st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }
    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 14px 16px;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }
    .status-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        min-height: 104px;
        padding: 13px 16px;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }
    .status-card-label {
        color: #1f2937;
        font-size: 0.88rem;
        margin-bottom: 0.45rem;
    }
    .status-card-value {
        color: #111827;
        font-size: 1.45rem;
        font-weight: 650;
        line-height: 1.15;
        white-space: normal;
    }
    .status-card-detail {
        color: #64748b;
        font-size: 0.78rem;
        line-height: 1.25;
        margin-top: 0.35rem;
    }
    div[data-testid="stSidebar"] {
        background: #f8fafc;
    }
    .app-hero {
        border-bottom: 1px solid #e5e7eb;
        display: flex;
        gap: 1rem;
        justify-content: space-between;
        align-items: flex-start;
        padding-bottom: 1rem;
        margin-bottom: 1rem;
    }
    .app-hero h1 {
        margin-bottom: 0.25rem;
    }
    .app-hero p {
        color: #475569;
        font-size: 1.02rem;
        margin: 0;
    }
    .app-version-badge {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        color: #475569;
        flex: 0 0 auto;
        font-size: 0.9rem;
        font-weight: 700;
        line-height: 1;
        margin-top: 0.15rem;
        padding: 0.55rem 0.7rem;
        white-space: nowrap;
    }
    @media (max-width: 700px) {
        .app-hero {
            display: block;
        }
        .app-version-badge {
            display: inline-block;
            margin-top: 0.75rem;
        }
    }
    .static-table-wrap {
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        overflow: hidden;
        margin: 0.5rem 0 1rem;
    }
    .static-table-wrap table {
        border-collapse: collapse;
        width: 100%;
        font-size: 0.92rem;
    }
    .static-table-wrap th {
        background: #f8fafc;
        color: #475569;
        font-weight: 700;
        text-align: left;
        padding: 10px 12px;
        border-bottom: 1px solid #e5e7eb;
    }
    .static-table-wrap td {
        padding: 9px 12px;
        border-bottom: 1px solid #eef2f7;
        color: #1f2937;
        vertical-align: top;
        user-select: none;
    }
    .static-table-wrap tr:last-child td {
        border-bottom: 0;
    }
    .live-preview-status {
        align-items: center;
        background: #f8fafc;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        color: #334155;
        display: flex;
        font-size: 0.95rem;
        gap: 0.6rem;
        margin: 0.35rem 0 0.6rem;
        padding: 0.7rem 0.85rem;
    }
    .live-preview-spinner {
        animation: live-preview-spin 0.85s linear infinite;
        border: 3px solid #cbd5e1;
        border-top-color: #ef4444;
        border-radius: 999px;
        display: inline-block;
        height: 18px;
        width: 18px;
    }
    .live-preview-plan-shell {
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        margin-top: 0.75rem;
        overflow: auto;
        position: relative;
        width: 100%;
    }
    .live-preview-plan-table {
        border-collapse: collapse;
        font-size: 0.88rem;
        min-width: max-content;
        width: 100%;
    }
    .live-preview-plan-table th {
        background: #f8fafc;
        border: 1px solid #e5e7eb;
        color: #64748b;
        font-weight: 600;
        padding: 9px 10px;
        position: sticky;
        top: 0;
        white-space: nowrap;
        z-index: 1;
    }
    .live-preview-plan-table .index-col {
        color: #64748b;
        min-width: 36px;
        text-align: right;
    }
    .live-preview-working .live-preview-plan-table {
        filter: grayscale(0.25);
        opacity: 0.42;
    }
    .live-preview-overlay {
        align-items: center;
        background: rgba(248, 250, 252, 0.5);
        bottom: 0;
        display: flex;
        justify-content: center;
        left: 0;
        pointer-events: none;
        position: absolute;
        right: 0;
        top: 0;
        z-index: 4;
    }
    .live-preview-overlay-card {
        align-items: center;
        background: rgba(255, 255, 255, 0.94);
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        box-shadow: 0 12px 35px rgba(15, 23, 42, 0.18);
        color: #1f2937;
        display: flex;
        font-weight: 700;
        gap: 0.85rem;
        padding: 1rem 1.25rem;
    }
    .live-preview-overlay-spinner {
        animation: live-preview-spin 0.85s linear infinite;
        border: 4px solid #cbd5e1;
        border-top-color: #ef4444;
        border-radius: 999px;
        display: inline-block;
        height: 34px;
        width: 34px;
    }
    @keyframes live-preview-spin {
        to {
            transform: rotate(360deg);
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if "employees_df" not in st.session_state:
    st.session_state.employees_df = editor_dataframe(SAMPLE_EMPLOYEES)
    st.session_state.sample_employee_set_version = SAMPLE_EMPLOYEE_SET_VERSION
elif "sample_employee_set_version" not in st.session_state:
    st.session_state.sample_employee_set_version = "eigene-daten"
elif (
    str(st.session_state.sample_employee_set_version).startswith("turnus-balanced")
    and st.session_state.sample_employee_set_version != SAMPLE_EMPLOYEE_SET_VERSION
):
    st.session_state.employees_df = editor_dataframe(SAMPLE_EMPLOYEES)
    st.session_state.sample_employee_set_version = SAMPLE_EMPLOYEE_SET_VERSION
st.session_state.employees_df = normalize_employee_dataframe(st.session_state.employees_df)
sabine_mask = st.session_state.employees_df["Name"].eq("Sabine Gruber")
if sabine_mask.any():
    sabine_index = st.session_state.employees_df.index[sabine_mask][0]
    if "Krankenstand" in str(st.session_state.employees_df.loc[sabine_index, "Qualifikation"]):
        st.session_state.employees_df.loc[sabine_index, "Qualifikation"] = "Krankenstand geplant"
        if not str(st.session_state.employees_df.loc[sabine_index, "Krankenstand-Tage"]).strip():
            st.session_state.employees_df.loc[sabine_index, "Krankenstand-Tage"] = ", ".join(str(day) for day in range(1, 32))
            st.session_state.employees_df.loc[sabine_index, "Wunschfrei-Tage"] = ""
if "shifts_df" not in st.session_state:
    st.session_state.shifts_df = default_shift_dataframe()
if "resources_df" not in st.session_state:
    st.session_state.resources_df = default_resource_dataframe()
if "day_requirement_overrides" not in st.session_state:
    st.session_state.day_requirement_overrides = {}
if "saved_schedules" not in st.session_state:
    st.session_state.saved_schedules = load_saved_schedules()
if "generated_plan" not in st.session_state:
    st.session_state.generated_plan = None
if "last_improvement_message" not in st.session_state:
    st.session_state.last_improvement_message = ""
if "employee_dialog_open" not in st.session_state:
    st.session_state.employee_dialog_open = False
if "employee_dialog_row_index" not in st.session_state:
    st.session_state.employee_dialog_row_index = None
if "best_plan_cache" not in st.session_state:
    st.session_state.best_plan_cache = load_best_plan_cache()
if "generation_run_number" not in st.session_state:
    st.session_state.generation_run_number = 0
if "compensatory_rest_counts_as_hours" not in st.session_state:
    st.session_state.compensatory_rest_counts_as_hours = True
st.session_state.vacation_counts_as_hours = True
if "vacation_weekend_policy" not in st.session_state:
    st.session_state.vacation_weekend_policy = DEFAULT_VACATION_WEEKEND_POLICY
st.session_state.vacation_weekend_policy = normalize_vacation_weekend_policy(
    st.session_state.vacation_weekend_policy
)
if "global_annual_vacation_weeks" not in st.session_state:
    st.session_state.global_annual_vacation_weeks = DEFAULT_ANNUAL_VACATION_WEEKS
if "global_annual_vacation_workdays" not in st.session_state:
    st.session_state.global_annual_vacation_workdays = DEFAULT_ANNUAL_VACATION_WORKDAYS
if "global_vacation_day_hours" not in st.session_state:
    st.session_state.global_vacation_day_hours = DEFAULT_VACATION_DAY_HOURS
if "legal_profile" not in st.session_state:
    st.session_state.legal_profile = DEFAULT_LEGAL_PROFILE
st.session_state.legal_profile = normalize_legal_profile(st.session_state.legal_profile)
legal_defaults = legal_profile_defaults(st.session_state.legal_profile)
if "daily_max_work_hours" not in st.session_state:
    st.session_state.daily_max_work_hours = legal_defaults["daily_max_hours"]
if "weekly_average_max_hours" not in st.session_state:
    st.session_state.weekly_average_max_hours = legal_defaults["weekly_average_max_hours"]
if "weekly_average_period_weeks" not in st.session_state:
    st.session_state.weekly_average_period_weeks = legal_defaults["weekly_average_period_weeks"]
if "weekly_rest_hours" not in st.session_state:
    st.session_state.weekly_rest_hours = legal_defaults["weekly_rest_hours"]
if "reduced_weekly_rest_hours" not in st.session_state:
    st.session_state.reduced_weekly_rest_hours = legal_defaults["reduced_weekly_rest_hours"]
if "allow_reduced_weekly_rest" not in st.session_state:
    st.session_state.allow_reduced_weekly_rest = legal_defaults["allow_reduced_weekly_rest"]
if "pause_policy" not in st.session_state:
    st.session_state.pause_policy = DEFAULT_PAUSE_POLICY
st.session_state.pause_policy = normalize_pause_policy(st.session_state.pause_policy)
if "pause_threshold_hours" not in st.session_state:
    st.session_state.pause_threshold_hours = legal_defaults["pause_after_hours"]
if "pause_duration_minutes" not in st.session_state:
    st.session_state.pause_duration_minutes = legal_defaults["pause_minutes"]
st.session_state.pause_threshold_hours = max(
    0.0,
    parse_hour_value(st.session_state.pause_threshold_hours, DEFAULT_PAUSE_THRESHOLD_HOURS),
)
try:
    st.session_state.pause_duration_minutes = max(0, int(round(float(st.session_state.pause_duration_minutes))))
except (TypeError, ValueError):
    st.session_state.pause_duration_minutes = DEFAULT_PAUSE_DURATION_MINUTES
if "max_overtime_percent" not in st.session_state:
    st.session_state.max_overtime_percent = 10
if "max_overtime_hours" not in st.session_state:
    st.session_state.max_overtime_hours = 12
if "max_undertime_percent" not in st.session_state:
    st.session_state.max_undertime_percent = 10
if "max_undertime_hours" not in st.session_state:
    st.session_state.max_undertime_hours = 12
if "decimal_separator" not in st.session_state:
    st.session_state.decimal_separator = ","
if "time_separator" not in st.session_state:
    st.session_state.time_separator = ":"
if "replacement_rest_enabled" not in st.session_state:
    st.session_state.replacement_rest_enabled = True
if "replacement_rest_kind" not in st.session_state:
    st.session_state.replacement_rest_kind = DEFAULT_REPLACEMENT_REST_KIND
st.session_state.replacement_rest_kind = normalize_replacement_rest_kind(
    st.session_state.replacement_rest_kind
)
if "replacement_rest_scope" not in st.session_state:
    st.session_state.replacement_rest_scope = normalize_replacement_rest_scope(
        None,
        enabled=bool(st.session_state.replacement_rest_enabled),
    )
else:
    st.session_state.replacement_rest_scope = normalize_replacement_rest_scope(
        st.session_state.replacement_rest_scope,
        enabled=bool(st.session_state.replacement_rest_enabled),
    )
st.session_state.replacement_rest_enabled = st.session_state.replacement_rest_scope != "Keine Ersatzruhe"
if "night_credit_mode" not in st.session_state:
    st.session_state.night_credit_mode = DEFAULT_NIGHT_CREDIT_MODE
st.session_state.night_credit_mode = normalize_night_credit_mode(st.session_state.night_credit_mode)
if "night_credit_hours" not in st.session_state:
    st.session_state.night_credit_hours = DEFAULT_NIGHT_CREDIT_HOURS
st.session_state.night_credit_hours = max(
    0.0,
    parse_hour_value(st.session_state.night_credit_hours, DEFAULT_NIGHT_CREDIT_HOURS),
)
if "time_account_usage" not in st.session_state:
    st.session_state.time_account_usage = DEFAULT_TIME_ACCOUNT_USAGE
st.session_state.time_account_usage = normalize_time_account_usage(st.session_state.time_account_usage)
if "global_max_consecutive_workdays" not in st.session_state:
    st.session_state.global_max_consecutive_workdays = 6
if "global_max_nights_per_month" not in st.session_state:
    st.session_state.global_max_nights_per_month = 4
if "global_rest_after_night" not in st.session_state:
    st.session_state.global_rest_after_night = 1
if "global_allow_three_nights" not in st.session_state:
    st.session_state.global_allow_three_nights = False
if "global_weekends_off" not in st.session_state:
    st.session_state.global_weekends_off = False
if "global_joint_weekends" not in st.session_state:
    st.session_state.global_joint_weekends = True
if "global_joint_weekends_priority" not in st.session_state:
    st.session_state.global_joint_weekends_priority = DEFAULT_PRIORITY_LABEL
if "global_max_nights_priority" not in st.session_state:
    st.session_state.global_max_nights_priority = DEFAULT_PRIORITY_LABEL
if "global_consecutive_days_priority" not in st.session_state:
    st.session_state.global_consecutive_days_priority = "1 - muss immer zutreffen"
if "global_rest_after_night_priority" not in st.session_state:
    st.session_state.global_rest_after_night_priority = DEFAULT_PRIORITY_LABEL
if "block_night_before_wish_free" not in st.session_state:
    st.session_state.block_night_before_wish_free = True
if "plan_includes_nights" not in st.session_state:
    st.session_state.plan_includes_nights = True
if "plan_includes_weekends" not in st.session_state:
    st.session_state.plan_includes_weekends = True
if "plan_is_turnus" not in st.session_state:
    st.session_state.plan_is_turnus = True
if "plan_optimization_mode" not in st.session_state:
    st.session_state.plan_optimization_mode = DEFAULT_PLAN_OPTIMIZATION_MODE
st.session_state.plan_optimization_mode = normalize_plan_optimization_mode(
    st.session_state.plan_optimization_mode
)
st.session_state.plan_calculation_mode = DEFAULT_CALCULATION_MODE

st.markdown(
    """
    <div class="app-hero">
        <div>
            <h1>KI-Dienstplan</h1>
            <p>Dienstplanung mit editierbaren Mitarbeiterdaten und OR-Tools-Optimierung.</p>
        </div>
        <div class="app-version-badge">Version {APP_VERSION}</div>
    </div>
    """.format(APP_VERSION=html.escape(str(APP_VERSION))),
    unsafe_allow_html=True,
)

current_year = date.today().year
if "selected_year" not in st.session_state:
    st.session_state.selected_year = current_year
if "selected_month" not in st.session_state:
    st.session_state.selected_month = date.today().month
if "manual_month_view" not in st.session_state:
    st.session_state.manual_month_view = False
if "planning_start_year" not in st.session_state:
    st.session_state.planning_start_year = int(st.session_state.selected_year)
if "planning_start_month" not in st.session_state:
    st.session_state.planning_start_month = int(st.session_state.selected_month)

next_plan_year, next_plan_month = next_open_plan_month(
    st.session_state.saved_schedules,
    int(st.session_state.planning_start_year),
    int(st.session_state.planning_start_month),
)
start_position = month_sequence_number(
    int(st.session_state.planning_start_year),
    int(st.session_state.planning_start_month),
)
selected_position = month_sequence_number(
    int(st.session_state.selected_year),
    int(st.session_state.selected_month),
)
next_plan_position = month_sequence_number(next_plan_year, next_plan_month)
if (
    not bool(st.session_state.manual_month_view)
    or selected_position < start_position
    or selected_position > next_plan_position
):
    st.session_state.selected_year = next_plan_year
    st.session_state.selected_month = next_plan_month
    st.session_state.manual_month_view = False

selected_year = int(st.session_state.selected_year)
selected_month = int(st.session_state.selected_month)

st.session_state.employees_df = migrate_legacy_absence_columns_to_month(
    st.session_state.employees_df,
    selected_year,
    selected_month,
)
st.session_state.employees_df = sync_absence_display_columns_for_month(
    st.session_state.employees_df,
    selected_year,
    selected_month,
)

days = build_month_dates(int(selected_year), selected_month)
st.session_state.current_month_days = days
holidays = austrian_holidays(int(selected_year))
st.session_state.shifts_df = shift_definitions_from_editor(st.session_state.shifts_df)
shifts = shift_codes(st.session_state.shifts_df)
night_shifts = night_shift_codes(st.session_state.shifts_df)
shift_priority_by_code = shift_priorities(st.session_state.shifts_df)
raw_shift_minutes_by_code = shift_minutes(st.session_state.shifts_df)
shift_minutes_by_code = effective_shift_minutes_by_pause_policy(
    raw_shift_minutes_by_code,
    st.session_state.pause_policy,
    st.session_state.pause_threshold_hours,
    st.session_state.pause_duration_minutes,
)
shift_hours_by_code = {
    code: format_minutes_as_hours(minutes)
    for code, minutes in shift_minutes_by_code.items()
}
shift_time_by_code = shift_time_windows(st.session_state.shifts_df)
st.session_state.resources_df = normalize_resource_dataframe(st.session_state.resources_df, shifts)
resource_requirements = resource_requirements_from_editor(st.session_state.resources_df, shifts)
daily_requirements = requirements_for_days(days, holidays, resource_requirements, shifts)
month_key = f"{int(selected_year)}-{selected_month:02d}-{'_'.join(shifts)}"
fixed_plan_key = plan_month_key(int(selected_year), selected_month)
daily_requirements = apply_day_overrides(daily_requirements, month_key, shifts)
employees = employees_from_editor(st.session_state.employees_df)
planning_employees = active_schedule_employees(employees)

planning_tab, employees_tab, resources_tab, settings_tab, help_tab = st.tabs(
    [
        "Dienstplan & Auswertung",
        "Mitarbeiter & Wünsche",
        "Dienstformen & Ressourcen",
        "Einstellungen",
        "Hilfe & Prüflogik",
    ]
)

if st.session_state.get("employee_dialog_open", False):
    dialog_row_index = st.session_state.get("employee_dialog_row_index")
    if dialog_row_index is not None:
        dialog_row_index = int(dialog_row_index)
        if dialog_row_index < 0 or dialog_row_index >= len(st.session_state.employees_df):
            close_employee_dialog_state()
            dialog_row_index = None
    if st.session_state.get("employee_dialog_open", False):
        employee_dialog(dialog_row_index)

with employees_tab:
    employees = employees_from_editor(st.session_state.employees_df)
    active_employees = active_schedule_employees(employees)
    employee_warnings = employee_warning_dataframe(employees)

    top_left, top_right = st.columns([0.68, 0.32])
    with top_left:
        st.subheader("Mitarbeiter & Wünsche")
        st.caption(
            "Kompakte Arbeitsansicht für Personal, Wünsche, Krankenstand und persönliche Dienstplanregeln."
        )
    with top_right:
        st.write("")
        if st.button("Mitarbeiter hinzufügen", width="stretch"):
            request_employee_dialog()
        if st.button("Testpersonal neu laden", width="stretch"):
            st.session_state.employees_df = editor_dataframe(SAMPLE_EMPLOYEES)
            st.session_state.sample_employee_set_version = SAMPLE_EMPLOYEE_SET_VERSION
            st.session_state.generated_plan = None
            st.success("Testpersonal wurde neu geladen.")
            st.rerun()

    month_factor = len(days) / 7 if days else 0
    personnel_target_hours = sum(employee.weekly_hours_target * month_factor for employee in active_employees)
    night_capable_count = sum(
        1
        for employee in active_employees
        if employee.max_nights_per_month > 0
        and (employee.likes_nights or employee.night_priority >= 3 or "nur nachtdienst" in employee.qualification.lower())
    )
    summary_cols = st.columns(7)
    summary_cols[0].metric("Aktive Personen", len(active_employees))
    summary_cols[1].metric("Personal-Soll h", format_display_hours(personnel_target_hours))
    summary_cols[2].metric("Nacht geeignet", night_capable_count)
    summary_cols[3].metric("Wochenendflexibel", sum(1 for employee in active_employees if not employee.prefers_weekends_off))
    summary_cols[4].metric(
        "Abwesenheitstage",
        sum(
            len(employee.blocked_days) + len(employee.planned_sick_days) + len(employee.vacation_days)
            for employee in active_employees
        ),
    )
    summary_cols[5].metric("Übernahme bestätigt", sum(1 for employee in employees if employee.takeover_confirmed))
    summary_cols[6].metric("Hinweise", len(employee_warnings))

    if not employee_warnings.empty:
        with st.expander("Hinweise zu Mitarbeiterdaten", expanded=False):
            st.caption("Diese Hinweise blockieren nicht automatisch, helfen aber beim Finden typischer Eingabefehler.")
            st.dataframe(germanize_dataframe(employee_warnings), width="stretch", hide_index=True)

    filter_left, filter_right = st.columns([0.34, 0.66])
    with filter_left:
        employee_search = st.text_input("Suche", placeholder="Name oder Qualifikation")
    with filter_right:
        filter_cols = st.columns(5)
        only_active = filter_cols[0].checkbox("nur aktiv", value=True)
        only_warnings = filter_cols[1].checkbox("nur Hinweise")
        only_night = filter_cols[2].checkbox("nur Nacht")
        only_weekend_free = filter_cols[3].checkbox("Wochenende frei")
        only_absences = filter_cols[4].checkbox("Wünsche/KS")

    visible_employee_indices = []
    search_text = employee_search.strip().lower()
    for employee_index, employee in enumerate(employees):
        if only_active and not employee.participates_in_schedule:
            continue
        if search_text and search_text not in f"{employee.name} {employee.qualification}".lower():
            continue
        if only_warnings and not employee_hint_list(employee):
            continue
        if only_night and not (
            employee.max_nights_per_month > 0
            and (employee.likes_nights or employee.night_priority >= 3 or "nur nachtdienst" in employee.qualification.lower())
        ):
            continue
        if only_weekend_free and not employee.prefers_weekends_off:
            continue
        if only_absences and not (employee.blocked_days or employee.planned_sick_days or employee.vacation_days):
            continue
        visible_employee_indices.append(employee_index)

    compact_df = employee_compact_dataframe(employees, visible_employee_indices)
    if compact_df.empty:
        st.info("Keine MitarbeiterInnen passen zu diesen Filtern.")
    else:
        render_static_table(compact_df, height_limit=430)
    st.caption("Prioritäten kurz: 1 Muss, 2 sehr wichtig, 3 wenn möglich, 4 locker, 5 fair verteilen.")

    employee_options_by_label = {
        f"{index + 1}. {employees[index].name}": index
        for index in visible_employee_indices
    }
    if not employee_options_by_label:
        employee_options_by_label = {
            f"{index + 1}. {employee.name}": index
            for index, employee in enumerate(employees)
        }
    edit_left, edit_middle, edit_right = st.columns([0.55, 0.225, 0.225])
    with edit_left:
        selected_employee_label = st.selectbox(
            "MitarbeiterIn auswählen",
            options=list(employee_options_by_label.keys()),
            disabled=not bool(employee_options_by_label),
        )
    with edit_middle:
        st.write("")
        if st.button("Bearbeiten", width="stretch", disabled=not bool(employee_options_by_label)):
            request_employee_dialog(employee_options_by_label[selected_employee_label])
    with edit_right:
        st.write("")
        if st.button("Löschen", width="stretch", disabled=not bool(employee_options_by_label)):
            delete_employee_dialog(employee_options_by_label[selected_employee_label])

    with st.expander("Massenbearbeitung", expanded=False):
        st.caption("Für typische Änderungen im Turnusdienst: mehrere Personen auswählen und eine Eigenschaft gemeinsam setzen.")
        all_employee_labels = {
            f"{index + 1}. {employee.name}": index
            for index, employee in enumerate(employees)
        }
        mass_left, mass_right = st.columns([0.55, 0.45])
        with mass_left:
            selected_mass_labels = st.multiselect(
                "Personen auswählen",
                options=list(all_employee_labels.keys()),
            )
        with mass_right:
            mass_action = st.selectbox(
                "Änderung",
                options=[
                    "Wochenende frei: Nein",
                    "Wochenende frei: Ja",
                    "Dienstplanrelevant: Ja",
                    "Dienstplanrelevant: Nein",
                    "Nacht geeignet: Ja",
                    "Nacht geeignet: Nein",
                    "Wochenstunden setzen",
                    "Globale Vorlage anwenden",
                ],
            )
            mass_hours_text = ""
            if mass_action == "Wochenstunden setzen":
                mass_hours_text = st.text_input("Neue Wochenstunden", value="30")
        if st.button("Massenänderung anwenden", type="primary", disabled=not selected_mass_labels):
            selected_indices = [all_employee_labels[label] for label in selected_mass_labels]
            if mass_action == "Wochenstunden setzen":
                new_hours = max(0.25, parse_hour_value(mass_hours_text, 30))
            for selected_index in selected_indices:
                if mass_action == "Wochenende frei: Nein":
                    st.session_state.employees_df.loc[selected_index, "Wochenende frei"] = False
                    st.session_state.employees_df.loc[selected_index, "Prio Wochenende"] = "5 - fair verteilen"
                elif mass_action == "Wochenende frei: Ja":
                    st.session_state.employees_df.loc[selected_index, "Wochenende frei"] = True
                    st.session_state.employees_df.loc[selected_index, "Prio Wochenende"] = DEFAULT_PRIORITY_LABEL
                elif mass_action == "Dienstplanrelevant: Ja":
                    st.session_state.employees_df.loc[selected_index, "Dienstplanrelevant"] = True
                elif mass_action == "Dienstplanrelevant: Nein":
                    st.session_state.employees_df.loc[selected_index, "Dienstplanrelevant"] = False
                elif mass_action == "Nacht geeignet: Ja":
                    st.session_state.employees_df.loc[selected_index, "Gerne Nacht"] = True
                    current_max_nights = int(st.session_state.employees_df.loc[selected_index, "Max. Naechte/Monat"] or 0)
                    st.session_state.employees_df.loc[selected_index, "Max. Naechte/Monat"] = max(
                        current_max_nights,
                        int(st.session_state.get("global_max_nights_per_month", 4)),
                    )
                elif mass_action == "Nacht geeignet: Nein":
                    st.session_state.employees_df.loc[selected_index, "Gerne Nacht"] = False
                    st.session_state.employees_df.loc[selected_index, "Max. Naechte/Monat"] = 0
                elif mass_action == "Wochenstunden setzen":
                    st.session_state.employees_df.loc[selected_index, "Wochenstunden"] = new_hours
                elif mass_action == "Globale Vorlage anwenden":
                    st.session_state.employees_df.loc[selected_index, "Max. Tage in Folge"] = int(st.session_state.global_max_consecutive_workdays)
                    st.session_state.employees_df.loc[selected_index, "Max. Naechte/Monat"] = int(st.session_state.global_max_nights_per_month)
                    st.session_state.employees_df.loc[selected_index, "Frei nach Nacht"] = int(st.session_state.global_rest_after_night)
                    st.session_state.employees_df.loc[selected_index, "Prio frei nach Nacht"] = st.session_state.global_rest_after_night_priority
                    st.session_state.employees_df.loc[selected_index, "3 Naechte erlaubt"] = bool(st.session_state.global_allow_three_nights)
                    st.session_state.employees_df.loc[selected_index, "Wochenende frei"] = bool(st.session_state.global_weekends_off)
                    st.session_state.employees_df.loc[selected_index, "Gemeinsame Wochenenden"] = bool(st.session_state.global_joint_weekends)
                    st.session_state.employees_df.loc[selected_index, "Prio gemeinsame Wochenenden"] = st.session_state.global_joint_weekends_priority
                    st.session_state.employees_df.loc[selected_index, "Urlaubswochen/Jahr"] = float(st.session_state.global_annual_vacation_weeks)
            st.session_state.sample_employee_set_version = "eigene-daten"
            st.session_state.generated_plan = None
            st.success("Massenänderung wurde angewendet.")
            st.rerun()

    with st.expander("Alle Details anzeigen", expanded=False):
        render_static_table(display_employee_dataframe(st.session_state.employees_df), height_limit=520)

with resources_tab:
    st.subheader("Dienstformen und Ressourcen")
    st.caption(
        "Lege zuerst deine Dienstformen fest. Danach stellst du den Standardbedarf pro Tagesart ein und kannst einzelne Tage manuell überschreiben."
    )

    shift_top_left, shift_top_right = st.columns([0.7, 0.3])
    with shift_top_left:
        st.markdown("**Dienstformen**")
    with shift_top_right:
        if st.button("Dienstform hinzufügen", width="stretch"):
            shift_dialog()

    render_static_table(display_shift_dataframe(st.session_state.shifts_df))
    st.caption(
        "Dienstform-Priorität: 1 muss immer besetzt werden, "
        "2 sollte besetzt sein, 3 nur wenn genug Mitarbeiter vorhanden sind."
    )

    shift_edit_left, shift_edit_right = st.columns([0.7, 0.3])
    with shift_edit_left:
        shift_options = [
            f"{row['Kuerzel']} - {row['Name']}" for _, row in st.session_state.shifts_df.iterrows()
        ]
        selected_shift = st.selectbox("Dienstform auswählen", options=shift_options)
    with shift_edit_right:
        st.write("")
        if st.button("Dienstform bearbeiten", width="stretch", disabled=not shift_options):
            selected_index = shift_options.index(selected_shift)
            shift_dialog(selected_index)

    st.session_state.shifts_df = shift_definitions_from_editor(st.session_state.shifts_df)
    shifts = shift_codes(st.session_state.shifts_df)
    night_shifts = night_shift_codes(st.session_state.shifts_df)

    st.markdown("**Standardbedarf je Tagesart**")
    st.session_state.resources_df = normalize_resource_dataframe(st.session_state.resources_df, shifts)
    render_static_table(st.session_state.resources_df)

    resource_edit_left, resource_edit_right = st.columns([0.7, 0.3])
    with resource_edit_left:
        selected_day_type = st.selectbox("Tagesart auswählen", options=DAY_TYPE_ORDER)
    with resource_edit_right:
        st.write("")
        if st.button("Standardbedarf bearbeiten", width="stretch"):
            resource_dialog(selected_day_type, shifts)

    resource_requirements = resource_requirements_from_editor(st.session_state.resources_df, shifts)
    daily_requirements = requirements_for_days(days, holidays, resource_requirements, shifts)
    daily_requirements = apply_day_overrides(daily_requirements, month_key, shifts)

    resource_staffing_summary, resource_staffing_df = staffing_hours_overview(
        employees=planning_employees,
        daily_requirements=daily_requirements,
        shifts=shifts,
        shift_priority_by_code=shift_priority_by_code,
        shift_minutes_by_code=shift_minutes_by_code,
        open_shift_codes=[],
        day_count=len(days),
        max_overtime_percent=float(st.session_state.max_overtime_percent),
        max_overtime_hours=float(st.session_state.max_overtime_hours),
        max_undertime_percent=float(st.session_state.max_undertime_percent),
        max_undertime_hours=float(st.session_state.max_undertime_hours),
        days=days,
        holidays=holidays,
        replacement_rest_scope=st.session_state.replacement_rest_scope,
        compensatory_rest_counts_as_hours=(
            bool(st.session_state.replacement_rest_enabled)
            and bool(st.session_state.compensatory_rest_counts_as_hours)
        ),
        vacation_counts_as_hours=True,
    )
    with st.expander("Stunden nach Dienstform-Priorität", expanded=False):
        st.caption(
            "Diese Übersicht gehört zu den Dienstformen: Prio 1 muss besetzt werden, "
            "Prio 2 und 3 dürfen bei Engpässen offen bleiben."
        )
        render_static_table(resource_staffing_df)

    st.subheader("Kalenderprüfung")
    st.caption("Hier kannst du einzelne Tage manuell anpassen, wenn an einem Datum mehr oder weniger Dienste gebraucht werden.")
    day_requirements_df = day_requirements_dataframe(days, holidays, daily_requirements, shifts)
    render_static_table(day_requirements_df, height_limit=520)

    day_edit_left, day_edit_right = st.columns([0.7, 0.3])
    with day_edit_left:
        day_options = day_requirements_df["Tag"].tolist()
        selected_day_label = st.selectbox("Tag auswählen", options=day_options)
    with day_edit_right:
        st.write("")
        if st.button("Tagesbedarf bearbeiten", width="stretch"):
            selected_day_index = day_options.index(selected_day_label)
            current_values = {
                shift: daily_requirements[(selected_day_index, shift)] for shift in shifts
            }
            day_requirement_dialog(selected_day_index, month_key, shifts, current_values)

with settings_tab:
    st.subheader("Globale Mitarbeitereinstellungen")
    st.caption("Wochenstunden bleiben pro MitarbeiterIn. Diese Regeln sind Vorlagen und können einzeln überschrieben werden.")

    employee_setting_cols = st.columns(3)
    with employee_setting_cols[0]:
        st.session_state.global_max_consecutive_workdays = st.number_input(
            "Max. Tage in Folge",
            min_value=1,
            max_value=14,
            value=int(st.session_state.global_max_consecutive_workdays),
            step=1,
            help="Hilft, echte freie Tage im Turnus zu erzwingen.",
        )
        st.session_state.global_consecutive_days_priority = st.selectbox(
            "Priorität Tage in Folge",
            options=list(PRIORITY_LEVELS.keys()),
            index=list(PRIORITY_LEVELS.keys()).index(priority_label(st.session_state.global_consecutive_days_priority)),
        )
    with employee_setting_cols[1]:
        st.session_state.global_max_nights_per_month = st.number_input(
            "Max. Nächte/Monat",
            min_value=0,
            max_value=31,
            value=int(st.session_state.global_max_nights_per_month),
            step=1,
        )
        st.session_state.global_max_nights_priority = st.selectbox(
            "Priorität max. Nächte",
            options=list(PRIORITY_LEVELS.keys()),
            index=list(PRIORITY_LEVELS.keys()).index(priority_label(st.session_state.global_max_nights_priority)),
        )
    with employee_setting_cols[2]:
        st.session_state.global_rest_after_night = st.number_input(
            "Freie Tage nach Nachtdienst",
            min_value=1,
            max_value=2,
            value=int(st.session_state.global_rest_after_night),
            step=1,
            help="1 bedeutet: Ausschlaftag frei. 2 bedeutet: ein zusätzlicher freier Tag nach dem Ausschlaftag.",
        )
        st.session_state.global_rest_after_night_priority = st.selectbox(
            "Priorität frei nach Nacht",
            options=list(PRIORITY_LEVELS.keys()),
            index=list(PRIORITY_LEVELS.keys()).index(priority_label(st.session_state.global_rest_after_night_priority)),
        )
        st.session_state.global_allow_three_nights = st.checkbox(
            "3 Nächte in Folge erlauben",
            value=bool(st.session_state.global_allow_three_nights),
        )
        st.session_state.global_weekends_off = st.checkbox(
            "Wochenende bevorzugt frei",
            value=bool(st.session_state.global_weekends_off),
        )
        st.session_state.global_joint_weekends = st.checkbox(
            "Wochenende nicht teilen",
            value=bool(st.session_state.global_joint_weekends),
            help="Samstag und Sonntag sollen möglichst gemeinsam frei oder gemeinsam gearbeitet sein.",
        )
        st.session_state.global_joint_weekends_priority = st.selectbox(
            "Priorität Wochenende nicht teilen",
            options=list(PRIORITY_LEVELS.keys()),
            index=list(PRIORITY_LEVELS.keys()).index(priority_label(st.session_state.global_joint_weekends_priority)),
        )

    apply_cols = st.columns([0.25, 0.75])
    with apply_cols[0]:
        if st.button("Auf alle anwenden"):
            st.session_state.employees_df["Max. Tage in Folge"] = int(st.session_state.global_max_consecutive_workdays)
            st.session_state.employees_df["Max. Naechte/Monat"] = int(st.session_state.global_max_nights_per_month)
            st.session_state.employees_df["Frei nach Nacht"] = int(st.session_state.global_rest_after_night)
            st.session_state.employees_df["Prio frei nach Nacht"] = st.session_state.global_rest_after_night_priority
            st.session_state.employees_df["3 Naechte erlaubt"] = bool(st.session_state.global_allow_three_nights)
            st.session_state.employees_df["Wochenende frei"] = bool(st.session_state.global_weekends_off)
            st.session_state.employees_df["Gemeinsame Wochenenden"] = bool(st.session_state.global_joint_weekends)
            st.session_state.employees_df["Prio gemeinsame Wochenenden"] = st.session_state.global_joint_weekends_priority
            st.session_state.employees_df["Urlaubswochen/Jahr"] = float(st.session_state.global_annual_vacation_weeks)
            st.session_state.employees_df["Urlaubstage/Jahr"] = float(st.session_state.global_annual_vacation_workdays)
            st.session_state.employees_df["Urlaubstag h"] = float(st.session_state.global_vacation_day_hours)
            st.success("Globale Mitarbeitereinstellungen wurden übernommen.")

    st.divider()
    st.subheader("Globale Dienstplan- und Zeiteinstellungen")
    st.caption("Bei Plus- und Minusstunden gilt: 0 deaktiviert genau diese Grenze. Sind Prozent und Stunden gesetzt, gewinnt die niedrigere aktive Grenze.")

    planning_start_value = date(
        int(st.session_state.planning_start_year),
        int(st.session_state.planning_start_month),
        1,
    )
    selected_start_date = st.date_input(
        "Planungsstart",
        value=planning_start_value,
        min_value=date(current_year - 1, 1, 1),
        max_value=date(current_year + 3, 12, 31),
        help="Ab diesem Monat startet die laufende Planung. Danach wird Monat für Monat weitergeplant.",
    )
    selected_start_month_date = date(int(selected_start_date.year), int(selected_start_date.month), 1)
    if selected_start_month_date != planning_start_value:
        st.session_state.planning_start_year = selected_start_month_date.year
        st.session_state.planning_start_month = selected_start_month_date.month
        new_year, new_month = next_open_plan_month(
            st.session_state.saved_schedules,
            selected_start_month_date.year,
            selected_start_month_date.month,
        )
        st.session_state.selected_year = new_year
        st.session_state.selected_month = new_month
        st.session_state.manual_month_view = False
        st.session_state.generated_plan = None
        st.rerun()

    format_cols = st.columns(2)
    with format_cols[0]:
        st.session_state.decimal_separator = st.selectbox(
            "Dezimaltrennzeichen",
            options=[",", "."],
            index=[",", "."].index(str(st.session_state.decimal_separator)),
        )
    with format_cols[1]:
        st.session_state.time_separator = st.selectbox(
            "Uhrzeit-Trennzeichen",
            options=[":", "."],
            index=[":", "."].index(str(st.session_state.time_separator)),
        )
    plan_kind_cols = st.columns(3)
    with plan_kind_cols[0]:
        st.session_state.plan_is_turnus = st.checkbox(
            "Turnusdienstplan",
            value=bool(st.session_state.plan_is_turnus),
        )
    with plan_kind_cols[1]:
        st.session_state.plan_includes_nights = st.checkbox(
            "Mit Nachtdiensten",
            value=bool(st.session_state.plan_includes_nights),
            disabled=not bool(st.session_state.plan_is_turnus),
        )
    with plan_kind_cols[2]:
        st.session_state.plan_includes_weekends = st.checkbox(
            "Mit Wochenenden/Feiertagen",
            value=bool(st.session_state.plan_includes_weekends),
        )

    st.markdown("**Ruhepausen**")
    st.caption("Lege fest, ob die Pause bereits in der Dienstform enthalten ist oder von den berechneten Dienststunden abgezogen wird.")
    pause_cols = st.columns(3)
    with pause_cols[0]:
        st.session_state.pause_policy = st.selectbox(
            "Pausenmodell",
            options=PAUSE_POLICY_OPTIONS,
            index=PAUSE_POLICY_OPTIONS.index(normalize_pause_policy(st.session_state.pause_policy)),
            help=(
                "Standard: Die Dienstform enthält die bezahlte Pause bereits. "
                "Nur bei unbezahlter Pause werden die berechneten Dienststunden gekürzt."
            ),
        )
    pause_is_deducted = st.session_state.pause_policy == "Pause unbezahlt und von Dienstzeit abziehen"
    with pause_cols[1]:
        pause_threshold_text = st.text_input(
            "Pause verpflichtend ab h",
            value=format_hour_value(st.session_state.pause_threshold_hours),
            disabled=not pause_is_deducted,
            help="Ab dieser Dienstlänge wird die Pausenzeit von den Dienststunden abgezogen.",
        )
        if pause_is_deducted:
            st.session_state.pause_threshold_hours = max(
                0.0,
                parse_hour_value(pause_threshold_text, float(st.session_state.pause_threshold_hours)),
            )
    with pause_cols[2]:
        st.session_state.pause_duration_minutes = st.number_input(
            "Pausendauer Minuten",
            min_value=0,
            max_value=180,
            value=int(st.session_state.pause_duration_minutes),
            step=5,
            disabled=not pause_is_deducted,
            help="Diese Minuten werden bei Variante 2 von langen Diensten abgezogen.",
        )
    if pause_is_deducted:
        st.info(
            "Bei diesem Modell bleiben Beginn und Ende der Dienstform gleich, aber die berechneten Dienststunden werden um die Pause reduziert."
        )
    else:
        st.caption("Die Dienststunden bleiben unverändert, weil die Pause laut Einstellung bezahlt und bereits enthalten ist.")

    st.markdown("**Rechtsprofil und harte Schutzregeln**")
    legal_profile_cols = st.columns(3)
    with legal_profile_cols[0]:
        selected_legal_profile = st.selectbox(
            "Rechtsprofil",
            options=LEGAL_PROFILE_OPTIONS,
            index=LEGAL_PROFILE_OPTIONS.index(normalize_legal_profile(st.session_state.legal_profile)),
            help="Legt die Standardgrenzen für Tageshöchstarbeitszeit, Wochenruhe und 48h-Durchrechnung fest.",
        )
        if selected_legal_profile != st.session_state.legal_profile:
            st.session_state.legal_profile = selected_legal_profile
            profile_defaults = legal_profile_defaults(selected_legal_profile)
            st.session_state.daily_max_work_hours = profile_defaults["daily_max_hours"]
            st.session_state.weekly_average_max_hours = profile_defaults["weekly_average_max_hours"]
            st.session_state.weekly_average_period_weeks = profile_defaults["weekly_average_period_weeks"]
            st.session_state.weekly_rest_hours = profile_defaults["weekly_rest_hours"]
            st.session_state.reduced_weekly_rest_hours = profile_defaults["reduced_weekly_rest_hours"]
            st.session_state.allow_reduced_weekly_rest = profile_defaults["allow_reduced_weekly_rest"]
            st.rerun()
        st.session_state.daily_max_work_hours = st.number_input(
            "Tageshöchstgrenze h",
            min_value=1.0,
            max_value=25.0,
            value=float(st.session_state.daily_max_work_hours),
            step=0.5,
            help="Dienste über dieser Grenze werden nicht eingeplant und in der Regelprüfung als Fehler markiert.",
        )
    with legal_profile_cols[1]:
        st.session_state.weekly_rest_hours = st.number_input(
            "Wochenruhe Ziel h",
            min_value=24.0,
            max_value=72.0,
            value=float(st.session_state.weekly_rest_hours),
            step=1.0,
            help="Zielwert für die wöchentliche zusammenhängende Ruhezeit.",
        )
        st.session_state.allow_reduced_weekly_rest = st.checkbox(
            "Schicht-Verkürzung erlauben",
            value=bool(st.session_state.allow_reduced_weekly_rest),
            help="Für Schichtmodelle: eine verkürzte Wochenruhe wird als Hinweis akzeptiert, der 4-Wochen-Schnitt wird geprüft.",
        )
        st.session_state.reduced_weekly_rest_hours = st.number_input(
            "Mindest-Wochenruhe h",
            min_value=12.0,
            max_value=float(st.session_state.weekly_rest_hours),
            value=min(float(st.session_state.reduced_weekly_rest_hours), float(st.session_state.weekly_rest_hours)),
            step=1.0,
            disabled=not bool(st.session_state.allow_reduced_weekly_rest),
        )
    with legal_profile_cols[2]:
        st.session_state.weekly_average_max_hours = st.number_input(
            "Ø Wochenarbeitszeit h",
            min_value=1.0,
            max_value=60.0,
            value=float(st.session_state.weekly_average_max_hours),
            step=0.5,
            help="Grenze für die rollierende Durchrechnung.",
        )
        st.session_state.weekly_average_period_weeks = st.number_input(
            "Durchrechnung Wochen",
            min_value=1,
            max_value=52,
            value=int(st.session_state.weekly_average_period_weeks),
            step=1,
        )

    st.session_state.plan_optimization_mode = st.selectbox(
        "Optimierungsziel",
        options=PLAN_OPTIMIZATION_MODES,
        index=PLAN_OPTIMIZATION_MODES.index(
            normalize_plan_optimization_mode(st.session_state.plan_optimization_mode)
        ),
        help=(
            "Abdeckung zuerst hält möglichst viele erlaubte Dienste besetzt. "
            "Zufriedenheit zuerst schützt Wünsche stärker und kann erlaubte Dienste eher offen lassen."
        ),
    )
    overtime_cols = st.columns(2)
    with overtime_cols[0]:
        st.session_state.max_overtime_percent = st.number_input(
            "Max. Überstunden in Prozent",
            min_value=0,
            max_value=100,
            value=int(st.session_state.max_overtime_percent),
            step=1,
            help="0 bedeutet: diese Prozent-Grenze ist nicht aktiv.",
        )
    with overtime_cols[1]:
        max_overtime_hours_text = st.text_input(
            "Max. Überstunden pro Person",
            value=format_hour_value(st.session_state.max_overtime_hours),
            help="0 bedeutet: diese Stunden-Grenze ist nicht aktiv.",
        )
        st.session_state.max_overtime_hours = min(
            80.0,
            max(0.0, parse_hour_value(max_overtime_hours_text, float(st.session_state.max_overtime_hours))),
        )

    undertime_cols = st.columns(2)
    with undertime_cols[0]:
        st.session_state.max_undertime_percent = st.number_input(
            "Max. Minusstunden in Prozent",
            min_value=0,
            max_value=100,
            value=int(st.session_state.max_undertime_percent),
            step=1,
            help="0 bedeutet: diese Prozent-Grenze ist nicht aktiv.",
        )
    with undertime_cols[1]:
        max_undertime_hours_text = st.text_input(
            "Max. Minusstunden pro Person",
            value=format_hour_value(st.session_state.max_undertime_hours),
            help="0 bedeutet: diese Stunden-Grenze ist nicht aktiv.",
        )
        st.session_state.max_undertime_hours = min(
            80.0,
            max(0.0, parse_hour_value(max_undertime_hours_text, float(st.session_state.max_undertime_hours))),
        )

    st.markdown("**Ausgleich, Zeitausgleich und Nachtgutschrift**")
    rest_cols = st.columns(3)
    with rest_cols[0]:
        st.session_state.replacement_rest_kind = st.selectbox(
            "Feiertags-/Sonntagsausgleich eintragen als",
            options=REPLACEMENT_REST_KIND_OPTIONS,
            index=REPLACEMENT_REST_KIND_OPTIONS.index(normalize_replacement_rest_kind(st.session_state.replacement_rest_kind)),
            help=(
                "Gesetzliche Ersatzruhe betrifft Arbeit in der wöchentlichen Ruhezeit. "
                "Feiertagsarbeit ist meist Feiertagsentgelt; Zeitausgleich braucht eine Vereinbarung."
            ),
        )
    with rest_cols[1]:
        st.session_state.replacement_rest_scope = st.selectbox(
            "Ausgleichstage für",
            options=REPLACEMENT_REST_SCOPE_OPTIONS,
            index=REPLACEMENT_REST_SCOPE_OPTIONS.index(
                normalize_replacement_rest_scope(
                    st.session_state.replacement_rest_scope,
                    enabled=bool(st.session_state.replacement_rest_enabled),
                )
            ),
            help=(
                "Legt fest, an welchen Tagen ein gearbeiteter Dienst einen ER-Eintrag auslöst. "
                "Standard: nur Feiertage."
            ),
        )
        st.session_state.replacement_rest_enabled = (
            st.session_state.replacement_rest_scope != "Keine Ersatzruhe"
        )
    with rest_cols[2]:
        if st.session_state.replacement_rest_kind == "Gesetzliche Ersatzruhe":
            st.session_state.compensatory_rest_counts_as_hours = True
        st.session_state.compensatory_rest_counts_as_hours = st.checkbox(
            "Ersatzruhe zählt als Dienststunden",
            value=bool(st.session_state.compensatory_rest_counts_as_hours),
            disabled=(
                not bool(st.session_state.replacement_rest_enabled)
                or st.session_state.replacement_rest_kind == "Gesetzliche Ersatzruhe"
            ),
            help="Gesetzliche Ersatzruhe zählt zur Arbeitszeit. Vertraglicher Zeitausgleich kann je Vertrag/KV anders geregelt sein.",
        )
    if (
        st.session_state.replacement_rest_kind == "Gesetzliche Ersatzruhe"
        and st.session_state.replacement_rest_scope == "Nur Feiertage"
    ):
        st.warning(
            "Rechtlicher Hinweis: Reine Feiertagsarbeit löst in Österreich normalerweise Feiertagsentgelt aus. "
            "Ein freier Ausgleichstag ist als Zeitausgleich nur mit passender Vereinbarung/KV sauber."
        )
    st.caption(
        "Für Turnusdienste ist das bewusst einstellbar: Verträge und Kollektivverträge können Feiertage, Sonntage oder Wochenenden unterschiedlich behandeln."
    )
    night_credit_cols = st.columns(3)
    with night_credit_cols[0]:
        st.session_state.night_credit_mode = st.selectbox(
            "Nachtgutschrift",
            options=NIGHT_CREDIT_MODE_OPTIONS,
            index=NIGHT_CREDIT_MODE_OPTIONS.index(normalize_night_credit_mode(st.session_state.night_credit_mode)),
            help=(
                "Zeitkonto: Zusatzgutschrift wird separat im Zeitkonto geführt und nicht als normale Ist-Stunde gezählt. "
                "Dienststunden: Zusatzgutschrift zählt direkt in Ist h und +/- h. "
                "Welche Variante richtig ist, hängt von Vertrag, KV oder Betriebsvereinbarung ab."
            ),
        )
    with night_credit_cols[1]:
        night_credit_text = st.text_input(
            "Stunden pro Nachtdienst",
            value=format_hour_value(st.session_state.night_credit_hours),
            disabled=st.session_state.night_credit_mode == "Keine Nachtgutschrift",
        )
        st.session_state.night_credit_hours = max(
            0.0,
            parse_hour_value(night_credit_text, float(st.session_state.night_credit_hours)),
        )
    with night_credit_cols[2]:
        st.session_state.time_account_usage = st.selectbox(
            "Zeitkonto-Ausgleich",
            options=TIME_ACCOUNT_USAGE_OPTIONS,
            index=TIME_ACCOUNT_USAGE_OPTIONS.index(normalize_time_account_usage(st.session_state.time_account_usage)),
            help=(
                "Steuert, wie stark vorhandene Plus-/Minusstunden aus dem Start-Zeitkonto in der Planung abgebaut werden. "
                "Vorrangig: möglichst bald ausgleichen. Sobald passend: mit guter Planqualität ausgleichen. "
                "Nachrangig: nur ausgleichen, wenn genug Kapazität vorhanden ist."
            ),
        )
    st.caption(
        "Kurz erklärt: Zeitkonto führt die Nachtgutschrift separat weiter; Dienststunden rechnen sie direkt in die Stundenbilanz."
    )

    st.markdown("**Urlaub**")
    st.caption("Urlaub zählt immer als bezahlte Dienstzeit und wird in den Ist-Stunden berücksichtigt.")
    vacation_cols = st.columns(3)
    with vacation_cols[0]:
        st.session_state.global_annual_vacation_weeks = st.number_input(
            "Standard-Urlaubswochen/Jahr",
            min_value=0.0,
            max_value=10.0,
            value=float(st.session_state.global_annual_vacation_weeks),
            step=0.5,
            help="Orientierung in Wochen. Die Stundenberechnung nutzt Urlaubstage und Stundenwert.",
        )
    with vacation_cols[1]:
        st.session_state.global_annual_vacation_workdays = st.number_input(
            "Standard-Urlaubstage/Jahr",
            min_value=0.0,
            max_value=60.0,
            value=float(st.session_state.global_annual_vacation_workdays),
            step=1.0,
            help="Bei 5 Wochen und 5-Tage-Woche meist 25 Arbeitstage.",
        )
        global_vacation_day_hours_text = st.text_input(
            "Standard-Stunden je Urlaubstag",
            value=format_hour_value(st.session_state.global_vacation_day_hours),
            help="0 bedeutet automatisch: individuelle Wochenstunden / 5.",
        )
        st.session_state.global_vacation_day_hours = max(
            0.0,
            parse_hour_value(global_vacation_day_hours_text, float(st.session_state.global_vacation_day_hours)),
        )
    with vacation_cols[2]:
        st.session_state.vacation_weekend_policy = st.selectbox(
            "Wochenende bei Urlaub",
            options=VACATION_WEEKEND_POLICY_OPTIONS,
            index=VACATION_WEEKEND_POLICY_OPTIONS.index(
                normalize_vacation_weekend_policy(st.session_state.vacation_weekend_policy)
            ),
            help="Nach einer Urlaubswoche bleibt das Wochenende danach frei. Optional auch das Wochenende davor.",
        )
    vacation_apply_cols = st.columns([0.25, 0.75])
    with vacation_apply_cols[0]:
        if st.button("Urlaubsstandard anwenden"):
            st.session_state.employees_df["Urlaubswochen/Jahr"] = float(st.session_state.global_annual_vacation_weeks)
            st.session_state.employees_df["Urlaubstage/Jahr"] = float(st.session_state.global_annual_vacation_workdays)
            st.session_state.employees_df["Urlaubstag h"] = float(st.session_state.global_vacation_day_hours)
            st.session_state.generated_plan = None
            st.success("Urlaubsstandard wurde übernommen.")

    st.session_state.block_night_before_wish_free = st.checkbox(
        "Kein Nachtdienst vor Wunschfrei",
        value=bool(st.session_state.block_night_before_wish_free),
        help="Wenn Wunschfrei Priorität 1 hat, bleibt auch die Nacht davor frei. So wird der freie Tag nicht durch Ausschlafen verbraucht.",
    )

    st.divider()
    st.subheader("Österreich-Regeln für Turnusdienste")
    st.caption("Kurzfassung als Planungsleitplanke, keine Rechtsberatung. KV, Betriebsvereinbarung und Berufsgruppe können strengere Regeln enthalten.")
    with st.expander("Aktive Rechtsleitplanken", expanded=True):
        st.caption(
            "Diese Werte verwendet die App aktuell für Generierung und Regelprüfung. "
            "Sie sollen die KV-/Vertragsprüfung nicht ersetzen, sondern sichtbar machen."
        )
        st.dataframe(
            germanize_dataframe(
                legal_guardrail_dataframe(
                    legal_profile=st.session_state.legal_profile,
                    daily_max_work_hours=float(st.session_state.daily_max_work_hours),
                    weekly_average_max_hours=float(st.session_state.weekly_average_max_hours),
                    weekly_average_period_weeks=int(st.session_state.weekly_average_period_weeks),
                    weekly_rest_hours=float(st.session_state.weekly_rest_hours),
                    reduced_weekly_rest_hours=float(st.session_state.reduced_weekly_rest_hours),
                    allow_reduced_weekly_rest=bool(st.session_state.allow_reduced_weekly_rest),
                    replacement_rest_kind=st.session_state.replacement_rest_kind,
                    replacement_rest_scope=st.session_state.replacement_rest_scope,
                    vacation_weekend_policy=st.session_state.vacation_weekend_policy,
                    night_credit_mode=st.session_state.night_credit_mode,
                    night_credit_hours=float(st.session_state.night_credit_hours),
                    time_account_usage=st.session_state.time_account_usage,
                    pause_policy=st.session_state.pause_policy,
                    pause_threshold_hours=float(st.session_state.pause_threshold_hours),
                    pause_duration_minutes=int(st.session_state.pause_duration_minutes),
                )
            ),
            width="stretch",
            hide_index=True,
        )
    legal_cols = st.columns(4)
    legal_cols[0].checkbox("11 Stunden Ruhezeit", value=True, disabled=True)
    legal_cols[1].checkbox("48 Stunden Wochenarbeitszeit", value=True, disabled=True)
    legal_cols[2].checkbox("36 Stunden Wochenruhe", value=True, disabled=True)
    legal_cols[3].checkbox("Ersatzruhe konfigurierbar", value=True, disabled=True)
    render_static_table(
        pd.DataFrame(
            [
                {"Regel": "11 Stunden Ruhezeit", "Umsetzung": "Zwischen zwei Diensten müssen immer mindestens 11 Stunden liegen."},
                {"Regel": "48 Stunden Wochenarbeitszeit", "Umsetzung": "Rollierende Durchrechnung wird in der Regelprüfung über fixierte Monate geprüft."},
                {"Regel": "36 Stunden Wochenruhe", "Umsetzung": "Zusammenhängende Ruhezeit wird mit Dienst-Uhrzeiten geprüft; Schichtverkürzung ist separat sichtbar."},
                {"Regel": "Ersatzruhe/Zeitausgleich", "Umsetzung": "Gesetzliche Ersatzruhe gilt für Arbeit in der wöchentlichen Ruhezeit. Feiertags-Zeitausgleich ist je Vertrag/KV einstellbar."},
                {"Regel": "Urlaub", "Umsetzung": "Anspruch je Person mit Stichtag, Urlaubstagen und Stundenwert pro Urlaubstag."},
                {"Regel": "Ruhepause", "Umsetzung": "Pausen können als bezahlt enthalten oder als Abzug von den berechneten Dienststunden geführt werden."},
            ]
        )
    )

    st.divider()
    st.subheader("Gespeicherte Dienstpläne")
    st.caption("Gespeicherte Monate sind fixiert und werden für monatsübergreifende Regeln berücksichtigt.")
    saved_plan_rows = []
    for key, plan in sorted(st.session_state.saved_schedules.items()):
        schedule = plan.get("schedule", {}) if isinstance(plan, dict) else {}
        open_count = 0
        if isinstance(plan, dict) and plan.get("schedule"):
            plan_days = build_month_dates(int(str(key).split("-")[0]), int(str(key).split("-")[1]))
            open_count = int(
                open_services_dataframe(
                    schedule,
                    plan_days,
                    daily_requirements if key == fixed_plan_key else {},
                    st.session_state.shifts_df,
                    open_shift_codes=[],
                    shift_priority_by_code=shift_priority_by_code,
                ).get("Offen", pd.Series(dtype=int)).sum()
            )
        saved_plan_rows.append(
            {
                "Monat": key,
                "MitarbeiterInnen": len(schedule),
                "Status": plan.get("status", "-") if isinstance(plan, dict) else "-",
                "Offene Dienste": open_count,
            }
        )
    if saved_plan_rows:
        render_static_table(pd.DataFrame(saved_plan_rows), height_limit=220)
        selected_saved_key = st.selectbox("Gespeicherten Plan auswählen", options=[row["Monat"] for row in saved_plan_rows])
        plan_manage_cols = st.columns(4)
        with plan_manage_cols[0]:
            if st.button("Plan öffnen"):
                year_text, month_text = selected_saved_key.split("-")
                st.session_state.selected_year = int(year_text)
                st.session_state.selected_month = int(month_text)
                st.session_state.manual_month_view = True
                st.session_state.generated_plan = None
                st.rerun()
        with plan_manage_cols[1]:
            if st.button("Plan löschen"):
                st.session_state.saved_schedules.pop(selected_saved_key, None)
                save_saved_schedules(st.session_state.saved_schedules)
                if st.session_state.generated_plan and st.session_state.generated_plan.get("key") == selected_saved_key:
                    st.session_state.generated_plan = None
                st.success("Gespeicherter Plan wurde gelöscht.")
                st.rerun()
        with plan_manage_cols[2]:
            st.download_button(
                "Pläne exportieren",
                data=json.dumps({"plans": st.session_state.saved_schedules}, ensure_ascii=False, indent=2),
                file_name="dienstplaene.json",
                mime="application/json",
            )
        with plan_manage_cols[3]:
            if st.button("Alle löschen"):
                clear_saved_schedules_dialog()
    else:
        st.info("Noch keine gespeicherten Dienstpläne vorhanden.")

with planning_tab:
    employees = employees_from_editor(st.session_state.employees_df)
    planning_employees = active_schedule_employees(employees)
    daily_requirements = apply_global_plan_scope(
        daily_requirements,
        days,
        shifts,
        night_shifts,
        holidays,
        include_nights=bool(st.session_state.plan_is_turnus and st.session_state.plan_includes_nights),
        include_weekends=bool(st.session_state.plan_includes_weekends),
    )
    open_shift_codes: list[str] = []

    st.subheader("Dienstplan generieren")
    if not planning_employees:
        st.error("Es gibt aktuell keine dienstplanrelevanten MitarbeiterInnen.")
        st.stop()
    current_next_year, current_next_month = next_open_plan_month(
        st.session_state.saved_schedules,
        int(st.session_state.planning_start_year),
        int(st.session_state.planning_start_month),
    )
    saved_plan = st.session_state.saved_schedules.get(fixed_plan_key)
    can_generate_selected, month_sequence_hint = can_generate_month(
        st.session_state.saved_schedules,
        int(selected_year),
        selected_month,
        int(st.session_state.planning_start_year),
        int(st.session_state.planning_start_month),
    )
    selected_position = month_sequence_number(int(selected_year), selected_month)
    start_position = month_sequence_number(
        int(st.session_state.planning_start_year),
        int(st.session_state.planning_start_month),
    )
    month_nav_cols = st.columns([0.42, 0.22, 0.18, 0.18])
    with month_nav_cols[0]:
        st.markdown(f"### {MONTH_NAMES[selected_month]} {int(selected_year)}")
        st.caption("Geplant wird immer ein ganzer Monat.")
    with month_nav_cols[1]:
        if can_generate_selected:
            st.caption(f"Status: {month_sequence_hint}")
        else:
            st.error(month_sequence_hint)
    with month_nav_cols[2]:
        if selected_position > start_position and st.button("Vorigen Monat anzeigen", width="stretch"):
            previous_year, previous_month = shift_month(int(selected_year), selected_month, -1)
            st.session_state.selected_year = previous_year
            st.session_state.selected_month = previous_month
            st.session_state.manual_month_view = True
            st.session_state.generated_plan = None
            st.rerun()
    with month_nav_cols[3]:
        if (
            int(selected_year) != current_next_year
            or selected_month != current_next_month
        ) and st.button("Aktuellen Planungsmonat", width="stretch"):
            st.session_state.selected_year = current_next_year
            st.session_state.selected_month = current_next_month
            st.session_state.manual_month_view = False
            st.session_state.generated_plan = None
            st.rerun()

    total_required = sum(daily_requirements.values())
    holiday_count = sum(1 for current_day in days if current_day in holidays)
    weekend_count = sum(1 for current_day in days if current_day.weekday() >= 5)

    staffing_summary, staffing_df = staffing_hours_overview(
        employees=planning_employees,
        daily_requirements=daily_requirements,
        shifts=shifts,
        shift_priority_by_code=shift_priority_by_code,
        shift_minutes_by_code=shift_minutes_by_code,
        open_shift_codes=open_shift_codes,
        day_count=len(days),
        max_overtime_percent=float(st.session_state.max_overtime_percent),
        max_overtime_hours=float(st.session_state.max_overtime_hours),
        max_undertime_percent=float(st.session_state.max_undertime_percent),
        max_undertime_hours=float(st.session_state.max_undertime_hours),
        days=days,
        holidays=holidays,
        replacement_rest_scope=st.session_state.replacement_rest_scope,
        compensatory_rest_counts_as_hours=(
            bool(st.session_state.replacement_rest_enabled)
            and bool(st.session_state.compensatory_rest_counts_as_hours)
        ),
        vacation_counts_as_hours=True,
    )
    with st.expander("Monatsübersicht anzeigen", expanded=False):
        metric_cols = st.columns(4)
        metric_cols[0].metric("Kalendertage", len(days))
        metric_cols[1].metric("Benötigte Dienste", total_required)
        metric_cols[2].metric("Samstage/Sonntage", weekend_count)
        metric_cols[3].metric("Feiertage", holiday_count)
        hour_cols = st.columns(5)
        hour_cols[0].metric("Personal-Sollstunden", format_display_hours(staffing_summary["personnel_target_hours"]))
        hour_cols[1].metric("Benötigte Dienststunden", format_display_hours(staffing_summary["service_required_hours"]))
        hour_cols[2].metric("Planbare Stunden", format_display_hours(staffing_summary["required_hours"]))
        hour_cols[3].metric("Pflichtstunden", format_display_hours(staffing_summary["hard_required_hours"]))
        hour_cols[4].metric("Restspielraum", format_display_hours(staffing_summary["hard_margin_hours"]))
        fte_cols = st.columns(3)
        fte_cols[0].metric("Planbedarf VZÄ", format_display_hours(staffing_summary["service_required_fte"]))
        fte_cols[1].metric("Personal VZÄ", format_display_hours(staffing_summary["personnel_fte"]))
        fte_cols[2].metric("Differenz Personal VZÄ", format_display_hours(staffing_summary["fte_difference"]))
        st.caption(
            "VZÄ = Vollzeitäquivalent. Berechnet mit "
            f"{format_display_hours(staffing_summary['full_time_weekly_hours'])} h/Woche; "
            "Differenz = vorhandenes Personal minus Planbedarf."
        )
        if staffing_summary.get("replacement_rest_credit_hours", 0) > 0:
            st.caption(
                "Planbare Stunden enthalten zusätzlich "
                f"{format_display_hours(staffing_summary['replacement_rest_credit_hours'])} h Ersatzruhe, "
                f"weil der Ausgleich aktuell zu den Stunden zählt "
                f"({st.session_state.replacement_rest_kind}, {st.session_state.replacement_rest_scope})."
            )
        if staffing_summary.get("vacation_credit_hours", 0) > 0:
            st.caption(
                "Planbare Stunden enthalten zusätzlich "
                f"{format_display_hours(staffing_summary['vacation_credit_hours'])} h Urlaub, "
                "weil Urlaub immer zu den Stunden zählt."
            )
    previous_assignments_preview = previous_assignments_for_generation(
        st.session_state.saved_schedules,
        st.session_state.employees_df,
        int(selected_year),
        selected_month,
        int(st.session_state.planning_start_year),
        int(st.session_state.planning_start_month),
        shifts,
        night_shifts,
    )
    preflight_df = build_preflight_checks(
        employees=planning_employees,
        days=days,
        holidays=holidays,
        daily_requirements=daily_requirements,
        shifts=shifts,
        night_shifts=night_shifts,
        shift_priority_by_code=shift_priority_by_code,
        open_shift_codes=open_shift_codes,
        staffing_summary=staffing_summary,
        vacation_weekend_policy=st.session_state.vacation_weekend_policy,
        previous_assignments=previous_assignments_preview,
        block_night_before_wish_free=bool(st.session_state.block_night_before_wish_free),
        legal_profile=st.session_state.legal_profile,
        daily_max_work_hours=float(st.session_state.daily_max_work_hours),
        weekly_average_max_hours=float(st.session_state.weekly_average_max_hours),
        weekly_average_period_weeks=int(st.session_state.weekly_average_period_weeks),
        weekly_rest_hours=float(st.session_state.weekly_rest_hours),
        reduced_weekly_rest_hours=float(st.session_state.reduced_weekly_rest_hours),
        allow_reduced_weekly_rest=bool(st.session_state.allow_reduced_weekly_rest),
        shift_minutes_by_code=shift_minutes_by_code,
    )
    service_diagnostics_df = service_level_diagnostics(
        employees=planning_employees,
        days=days,
        holidays=holidays,
        daily_requirements=daily_requirements,
        shifts=shifts,
        night_shifts=night_shifts,
        shift_df=st.session_state.shifts_df,
        shift_priority_by_code=shift_priority_by_code,
        open_shift_codes=open_shift_codes,
        previous_assignments=previous_assignments_preview,
        block_night_before_wish_free=bool(st.session_state.block_night_before_wish_free),
        vacation_weekend_policy=st.session_state.vacation_weekend_policy,
    )
    blocker_count = int((preflight_df["Status"] == "Blocker").sum()) if not preflight_df.empty else 0
    warning_count = (
        int((preflight_df["Status"] == "Warnung").sum()) if not preflight_df.empty else 0
    ) + len(service_diagnostics_df)
    scenario_df = scenario_readiness_dataframe(
        preflight_df=preflight_df,
        service_diagnostics_df=service_diagnostics_df,
        staffing_summary=staffing_summary,
        previous_assignments=previous_assignments_preview,
        employees=planning_employees,
        days=days,
        holidays=holidays,
        vacation_weekend_policy=st.session_state.vacation_weekend_policy,
    )
    if blocker_count > 0 or warning_count > 0:
        with st.expander(
            f"Machbarkeitsprüfung ({blocker_count} Blocker, {warning_count} Warnungen)",
            expanded=True,
        ):
            st.caption("Diese Prüfung erkennt die häufigsten rechnerischen Gründe, warum ein Dienstplan nicht möglich ist.")
            st.dataframe(germanize_dataframe(preflight_df), width="stretch", hide_index=True)
            if not service_diagnostics_df.empty:
                st.markdown("**Engpässe je Tag und Dienstform**")
                st.dataframe(germanize_dataframe(service_diagnostics_df), width="stretch", hide_index=True)
    else:
        st.caption("Machbarkeit: keine Blocker oder Warnungen.")
    if staffing_summary["too_many_personnel_hours"] > 0:
        st.error(
            "Achtung: Es sind mehr Mindest-Personalstunden vorhanden als Dienststunden geplant sind. "
            f"Nach den Minusstunden-Grenzen müssen rund {format_display_hours(staffing_summary['personnel_min_hours'])} h verplant werden, "
            f"planbar sind aber nur {format_display_hours(staffing_summary['required_hours'])} h. "
            f"Es fehlen etwa {format_display_hours(staffing_summary['too_many_personnel_hours'])} h Spielraum. "
            "Passe Minusstunden, Wochenstunden, Personalanzahl oder Ressourcenbedarf an."
        )
    if staffing_summary["too_few_personnel_hours"] > 0:
        st.error(
            "Achtung: Die Pflichtdienste brauchen mehr Stunden, als mit der aktuellen Überstunden-Grenze möglich sind. "
            f"Es fehlen etwa {format_display_hours(staffing_summary['too_few_personnel_hours'])} h. "
            "Erhöhe die Überstunden-Grenze, plane mehr Personal ein oder reduziere Pflichtdienste."
        )
    if saved_plan:
        st.info("Für diesen Monat gibt es bereits einen gespeicherten, fixierten Dienstplan.")
    if st.session_state.get("best_plan_cache_loaded", False):
        st.success("Für diese Einstellungen wurde der bisher beste Entwurf aus dieser Sitzung geladen.")
        st.session_state.best_plan_cache_loaded = False
    workflow_df = planning_workflow_dataframe(
        employee_count=len(planning_employees),
        employee_warning_count=len(employee_warning_dataframe(employees)),
        blocker_count=blocker_count,
        warning_count=warning_count,
        generated_plan_exists=bool(st.session_state.get("generated_plan")),
        saved_plan_exists=bool(saved_plan),
        can_generate=bool(can_generate_selected),
    )
    selected_optimization_mode = normalize_plan_optimization_mode(st.session_state.plan_optimization_mode)
    selected_calculation_mode = DEFAULT_CALCULATION_MODE
    previous_assignments_current = previous_assignments_for_generation(
        st.session_state.saved_schedules,
        st.session_state.employees_df,
        int(selected_year),
        selected_month,
        int(st.session_state.planning_start_year),
        int(st.session_state.planning_start_month),
        shifts,
        night_shifts,
    )
    generation_settings = {
        "max_overtime_percent": float(st.session_state.max_overtime_percent),
        "max_overtime_hours": float(st.session_state.max_overtime_hours),
        "max_undertime_percent": float(st.session_state.max_undertime_percent),
        "max_undertime_hours": float(st.session_state.max_undertime_hours),
        "replacement_rest_enabled": bool(st.session_state.replacement_rest_enabled),
        "replacement_rest_kind": st.session_state.replacement_rest_kind,
        "replacement_rest_scope": st.session_state.replacement_rest_scope,
        "compensatory_rest_counts_as_hours": bool(st.session_state.compensatory_rest_counts_as_hours),
        "block_night_before_wish_free": bool(st.session_state.block_night_before_wish_free),
        "plan_is_turnus": bool(st.session_state.plan_is_turnus),
        "plan_includes_nights": bool(st.session_state.plan_includes_nights),
        "plan_includes_weekends": bool(st.session_state.plan_includes_weekends),
        "planning_start_year": int(st.session_state.planning_start_year),
        "planning_start_month": int(st.session_state.planning_start_month),
        "vacation_counts_as_hours": True,
        "vacation_weekend_policy": st.session_state.vacation_weekend_policy,
        "legal_profile": st.session_state.legal_profile,
        "daily_max_work_hours": float(st.session_state.daily_max_work_hours),
        "weekly_average_max_hours": float(st.session_state.weekly_average_max_hours),
        "weekly_average_period_weeks": int(st.session_state.weekly_average_period_weeks),
        "weekly_rest_hours": float(st.session_state.weekly_rest_hours),
        "reduced_weekly_rest_hours": float(st.session_state.reduced_weekly_rest_hours),
        "allow_reduced_weekly_rest": bool(st.session_state.allow_reduced_weekly_rest),
        "pause_policy": st.session_state.pause_policy,
        "pause_threshold_hours": float(st.session_state.pause_threshold_hours),
        "pause_duration_minutes": int(st.session_state.pause_duration_minutes),
        "time_account_usage": st.session_state.time_account_usage,
    }
    if st.session_state.night_credit_mode != "Keine Nachtgutschrift":
        generation_settings["night_credit_mode"] = st.session_state.night_credit_mode
        generation_settings["night_credit_hours"] = float(st.session_state.night_credit_hours)
    current_cache_key = generation_cache_key(
        year=int(selected_year),
        month=selected_month,
        calculation_mode=selected_calculation_mode,
        optimization_mode=selected_optimization_mode,
        employees_df=st.session_state.employees_df,
        shifts_df=st.session_state.shifts_df,
        resources_df=st.session_state.resources_df,
        daily_requirements=daily_requirements,
        day_requirement_overrides=st.session_state.day_requirement_overrides,
        month_key=month_key,
        open_shift_codes=open_shift_codes,
        previous_assignments=previous_assignments_current,
        settings=generation_settings,
    )
    base_seed = stable_seed_from_key(current_cache_key)
    base_solver_args = {
        "employees": planning_employees,
        "days": days,
        "shifts": shifts,
        "night_shifts": night_shifts,
        "daily_requirements": daily_requirements,
        "holidays": holidays,
        "shift_priority_by_code": shift_priority_by_code,
        "shift_minutes_by_code": shift_minutes_by_code,
        "previous_assignments": previous_assignments_current,
        "max_overtime_percent": float(st.session_state.max_overtime_percent),
        "max_overtime_hours": float(st.session_state.max_overtime_hours),
        "open_shift_codes": open_shift_codes,
        "replacement_rest_scope": st.session_state.replacement_rest_scope,
        "compensatory_rest_counts_as_hours": (
            bool(st.session_state.replacement_rest_enabled)
            and bool(st.session_state.compensatory_rest_counts_as_hours)
        ),
        "vacation_counts_as_hours": True,
        "vacation_weekend_policy": st.session_state.vacation_weekend_policy,
        "shift_time_by_code": shift_time_by_code,
        "max_undertime_percent": float(st.session_state.max_undertime_percent),
        "max_undertime_hours": float(st.session_state.max_undertime_hours),
        "block_night_before_wish_free": bool(st.session_state.block_night_before_wish_free),
        "daily_max_work_hours": float(st.session_state.daily_max_work_hours),
        "weekly_rest_hours": float(st.session_state.weekly_rest_hours),
        "reduced_weekly_rest_hours": float(st.session_state.reduced_weekly_rest_hours),
        "allow_reduced_weekly_rest": bool(st.session_state.allow_reduced_weekly_rest),
        "night_credit_mode": st.session_state.night_credit_mode,
        "night_credit_hours": float(st.session_state.night_credit_hours),
        "time_account_usage": st.session_state.time_account_usage,
    }
    if st.session_state.get("last_improvement_message"):
        st.info(st.session_state.last_improvement_message)
        st.session_state.last_improvement_message = ""

    generate = st.button(
        "Neu generieren" if saved_plan else "Dienstplan generieren",
        type="primary",
        width="stretch",
        disabled=not can_generate_selected,
    )

    if generate:
        st.session_state.generation_run_number = int(st.session_state.get("generation_run_number", 0)) + 1
        selected_optimization_mode = normalize_plan_optimization_mode(st.session_state.plan_optimization_mode)
        selected_calculation_mode = DEFAULT_CALCULATION_MODE
        previous_assignments_current = previous_assignments_for_generation(
            st.session_state.saved_schedules,
            st.session_state.employees_df,
            int(selected_year),
            selected_month,
            int(st.session_state.planning_start_year),
            int(st.session_state.planning_start_month),
            shifts,
            night_shifts,
        )
        generation_settings = {
            "max_overtime_percent": float(st.session_state.max_overtime_percent),
            "max_overtime_hours": float(st.session_state.max_overtime_hours),
            "max_undertime_percent": float(st.session_state.max_undertime_percent),
            "max_undertime_hours": float(st.session_state.max_undertime_hours),
            "replacement_rest_enabled": bool(st.session_state.replacement_rest_enabled),
            "replacement_rest_kind": st.session_state.replacement_rest_kind,
            "replacement_rest_scope": st.session_state.replacement_rest_scope,
            "compensatory_rest_counts_as_hours": bool(st.session_state.compensatory_rest_counts_as_hours),
            "block_night_before_wish_free": bool(st.session_state.block_night_before_wish_free),
            "plan_is_turnus": bool(st.session_state.plan_is_turnus),
            "plan_includes_nights": bool(st.session_state.plan_includes_nights),
            "plan_includes_weekends": bool(st.session_state.plan_includes_weekends),
            "planning_start_year": int(st.session_state.planning_start_year),
            "planning_start_month": int(st.session_state.planning_start_month),
            "vacation_counts_as_hours": True,
            "vacation_weekend_policy": st.session_state.vacation_weekend_policy,
            "legal_profile": st.session_state.legal_profile,
            "daily_max_work_hours": float(st.session_state.daily_max_work_hours),
            "weekly_average_max_hours": float(st.session_state.weekly_average_max_hours),
            "weekly_average_period_weeks": int(st.session_state.weekly_average_period_weeks),
            "weekly_rest_hours": float(st.session_state.weekly_rest_hours),
            "reduced_weekly_rest_hours": float(st.session_state.reduced_weekly_rest_hours),
            "allow_reduced_weekly_rest": bool(st.session_state.allow_reduced_weekly_rest),
            "pause_policy": st.session_state.pause_policy,
            "pause_threshold_hours": float(st.session_state.pause_threshold_hours),
            "pause_duration_minutes": int(st.session_state.pause_duration_minutes),
            "time_account_usage": st.session_state.time_account_usage,
        }
        if st.session_state.night_credit_mode != "Keine Nachtgutschrift":
            generation_settings["night_credit_mode"] = st.session_state.night_credit_mode
            generation_settings["night_credit_hours"] = float(st.session_state.night_credit_hours)
        current_cache_key = generation_cache_key(
            year=int(selected_year),
            month=selected_month,
            calculation_mode=selected_calculation_mode,
            optimization_mode=selected_optimization_mode,
            employees_df=st.session_state.employees_df,
            shifts_df=st.session_state.shifts_df,
            resources_df=st.session_state.resources_df,
            daily_requirements=daily_requirements,
            day_requirement_overrides=st.session_state.day_requirement_overrides,
            month_key=month_key,
            open_shift_codes=open_shift_codes,
            previous_assignments=previous_assignments_current,
            settings=generation_settings,
        )
        base_seed = stable_seed_from_key(current_cache_key)
        cached_plan = st.session_state.best_plan_cache.get(current_cache_key)
        cached_plan_candidate = None
        if cached_plan:
            cached_plan_copy = copy.deepcopy(cached_plan)
            if st.session_state.night_credit_mode != "Keine Nachtgutschrift":
                cached_plan_copy["metrics"] = apply_night_credit_hours(
                    cached_plan_copy.get("schedule", {}),
                    cached_plan_copy.get("metrics", {}),
                    night_shifts,
                    float(st.session_state.night_credit_hours),
                    counts_as_hours=st.session_state.night_credit_mode == "Nachtgutschrift als Dienststunden",
                )
                cached_plan_copy["night_credit_mode"] = st.session_state.night_credit_mode
                cached_plan_copy["night_credit_hours"] = float(st.session_state.night_credit_hours)
            cached_plan_candidate = cached_plan_copy
        compatibility_settings = {
            "replacement_rest_enabled": bool(st.session_state.replacement_rest_enabled),
            "replacement_rest_scope": st.session_state.replacement_rest_scope,
            "counts_rest_as_hours": (
                bool(st.session_state.replacement_rest_enabled)
                and bool(st.session_state.compensatory_rest_counts_as_hours)
            ),
            "vacation_weekend_policy": st.session_state.vacation_weekend_policy,
            "max_overtime_percent": float(st.session_state.max_overtime_percent),
            "max_overtime_hours": float(st.session_state.max_overtime_hours),
            "max_undertime_percent": float(st.session_state.max_undertime_percent),
            "max_undertime_hours": float(st.session_state.max_undertime_hours),
            "block_night_before_wish_free": bool(st.session_state.block_night_before_wish_free),
            "daily_max_work_hours": float(st.session_state.daily_max_work_hours),
            "weekly_average_max_hours": float(st.session_state.weekly_average_max_hours),
            "weekly_average_period_weeks": int(st.session_state.weekly_average_period_weeks),
            "weekly_rest_hours": float(st.session_state.weekly_rest_hours),
            "reduced_weekly_rest_hours": float(st.session_state.reduced_weekly_rest_hours),
            "allow_reduced_weekly_rest": bool(st.session_state.allow_reduced_weekly_rest),
            "pause_policy": st.session_state.pause_policy,
            "pause_threshold_hours": float(st.session_state.pause_threshold_hours),
            "pause_duration_minutes": int(st.session_state.pause_duration_minutes),
            "night_credit_mode": st.session_state.night_credit_mode,
            "night_credit_hours": float(st.session_state.night_credit_hours),
            "time_account_usage": st.session_state.time_account_usage,
            "plan_optimization_mode": selected_optimization_mode,
            "calculation_mode": selected_calculation_mode,
        }
        employee_name_set = {employee.name for employee in planning_employees}
        compatible_cached_plan = None
        for candidate in st.session_state.best_plan_cache.values():
            if not isinstance(candidate, dict) or candidate.get("key") != fixed_plan_key:
                continue
            candidate_schedule = candidate.get("schedule", {})
            if set(candidate_schedule.keys()) != employee_name_set:
                continue
            if any(len(assignments) != len(days) for assignments in candidate_schedule.values()):
                continue
            if any(candidate.get(key) != value for key, value in compatibility_settings.items()):
                continue
            candidate_copy = copy.deepcopy(candidate)
            candidate_rule_checks = validate_schedule_rules(
                schedule=candidate_copy.get("schedule", {}),
                metrics=candidate_copy.get("metrics", {}),
                employees=planning_employees,
                days=days,
                night_shifts=night_shifts,
                shifts=shifts,
                holidays=holidays,
                daily_requirements=daily_requirements,
                shift_df=st.session_state.shifts_df,
                shift_minutes_by_code=shift_minutes_by_code,
                shift_time_by_code=shift_time_by_code,
                max_overtime_percent=float(st.session_state.max_overtime_percent),
                max_overtime_hours=float(st.session_state.max_overtime_hours),
                max_undertime_percent=float(st.session_state.max_undertime_percent),
                max_undertime_hours=float(st.session_state.max_undertime_hours),
                block_night_before_wish_free=bool(st.session_state.block_night_before_wish_free),
                previous_assignments=previous_assignments_current,
                open_shift_codes=open_shift_codes,
                shift_priority_by_code=shift_priority_by_code,
                vacation_weekend_policy=st.session_state.vacation_weekend_policy,
                legal_profile=st.session_state.legal_profile,
                daily_max_work_hours=float(st.session_state.daily_max_work_hours),
                weekly_average_max_hours=float(st.session_state.weekly_average_max_hours),
                weekly_average_period_weeks=int(st.session_state.weekly_average_period_weeks),
                weekly_rest_hours=float(st.session_state.weekly_rest_hours),
                reduced_weekly_rest_hours=float(st.session_state.reduced_weekly_rest_hours),
                allow_reduced_weekly_rest=bool(st.session_state.allow_reduced_weekly_rest),
                saved_schedules=st.session_state.saved_schedules,
            )
            if any(check.get("Status") == "Fehler" for check in candidate_rule_checks):
                continue
            candidate_copy["rule_checks"] = candidate_rule_checks
            if st.session_state.night_credit_mode != "Keine Nachtgutschrift":
                candidate_copy["metrics"] = apply_night_credit_hours(
                    candidate_copy.get("schedule", {}),
                    candidate_copy.get("metrics", {}),
                    night_shifts,
                    float(st.session_state.night_credit_hours),
                    counts_as_hours=st.session_state.night_credit_mode == "Nachtgutschrift als Dienststunden",
                )
                candidate_copy["night_credit_mode"] = st.session_state.night_credit_mode
                candidate_copy["night_credit_hours"] = float(st.session_state.night_credit_hours)
            compatible_cached_plan = better_plan_payload(
                compatible_cached_plan,
                candidate_copy,
                days=days,
                daily_requirements=daily_requirements,
                shift_df=st.session_state.shifts_df,
                open_shift_codes=open_shift_codes,
                shift_priority_by_code=shift_priority_by_code,
            )
        best_cached_candidate = better_plan_payload(
            cached_plan_candidate,
            compatible_cached_plan,
            days=days,
            daily_requirements=daily_requirements,
            shift_df=st.session_state.shifts_df,
            open_shift_codes=open_shift_codes,
            shift_priority_by_code=shift_priority_by_code,
        )
        if best_cached_candidate:
            best_cached_candidate["cache_key"] = current_cache_key
            st.session_state.best_plan_cache[current_cache_key] = best_cached_candidate
            save_best_plan_cache(st.session_state.best_plan_cache)
            st.session_state.generated_plan = copy.deepcopy(best_cached_candidate)
            st.session_state.generated_plan["key"] = fixed_plan_key
            st.session_state.best_plan_cache_loaded = True
            st.rerun()
        open_shift_set = set(open_shift_codes)
        max_shift_demand = max(
            (
                demand
                for (_day_index, shift), demand in daily_requirements.items()
                if shift_priority_by_code.get(shift, 1) == 1 and shift not in open_shift_set
            ),
            default=0,
        )
        max_day_demand = max(
            sum(
                daily_requirements.get((d, shift), 0)
                for shift in shifts
                if shift_priority_by_code.get(shift, 1) == 1 and shift not in open_shift_set
            )
            for d in range(len(days))
        )
        if len(planning_employees) < max_shift_demand or len(planning_employees) < max_day_demand:
            st.error("Es gibt zu wenige MitarbeiterInnen für den höchsten Pflichtbedarf an einem Tag.")
            st.stop()

        progress_text = st.empty()
        progress_bar = st.progress(0)
        progress_text.info("Dienstplan wird vorbereitet...")
        progress_bar.progress(10)
        progress_text.info("Regeln und Monatsdaten werden geprüft...")
        progress_bar.progress(25)
        progress_text.info("Zuerst wird ein möglichst vollständig besetzter Plan gesucht...")
        progress_bar.progress(40)
        preview_slot = st.empty()
        generation_started_at = datetime.now()
        generation_wall_time_limit_seconds = 240
        render_generation_preview(
            preview_slot,
            "Noch kein gültiger Plan gefunden. Die Optimierung startet gerade.",
            None,
            None,
            days,
            planning_employees,
            daily_requirements,
            st.session_state.shifts_df,
            open_shift_codes,
            shift_priority_by_code,
        )
        with st.spinner("Dienstplan wird optimiert..."):
            solver_args = {
                "employees": planning_employees,
                "days": days,
                "shifts": shifts,
                "night_shifts": night_shifts,
                "daily_requirements": daily_requirements,
                "holidays": holidays,
                "shift_priority_by_code": shift_priority_by_code,
                "shift_minutes_by_code": shift_minutes_by_code,
                "previous_assignments": previous_assignments_current,
                "max_overtime_percent": float(st.session_state.max_overtime_percent),
                "max_overtime_hours": float(st.session_state.max_overtime_hours),
                "open_shift_codes": open_shift_codes,
                "replacement_rest_scope": st.session_state.replacement_rest_scope,
                "compensatory_rest_counts_as_hours": (
                    bool(st.session_state.replacement_rest_enabled)
                    and bool(st.session_state.compensatory_rest_counts_as_hours)
                ),
                "vacation_counts_as_hours": True,
                "vacation_weekend_policy": st.session_state.vacation_weekend_policy,
                "shift_time_by_code": shift_time_by_code,
                "max_undertime_percent": float(st.session_state.max_undertime_percent),
                "max_undertime_hours": float(st.session_state.max_undertime_hours),
                "block_night_before_wish_free": bool(st.session_state.block_night_before_wish_free),
                "daily_max_work_hours": float(st.session_state.daily_max_work_hours),
                "weekly_rest_hours": float(st.session_state.weekly_rest_hours),
                "reduced_weekly_rest_hours": float(st.session_state.reduced_weekly_rest_hours),
                "allow_reduced_weekly_rest": bool(st.session_state.allow_reduced_weekly_rest),
                "night_credit_mode": st.session_state.night_credit_mode,
                "night_credit_hours": float(st.session_state.night_credit_hours),
                "time_account_usage": st.session_state.time_account_usage,
            }
            holiday_heavy = holiday_pressure_level(days, holidays) >= 6
            defer_replacement_rest = False
            solver_run_args = dict(solver_args)
            if defer_replacement_rest:
                solver_run_args["replacement_rest_scope"] = "Keine Ersatzruhe"
                solver_run_args["compensatory_rest_counts_as_hours"] = False
            status, schedule, metrics = solve_schedule(
                **solver_run_args,
                max_time_seconds=35,
                optimize_for_fairness=False,
                plan_strategy="Abdeckung zuerst",
                random_seed=base_seed,
            )
            optimization_note = ""
            if schedule:
                variant_profiles = generation_variant_profiles(selected_optimization_mode, days, holidays)
                progress_text.info("Gültiger Plan gefunden. Jetzt werden gezielte Varianten verglichen...")
                progress_bar.progress(65)
                best_status, best_schedule, best_metrics = status, schedule, metrics
                best_score = plan_quality_score(
                    schedule,
                    metrics,
                    days,
                    daily_requirements,
                    st.session_state.shifts_df,
                    open_shift_codes,
                    shift_priority_by_code,
                    selected_optimization_mode,
                )
                best_rank = plan_comparison_key(
                    best_schedule,
                    best_metrics,
                    days,
                    daily_requirements,
                    st.session_state.shifts_df,
                    open_shift_codes,
                    shift_priority_by_code,
                    selected_optimization_mode,
                    selected_calculation_mode,
                    best_status,
                )
                best_shortage_penalty = schedule_shortage_penalty(
                    schedule,
                    days,
                    daily_requirements,
                    st.session_state.shifts_df,
                    open_shift_codes,
                    shift_priority_by_code,
                )
                render_generation_preview(
                    preview_slot,
                    "Erster gültiger Plan gefunden. Jetzt wird nach besseren Varianten gesucht.",
                    best_schedule,
                    best_metrics,
                    days,
                    planning_employees,
                    daily_requirements,
                    st.session_state.shifts_df,
                    open_shift_codes,
                    shift_priority_by_code,
                    score=best_score,
                    status=best_status,
                )
                optimized_found = False
                allowed_shortage_penalty = allowed_shortage_penalty_for_mode(
                    selected_optimization_mode,
                    best_shortage_penalty,
                )
                for variant_index, (variant_label, variant_strategy, seed_offset) in enumerate(variant_profiles, start=1):
                    if (datetime.now() - generation_started_at).total_seconds() > generation_wall_time_limit_seconds:
                        optimization_note = (
                            "Die automatische Optimierung wurde nach dem Zeitfenster beendet. "
                            "Der beste bis dahin gefundene gültige Plan wird angezeigt und kann mit 'Plan weiter optimieren' verfeinert werden."
                        )
                        break
                    progress_text.info(f"Variante {variant_index}: {variant_label}...")
                    progress_bar.progress(
                        min(88, 65 + int(20 * variant_index / max(1, len(variant_profiles))))
                    )
                    time_budget = (
                        26
                        if variant_strategy == "Abdeckung zuerst"
                        else variant_time_budget_seconds(
                            best_metrics,
                            selected_optimization_mode,
                            holiday_heavy=holiday_heavy,
                        )
                    )
                    variant_shortage_limit = (
                        best_shortage_penalty
                        if variant_strategy == "Abdeckung zuerst"
                        else allowed_shortage_penalty
                    )
                    optimized_status, optimized_schedule, optimized_metrics = solve_schedule(
                        **solver_run_args,
                        max_time_seconds=time_budget,
                        optimize_for_fairness=True,
                        plan_strategy=variant_strategy,
                        random_seed=base_seed + seed_offset,
                        deterministic_search=False,
                        max_shortage_penalty=variant_shortage_limit,
                    )
                    if not optimized_schedule:
                        render_generation_preview(
                            preview_slot,
                            f"Variante {variant_index} ({variant_label}) hat keine gültige Verbesserung geliefert. Bisher beste Variante bleibt sichtbar.",
                            best_schedule,
                            best_metrics,
                            days,
                            planning_employees,
                            daily_requirements,
                            st.session_state.shifts_df,
                            open_shift_codes,
                            shift_priority_by_code,
                            score=best_score,
                            status=best_status,
                        )
                        continue
                    optimized_found = True
                    score = plan_quality_score(
                        optimized_schedule,
                        optimized_metrics,
                        days,
                        daily_requirements,
                        st.session_state.shifts_df,
                        open_shift_codes,
                        shift_priority_by_code,
                        selected_optimization_mode,
                    )
                    rank = plan_comparison_key(
                        optimized_schedule,
                        optimized_metrics,
                        days,
                        daily_requirements,
                        st.session_state.shifts_df,
                        open_shift_codes,
                        shift_priority_by_code,
                        selected_optimization_mode,
                        selected_calculation_mode,
                        optimized_status,
                    )
                    if rank > best_rank:
                        best_status, best_schedule, best_metrics = optimized_status, optimized_schedule, optimized_metrics
                        best_score = score
                        best_rank = rank
                        best_shortage_penalty = schedule_shortage_penalty(
                            optimized_schedule,
                            days,
                            daily_requirements,
                            st.session_state.shifts_df,
                            open_shift_codes,
                            shift_priority_by_code,
                        )
                        allowed_shortage_penalty = allowed_shortage_penalty_for_mode(
                            selected_optimization_mode,
                            best_shortage_penalty,
                        )
                        preview_title = f"Variante {variant_index} ({variant_label}) ist aktuell die beste gefundene Lösung."
                    else:
                        preview_title = f"Variante {variant_index} ({variant_label}) wurde geprüft. Die bisher beste Lösung bleibt vorne."
                    render_generation_preview(
                        preview_slot,
                        preview_title,
                        best_schedule,
                        best_metrics,
                        days,
                        planning_employees,
                        daily_requirements,
                        st.session_state.shifts_df,
                        open_shift_codes,
                        shift_priority_by_code,
                        score=best_score,
                        status=best_status,
                    )
                satisfaction_target = 88.0 if selected_optimization_mode == "Zufriedenheit zuerst" else 78.0
                if average_satisfaction_value(best_metrics) < satisfaction_target:
                    progress_text.info(
                        "Die Zufriedenheit ist noch zu niedrig. Zusätzliche feste Qualitätsläufe werden geprüft..."
                    )
                    extra_profiles = [
                        ("Zufriedenheit vertiefen", "Zufriedenheit zuerst", 307, 55),
                        ("Warnungen vertiefen", "Warnungen minimieren", 347, 55),
                        ("Wunschfrei vertiefen", "Wunschfrei schützen", 389, 50),
                        ("Minimum anheben", "Schlechteste Person schützen", 431, 50),
                        ("Stunden nachglätten", "Stunden sanft glätten", 479, 45),
                    ]
                    if holiday_heavy:
                        extra_profiles.append(("Feiertage vertiefen", "Feiertage robust", 523, 55))
                    for extra_index, (extra_label, extra_strategy, seed_offset, time_budget) in enumerate(extra_profiles, start=1):
                        if (datetime.now() - generation_started_at).total_seconds() > generation_wall_time_limit_seconds:
                            optimization_note = (
                                "Die automatische Optimierung wurde nach dem Zeitfenster beendet. "
                                "Der beste bis dahin gefundene gültige Plan wird angezeigt und kann mit 'Plan weiter optimieren' verfeinert werden."
                            )
                            break
                        progress_bar.progress(min(94, 88 + extra_index))
                        progress_text.info(f"Zusatzlauf {extra_index}: {extra_label}...")
                        extra_status, extra_schedule, extra_metrics = solve_schedule(
                            **solver_run_args,
                            max_time_seconds=time_budget,
                            optimize_for_fairness=True,
                            plan_strategy=extra_strategy,
                            random_seed=base_seed + seed_offset,
                            deterministic_search=False,
                            max_shortage_penalty=allowed_shortage_penalty,
                        )
                        if not extra_schedule:
                            continue
                        optimized_found = True
                        extra_score = plan_quality_score(
                            extra_schedule,
                            extra_metrics,
                            days,
                            daily_requirements,
                            st.session_state.shifts_df,
                            open_shift_codes,
                            shift_priority_by_code,
                            selected_optimization_mode,
                        )
                        extra_rank = plan_comparison_key(
                            extra_schedule,
                            extra_metrics,
                            days,
                            daily_requirements,
                            st.session_state.shifts_df,
                            open_shift_codes,
                            shift_priority_by_code,
                            selected_optimization_mode,
                            selected_calculation_mode,
                            extra_status,
                        )
                        if extra_rank > best_rank:
                            best_status, best_schedule, best_metrics = extra_status, extra_schedule, extra_metrics
                            best_score = extra_score
                            best_rank = extra_rank
                            best_shortage_penalty = schedule_shortage_penalty(
                                extra_schedule,
                                days,
                                daily_requirements,
                                st.session_state.shifts_df,
                                open_shift_codes,
                                shift_priority_by_code,
                            )
                            allowed_shortage_penalty = allowed_shortage_penalty_for_mode(
                                selected_optimization_mode,
                                best_shortage_penalty,
                            )
                            render_generation_preview(
                                preview_slot,
                                f"Zusatzlauf {extra_index} ({extra_label}) hat die Qualität verbessert.",
                                best_schedule,
                                best_metrics,
                                days,
                                planning_employees,
                                daily_requirements,
                                st.session_state.shifts_df,
                                open_shift_codes,
                                shift_priority_by_code,
                                score=best_score,
                                status=best_status,
                            )
                        if average_satisfaction_value(best_metrics) >= satisfaction_target:
                            break
                status, schedule, metrics = best_status, best_schedule, best_metrics
                if not optimized_found:
                    optimization_note = (
                        "Der erste Plan ist gültig. Die gezielten Varianten haben keinen besseren Plan mehr gefunden."
                    )
                else:
                    optimization_note = (
                        f"Mehrere feste Varianten wurden geprüft; gewählt wurde die beste Lösung für "
                        f"'{selected_optimization_mode}' nach Zufriedenheit, Warnungen und offenen Diensten."
                    )

        progress_bar.progress(90)
        progress_text.info("Ergebnis wird aufbereitet...")

        if not schedule:
            progress_bar.empty()
            progress_text.empty()
            st.error("Es wurde kein gültiger Plan gefunden.")
            st.caption(f"Solver-Status: {status}")
            st.subheader("Wahrscheinlichste Ursachen")
            issue_df = preflight_df[preflight_df["Status"] != "OK"] if not preflight_df.empty else preflight_df
            if issue_df.empty and service_diagnostics_df.empty:
                st.warning(
                    "Die Schnellprüfung hat keinen einfachen Blocker gefunden. "
                    "Der genaue Solver meldet aber einen Konflikt zwischen mehreren harten Einzelregeln."
                )
            elif not issue_df.empty:
                st.dataframe(germanize_dataframe(issue_df), width="stretch", hide_index=True)
            if not service_diagnostics_df.empty:
                st.markdown("**Konkrete Engpässe je Tag und Dienstform**")
                st.dataframe(germanize_dataframe(service_diagnostics_df), width="stretch", hide_index=True)
            diagnosis_reasons = diagnose_no_plan(
                employees=planning_employees,
                days=days,
                holidays=holidays,
                daily_requirements=daily_requirements,
                open_shift_codes=open_shift_codes,
                shifts=shifts,
                shift_priority_by_code=shift_priority_by_code,
                shift_minutes_by_code=shift_minutes_by_code,
                night_shifts=night_shifts,
                max_overtime_percent=float(st.session_state.max_overtime_percent),
                max_overtime_hours=float(st.session_state.max_overtime_hours),
                max_undertime_percent=float(st.session_state.max_undertime_percent),
                max_undertime_hours=float(st.session_state.max_undertime_hours),
                replacement_rest_scope=st.session_state.replacement_rest_scope,
                compensatory_rest_counts_as_hours=(
                    bool(st.session_state.replacement_rest_enabled)
                    and bool(st.session_state.compensatory_rest_counts_as_hours)
                ),
            )
            next_steps_df = failure_next_steps_dataframe(
                issue_df,
                service_diagnostics_df,
                diagnosis_reasons,
            )
            if not next_steps_df.empty:
                st.markdown("**Was du als Erstes tun solltest**")
                st.dataframe(germanize_dataframe(next_steps_df), width="stretch", hide_index=True)
            for reason in diagnosis_reasons:
                if reason.startswith("Hauptgrund:"):
                    st.error(reason)
                else:
                    st.warning(reason)
            st.warning(
                "Tipp: Mehr Mitarbeiter hinzufügen, Ressourcenbedarf reduzieren, Wunschfrei-/Urlaubstage reduzieren oder Maximalwerte lockern."
            )
        else:
            progress_bar.progress(100)
            progress_text.success("Dienstplan fertig.")
            if st.session_state.replacement_rest_enabled:
                schedule, metrics, open_rest_notes = add_compensatory_rest_days(
                    schedule,
                    metrics,
                    days,
                    holidays,
                    shift_hours_by_code,
                    st.session_state.replacement_rest_scope,
                    bool(st.session_state.compensatory_rest_counts_as_hours),
                    source_hours_already_counted=not defer_replacement_rest,
                    employees=planning_employees,
                    vacation_weekend_policy=st.session_state.vacation_weekend_policy,
                )
            else:
                open_rest_notes = []
            if st.session_state.night_credit_mode != "Keine Nachtgutschrift":
                metrics = apply_night_credit_hours(
                    schedule,
                    metrics,
                    night_shifts,
                    float(st.session_state.night_credit_hours),
                    counts_as_hours=st.session_state.night_credit_mode == "Nachtgutschrift als Dienststunden",
                )
            rule_checks = validate_schedule_rules(
                schedule=schedule,
                metrics=metrics,
                employees=planning_employees,
                days=days,
                night_shifts=night_shifts,
                shifts=shifts,
                holidays=holidays,
                daily_requirements=daily_requirements,
                shift_df=st.session_state.shifts_df,
                shift_minutes_by_code=shift_minutes_by_code,
                shift_time_by_code=shift_time_by_code,
                max_overtime_percent=float(st.session_state.max_overtime_percent),
                max_overtime_hours=float(st.session_state.max_overtime_hours),
                max_undertime_percent=float(st.session_state.max_undertime_percent),
                max_undertime_hours=float(st.session_state.max_undertime_hours),
                block_night_before_wish_free=bool(st.session_state.block_night_before_wish_free),
                previous_assignments=previous_assignments_current,
                open_shift_codes=open_shift_codes,
                shift_priority_by_code=shift_priority_by_code,
                vacation_weekend_policy=st.session_state.vacation_weekend_policy,
                legal_profile=st.session_state.legal_profile,
                daily_max_work_hours=float(st.session_state.daily_max_work_hours),
                weekly_average_max_hours=float(st.session_state.weekly_average_max_hours),
                weekly_average_period_weeks=int(st.session_state.weekly_average_period_weeks),
                weekly_rest_hours=float(st.session_state.weekly_rest_hours),
                reduced_weekly_rest_hours=float(st.session_state.reduced_weekly_rest_hours),
                allow_reduced_weekly_rest=bool(st.session_state.allow_reduced_weekly_rest),
                saved_schedules=st.session_state.saved_schedules,
            )
            preview_slot.empty()
            final_quality_score = plan_quality_score(
                schedule,
                metrics,
                days,
                daily_requirements,
                st.session_state.shifts_df,
                open_shift_codes,
                shift_priority_by_code,
                selected_optimization_mode,
            )
            generated_plan_payload = {
                "key": fixed_plan_key,
                "year": int(selected_year),
                "month": selected_month,
                "status": status,
                "schedule": schedule,
                "metrics": metrics,
                "open_rest_notes": open_rest_notes,
                "rule_checks": rule_checks,
                "replacement_rest_enabled": bool(st.session_state.replacement_rest_enabled),
                "replacement_rest_kind": st.session_state.replacement_rest_kind,
                "replacement_rest_scope": st.session_state.replacement_rest_scope,
                "counts_rest_as_hours": (
                    bool(st.session_state.replacement_rest_enabled)
                    and bool(st.session_state.compensatory_rest_counts_as_hours)
                ),
                "night_credit_mode": st.session_state.night_credit_mode,
                "night_credit_hours": float(st.session_state.night_credit_hours),
                "vacation_counts_as_hours": True,
                "vacation_weekend_policy": st.session_state.vacation_weekend_policy,
                "max_overtime_percent": float(st.session_state.max_overtime_percent),
                "max_overtime_hours": float(st.session_state.max_overtime_hours),
                "max_undertime_percent": float(st.session_state.max_undertime_percent),
                "max_undertime_hours": float(st.session_state.max_undertime_hours),
                "block_night_before_wish_free": bool(st.session_state.block_night_before_wish_free),
                "legal_profile": st.session_state.legal_profile,
                "daily_max_work_hours": float(st.session_state.daily_max_work_hours),
                "weekly_average_max_hours": float(st.session_state.weekly_average_max_hours),
                "weekly_average_period_weeks": int(st.session_state.weekly_average_period_weeks),
                "weekly_rest_hours": float(st.session_state.weekly_rest_hours),
                "reduced_weekly_rest_hours": float(st.session_state.reduced_weekly_rest_hours),
                "allow_reduced_weekly_rest": bool(st.session_state.allow_reduced_weekly_rest),
                "pause_policy": st.session_state.pause_policy,
                "pause_threshold_hours": float(st.session_state.pause_threshold_hours),
                "pause_duration_minutes": int(st.session_state.pause_duration_minutes),
                "time_account_usage": st.session_state.time_account_usage,
                "open_shift_codes": open_shift_codes,
                "shifts": shifts,
                "night_shifts": night_shifts,
                "plan_optimization_mode": selected_optimization_mode,
                "calculation_mode": selected_calculation_mode,
                "cache_key": current_cache_key,
                "quality_score": final_quality_score,
            }
            best_cached_plan = better_plan_payload(
                st.session_state.best_plan_cache.get(current_cache_key),
                generated_plan_payload,
                days=days,
                daily_requirements=daily_requirements,
                shift_df=st.session_state.shifts_df,
                open_shift_codes=open_shift_codes,
                shift_priority_by_code=shift_priority_by_code,
            )
            st.session_state.best_plan_cache[current_cache_key] = best_cached_plan
            save_best_plan_cache(st.session_state.best_plan_cache)
            st.session_state.generated_plan = copy.deepcopy(best_cached_plan)
            st.session_state.generated_plan["key"] = fixed_plan_key
            if status == "OPTIMAL":
                st.success("Gültiger Dienstplan gefunden.")
                st.info(
                    "Der interne Solverlauf wurde optimal abgeschlossen. "
                    "Die beste angezeigte Variante wird zusätzlich nach Zufriedenheit und Warnungen verglichen."
                )
            else:
                st.warning("Gültiger Dienstplan gefunden, aber der interne Rechenschritt ist nicht optimal bewiesen.")
            if optimization_note:
                st.info(optimization_note)

    pending_plan = st.session_state.generated_plan
    if pending_plan and pending_plan.get("key") == fixed_plan_key:
        pending_rule_errors = sum(1 for check in pending_plan.get("rule_checks", []) if check.get("Status") == "Fehler")
        if pending_rule_errors:
            st.error("Dieser Entwurf hat Fehler in der Regelprüfung und kann nicht fixiert werden.")

        def visible_plan_stats(plan: dict) -> dict[str, object]:
            metrics = plan.get("metrics", {})
            metrics_df = pd.DataFrame.from_dict(metrics, orient="index") if metrics else pd.DataFrame()
            open_df = open_services_dataframe(
                plan.get("schedule", {}),
                days,
                daily_requirements,
                st.session_state.shifts_df,
                open_shift_codes=[],
                shift_priority_by_code=shift_priority_by_code,
            )
            max_deviation = 0.0
            if not metrics_df.empty and "Stundenabweichung h" in metrics_df:
                max_deviation = float(
                    pd.to_numeric(metrics_df["Stundenabweichung h"], errors="coerce").fillna(0).max()
                )
            return {
                "satisfaction": average_satisfaction_value(metrics),
                "warnings": active_warning_value(metrics),
                "open": int(open_df.get("Offen", pd.Series(dtype=int)).sum()) if not open_df.empty else 0,
                "deviation": max_deviation,
                "status": solver_status_text(plan.get("status")),
            }

        if pending_plan.get("schedule") and pending_plan.get("status") != "OPTIMAL":
            stats = visible_plan_stats(pending_plan)
            st.markdown("**Beste Variante bisher**")
            improve_summary_cols = st.columns(5)
            improve_summary_cols[0].metric("Zufriedenheit Ø", f"{format_display_hours(round(float(stats['satisfaction']), 1))} %")
            improve_summary_cols[1].metric("Warnungen", int(stats["warnings"]))
            improve_summary_cols[2].metric("Offene Dienste", int(stats["open"]))
            improve_summary_cols[3].metric("Max. Abweichung", f"{format_display_hours(stats['deviation'])} h")
            improve_summary_cols[4].metric("Optimalität", str(stats["status"]))

        improvement_progress_slot = st.empty()
        improvement_text_slot = st.empty()
        improvement_preview_slot = st.empty()
        save_left, improve_middle, save_right = st.columns([0.36, 0.28, 0.36])
        with save_left:
            if st.button("Plan speichern und fixieren", type="primary", width="stretch", disabled=pending_rule_errors > 0):
                st.session_state.saved_schedules[fixed_plan_key] = pending_plan
                save_saved_schedules(st.session_state.saved_schedules)
                next_year_after_save, next_month_after_save = next_open_plan_month(
                    st.session_state.saved_schedules,
                    int(st.session_state.planning_start_year),
                    int(st.session_state.planning_start_month),
                )
                st.session_state.selected_year = next_year_after_save
                st.session_state.selected_month = next_month_after_save
                st.session_state.manual_month_view = False
                st.session_state.generated_plan = None
                st.success("Dienstplan gespeichert. Er ist jetzt für die MitarbeiterInnen fix.")
                st.rerun()
        with improve_middle:
            show_improve_button = (
                bool(pending_plan.get("schedule"))
                and pending_plan.get("status") != "OPTIMAL"
                and pending_rule_errors == 0
            )
            input_matches = pending_plan.get("cache_key") == current_cache_key
            if show_improve_button and not input_matches:
                st.caption("Einstellungen haben sich geändert. Bitte zuerst neu generieren.")
            if show_improve_button and st.button(
                "Plan weiter optimieren",
                width="stretch",
                disabled=not input_matches,
                help="Prüft zusätzliche Qualitätsläufe. Der bisherige Plan wird nur ersetzt, wenn eine bessere Variante gefunden wird.",
            ):
                before_stats = visible_plan_stats(pending_plan)
                best_plan = copy.deepcopy(pending_plan)
                best_rank = plan_comparison_key(
                    best_plan.get("schedule", {}),
                    best_plan.get("metrics", {}),
                    days,
                    daily_requirements,
                    st.session_state.shifts_df,
                    open_shift_codes,
                    shift_priority_by_code,
                    selected_optimization_mode,
                    selected_calculation_mode,
                    best_plan.get("status"),
                )
                best_shortage_penalty = schedule_shortage_penalty(
                    best_plan.get("schedule", {}),
                    days,
                    daily_requirements,
                    st.session_state.shifts_df,
                    open_shift_codes,
                    shift_priority_by_code,
                )
                allowed_shortage_penalty = allowed_shortage_penalty_for_mode(
                    selected_optimization_mode,
                    best_shortage_penalty,
                )
                improvement_progress = improvement_progress_slot.progress(0)
                improvement_text = improvement_text_slot
                improvement_preview = improvement_preview_slot
                holiday_heavy = holiday_pressure_level(days, holidays) >= 6
                improvement_profiles = plan_improvement_profiles(
                    selected_optimization_mode,
                    holiday_heavy=holiday_heavy,
                )
                improved = False
                improvement_timed_out = False
                improvement_started_at = datetime.now()
                improvement_wall_time_limit_seconds = 180
                with st.spinner("Plan wird weiter optimiert..."):
                    for improvement_index, (label, strategy, seed_offset, time_budget) in enumerate(improvement_profiles, start=1):
                        remaining_seconds = improvement_wall_time_limit_seconds - (
                            datetime.now() - improvement_started_at
                        ).total_seconds()
                        if remaining_seconds <= 5:
                            improvement_timed_out = True
                            break
                        improvement_text.info(f"Verbesserungslauf {improvement_index}: {label}...")
                        improvement_progress.progress(
                            min(95, int(100 * improvement_index / max(1, len(improvement_profiles))))
                        )
                        candidate_status, candidate_schedule, candidate_metrics = solve_schedule(
                            **base_solver_args,
                            max_time_seconds=max(5, min(int(time_budget), int(remaining_seconds))),
                            optimize_for_fairness=True,
                            plan_strategy=strategy,
                            random_seed=base_seed + seed_offset + int(st.session_state.get("generation_run_number", 0)) * 997,
                            deterministic_search=False,
                            max_shortage_penalty=allowed_shortage_penalty,
                            assignment_hint=best_plan.get("schedule", {}),
                        )
                        if not candidate_schedule:
                            continue
                        if st.session_state.replacement_rest_enabled:
                            candidate_schedule, candidate_metrics, candidate_open_rest_notes = add_compensatory_rest_days(
                                candidate_schedule,
                                candidate_metrics,
                                days,
                                holidays,
                                shift_hours_by_code,
                                st.session_state.replacement_rest_scope,
                                bool(st.session_state.compensatory_rest_counts_as_hours),
                                source_hours_already_counted=True,
                                employees=planning_employees,
                                vacation_weekend_policy=st.session_state.vacation_weekend_policy,
                            )
                        else:
                            candidate_open_rest_notes = []
                        if st.session_state.night_credit_mode != "Keine Nachtgutschrift":
                            candidate_metrics = apply_night_credit_hours(
                                candidate_schedule,
                                candidate_metrics,
                                night_shifts,
                                float(st.session_state.night_credit_hours),
                                counts_as_hours=st.session_state.night_credit_mode == "Nachtgutschrift als Dienststunden",
                            )
                        candidate_rule_checks = validate_schedule_rules(
                            schedule=candidate_schedule,
                            metrics=candidate_metrics,
                            employees=planning_employees,
                            days=days,
                            night_shifts=night_shifts,
                            shifts=shifts,
                            holidays=holidays,
                            daily_requirements=daily_requirements,
                            shift_df=st.session_state.shifts_df,
                            shift_minutes_by_code=shift_minutes_by_code,
                            shift_time_by_code=shift_time_by_code,
                            max_overtime_percent=float(st.session_state.max_overtime_percent),
                            max_overtime_hours=float(st.session_state.max_overtime_hours),
                            max_undertime_percent=float(st.session_state.max_undertime_percent),
                            max_undertime_hours=float(st.session_state.max_undertime_hours),
                            block_night_before_wish_free=bool(st.session_state.block_night_before_wish_free),
                            previous_assignments=previous_assignments_current,
                            open_shift_codes=open_shift_codes,
                            shift_priority_by_code=shift_priority_by_code,
                            vacation_weekend_policy=st.session_state.vacation_weekend_policy,
                            legal_profile=st.session_state.legal_profile,
                            daily_max_work_hours=float(st.session_state.daily_max_work_hours),
                            weekly_average_max_hours=float(st.session_state.weekly_average_max_hours),
                            weekly_average_period_weeks=int(st.session_state.weekly_average_period_weeks),
                            weekly_rest_hours=float(st.session_state.weekly_rest_hours),
                            reduced_weekly_rest_hours=float(st.session_state.reduced_weekly_rest_hours),
                            allow_reduced_weekly_rest=bool(st.session_state.allow_reduced_weekly_rest),
                            saved_schedules=st.session_state.saved_schedules,
                        )
                        if any(check.get("Status") == "Fehler" for check in candidate_rule_checks):
                            continue
                        candidate_quality_score = plan_quality_score(
                            candidate_schedule,
                            candidate_metrics,
                            days,
                            daily_requirements,
                            st.session_state.shifts_df,
                            open_shift_codes,
                            shift_priority_by_code,
                            selected_optimization_mode,
                        )
                        candidate_plan = {
                            "key": fixed_plan_key,
                            "year": int(selected_year),
                            "month": selected_month,
                            "status": candidate_status,
                            "schedule": candidate_schedule,
                            "metrics": candidate_metrics,
                            "open_rest_notes": candidate_open_rest_notes,
                            "rule_checks": candidate_rule_checks,
                            "replacement_rest_enabled": bool(st.session_state.replacement_rest_enabled),
                            "replacement_rest_scope": st.session_state.replacement_rest_scope,
                            "counts_rest_as_hours": (
                                bool(st.session_state.replacement_rest_enabled)
                                and bool(st.session_state.compensatory_rest_counts_as_hours)
                            ),
                            "night_credit_mode": st.session_state.night_credit_mode,
                            "night_credit_hours": float(st.session_state.night_credit_hours),
                            "vacation_counts_as_hours": True,
                            "vacation_weekend_policy": st.session_state.vacation_weekend_policy,
                            "max_overtime_percent": float(st.session_state.max_overtime_percent),
                            "max_overtime_hours": float(st.session_state.max_overtime_hours),
                            "max_undertime_percent": float(st.session_state.max_undertime_percent),
                            "max_undertime_hours": float(st.session_state.max_undertime_hours),
                            "block_night_before_wish_free": bool(st.session_state.block_night_before_wish_free),
                            "pause_policy": st.session_state.pause_policy,
                            "pause_threshold_hours": float(st.session_state.pause_threshold_hours),
                            "pause_duration_minutes": int(st.session_state.pause_duration_minutes),
                            "time_account_usage": st.session_state.time_account_usage,
                            "open_shift_codes": open_shift_codes,
                            "shifts": shifts,
                            "night_shifts": night_shifts,
                            "plan_optimization_mode": selected_optimization_mode,
                            "calculation_mode": selected_calculation_mode,
                            "cache_key": current_cache_key,
                            "quality_score": candidate_quality_score,
                        }
                        candidate_rank = plan_comparison_key(
                            candidate_schedule,
                            candidate_metrics,
                            days,
                            daily_requirements,
                            st.session_state.shifts_df,
                            open_shift_codes,
                            shift_priority_by_code,
                            selected_optimization_mode,
                            selected_calculation_mode,
                            candidate_status,
                        )
                        if candidate_rank > best_rank:
                            best_plan = candidate_plan
                            best_rank = candidate_rank
                            best_shortage_penalty = schedule_shortage_penalty(
                                candidate_schedule,
                                days,
                                daily_requirements,
                                st.session_state.shifts_df,
                                open_shift_codes,
                                shift_priority_by_code,
                            )
                            allowed_shortage_penalty = allowed_shortage_penalty_for_mode(
                                selected_optimization_mode,
                                best_shortage_penalty,
                            )
                            improved = True
                            render_generation_preview(
                                improvement_preview,
                                f"{label} hat eine bessere Variante gefunden.",
                                candidate_schedule,
                                candidate_metrics,
                                days,
                                planning_employees,
                                daily_requirements,
                                st.session_state.shifts_df,
                                open_shift_codes,
                                shift_priority_by_code,
                                score=candidate_quality_score,
                                status=candidate_status,
                                working=True,
                            )
                improvement_progress.empty()
                improvement_text.empty()
                improvement_preview.empty()
                if improved:
                    cache_best_plan = better_plan_payload(
                        st.session_state.best_plan_cache.get(current_cache_key),
                        best_plan,
                        days=days,
                        daily_requirements=daily_requirements,
                        shift_df=st.session_state.shifts_df,
                        open_shift_codes=open_shift_codes,
                        shift_priority_by_code=shift_priority_by_code,
                    )
                    st.session_state.best_plan_cache[current_cache_key] = cache_best_plan
                    save_best_plan_cache(st.session_state.best_plan_cache)
                    st.session_state.generated_plan = copy.deepcopy(cache_best_plan)
                    st.session_state.generated_plan["key"] = fixed_plan_key
                    after_stats = visible_plan_stats(st.session_state.generated_plan)
                    st.session_state.last_improvement_message = (
                        "Plan weiter optimiert: "
                        f"Zufriedenheit {format_display_hours(round(float(before_stats['satisfaction']), 1))} % → "
                        f"{format_display_hours(round(float(after_stats['satisfaction']), 1))} %, "
                        f"Warnungen {int(before_stats['warnings'])} → {int(after_stats['warnings'])}, "
                        f"offene Dienste {int(before_stats['open'])} → {int(after_stats['open'])}."
                    )
                else:
                    st.session_state.last_improvement_message = (
                        "Weiter optimiert, aber keine bessere Variante gefunden. "
                        "Der bisherige Plan wurde unverändert behalten."
                    )
                if improvement_timed_out:
                    st.session_state.last_improvement_message += (
                        " Das Zeitfenster wurde ausgeschöpft; der beste bisherige Plan bleibt erhalten."
                    )
                st.rerun()
        with save_right:
            if st.button("Entwurf verwerfen", width="stretch"):
                st.session_state.generated_plan = None
                st.rerun()
        render_plan_result(
            pending_plan["schedule"],
            pending_plan["metrics"],
            days,
            planning_employees,
            holidays,
            daily_requirements,
            st.session_state.shifts_df,
            fixed=False,
            open_rest_notes=pending_plan.get("open_rest_notes", []),
            rule_checks=pending_plan.get("rule_checks", []),
            open_shift_codes=[],
            shift_priority_by_code=shift_priority_by_code,
            solver_status=pending_plan.get("status"),
            calculation_mode=pending_plan.get("calculation_mode"),
            shifts=shifts,
            night_shifts=night_shifts,
            shift_minutes_by_code=shift_minutes_by_code,
            shift_time_by_code=shift_time_by_code,
            previous_assignments=previous_assignments_current,
        )
    elif saved_plan:
        render_plan_result(
            saved_plan["schedule"],
            saved_plan["metrics"],
            days,
            planning_employees,
            holidays,
            daily_requirements,
            st.session_state.shifts_df,
            fixed=True,
            open_rest_notes=saved_plan.get("open_rest_notes", []),
            rule_checks=saved_plan.get("rule_checks", []),
            open_shift_codes=[],
            shift_priority_by_code=shift_priority_by_code,
            solver_status=saved_plan.get("status"),
            calculation_mode=saved_plan.get("calculation_mode"),
            shifts=shifts,
            night_shifts=night_shifts,
            shift_minutes_by_code=shift_minutes_by_code,
            shift_time_by_code=shift_time_by_code,
            previous_assignments=previous_assignments_current,
        )
    else:
        st.info("Prüfe bei Bedarf die Einstellungen und klicke dann auf 'Dienstplan generieren'.")

with help_tab:
    st.subheader("Hilfe & Prüflogik")
    st.caption("Hier liegen die Erklärungen und Vorprüfungen, damit der Dienstplan-Tab als ruhige Arbeitsfläche bleibt.")

    with st.expander("Feste Prüfszenarien und Ampeln", expanded=True):
        st.caption(
            "Diese drei Prüfszenarien bewerten die aktuelle Eingabe vor dem Generieren. "
            "Sie ersetzen nicht die Solver-Prüfung, zeigen aber früh, wo es wahrscheinlich eng wird."
        )
        st.dataframe(germanize_dataframe(scenario_df), width="stretch", hide_index=True)

    with st.expander("Planungsablauf", expanded=True):
        st.caption("Diese Reihenfolge hilft, damit NutzerInnen nicht raten müssen, was als Nächstes zu tun ist.")
        st.dataframe(germanize_dataframe(workflow_df), width="stretch", hide_index=True)

    with st.expander("Wie die Planung entscheidet", expanded=False):
        st.markdown(
            """
            - Globale Regeln wie Überstunden, Minusstunden und Ausgleich liegen im Reiter Einstellungen.
            - Ob ein Dienst offen bleiben darf, steuert die Priorität der Dienstform im Reiter Dienstformen & Ressourcen.
            - Das aktuelle Optimierungsziel ist: **{optimization_mode}**.
            - Für gleiche Eingaben wird der beste bekannte Entwurf stabil wiederverwendet.
            """.format(
                optimization_mode=html.escape(
                    normalize_plan_optimization_mode(st.session_state.plan_optimization_mode)
                )
            )
        )

    with st.expander("Aktive Rechtsleitplanken", expanded=False):
        st.caption("Kurzfassung als Planungsleitplanke, keine Rechtsberatung. KV, Betriebsvereinbarung und Berufsgruppe können strengere Regeln enthalten.")
        st.dataframe(
            germanize_dataframe(
                legal_guardrail_dataframe(
                    legal_profile=st.session_state.legal_profile,
                    daily_max_work_hours=float(st.session_state.daily_max_work_hours),
                    weekly_average_max_hours=float(st.session_state.weekly_average_max_hours),
                    weekly_average_period_weeks=int(st.session_state.weekly_average_period_weeks),
                    weekly_rest_hours=float(st.session_state.weekly_rest_hours),
                    reduced_weekly_rest_hours=float(st.session_state.reduced_weekly_rest_hours),
                    allow_reduced_weekly_rest=bool(st.session_state.allow_reduced_weekly_rest),
                    replacement_rest_kind=st.session_state.replacement_rest_kind,
                    replacement_rest_scope=st.session_state.replacement_rest_scope,
                    vacation_weekend_policy=st.session_state.vacation_weekend_policy,
                    night_credit_mode=st.session_state.night_credit_mode,
                    night_credit_hours=float(st.session_state.night_credit_hours),
                    time_account_usage=st.session_state.time_account_usage,
                    pause_policy=st.session_state.pause_policy,
                    pause_threshold_hours=float(st.session_state.pause_threshold_hours),
                    pause_duration_minutes=int(st.session_state.pause_duration_minutes),
                )
            ),
            width="stretch",
            hide_index=True,
        )


