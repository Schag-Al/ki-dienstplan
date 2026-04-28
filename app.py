from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from io import BytesIO, StringIO

import pandas as pd
import streamlit as st
from ortools.sat.python import cp_model

APP_VERSION = "0.1.4"
st.set_page_config(page_title="KI-Dienstplan", layout="wide")

MONTH_NAMES = {
    1: "Januar", 2: "Februar", 3: "Maerz", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
DAY_TYPES = ["Werktag", "Samstag", "Sonntag/Feiertag"]
SHIFT_COLORS = ["#bbf7d0", "#bae6fd", "#fed7aa", "#fde68a", "#c7d2fe", "#fecdd3", "#ccfbf1", "#e9d5ff"]
FREE_COLOR = "#f1f5f9"


@dataclass(frozen=True)
class Employee:
    name: str
    role: str
    weekly_hours: int
    max_shifts_week: int
    max_nights_month: int
    can_night: bool
    only_double_nights: bool
    rest_after_night: int
    weekend_preference: bool
    blocked_days: tuple[int, ...]


def default_employees() -> pd.DataFrame:
    return pd.DataFrame([
        {"Name": "Martina Hofer", "Bereich": "Leitung / Buero - nicht dienstplanrelevant", "Wochenstunden": 1, "Max Dienste/Woche": 1, "Max Naechte/Monat": 0, "Nachtdienst": False, "Nur Doppelnaechte": False, "Frei nach Nacht": 1, "Wochenende frei": True, "Wunschfrei": "1-31"},
        {"Name": "Sabine Gruber", "Bereich": "Krankenstand ganzer Monat", "Wochenstunden": 1, "Max Dienste/Woche": 1, "Max Naechte/Monat": 0, "Nachtdienst": False, "Nur Doppelnaechte": False, "Frei nach Nacht": 1, "Wochenende frei": True, "Wunschfrei": "1-31"},
        {"Name": "Julia Berger", "Bereich": "Pflege - keine Nacht", "Wochenstunden": 32, "Max Dienste/Woche": 4, "Max Naechte/Monat": 0, "Nachtdienst": False, "Nur Doppelnaechte": False, "Frei nach Nacht": 2, "Wochenende frei": True, "Wunschfrei": "4,5"},
        {"Name": "Lukas Steiner", "Bereich": "Pflege - keine Nacht", "Wochenstunden": 40, "Max Dienste/Woche": 5, "Max Naechte/Monat": 0, "Nachtdienst": False, "Nur Doppelnaechte": False, "Frei nach Nacht": 2, "Wochenende frei": False, "Wunschfrei": "12"},
        {"Name": "Nadine Leitner", "Bereich": "Pflege - keine Nacht", "Wochenstunden": 30, "Max Dienste/Woche": 4, "Max Naechte/Monat": 0, "Nachtdienst": False, "Nur Doppelnaechte": False, "Frei nach Nacht": 2, "Wochenende frei": True, "Wunschfrei": "8,9"},
        {"Name": "Daniel Novak", "Bereich": "Nur Nachtdienst", "Wochenstunden": 36, "Max Dienste/Woche": 4, "Max Naechte/Monat": 16, "Nachtdienst": True, "Nur Doppelnaechte": True, "Frei nach Nacht": 2, "Wochenende frei": False, "Wunschfrei": "11"},
        {"Name": "Anna Huber", "Bereich": "Pflege", "Wochenstunden": 40, "Max Dienste/Woche": 5, "Max Naechte/Monat": 5, "Nachtdienst": True, "Nur Doppelnaechte": False, "Frei nach Nacht": 2, "Wochenende frei": True, "Wunschfrei": "3,4"},
        {"Name": "Ben Fischer", "Bereich": "Pflege", "Wochenstunden": 40, "Max Dienste/Woche": 5, "Max Naechte/Monat": 8, "Nachtdienst": True, "Nur Doppelnaechte": True, "Frei nach Nacht": 1, "Wochenende frei": False, "Wunschfrei": "18"},
        {"Name": "Clara Winkler", "Bereich": "Pflege", "Wochenstunden": 32, "Max Dienste/Woche": 4, "Max Naechte/Monat": 4, "Nachtdienst": True, "Nur Doppelnaechte": False, "Frei nach Nacht": 2, "Wochenende frei": True, "Wunschfrei": "9,10"},
        {"Name": "David Eder", "Bereich": "Springer", "Wochenstunden": 40, "Max Dienste/Woche": 5, "Max Naechte/Monat": 8, "Nachtdienst": True, "Nur Doppelnaechte": False, "Frei nach Nacht": 1, "Wochenende frei": False, "Wunschfrei": "24"},
        {"Name": "Elif Yilmaz", "Bereich": "Pflege", "Wochenstunden": 36, "Max Dienste/Woche": 4, "Max Naechte/Monat": 4, "Nachtdienst": True, "Nur Doppelnaechte": False, "Frei nach Nacht": 2, "Wochenende frei": True, "Wunschfrei": "15"},
        {"Name": "Felix Brandner", "Bereich": "Pflege", "Wochenstunden": 40, "Max Dienste/Woche": 5, "Max Naechte/Monat": 7, "Nachtdienst": True, "Nur Doppelnaechte": True, "Frei nach Nacht": 1, "Wochenende frei": False, "Wunschfrei": "7"},
        {"Name": "Greta Pichler", "Bereich": "Teamleitung", "Wochenstunden": 32, "Max Dienste/Woche": 4, "Max Naechte/Monat": 3, "Nachtdienst": True, "Nur Doppelnaechte": False, "Frei nach Nacht": 2, "Wochenende frei": True, "Wunschfrei": "21,22"},
        {"Name": "Hannah Lang", "Bereich": "Springer", "Wochenstunden": 24, "Max Dienste/Woche": 3, "Max Naechte/Monat": 5, "Nachtdienst": True, "Nur Doppelnaechte": False, "Frei nach Nacht": 1, "Wochenende frei": False, "Wunschfrei": "13"},
        {"Name": "Ivan Horvat", "Bereich": "Pflege", "Wochenstunden": 40, "Max Dienste/Woche": 5, "Max Naechte/Monat": 6, "Nachtdienst": True, "Nur Doppelnaechte": False, "Frei nach Nacht": 1, "Wochenende frei": False, "Wunschfrei": "26"},
        {"Name": "Laura Klein", "Bereich": "Pflege", "Wochenstunden": 30, "Max Dienste/Woche": 4, "Max Naechte/Monat": 3, "Nachtdienst": True, "Nur Doppelnaechte": False, "Frei nach Nacht": 2, "Wochenende frei": True, "Wunschfrei": "16,17"},
        {"Name": "Marco Seidl", "Bereich": "Pflege", "Wochenstunden": 36, "Max Dienste/Woche": 4, "Max Naechte/Monat": 6, "Nachtdienst": True, "Nur Doppelnaechte": True, "Frei nach Nacht": 2, "Wochenende frei": False, "Wunschfrei": "5"},
        {"Name": "Nora Reiter", "Bereich": "Pflege", "Wochenstunden": 24, "Max Dienste/Woche": 3, "Max Naechte/Monat": 2, "Nachtdienst": True, "Nur Doppelnaechte": False, "Frei nach Nacht": 2, "Wochenende frei": True, "Wunschfrei": "19"},
    ])


def default_shifts() -> pd.DataFrame:
    return pd.DataFrame([
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
    ])


def default_resources() -> pd.DataFrame:
    rows = []
    defaults = {
        "Werktag": {"D19": 1, "D6": 2, "D7": 1, "D8": 2, "D14": 1, "N18": 2, "D15": 0, "D715": 0, "D718": 0, "D614": 0},
        "Samstag": {"D19": 0, "D6": 2, "D7": 0, "D8": 2, "D14": 1, "N18": 2, "D15": 3, "D715": 2, "D718": 1, "D614": 1},
        "Sonntag/Feiertag": {"D19": 0, "D6": 2, "D7": 0, "D8": 2, "D14": 1, "N18": 2, "D15": 3, "D715": 2, "D718": 1, "D614": 1},
    }
    for day_type, values in defaults.items():
        row = {"Tagesart": day_type}
        row.update(values)
        rows.append(row)
    return pd.DataFrame(rows)


def parse_days(value: object) -> tuple[int, ...]:
    result: set[int] = set()
    text = str(value or "").replace(";", ",")
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start, end = [int(x.strip()) for x in part.split("-", 1)]
            except ValueError:
                continue
            result.update(range(max(1, start), min(31, end) + 1))
        else:
            try:
                day = int(part)
            except ValueError:
                continue
            if 1 <= day <= 31:
                result.add(day)
    return tuple(sorted(result))


def month_dates(year: int, month: int) -> list[date]:
    return [date(year, month, day) for day in range(1, calendar.monthrange(year, month)[1] + 1)]


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
    return {
        date(year, 1, 1): "Neujahr", date(year, 1, 6): "Heilige Drei Koenige",
        easter + timedelta(days=1): "Ostermontag", date(year, 5, 1): "Staatsfeiertag",
        easter + timedelta(days=39): "Christi Himmelfahrt", easter + timedelta(days=50): "Pfingstmontag",
        easter + timedelta(days=60): "Fronleichnam", date(year, 8, 15): "Mariae Himmelfahrt",
        date(year, 10, 26): "Nationalfeiertag", date(year, 11, 1): "Allerheiligen",
        date(year, 12, 8): "Mariae Empfaengnis", date(year, 12, 25): "Christtag", date(year, 12, 26): "Stefanitag",
    }


def day_type(day: date, holidays: dict[date, str]) -> str:
    if day in holidays or day.weekday() == 6:
        return "Sonntag/Feiertag"
    if day.weekday() == 5:
        return "Samstag"
    return "Werktag"


def clean_shifts(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().fillna("")
    for col in ["Kuerzel", "Name", "Stunden", "Nacht", "Prioritaet", "Farbe"]:
        if col not in df.columns:
            df[col] = ""
    df = df[["Kuerzel", "Name", "Stunden", "Nacht", "Prioritaet", "Farbe"]]
    df["Kuerzel"] = df["Kuerzel"].astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True).str[:5]
    df = df[df["Kuerzel"] != ""].drop_duplicates("Kuerzel").reset_index(drop=True)
    df["Name"] = df["Name"].astype(str).str.strip().where(df["Name"].astype(str).str.strip() != "", df["Kuerzel"])
    df["Stunden"] = pd.to_numeric(df["Stunden"], errors="coerce").fillna(8).clip(1, 24).astype(int)
    df["Prioritaet"] = pd.to_numeric(df["Prioritaet"], errors="coerce").fillna(1).clip(1, 3).astype(int)
    df["Nacht"] = df["Nacht"].astype(bool)
    df["Farbe"] = df["Farbe"].astype(str).replace("", "#e5e7eb")
    return df


def clean_employees(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().fillna("")
    cols = ["Name", "Bereich", "Wochenstunden", "Max Dienste/Woche", "Max Naechte/Monat", "Nachtdienst", "Nur Doppelnaechte", "Frei nach Nacht", "Wochenende frei", "Wunschfrei"]
    for col in cols:
        if col not in df.columns:
            df[col] = ""
    df = df[cols]
    df["Name"] = df["Name"].astype(str).str.strip()
    df = df[df["Name"] != ""].reset_index(drop=True)
    for col, default, low, high in [
        ("Wochenstunden", 40, 1, 60), ("Max Dienste/Woche", 5, 1, 7),
        ("Max Naechte/Monat", 4, 0, 31), ("Frei nach Nacht", 2, 0, 3),
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(default).clip(low, high).astype(int)
    for col in ["Nachtdienst", "Nur Doppelnaechte", "Wochenende frei"]:
        df[col] = df[col].astype(bool)
    return df


def employees_from_df(df: pd.DataFrame) -> list[Employee]:
    result = []
    for row in clean_employees(df).to_dict("records"):
        result.append(Employee(
            name=str(row["Name"]), role=str(row["Bereich"]), weekly_hours=int(row["Wochenstunden"]),
            max_shifts_week=int(row["Max Dienste/Woche"]), max_nights_month=int(row["Max Naechte/Monat"]),
            can_night=bool(row["Nachtdienst"]), only_double_nights=bool(row["Nur Doppelnaechte"]),
            rest_after_night=int(row["Frei nach Nacht"]), weekend_preference=bool(row["Wochenende frei"]),
            blocked_days=tuple(day - 1 for day in parse_days(row["Wunschfrei"])),
        ))
    return result


def normalize_resources(resources: pd.DataFrame, shift_codes: list[str]) -> pd.DataFrame:
    source = resources.copy().fillna(0)
    if "Tagesart" in source.columns:
        source = source.set_index("Tagesart", drop=False)
    rows = []
    for type_name in DAY_TYPES:
        row = {"Tagesart": type_name}
        for code in shift_codes:
            value = source.loc[type_name, code] if type_name in source.index and code in source.columns else 0
            row[code] = max(0, int(value or 0))
        rows.append(row)
    return pd.DataFrame(rows)


def build_requirements(days: list[date], holidays: dict[date, str], resources: pd.DataFrame, shift_codes: list[str]) -> dict[tuple[int, str], int]:
    resource_map = resources.set_index("Tagesart").to_dict("index")
    return {(i, code): int(resource_map[day_type(day, holidays)].get(code, 0)) for i, day in enumerate(days) for code in shift_codes}


def solve_schedule(employees: list[Employee], days: list[date], shifts: pd.DataFrame, requirements: dict[tuple[int, str], int], holidays: dict[date, str]):
    shift_codes = shifts["Kuerzel"].tolist()
    night_codes = set(shifts.loc[shifts["Nacht"], "Kuerzel"].tolist())
    shift_hours = dict(zip(shifts["Kuerzel"], shifts["Stunden"]))
    shift_priority = dict(zip(shifts["Kuerzel"], shifts["Prioritaet"]))
    model = cp_model.CpModel()
    e_count, d_count = len(employees), len(days)
    x = {(e, d, s): model.NewBoolVar(f"x_{e}_{d}_{s}") for e in range(e_count) for d in range(d_count) for s in shift_codes}
    objective = []

    for d in range(d_count):
        for s in shift_codes:
            demand = int(requirements.get((d, s), 0))
            assigned = sum(x[(e, d, s)] for e in range(e_count))
            if shift_priority.get(s, 1) == 1:
                model.Add(assigned == demand)
            else:
                shortage = model.NewIntVar(0, demand, f"short_{d}_{s}")
                model.Add(assigned + shortage == demand)
                model.Add(assigned <= demand)
                objective.append(shortage * (-120 if shift_priority.get(s) == 2 else -30))

    for e, employee in enumerate(employees):
        for d in range(d_count):
            model.AddAtMostOne(x[(e, d, s)] for s in shift_codes)
            if d in employee.blocked_days:
                for s in shift_codes:
                    model.Add(x[(e, d, s)] == 0)
            if not employee.can_night or "keine nacht" in employee.role.lower():
                for s in night_codes:
                    model.Add(x[(e, d, s)] == 0)
            if "nur nachtdienst" in employee.role.lower():
                for s in shift_codes:
                    if s not in night_codes:
                        model.Add(x[(e, d, s)] == 0)
            if d < d_count - 1:
                for ns in night_codes:
                    for s in shift_codes:
                        if employee.rest_after_night >= 1:
                            model.Add(x[(e, d, ns)] + x[(e, d + 1, s)] <= 1)
            if d < d_count - 2 and employee.rest_after_night >= 2:
                for ns in night_codes:
                    for s in shift_codes:
                        model.Add(x[(e, d, ns)] + x[(e, d + 2, s)] <= 1)
        model.Add(sum(x[(e, d, s)] for d in range(d_count) for s in night_codes) <= employee.max_nights_month)
        for week_start in range(0, d_count, 7):
            model.Add(sum(x[(e, d, s)] for d in range(week_start, min(week_start + 7, d_count)) for s in shift_codes) <= employee.max_shifts_week)
        target = max(1, round(employee.weekly_hours / 40 * sum(requirements.values()) / max(1, e_count)))
        total = sum(x[(e, d, s)] for d in range(d_count) for s in shift_codes)
        over = model.NewIntVar(0, d_count, f"over_{e}")
        under = model.NewIntVar(0, d_count, f"under_{e}")
        model.Add(total - target == over - under)
        objective.extend([over * -2, under * -2])
        if employee.weekend_preference:
            for d, day in enumerate(days):
                if day.weekday() >= 5 or day in holidays:
                    objective.append(sum(x[(e, d, s)] for s in shift_codes) * -3)

    model.Maximize(sum(objective) if objective else 0)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return "Kein gueltiger Plan gefunden", pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    schedule = {employee.name: [] for employee in employees}
    rows = []
    calendar_rows = []
    for e, employee in enumerate(employees):
        row = {"Name": employee.name}
        for d, day in enumerate(days):
            assigned = next((s for s in shift_codes if solver.Value(x[(e, d, s)]) == 1), "Frei")
            row[f"{WEEKDAYS[day.weekday()]} {day.day:02d}"] = assigned
            schedule[employee.name].append(assigned)
        rows.append(row)
    for d, day in enumerate(days):
        row = {"Tag": f"{WEEKDAYS[day.weekday()]} {day.strftime('%d.%m.')}", "Tagesart": day_type(day, holidays), "Feiertag": holidays.get(day, "")}
        for s in shift_codes:
            people = [name for name, assignments in schedule.items() if assignments[d] == s]
            row[s] = ", ".join(people)
        calendar_rows.append(row)
    metrics = []
    for employee in employees:
        planned = [s for s in schedule[employee.name] if s != "Frei"]
        metrics.append({
            "Name": employee.name,
            "Dienste": len(planned),
            "Stunden": sum(int(shift_hours.get(s, 0)) for s in planned),
            "Nachtdienste": sum(1 for s in planned if s in night_codes),
            "Wochenende/Feiertag": sum(1 for d, s in enumerate(schedule[employee.name]) if s != "Frei" and (days[d].weekday() >= 5 or days[d] in holidays)),
            "Wunschfrei verletzt": sum(1 for d in employee.blocked_days if d < len(days) and schedule[employee.name][d] != "Frei"),
        })
    label = "Optimal" if status == cp_model.OPTIMAL else "Gueltig"
    return label, pd.DataFrame(rows), pd.DataFrame(calendar_rows), pd.DataFrame(metrics)


def style_schedule(df: pd.DataFrame, shifts: pd.DataFrame):
    colors = dict(zip(shifts["Kuerzel"], shifts["Farbe"]))
    colors["Frei"] = FREE_COLOR
    def color(value: object) -> str:
        text = str(value)
        if text in colors:
            return f"background-color:{colors[text]}; color:#111827; font-weight:650;"
        return ""
    cols = [c for c in df.columns if c != "Name"]
    return df.style.map(color, subset=cols)


def csv_bytes(df: pd.DataFrame) -> bytes:
    buf = StringIO()
    df.to_csv(buf, index=False, sep=";")
    return buf.getvalue().encode("utf-8-sig")


if "employees_df" not in st.session_state:
    st.session_state.employees_df = default_employees()
if "shifts_df" not in st.session_state:
    st.session_state.shifts_df = default_shifts()
if "resources_df" not in st.session_state:
    st.session_state.resources_df = default_resources()

st.markdown("""
<style>
.block-container { padding-top: 1.4rem; padding-bottom: 2rem; }
div[data-testid="stMetric"] { border:1px solid #e5e7eb; border-radius:8px; padding:12px 14px; background:white; }
</style>
""", unsafe_allow_html=True)

st.title("KI-Dienstplan")
st.caption(f"Online-Version {APP_VERSION} mit editierbaren Mitarbeitern, Dienstformen, Ressourcen und OR-Tools-Optimierung.")

employees_tab, resources_tab, plan_tab = st.tabs(["Mitarbeiter & Wuensche", "Dienstformen & Ressourcen", "Dienstplan & Auswertung"])

with employees_tab:
    st.subheader("Mitarbeiter bearbeiten")
    st.session_state.employees_df = st.data_editor(
        clean_employees(st.session_state.employees_df),
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Nachtdienst": st.column_config.CheckboxColumn("Nachtdienst"),
            "Nur Doppelnaechte": st.column_config.CheckboxColumn("Nur Doppelnaechte"),
            "Wochenende frei": st.column_config.CheckboxColumn("Wochenende frei"),
            "Wunschfrei": st.column_config.TextColumn("Wunschfrei", help="Einzeltage oder Bereiche, z.B. 3,4,18 oder 1-31"),
        },
    )
    people = employees_from_df(st.session_state.employees_df)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mitarbeiter", len(people))
    c2.metric("Wunschfrei-Tage", sum(len(p.blocked_days) for p in people))
    c3.metric("Nachtdienst moeglich", sum(1 for p in people if p.can_night))
    c4.metric("Wochenende frei", sum(1 for p in people if p.weekend_preference))

with resources_tab:
    st.subheader("Dienstformen")
    st.session_state.shifts_df = st.data_editor(
        clean_shifts(st.session_state.shifts_df),
        num_rows="dynamic",
        use_container_width=True,
        column_config={"Nacht": st.column_config.CheckboxColumn("Nacht"), "Farbe": st.column_config.TextColumn("Farbe")},
    )
    shifts = clean_shifts(st.session_state.shifts_df)
    st.subheader("Standardbedarf je Tagesart")
    st.session_state.resources_df = st.data_editor(
        normalize_resources(st.session_state.resources_df, shifts["Kuerzel"].tolist()),
        num_rows="fixed",
        use_container_width=True,
        disabled=["Tagesart"],
    )
    st.caption("Prioritaet Dienstform: 1 muss besetzt werden, 2 sollte besetzt sein, 3 nur wenn genug Personal vorhanden ist.")

with plan_tab:
    year_now = date.today().year
    left, right = st.columns([1, 2])
    with left:
        selected_year = int(st.number_input("Jahr", min_value=year_now - 1, max_value=year_now + 3, value=year_now, step=1))
    with right:
        selected_month_label = st.selectbox("Monat", [f"{m:02d} - {MONTH_NAMES[m]}" for m in range(1, 13)], index=date.today().month - 1)
    selected_month = int(selected_month_label.split(" - ")[0])
    days = month_dates(selected_year, selected_month)
    holidays = austrian_holidays(selected_year)
    shifts = clean_shifts(st.session_state.shifts_df)
    resources = normalize_resources(st.session_state.resources_df, shifts["Kuerzel"].tolist())
    requirements = build_requirements(days, holidays, resources, shifts["Kuerzel"].tolist())
    people = employees_from_df(st.session_state.employees_df)

    total_demand = sum(requirements.values())
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Kalendertage", len(days))
    m2.metric("Benoetigte Dienste", total_demand)
    m3.metric("Mitarbeiter", len(people))
    m4.metric("Feiertage", sum(1 for d in days if d in holidays))

    with st.expander("Tagesbedarf pruefen", expanded=False):
        day_rows = []
        for i, day in enumerate(days):
            row = {"Tag": f"{WEEKDAYS[day.weekday()]} {day.strftime('%d.%m.')}", "Tagesart": day_type(day, holidays), "Feiertag": holidays.get(day, "")}
            for code in shifts["Kuerzel"]:
                row[code] = requirements[(i, code)]
            day_rows.append(row)
        st.dataframe(pd.DataFrame(day_rows), use_container_width=True, hide_index=True)

    if st.button("Dienstplan generieren", type="primary", use_container_width=True):
        if not people or shifts.empty:
            st.error("Bitte Mitarbeiter und Dienstformen anlegen.")
        elif max(requirements.values() or [0]) > len(people):
            st.error("Es gibt zu wenige Mitarbeiter fuer mindestens eine Schicht.")
        else:
            with st.spinner("Dienstplan wird optimiert..."):
                status, schedule_df, calendar_df, metrics_df = solve_schedule(people, days, shifts, requirements, holidays)
            st.session_state.result = (status, schedule_df, calendar_df, metrics_df)

    if "result" in st.session_state:
        status, schedule_df, calendar_df, metrics_df = st.session_state.result
        if schedule_df.empty:
            st.error(status)
        else:
            st.success(f"{status}: Dienstplan wurde erstellt.")
            view_a, view_b, view_c = st.tabs(["Mitarbeiteransicht", "Kalenderansicht", "Auswertung"])
            with view_a:
                st.dataframe(style_schedule(schedule_df, shifts), use_container_width=True, hide_index=True)
                st.download_button("Mitarbeiteransicht als CSV", csv_bytes(schedule_df), "dienstplan.csv", "text/csv", use_container_width=True)
            with view_b:
                st.dataframe(calendar_df, use_container_width=True, hide_index=True)
                st.download_button("Kalenderansicht als CSV", csv_bytes(calendar_df), "dienstplan-kalender.csv", "text/csv", use_container_width=True)
            with view_c:
                st.dataframe(metrics_df, use_container_width=True, hide_index=True)
                st.download_button("Auswertung als CSV", csv_bytes(metrics_df), "dienstplan-auswertung.csv", "text/csv", use_container_width=True)
    else:
        st.info("Daten pruefen und danach den Dienstplan generieren.")
