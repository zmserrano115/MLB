"""Streamlit renderer for the Advanced HVP research page."""

from __future__ import annotations

import json
from html import escape
from threading import Event, Thread

import pandas as pd
import streamlit as st

from src import bvp_research
from src.live_game import player_headshot_url
from src.pitch_analysis import UNAVAILABLE, fmt_metric, safe_float, safe_int
from src.player_rankings import rank_hitters_by_wrc_plus

PAGE_TAB_LABEL = "Advanced HVP"
BULLPEN_TAB_LABEL = "Bullpen"


@st.cache_data(show_spinner=False, ttl=600, max_entries=128)
def _load_specific_research_cached(batter_id, pitcher_id, season, db_key):
    return bvp_research.specific_pitcher_research(
        int(batter_id),
        int(pitcher_id),
        int(season),
        backfill_missing=False,
    )


@st.cache_resource(show_spinner=False, max_entries=128)
def _start_specific_history_backfill(batter_id, pitcher_id, game_logs_json):
    state = {
        "done": Event(),
        "saved": 0,
    }

    def load_missing_history():
        try:
            game_logs = json.loads(game_logs_json)
            state["saved"] = len(
                bvp_research.backfill_matchup_pitch_history(
                    int(batter_id),
                    int(pitcher_id),
                    game_logs,
                )
            )
        finally:
            state["done"].set()

    Thread(
        target=load_missing_history,
        name=f"hvp-history-{int(batter_id)}-{int(pitcher_id)}",
        daemon=True,
    ).start()
    return state


@st.fragment(run_every="2s")
def _refresh_specific_history_when_ready(state, matchup_key):
    if not state["done"].is_set():
        return
    refresh_key = f"hvp_history_refreshed_{matchup_key}"
    if state.get("saved", 0) > 0 and not st.session_state.get(refresh_key):
        st.session_state[refresh_key] = True
        _load_specific_research_cached.clear()
        st.rerun(scope="app")


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


def _auto_select_player_game(schedule_df, *player_rows):
    """Use a selected player's only scheduled game without another user step."""
    current_game_pk = _state_int("hvp_game_pk")
    scheduled_games = []
    for player_row in player_rows:
        game_pks = bvp_research.scheduled_game_pks_for_player(
            schedule_df,
            player_row,
        )
        scheduled_games.extend(game_pk for game_pk in game_pks if game_pk not in scheduled_games)
        if current_game_pk in game_pks:
            return current_game_pk
        if len(game_pks) == 1:
            _set_state_int("hvp_game_pk", game_pks[0])
            st.session_state.pop("hvp_game_select", None)
            return game_pks[0]
    if any(player_rows) and current_game_pk not in scheduled_games:
        _set_state_int("hvp_game_pk", None)
        st.session_state.pop("hvp_game_select", None)
        return None
    return current_game_pk


def _reset_hvp_selection():
    for key in (
        "hvp_game_pk",
        "hvp_game_select",
        "hvp_previous_game_pk",
        "hvp_batter_id",
        "hvp_pitcher_id",
        "hvp_opponent_team_id",
    ):
        st.session_state.pop(key, None)


def _restore_query_state(selected_date):
    defaults = {
        "hvp_game_pk": _query_int("game_pk", "hvp_game_pk"),
    }
    for key, value in defaults.items():
        if key not in st.session_state and value is not None:
            st.session_state[key] = value
    if "hvp_selected_date" not in st.session_state:
        st.session_state.hvp_selected_date = str(_query_value("date", selected_date))


def _sync_query_params(selected_date):
    st.query_params["view"] = "Matchups"
    st.query_params["matchup_table"] = PAGE_TAB_LABEL
    st.query_params["date"] = str(selected_date)
    mappings = {
        "game_pk": st.session_state.get("hvp_game_pk"),
    }
    for private_key in ("batter_id", "pitcher_id", "opponent_team_id", "hvp_mode"):
        st.query_params.pop(private_key, None)
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
    role = "batter" if group == "batter" else "pitcher"
    name = _player_display(row, fallback=f"Select {role}")
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
        name_html = f'<div class="hvp-player-name">{escape(name)}</div>'
        meta_html = '<div class="hvp-player-meta">Tap to browse players</div>'
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


def _ordered_picker_players(frame, group):
    players = pd.DataFrame(frame).copy()
    if players.empty:
        return players
    players = players.drop_duplicates("player_id", keep="first")
    if group == "batter":
        return rank_hitters_by_wrc_plus(players)
    return players.reset_index(drop=True)


def _render_player_picker(frame, group):
    players = _ordered_picker_players(frame, group)
    if players.empty:
        st.info("No players are available for this selection.")
        return
    search = st.text_input(
        f"Search {group}s",
        key=f"hvp_{group}_picker_search",
        placeholder=f"Search {group}...",
        label_visibility="collapsed",
    ).strip().casefold()
    if search:
        names = players.get("Name", players.get("Player", pd.Series(dtype=str)))
        teams = players.get("Team", players.get("team_name", pd.Series(dtype=str)))
        mask = names.fillna("").astype(str).str.casefold().str.contains(search, regex=False)
        mask |= teams.fillna("").astype(str).str.casefold().str.contains(search, regex=False)
        players = players[mask]
    # Keep the initial image request bounded; search still resolves the full pool.
    visible_players = players.head(30)
    for offset in range(0, len(visible_players), 3):
        columns = st.columns(3, gap="small")
        for column, (_, row) in zip(
            columns,
            visible_players.iloc[offset : offset + 3].iterrows(),
            strict=False,
        ):
            player_id = pd.to_numeric(row.get("player_id"), errors="coerce")
            if pd.isna(player_id):
                continue
            name = str(row.get("Name") or row.get("Player") or "Player")
            team = str(row.get("Team") or row.get("team_name") or "").strip()
            with column, st.container(key=f"hvp_picker_card_{group}_{int(player_id)}"):
                st.html(
                    '<div class="hvp-picker-player-card">'
                    f'<img src="{escape(player_headshot_url(int(player_id), width=128), quote=True)}" '
                    f'alt="{escape(name, quote=True)} headshot">'
                    '<div class="hvp-picker-player-copy">'
                    f'<strong>{escape(name)}</strong>'
                    f'<span>{escape(team)}</span>'
                    "</div></div>"
                )
                if st.button(
                    f"Select {name}",
                    key=f"hvp_pick_{group}_{int(player_id)}",
                    use_container_width=True,
                ):
                    _set_state_int(f"hvp_{group}_id", int(player_id))
                    st.rerun(scope="app")


@st.dialog("Choose batter", width="large")
def _batter_picker_dialog(frame):
    _render_player_picker(frame, "batter")


@st.dialog("Choose pitcher", width="large")
def _pitcher_picker_dialog(frame):
    _render_player_picker(frame, "pitcher")


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
        .hvp-player-card {
            align-items: center;
            background: #fff;
            border: 1px solid #d9e1ea;
            border-radius: 6px;
            display: flex;
            gap: 12px;
            min-height: 92px;
            padding: 10px 12px;
            transition: border-color 150ms ease, box-shadow 150ms ease, transform 150ms ease;
        }
        [class*="st-key-hvp_batter_card"],
        [class*="st-key-hvp_pitcher_card"] {
            position: relative;
        }
        [class*="st-key-hvp_batter_card"] > [data-testid="stElementContainer"]:has(.stButton),
        [class*="st-key-hvp_pitcher_card"] > [data-testid="stElementContainer"]:has(.stButton) {
            height: 92px !important;
            inset: 0 !important;
            position: absolute !important;
            z-index: 3 !important;
        }
        [class*="st-key-hvp_batter_card"] .stButton,
        [class*="st-key-hvp_pitcher_card"] .stButton {
            height: 100%;
        }
        [class*="st-key-hvp_batter_card"] .stButton > button,
        [class*="st-key-hvp_pitcher_card"] .stButton > button {
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
            color: transparent !important;
            height: 100%;
            min-height: 92px;
            opacity: 0;
            padding: 0;
            width: 100%;
        }
        [class*="st-key-hvp_batter_card"]:hover .hvp-player-card,
        [class*="st-key-hvp_pitcher_card"]:hover .hvp-player-card {
            border-color: #0f3b66;
            box-shadow: 0 4px 12px rgba(15, 59, 102, 0.12);
            cursor: pointer;
            transform: translateY(-1px);
        }
        [class*="st-key-hvp_batter_card"]:has(button:focus-visible) .hvp-player-card,
        [class*="st-key-hvp_pitcher_card"]:has(button:focus-visible) .hvp-player-card {
            outline: 3px solid rgba(15, 59, 102, 0.35);
            outline-offset: 2px;
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
        [class*="st-key-hvp_picker_card_"] {
            min-height: 84px;
            position: relative;
        }
        .hvp-picker-player-card {
            align-items: center;
            background: #ffffff;
            border: 1px solid #d8dee6;
            border-radius: 6px;
            display: flex;
            gap: 10px;
            min-height: 84px;
            padding: 9px 10px;
            transition: border-color 150ms ease, box-shadow 150ms ease, transform 150ms ease;
        }
        .hvp-picker-player-card img {
            background: #edf1f5;
            border: 1px solid #d8dee6;
            border-radius: 50%;
            flex: 0 0 auto;
            height: 62px;
            object-fit: cover;
            width: 62px;
        }
        .hvp-picker-player-copy {
            min-width: 0;
        }
        .hvp-picker-player-copy strong,
        .hvp-picker-player-copy span {
            display: block;
        }
        .hvp-picker-player-copy strong {
            color: #071b31;
            font-size: 0.92rem;
            line-height: 1.2;
        }
        .hvp-picker-player-copy span {
            color: #637183;
            font-size: 0.78rem;
            margin-top: 3px;
        }
        [class*="st-key-hvp_picker_card_"] > [data-testid="stElementContainer"]:has(.stButton) {
            height: 84px !important;
            inset: 0 !important;
            position: absolute !important;
            z-index: 3 !important;
        }
        [class*="st-key-hvp_picker_card_"] .stButton,
        [class*="st-key-hvp_picker_card_"] .stButton > button {
            height: 100% !important;
            min-height: 84px !important;
            width: 100% !important;
        }
        [class*="st-key-hvp_picker_card_"] .stButton > button {
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
            color: transparent !important;
            opacity: 0;
            padding: 0;
        }
        [class*="st-key-hvp_picker_card_"]:hover .hvp-picker-player-card {
            border-color: #0f3b66;
            box-shadow: 0 3px 10px rgba(15, 59, 102, 0.12);
            cursor: pointer;
            transform: translateY(-1px);
        }
        [class*="st-key-hvp_picker_card_"]:has(button:focus-visible) .hvp-picker-player-card {
            outline: 3px solid rgba(15, 59, 102, 0.35);
            outline-offset: 2px;
        }
        .hvp-heat-shell {
            background: #ffffff;
            border: 1px solid #d8dee6;
            border-radius: 0;
            margin: 0 0 14px;
            overflow: hidden;
        }
        .hvp-heat-title {
            background: #ffffff;
            border-bottom: 1px solid #d8dee6;
            color: #071b31;
            font-family: "Bebas Neue", "Arial Narrow", sans-serif;
            font-size: 1.25rem;
            font-weight: 400;
            letter-spacing: 0.035em;
            padding: 11px 12px 9px;
        }
        .hvp-heat-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
        }
        .hvp-heat-cell {
            align-items: center;
            border-bottom: 1px solid #e2e8ef;
            border-right: 1px solid #e2e8ef;
            color: #071b31;
            display: flex;
            justify-content: space-between;
            min-height: 58px;
            padding: 9px 12px;
        }
        .hvp-heat-cell span {
            color: inherit;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }
        .hvp-heat-cell strong {
            color: inherit;
            font-size: 1.05rem;
            font-variant-numeric: tabular-nums;
        }
        .heat-strong { background: #ffffff; color: #08733f; box-shadow: inset 3px 0 0 #168253; }
        .heat-good { background: #ffffff; color: #236848; box-shadow: inset 3px 0 0 #5b9b78; }
        .heat-neutral { background: #ffffff; color: #755f08; box-shadow: inset 3px 0 0 #d4aa20; }
        .heat-poor { background: #ffffff; color: #8b2e38; box-shadow: inset 3px 0 0 #b54b55; }
        .heat-missing { background: #ffffff; color: #7b8795; box-shadow: inset 3px 0 0 #aeb8c4; }
        .heat-sample { background: #ffffff; color: #173f67; box-shadow: inset 3px 0 0 #4e789e; }
        .hvp-pitch-heat {
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }
        .hvp-pitch-heat table {
            border-collapse: collapse;
            min-width: 760px;
            width: 100%;
        }
        .hvp-pitch-heat th {
            background: #f7f9fb;
            border-bottom: 1px solid #d8dee6;
            color: #526171;
            font-size: 0.72rem;
            letter-spacing: 0.04em;
            padding: 8px 10px;
            text-align: center;
            text-transform: uppercase;
        }
        .hvp-pitch-heat th:first-child,
        .hvp-pitch-heat td:first-child {
            text-align: left;
        }
        .hvp-pitch-heat td {
            border-bottom: 1px solid #e2e8ef;
            border-left: 0;
            border-right: 0;
            border-top: 0;
            font-size: 0.95rem;
            font-variant-numeric: tabular-nums;
            font-weight: 750;
            padding: 10px;
            text-align: center;
        }
        .hvp-pitch-name {
            background: #ffffff;
            border-color: #d9e1ea !important;
            color: #071b31;
            box-shadow: none !important;
            min-width: 180px;
        }
        @media (max-width: 680px) {
            .hvp-heat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .hvp-heat-cell { min-height: 54px; }
            [class*="st-key-hvp_batter_card"] > [data-testid="stElementContainer"]:has(.stButton),
            [class*="st-key-hvp_pitcher_card"] > [data-testid="stElementContainer"]:has(.stButton),
            [class*="st-key-hvp_batter_card"] .stButton > button,
            [class*="st-key-hvp_pitcher_card"] .stButton > button {
                height: 78px !important;
                min-height: 78px !important;
            }
        }
        .hvp-metric-grid {
            display: grid;
            grid-template-columns: repeat(9, minmax(72px, 1fr));
            margin: 0 0 14px;
            border: 1px solid #d8dee6;
        }
        .hvp-metric {
            background: #ffffff;
            border-right: 1px solid #e2e8ef;
            min-height: 64px;
            padding: 10px 12px;
        }
        .hvp-metric:last-child {
            border-right: 0;
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
        .hvp-matchup-heading {
            align-items: baseline;
            border-bottom: 2px solid #173f67;
            display: flex;
            justify-content: space-between;
            margin: 2px 0 0;
            padding: 8px 2px 7px;
        }
        .hvp-matchup-heading strong {
            color: #071b31;
            font-family: "Bebas Neue", "Arial Narrow", sans-serif;
            font-size: 1.55rem;
            font-weight: 400;
            letter-spacing: 0.035em;
        }
        .hvp-matchup-heading span {
            color: #637183;
            font-size: 0.75rem;
            font-weight: 800;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }
        .hvp-auto-game {
            border-left: 3px solid #245f96;
            color: #526171;
            font-size: 0.82rem;
            margin: 0 0 10px;
            padding: 7px 10px;
        }
        .hvp-bullpen-banner {
            align-items: center;
            background: #f7f9fb;
            border: 1px solid #d8e1eb;
            border-left: 4px solid #173f67;
            display: flex;
            gap: 13px;
            margin: 0 0 10px;
            min-height: 72px;
            padding: 9px 13px;
        }
        .hvp-bullpen-banner img {
            height: 52px;
            object-fit: contain;
            width: 52px;
        }
        .hvp-bullpen-banner span,
        .hvp-section-kicker {
            color: #667486;
            display: block;
            font-size: 0.7rem;
            font-weight: 800;
            letter-spacing: 0.075em;
            text-transform: uppercase;
        }
        .hvp-bullpen-banner strong {
            color: #071b31;
            display: block;
            font-family: "Bebas Neue", "Arial Narrow", sans-serif;
            font-size: 1.45rem;
            font-weight: 400;
            letter-spacing: 0.035em;
            line-height: 1.1;
            margin-top: 2px;
        }
        .hvp-pa-summary {
            border: 1px solid #d8e1eb;
            display: grid;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            margin: 0 0 10px;
        }
        .hvp-pa-stat {
            border-right: 1px solid #e2e8ef;
            padding: 8px 10px;
        }
        .hvp-pa-stat:last-child { border-right: 0; }
        .hvp-pa-stat span {
            color: #667486;
            display: block;
            font-size: 0.66rem;
            font-weight: 800;
            letter-spacing: 0.055em;
            text-transform: uppercase;
        }
        .hvp-pa-stat strong {
            color: #071b31;
            display: block;
            font-size: 1rem;
            font-variant-numeric: tabular-nums;
            margin-top: 2px;
        }
        .hvp-pa-analysis {
            align-items: start;
            display: grid;
            gap: 12px;
            grid-template-columns: minmax(280px, 320px) minmax(0, 1fr);
        }
        .hvp-pa-zone-card {
            border: 1px solid #d8e1eb;
            background: #fbfcfe;
            padding: 9px;
        }
        .hvp-pa-zone-title {
            color: #071b31;
            font-family: "Bebas Neue", "Arial Narrow", sans-serif;
            font-size: 1rem;
            letter-spacing: 0.04em;
            margin: 0 0 6px;
        }
        .hvp-pa-zone-svg {
            aspect-ratio: 170 / 160;
            background: #ffffff;
            display: block;
            height: auto;
            width: 100%;
        }
        .hvp-pa-zone-box {
            fill: rgba(232, 240, 247, 0.55);
            stroke: #173f67;
            stroke-width: 1.4;
            vector-effect: non-scaling-stroke;
        }
        .hvp-pa-zone-grid {
            stroke: #cfd8e3;
            stroke-width: 0.8;
            vector-effect: non-scaling-stroke;
        }
        .hvp-pa-zone-pitch {
            stroke: #ffffff;
            stroke-width: 1.5;
            vector-effect: non-scaling-stroke;
        }
        .hvp-pa-zone-pitch.ball { fill: #2f9967; }
        .hvp-pa-zone-pitch.strike { fill: #b42318; }
        .hvp-pa-zone-pitch.in-play { fill: #245f96; }
        .hvp-pa-zone-pitch.foul { fill: #6f7884; }
        .hvp-pa-zone-pitch.unknown { fill: #6b7888; }
        .hvp-pa-zone-number {
            dominant-baseline: central;
            fill: #ffffff;
            font-size: 8px;
            font-weight: 900;
            pointer-events: none;
            text-anchor: middle;
        }
        .hvp-pa-zone-empty {
            color: #667486;
            font-size: 0.72rem;
            margin-top: 5px;
            text-align: center;
        }
        .hvp-table-wrap {
            border: 1px solid #d8e1eb;
            overflow-x: auto;
            width: 100%;
        }
        .hvp-standard-table {
            border-collapse: collapse;
            min-width: 760px;
            width: 100%;
        }
        .hvp-standard-table th {
            background: #f5f7fa;
            border-bottom: 1px solid #d8e1eb;
            color: #59687a;
            font-size: 0.68rem;
            font-weight: 850;
            letter-spacing: 0.05em;
            padding: 8px 10px;
            text-align: left;
            text-transform: uppercase;
            white-space: nowrap;
        }
        .hvp-standard-table td {
            border-bottom: 1px solid #e5eaf0;
            color: #14283f;
            font-size: 0.82rem;
            padding: 9px 10px;
            vertical-align: middle;
        }
        .hvp-standard-table tbody tr:last-child td { border-bottom: 0; }
        .hvp-standard-table tbody tr:hover { background: #f8fafc; }
        .hvp-pa-analysis .hvp-standard-table { min-width: 520px; }
        .hvp-pitch-row-hit td {
            background: #edf7f1;
            color: #0b5f3d;
        }
        .hvp-pitch-row-hit td:first-child {
            box-shadow: inset 3px 0 0 #168253;
        }
        .hvp-pitch-row-out td {
            background: #fbefef;
            color: #84232d;
        }
        .hvp-pitch-row-out td:first-child {
            box-shadow: inset 3px 0 0 #b54b55;
        }
        .hvp-pitch-row-hit:hover td { background: #e4f3ea; }
        .hvp-pitch-row-out:hover td { background: #f7e5e6; }
        .hvp-cell-primary {
            color: #071b31;
            font-weight: 800;
            white-space: nowrap;
        }
        .hvp-cell-muted { color: #667486 !important; }
        .hvp-bullpen-overview {
            border-bottom: 2px solid #173f67;
            display: flex;
            justify-content: space-between;
            margin-top: 4px;
            padding: 8px 2px 7px;
        }
        .hvp-bullpen-overview strong {
            color: #071b31;
            font-family: "Bebas Neue", "Arial Narrow", sans-serif;
            font-size: 1.5rem;
            font-weight: 400;
            letter-spacing: 0.035em;
        }
        .hvp-bullpen-notables {
            display: grid;
            gap: 8px;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            margin: 0 0 12px;
        }
        .hvp-bullpen-notable {
            border: 1px solid #d8e1eb;
            border-left: 3px solid #4e789e;
            padding: 9px 11px;
        }
        .hvp-bullpen-notable span {
            color: #667486;
            display: block;
            font-size: 0.67rem;
            font-weight: 800;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }
        .hvp-bullpen-notable strong {
            color: #071b31;
            display: block;
            font-size: 0.9rem;
            margin-top: 2px;
        }
        .hvp-bullpen-card-grid {
            display: grid;
            gap: 10px;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            margin: 0 0 14px;
        }
        .hvp-bullpen-card {
            background: #fff;
            border: 1px solid #d8e1eb;
            border-top: 3px solid #173f67;
            min-width: 0;
            padding: 10px 11px;
        }
        .hvp-bullpen-card-head {
            align-items: center;
            display: flex;
            gap: 9px;
        }
        .hvp-bullpen-card-head img {
            background: #eef2f6;
            border-radius: 50%;
            height: 48px;
            object-fit: cover;
            width: 48px;
        }
        .hvp-bullpen-card-head strong {
            color: #071b31;
            display: block;
            font-size: 0.92rem;
        }
        .hvp-bullpen-card-head span {
            color: #667486;
            display: block;
            font-size: 0.72rem;
            margin-top: 2px;
        }
        .hvp-bullpen-player-stats {
            border-bottom: 1px solid #e2e8ef;
            border-top: 1px solid #e2e8ef;
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            margin: 9px 0;
            padding: 7px 0;
        }
        .hvp-bullpen-player-stat {
            border-right: 1px solid #e2e8ef;
            text-align: center;
        }
        .hvp-bullpen-player-stat:last-child { border-right: 0; }
        .hvp-bullpen-player-stat span {
            color: #6a7787;
            display: block;
            font-size: 0.61rem;
            font-weight: 800;
            text-transform: uppercase;
        }
        .hvp-bullpen-player-stat strong {
            color: #10263d;
            display: block;
            font-size: 0.82rem;
            font-variant-numeric: tabular-nums;
            margin-top: 1px;
        }
        .hvp-bullpen-card-foot {
            align-items: center;
            color: #5d6b7b;
            display: flex;
            font-size: 0.72rem;
            justify-content: space-between;
        }
        .hvp-player-table-cell {
            align-items: center;
            display: flex;
            gap: 7px;
            min-width: 150px;
        }
        .hvp-player-table-cell img {
            background: #eef2f6;
            border-radius: 50%;
            height: 34px;
            object-fit: cover;
            width: 34px;
        }
        .hvp-empty-table-row td {
            color: #6b7787 !important;
            font-size: 0.82rem !important;
            font-weight: 500 !important;
            padding: 16px !important;
            text-align: left !important;
        }
        @media (max-width: 980px) {
            .hvp-metric-grid { grid-template-columns: repeat(5, minmax(72px, 1fr)); }
            .hvp-metric { border-bottom: 1px solid #e2e8ef; }
        }
        @media (max-width: 760px) {
            .hvp-shell { padding: 12px; }
            .hvp-player-card { min-height: 78px; }
            .hvp-player-card img { height: 54px; width: 54px; }
            .hvp-avatar-blank { height: 54px; width: 54px; }
            .hvp-metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            .hvp-metric { min-height: 54px; padding: 7px 6px; }
            .hvp-metric strong { font-size: 0.95rem; }
            .hvp-metric span { font-size: 0.64rem; }
            .hvp-pa-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            .hvp-pa-stat { border-bottom: 1px solid #e2e8ef; }
            .hvp-bullpen-card-grid,
            .hvp-bullpen-notables { grid-template-columns: 1fr; }
            .hvp-pa-analysis { grid-template-columns: 1fr; }
            .hvp-pa-zone-card { margin: 0 auto; max-width: 340px; width: 100%; }
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
    analysis_mode="Specific Pitcher",
):
    _restore_query_state(selected_date)
    if analysis_mode == "Specific Pitcher":
        st.session_state.hvp_game_pk = None
        st.session_state.hvp_previous_game_pk = None
    _render_hvp_styles()

    batters = bvp_research.player_lookup(batters_df)
    pitchers = bvp_research.player_lookup(pitchers_df)
    selected_game_pk = _state_int("hvp_game_pk")
    selected_batter_id = _state_int("hvp_batter_id")
    selected_pitcher_id = _state_int("hvp_pitcher_id")
    batter_row = batters.get(selected_batter_id, {})
    pitcher_row = pitchers.get(selected_pitcher_id, {})
    if analysis_mode != "Specific Pitcher":
        selected_game_pk = _auto_select_player_game(
            schedule_df,
            batter_row,
        )

    game_row = bvp_research.game_context(schedule_df, selected_game_pk)
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

    _render_selection_header(
        schedule_df,
        batters_df,
        pitchers_df,
        selected_date,
        batters,
        pitchers,
        analysis_mode,
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

    if analysis_mode == "Specific Pitcher":
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
    analysis_mode,
):
    with st.container(key="hvp_selection_header"):
        if analysis_mode != "Specific Pitcher":
            game_opts = bvp_research.game_options(schedule_df)
            game_labels = list(game_opts)
            current_game_pk = _state_int("hvp_game_pk")
            current_batter_id = _state_int("hvp_batter_id")
            current_pitcher_id = _state_int("hvp_pitcher_id")
            batter_selection = batters.get(current_batter_id, {})
            pitcher_selection = pitchers.get(current_pitcher_id, {})
            selected_player_rows = [
                batter_selection or pitcher_selection
            ] if (batter_selection or pitcher_selection) else []
            player_game_pks = []
            for player_row in selected_player_rows:
                for game_pk in bvp_research.scheduled_game_pks_for_player(
                    schedule_df,
                    player_row,
                ):
                    if game_pk not in player_game_pks:
                        player_game_pks.append(game_pk)
            game_index = None
            if current_game_pk in set(game_opts.values()):
                game_index = list(game_opts.values()).index(current_game_pk)
            saved_game_label = st.session_state.get("hvp_game_select")
            if (
                saved_game_label not in game_opts
                or game_opts.get(saved_game_label) != current_game_pk
            ):
                st.session_state.pop("hvp_game_select", None)

            requires_game_choice = current_game_pk is None or len(player_game_pks) > 1
            if requires_game_choice:
                game_col, action_col = st.columns(
                    [3.45, 0.55],
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
                with action_col:
                    st.button(
                        "Reset",
                        key="hvp_reset",
                        use_container_width=True,
                        on_click=_reset_hvp_selection,
                    )
            else:
                game_row = bvp_research.game_context(schedule_df, current_game_pk)
                _render_bullpen_team_banner(game_row, batter_selection)

        current_batter_id = _state_int("hvp_batter_id")
        current_pitcher_id = _state_int("hvp_pitcher_id")
        card_cols = st.columns(
            2 if analysis_mode == "Specific Pitcher" else 1,
            gap="small",
        )
        with card_cols[0], st.container(key="hvp_batter_card"):
            _player_card(current_batter_id, batters.get(current_batter_id, {}), "batter")
            if st.button(
                "Choose batter" if current_batter_id is None else "Change batter",
                key="hvp_open_batter_picker",
                use_container_width=True,
            ):
                _batter_picker_dialog(batters_df)
        if analysis_mode == "Specific Pitcher":
            with card_cols[1], st.container(key="hvp_pitcher_card"):
                _player_card(current_pitcher_id, pitchers.get(current_pitcher_id, {}), "pitcher")
                if st.button(
                    "Choose pitcher" if current_pitcher_id is None else "Change pitcher",
                    key="hvp_open_pitcher_picker",
                    use_container_width=True,
                ):
                    _pitcher_picker_dialog(pitchers_df)


def _render_bullpen_team_banner(game_row, batter_row):
    context = bvp_research.opponent_context_for_batter(game_row, batter_row)
    team_id = context.get("opponent_team_id")
    team_name = context.get("opponent_team") or context.get("opponent_abbr")
    if team_id is None or not team_name:
        return
    logo_url = f"https://www.mlbstatic.com/team-logos/{int(team_id)}.svg"
    st.html(
        '<div class="hvp-bullpen-banner">'
        f'<img src="{escape(logo_url, quote=True)}" alt="{escape(str(team_name), quote=True)} logo">'
        f"<div><strong>{escape(str(team_name))} Bullpen</strong></div>"
        "</div>"
    )


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

    research = _load_specific_research_cached(
        int(batter_id),
        int(pitcher_id),
        int(season),
        database_cache_key,
    )
    summary = research.get("summary", {})
    st.html(
        '<div class="hvp-matchup-heading">'
        f"<strong>{escape(_player_display(batter_row, 'Batter'))} vs "
        f"{escape(_player_display(pitcher_row, 'Pitcher'))}</strong>"
        "</div>"
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
        ]
    )
    _render_matchup_heatmap(summary)
    _render_exact_pitch_table(research.get("comparison_rows", []))
    _render_plate_appearance_logs(
        research.get("plate_appearances", []),
        research.get("pitch_events", []),
    )
    missing_game_logs = research.get("missing_pitch_game_logs", [])
    if missing_game_logs:
        game_logs_json = json.dumps(missing_game_logs, sort_keys=True, default=str)
        backfill_state = _start_specific_history_backfill(
            int(batter_id),
            int(pitcher_id),
            game_logs_json,
        )
        _refresh_specific_history_when_ready(
            backfill_state,
            f"{int(batter_id)}_{int(pitcher_id)}",
        )


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


def _heat_class(value, baseline, higher_is_better=True):
    value = safe_float(value)
    if value is None or baseline in (None, 0):
        return "heat-missing"
    edge = (value - float(baseline)) / abs(float(baseline))
    if not higher_is_better:
        edge *= -1
    if edge >= 0.12:
        return "heat-strong"
    if edge >= 0.03:
        return "heat-good"
    if edge > -0.03:
        return "heat-neutral"
    return "heat-poor"


def _heat_value(value, percent=False):
    value = safe_float(value)
    if value is None:
        return "—"
    if percent:
        return f"{value:.1f}%"
    return f"{value:.3f}".replace("0.", ".")


def _render_matchup_heatmap(summary):
    metrics = (
        ("AVG", 0.250, True, False),
        ("OBP", 0.320, True, False),
        ("SLG", 0.410, True, False),
        ("OPS", 0.730, True, False),
        ("wOBA", 0.315, True, False),
        ("K%", 22.0, False, True),
        ("BB%", 8.0, True, True),
    )
    cells = []
    for label, baseline, higher_is_better, percent in metrics:
        value = safe_float(summary.get(label))
        cells.append(
            f'<div class="hvp-heat-cell {_heat_class(value, baseline, higher_is_better)}">'
            f"<span>{escape(label)}</span><strong>{_heat_value(value, percent=percent)}</strong>"
            "</div>"
        )
    cells.append(
        '<div class="hvp-heat-cell heat-sample">'
        f"<span>Sample</span><strong>{safe_int(summary.get('PA'))} PA</strong></div>"
    )
    st.html(
        '<div class="hvp-heat-shell">'
        '<div class="hvp-heat-title">Matchup Stat Grid</div>'
        f'<div class="hvp-heat-grid">{"".join(cells)}</div></div>'
    )


def _render_exact_pitch_table(rows):
    frame = pd.DataFrame(rows or [])
    if not frame.empty:
        frame["Direct Count"] = pd.to_numeric(frame.get("Direct Count"), errors="coerce")
        frame["Pitcher Count"] = pd.to_numeric(frame.get("Pitcher Count"), errors="coerce")
        frame = frame.sort_values(
            ["Direct Count", "Pitcher Count", "Pitch"],
            ascending=[False, False, True],
            na_position="last",
        )
    columns = (
        ("Direct AVG", "AVG", 0.250, True, False),
        ("Direct SLG", "SLG", 0.410, True, False),
        ("Direct wOBA", "wOBA", 0.315, True, False),
        ("Whiff%", "Whiff%", 25.0, False, True),
        ("CSW%", "CSW%", 27.0, False, True),
    )
    header = "".join(f"<th>{escape(label)}</th>" for _, label, *_ in columns)
    body = []
    for _, row in frame.iterrows():
        cells = []
        for key, _, baseline, higher_is_better, percent in columns:
            value = safe_float(row.get(key))
            cells.append(
                f'<td class="{_heat_class(value, baseline, higher_is_better)}">'
                f"{_heat_value(value, percent=percent)}</td>"
            )
        body.append(
            "<tr>"
            f'<td class="hvp-pitch-name">{escape(str(row.get("Pitch") or "Pitch"))}</td>'
            f'<td class="heat-sample">{safe_int(row.get("Direct Count"))}</td>'
            f'<td class="heat-sample">{safe_int(row.get("At Bats"))}</td>'
            f'<td class="heat-sample">{safe_int(row.get("Balls in Play"))}</td>'
            f"{''.join(cells)}"
            "</tr>"
        )
    if not body:
        body.append(
            '<tr class="hvp-empty-table-row">'
            '<td colspan="9">Pitch-type results will appear here when repertoire '
            "or head-to-head pitch data is available.</td></tr>"
        )
    st.html(
        '<div class="hvp-heat-shell">'
        '<div class="hvp-heat-title">Pitch Type Performance</div>'
        '<div class="hvp-pitch-heat"><table><thead><tr>'
        f"<th>Pitch</th><th>Pitches</th><th>AB</th><th>BIP</th>{header}"
        f"</tr></thead><tbody>{''.join(body)}</tbody></table></div></div>"
    )


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


_BASEBALL_LABELS = {
    "field_out": "Field Out",
    "force_out": "Force Out",
    "grounded_into_double_play": "Grounded Into Double Play",
    "double_play": "Double Play",
    "strikeout": "Strikeout",
    "strikeout_double_play": "Strikeout Double Play",
    "hit_by_pitch": "Hit By Pitch",
    "intent_walk": "Intentional Walk",
    "walk": "Walk",
    "single": "Single",
    "double": "Double",
    "triple": "Triple",
    "home_run": "Home Run",
    "sac_fly": "Sacrifice Fly",
    "sac_bunt": "Sacrifice Bunt",
    "field_error": "Reached On Error",
    "fielders_choice": "Fielder's Choice",
    "called_strike": "Called Strike",
    "swinging_strike": "Swinging Strike",
    "swinging_strike_blocked": "Swinging Strike",
    "foul": "Foul",
    "foul_tip": "Foul Tip",
    "ball": "Ball",
    "blocked_ball": "Blocked Ball",
    "hit_into_play": "Ball In Play",
    "in_play,_out(s)": "Ball In Play, Out",
    "in_play,_no_out": "Ball In Play, Hit",
    "in_play,_run(s)": "Ball In Play, Run",
}


def _humanize_baseball_value(value, fallback=UNAVAILABLE):
    if value is None or str(value).strip() == "":
        return fallback
    text = str(value).strip()
    return _BASEBALL_LABELS.get(
        text.casefold(),
        text.replace("_", " ").replace("-", " ").title(),
    )


def _display_number(value, digits=0, suffix=""):
    number = safe_float(value)
    if number is None:
        return UNAVAILABLE
    rendered = str(int(round(number))) if digits == 0 else f"{number:.{digits}f}"
    return f"{rendered}{suffix}"


def _format_pa_date(value):
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value or UNAVAILABLE)
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"


def _inning_label(value):
    inning = safe_int(value)
    if inning <= 0:
        return "Inning unavailable"
    if 10 <= inning % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(inning % 10, "th")
    return f"{inning}{suffix} inning"


def _pa_pitch_rows(pa, pitch_events_by_pa):
    key = (pa.get("game_pk"), pa.get("at_bat_number"))
    pitches = pitch_events_by_pa.get(key, pa.get("pitches", [])) or []
    return sorted(pitches, key=lambda row: safe_int(row.get("pitch_number")))


def _pa_zone_fallback(zone):
    zone = safe_int(zone)
    centers = {
        1: (52, 36),
        2: (85, 36),
        3: (118, 36),
        4: (52, 78),
        5: (85, 78),
        6: (118, 78),
        7: (52, 119),
        8: (85, 119),
        9: (118, 119),
        11: (18, 20),
        12: (152, 20),
        13: (18, 145),
        14: (152, 145),
    }
    return centers.get(zone)


def _pa_zone_coordinates(pitch):
    plate_x = safe_float(pitch.get("plate_x"))
    plate_z = safe_float(pitch.get("plate_z"))
    if plate_x is None or plate_z is None:
        return _pa_zone_fallback(pitch.get("zone"))
    x = 85.0 + (plate_x * 60.0)
    y = 77.5 - (((plate_z - 2.525) / 1.95) * 125.0)
    return max(8.0, min(162.0, x)), max(7.0, min(153.0, y))


def _pa_pitch_tone(pitch):
    description = str(pitch.get("pitch_description") or "").casefold()
    if "in_play" in description or "hit_into_play" in description:
        return "in-play"
    if "foul" in description:
        return "foul"
    if "ball" in description or "pitchout" in description:
        return "ball"
    if "strike" in description:
        return "strike"
    return "unknown"


def _pa_strike_zone_html(pitches):
    markers = []
    for index, pitch in enumerate(pitches, start=1):
        coordinates = _pa_zone_coordinates(pitch)
        if coordinates is None:
            continue
        x, y = coordinates
        number = safe_int(pitch.get("pitch_number")) or index
        pitch_name = (
            pitch.get("pitch_name")
            or bvp_research.pitch_name_for_code(pitch.get("pitch_type"))
            or "Pitch"
        )
        result = _humanize_baseball_value(pitch.get("pitch_description"), "Pitch")
        velocity = _display_number(pitch.get("release_speed"), 1, " mph")
        title = f"Pitch {number}, {pitch_name}, {velocity}, {result}"
        markers.append(
            f'<circle class="hvp-pa-zone-pitch {_pa_pitch_tone(pitch)}" '
            f'cx="{x:.1f}" cy="{y:.1f}" r="8"><title>{escape(title)}</title></circle>'
            f'<text class="hvp-pa-zone-number" x="{x:.1f}" y="{y:.1f}">{number}</text>'
        )
    empty_note = (
        ""
        if markers
        else '<div class="hvp-pa-zone-empty">Pitch locations are not available.</div>'
    )
    return (
        '<div class="hvp-pa-zone-card">'
        '<div class="hvp-pa-zone-title">Strike Zone</div>'
        '<svg class="hvp-pa-zone-svg" viewBox="0 0 170 160" '
        'role="img" aria-label="Strike zone pitch locations">'
        '<rect class="hvp-pa-zone-box" x="35" y="15" width="100" height="125"/>'
        '<line class="hvp-pa-zone-grid" x1="68.3" y1="15" x2="68.3" y2="140"/>'
        '<line class="hvp-pa-zone-grid" x1="101.7" y1="15" x2="101.7" y2="140"/>'
        '<line class="hvp-pa-zone-grid" x1="35" y1="56.7" x2="135" y2="56.7"/>'
        '<line class="hvp-pa-zone-grid" x1="35" y1="98.3" x2="135" y2="98.3"/>'
        f'{"".join(markers)}</svg>{empty_note}</div>'
    )


def _pa_summary_html(pa):
    items = (
        ("Final count", pa.get("final_count") or UNAVAILABLE),
        ("Pitches", _display_number(pa.get("pitch_count"))),
        ("Runs batted in", _display_number(pa.get("rbi"))),
        ("Exit velocity", _display_number(pa.get("launch_speed"), 1, " mph")),
        ("Launch angle", _display_number(pa.get("launch_angle"), 1, " deg")),
        ("Distance", _display_number(pa.get("estimated_distance"), 0, " ft")),
    )
    cells = "".join(
        '<div class="hvp-pa-stat">'
        f"<span>{escape(label)}</span><strong>{escape(str(value))}</strong>"
        "</div>"
        for label, value in items
    )
    return f'<div class="hvp-pa-summary">{cells}</div>'


_HIT_RESULTS = {"single", "double", "triple", "home_run"}
_OUT_RESULTS = {
    "field_out",
    "force_out",
    "grounded_into_double_play",
    "double_play",
    "strikeout",
    "strikeout_double_play",
    "sac_fly",
    "sac_bunt",
    "fielders_choice_out",
    "other_out",
}


def _decisive_pitch_row_class(pa_result):
    result = str(pa_result or "").strip().casefold()
    if result in _HIT_RESULTS:
        return "hvp-pitch-row-hit"
    if result in _OUT_RESULTS:
        return "hvp-pitch-row-out"
    return ""


def _pitch_table_html(pitches, pa_result=None):
    rows = []
    decisive_class = _decisive_pitch_row_class(pa_result)
    for index, pitch in enumerate(pitches):
        pitch_name = (
            pitch.get("pitch_name")
            or bvp_research.pitch_name_for_code(pitch.get("pitch_type"))
            or UNAVAILABLE
        )
        velocity = _display_number(pitch.get("release_speed"), 1, " mph")
        count = f"{safe_int(pitch.get('balls'))}-{safe_int(pitch.get('strikes'))}"
        result = _humanize_baseball_value(pitch.get("pitch_description"))
        row_class = decisive_class if index == len(pitches) - 1 else ""
        rows.append(
            f'<tr class="{row_class}">'
            f'<td class="hvp-cell-primary">{safe_int(pitch.get("pitch_number"))}</td>'
            f"<td>{escape(count)}</td>"
            f'<td class="hvp-cell-primary">{escape(str(pitch_name))}</td>'
            f"<td>{escape(velocity)}</td>"
            f"<td>{escape(result)}</td>"
            "</tr>"
        )
    return (
        '<div class="hvp-table-wrap"><table class="hvp-standard-table">'
        "<thead><tr><th>#</th><th>Count</th><th>Pitch</th><th>Velocity</th>"
        "<th>Result</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_plate_appearance_logs(plate_appearances, pitch_events):
    st.markdown("#### Career Matchup At Bats")
    if not plate_appearances:
        st.info(
            "No pitch locations are available for this pair yet. "
            "Career game level BvP can still be present above while pitch level Statcast is pending."
        )
        return
    pitch_events_by_pa = {}
    for pitch in pitch_events or []:
        pitch_events_by_pa.setdefault(
            (pitch.get("game_pk"), pitch.get("at_bat_number")),
            [],
        ).append(pitch)
    for index, pa in enumerate(plate_appearances[:80], start=1):
        result = pa.get("pa_result") or pa.get("event") or "Completed PA"
        pitches = _pa_pitch_rows(pa, pitch_events_by_pa)
        pitch_count = safe_int(pa.get("pitch_count")) or len(pitches)
        label = (
            f"{_format_pa_date(pa.get('game_date'))}, {_inning_label(pa.get('inning'))}: "
            f"{_humanize_baseball_value(result)} ({pitch_count} "
            f"{'pitch' if pitch_count == 1 else 'pitches'})"
        )
        with st.expander(label):
            st.html(_pa_summary_html(pa))
            if pitches:
                st.markdown(
                    '<div class="hvp-pa-analysis">'
                    f"{_pa_strike_zone_html(pitches)}"
                    f"{_pitch_table_html(pitches, result)}"
                    "</div>",
                    unsafe_allow_html=True,
                )
            elif index == 1:
                st.markdown(
                    _pa_strike_zone_html([]),
                    unsafe_allow_html=True,
                )


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
            opponent_context.get("probable_pitcher_id"),
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
    grade = str(composite.get("overall_grade") or "No Data")
    grade_class = "difficult" if "difficult" in grade.lower() else "neutral" if "neutral" in grade.lower() or "no data" in grade.lower() else ""
    st.html(
        '<div class="hvp-bullpen-overview">'
        "<strong>Bullpen Matchup Overview</strong>"
        f'<span class="hvp-grade {grade_class}">{escape(grade)}</span>'
        "</div>"
    )
    _metric_grid(
        [
            ("Projected AVG", composite.get("projected_AVG"), 3),
            ("Projected OBP", composite.get("projected_OBP"), 3),
            ("Projected SLG", composite.get("projected_SLG"), 3),
            ("Projected wOBA", composite.get("projected_wOBA"), 3),
            ("Projected K%", composite.get("projected_K%"), 1, True),
            ("Projected BB%", composite.get("projected_BB%"), 1, True),
            ("Matchup score", composite.get("overall_score"), 1),
            ("Relievers", composite.get("active_relievers_included"), 0),
        ]
    )
    notables = (
        ("Most likely to appear", composite.get("most_likely")),
        ("Best matchup for batter", composite.get("most_favorable")),
        ("Toughest matchup", composite.get("most_difficult")),
    )
    st.html(
        '<div class="hvp-bullpen-notables">'
        + "".join(
            '<div class="hvp-bullpen-notable">'
            f"<span>{escape(label)}</span>"
            f"<strong>{escape(str(value or UNAVAILABLE))}</strong>"
            "</div>"
            for label, value in notables
        )
        + "</div>"
    )
    with st.expander("How this projection is built"):
        st.write(
            "Relievers are weighted by projected appearance probability, availability score, expected batters faced, "
            "and role. Direct BvP is visible but shrunk toward larger evidence: batter vs hand, batter vs exact pitch mix, "
            "pitcher allowed profile where available, then league-style baseline. Limited or unavailable pitchers are "
            "discounted from the composite by default."
        )
        st.caption(
            f"Confidence: {composite.get('confidence') or UNAVAILABLE}. {roster_note}"
        )


def _bullpen_stat(value, digits=2, percent=False):
    if safe_float(value) is None:
        return UNAVAILABLE
    return fmt_metric(value, digits=digits, percent=percent)


def _bullpen_cards_html(frame):
    cards = []
    for _, row in frame.head(6).iterrows():
        player_id = safe_int(row.get("player_id"))
        name = str(row.get("Player") or "Pitcher")
        image_url = player_headshot_url(player_id, width=96)
        role = _humanize_baseball_value(row.get("projected_role"), "Reliever")
        hand = str(row.get("Throws") or "").strip()
        player_meta = f"{role}, throws {hand}" if hand else role
        stats = (
            ("ERA", _bullpen_stat(row.get("ERA"), 2)),
            ("WHIP", _bullpen_stat(row.get("WHIP"), 2)),
            ("K%", _bullpen_stat(row.get("K%"), 1, True)),
            ("IP", _bullpen_stat(row.get("IP"), 1)),
        )
        probability = _bullpen_stat(
            (safe_float(row.get("appearance_probability")) or 0) * 100,
            0,
            True,
        )
        stat_cells = "".join(
            '<div class="hvp-bullpen-player-stat">'
            f"<span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
            for label, value in stats
        )
        cards.append(
            '<div class="hvp-bullpen-card">'
            '<div class="hvp-bullpen-card-head">'
            f'<img src="{escape(image_url, quote=True)}" alt="{escape(name, quote=True)} headshot">'
            f"<div><strong>{escape(name)}</strong>"
            f"<span>{escape(player_meta)}</span></div></div>"
            f'<div class="hvp-bullpen-player-stats">{stat_cells}</div>'
            '<div class="hvp-bullpen-card-foot">'
            f"<span>{escape(probability)} appearance chance</span>"
            f"<strong>{escape(str(row.get('matchup_grade') or UNAVAILABLE))}</strong>"
            "</div></div>"
        )
    return f'<div class="hvp-bullpen-card-grid">{"".join(cards)}</div>'


def _bullpen_table_html(frame):
    rows = []
    for _, row in frame.iterrows():
        player_id = safe_int(row.get("player_id"))
        name = str(row.get("Player") or "Pitcher")
        image_url = player_headshot_url(player_id, width=72)
        probability = _bullpen_stat(
            (safe_float(row.get("appearance_probability")) or 0) * 100,
            0,
            True,
        )
        rows.append(
            "<tr>"
            '<td><div class="hvp-player-table-cell">'
            f'<img src="{escape(image_url, quote=True)}" alt="">'
            f'<span class="hvp-cell-primary">{escape(name)}</span></div></td>'
            f"<td>{escape(_bullpen_stat(row.get('ERA'), 2))}</td>"
            f"<td>{escape(_bullpen_stat(row.get('WHIP'), 2))}</td>"
            f"<td>{escape(_bullpen_stat(row.get('K%'), 1, True))}</td>"
            f"<td>{escape(_bullpen_stat(row.get('IP'), 1))}</td>"
            f"<td>{escape(_humanize_baseball_value(row.get('projected_role'), 'Reliever'))}</td>"
            f"<td>{escape(probability)}</td>"
            f"<td>{escape(str(row.get('availability_label') or UNAVAILABLE))}</td>"
            f"<td>{escape(str(row.get('matchup_grade') or UNAVAILABLE))}</td>"
            f"<td>{escape(_bullpen_stat(row.get('projected_wOBA'), 3))}</td>"
            f"<td>{safe_int(row.get('Direct PA'))}</td>"
            f'<td class="hvp-cell-muted">{escape(str(row.get("primary_pitches") or UNAVAILABLE))}</td>'
            "</tr>"
        )
    return (
        '<div class="hvp-table-wrap"><table class="hvp-standard-table">'
        "<thead><tr><th>Pitcher</th><th>ERA</th><th>WHIP</th><th>K%</th><th>IP</th>"
        "<th>Role</th><th>Chance</th><th>Availability</th><th>Matchup</th>"
        "<th>Projected wOBA</th><th>Direct PA</th><th>Primary pitches</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_bullpen_table(relievers):
    st.html(
        '<div class="hvp-matchup-heading">'
        "<strong>Projected Relievers</strong>"
        "</div>"
    )
    if not relievers:
        st.info("No projected relievers were found for the selected game.")
        return

    frame = pd.DataFrame(relievers)
    hands = sorted(value for value in frame["Throws"].dropna().unique() if value)
    filter_cols = st.columns([1, 1, 1, 1] if hands else [1, 1, 1], gap="small")
    role_filter = filter_cols[0].multiselect(
        "Role",
        sorted(frame["projected_role"].dropna().unique()),
        key="hvp_bullpen_role_filter",
    )
    hand_filter = []
    next_filter = 1
    if hands:
        hand_filter = filter_cols[1].multiselect(
            "Throws",
            hands,
            key="hvp_bullpen_hand_filter",
        )
        next_filter = 2
    availability_filter = filter_cols[next_filter].multiselect(
        "Availability",
        sorted(frame["availability_label"].dropna().unique()),
        key="hvp_bullpen_availability_filter",
    )
    min_probability = filter_cols[next_filter + 1].slider(
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
    if filtered.empty:
        st.info("No relievers match the selected filters.")
        return

    st.html(_bullpen_cards_html(filtered))
    st.html(_bullpen_table_html(filtered))

    for _, row in filtered.head(18).iterrows():
        label = (
            f"{row.get('Player')}, {_humanize_baseball_value(row.get('projected_role'), 'Reliever')}, "
            f"{row.get('availability_label')}, {row.get('matchup_grade')}"
        )
        with st.expander(label):
            st.caption(row.get("availability_reason") or "No availability note is stored.")
            st.write(row.get("matchup_reason") or "No matchup note is stored.")
            exact_rows = row.get("exact_pitch_rows")
            if exact_rows:
                _render_exact_pitch_table(exact_rows)
            else:
                st.caption("No exact pitch-type BvP rows are stored for this reliever yet.")


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
