from __future__ import annotations

import calendar
from datetime import date, timedelta
from io import StringIO

import pandas as pd
import streamlit as st


st.set_page_config(page_title="KI-Dienstplan", layout="wide")

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
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
SHIFT_COLORS = {
    "D6": "#bbf7d0",
    "D8": "#bae6fd",
    "D14": "#fed7aa",
    "D19": "#fde68a",
    "N18": "#c7d2fe",
    "Frei": "#f1f5f9",
}

DEFAULT_EMPLOYEES = pd.DataFrame(
    [
        {"Name": "Anna Huber", "Wochenstunden": 40, "Max Dienste/Woche": 5, "Nachtdienst": True, "Wunschfrei": "3,4"},
        {"Name": "Ben Fischer", "Wochenstunden": 40, "Max Dienste/Woche": 5, "Nachtdienst": True, "Wunschfrei": "18"},
        {"Name": "Clara Winkler", "Wochenstunden": 32, "Max Dienste/Woche": 4, "Nachtdienst": False, "Wunschfrei": "9,10"},
        {"Name": "David Eder", "Wochenstunden": 40, "Max Dienste/Woche": 5, "Nachtdienst": True, "Wunschfrei": "24"},
        {"Name": "Elif Yilmaz", "Wochenstunden": 36, "Max Dienste/Woche": 4, "Nachtdienst": False, "Wunschfrei": "15"},
        {"Name": "Felix Brandner", "Wochenstunden": 40, "Max Dienste/Woche": 5, "Nachtdienst": True, "Wunschfrei": "7"},
        {"Name": "Greta Pichler", "Wochenstunden": 32, "Max Dienste/Woche": 4, "Nachtdienst": False, "Wunschfrei": "21,22"},
        {"Name": "Hannah Lang", "Wochenstunden": 24, "Max Dienste/Woche": 3, "Nachtdienst": True, "Wunschfrei": "13"},
    ]
)

DEFAULT_SHIFTS = pd.DataFrame(
    [
        {"Kuerzel": "D6", "Name": "6-18", "Stunden": 12, "Bedarf Werktag": 2, "Bedarf Wochenende": 2, "Nacht": False},
        {"Kuerzel": "D8", "Name": "8-20", "Stunden": 12, "Bedarf Werktag": 2, "Bedarf Wochenende": 2, "Nacht": False},
        {"Kuerzel": "D14", "Name": "14-22", "Stunden": 8, "Bedarf Werktag": 1, "Bedarf Wochenende": 1, "Nacht": False},
        {"Kuerzel": "D19", "Name": "19-23", "Stunden": 4, "Bedarf Werktag": 1, "Bedarf Wochenende": 0, "Nacht": False},
        {"Kuerzel": "N18", "Name": "18-6", "Stunden": 12, "Bedarf Werktag": 1, "Bedarf Wochenende": 1, "Nacht": True},
    ]
)


def month_dates(year: int, month: int) -> list[date]:
    return [date(year, month, day) for day in range(1, calendar.monthrange(year, month)[1] + 1)]


def parse_days(value: object) -> set[int]:
    days: set[int] = set()
    for part in str(value or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            day = int(part)
        except ValueError:
            continue
        if 1 <= day <= 31:
            days.add(day)
    return days


def clean_employees(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().fillna("")
    expected = ["Name", "Wochenstunden", "Max Dienste/Woche", "Nachtdienst", "Wunschfrei"]
    for column in expected:
        if column not in df.columns:
            df[column] = ""
    df = df[expected]
    df["Name"] = df["Name"].astype(str).str.strip()
    df = df[df["Name"] != ""].reset_index(drop=True)
    df["Wochenstunden"] = pd.to_numeric(df["Wochenstunden"], errors="coerce").fillna(40).clip(1, 60).astype(int)
    df["Max Dienste/Woche"] = pd.to_numeric(df["Max Dienste/Woche"], errors="coerce").fillna(5).clip(1, 7).astype(int)
    df["Nachtdienst"] = df["Nachtdienst"].astype(bool)
    df["Wunschfrei"] = df["Wunschfrei"].astype(str)
    return df


def clean_shifts(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().fillna("")
    expected = ["Kuerzel", "Name", "Stunden", "Bedarf Werktag", "Bedarf Wochenende", "Nacht"]
    for column in expected:
        if column not in df.columns:
            df[column] = ""
    df = df[expected]
    df["Kuerzel"] = df["Kuerzel"].astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True).str[:5]
    df["Name"] = df["Name"].astype(str).str.strip()
    df = df[df["Kuerzel"] != ""].drop_duplicates("Kuerzel").reset_index(drop=True)
    df["Name"] = df["Name"].where(df["Name"] != "", df["Kuerzel"])
    for column in ["Stunden", "Bedarf Werktag", "Bedarf Wochenende"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0).clip(0, 24).astype(int)
    df["Stunden"] = df["Stunden"].clip(1, 24)
    df["Nacht"] = df["Nacht"].astype(bool)
    return df


def demand_for_day(day: date, shifts: pd.DataFrame) -> list[str]:
    weekend = day.weekday() >= 5
    demand_column = "Bedarf Wochenende" if weekend else "Bedarf Werktag"
    required: list[str] = []
    for _, shift in shifts.iterrows():
        required.extend([shift["Kuerzel"]] * int(shift[demand_column]))
    return required


def generate_schedule(employees: pd.DataFrame, shifts: pd.DataFrame, days: list[date]) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    names = employees["Name"].tolist()
    if not names:
        return pd.DataFrame(), pd.DataFrame(), ["Bitte mindestens eine Person anlegen."]
    if shifts.empty:
        return pd.DataFrame(), pd.DataFrame(), ["Bitte mindestens eine Dienstform anlegen."]

    employee_rows = employees.set_index("Name").to_dict("index")
    night_shifts = set(shifts.loc[shifts["Nacht"], "Kuerzel"].tolist())
    shift_hours = dict(zip(shifts["Kuerzel"], shifts["Stunden"]))
    blocked = {name: parse_days(row.get("Wunschfrei")) for name, row in employee_rows.items()}
    assignments = {name: ["Frei" for _ in days] for name in names}
    counts = {name: 0 for name in names}
    weekly_counts = {name: {} for name in names}
    warnings: list[str] = []

    for day_index, current_day in enumerate(days):
        week_key = current_day.isocalendar().week
        already_on_day: set[str] = set()
        required_shifts = demand_for_day(current_day, shifts)

        for shift_code in required_shifts:
            candidates = []
            for name in names:
                row = employee_rows[name]
                if name in already_on_day:
                    continue
                if current_day.day in blocked[name]:
                    continue
                if shift_code in night_shifts and not bool(row["Nachtdienst"]):
                    continue
                used_this_week = weekly_counts[name].get(week_key, 0)
                if used_this_week >= int(row["Max Dienste/Woche"]):
                    continue
                if day_index > 0 and assignments[name][day_index - 1] in night_shifts:
                    continue
                target = max(1, int(row["Wochenstunden"]) // 8)
                candidates.append((counts[name] / target, used_this_week, counts[name], name))

            if not candidates:
                warnings.append(f"{current_day.strftime('%d.%m.%Y')}: {shift_code} konnte nicht besetzt werden.")
                continue

            _, _, _, selected = sorted(candidates)[0]
            assignments[selected][day_index] = shift_code
            already_on_day.add(selected)
            counts[selected] += 1
            weekly_counts[selected][week_key] = weekly_counts[selected].get(week_key, 0) + 1

    schedule_rows = []
    for name in names:
        row = {"Name": name}
        for day_index, current_day in enumerate(days):
            row[f"{WEEKDAYS[current_day.weekday()]} {current_day.day:02d}"] = assignments[name][day_index]
        schedule_rows.append(row)

    metrics_rows = []
    for name in names:
        planned_shifts = [shift for shift in assignments[name] if shift != "Frei"]
        metrics_rows.append(
            {
                "Name": name,
                "Dienste": len(planned_shifts),
                "Stunden": sum(int(shift_hours.get(shift, 0)) for shift in planned_shifts),
                "Nachtdienste": sum(1 for shift in planned_shifts if shift in night_shifts),
                "Wunschfrei verletzt": sum(
                    1 for index, day in enumerate(days) if day.day in blocked[name] and assignments[name][index] != "Frei"
                ),
            }
        )

    return pd.DataFrame(schedule_rows), pd.DataFrame(metrics_rows), warnings


def style_schedule(df: pd.DataFrame):
    def color_cell(value: object) -> str:
        text = str(value)
        color = SHIFT_COLORS.get(text, "#ffffff")
        if text == "Frei":
            return f"background-color:{color}; color:#64748b;"
        return f"background-color:{color}; color:#0f172a; font-weight:700;"

    day_columns = [column for column in df.columns if column != "Name"]
    return df.style.map(color_cell, subset=day_columns)


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    buffer = StringIO()
    df.to_csv(buffer, index=False, sep=";")
    return buffer.getvalue().encode("utf-8-sig")


if "employees" not in st.session_state:
    st.session_state.employees = DEFAULT_EMPLOYEES.copy()
if "shifts" not in st.session_state:
    st.session_state.shifts = DEFAULT_SHIFTS.copy()

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem; }
    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 12px 14px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("KI-Dienstplan")
st.caption("Online-Version fuer gemeinsamen Test und Planung im Browser.")

settings_tab, plan_tab = st.tabs(["Daten bearbeiten", "Dienstplan"])

with settings_tab:
    st.subheader("Mitarbeiter")
    st.session_state.employees = st.data_editor(
        clean_employees(st.session_state.employees),
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Nachtdienst": st.column_config.CheckboxColumn("Nachtdienst"),
            "Wunschfrei": st.column_config.TextColumn("Wunschfrei", help="Tage als Zahlen, z.B. 3,4,18"),
        },
    )

    st.subheader("Dienstformen und Bedarf")
    st.session_state.shifts = st.data_editor(
        clean_shifts(st.session_state.shifts),
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Nacht": st.column_config.CheckboxColumn("Nacht"),
        },
    )

with plan_tab:
    current_year = date.today().year
    left, right = st.columns([1, 2])
    with left:
        selected_year = st.number_input("Jahr", min_value=current_year - 1, max_value=current_year + 3, value=current_year, step=1)
    with right:
        selected_month_label = st.selectbox(
            "Monat",
            [f"{month:02d} - {MONTH_NAMES[month]}" for month in range(1, 13)],
            index=date.today().month - 1,
        )

    selected_month = int(selected_month_label.split(" - ")[0])
    days = month_dates(int(selected_year), selected_month)
    employees = clean_employees(st.session_state.employees)
    shifts = clean_shifts(st.session_state.shifts)

    total_demand = sum(len(demand_for_day(day, shifts)) for day in days)
    metric_cols = st.columns(4)
    metric_cols[0].metric("Mitarbeiter", len(employees))
    metric_cols[1].metric("Tage", len(days))
    metric_cols[2].metric("Benoetigte Dienste", total_demand)
    metric_cols[3].metric("Dienstformen", len(shifts))

    if st.button("Dienstplan generieren", type="primary", use_container_width=True):
        schedule_df, metrics_df, warnings = generate_schedule(employees, shifts, days)
        st.session_state.schedule_df = schedule_df
        st.session_state.metrics_df = metrics_df
        st.session_state.warnings = warnings

    if "schedule_df" in st.session_state and not st.session_state.schedule_df.empty:
        st.success("Dienstplan wurde erstellt.")
        st.dataframe(style_schedule(st.session_state.schedule_df), use_container_width=True, hide_index=True)

        st.subheader("Auswertung")
        st.dataframe(st.session_state.metrics_df, use_container_width=True, hide_index=True)

        col_a, col_b = st.columns(2)
        with col_a:
            st.download_button(
                "Dienstplan als CSV herunterladen",
                data=to_csv_bytes(st.session_state.schedule_df),
                file_name="dienstplan.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with col_b:
            st.download_button(
                "Auswertung als CSV herunterladen",
                data=to_csv_bytes(st.session_state.metrics_df),
                file_name="dienstplan-auswertung.csv",
                mime="text/csv",
                use_container_width=True,
            )

        warnings = st.session_state.get("warnings", [])
        if warnings:
            st.warning("Einige Dienste konnten mit den aktuellen Vorgaben nicht besetzt werden.")
            st.dataframe(pd.DataFrame({"Hinweis": warnings}), use_container_width=True, hide_index=True)
    else:
        st.info("Daten pruefen und danach den Dienstplan generieren.")
