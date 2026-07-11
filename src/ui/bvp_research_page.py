"""Streamlit renderer for the Advanced HVP research page."""

from __future__ import annotations

from html import escape
import json

import pandas as pd
import streamlit as st

from src import bvp_research
from src.live_game import player_headshot_url
from src.pitch_analysis import UNAVAILABLE, fmt_metric, safe_float, safe_int


PAGE_TITLE = "Advanced Batter vs Pitcher Research"
PAGE_TAB_LABEL = "Advanced HVP"
MODE_OPTIONS = ("Specific Pitcher", "Projected Bullpen")


@st.cache_data(show_spinner=False, ttl=600, max_entries=128)
def _load_specific_research_cached(batter_id, pitcher_id, season, db_key):
    return bvp_research.specific_pitcher_research(
        int(batter_id),
        int(pitcher_id),
        int(season),
    )


@st.cache_data(show_spinner=False, ttl=600, max_entries=64)
def _load_bullpen_research_cached(
    batter_id,
    roster_records,
    pitcher_records,
    season,
    game_date,
    game_pk,
    opponent_team_id,
    probable_starter_id,
    pitcher_hand,
    doubleheader,
    already_used_pitcher_ids,
    db_key,
):
    roster_df = pd.DataFrame([dict(row) for row in roster_records])
    pitcher_stats_df = pd.DataFrame([dict(row) for row in pitcher_records])
    return bvp_research.projected_bullpen_research(
        batter_id=int(batter_id),
        roster_df=roster_df,
        pitcher_stats_df=pitcher_stats_df,
        season=int(season),
        game_date=str(game_date),
        game_pk=game_pk,
        opponent_team_id=opponent_team_id,
        probable_starter_id=probable_starter_id,
        pitcher_hand=pitcher_hand,
        doubleheader=bool(doubleheader),
        already_used_pitcher_ids=already_used_pitcher_ids,
    )


def _cache_value(value):
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, sort_keys=True, default=str)
    if pd.isna(value):
        return None
    return value


def _cache_records(frame):
    frame = pd.DataFrame(frame)
    if frame.empty:
        return tuple()
    records = []
    for row in frame.to_dict("records"):
        records.append(
            tuple(
                (str(key), _cache_value(value))
                for key, value in sorted(row.items(), key=lambda item: str(item[0]))
            )
        )
    return tuple(records)


def _query_value(name, default=None):
    value = st.query_params.get(name, default)
    if isinstance(value, list):
        return value[0] if value else default
    return value


def _query_int(*names):
    for name in names:
        value = pd.to_numeric(_query_value(name), errors="coerce")
        if pd.notna(value):
            return int(value)
    return None


def _state_int(key):
    value = pd.to_numeric(st.session_state.get(key), errors="coerce")
    if pd.isna(value):
        return None
    return int(value)


def _set_state_int(key, value):
    value = pd.to_numeric(value, errors="coerce")
    st.session_state[key] = int(value) if pd.notna(value) else None


def _restore_query_state(selected_date):
    defaults = {
        "hvp_game_pk": _query_int("game_pk", "hvp_game_pk"),
        "hvp_batter_id": _query_int("batter_id", "hvp_batter_id"),
        "hvp_pitcher_id": _query_int("pitcher_id", "hvp_pitcher_id"),
        "hvp_opponent_team_id": _query_int("opponent_team_id", "hvp_opponent_team_id"),
        "hvp_mode": _query_value("hvp_mode", MODE_OPTIONS[0]),
    }
    for key, value in defaults.items():
        if key not in st.session_state and value is not None:
            st.session_state[key] = value
    if "hvp_selected_date" not in st.session_state:
        st.session_state.hvp_selected_date = str(_query_value("date", selected_date))
    if st.session_state.get("hvp_mode") not in MODE_OPTIONS:
        st.session_state.hvp_mode = MODE_OPTIONS[0]


def _sync_query_params(selected_date):
    st.query_params["view"] = "Matchups"
    st.query_params["matchup_table"] = PAGE_TAB_LABEL
    st.query_params["date"] = str(selected_date)
    mappings = {
        "game_pk": st.session_state.get("hvp_game_pk"),
        "batter_id": st.session_state.get("hvp_batter_id"),
        "pitcher_id": st.session_state.get("hvp_pitcher_id"),
        "opponent_team_id": st.session_state.get("hvp_opponent_team_id"),
        "hvp_mode": st.session_state.get("hvp_mode"),
    }
    for key, value in mappings.items():
        if value is None or value == "":
            st.query_params.pop(key, None)
        else:
            st.query_params[key] = str(value)


def _player_display(row, fallback="Select player"):
    if not row:
        return fallback
    return str(row.get("Name") or row.get("Player") or fallback)


def _player_meta(row, group):
    if not row:
        return ""
    if group == "batter":
        side = row.get("Bats") or row.get("bat_side") or row.get("batting_side")
        position = row.get("Position") or row.get("position") or ""
        team = row.get("Team") or row.get("team_name") or ""
        return " · ".join(str(value) for value in (team, side, position) if value)
    hand = row.get("Throws") or row.get("throwing_hand") or row.get("pitcher_hand")
    role = row.get("Role") or row.get("projected_role") or "Pitcher"
    team = row.get("Team") or row.get("team_name") or ""
    return " · ".join(str(value) for value in (team, hand, role) if value)


def _player_card(player_id, row, group):
    has_player = bool(player_id and row)
    name = _player_display(row, fallback="Batter" if group == "batter" else "Pitcher")
    meta = _player_meta(row, group)
    if has_player:
        avatar_html = (
            f'<img src="{escape(player_headshot_url(int(player_id), width=96))}" '
            f'alt="{escape(name)} headshot">'
        )
        name_html = f'<div class="hvp-player-name">{escape(name)}</div>'
        meta_html = f'<div class="hvp-player-meta">{escape(meta)}</div>' if meta else ""
    else:
        avatar_html = '<div class="hvp-avatar-blank" aria-hidden="true"></div>'
        name_html = '<div class="hvp-player-name hvp-player-empty" aria-hidden="true">&nbsp;</div>'
        meta_html = '<div class="hvp-player-meta hvp-player-empty" aria-hidden="true">&nbsp;</div>'
    st.html(
        f"""
        <div class="hvp-player-card">
            {avatar_html}
            <div>
                {name_html}
                {meta_html}
            </div>
        </div>
        """
    )


def _render_hvp_styles():
    st.markdown(
        """
        <style>
        .hvp-shell {
            background: #ffffff;
            border: 1px solid #d9e1ea;
            border-radius: 6px;
            padding: 14px 16px;
            margin: 0 0 14px;
        }
        .hvp-title {
            color: #071b31;
            font-family: "Bebas Neue", sans-serif;
            font-size: 2rem;
            line-height: 1;
            margin: 0;
        }
        .hvp-player-card {
            align-items: center;
            background: #fff;
            border: 1px solid #d9e1ea;
            border-radius: 6px;
            display: flex;
            gap: 12px;
            min-height: 92px;
            padding: 10px 12px;
        }
        .hvp-player-card img {
            background: #edf1f5;
            border-radius: 50%;
            height: 68px;
            object-fit: cover;
            width: 68px;
        }
        .hvp-avatar-blank {
            background:
                radial-gradient(circle at 50% 38%, #cfd8e3 0 18%, transparent 19%),
                radial-gradient(circle at 50% 96%, #cfd8e3 0 34%, transparent 35%),
                #edf1f5;
            border: 1px solid #d8e1eb;
            border-radius: 50%;
            flex: 0 0 auto;
            height: 68px;
            width: 68px;
        }
        .hvp-player-name {
            color: #071b31;
            font-weight: 900;
            min-height: 1.1rem;
        }
        .hvp-player-empty {
            min-width: 1px;
        }
        .hvp-player-meta {
            color: #637183;
            font-size: 0.9rem;
            margin-top: 2px;
        }
        .hvp-metric-grid {
            display: grid;
            gap: 1px;
            grid-template-columns: repeat(auto-fit, minmax(108px, 1fr));
            margin: 10px 0 12px;
        }
        .hvp-metric {
            background: #f7f9fb;
            border: 1px solid #e2e8ef;
            min-height: 64px;
            padding: 9px 10px;
        }
        .hvp-metric span {
            color: #607083;
            display: block;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }
        .hvp-metric strong {
            color: #071b31;
            display: block;
            font-size: 1.15rem;
            margin-top: 4px;
        }
        .hvp-grade {
            background: #eef5f1;
            border: 1px solid #cde3d7;
            border-radius: 4px;
            color: #0b6d3b;
            display: inline-block;
            font-weight: 900;
            padding: 3px 8px;
        }
        .hvp-grade.difficult {
            background: #f7eeee;
            border-color: #e2cccc;
            color: #8b2e2e;
        }
        .hvp-grade.neutral {
            background: #f3f5f8;
            border-color: #d8e0ea;
            color: #425064;
        }
        .hvp-note {
            border-top: 1px solid #dce3eb;
            color: #526174;
            font-size: 0.9rem;
            margin-top: 10px;
            padding-top: 10px;
        }
        @media (max-width: 760px) {
            .hvp-shell { padding: 12px; }
            .hvp-title { font-size: 1.55rem; }
            .hvp-player-card { min-height: 78px; }
            .hvp-player-card img { height: 54px; width: 54px; }
            .hvp-avatar-blank { height: 54px; width: 54px; }
            .hvp-metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            .hvp-metric { min-height: 54px; padding: 7px 6px; }
            .hvp-metric strong { font-size: 0.95rem; }
            .hvp-metric span { font-size: 0.64rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_bvp_research_page(
    schedule_df,
    batters_df,
    pitchers_df,
    season,
    selected_date,
    database_cache_key,
    active_roster_loader=None,
):
    _restore_query_state(selected_date)
    _render_hvp_styles()

    batters = bvp_research.player_lookup(batters_df)
    pitchers = bvp_research.player_lookup(pitchers_df)
    selected_game_pk = _state_int("hvp_game_pk")
    selected_batter_id = _state_int("hvp_batter_id")
    selected_pitcher_id = _state_int("hvp_pitcher_id")

    game_row = bvp_research.game_context(schedule_df, selected_game_pk)
    batter_row = batters.get(selected_batter_id, {})
    opponent_context = bvp_research.opponent_context_for_batter(game_row, batter_row)
    previous_game_pk = st.session_state.get("hvp_previous_game_pk")
    if selected_game_pk != previous_game_pk:
        st.session_state.hvp_previous_game_pk = selected_game_pk
        probable = opponent_context.get("probable_pitcher_id")
        if probable is not None:
            selected_pitcher_id = int(probable)
            st.session_state.hvp_pitcher_id = selected_pitcher_id
    if opponent_context.get("opponent_team_id") is not None:
        st.session_state.hvp_opponent_team_id = int(opponent_context["opponent_team_id"])

    st.markdown(
        f"""
        <div class="hvp-shell">
            <div class="hvp-title">{PAGE_TITLE}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _render_selection_header(
        schedule_df,
        batters_df,
        pitchers_df,
        selected_date,
        batters,
        pitchers,
    )

    selected_game_pk = _state_int("hvp_game_pk")
    selected_batter_id = _state_int("hvp_batter_id")
    selected_pitcher_id = _state_int("hvp_pitcher_id")
    game_row = bvp_research.game_context(schedule_df, selected_game_pk)
    batter_row = batters.get(selected_batter_id, {})
    pitcher_row = pitchers.get(selected_pitcher_id, {})
    opponent_context = bvp_research.opponent_context_for_batter(game_row, batter_row)
    if opponent_context.get("opponent_team_id") is not None:
        st.session_state.hvp_opponent_team_id = int(opponent_context["opponent_team_id"])
    _sync_query_params(selected_date)

    mode = st.radio(
        "Analysis mode",
        MODE_OPTIONS,
        key="hvp_mode",
        horizontal=True,
        label_visibility="collapsed",
    )
    _sync_query_params(selected_date)

    if mode == "Specific Pitcher":
        _render_specific_pitcher_mode(
            selected_batter_id,
            selected_pitcher_id,
            batter_row,
            pitcher_row,
            season,
            database_cache_key,
        )
    else:
        _render_projected_bullpen_mode(
            selected_batter_id,
            selected_pitcher_id,
            batter_row,
            game_row,
            opponent_context,
            pitchers_df,
            season,
            selected_date,
            selected_game_pk,
            database_cache_key,
            active_roster_loader,
        )


def _render_selection_header(
    schedule_df,
    batters_df,
    pitchers_df,
    selected_date,
    batters,
    pitchers,
):
    game_opts = bvp_research.game_options(schedule_df)
    game_labels = list(game_opts)
    current_game_pk = _state_int("hvp_game_pk")
    game_index = None
    if current_game_pk in set(game_opts.values()):
        game_index = list(game_opts.values()).index(current_game_pk)

    batter_opts = bvp_research.player_search_options(batters_df)
    pitcher_opts = bvp_research.player_search_options(pitchers_df)
    current_batter_id = _state_int("hvp_batter_id")
    current_pitcher_id = _state_int("hvp_pitcher_id")

    batter_index = (
        list(batter_opts.values()).index(current_batter_id)
        if current_batter_id in set(batter_opts.values())
        else None
    )
    pitcher_index = (
        list(pitcher_opts.values()).index(current_pitcher_id)
        if current_pitcher_id in set(pitcher_opts.values())
        else None
    )

    with st.container(key="hvp_selection_header"):
        game_col, batter_col, pitcher_col, action_col = st.columns(
            [1.05, 1.2, 1.2, 0.55],
            gap="small",
            vertical_alignment="bottom",
        )
        with game_col:
            selected_game_label = st.selectbox(
                "Selected game",
                game_labels,
                index=game_index,
                placeholder="Select game...",
                key="hvp_game_select",
            )
            _set_state_int("hvp_game_pk", game_opts.get(selected_game_label))
        with batter_col:
            selected_batter_label = st.selectbox(
                "Batter search",
                list(batter_opts),
                index=batter_index,
                placeholder="Search batter by MLB ID...",
                key="hvp_batter_select",
            )
            _set_state_int("hvp_batter_id", batter_opts.get(selected_batter_label))
        with pitcher_col:
            selected_pitcher_label = st.selectbox(
                "Pitcher search",
                list(pitcher_opts),
                index=pitcher_index,
                placeholder="Search pitcher by MLB ID...",
                key="hvp_pitcher_select",
            )
            _set_state_int("hvp_pitcher_id", pitcher_opts.get(selected_pitcher_label))
        with action_col:
            if st.button("Reset", key="hvp_reset", use_container_width=True):
                for key in (
                    "hvp_game_pk",
                    "hvp_batter_id",
                    "hvp_pitcher_id",
                    "hvp_opponent_team_id",
                ):
                    st.session_state[key] = None
                st.rerun(scope="app")

        current_batter_id = _state_int("hvp_batter_id")
        current_pitcher_id = _state_int("hvp_pitcher_id")
        selected_game_pk = _state_int("hvp_game_pk")
        game_row = bvp_research.game_context(schedule_df, selected_game_pk)
        card_cols = st.columns(2, gap="small")
        with card_cols[0]:
            _player_card(current_batter_id, batters.get(current_batter_id, {}), "batter")
        with card_cols[1]:
            _player_card(current_pitcher_id, pitchers.get(current_pitcher_id, {}), "pitcher")


def _render_specific_pitcher_mode(
    batter_id,
    pitcher_id,
    batter_row,
    pitcher_row,
    season,
    database_cache_key,
):
    if batter_id is None:
        st.info("Select a batter to begin Advanced HVP research.")
        return
    if pitcher_id is None:
        st.info("Select a pitcher or choose a scheduled game with an announced probable starter.")
        return

    with st.spinner("Loading Advanced HVP research..."):
        research = _load_specific_research_cached(
            int(batter_id),
            int(pitcher_id),
            int(season),
            database_cache_key,
        )
    summary = research.get("summary", {})
    st.markdown('<div class="hvp-shell">', unsafe_allow_html=True)
    st.markdown(
        f"#### {_player_display(batter_row, 'Batter')} vs {_player_display(pitcher_row, 'Pitcher')}"
    )
    _metric_grid(
        [
            ("PA", summary.get("PA"), 0),
            ("AB", summary.get("AB"), 0),
            ("H", summary.get("H"), 0),
            ("1B", summary.get("1B"), 0),
            ("2B", summary.get("2B"), 0),
            ("3B", summary.get("3B"), 0),
            ("HR", summary.get("HR"), 0),
            ("BB", summary.get("BB"), 0),
            ("SO", summary.get("SO"), 0),
            ("AVG", summary.get("AVG"), 3),
            ("OBP", summary.get("OBP"), 3),
            ("SLG", summary.get("SLG"), 3),
            ("OPS", summary.get("OPS"), 3),
            ("wOBA", summary.get("wOBA"), 3),
            ("K%", summary.get("K%"), 1, True),
            ("BB%", summary.get("BB%"), 1, True),
            ("BABIP", summary.get("BABIP"), 3),
            ("Barrel%", summary.get("Barrel%"), 1, True),
            ("Hard-hit%", summary.get("Hard-hit%"), 1, True),
        ]
    )
    st.caption(
        "Career BvP uses the local historical database. "
        f"Pitch-level Statcast rows: {summary.get('data_date_range') or 'not backfilled yet'}. "
        f"Sample: {summary.get('sample_label', 'Unavailable')}. "
        f"Last matchup: {summary.get('last_matchup_date') or UNAVAILABLE}."
    )
    st.markdown("</div>", unsafe_allow_html=True)

    _render_exact_pitch_table(research.get("comparison_rows", []))
    _render_pitch_location(research.get("pitch_events", []))
    _render_plate_appearance_logs(research.get("plate_appearances", []), research.get("pitch_events", []))


def _metric_grid(items):
    html = ['<div class="hvp-metric-grid">']
    for item in items:
        label = item[0]
        value = item[1]
        digits = item[2] if len(item) >= 3 else 3
        percent = item[3] if len(item) >= 4 else False
        html.append(
            '<div class="hvp-metric">'
            f"<span>{escape(str(label))}</span>"
            f"<strong>{escape(fmt_metric(value, digits=digits, percent=percent))}</strong>"
            "</div>"
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def _render_exact_pitch_table(rows):
    st.markdown('<div class="hvp-shell">', unsafe_allow_html=True)
    st.markdown("#### Exact Pitch-Type Analysis")
    if not rows:
        st.info(
            "No exact pitch-level history is available yet for this pair. "
            "Run the pitch-data refresh or backfill to populate exact pitch chips, zone rates, and CSW/whiff detail."
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return
    frame = pd.DataFrame(rows)
    display_columns = [
        "Pitch",
        "Code",
        "Pitcher Usage",
        "Pitcher Count",
        "Avg Velo",
        "Direct Count",
        "Whiff%",
        "CSW%",
        "Contact%",
        "Hard-hit%",
        "Barrel%",
        "Direct AVG",
        "Direct SLG",
        "Direct wOBA",
        "Direct xwOBA",
        "Batter Pitch AVG",
        "Batter Pitch SLG",
        "Batter Pitch K%",
        "Sample",
    ]
    display_columns = [column for column in display_columns if column in frame.columns]
    st.dataframe(frame[display_columns], hide_index=True, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_pitch_location(pitch_events):
    frame = pd.DataFrame(pitch_events or [])
    st.markdown('<div class="hvp-shell">', unsafe_allow_html=True)
    st.markdown("#### Pitch Location")
    if frame.empty or "plate_x" not in frame.columns or "plate_z" not in frame.columns:
        st.info("Pitch-location rows are not available yet for this matchup.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    frame = frame.copy()
    frame["plate_x"] = pd.to_numeric(frame["plate_x"], errors="coerce")
    frame["plate_z"] = pd.to_numeric(frame["plate_z"], errors="coerce")
    frame = frame.dropna(subset=["plate_x", "plate_z"])
    if frame.empty:
        st.info("Pitch-location rows are present, but plate coordinates are unavailable.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    selected_pitch = st.selectbox(
        "Pitch type",
        ["All", *sorted(frame["pitch_type"].dropna().astype(str).str.upper().unique())],
        key="hvp_location_pitch_type",
    )
    if selected_pitch != "All":
        frame = frame[frame["pitch_type"].astype(str).str.upper().eq(selected_pitch)]
    chart_df = frame.rename(columns={"plate_x": "x", "plate_z": "z"})
    st.scatter_chart(chart_df, x="x", y="z", color="pitch_type", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_plate_appearance_logs(plate_appearances, pitch_events):
    st.markdown('<div class="hvp-shell">', unsafe_allow_html=True)
    st.markdown("#### Plate-Appearance Logs")
    if not plate_appearances:
        st.info(
            "No pitch-sequence plate appearances are available for this pair yet. "
            "Career game-level BvP can still be present above while pitch-level Statcast is pending."
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return
    pitch_events_by_pa = {}
    for pitch in pitch_events or []:
        pitch_events_by_pa.setdefault(
            (pitch.get("game_pk"), pitch.get("at_bat_number")),
            [],
        ).append(pitch)
    for index, pa in enumerate(plate_appearances[:80], start=1):
        result = pa.get("pa_result") or pa.get("event") or "Completed PA"
        label = (
            f"{pa.get('game_date', UNAVAILABLE)} · Inning {pa.get('inning', UNAVAILABLE)} · "
            f"{result} · {pa.get('pitch_sequence', UNAVAILABLE)}"
        )
        with st.expander(label):
            cols = st.columns(6)
            cols[0].metric("Final count", pa.get("final_count") or UNAVAILABLE)
            cols[1].metric("Pitches", safe_int(pa.get("pitch_count")))
            cols[2].metric("RBI", safe_int(pa.get("rbi")))
            cols[3].metric("EV", fmt_metric(pa.get("launch_speed"), 1))
            cols[4].metric("LA", fmt_metric(pa.get("launch_angle"), 1))
            cols[5].metric("Dist", fmt_metric(pa.get("estimated_distance"), 0))
            pitches = pitch_events_by_pa.get((pa.get("game_pk"), pa.get("at_bat_number")), pa.get("pitches", []))
            if pitches:
                pitch_df = pd.DataFrame(pitches)
                pitch_cols = [
                    "pitch_number",
                    "balls",
                    "strikes",
                    "pitch_type",
                    "pitch_name",
                    "release_speed",
                    "pitch_description",
                    "plate_x",
                    "plate_z",
                    "zone",
                    "pfx_x",
                    "pfx_z",
                    "release_spin_rate",
                ]
                pitch_cols = [column for column in pitch_cols if column in pitch_df.columns]
                st.dataframe(pitch_df[pitch_cols], hide_index=True, use_container_width=True)
            elif index == 1:
                st.caption("Pitch-by-pitch detail is not stored for this cached PA row.")
    st.markdown("</div>", unsafe_allow_html=True)


def _render_projected_bullpen_mode(
    batter_id,
    pitcher_id,
    batter_row,
    game_row,
    opponent_context,
    pitchers_df,
    season,
    selected_date,
    game_pk,
    database_cache_key,
    active_roster_loader,
):
    if batter_id is None:
        st.info("Select a batter before building a projected bullpen matchup.")
        return
    if not game_row:
        st.info("Select a scheduled game so the opposing team and bullpen can be projected.")
        return
    opponent_team_id = opponent_context.get("opponent_team_id") or _state_int("hvp_opponent_team_id")
    if opponent_team_id is None:
        st.info("The selected batter is not on either team for this game.")
        return

    roster_df, roster_note = _load_opponent_roster(
        game_row,
        opponent_team_id,
        selected_date,
        pitchers_df,
        active_roster_loader,
    )
    if roster_df.empty:
        st.warning("Projected bullpen is unavailable because the active roster could not be loaded.")
        return

    with st.spinner("Projecting full bullpen availability..."):
        research = _load_bullpen_research_cached(
            int(batter_id),
            _cache_records(roster_df),
            _cache_records(pitchers_df),
            int(season),
            str(selected_date),
            int(game_pk) if game_pk is not None else None,
            int(opponent_team_id),
            opponent_context.get("probable_pitcher_id") or pitcher_id,
            opponent_context.get("probable_pitcher_hand"),
            _is_doubleheader(game_row, opponent_team_id),
            tuple(),
            database_cache_key,
        )
    relievers = research.get("relievers", [])
    composite = research.get("composite", {})
    _render_bullpen_composite(composite, roster_note)
    _render_bullpen_table(relievers)


def _load_opponent_roster(game_row, opponent_team_id, selected_date, pitchers_df, active_roster_loader):
    team_record = bvp_research.team_record_from_game_context(game_row, opponent_team_id)
    if team_record and active_roster_loader is not None:
        try:
            roster_df = active_roster_loader((team_record,), selected_date)
            if roster_df is not None and not roster_df.empty:
                return roster_df, "Active MLB roster loaded from MLB StatsAPI."
        except Exception:
            pass
    frame = pd.DataFrame(pitchers_df)
    if frame.empty or "team_id" not in frame.columns:
        return pd.DataFrame(), "Roster unavailable."
    fallback = frame[pd.to_numeric(frame["team_id"], errors="coerce").eq(int(opponent_team_id))].copy()
    if fallback.empty:
        return pd.DataFrame(), "Roster unavailable."
    fallback["group"] = "pitching"
    fallback["Position"] = "P"
    fallback["status"] = "Roster fallback from current pitching stats"
    return fallback, "Active roster unavailable; using current season pitching list as a fallback."


def _is_doubleheader(game_row, team_id):
    # Schedule rows are already scoped to the selected date. If the source adds
    # doubleheader flags later, this keeps the projection hook centralized.
    value = game_row.get("doubleheader") or game_row.get("double_header")
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def _render_bullpen_composite(composite, roster_note):
    st.markdown('<div class="hvp-shell">', unsafe_allow_html=True)
    st.markdown("#### Projected Bullpen Matchup")
    grade = str(composite.get("overall_grade") or "No Data")
    grade_class = "difficult" if "difficult" in grade.lower() else "neutral" if "neutral" in grade.lower() or "no data" in grade.lower() else ""
    st.markdown(
        f'<span class="hvp-grade {grade_class}">{escape(grade)}</span>',
        unsafe_allow_html=True,
    )
    _metric_grid(
        [
            ("Score", composite.get("overall_score"), 1),
            ("Projected K%", composite.get("projected_K%"), 1, True),
            ("Projected BB%", composite.get("projected_BB%"), 1, True),
            ("Projected AVG", composite.get("projected_AVG"), 3),
            ("Projected OBP", composite.get("projected_OBP"), 3),
            ("Projected SLG", composite.get("projected_SLG"), 3),
            ("Projected wOBA", composite.get("projected_wOBA"), 3),
            ("Relievers", composite.get("active_relievers_included"), 0),
            ("Excluded", composite.get("excluded_because_availability"), 0),
        ]
    )
    st.caption(
        f"Most favorable: {composite.get('most_favorable') or UNAVAILABLE}. "
        f"Most difficult: {composite.get('most_difficult') or UNAVAILABLE}. "
        f"Most likely: {composite.get('most_likely') or UNAVAILABLE}. "
        f"Confidence: {composite.get('confidence') or UNAVAILABLE}. "
        f"{roster_note}"
    )
    with st.expander("Methodology"):
        st.write(
            "Relievers are weighted by projected appearance probability, availability score, expected batters faced, "
            "and role. Direct BvP is visible but shrunk toward larger evidence: batter vs hand, batter vs exact pitch mix, "
            "pitcher allowed profile where available, then league-style baseline. Limited or unavailable pitchers are "
            "discounted from the composite by default."
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _render_bullpen_table(relievers):
    st.markdown('<div class="hvp-shell">', unsafe_allow_html=True)
    st.markdown("#### Full Projected Bullpen")
    if not relievers:
        st.info("No projected relievers were found for the selected game.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    frame = pd.DataFrame(relievers)
    filter_cols = st.columns([1, 1, 1, 1], gap="small")
    role_filter = filter_cols[0].multiselect(
        "Role",
        sorted(frame["projected_role"].dropna().unique()),
        key="hvp_bullpen_role_filter",
    )
    hand_filter = filter_cols[1].multiselect(
        "Throws",
        sorted(value for value in frame["Throws"].dropna().unique() if value),
        key="hvp_bullpen_hand_filter",
    )
    availability_filter = filter_cols[2].multiselect(
        "Availability",
        sorted(frame["availability_label"].dropna().unique()),
        key="hvp_bullpen_availability_filter",
    )
    min_probability = filter_cols[3].slider(
        "Min probability",
        0,
        100,
        0,
        key="hvp_bullpen_min_probability",
    )
    include_limited = st.checkbox(
        "Show limited/unavailable pitchers",
        value=True,
        key="hvp_show_limited_relievers",
    )
    sort_by = st.selectbox(
        "Sort bullpen",
        [
            "Most likely to appear",
            "Best matchup for batter",
            "Worst matchup for batter",
            "Availability",
            "Role",
            "Handedness",
            "Direct BvP sample",
            "Matchup grade",
        ],
        key="hvp_bullpen_sort",
    )

    filtered = frame.copy()
    if role_filter:
        filtered = filtered[filtered["projected_role"].isin(role_filter)]
    if hand_filter:
        filtered = filtered[filtered["Throws"].isin(hand_filter)]
    if availability_filter:
        filtered = filtered[filtered["availability_label"].isin(availability_filter)]
    if min_probability:
        filtered = filtered[
            pd.to_numeric(filtered["appearance_probability"], errors="coerce").fillna(0) * 100
            >= min_probability
        ]
    if not include_limited:
        filtered = filtered[~filtered["availability_label"].isin(["Limited", "Unavailable"])]
    filtered = _sort_bullpen(filtered, sort_by)

    table_columns = [
        "Player",
        "Throws",
        "projected_role",
        "availability_label",
        "availability_score",
        "last_appearance_date",
        "pitches_yesterday",
        "pitches_last_three_days",
        "appearance_probability",
        "Direct PA",
        "Direct AVG",
        "Direct OBP",
        "Direct SLG",
        "Direct OPS",
        "Direct wOBA",
        "primary_pitches",
        "matchup_score",
        "matchup_grade",
        "sample_confidence",
        "matchup_reason",
    ]
    table_columns = [column for column in table_columns if column in filtered.columns]
    st.dataframe(filtered[table_columns], hide_index=True, use_container_width=True)

    for _, row in filtered.head(18).iterrows():
        label = (
            f"{row.get('Player')} · {row.get('projected_role')} · "
            f"{row.get('availability_label')} · {row.get('matchup_grade')}"
        )
        with st.expander(label):
            st.write(row.get("availability_reason") or "No availability reason stored.")
            exact_rows = row.get("exact_pitch_rows")
            if exact_rows:
                st.dataframe(pd.DataFrame(exact_rows), hide_index=True, use_container_width=True)
            else:
                st.caption("No exact pitch-type BvP rows are stored for this reliever yet.")
    st.markdown("</div>", unsafe_allow_html=True)


def _sort_bullpen(frame, sort_by):
    frame = frame.copy()
    if frame.empty:
        return frame
    if sort_by == "Best matchup for batter":
        return frame.sort_values("matchup_score", ascending=False, na_position="last")
    if sort_by == "Worst matchup for batter":
        return frame.sort_values("matchup_score", ascending=True, na_position="last")
    if sort_by == "Availability":
        return frame.sort_values("availability_score", ascending=False, na_position="last")
    if sort_by == "Role":
        return frame.sort_values(["projected_role", "Player"], ascending=[True, True])
    if sort_by == "Handedness":
        return frame.sort_values(["Throws", "Player"], ascending=[True, True])
    if sort_by == "Direct BvP sample":
        return frame.sort_values("Direct PA", ascending=False, na_position="last")
    if sort_by == "Matchup grade":
        return frame.sort_values(["matchup_grade", "matchup_score"], ascending=[True, False])
    return frame.sort_values("appearance_probability", ascending=False, na_position="last")
