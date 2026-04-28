        color = colors.get(shift_code, FREE_SHIFT_COLOR)
        border = " border: 2px solid #ef4444;" if "WF" in value_text.split(" ") else ""
        return f"background-color: {color}; text-align: center; font-weight: 700;{border}"

    day_columns = [column for column in df.columns if column not in {"Mitarbeiter", "Soll h", "Ist h", "+/- h"}]
    return df.style.map(color_shift, subset=day_columns)


def employees_dataframe(employees: list[Employee]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Name": e.name,
                "Qualifikation": e.qualification,
                "Wochenstunden-Ziel": e.weekly_hours_target,
                "Max. Dienste/Woche": e.max_shifts_per_week,
                "Max. Naechte/Monat": e.max_nights_per_month,
                "Gerne Nacht": "ja" if e.likes_nights else "nein",
                "Nur Doppelnaechte": "ja" if e.double_nights_only else "nein",
                "Frei nach Nacht": e.rest_after_night,
                "Wochenende frei": "ja" if e.prefers_weekends_off else "nein",
                "Prio Nacht": priority_label(e.night_priority),
                "Prio Doppelnaechte": priority_label(e.double_night_priority),
                "Prio frei nach Nacht": priority_label(e.rest_priority),
                "Prio Wochenende": priority_label(e.weekend_priority),
                "Prio Wunschfrei": priority_label(e.wish_free_priority),
                "Wunschfrei-Tage": ", ".join(str(day + 1) for day in e.blocked_days) or "-",
            }
            for e in employees
        ]
    )


def editor_dataframe(employees: list[Employee]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Name": e.name,
                "Qualifikation": e.qualification,
                "Wochenstunden": e.weekly_hours_target,
                "Max. Dienste/Woche": e.max_shifts_per_week,
                "Max. Naechte/Monat": e.max_nights_per_month,
                "Gerne Nacht": e.likes_nights,
                "Nur Doppelnaechte": e.double_nights_only,
                "Frei nach Nacht": e.rest_after_night,
                "Wochenende frei": e.prefers_weekends_off,
                "Prio Nacht": priority_label(e.night_priority),
                "Prio Doppelnaechte": priority_label(e.double_night_priority),
                "Prio frei nach Nacht": priority_label(e.rest_priority),
                "Prio Wochenende": priority_label(e.weekend_priority),
                "Prio Wunschfrei": priority_label(e.wish_free_priority),
                "Wunschfrei-Tage": ", ".join(str(day + 1) for day in e.blocked_days),
            }
            for e in employees
        ]
    )


def normalize_employee_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    defaults = {
        "Name": "",
        "Qualifikation": "Pflege",
        "Wochenstunden": 30,
        "Max. Dienste/Woche": 4,
        "Max. Naechte/Monat": 4,
        "Gerne Nacht": False,
        "Nur Doppelnaechte": False,
        "Frei nach Nacht": 1,
        "Wochenende frei": True,
        "Prio Nacht": DEFAULT_PRIORITY_LABEL,
        "Prio Doppelnaechte": DEFAULT_PRIORITY_LABEL,
        "Prio frei nach Nacht": DEFAULT_PRIORITY_LABEL,
        "Prio Wochenende": DEFAULT_PRIORITY_LABEL,
        "Prio Wunschfrei": "1 - muss immer zutreffen",
        "Wunschfrei-Tage": "",
    }
    if "Wunschfrei-Tage" not in normalized.columns and "Gesperrte Tage" in normalized.columns:
        normalized["Wunschfrei-Tage"] = normalized["Gesperrte Tage"]
    if "Prio Nacht" not in normalized.columns and "Prioritaet" in normalized.columns:
        normalized["Prio Nacht"] = normalized["Prioritaet"].map(priority_label)
        normalized["Prio Doppelnaechte"] = normalized["Prioritaet"].map(priority_label)
        normalized["Prio frei nach Nacht"] = normalized["Prioritaet"].map(priority_label)
        normalized["Prio Wochenende"] = normalized["Prioritaet"].map(priority_label)
        normalized["Prio Wunschfrei"] = "1 - muss immer zutreffen"

    for column, default in defaults.items():
        if column not in normalized.columns:
            normalized[column] = default

    normalized = normalized[list(defaults.keys())]
    for column in [
        "Prio Nacht",
        "Prio Doppelnaechte",
        "Prio frei nach Nacht",
        "Prio Wochenende",
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
        try:
            day_number = int(part)
        except ValueError:
            continue
        if day_number > 0:
            blocked_days.append(day_number - 1)
    return tuple(sorted(set(blocked_days)))


def employees_from_editor(df: pd.DataFrame) -> list[Employee]:
    employees = []
    for _, row in df.fillna("").iterrows():
        name = str(row.get("Name", "")).strip()
        if not name:
            continue
        employees.append(
            Employee(
                name=name,
                qualification=str(row.get("Qualifikation", "Pflege")).strip() or "Pflege",
                weekly_hours_target=max(1, int(row.get("Wochenstunden", 30) or 30)),
                max_shifts_per_week=max(1, int(row.get("Max. Dienste/Woche", 5) or 5)),
                max_nights_per_month=max(0, int(row.get("Max. Naechte/Monat", 4) or 4)),
                likes_nights=bool(row.get("Gerne Nacht", False)),
                double_nights_only=bool(row.get("Nur Doppelnaechte", False)),
                rest_after_night=int(row.get("Frei nach Nacht", 1) or 1),
                prefers_weekends_off=bool(row.get("Wochenende frei", False)),
                night_priority=priority_value(row.get("Prio Nacht", DEFAULT_PRIORITY_LABEL)),
                double_night_priority=priority_value(row.get("Prio Doppelnaechte", DEFAULT_PRIORITY_LABEL)),
                rest_priority=priority_value(row.get("Prio frei nach Nacht", DEFAULT_PRIORITY_LABEL)),
                weekend_priority=priority_value(row.get("Prio Wochenende", DEFAULT_PRIORITY_LABEL)),
                wish_free_priority=priority_value(row.get("Prio Wunschfrei", "1 - muss immer zutreffen")),
                blocked_days=parse_blocked_days(row.get("Wunschfrei-Tage", row.get("Gesperrte Tage", ""))),
            )
        )
    return employees


def add_employee_row() -> None:
    next_number = len(st.session_state.employees_df) + 1
    new_row = pd.DataFrame(
        [
            {
                "Name": f"Testperson {next_number}",
                "Qualifikation": "Pflege",
                "Wochenstunden": 30,
                "Max. Dienste/Woche": 4,
                "Max. Naechte/Monat": 4,
                "Gerne Nacht": False,
                "Nur Doppelnaechte": False,
                "Frei nach Nacht": 1,
                "Wochenende frei": True,
                "Prio Nacht": DEFAULT_PRIORITY_LABEL,
                "Prio Doppelnaechte": DEFAULT_PRIORITY_LABEL,
                "Prio frei nach Nacht": DEFAULT_PRIORITY_LABEL,
                "Prio Wochenende": DEFAULT_PRIORITY_LABEL,
                "Prio Wunschfrei": "1 - muss immer zutreffen",
                "Wunschfrei-Tage": "",
            }
        ]
    )
    st.session_state.employees_df = pd.concat(
        [st.session_state.employees_df, new_row], ignore_index=True
    )


def add_shift_row() -> None:
    existing_count = len(st.session_state.shifts_df)
    new_code = f"D{existing_count + 1}"
    new_row = pd.DataFrame(
        [
            {
                "Kuerzel": new_code,
                "Name": f"Zusatzdienst {existing_count + 1}",
                "Stunden": 8,
                "Nacht": False,
                "Prioritaet": 1,
                "Farbe": SHIFT_COLORS[existing_count % len(SHIFT_COLORS)],
            }
        ]
    )
    st.session_state.shifts_df = pd.concat(
        [st.session_state.shifts_df, new_row], ignore_index=True
    )


@st.dialog("Mitarbeiter")
def employee_dialog(row_index: int | None = None) -> None:
    is_edit = row_index is not None
    if is_edit:
        current = st.session_state.employees_df.iloc[row_index].to_dict()
    else:
        next_number = len(st.session_state.employees_df) + 1
        current = {
            "Name": f"Testperson {next_number}",
            "Qualifikation": "Pflege",
            "Wochenstunden": 30,
            "Max. Dienste/Woche": 4,
            "Max. Naechte/Monat": 4,
            "Gerne Nacht": False,
            "Nur Doppelnaechte": False,
            "Frei nach Nacht": 1,
            "Wochenende frei": True,
            "Prio Nacht": DEFAULT_PRIORITY_LABEL,
            "Prio Doppelnaechte": DEFAULT_PRIORITY_LABEL,
            "Prio frei nach Nacht": DEFAULT_PRIORITY_LABEL,
            "Prio Wochenende": DEFAULT_PRIORITY_LABEL,
            "Prio Wunschfrei": "1 - muss immer zutreffen",
            "Wunschfrei-Tage": "",
        }

    with st.form(f"employee_form_{row_index if is_edit else 'new'}"):
        name = st.text_input("Name", value=str(current["Name"]))
        qualification = st.text_input("Qualifikation", value=str(current["Qualifikation"]))
        weekly_hours = st.number_input("Wochenstunden", min_value=1, max_value=60, value=int(current["Wochenstunden"]), step=1)
        max_shifts = st.number_input("Max. Dienste/Woche", min_value=1, max_value=7, value=int(current["Max. Dienste/Woche"]), step=1)
        max_nights = st.number_input("Max. Naechte/Monat", min_value=0, max_value=31, value=int(current["Max. Naechte/Monat"]), step=1)
        likes_nights = st.checkbox("Macht gerne Nachtdienste", value=bool(current["Gerne Nacht"]))
        night_priority = st.selectbox(
            "Prioritaet Nachtwunsch",
            options=list(PRIORITY_LEVELS.keys()),
            index=list(PRIORITY_LEVELS.keys()).index(priority_label(current.get("Prio Nacht", DEFAULT_PRIORITY_LABEL))),
        )
        double_nights = st.checkbox("Nur Doppelnaechte", value=bool(current["Nur Doppelnaechte"]))
        double_night_priority = st.selectbox(
            "Prioritaet Doppelnaechte",
            options=list(PRIORITY_LEVELS.keys()),
            index=list(PRIORITY_LEVELS.keys()).index(priority_label(current.get("Prio Doppelnaechte", DEFAULT_PRIORITY_LABEL))),
        )
        rest_after_night = st.number_input("Frei nach Nacht", min_value=1, max_value=2, value=int(current["Frei nach Nacht"]), step=1)
        rest_priority = st.selectbox(
            "Prioritaet frei nach Nacht",
            options=list(PRIORITY_LEVELS.keys()),
            index=list(PRIORITY_LEVELS.keys()).index(priority_label(current.get("Prio frei nach Nacht", DEFAULT_PRIORITY_LABEL))),
        )
        weekends_off = st.checkbox("Bevorzugt Wochenende frei", value=bool(current["Wochenende frei"]))
        weekend_priority = st.selectbox(
            "Prioritaet Wochenende frei",
            options=list(PRIORITY_LEVELS.keys()),
            index=list(PRIORITY_LEVELS.keys()).index(priority_label(current.get("Prio Wochenende", DEFAULT_PRIORITY_LABEL))),
        )
        wish_free_priority = st.selectbox(
            "Prioritaet Wunschfrei-Tage",
            options=list(PRIORITY_LEVELS.keys()),
            index=list(PRIORITY_LEVELS.keys()).index(priority_label(current.get("Prio Wunschfrei", "1 - muss immer zutreffen"))),
        )

        month_days = build_month_dates(
            int(st.session_state.get("selected_year", date.today().year)),
            int(st.session_state.get("selected_month", date.today().month)),
        )
        day_options = [f"{day.day}: {day_label(day)}" for day in month_days]
        blocked_day_numbers = {day + 1 for day in parse_blocked_days(current.get("Wunschfrei-Tage", current.get("Gesperrte Tage", "")))}
        default_days = [option for option in day_options if int(option.split(":")[0]) in blocked_day_numbers]
        blocked_days_selected = st.multiselect("Wunschfrei-Tage im Monat", options=day_options, default=default_days)

        submitted = st.form_submit_button("Speichern", type="primary")

    if submitted:
        new_row = {
            "Name": name.strip() or "Ohne Name",
            "Qualifikation": qualification,
            "Wochenstunden": weekly_hours,
            "Max. Dienste/Woche": max_shifts,
            "Max. Naechte/Monat": max_nights,
            "Gerne Nacht": likes_nights,
            "Nur Doppelnaechte": double_nights,
            "Frei nach Nacht": rest_after_night,
            "Wochenende frei": weekends_off,
            "Prio Nacht": night_priority,
            "Prio Doppelnaechte": double_night_priority,
            "Prio frei nach Nacht": rest_priority,
            "Prio Wochenende": weekend_priority,
            "Prio Wunschfrei": wish_free_priority,
            "Wunschfrei-Tage": ", ".join(option.split(":")[0] for option in blocked_days_selected),
        }
        if is_edit:
            st.session_state.employees_df.loc[row_index, list(new_row.keys())] = list(new_row.values())
        else:
            st.session_state.employees_df = pd.concat(
                [st.session_state.employees_df, pd.DataFrame([new_row])],
                ignore_index=True,
            )
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
            "Stunden": 8,
            "Nacht": False,
            "Prioritaet": 1,
            "Farbe": SHIFT_COLORS[(next_number - 1) % len(SHIFT_COLORS)],
        }

    with st.form(f"shift_form_{row_index if is_edit else 'new'}"):
        code = st.text_input("Kuerzel", value=str(current["Kuerzel"]), max_chars=4)
        name = st.text_input("Name", value=str(current["Name"]))
        hours = st.number_input("Stunden", min_value=1, max_value=24, value=int(current["Stunden"]), step=1)
        is_night = st.checkbox("Ist Nachtdienst", value=bool(current["Nacht"]))
        shift_priority = st.selectbox(
            "Prioritaet",
            options=list(SHIFT_PRIORITY_LEVELS.keys()),
            index=list(SHIFT_PRIORITY_LEVELS.keys()).index(shift_priority_label(current.get("Prioritaet", 1))),
        )
        color = st.color_picker("Farbe", value=str(current["Farbe"]) or SHIFT_COLORS[0])
        submitted = st.form_submit_button("Speichern", type="primary")

    if submitted:
        new_row = {
            "Kuerzel": code.strip().upper() or f"D{len(st.session_state.shifts_df) + 1}",
            "Name": name.strip() or "Dienst",
            "Stunden": hours,
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
            row[shift_names[shift]] = ", ".join(assigned_by_shift[shift])
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