    }
    div[data-testid="stSidebar"] {
        background: #f8fafc;
    }
    .app-hero {
        border-bottom: 1px solid #e5e7eb;
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
    </style>
    """,
    unsafe_allow_html=True,
)

if "employees_df" not in st.session_state:
    st.session_state.employees_df = editor_dataframe(SAMPLE_EMPLOYEES)
st.session_state.employees_df = normalize_employee_dataframe(st.session_state.employees_df)
if "shifts_df" not in st.session_state:
    st.session_state.shifts_df = default_shift_dataframe()
if "resources_df" not in st.session_state:
    st.session_state.resources_df = default_resource_dataframe()
if "day_requirement_overrides" not in st.session_state:
    st.session_state.day_requirement_overrides = {}

st.markdown(
    """
    <div class="app-hero">
        <h1>KI-Dienstplan MVP</h1>
        <p>Lokale Demo mit editierbaren Testpersonen und OR-Tools-Optimierung.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

current_year = date.today().year
if "selected_year" not in st.session_state:
    st.session_state.selected_year = current_year
if "selected_month" not in st.session_state:
    st.session_state.selected_month = date.today().month

selected_year = int(st.session_state.selected_year)
selected_month = int(st.session_state.selected_month)

days = build_month_dates(int(selected_year), selected_month)
holidays = austrian_holidays(int(selected_year))
st.session_state.shifts_df = shift_definitions_from_editor(st.session_state.shifts_df)
shifts = shift_codes(st.session_state.shifts_df)
night_shifts = night_shift_codes(st.session_state.shifts_df)
shift_priority_by_code = shift_priorities(st.session_state.shifts_df)
shift_hours_by_code = shift_hours(st.session_state.shifts_df)
st.session_state.resources_df = normalize_resource_dataframe(st.session_state.resources_df, shifts)
resource_requirements = resource_requirements_from_editor(st.session_state.resources_df, shifts)
daily_requirements = requirements_for_days(days, holidays, resource_requirements, shifts)
month_key = f"{int(selected_year)}-{selected_month:02d}-{'_'.join(shifts)}"
daily_requirements = apply_day_overrides(daily_requirements, month_key, shifts)
employees = employees_from_editor(st.session_state.employees_df)

employees_tab, planning_tab, resources_tab = st.tabs(
    ["Mitarbeiter & Wuensche", "Dienstplan & Auswertung", "Dienstformen & Ressourcen"]
)

with employees_tab:
    top_left, top_right = st.columns([0.7, 0.3])
    with top_left:
        st.subheader("Mitarbeiter bearbeiten")
        st.caption(
            "Alles sind Fantasiedaten. Wunschfrei-Tage waehlst du im Bearbeiten-Fenster aus."
        )
    with top_right:
        st.write("")
        if st.button("Mitarbeiter hinzufuegen", width="stretch"):
            employee_dialog()

    render_static_table(display_employee_dataframe(st.session_state.employees_df), height_limit=520)
    st.caption(
        "Prioritaeten: 1 muss immer zutreffen, 2 nur im Ausnahmefall verletzen, "
        "3 wenn moeglich beachten, 4 geringe Prioritaet, 5 fair verteilen."
    )

    edit_left, edit_right = st.columns([0.7, 0.3])
    with edit_left:
        employee_options = st.session_state.employees_df["Name"].tolist()
        selected_employee = st.selectbox("Mitarbeiter auswaehlen", options=employee_options)
    with edit_right:
        st.write("")
        if st.button("Mitarbeiter bearbeiten", width="stretch", disabled=not employee_options):
            selected_index = employee_options.index(selected_employee)
            employee_dialog(selected_index)

    employees = employees_from_editor(st.session_state.employees_df)

    employee_cols = st.columns(4)
    employee_cols[0].metric("Mitarbeiter", len(employees))
    employee_cols[1].metric("Wunschfrei-Tage", sum(len(employee.blocked_days) for employee in employees))
    employee_cols[2].metric("Nacht-Fans", sum(1 for employee in employees if employee.likes_nights))
    employee_cols[3].metric("Wochenende frei", sum(1 for employee in employees if employee.prefers_weekends_off))

with resources_tab:
    st.subheader("Dienstformen und Ressourcen")
    st.caption(
        "Lege zuerst deine Dienstformen fest. Danach stellst du den Standardbedarf pro Tagesart ein und kannst einzelne Tage manuell ueberschreiben."
    )

    shift_top_left, shift_top_right = st.columns([0.7, 0.3])
    with shift_top_left:
        st.markdown("**Dienstformen**")
    with shift_top_right:
        if st.button("Dienstform hinzufuegen", width="stretch"):
            shift_dialog()

    render_static_table(display_shift_dataframe(st.session_state.shifts_df))
    st.caption(
        "Dienstform-Prioritaet: 1 muss immer besetzt werden, "
        "2 sollte besetzt sein, 3 nur wenn genug Mitarbeiter vorhanden sind."
    )

    shift_edit_left, shift_edit_right = st.columns([0.7, 0.3])
    with shift_edit_left:
        shift_options = [
            f"{row['Kuerzel']} - {row['Name']}" for _, row in st.session_state.shifts_df.iterrows()
        ]
        selected_shift = st.selectbox("Dienstform auswaehlen", options=shift_options)
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
        selected_day_type = st.selectbox("Tagesart auswaehlen", options=DAY_TYPE_ORDER)
    with resource_edit_right:
        st.write("")
        if st.button("Standardbedarf bearbeiten", width="stretch"):
            resource_dialog(selected_day_type, shifts)

    resource_requirements = resource_requirements_from_editor(st.session_state.resources_df, shifts)
    daily_requirements = requirements_for_days(days, holidays, resource_requirements, shifts)
    daily_requirements = apply_day_overrides(daily_requirements, month_key, shifts)

    st.subheader("Kalenderpruefung")
    st.caption("Hier kannst du einzelne Tage manuell anpassen, wenn an einem Datum mehr oder weniger Dienste gebraucht werden.")
    day_requirements_df = day_requirements_dataframe(days, holidays, daily_requirements, shifts)
    render_static_table(day_requirements_df, height_limit=520)

    day_edit_left, day_edit_right = st.columns([0.7, 0.3])
    with day_edit_left:
        day_options = day_requirements_df["Tag"].tolist()
        selected_day_label = st.selectbox("Tag auswaehlen", options=day_options)
    with day_edit_right:
        st.write("")
        if st.button("Tagesbedarf bearbeiten", width="stretch"):
            selected_day_index = day_options.index(selected_day_label)
            current_values = {
                shift: daily_requirements[(selected_day_index, shift)] for shift in shifts
            }
            day_requirement_dialog(selected_day_index, month_key, shifts, current_values)

with planning_tab:
    st.subheader("Dienstplan generieren")
    plan_left, plan_right = st.columns([0.35, 0.65])
    with plan_left:
        selected_year_input = st.number_input(
            "Jahr",
            min_value=current_year - 1,
            max_value=current_year + 3,
            value=selected_year,
            step=1,
        )
    with plan_right:
        selected_month_label = st.selectbox(
            "Monat",
            options=[f"{month:02d} - {MONTH_NAMES[month]}" for month in range(1, 13)],
            index=selected_month - 1,
        )
    new_selected_month = int(selected_month_label.split(" - ")[0])
    if int(selected_year_input) != selected_year or new_selected_month != selected_month:
        st.session_state.selected_year = int(selected_year_input)
        st.session_state.selected_month = new_selected_month
        st.rerun()

    st.caption(f"Geplant wird immer ein ganzer Monat: {MONTH_NAMES[selected_month]} {int(selected_year)}.")

    total_required = sum(daily_requirements.values())
    holiday_count = sum(1 for current_day in days if current_day in holidays)
    sunday_or_holiday_count = sum(1 for current_day in days if day_type(current_day, holidays) == "Sonntag/Feiertag")

    metric_cols = st.columns(4)
    metric_cols[0].metric("Kalendertage", len(days))
    metric_cols[1].metric("Benoetigte Dienste", total_required)
    metric_cols[2].metric("Sonntag/Feiertag", sunday_or_holiday_count)
    metric_cols[3].metric("Feiertage", holiday_count)

    generate = st.button("Dienstplan generieren", type="primary", width="stretch")

    if generate:
        max_shift_demand = max(daily_requirements.values()) if daily_requirements else 0
        max_day_demand = max(
            sum(daily_requirements.get((d, shift), 0) for shift in shifts)
            for d in range(len(days))
        )
        if len(employees) < max_shift_demand or len(employees) < max_day_demand:
            st.error("Es gibt zu wenige Mitarbeiter fuer den hoechsten Tages- oder Schichtbedarf.")
            st.stop()

        with st.spinner("Dienstplan wird optimiert..."):
            status, schedule, metrics = solve_schedule(
                employees,
                days,
                shifts=shifts,
                night_shifts=night_shifts,
                daily_requirements=daily_requirements,
                holidays=holidays,
                shift_priority_by_code=shift_priority_by_code,
                shift_hours_by_code=shift_hours_by_code,
            )

        if not schedule:
            st.error("Es wurde kein gueltiger Plan gefunden.")
            st.warning(
                "Tipp: Mehr Mitarbeiter hinzufuegen, Ressourcenbedarf reduzieren, Sperrtage reduzieren oder Maximalwerte lockern."
            )
        else:
            if status == "OPTIMAL":
                st.success("Gueltiger Dienstplan gefunden.")
            else:
                st.warning("Gueltiger Dienstplan gefunden, aber nicht garantiert optimal.")

            metrics_df = pd.DataFrame.from_dict(metrics, orient="index").reset_index(names="Name")
            total_violations = int(metrics_df["Verletzte weiche Wuensche"].sum())

            summary_cols = st.columns(4)
            summary_cols[0].metric("Geplante Dienste", int(metrics_df["Dienste"].sum()))
            summary_cols[1].metric("Nachtdienste", int(metrics_df["Nachtdienste"].sum()))
            summary_cols[2].metric("Wochenenden/Feiertage", int(metrics_df["Wochenenddienste"].sum()))
            summary_cols[3].metric("Verletzte Wuensche", total_violations)

            employee_tab, calendar_tab, metrics_tab = st.tabs(
                ["Mitarbeiteransicht", "Kalenderansicht", "Auswertung"]
            )

            with employee_tab:
                df = schedule_dataframe(schedule, days, employees, metrics)
                employee_table_height = 90 + (len(df) + 1) * 38
                st.dataframe(style_schedule(df, st.session_state.shifts_df), width="stretch", height=employee_table_height)

            with calendar_tab:
                daily_df = daily_coverage_dataframe(
                    schedule,
                    days,
                    holidays,
                    daily_requirements,
                    st.session_state.shifts_df,
                )
                for week_start in range(0, len(daily_df), 7):
                    week_number = week_start // 7 + 1
                    st.markdown(f"**Monatswoche {week_number}**")
                    st.dataframe(
                        style_daily_calendar(daily_df.iloc[week_start : week_start + 7], st.session_state.shifts_df),
                        width="stretch",
                        hide_index=True,
                    )

            with metrics_tab:
                st.dataframe(metrics_df, width="stretch", hide_index=True)
                st.caption(
                    "Sollstunden werden anteilig fuer den geplanten Monat berechnet. "
                    "Plus/Minus zeigt die Abweichung vom fairen Monatsziel."
                )

            st.subheader("Warnungen und Hinweise")
            if total_violations == 0:
                st.info("Alle ausgewerteten weichen Wuensche wurden erfuellt.")
            else:
                st.info(
                    f"Es gibt {total_violations} verletzte weiche Wuensche. "
                    "Das ist bei knappen Personalplaenen normal und kann durch mehr Personal oder weichere Vorgaben verbessert werden."
                )
                violation_rows = metrics_df[
                    metrics_df["Verletzte weiche Wuensche"] > 0
                ][["Name", "Verletzte weiche Wuensche", "Welche Wuensche verletzt"]]
                st.markdown("**Konkret betroffene MitarbeiterInnen**")
                st.dataframe(violation_rows, width="stretch", hide_index=True)
    else:
        st.info("Waehle Monat und Ressourcen, pruefe die Mitarbeiter und klicke dann auf 'Dienstplan generieren'.")