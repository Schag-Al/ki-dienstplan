    return display_df


def display_shift_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    display_df = shift_definitions_from_editor(df).copy()
    display_df["Nacht"] = display_df["Nacht"].map(lambda value: "Ja" if bool(value) else "Nein")
    display_df["Farbe"] = display_df["Farbe"].map(color_swatch)
    return display_df


def render_static_table(df: pd.DataFrame, height_limit: int | None = None) -> None:
    table_df = df.copy().fillna("")
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


def solve_schedule(
    employees: list[Employee],
    days: list[date],
    shifts: list[str],
    night_shifts: list[str],
    daily_requirements: dict[tuple[int, str], int] | None = None,
    holidays: dict[date, str] | None = None,
    shift_priority_by_code: dict[str, int] | None = None,
    shift_hours_by_code: dict[str, int] | None = None,
) -> tuple[str, dict, dict]:
    model = cp_model.CpModel()
    employee_count = len(employees)
    day_count = len(days)
    holidays = holidays or {}
    first_shift = shifts[0] if shifts else ""
    if daily_requirements is None:
        daily_requirements = {(d, shift): 1 for d in range(day_count) for shift in shifts}
    shift_priority_by_code = shift_priority_by_code or {shift: 1 for shift in shifts}
    shift_hours_by_code = shift_hours_by_code or {shift: 8 for shift in shifts}
    objective_terms = []

    x = {}
    for e in range(employee_count):
        for d in range(day_count):
            for shift in shifts:
                x[(e, d, shift)] = model.NewBoolVar(f"x_e{e}_d{d}_{shift}")

    # Harte Regel: Jede echte Schicht wird gemaess Ressourcenbedarf besetzt.
    for d in range(day_count):
        for shift in shifts:
            demand = daily_requirements.get((d, shift), 1)
            assigned = sum(x[(e, d, shift)] for e in range(employee_count))
            shift_priority = shift_priority_by_code.get(shift, 1)
            if shift_priority == 1:
                model.Add(assigned == demand)
            else:
                shortage = model.NewIntVar(0, demand, f"shortage_d{d}_{shift}")
                model.Add(assigned + shortage == demand)
                model.Add(assigned <= demand)
                shortage_penalty = 140 if shift_priority == 2 else 25
                objective_terms.append(shortage * -shortage_penalty)

    # Harte Regeln je Mitarbeiter.
    for e, employee in enumerate(employees):
        for d in range(day_count):
            model.AddAtMostOne(x[(e, d, shift)] for shift in shifts)

            if d in employee.blocked_days:
                if employee.wish_free_priority == 1:
                    for shift in shifts:
                        model.Add(x[(e, d, shift)] == 0)

            if d < day_count - 1 and first_shift:
                for night_shift in night_shifts:
                    model.Add(x[(e, d, night_shift)] + x[(e, d + 1, first_shift)] <= 1)

        model.Add(
            sum(x[(e, d, shift)] for d in range(day_count) for shift in night_shifts)
            <= employee.max_nights_per_month
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
                for night_shift in night_shifts:
                    for rest_day in (d + 1, d + 2):
                        if rest_day < day_count:
                            for shift in shifts:
                                model.Add(x[(e, d, night_shift)] + x[(e, rest_day, shift)] <= 1)

        for week_start in range(0, day_count, 7):
            week_end = min(week_start + 7, day_count)
            model.Add(
                sum(x[(e, d, shift)] for d in range(week_start, week_end) for shift in shifts)
                <= employee.max_shifts_per_week
            )

    weekend_days = weekend_indices(days, holidays)
    total_weekend_required = sum(
        daily_requirements.get((d, shift), 0) for d in weekend_days for shift in shifts
    )
    average_weekend_shifts = max(1, total_weekend_required // employee_count)
    total_required_shifts = sum(daily_requirements.values())
    total_required_hours = sum(
        daily_requirements.get((d, shift), 0) * shift_hours_by_code.get(shift, 8)
        for d in range(day_count)
        for shift in shifts
    )
    total_required_nights = sum(
        daily_requirements.get((d, shift), 0)
        for d in range(day_count)
        for shift in night_shifts
    )
    total_weekly_hours = sum(employee.weekly_hours_target for employee in employees)

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
    night_deviations = []
    weekend_deviations = []

    for e, employee in enumerate(employees):
        night_priority = priority_weight(employee.night_priority)
        double_night_priority = priority_weight(employee.double_night_priority)
        rest_priority = priority_weight(employee.rest_priority)
        weekend_priority = priority_weight(employee.weekend_priority)
        wish_free_priority = priority_weight(employee.wish_free_priority)
        total_shifts = sum(x[(e, d, shift)] for d in range(day_count) for shift in shifts)
        total_hours = sum(
            x[(e, d, shift)] * shift_hours_by_code.get(shift, 8)
            for d in range(day_count)
            for shift in shifts
        )
        employee_night_shifts = sum(x[(e, d, shift)] for d in range(day_count) for shift in night_shifts)
        weekend_shifts = sum(x[(e, d, shift)] for d in weekend_days for shift in shifts)

        employee_night_weight = night_distribution_weight(employee)
        if employee.likes_nights and employee.max_nights_per_month >= 2 and eligible_night_weight > 0:
            preferred_target = round(total_required_nights * employee_night_weight / eligible_night_weight)
            minimum_liked_nights = max(2, round(preferred_target * 0.65))
            minimum_liked_nights = min(employee.max_nights_per_month, minimum_liked_nights)
            model.Add(employee_night_shifts >= minimum_liked_nights)

        employee_weekend_weight = weekend_distribution_weight(employee)
        if eligible_weekend_weight > 0:
            target_weekends = round(total_weekend_required * employee_weekend_weight / eligible_weekend_weight)
        else:
            target_weekends = average_weekend_shifts
        if employee.prefers_weekends_off and employee.weekend_priority <= 3:
            allowed_extra = 1 if employee.weekend_priority == 2 else 2
            model.Add(weekend_shifts <= max(1, target_weekends + allowed_extra))

        # Faire Gesamtverteilung um einen groben Zielwert.
        over_total = model.NewIntVar(0, day_count, f"over_total_e{e}")
        under_total = model.NewIntVar(0, day_count, f"under_total_e{e}")
        target_shifts = round(total_required_shifts * employee.weekly_hours_target / total_weekly_hours)
        model.Add(total_shifts - target_shifts <= over_total)
        model.Add(target_shifts - total_shifts <= under_total)
        objective_terms.extend([over_total * -5, under_total * -5])

        # Stunden sind wichtiger als reine Dienstanzahl: Soll/Ist-Abweichungen fair verteilen.
        target_hours = round(total_required_hours * employee.weekly_hours_target / total_weekly_hours)
        over_hours = model.NewIntVar(0, max(1, total_required_hours), f"over_hours_e{e}")
        under_hours = model.NewIntVar(0, max(1, total_required_hours), f"under_hours_e{e}")
        model.Add(total_hours - target_hours <= over_hours)
        model.Add(target_hours - total_hours <= under_hours)
        abs_hours = model.NewIntVar(0, max(1, total_required_hours), f"abs_hours_e{e}")
        model.AddMaxEquality(abs_hours, [over_hours, under_hours])
        hour_deviations.append(abs_hours)
        objective_terms.extend([over_hours * -120, under_hours * -120, abs_hours * -80])

        # Nachtwunsch.
        if employee.likes_nights:
            objective_terms.append(employee_night_shifts * (night_priority * 10))
        else:
            objective_terms.append(employee_night_shifts * (night_priority * -30))

        # Wochenende fair und bei Wunsch eher frei.
        weekend_under = model.NewIntVar(0, max(1, total_weekend_required), f"weekend_under_e{e}")
        weekend_over = model.NewIntVar(0, max(1, total_weekend_required), f"weekend_over_e{e}")
        weekend_abs = model.NewIntVar(0, max(1, total_weekend_required), f"weekend_abs_e{e}")
        model.Add(weekend_shifts - target_weekends <= weekend_over)
        model.Add(target_weekends - weekend_shifts <= weekend_under)
        model.AddMaxEquality(weekend_abs, [weekend_over, weekend_under])
        weekend_deviations.append(weekend_abs)
        objective_terms.extend([weekend_over * -90, weekend_under * -35, weekend_abs * -40])
        if employee.prefers_weekends_off:
            objective_terms.append(weekend_shifts * (weekend_priority * -45))

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
            else:
                objective_terms.extend([night_over * -180, night_under * -8, night_abs * -45])

        if employee.wish_free_priority > 1 and employee.blocked_days:
            wish_free_assignments = []
            for d in employee.blocked_days:
                if d < day_count:
                    assigned_on_wish_free = sum(x[(e, d, shift)] for shift in shifts)
                    wish_free_assignments.append(assigned_on_wish_free)
                    objective_terms.append(assigned_on_wish_free * (wish_free_priority * -180))
            if employee.wish_free_priority == 2 and wish_free_assignments:
                model.Add(sum(wish_free_assignments) <= 1)

        # Zwei freie Tage nach Nacht werden weich bevorzugt.
        if employee.rest_after_night == 2:
            for d in range(day_count - 2):
                after_two_days = sum(x[(e, d + 2, shift)] for shift in shifts)
                for night_shift in night_shifts:
                    violation = model.NewBoolVar(f"rest2_violation_e{e}_d{d}_{night_shift}")
                    model.Add(after_two_days <= violation).OnlyEnforceIf(x[(e, d, night_shift)])
                    model.Add(violation == 0).OnlyEnforceIf(x[(e, d, night_shift)].Not())
                    objective_terms.append(violation * (rest_priority * -25))

    # Doppelnacht-Wunsch: Einzelne Naechte werden als weiche Verletzung bestraft.
    for e, employee in enumerate(employees):
        if not employee.double_nights_only:
            continue
        lonely_nights_for_employee = []
        for night_shift in night_shifts:
            for d in range(day_count):
                pair_score = []
                if d > 0:
                    pair_score.append(x[(e, d - 1, night_shift)])
                if d < day_count - 1:
                    pair_score.append(x[(e, d + 1, night_shift)])
                if pair_score:
                    paired = model.NewBoolVar(f"paired_night_e{e}_d{d}_{night_shift}")
                    model.AddMaxEquality(paired, pair_score)
                    lonely = model.NewBoolVar(f"soft_lonely_night_e{e}_d{d}_{night_shift}")
                    model.Add(lonely >= x[(e, d, night_shift)] - paired)
                    model.Add(lonely <= x[(e, d, night_shift)])
                    model.Add(lonely <= 1 - paired)
                    lonely_nights_for_employee.append(lonely)
                    objective_terms.append(lonely * (double_night_priority * -220))
                    objective_terms.append(paired * double_night_priority)
        if lonely_nights_for_employee:
            if employee.double_night_priority == 1:
                model.Add(sum(lonely_nights_for_employee) == 0)
            elif employee.double_night_priority == 2:
                model.Add(sum(lonely_nights_for_employee) <= 1)
            elif employee.double_night_priority == 3:
                model.Add(sum(lonely_nights_for_employee) <= 2)

    if hour_deviations:
        max_hour_deviation = model.NewIntVar(0, max(1, total_required_hours), "max_hour_deviation")
        model.AddMaxEquality(max_hour_deviation, hour_deviations)
        model.Add(max_hour_deviation <= 12)
        objective_terms.append(max_hour_deviation * -2000)
    if night_deviations:
        max_night_deviation = model.NewIntVar(0, day_count, "max_night_deviation")
        model.AddMaxEquality(max_night_deviation, night_deviations)
        model.Add(max_night_deviation <= 3)
        objective_terms.append(max_night_deviation * -500)
    if weekend_deviations:
        max_weekend_deviation = model.NewIntVar(0, len(weekend_days), "max_weekend_deviation")
        model.AddMaxEquality(max_weekend_deviation, weekend_deviations)
        model.Add(max_weekend_deviation <= 3)
        objective_terms.append(max_weekend_deviation * -300)

    model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 45
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 7
    solver.parameters.randomize_search = False
    status = solver.Solve(model)
    status_name = solver.StatusName(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return status_name, {}, {}

    schedule = {}
    metrics = {}
    for e, employee in enumerate(employees):
        row = []
        total = nights = weekends = fulfilled = violated = 0
        planned_hours = 0
        violation_details = []
        for d, current_day in enumerate(days):
            assigned = "-"
            for shift in shifts:
                if solver.Value(x[(e, d, shift)]) == 1:
                    assigned = shift
                    total += 1
                    planned_hours += shift_hours_by_code.get(shift, 8)
                    if shift in night_shifts:
                        nights += 1
                    if current_day.weekday() >= 5 or current_day in holidays:
                        weekends += 1
            row.append(assigned)

        if employee.likes_nights:
            fulfilled += nights
            missing_nights = max(0, 2 - nights)
            violated += missing_nights
            if missing_nights:
                violation_details.append(f"wollte gerne Nachtdienste, bekam nur {nights}")
        else:
            fulfilled += max(0, 4 - nights)
            violated += nights
            if nights:
                violation_details.append(f"wollte moeglichst keine Nachtdienste, bekam {nights}")
        if employee.prefers_weekends_off:
            fulfilled += max(0, 2 - weekends)
            violated += weekends
            if weekends:
                violation_details.append(f"bevorzugt Wochenende frei, bekam {weekends} Wochenend-/Feiertagsdienste")
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
            violated += lonely_count
            if lonely_count:
                violation_details.append(f"wuenscht Doppelnaechte, {lonely_count} Nachtdienst(e) standen einzeln")

        wish_free_worked = [
            d + 1
            for d in employee.blocked_days
            if d < day_count and row[d] != "-"
        ]
        if employee.wish_free_priority > 1 and wish_free_worked:
            violated += len(wish_free_worked)
            violation_details.append(
                "Wunschfrei nicht eingehalten an Tag(en): " + ", ".join(str(day) for day in wish_free_worked)
            )

        target_hours = round(total_required_hours * employee.weekly_hours_target / total_weekly_hours)
        hour_diff = planned_hours - target_hours

        schedule[employee.name] = row
        metrics[employee.name] = {
            "Qualifikation": employee.qualification,
            "Sollstunden": target_hours,
            "Geplante Stunden": planned_hours,
            "Plus/Minus Stunden": hour_diff,
            "Dienste": total,
            "Nachtdienste": nights,
            "Wochenenddienste": weekends,
            "Erfuellte Wuensche": fulfilled,
            "Verletzte weiche Wuensche": violated,
            "Welche Wuensche verletzt": "; ".join(violation_details) if violation_details else "-",
        }

    return status_name, schedule, metrics


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
            "Soll h": employee_metrics.get("Sollstunden", ""),
            "Ist h": employee_metrics.get("Geplante Stunden", ""),
            "+/- h": employee_metrics.get("Plus/Minus Stunden", ""),
        }
        for day_index, current_day in enumerate(days):
            value = plan[day_index]
            is_wish_free = employee is not None and day_index in employee.blocked_days
            if is_wish_free and value == "-":
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
        shift_code = value_text.split(" ")[0]