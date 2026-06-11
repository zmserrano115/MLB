from datetime import timedelta
from html import escape
import json
import os
from pathlib import Path
import uuid

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.mlb_schedule import get_daily_schedule
from src import weather as weather_service
from src.stat_data import (
    get_batter_stats,
    get_pitcher_stats,
    get_batter_vs_pitcher_game_log,
    get_pitcher_vs_team_game_log,
)
from src.matchups import (
    build_batter_vs_pitcher_matchups,
    build_batter_vs_hand_matchups,
    build_pitcher_k_matchups,
)
from src.injuries import add_injury_columns, fetch_injury_report
from src.recent_form import build_recent_bar_chart_html
from src import database
from src.time_utils import current_app_date


st.set_page_config(
    page_title="All Rise Analytics",
    layout="wide",
    initial_sidebar_state="collapsed",
)

RESEARCH_TABLE_COMPONENT = components.declare_component(
    "research_table",
    path=str(Path(__file__).parent / "components" / "research_table"),
)

TEAM_ID_BY_NAME = {
    "Arizona Diamondbacks": 109,
    "Atlanta Braves": 144,
    "Baltimore Orioles": 110,
    "Boston Red Sox": 111,
    "Chicago Cubs": 112,
    "Chicago White Sox": 145,
    "Cincinnati Reds": 113,
    "Cleveland Guardians": 114,
    "Colorado Rockies": 115,
    "Detroit Tigers": 116,
    "Houston Astros": 117,
    "Kansas City Royals": 118,
    "Los Angeles Angels": 108,
    "Los Angeles Dodgers": 119,
    "Miami Marlins": 146,
    "Milwaukee Brewers": 158,
    "Minnesota Twins": 142,
    "New York Mets": 121,
    "New York Yankees": 147,
    "Athletics": 133,
    "Oakland Athletics": 133,
    "Philadelphia Phillies": 143,
    "Pittsburgh Pirates": 134,
    "San Diego Padres": 135,
    "San Francisco Giants": 137,
    "Seattle Mariners": 136,
    "St. Louis Cardinals": 138,
    "Tampa Bay Rays": 139,
    "Texas Rangers": 140,
    "Toronto Blue Jays": 141,
    "Washington Nationals": 120,
}

TEAM_ID_BY_ABBR = {
    "ARI": 109,
    "AZ": 109,
    "ATL": 144,
    "BAL": 110,
    "BOS": 111,
    "CHC": 112,
    "CWS": 145,
    "CIN": 113,
    "CLE": 114,
    "COL": 115,
    "DET": 116,
    "HOU": 117,
    "KC": 118,
    "KCR": 118,
    "LAA": 108,
    "LAD": 119,
    "MIA": 146,
    "MIL": 158,
    "MIN": 142,
    "NYM": 121,
    "NYY": 147,
    "ATH": 133,
    "OAK": 133,
    "PHI": 143,
    "PIT": 134,
    "SD": 135,
    "SDP": 135,
    "SF": 137,
    "SFG": 137,
    "SEA": 136,
    "STL": 138,
    "TB": 139,
    "TBR": 139,
    "TEX": 140,
    "TOR": 141,
    "WSH": 120,
}


st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Manrope:wght@400;500;600;700&display=swap');

    :root {
        --bg: #f3f5f7;
        --nav: #06172b;
        --panel: #ffffff;
        --text: #111827;
        --muted: #526171;
        --muted-2: #7b8794;
        --line: #d8dee6;
        --font-body: "Manrope", "Segoe UI", Helvetica, sans-serif;
        --font-display: "Bebas Neue", "Arial Narrow", sans-serif;
    }

    html, body, .stApp {
        font-family: var(--font-body) !important;
    }

    .stApp {
        background:
            linear-gradient(180deg, rgba(6, 23, 43, 0.035), rgba(243, 245, 247, 0) 360px),
            repeating-linear-gradient(
                135deg,
                rgba(6, 23, 43, 0.018) 0px,
                rgba(6, 23, 43, 0.018) 1px,
                transparent 1px,
                transparent 18px
            ),
            var(--bg);
        color: var(--text);
    }

    .block-container {
        padding-top: 4.6rem;
        padding-bottom: 2.2rem;
        max-width: 1480px;
    }

    h1, h2, h3, h4, h5, h6,
    p, li, span, label, div {
        font-family: var(--font-body);
    }

    header[data-testid="stHeader"] {
        background: var(--nav);
        border-bottom: 1px solid rgba(255,255,255,0.12);
        height: 58px;
    }

    header[data-testid="stHeader"]::before {
        content: "All Rise Analytics";
        position: fixed;
        top: 12px;
        left: 78px;
        color: #ffffff;
        font-family: var(--font-display) !important;
        font-size: 28px;
        font-weight: 400;
        letter-spacing: 0.02em;
        z-index: 999999;
        pointer-events: none;
    }

    header[data-testid="stHeader"]::after {
        content: "";
        display: none;
    }

    header[data-testid="stHeader"] button,
    header[data-testid="stHeader"] button *,
    div[data-testid="collapsedControl"] button,
    div[data-testid="collapsedControl"] button *,
    div[data-testid="collapsedControl"] svg,
    button[data-testid="baseButton-header"],
    button[data-testid="baseButton-header"] * {
        color: #ffffff !important;
        fill: #ffffff !important;
        stroke: #ffffff !important;
    }

    .section-shell {
        margin: 18px 0 10px 0;
        padding: 0;
        border: 0;
        background: transparent;
    }

    .section-label,
    .metric-label {
        color: var(--muted-2);
        font-size: 11px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.09em;
        margin-bottom: 6px;
    }

    .section-title {
        color: var(--text);
        font-family: var(--font-body) !important;
        font-size: 22px;
        line-height: 1.15;
        font-weight: 500;
        letter-spacing: 0.01em;
        margin-bottom: 0;
    }

    .title-date {
        color: #64748b !important;
        font-size: 17px;
        font-weight: 500;
        letter-spacing: 0.01em;
        margin-left: 8px;
    }

    .slate-strip {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        border: 1px solid var(--line);
        background: var(--panel);
        margin: 0 0 16px 0;
    }

    .slate-item {
        min-height: 72px;
        padding: 12px 15px;
        border-right: 1px solid var(--line);
        display: flex;
        flex-direction: column;
        justify-content: center;
    }

    .slate-item:last-child {
        border-right: 0;
    }

    .slate-value {
        color: var(--text);
        font-size: 22px;
        font-weight: 500;
        line-height: 1.08;
        letter-spacing: 0;
        margin-top: 4px;
    }

    .status-box,
    .disclaimer-box {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 0;
        padding: 14px 16px;
        margin: 12px 0 16px 0;
        color: var(--muted);
        font-size: 14px;
        line-height: 1.65;
        box-shadow: none;
    }

    .schedule-weather-table {
        border: 1px solid var(--line);
        background: var(--panel);
        margin-bottom: 12px;
        overflow: visible;
    }

    .schedule-weather-head,
    .schedule-weather-row {
        display: grid;
        grid-template-columns: 130px minmax(210px, 1.2fr) minmax(150px, 0.8fr) 110px 100px;
        align-items: center;
        column-gap: 12px;
        padding: 10px 14px;
    }

    .schedule-weather-head {
        background: #eef2f6;
        border-bottom: 1px solid var(--line);
        color: var(--muted);
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.07em;
        text-transform: uppercase;
    }

    .schedule-weather-row {
        position: relative;
        min-height: 58px;
        border-bottom: 1px solid var(--line);
        color: var(--text);
        font-size: 13px;
    }

    .schedule-weather-row:has(.schedule-tooltip:hover),
    .schedule-weather-row:has(.schedule-tooltip:focus-visible) {
        z-index: 20;
    }

    .schedule-weather-row:last-child {
        border-bottom: 0;
    }

    .schedule-game-logos,
    .schedule-weather-chip,
    .schedule-wind-chip {
        display: inline-flex;
        align-items: center;
        gap: 8px;
    }

    .schedule-game-logos img {
        width: 30px;
        height: 30px;
        object-fit: contain;
    }

    .schedule-at {
        color: var(--muted);
        font-weight: 700;
    }

    .schedule-pitchers {
        line-height: 1.45;
    }

    .schedule-pitchers span,
    .schedule-venue span {
        display: block;
        color: var(--muted);
        font-size: 11px;
    }

    .schedule-weather-chip,
    .schedule-wind-chip {
        cursor: help;
        position: relative;
        width: fit-content;
        border-bottom: 1px dotted #7b8794;
        font-size: 17px;
        font-weight: 600;
        white-space: nowrap;
    }

    .schedule-weather-chip {
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }

    .weather-svg {
        flex: 0 0 auto;
    }

    .schedule-tooltip:hover::after,
    .schedule-tooltip:focus-visible::after {
        content: attr(data-tooltip);
        position: absolute;
        z-index: 1000;
        left: 0;
        bottom: calc(100% + 9px);
        width: min(300px, 70vw);
        padding: 9px 11px;
        border: 1px solid #c8d1dc;
        background: #ffffff;
        color: #263445;
        font-size: 12px;
        font-weight: 500;
        line-height: 1.45;
        white-space: normal;
        box-shadow: 0 8px 24px rgba(15, 31, 48, 0.14);
        pointer-events: none;
    }

    .schedule-wind-arrow {
        color: #87919c;
        font-size: 24px;
        font-weight: 700;
        line-height: 1;
    }

    .schedule-weather-edge {
        display: block;
        margin-top: 3px;
        color: var(--muted);
        font-size: 10px;
        font-weight: 600;
        white-space: nowrap;
    }

    .schedule-hover-note {
        color: var(--muted-2);
        font-size: 11px;
        margin: -3px 0 14px 0;
    }

    .research-table-note {
        color: var(--muted);
        font-size: 11px;
        margin: -3px 0 8px 0;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        border-bottom: 1px solid var(--line);
        padding-bottom: 0;
    }

    .stTabs [data-baseweb="tab"] {
        height: 42px;
        border-radius: 0;
        padding-left: 20px;
        padding-right: 20px;
        color: var(--muted);
        background: transparent;
        font-weight: 500;
        letter-spacing: 0.01em;
    }

    .stTabs [aria-selected="true"] {
        color: var(--text) !important;
        background: var(--panel) !important;
        border: 1px solid var(--line) !important;
        border-bottom: 1px solid var(--panel) !important;
    }

    .stButton > button {
        border-radius: 0;
        border: 1px solid var(--line);
        background: #eef3f8;
        color: var(--text);
        font-weight: 500;
        box-shadow: none;
    }

    .stButton > button:hover {
        border-color: #b9c3cf;
        background: #e2eaf3;
        color: var(--text);
    }

    @media (max-width: 680px) {
        .st-key-matchup_toolbar [data-testid="stHorizontalBlock"] {
            display: grid !important;
            grid-template-columns: 44px minmax(0, 1fr) 44px !important;
            gap: 8px !important;
        }

        .st-key-matchup_toolbar [data-testid="stColumn"] {
            width: 100% !important;
            min-width: 0 !important;
            flex: none !important;
        }

        .st-key-matchup_toolbar [data-testid="stColumn"]:nth-child(1),
        .st-key-matchup_toolbar [data-testid="stColumn"]:nth-child(2),
        .st-key-matchup_toolbar [data-testid="stColumn"]:nth-child(3) {
            grid-column: 1 / -1;
        }

        .st-key-matchup_toolbar [data-testid="stColumn"]:nth-child(4) {
            grid-column: 1;
            grid-row: 4;
        }

        .st-key-matchup_toolbar [data-testid="stColumn"]:nth-child(5) {
            grid-column: 2;
            grid-row: 4;
        }

        .st-key-matchup_toolbar [data-testid="stColumn"]:nth-child(6) {
            grid-column: 3;
            grid-row: 4;
        }
    }

    @media (max-width: 900px) {
        .block-container {
            padding-top: 4.4rem;
        }

        .slate-strip {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .slate-item {
            border-bottom: 1px solid var(--line);
        }

        .slate-item:nth-child(2) {
            border-right: 0;
        }

        .slate-item:nth-child(3),
        .slate-item:nth-child(4) {
            border-bottom: 0;
        }

        .schedule-weather-head,
        .schedule-weather-row {
            grid-template-columns: 110px 85px 78px;
        }

        .schedule-weather-head > :nth-child(2),
        .schedule-weather-row > :nth-child(2),
        .schedule-weather-head > :nth-child(3),
        .schedule-weather-row > :nth-child(3) {
            display: none;
        }

        .research-table-note {
            line-height: 1.45;
            margin-bottom: 6px;
        }

    }
    </style>
    """,
    unsafe_allow_html=True,
)


def format_display_date(value):
    try:
        return pd.to_datetime(value).strftime("%m/%d/%y")
    except Exception:
        return str(value)


def team_logo_url(team_value):
    if team_value is None or pd.isna(team_value):
        return ""

    team_value = str(team_value).strip()
    team_id = TEAM_ID_BY_NAME.get(team_value)

    if team_id is None:
        team_id = TEAM_ID_BY_ABBR.get(team_value.upper())

    if team_id is None:
        return ""

    return f"https://www.mlbstatic.com/team-logos/team-cap-on-light/{team_id}.svg"


def weather_icon_svg(icon_name, size=18, padding=0):
    paths = {
        "clear": (
            "<circle cx='12' cy='12' r='4'/>"
            "<path d='M12 2v2M12 20v2M4.93 4.93l1.42 1.42"
            "M17.66 17.66l1.41 1.41M2 12h2M20 12h2"
            "M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41'/>"
        ),
        "partly-cloudy": (
            "<path d='M8.5 5.5A4 4 0 0 1 16 7.5'/>"
            "<path d='M5 9H4a3 3 0 0 0 0 6h13a4 4 0 0 0 0-8"
            " 5.5 5.5 0 0 0-10.6 2'/>"
        ),
        "cloudy": (
            "<path d='M5 18h12a4 4 0 0 0 .4-7.98"
            "A6 6 0 0 0 6.1 8.4 4.5 4.5 0 0 0 5 18Z'/>"
        ),
        "rain": (
            "<path d='M5 15h12a4 4 0 0 0 .4-7.98"
            "A6 6 0 0 0 6.1 5.4 4.5 4.5 0 0 0 5 15Z'/>"
            "<path d='M8 18l-1 3M13 18l-1 3M18 18l-1 3'/>"
        ),
        "storm": (
            "<path d='M5 14h12a4 4 0 0 0 .4-7.98"
            "A6 6 0 0 0 6.1 4.4 4.5 4.5 0 0 0 5 14Z'/>"
            "<path d='m13 15-3 5h3l-1 3 4-6h-3l1-2'/>"
        ),
        "snow": (
            "<path d='M5 14h12a4 4 0 0 0 .4-7.98"
            "A6 6 0 0 0 6.1 4.4 4.5 4.5 0 0 0 5 14Z'/>"
            "<path d='M8 18v4M6.3 19l3.4 2M9.7 19l-3.4 2"
            "M16 18v4M14.3 19l3.4 2M17.7 19l-3.4 2'/>"
        ),
        "fog": (
            "<path d='M5 13h12a4 4 0 0 0 .4-7.98"
            "A6 6 0 0 0 6.1 3.4 4.5 4.5 0 0 0 5 13Z'/>"
            "<path d='M4 17h16M6 21h12'/>"
        ),
        "unknown": (
            "<circle cx='12' cy='12' r='9'/>"
            "<path d='M9.8 9a2.3 2.3 0 1 1 3.3 2.1"
            "c-.8.4-1.1.9-1.1 1.9M12 17h.01'/>"
        ),
    }

    icon_paths = paths.get(str(icon_name or "unknown"), paths["unknown"])
    viewbox_size = 24 + (padding * 2)

    return (
        "<svg class='weather-svg' xmlns='http://www.w3.org/2000/svg' "
        f"viewBox='{-padding} {-padding} {viewbox_size} {viewbox_size}' "
        f"width='{size}' height='{size}' fill='none' "
        "stroke='#617083' stroke-width='1.7' stroke-linecap='round' "
        f"stroke-linejoin='round'>{icon_paths}</svg>"
    )


def add_game_column(df):
    if df.empty:
        return df

    df = df.copy()

    if "game" not in df.columns and "away_team" in df.columns and "home_team" in df.columns:
        df["game"] = df["away_team"].astype(str) + " @ " + df["home_team"].astype(str)

    return df


def get_game_options(schedule_df):
    if schedule_df.empty:
        return ["All Games"]

    schedule_df = add_game_column(schedule_df)

    if "game" not in schedule_df.columns:
        return ["All Games"]

    games = schedule_df["game"].dropna().unique().tolist()
    games = sorted(games)

    return ["All Games"] + games


def filter_by_game(df, selected_game):
    if df.empty or selected_game == "All Games":
        return df

    if "game" not in df.columns:
        return df

    return df[df["game"] == selected_game].copy()


def get_player_options(dataframes, columns):
    names = set()
    for dataframe in dataframes:
        if dataframe is None or dataframe.empty:
            continue
        for column in columns:
            if column not in dataframe.columns:
                continue
            names.update(
                str(value).strip()
                for value in dataframe[column].dropna()
                if str(value).strip()
            )
    return sorted(names, key=str.casefold)


def filter_by_players(df, selected_batter=None, selected_pitcher=None):
    if df.empty:
        return df

    result = df
    if selected_batter and "batter" in result.columns:
        result = result[result["batter"] == selected_batter]

    if selected_pitcher:
        pitcher_column = None
        if "opposing_pitcher" in result.columns:
            pitcher_column = "opposing_pitcher"
        elif "pitcher" in result.columns:
            pitcher_column = "pitcher"
        if pitcher_column:
            result = result[result[pitcher_column] == selected_pitcher]

    return result.copy()


def is_missing_value(value):
    if value is None:
        return True

    try:
        if pd.isna(value):
            return True
    except Exception:
        pass

    if str(value).strip() == "":
        return True

    return False


def render_schedule_weather_table(df):
    if df.empty:
        st.info("No games are available for this selection.")
        return

    rows = []
    for _, row in df.iterrows():
        away_team = str(row.get("away_team") or "")
        home_team = str(row.get("home_team") or "")
        away_logo = team_logo_url(away_team)
        home_logo = team_logo_url(home_team)
        away_pitcher = str(row.get("away_probable_pitcher") or "TBD")
        home_pitcher = str(row.get("home_probable_pitcher") or "TBD")
        away_hand = str(row.get("away_pitcher_hand") or "")
        home_hand = str(row.get("home_pitcher_hand") or "")
        venue = str(row.get("venue_name") or "Venue TBD")
        roof = str(row.get("roof_type") or "Roof unknown")
        weather_icon_name = str(row.get("weather_icon") or "unknown")
        weather_svg = weather_icon_svg(weather_icon_name, size=22)  
        weather_display = str(row.get("weather_display") or "?")      
        wind_arrow = str(row.get("wind_arrow") or "\u00b7")
        weather_edge = str(row.get("weather_edge") or "Neutral")
        wind_speed = pd.to_numeric(row.get("wind_speed_mph"), errors="coerce")
        wind_speed_text = (
            f"{float(wind_speed):.0f} mph" if pd.notna(wind_speed) else "N/A"
        )
        weather_tooltip = escape(
            str(row.get("weather_tooltip") or "Forecast unavailable."),
            quote=True,
        )
        wind_tooltip = escape(
            str(row.get("wind_tooltip") or "Wind forecast unavailable."),
            quote=True,
        )

        away_pitcher_text = escape(away_pitcher)
        if away_hand:
            away_pitcher_text += f" ({escape(away_hand)})"
        home_pitcher_text = escape(home_pitcher)
        if home_hand:
            home_pitcher_text += f" ({escape(home_hand)})"

        rows.append(
            f"""
            <div class="schedule-weather-row">
                <div class="schedule-game-logos">
                    <img src="{escape(away_logo, quote=True)}"
                         alt="{escape(away_team, quote=True)}"
                         title="{escape(away_team, quote=True)}">
                    <span class="schedule-at">@</span>
                    <img src="{escape(home_logo, quote=True)}"
                         alt="{escape(home_team, quote=True)}"
                         title="{escape(home_team, quote=True)}">
                </div>
                <div class="schedule-pitchers">
                    {away_pitcher_text}
                    <span>{home_pitcher_text}</span>
                </div>
                <div class="schedule-venue">
                    {escape(venue)}
                    <span>{escape(roof)}</span>
                </div>
                <div>
                    <span class="schedule-weather-chip schedule-tooltip"
                          data-tooltip="{weather_tooltip}" tabindex="0">
                        {weather_svg}
                        <span>{escape(weather_display)}</span>
                    </span>
                    <span class="schedule-weather-edge">{escape(weather_edge)}</span>
                </div>
                <div>
                    <span class="schedule-wind-chip schedule-tooltip"
                          data-tooltip="{wind_tooltip}" tabindex="0">
                        <span class="schedule-wind-arrow">{escape(wind_arrow)}</span>
                        {escape(wind_speed_text)}
                    </span>
                </div>
            </div>
            """
        )

    st.html(
        f"""
        <div class="schedule-weather-table">
            <div class="schedule-weather-head">
                <div>Game</div>
                <div>Probable Pitchers</div>
                <div>Ballpark</div>
                <div>Weather</div>
                <div>Wind</div>
            </div>
            {''.join(rows)}
        </div>
        <div class="schedule-hover-note">
            Hover the weather or wind values for the full forecast and matchup meaning.
        </div>
        """
    )


def matchup_grade_class(grade):
    value = str(grade or "").lower()
    if "strong" in value or "good" in value or "elite" in value:
        return "good"
    if "neutral" in value:
        return "neutral"
    if "avoid" in value:
        return "avoid"
    if "sample" in value:
        return "sample"
    return "none"


RESEARCH_COLUMN_LABELS = {
    "game_date": "Date",
    "batter": "Batter",
    "pitcher": "Pitcher",
    "opponent": "Opponent",
    "home_away": "H/A",
    "Pitch Count": "PC",
    "split": "Split",
    "opposing_pitcher": "Pitcher",
    "opposing_pitcher_hand": "Hand",
    "pitcher_hand": "Hand",
    "Season IP": "Season IP",
    "Projected IP": "Proj IP",
    "Projected Pitch Count": "Proj PC",
    "Projected Ks": "Proj K",
    "Projected Hits": "Proj H",
    "opponent_avg_k%": "Opp K%",
    "weather_condition": "Weather",
    "weather_display": "Temp",
    "humidity_pct": "Humidity",
    "precip_probability_pct": "Rain",
    "wind_speed_mph": "Wind mph",
    "wind_direction_cardinal": "Wind Dir",
    "wind_field_direction": "Field Wind",
    "wind_out_mph": "Out mph",
    "weather_edge": "Weather Edge",
    "matchup_grade": "Grade",
    "k_matchup_score": "K Score",
    "k_matchup_grade": "Grade",
}

RESEARCH_COLUMN_WIDTHS = {
    "game_date": 82,
    "home_away": 54,
    "Pitch Count": 58,
    "opposing_pitcher": 130,
    "opposing_pitcher_hand": 54,
    "pitcher_hand": 54,
    "opponent": 110,
    "split": 70,
    "weather_condition": 105,
    "weather_display": 58,
    "humidity_pct": 68,
    "precip_probability_pct": 58,
    "wind_speed_mph": 70,
    "wind_direction_cardinal": 66,
    "wind_field_direction": 82,
    "wind_out_mph": 66,
    "weather_edge": 130,
    "matchup_grade": 108,
    "k_matchup_grade": 108,
}

INTEGER_RESEARCH_COLUMNS = {
    "PA",
    "AB",
    "H",
    "TB",
    "BB",
    "HBP",
    "SO",
    "HR",
    "RBI",
    "GS",
    "BF",
    "R",
    "ER",
    "Projected Pitch Count",
}
THREE_DECIMAL_RESEARCH_COLUMNS = {"AVG", "OBP", "SLG", "OPS"}
TWO_DECIMAL_RESEARCH_COLUMNS = {
    "K%",
    "BB%",
    "ERA",
    "WHIP",
    "K/9",
    "SwStr%",
    "opponent_avg_k%",
    "Projected IP",
    "Projected Ks",
    "Projected Hits",
    "k_matchup_score",
}
ONE_DECIMAL_RESEARCH_COLUMNS = {"Season IP"}
PERCENT_RESEARCH_COLUMNS = {"humidity_pct", "precip_probability_pct"}
RESEARCH_SORT_ALIASES = {
    "weather_display": "temperature_f",
    "weather_edge": "hitter_weather_adjustment",
    "matchup_grade": "weather_adjusted_score",
    "k_matchup_grade": "k_matchup_score",
}


def research_cell_value(column, value):
    if is_missing_value(value):
        return "-"

    number = pd.to_numeric(value, errors="coerce")
    if column in INTEGER_RESEARCH_COLUMNS and pd.notna(number):
        return f"{float(number):.0f}"
    if column in THREE_DECIMAL_RESEARCH_COLUMNS and pd.notna(number):
        return f"{float(number):.3f}"
    if column in TWO_DECIMAL_RESEARCH_COLUMNS and pd.notna(number):
        return f"{float(number):.2f}"
    if column in ONE_DECIMAL_RESEARCH_COLUMNS and pd.notna(number):
        return f"{float(number):.1f}"
    if column in PERCENT_RESEARCH_COLUMNS and pd.notna(number):
        return f"{float(number):.0f}%"
    if column == "wind_speed_mph" and pd.notna(number):
        return f"{float(number):.0f}"
    if column == "wind_out_mph" and pd.notna(number):
        return f"{float(number):+.1f}"
    return str(value)


def research_game_html(game):
    game_text = str(game or "")
    if " vs " in game_text:
        first_team, second_team = game_text.split(" vs ", 1)
        separator = "vs"
    elif " @ " in game_text:
        first_team, second_team = game_text.split(" @ ", 1)
        separator = "@"
    else:
        first_team, second_team = game_text, ""
        separator = "@"
    first_logo = team_logo_url(first_team)
    second_logo = team_logo_url(second_team)
    return (
        '<span class="research-game">'
        f'<img src="{escape(first_logo, quote=True)}" '
        f'alt="{escape(first_team, quote=True)}" title="{escape(first_team, quote=True)}">'
        f'<span class="research-at">{separator}</span>'
        f'<img src="{escape(second_logo, quote=True)}" '
        f'alt="{escape(second_team, quote=True)}" title="{escape(second_team, quote=True)}">'
        "</span>"
    )


def player_perspective_game(game, player_team):
    game_text = str(game or "").strip()
    if " @ " not in game_text:
        return game_text

    away_team, home_team = game_text.split(" @ ", 1)
    if str(player_team or "").strip() == home_team:
        return f"{home_team} vs {away_team}"
    return f"{away_team} @ {home_team}"


def research_log_payload(row, log_type):
    if log_type == "pitcher":
        payload = {
            "log_type": "pitcher",
            "pitcher_id": row.get("pitcher_id"),
            "pitcher": row.get("pitcher"),
            "opponent": row.get("opponent"),
        }
    else:
        payload = {
            "log_type": "bvp",
            "batter_id": row.get("batter_id"),
            "opposing_pitcher_id": row.get("opposing_pitcher_id"),
            "batter": row.get("batter"),
            "opposing_pitcher": row.get("opposing_pitcher"),
        }
    clean_payload = {}
    for key, value in payload.items():
        if is_missing_value(value):
            continue
        if key.endswith("_id"):
            numeric_value = pd.to_numeric(value, errors="coerce")
            if pd.notna(numeric_value):
                value = int(numeric_value)
        clean_payload[key] = value
    return clean_payload


def research_injury_badge_html(row):
    tooltip = row.get("injury_tooltip")
    if is_missing_value(tooltip):
        return ""
    tooltip = escape(str(tooltip), quote=True)
    return (
        '<span class="research-injury-badge" tabindex="0" '
        f'aria-label="{tooltip}" title="{tooltip}" '
        f'data-tooltip="{tooltip}">inj</span>'
    )


def research_edge_class(value):
    edge = str(value or "").lower()
    if "hitter boost" in edge:
        return "hitter"
    if "pitcher boost" in edge:
        return "pitcher"
    return "neutral"


def research_sort_metadata(row, column):
    sort_column = RESEARCH_SORT_ALIASES.get(column, column)
    value = row.get(sort_column)
    if is_missing_value(value):
        return "", "missing"

    numeric_value = pd.to_numeric(value, errors="coerce")
    if pd.notna(numeric_value):
        return str(float(numeric_value)), "number"
    return str(value).strip().lower(), "text"


def render_research_table(df, columns, player_column, log_type, table_key):
    header_cells = [
        '<th class="sticky-game"></th>',
        '<th class="sticky-player align-left" aria-sort="none">'
        f'<button type="button" class="research-sort-button" data-column-index="1">'
        f"<span>{escape(player_column.title())}</span>"
        '<span class="research-sort-indicator" aria-hidden="true"></span>'
        "</button></th>",
    ]
    data_columns = [
        column
        for column in columns
        if column not in {"game", player_column}
    ]
    for column in data_columns:
        label = RESEARCH_COLUMN_LABELS.get(column, column)
        width = RESEARCH_COLUMN_WIDTHS.get(column, 62)
        header_classes = []
        if column in {
            "opposing_pitcher",
            "opponent",
            "split",
            "weather_condition",
            "wind_direction_cardinal",
            "wind_field_direction",
            "weather_edge",
            "matchup_grade",
            "k_matchup_grade",
        }:
            header_classes.append("align-left")
        if column in {"matchup_grade", "k_matchup_grade"}:
            header_classes.append("sticky-grade")
        header_cells.append(
            f'<th class="{" ".join(header_classes)}" '
            f'style="min-width:{width}px" '
            'aria-sort="none">'
            f'<button type="button" class="research-sort-button" '
            f'data-column-index="{len(header_cells)}">'
            f"<span>{escape(label)}</span>"
            '<span class="research-sort-indicator" aria-hidden="true"></span>'
            "</button></th>"
        )

    body_rows = []
    for _, row in df.iterrows():
        player_name = str(row.get(player_column) or "Unknown")
        player_team_column = (
            "pitcher_team"
            if player_column == "pitcher"
            else "team"
        )
        display_game = player_perspective_game(
            row.get("game"),
            row.get(player_team_column),
        )
        player_payload = json.dumps(
            research_log_payload(row, log_type),
            separators=(",", ":"),
        )
        player_sort_value, player_sort_kind = research_sort_metadata(
            row,
            player_column,
        )
        cells = [
            f'<td class="sticky-game">{research_game_html(display_game)}</td>',
            '<td class="sticky-player" '
            f'data-sort-value="{escape(player_sort_value, quote=True)}" '
            f'data-sort-kind="{player_sort_kind}">'
            '<button type="button" class="research-player-link" '
            f'data-research-event="{escape(player_payload, quote=True)}">'
            f"{escape(player_name)}</button>"
            f"{research_injury_badge_html(row)}</td>",
        ]
        for column in data_columns:
            value = row.get(column)
            sort_value, sort_kind = research_sort_metadata(row, column)
            cell_classes = []
            if column in {
                "opposing_pitcher",
                "opponent",
                "split",
                "weather_condition",
                "wind_direction_cardinal",
                "wind_field_direction",
                "weather_edge",
                "matchup_grade",
                "k_matchup_grade",
            }:
                cell_classes.append("align-left")
            if column in {"matchup_grade", "k_matchup_grade"}:
                cell_classes.append("sticky-grade")
            if column == "weather_condition":
                icon = weather_icon_svg(row.get("weather_icon"), size=17)
                tooltip = escape(
                    str(row.get("weather_tooltip") or ""),
                    quote=True,
                )
                content = (
                    f'<span class="research-weather" title="{tooltip}">'
                    f"{icon}<span>{escape(research_cell_value(column, value))}</span>"
                    "</span>"
                )
            elif column in {
                "wind_speed_mph",
                "wind_direction_cardinal",
                "wind_field_direction",
                "wind_out_mph",
            }:
                tooltip = escape(
                    str(row.get("wind_tooltip") or ""),
                    quote=True,
                )
                content = (
                    f'<span title="{tooltip}">'
                    f"{escape(research_cell_value(column, value))}</span>"
                )
            elif column == "weather_edge":
                content = (
                    f'<span class="research-edge {research_edge_class(value)}">'
                    f"{escape(research_cell_value(column, value))}</span>"
                )
            elif column in {"matchup_grade", "k_matchup_grade"}:
                grade_class = matchup_grade_class(value)
                content = (
                    f'<span class="research-grade {grade_class}">'
                    f"{escape(research_cell_value(column, value))}</span>"
                )
            else:
                content = escape(research_cell_value(column, value))
            cells.append(
                f'<td class="{" ".join(cell_classes)}" '
                f'data-sort-value="{escape(sort_value, quote=True)}" '
                f'data-sort-kind="{sort_kind}">{content}</td>'
            )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    return RESEARCH_TABLE_COMPONENT(
        table_html=f"""
        <div class="research-table-shell" id="{escape(table_key, quote=True)}">
            <table class="research-table">
                <thead><tr>{''.join(header_cells)}</tr></thead>
                <tbody>{''.join(body_rows)}</tbody>
            </table>
        </div>
        """,
        table_height=542,
        key=table_key,
        default=None,
    )


def game_log_date_display(value):
    parsed_date = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed_date):
        return research_cell_value("game_date", value)
    return parsed_date.strftime("%m/%d/%y")


def game_log_matchup_html(row, log_type):
    team = str(row.get("team") or "")
    opponent = str(row.get("opponent") or "")
    if team and opponent:
        if str(row.get("home_away") or "").lower() == "home":
            game = f"{opponent} @ {team}"
        else:
            game = f"{team} @ {opponent}"
        return research_game_html(game)

    logo = team_logo_url(opponent)
    return (
        '<span class="research-log-opponent">'
        f'<img src="{escape(logo, quote=True)}" '
        f'alt="{escape(opponent, quote=True)}" '
        f'title="{escape(opponent, quote=True)}">'
        f"<span>{escape(opponent)}</span>"
        "</span>"
    )


def render_game_log_table(game_log_df, columns, log_type, table_key):
    identity_label = "Matchup"
    header_cells = [
        '<th class="sticky-game" aria-sort="none">'
        '<button type="button" class="research-sort-button" data-column-index="0">'
        '<span>Date</span>'
        '<span class="research-sort-indicator" aria-hidden="true"></span>'
        "</button></th>",
        '<th class="sticky-player align-left" aria-sort="none">'
        '<button type="button" class="research-sort-button" data-column-index="1">'
        f"<span>{identity_label}</span>"
        '<span class="research-sort-indicator" aria-hidden="true"></span>'
        "</button></th>",
    ]
    data_columns = [
        column
        for column in columns
        if column
        not in {
            "game_date",
            "team_logo",
            "team",
            "opponent_logo",
            "opponent",
        }
    ]
    for column in data_columns:
        label = RESEARCH_COLUMN_LABELS.get(column, column)
        width = RESEARCH_COLUMN_WIDTHS.get(column, 62)
        align_class = "align-left" if column == "home_away" else ""
        header_cells.append(
            f'<th class="{align_class}" style="min-width:{width}px" '
            'aria-sort="none">'
            f'<button type="button" class="research-sort-button" '
            f'data-column-index="{len(header_cells)}">'
            f"<span>{escape(label)}</span>"
            '<span class="research-sort-indicator" aria-hidden="true"></span>'
            "</button></th>"
        )

    body_rows = []
    for _, row in game_log_df.iterrows():
        date_sort_value, date_sort_kind = research_sort_metadata(
            row,
            "game_date",
        )
        opponent_sort_value, opponent_sort_kind = research_sort_metadata(
            row,
            "opponent",
        )
        cells = [
            '<td class="sticky-game" '
            f'data-sort-value="{escape(date_sort_value, quote=True)}" '
            f'data-sort-kind="{date_sort_kind}">'
            f"{escape(game_log_date_display(row.get('game_date')))}</td>",
            '<td class="sticky-player" '
            f'data-sort-value="{escape(opponent_sort_value, quote=True)}" '
            f'data-sort-kind="{opponent_sort_kind}">'
            f"{game_log_matchup_html(row, log_type)}</td>",
        ]
        for column in data_columns:
            value = row.get(column)
            sort_value, sort_kind = research_sort_metadata(row, column)
            align_class = "align-left" if column == "home_away" else ""
            cells.append(
                f'<td class="{align_class}" '
                f'data-sort-value="{escape(sort_value, quote=True)}" '
                f'data-sort-kind="{sort_kind}">'
                f"{escape(research_cell_value(column, value))}</td>"
            )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    table_height = min(540, max(112, 40 + (len(game_log_df) * 36)))
    RESEARCH_TABLE_COMPONENT(
        table_html=f"""
        <div class="research-table-shell game-log-table-shell"
             id="{escape(table_key, quote=True)}">
            <table class="research-table game-log-table">
                <thead><tr>{''.join(header_cells)}</tr></thead>
                <tbody>{''.join(body_rows)}</tbody>
            </table>
        </div>
        """,
        table_height=table_height,
        key=table_key,
        default=None,
    )


def selected_log_from_event(table_key, event):
    selected_key = f"{table_key}_selected_log"
    event_key = f"{table_key}_processed_event"
    if isinstance(event, dict) and event.get("type") == "select_player":
        event_id = str(event.get("event_id") or "")
        payload = event.get("payload")
        if (
            event_id
            and event_id != st.session_state.get(event_key)
            and isinstance(payload, dict)
        ):
            st.session_state[event_key] = event_id
            st.session_state[selected_key] = payload
    return st.session_state.get(selected_key)


def render_selected_research_log(table_key, selected_log):
    if selected_log is None:
        return

    if st.button(
        "Close game log",
        key=f"{table_key}_close_log",
        type="tertiary",
    ):
        st.session_state[f"{table_key}_selected_log"] = None
        return

    if selected_log.get("log_type") == "pitcher":
        display_pitcher_vs_team_game_log(selected_log)
    else:
        display_bvp_game_log(selected_log)


def display_bvp_game_log(selected_row):
    batter_name = selected_row.get("batter")
    pitcher_name = selected_row.get("opposing_pitcher")
    batter_id = selected_row.get("batter_id")
    pitcher_id = selected_row.get("opposing_pitcher_id")

    st.markdown(
        f"""
        <div class="section-shell game-log-heading">
            <div class="section-label">Career Game Log</div>
            <div class="section-title">
                {escape(str(batter_name))} vs {escape(str(pitcher_name))}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if is_missing_value(batter_id) or is_missing_value(pitcher_id):
        st.warning("Player ID was not found for this row.")
        return

    with st.spinner("Loading career batter-vs-pitcher game log..."):
        game_log_df = get_batter_vs_pitcher_game_log(
            int(batter_id),
            int(pitcher_id),
        )

    if game_log_df.empty:
        st.warning("No individual career game-log history was found for this matchup.")
        return

    if "team" in game_log_df.columns:
        game_log_df["team_logo"] = game_log_df["team"].apply(team_logo_url)

    if "opponent" in game_log_df.columns:
        game_log_df["opponent_logo"] = game_log_df["opponent"].apply(team_logo_url)

    game_log_cols = [
        "game_date",
        "team_logo",
        "team",
        "opponent_logo",
        "opponent",
        "home_away",
        "PA",
        "AB",
        "H",
        "TB",
        "BB",
        "HBP",
        "SO",
        "HR",
        "RBI",
        "AVG",
        "OBP",
        "SLG",
        "OPS",
        "K%",
        "BB%",
    ]

    game_log_cols = [col for col in game_log_cols if col in game_log_df.columns]

    render_game_log_table(
        game_log_df[game_log_cols],
        game_log_cols,
        log_type="bvp",
        table_key=f"bvp-game-log-{int(batter_id)}-{int(pitcher_id)}",
    )
    chart_html = build_recent_bar_chart_html(
        game_log_df,
        value_column="TB",
        title="Total Bases - Last 5 Meetings",
        subtitle=f"{batter_name} vs {pitcher_name}",
        scale_floor=4,
        accent="#245f96",
    )
    if chart_html:
        st.html(chart_html)


def display_pitcher_vs_team_game_log(selected_row):
    pitcher_name = selected_row.get("pitcher")
    opponent_team = selected_row.get("opponent")
    pitcher_id = selected_row.get("pitcher_id")

    st.markdown(
        f"""
        <div class="section-shell game-log-heading">
            <div class="section-label">Career Game Log</div>
            <div class="section-title">
                {escape(str(pitcher_name))} vs {escape(str(opponent_team))}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if is_missing_value(pitcher_id):
        st.warning("Pitcher ID was not found for this row.")
        return

    with st.spinner("Loading pitcher-vs-team career game log..."):
        game_log_df = get_pitcher_vs_team_game_log(
            pitcher_id=int(pitcher_id),
            opponent_team=opponent_team,
        )

    if game_log_df.empty:
        st.warning("No pitcher-vs-team career game-log history was found for this matchup.")
        return

    if "opponent" in game_log_df.columns:
        game_log_df["opponent_logo"] = game_log_df["opponent"].apply(team_logo_url)

    game_log_cols = [
        "game_date",
        "team",
        "opponent_logo",
        "opponent",
        "home_away",
        "IP",
        "Pitch Count",
        "BF",
        "H",
        "BB",
        "HBP",
        "SO",
        "HR",
        "R",
    ]

    game_log_cols = [col for col in game_log_cols if col in game_log_df.columns]

    render_game_log_table(
        game_log_df[game_log_cols],
        game_log_cols,
        log_type="pitcher",
        table_key=f"pitcher-game-log-{int(pitcher_id)}-{opponent_team}",
    )
    chart_html = build_recent_bar_chart_html(
        game_log_df,
        value_column="SO",
        title="Strikeouts - Last 5 Appearances",
        subtitle=f"{pitcher_name} vs {opponent_team}",
        scale_floor=10,
        accent="#173f67",
    )
    if chart_html:
        st.html(chart_html)


@st.fragment
def render_bvp_table_fragment(filtered_bvp_matchups):
    if filtered_bvp_matchups.empty:
        st.warning("No batter vs pitcher matchup data was found for this selection.")
        return

    bvp_cols = [
        "game",
        "batter",
        "opposing_pitcher",
        "opposing_pitcher_hand",
        "PA",
        "AB",
        "H",
        "BB",
        "HBP",
        "SO",
        "HR",
        "RBI",
        "AVG",
        "OBP",
        "SLG",
        "OPS",
        "K%",
        "BB%",
        "weather_condition",
        "weather_display",
        "humidity_pct",
        "precip_probability_pct",
        "wind_speed_mph",
        "wind_direction_cardinal",
        "wind_field_direction",
        "wind_out_mph",
        "weather_edge",
        "matchup_grade",
    ]
    bvp_cols = [
        column for column in bvp_cols if column in filtered_bvp_matchups.columns
    ]

    with st.popover("Minimum sample"):
        min_bvp_pa = st.slider(
            "Minimum PA vs Pitcher",
            min_value=0,
            max_value=50,
            value=0,
            step=1,
            key="bvp_min_pa",
        )

    display_bvp = filtered_bvp_matchups[
        filtered_bvp_matchups["PA"] >= min_bvp_pa
    ].copy()

    display_bvp = display_bvp.reset_index(drop=True)

    st.html(
        f'<div class="research-table-note">Showing {len(display_bvp):,} '
        'matchups. Click a batter name '
        "to open the career game log.</div>"
    )
    table_event = render_research_table(
        display_bvp,
        bvp_cols,
        player_column="batter",
        log_type="bvp",
        table_key="bvp-research-table",
    )
    render_selected_research_log(
        "bvp-research-table",
        selected_log_from_event("bvp-research-table", table_event),
    )


@st.fragment
def render_hand_table_fragment(filtered_hand_matchups):
    if filtered_hand_matchups.empty:
        st.warning("No batter vs pitcher-hand split data was found for this selection.")
        return

    hand_cols = [
        "game",
        "batter",
        "opposing_pitcher",
        "opposing_pitcher_hand",
        "split",
        "PA",
        "AB",
        "H",
        "BB",
        "HBP",
        "SO",
        "HR",
        "RBI",
        "AVG",
        "OBP",
        "SLG",
        "OPS",
        "K%",
        "BB%",
        "weather_condition",
        "weather_display",
        "humidity_pct",
        "precip_probability_pct",
        "wind_speed_mph",
        "wind_direction_cardinal",
        "wind_field_direction",
        "wind_out_mph",
        "weather_edge",
        "matchup_grade",
    ]
    hand_cols = [
        column for column in hand_cols if column in filtered_hand_matchups.columns
    ]

    with st.popover("Minimum sample"):
        min_hand_pa = st.slider(
            "Minimum PA vs Throwing Hand",
            min_value=0,
            max_value=300,
            value=0,
            step=5,
            key="hand_min_pa_all_default",
        )

        min_hand_obp = st.slider(
            "Minimum OBP vs Throwing Hand",
            min_value=0.000,
            max_value=0.500,
            value=0.000,
            step=0.005,
            key="hand_min_obp_all_default",
        )

    display_hand = filtered_hand_matchups[
        (filtered_hand_matchups["PA"] >= min_hand_pa)
        & (filtered_hand_matchups["OBP"] >= min_hand_obp)
    ].copy()

    display_hand = display_hand.reset_index(drop=True)

    st.html(
        f'<div class="research-table-note">Showing {len(display_hand):,} '
        'matchups. Click a batter name '
        "to open the game log against today's probable pitcher.</div>"
    )
    table_event = render_research_table(
        display_hand,
        hand_cols,
        player_column="batter",
        log_type="bvp",
        table_key="hand-research-table",
    )
    render_selected_research_log(
        "hand-research-table",
        selected_log_from_event("hand-research-table", table_event),
    )


@st.fragment
def render_pitcher_table_fragment(filtered_pitcher_k_matchups):
    if filtered_pitcher_k_matchups.empty:
        st.warning("No pitcher strikeout matchups were created for this selection.")
        return

    required_projected_cols = [
        "Projected IP",
        "Projected Pitch Count",
        "Projected Ks",
        "Projected Hits",
    ]
    missing_projected_cols = [
        col
        for col in required_projected_cols
        if col not in filtered_pitcher_k_matchups.columns
    ]
    if missing_projected_cols:
        st.warning(
            "The cloud data has not been refreshed with the newest pitcher projection columns yet. "
            "Run the GitHub Action refresh, then reboot the Streamlit app."
        )

    k_cols = [
        "game",
        "pitcher",
        "pitcher_hand",
        "opponent",
        "Season IP",
        "GS",
        "Projected IP",
        "Projected Pitch Count",
        "Projected Ks",
        "Projected Hits",
        "ERA",
        "WHIP",
        "K%",
        "K/9",
        "SwStr%",
        "opponent_avg_k%",
        "weather_condition",
        "weather_display",
        "humidity_pct",
        "precip_probability_pct",
        "wind_speed_mph",
        "wind_direction_cardinal",
        "wind_field_direction",
        "wind_out_mph",
        "weather_edge",
        "k_matchup_score",
        "k_matchup_grade",
    ]
    k_cols = [
        column for column in k_cols if column in filtered_pitcher_k_matchups.columns
    ]

    display_k = filtered_pitcher_k_matchups.reset_index(drop=True)

    st.html(
        f'<div class="research-table-note">Showing {len(display_k):,} '
        'matchups. Click a pitcher name '
        "to open the career opponent game log.</div>"
    )
    table_event = render_research_table(
        display_k,
        k_cols,
        player_column="pitcher",
        log_type="pitcher",
        table_key="pitcher-research-table",
    )
    render_selected_research_log(
        "pitcher-research-table",
        selected_log_from_event("pitcher-research-table", table_event),
    )


app_today = current_app_date()
try:
    if "MLB_DB_URL" in st.secrets:
        os.environ.setdefault("MLB_DB_URL", st.secrets["MLB_DB_URL"])
except Exception:
    pass
database.init_database()


if "selected_game_date" not in st.session_state:
    st.session_state.selected_game_date = app_today
if "data_snapshot_id" not in st.session_state:
    st.session_state.data_snapshot_id = uuid.uuid4().hex


def shift_selected_date(days):
    st.session_state.selected_game_date += timedelta(days=days)


with st.container(key="matchup_toolbar"):
    toolbar_columns = st.columns(
        [2.2, 1.45, 2.2, 0.42, 1.6, 0.42],
        gap="small",
        vertical_alignment="bottom",
    )
    with toolbar_columns[0]:
        batter_filter_slot = st.empty()
    with toolbar_columns[1]:
        game_filter_slot = st.empty()
    with toolbar_columns[2]:
        pitcher_filter_slot = st.empty()
    with toolbar_columns[3]:
        st.button(
            "\u2039",
            key="previous_game_date",
            help="Previous day",
            on_click=shift_selected_date,
            args=(-1,),
            use_container_width=True,
        )
    with toolbar_columns[4]:
        selected_date = st.date_input(
            "Game Date",
            key="selected_game_date",
            label_visibility="collapsed",
        )
    with toolbar_columns[5]:
        st.button(
            "\u203a",
            key="next_game_date",
            help="Next day",
            on_click=shift_selected_date,
            args=(1,),
            use_container_width=True,
        )

season = selected_date.year
min_pa = 0
force_refresh = False
data_snapshot_id = st.session_state.data_snapshot_id


@st.cache_data(show_spinner=True)
def load_schedule(game_date, snapshot_id):
    return get_daily_schedule(str(game_date))


@st.cache_data(show_spinner=True)
def load_weather(schedule, snapshot_id, cache_version):
    return weather_service.enrich_schedule_with_weather(schedule)


@st.cache_data(show_spinner=False)
def load_injuries(team_ids, game_date, snapshot_id):
    return fetch_injury_report(team_ids, game_date)


def load_published_weather(cache_version, snapshot_id):
    fetcher = getattr(
        weather_service,
        "fetch_published_weather_cache",
        None,
    )
    if not fetcher:
        return pd.DataFrame()
    return fetcher(
        cache_bust=f"{app_today.isoformat()}-{cache_version}-{snapshot_id}",
    )


def merge_published_weather(current_df, cached_df):
    merger = getattr(weather_service, "merge_cached_weather", None)
    return merger(current_df, cached_df) if merger else current_df


def preserve_previous_weather(current_df, previous_df):
    if (
        current_df is None
        or current_df.empty
        or previous_df is None
        or previous_df.empty
        or "game_pk" not in current_df.columns
        or "game_pk" not in previous_df.columns
    ):
        return current_df

    result = current_df.copy()
    previous_by_game = previous_df.drop_duplicates("game_pk").set_index("game_pk")
    weather_columns = [
        column
        for column in previous_df.columns
        if column.startswith(("weather_", "wind_"))
        or column
        in {
            "forecast_time_utc",
            "temperature_f",
            "humidity_pct",
            "precip_probability_pct",
            "surface_pressure_hpa",
            "air_density_kg_m3",
            "hitter_weather_adjustment",
            "pitcher_weather_adjustment",
        }
    ]

    for index, row in result.iterrows():
        if row.get("weather_status") == "Forecast available":
            continue

        game_pk = row.get("game_pk")
        if game_pk not in previous_by_game.index:
            continue

        previous = previous_by_game.loc[game_pk]
        if previous.get("weather_status") != "Forecast available":
            continue

        for column in weather_columns:
            result.at[index, column] = previous.get(column)
        result.at[index, "weather_source"] = "Last successful forecast"

    return result


@st.cache_data(show_spinner=True)
def load_batter_stats(season, force_refresh, snapshot_id):
    return get_batter_stats(season, force_refresh=force_refresh)


@st.cache_data(show_spinner=True)
def load_pitcher_stats(season, force_refresh, snapshot_id):
    return get_pitcher_stats(season, force_refresh=force_refresh)


if force_refresh:
    load_schedule.clear()
    load_weather.clear()
    load_injuries.clear()

schedule_df = load_schedule(selected_date, data_snapshot_id)

if schedule_df.empty:
    st.warning("No MLB games found for this date.")
    st.stop()

published_weather = load_published_weather(
    cache_version=3,
    snapshot_id=data_snapshot_id,
)
cached_schedule_df = merge_published_weather(
    schedule_df,
    published_weather,
)
cached_weather_available = cached_schedule_df.get(
    "weather_status",
    pd.Series(dtype=str),
).eq("Forecast available")

if len(cached_schedule_df) and cached_weather_available.all():
    schedule_df = cached_schedule_df
else:
    schedule_df = load_weather(
        schedule_df,
        data_snapshot_id,
        cache_version=5,
    )
    schedule_df = merge_published_weather(
        schedule_df,
        published_weather,
    )
weather_session_cache = st.session_state.setdefault(
    "last_successful_weather_by_date",
    {},
)
weather_cache_key = str(selected_date)
schedule_df = preserve_previous_weather(
    schedule_df,
    weather_session_cache.get(weather_cache_key),
)
if schedule_df.get(
    "weather_status",
    pd.Series(dtype=str),
).eq("Forecast available").any():
    weather_session_cache[weather_cache_key] = schedule_df.copy()

weather_available = schedule_df.get(
    "weather_status",
    pd.Series(dtype=str),
).eq("Forecast available")
if len(schedule_df) and not weather_available.any():
    published_error = published_weather.attrs.get("weather_error")
    runtime_errors = schedule_df.get(
        "weather_error",
        pd.Series(dtype=str),
    ).dropna()
    error_detail = published_error
    if not runtime_errors.empty:
        error_detail = runtime_errors.iloc[0]
    message = (
        "Game-time weather could not be loaded from the published forecast, "
        "Open-Meteo, MET Norway, or MLB StatsAPI."
    )
    if error_detail:
        message += f" Provider detail: {error_detail}"
    st.error(message)
batters_df = load_batter_stats(season, force_refresh, data_snapshot_id)
pitchers_df = load_pitcher_stats(season, force_refresh, data_snapshot_id)

cloud_status_html = """
<div class="status-box">
    <b>Data Mode:</b> Live pitchers, stadium weather, and SQLite history<br>
    Browser refresh loads the latest probable pitchers and game-time forecasts.
    Completed-game matchup and pitcher history comes from the local database.
</div>
"""

with st.spinner("Building batter vs pitcher matchups..."):
    bvp_matchups = build_batter_vs_pitcher_matchups(
        schedule_df=schedule_df,
        batters_df=batters_df,
        season=season,
        min_pa=min_pa,
    )

with st.spinner("Building batter vs pitcher hand matchups..."):
    hand_matchups = build_batter_vs_hand_matchups(
        schedule_df=schedule_df,
        batters_df=batters_df,
        season=season,
        min_pa=min_pa,
    )

with st.spinner("Building pitcher strikeout matchups..."):
    pitcher_k_matchups = build_pitcher_k_matchups(
        schedule_df=schedule_df,
        batters_df=batters_df,
        pitchers_df=pitchers_df,
        min_pa=min_pa,
    )

schedule_team_ids = tuple(
    sorted(
        {
            int(team_id)
            for column in ("away_team_id", "home_team_id")
            for team_id in schedule_df.get(
                column,
                pd.Series(dtype=float),
            ).dropna()
        }
    )
)
injury_report = load_injuries(
    schedule_team_ids,
    selected_date,
    data_snapshot_id,
)
bvp_matchups = add_injury_columns(
    bvp_matchups,
    "batter_id",
    injury_report,
)
hand_matchups = add_injury_columns(
    hand_matchups,
    "batter_id",
    injury_report,
)
pitcher_k_matchups = add_injury_columns(
    pitcher_k_matchups,
    "pitcher_id",
    injury_report,
)


if schedule_df.empty:
    st.warning("No schedule data available.")
    st.stop()


schedule_df = add_game_column(schedule_df)
game_options = get_game_options(schedule_df)
batter_options = get_player_options(
    [bvp_matchups, hand_matchups],
    ["batter"],
)
pitcher_options = get_player_options(
    [bvp_matchups, hand_matchups, pitcher_k_matchups],
    ["opposing_pitcher", "pitcher"],
)

if st.session_state.get("selected_batter") not in [None, *batter_options]:
    st.session_state.selected_batter = None
if st.session_state.get("selected_pitcher") not in [None, *pitcher_options]:
    st.session_state.selected_pitcher = None
if st.session_state.get("selected_game") not in game_options:
    st.session_state.selected_game = "All Games"

selected_batter = batter_filter_slot.selectbox(
    "Batter",
    batter_options,
    index=None,
    placeholder="Batter...",
    key="selected_batter",
    label_visibility="collapsed",
)
selected_game = game_filter_slot.selectbox(
    "Game",
    game_options,
    key="selected_game",
    label_visibility="collapsed",
)
selected_pitcher = pitcher_filter_slot.selectbox(
    "Pitcher",
    pitcher_options,
    index=None,
    placeholder="Pitcher...",
    key="selected_pitcher",
    label_visibility="collapsed",
)

filtered_schedule_df = filter_by_game(schedule_df, selected_game)
filtered_bvp_matchups = filter_by_players(
    filter_by_game(bvp_matchups, selected_game),
    selected_batter,
    selected_pitcher,
)
filtered_hand_matchups = filter_by_players(
    filter_by_game(hand_matchups, selected_game),
    selected_batter,
    selected_pitcher,
)
filtered_pitcher_k_matchups = filter_by_players(
    filter_by_game(pitcher_k_matchups, selected_game),
    selected_batter,
    selected_pitcher,
)


display_game_date = format_display_date(selected_date)


main_tab, matchup_tab, info_tab = st.tabs(
    [
        "Overview",
        "Matchups",
        "Details",
    ]
)


with main_tab:

    selected_game_display = selected_game if selected_game != "All Games" else "Full slate"

    st.markdown(
        f"""
        <div class="slate-strip">
            <div class="slate-item">
                <div class="metric-label">Games</div>
                <div class="slate-value">{len(schedule_df)}</div>
            </div>
            <div class="slate-item">
                <div class="metric-label">BvP Rows</div>
                <div class="slate-value">{len(filtered_bvp_matchups)}</div>
            </div>
            <div class="slate-item">
                <div class="metric-label">K Targets</div>
                <div class="slate-value">{len(filtered_pitcher_k_matchups)}</div>
            </div>
            <div class="slate-item">
                <div class="metric-label">Current View</div>
                <div class="slate-value">{selected_game_display}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="section-shell">
            <div class="section-label">Schedule</div>
            <div class="section-title">Today's Games <span class="title-date">{display_game_date}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_schedule_weather_table(filtered_schedule_df)


with matchup_tab:
    st.markdown(
        """
        <div class="section-shell">
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3 = st.tabs(
        [
            "Hitter vs Pitcher",
            "Hitter vs Throwing Hand",
            "Strikeout Targets",
        ]
    )

    with tab1:
        render_bvp_table_fragment(filtered_bvp_matchups)

    with tab2:
        render_hand_table_fragment(filtered_hand_matchups)

    with tab3:
        render_pitcher_table_fragment(filtered_pitcher_k_matchups)

with info_tab:
    st.markdown(
        """
        <div class="section-shell">
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        ### How the matchup tables work

        **Hitter vs Pitcher**
        - Direct hitter history against today's probable pitcher.

        **Hitter vs Throwing Hand**
        - Hitter split against right-handed or left-handed pitchers.

        **Strikeout Targets**
        - Uses projected innings, projected pitch count, pitcher strikeout ability,
          opponent hitter strikeout tendencies, and a small weather run-environment
          adjustment.

        **Weather**
        - Game-time conditions and field-relative wind are included in matchup
          rankings. Hover a weather or wind value for details.

        **Grade Colors**
        - Green = favorable
        - Yellow = neutral
        - Red = avoid
        - Blue = small sample
        - Gray = no history
        """
    )

    st.markdown(
        """
        ### Glossary

        | Abbreviation | Meaning |
        |---|---|
        | **PA** | Plate Appearances |
        | **AB** | At-Bats |
        | **H** | Hits |
        | **BB** | Walks |
        | **HBP** | Hit By Pitch |
        | **SO** | Strikeouts |
        | **HR** | Home Runs |
        | **RBI** | Runs Batted In |
        | **AVG** | Batting Average |
        | **OBP** | On-Base Percentage |
        | **SLG** | Slugging Percentage |
        | **OPS** | On-Base Plus Slugging |
        | **K%** | Strikeout Percentage |
        | **BB%** | Walk Percentage |
        | **IP** | Innings Pitched |
        | **PC** | Pitch Count |
        | **BF** | Batters Faced |
        | **R** | Runs Allowed |
        | **ERA** | Earned Run Average |
        | **WHIP** | Walks plus Hits per Inning Pitched |
        | **K/9** | Strikeouts per 9 Innings |
        | **Opp K%** | Opponent Average Strikeout Percentage |
        | **Proj IP** | Projected Innings Pitched |
        | **Proj PC** | Projected Pitch Count |
        | **Proj K** | Projected Strikeouts |
        | **Proj H** | Projected Hits Allowed |
        | **K Score** | Strikeout Matchup Score |
        | **RHP** | Right-Handed Pitcher |
        | **LHP** | Left-Handed Pitcher |
        | **H/A** | Home/Away |
        """
    )

    st.markdown(
        """
        <div class="disclaimer-box">
            <b>Disclaimer:</b> This dashboard is for sports analytics and research purposes only.
            Matchup history can have small sample sizes, so direct hitter-vs-pitcher results should
            not be treated as guarantees. Handedness splits usually provide a larger sample and may
            be more useful for evaluating matchup context.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("Data Refresh Status")
    st.markdown(cloud_status_html, unsafe_allow_html=True)
