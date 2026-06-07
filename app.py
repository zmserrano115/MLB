from datetime import date
import os
from urllib.parse import quote

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from src.mlb_schedule import get_daily_schedule
from src.weather import enrich_schedule_with_weather
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
from src import database


st.set_page_config(
    page_title="All Rise Analytics",
    layout="wide",
)

live_refresh_count = st_autorefresh(
    interval=15 * 60 * 1000,
    key="live_context_autorefresh",
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
        --line-dark: #b9c3cf;
        --accent: #0f3b66;
        --accent-2: #173f68;
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

    .brand-hero {
        position: relative;
        margin: 0 0 18px 0;
        padding: 34px 34px 38px 34px;
        min-height: 290px;
        display: flex;
        align-items: center;
        overflow: hidden;
        border: 1px solid #08223a;
        background:
            linear-gradient(90deg, rgba(6, 23, 43, 0.97) 0%, rgba(10, 35, 57, 0.93) 45%, rgba(14, 53, 84, 0.88) 100%);
    }

    .brand-hero::before {
        content: "";
        position: absolute;
        inset: 0;
        background:
            linear-gradient(115deg, transparent 0%, transparent 62%, rgba(255,255,255,0.05) 62%, rgba(255,255,255,0.05) 63%, transparent 63%),
            radial-gradient(circle at 76% 34%, rgba(255,255,255,0.08), transparent 22%);
        opacity: 1;
    }

    .hero-content {
        position: relative;
        z-index: 3;
        max-width: 820px;
    }

    .hero-brand {
        font-family: var(--font-display) !important;
        color: #ffffff;
        font-size: clamp(62px, 8vw, 118px);
        line-height: 0.88;
        font-weight: 400;
        letter-spacing: 0.018em;
        margin: 0 0 16px 0;
    }

    .hero-line {
        width: 92px;
        height: 3px;
        background: #ffffff;
        margin: 0 0 18px 0;
        opacity: 0.9;
    }

    .hero-headline {
        color: #dbe7f4;
        font-size: 20px;
        line-height: 1.45;
        font-weight: 500;
        max-width: 720px;
        margin: 0;
    }

    .hero-baseball-wrap {
        position: absolute;
        right: 34px;
        top: 50%;
        transform: translateY(-50%);
        width: 300px;
        height: 300px;
        z-index: 2;
        pointer-events: none;
    }

    .hero-ball-shadow {
        position: absolute;
        inset: 36px 18px 16px 68px;
        background: radial-gradient(circle, rgba(0,0,0,0.18) 0%, rgba(0,0,0,0) 70%);
        filter: blur(20px);
        opacity: 0.34;
    }

    .hero-ball-svg {
        position: relative;
        width: 100%;
        height: 100%;
        display: block;
        opacity: 0.95;
    }

    .section-shell {
        margin: 18px 0 10px 0;
        padding: 0;
        border: 0;
        background: transparent;
    }

    .section-label,
    .metric-label,
    .selected-game-label {
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

    div[data-testid="stDataFrame"] {
        border: 1px solid #d6dde6 !important;
        border-radius: 0 !important;
        overflow: hidden !important;
        background: #ffffff !important;
        box-shadow: none !important;
    }

    div[data-testid="stDataFrame"] > div {
        background: #ffffff !important;
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

    section[data-testid="stSidebar"] {
        background: #ffffff !important;
        border-right: 1px solid #cfd7e2 !important;
        box-shadow: 6px 0 22px rgba(15, 23, 42, 0.08);
    }

    section[data-testid="stSidebar"] > div {
        background: #ffffff !important;
        padding-top: 1.25rem;
    }

    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: #111827 !important;
        font-weight: 500 !important;
    }

    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] {
        color: #111827 !important;
    }

    section[data-testid="stSidebar"] label p {
        color: #374151 !important;
        font-size: 13px !important;
        font-weight: 500 !important;
    }

    section[data-testid="stSidebar"] small {
        color: #4b5563 !important;
    }

    section[data-testid="stSidebar"] input {
        background: #f8fafc !important;
        color: #111827 !important;
        border: 1px solid #cfd7e2 !important;
        border-radius: 0 !important;
    }

    section[data-testid="stSidebar"] [data-baseweb="select"] > div {
        background: #f8fafc !important;
        color: #111827 !important;
        border: 1px solid #cfd7e2 !important;
        border-radius: 0 !important;
    }

    section[data-testid="stSidebar"] [data-baseweb="select"] span {
        color: #111827 !important;
    }

    section[data-testid="stSidebar"] button {
        background: #0f3b66 !important;
        color: #ffffff !important;
        border: 1px solid #0f3b66 !important;
        border-radius: 0 !important;
        font-weight: 500 !important;
    }

    section[data-testid="stSidebar"] button * {
        color: #ffffff !important;
        fill: #ffffff !important;
        stroke: #ffffff !important;
    }

    section[data-testid="stSidebar"] button:hover {
        background: #145083 !important;
        border-color: #145083 !important;
        color: #ffffff !important;
    }

    section[data-testid="stSidebar"] button:hover * {
        color: #ffffff !important;
        fill: #ffffff !important;
        stroke: #ffffff !important;
    }

    section[data-testid="stSidebar"] [data-testid="stNumberInput"] button {
        background: #eef3f8 !important;
        color: #111827 !important;
        border: 1px solid #cfd7e2 !important;
    }

    section[data-testid="stSidebar"] [data-testid="stNumberInput"] button * {
        color: #111827 !important;
        fill: #111827 !important;
        stroke: #111827 !important;
    }

    section[data-testid="stSidebar"] [data-testid="stNumberInput"] button:hover {
        background: #e2eaf3 !important;
        color: #111827 !important;
        border-color: #b9c3cf !important;
    }

    section[data-testid="stSidebar"] [data-testid="stNumberInput"] button:hover * {
        color: #111827 !important;
        fill: #111827 !important;
        stroke: #111827 !important;
    }

    section[data-testid="stSidebar"] [data-testid="stDateInput"] input {
        color: #111827 !important;
    }

    .custom-label-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-top: 18px;
        margin-bottom: 6px;
        width: 100%;
    }

    .custom-label-text {
        color: #111827 !important;
        font-size: 13px;
        font-weight: 500;
        line-height: 1.2;
    }

    .custom-help-wrap {
        position: relative;
        display: inline-flex;
        align-items: center;
        justify-content: center;
    }

    .custom-help-dot {
        width: 22px;
        height: 22px;
        border-radius: 0;
        background: #0f3b66;
        color: #ffffff !important;
        border: 1px solid #0f3b66;
        font-family: var(--font-body);
        font-size: 14px;
        font-weight: 600;
        line-height: 20px;
        text-align: center;
        cursor: default;
        user-select: none;
        box-shadow: none;
        -webkit-font-smoothing: antialiased;
        text-rendering: geometricPrecision;
    }

    .custom-help-tooltip {
        display: none;
        position: absolute;
        right: 0;
        top: 29px;
        width: 250px;
        background: #0f172a !important;
        color: #f8fafc !important;
        border: 1px solid #334155;
        border-radius: 0;
        padding: 10px 12px;
        font-size: 13px;
        font-weight: 400;
        line-height: 1.45;
        z-index: 999999;
        box-shadow: 0 8px 22px rgba(15, 23, 42, 0.25);
    }

    .custom-help-wrap:hover .custom-help-tooltip {
        display: block;
    }

    section[data-testid="stSidebar"] .custom-help-tooltip,
    section[data-testid="stSidebar"] .custom-help-tooltip * {
        color: #f8fafc !important;
    }

    section[data-testid="stSidebar"] .custom-help-dot {
        color: #ffffff !important;
    }

    @media (max-width: 900px) {
        .block-container {
            padding-top: 4.4rem;
        }

        .brand-hero {
            padding: 28px 22px 30px 22px;
            min-height: 250px;
        }

        .hero-brand {
            font-size: 64px;
        }

        .hero-headline {
            font-size: 17px;
        }

        .hero-baseball-wrap {
            width: 190px;
            height: 190px;
            right: -18px;
            opacity: 0.58;
        }

        .hero-ball-shadow {
            inset: 24px 10px 10px 34px;
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


def opponent_from_game(game, team):
    if pd.isna(game) or pd.isna(team):
        return ""

    game = str(game)
    team = str(team)

    if " @ " not in game:
        return ""

    away_team, home_team = game.split(" @ ", 1)

    if team == away_team:
        return home_team

    if team == home_team:
        return away_team

    return ""


def grade_bar_url(grade):
    grade = str(grade).lower()

    if "elite" in grade or "strong" in grade or "good" in grade:
        color = "2ca25f"
    elif "neutral" in grade:
        color = "d99a16"
    elif "avoid" in grade:
        color = "d64545"
    elif "small sample" in grade:
        color = "3f7fd8"
    elif "no history" in grade:
        color = "9ca3af"
    else:
        color = "9ca3af"

    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='8' height='34' viewBox='0 0 8 34'>"
        f"<rect x='0' y='0' width='8' height='34' fill='#{color}'/>"
        f"</svg>"
    )

    return "data:image/svg+xml;utf8," + quote(svg)


def make_light_table(df):
    return (
        df.style
        .set_properties(
            **{
                "background-color": "#ffffff",
                "color": "#111827",
                "border-color": "#d6dde6",
            }
        )
        .set_table_styles(
            [
                {
                    "selector": "th",
                    "props": [
                        ("background-color", "#eef2f6"),
                        ("color", "#111827"),
                        ("font-weight", "500"),
                        ("border-color", "#d6dde6"),
                    ],
                },
                {
                    "selector": "td",
                    "props": [
                        ("background-color", "#ffffff"),
                        ("color", "#111827"),
                        ("border-color", "#e5e7eb"),
                    ],
                },
            ]
        )
    )


def show_table(df, key=None, selectable=False):
    table_data = make_light_table(df)

    kwargs = {
        "data": table_data,
        "width": "stretch",
        "hide_index": True,
        "column_config": table_column_config(),
        "row_height": 42,
    }

    if selectable:
        kwargs["on_select"] = "rerun"
        kwargs["selection_mode"] = "single-row"
        kwargs["key"] = key

    return st.dataframe(**kwargs)


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


def table_column_config():
    return {
        "grade_bar": st.column_config.ImageColumn("", width=18),
        "team_logo": st.column_config.ImageColumn("", width=32),
        "opponent_logo": st.column_config.ImageColumn("", width=32),
        "away_logo": st.column_config.ImageColumn("", width=32),
        "home_logo": st.column_config.ImageColumn("", width=32),
        "pitcher_team_logo": st.column_config.ImageColumn("", width=32),
        "away_team": st.column_config.TextColumn("Away Team", width=145),
        "home_team": st.column_config.TextColumn("Home Team", width=145),
        "team": st.column_config.TextColumn("Team", width=125),
        "opponent": st.column_config.TextColumn("Opponent", width=125),
        "opponent_team": st.column_config.TextColumn("Opponent", width=125),
        "away_probable_pitcher": st.column_config.TextColumn("Away Pitcher", width=145),
        "home_probable_pitcher": st.column_config.TextColumn("Home Pitcher", width=145),
        "away_pitcher_hand": st.column_config.TextColumn("Hand", width=60),
        "home_pitcher_hand": st.column_config.TextColumn("Hand", width=60),
        "batter": st.column_config.TextColumn("Batter", width=140),
        "pitcher": st.column_config.TextColumn("Pitcher", width=140),
        "opposing_pitcher": st.column_config.TextColumn("Pitcher", width=140),
        "pitcher_hand": st.column_config.TextColumn("Hand", width=60),
        "opposing_pitcher_hand": st.column_config.TextColumn("Hand", width=60),
        "split": st.column_config.TextColumn("Split", width=75),
        "home_away": st.column_config.TextColumn("H/A", width=60),
        "game_date": st.column_config.TextColumn("Date", width=95),
        "matchup_grade": st.column_config.TextColumn("Grade", width=115),
        "k_matchup_grade": st.column_config.TextColumn("K Grade", width=115),
        "PA": st.column_config.NumberColumn("PA", width=55, format="%d"),
        "AB": st.column_config.NumberColumn("AB", width=55, format="%d"),
        "H": st.column_config.NumberColumn("H", width=50, format="%d"),
        "BB": st.column_config.NumberColumn("BB", width=55, format="%d"),
        "HBP": st.column_config.NumberColumn("HBP", width=60, format="%d"),
        "SO": st.column_config.NumberColumn("SO", width=55, format="%d"),
        "HR": st.column_config.NumberColumn("HR", width=55, format="%d"),
        "RBI": st.column_config.NumberColumn("RBI", width=60, format="%d"),
        "BF": st.column_config.NumberColumn("BF", width=55, format="%d"),
        "R": st.column_config.NumberColumn("R", width=50, format="%d"),
        "IP": st.column_config.NumberColumn("IP", width=55, format="%.1f"),
        "Pitch Count": st.column_config.NumberColumn("PC", width=60, format="%d"),
        "AVG": st.column_config.NumberColumn("AVG", width=70, format="%.3f"),
        "OBP": st.column_config.NumberColumn("OBP", width=70, format="%.3f"),
        "SLG": st.column_config.NumberColumn("SLG", width=70, format="%.3f"),
        "OPS": st.column_config.NumberColumn("OPS", width=70, format="%.3f"),
        "K%": st.column_config.NumberColumn("K%", width=65, format="%.2f"),
        "BB%": st.column_config.NumberColumn("BB%", width=65, format="%.2f"),
        "Projected IP": st.column_config.NumberColumn("Proj IP", width=80, format="%.2f"),
        "Projected Pitch Count": st.column_config.NumberColumn("Proj PC", width=80, format="%.0f"),
        "Projected Ks": st.column_config.NumberColumn("Proj K", width=75, format="%.2f"),
        "ERA": st.column_config.NumberColumn("ERA", width=65, format="%.2f"),
        "WHIP": st.column_config.NumberColumn("WHIP", width=70, format="%.2f"),
        "K/9": st.column_config.NumberColumn("K/9", width=65, format="%.2f"),
        "opponent_avg_k%": st.column_config.NumberColumn("Opp K%", width=80, format="%.2f"),
        "k_matchup_score": st.column_config.NumberColumn("K Score", width=80, format="%.2f"),
        "venue_name": st.column_config.TextColumn("Ballpark", width=145),
        "roof_type": st.column_config.TextColumn("Roof", width=90),
        "weather_summary": st.column_config.TextColumn("Game Weather", width=240),
        "weather_edge": st.column_config.TextColumn("Weather Edge", width=145),
        "hitter_weather_adjustment": st.column_config.NumberColumn(
            "Wx Adj",
            width=75,
            format="%+.2f",
        ),
        "weather_k_adjustment": st.column_config.NumberColumn(
            "Wx K Adj",
            width=80,
            format="%+.2f",
        ),
        "weather_adjusted_score": st.column_config.NumberColumn(
            "Wx Score",
            width=80,
            format="%.2f",
        ),
        "history_grade": st.column_config.TextColumn("History Grade", width=115),
    }


def prepare_schedule_display(df):
    df = df.copy()

    if "away_team" in df.columns:
        df["away_logo"] = df["away_team"].apply(team_logo_url)

    if "home_team" in df.columns:
        df["home_logo"] = df["home_team"].apply(team_logo_url)

    return df


def prepare_batter_display(df):
    df = df.copy()

    if "matchup_grade" in df.columns:
        df["grade_bar"] = df["matchup_grade"].apply(grade_bar_url)
    else:
        df["grade_bar"] = grade_bar_url("no history")

    if "team" in df.columns:
        df["team_logo"] = df["team"].apply(team_logo_url)

    if "game" in df.columns and "team" in df.columns:
        df["opponent_team"] = df.apply(
            lambda row: opponent_from_game(row.get("game"), row.get("team")),
            axis=1,
        )
        df["opponent_logo"] = df["opponent_team"].apply(team_logo_url)

    return df


def prepare_pitcher_display(df):
    df = df.copy()

    if "k_matchup_grade" in df.columns:
        df["grade_bar"] = df["k_matchup_grade"].apply(grade_bar_url)
    else:
        df["grade_bar"] = grade_bar_url("no history")

    if "pitcher_team" in df.columns:
        df["pitcher_team_logo"] = df["pitcher_team"].apply(team_logo_url)

    if "opponent" in df.columns:
        df["opponent_logo"] = df["opponent"].apply(team_logo_url)

    return df


def display_bvp_game_log(selected_row, season):
    batter_name = selected_row.get("batter")
    pitcher_name = selected_row.get("opposing_pitcher")
    batter_id = selected_row.get("batter_id")
    pitcher_id = selected_row.get("opposing_pitcher_id")

    st.subheader(f"Career Game Log: {batter_name} vs {pitcher_name}")

    if is_missing_value(batter_id) or is_missing_value(pitcher_id):
        st.warning("Player ID was not found for this row.")
        return

    with st.spinner("Loading career batter-vs-pitcher game log..."):
        game_log_df = get_batter_vs_pitcher_game_log(
            int(batter_id),
            int(pitcher_id),
            int(season),
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

    show_table(game_log_df[game_log_cols])


def display_pitcher_vs_team_game_log(selected_row):
    pitcher_name = selected_row.get("pitcher")
    opponent_team = selected_row.get("opponent")
    pitcher_id = selected_row.get("pitcher_id")

    st.subheader(f"Career Game Log: {pitcher_name} vs {opponent_team}")

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
        "opponent_logo",
        "opponent",
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

    show_table(game_log_df[game_log_cols])


current_year = date.today().year
try:
    if "MLB_DB_URL" in st.secrets:
        os.environ.setdefault("MLB_DB_URL", st.secrets["MLB_DB_URL"])
except Exception:
    pass
database.init_database()


with st.sidebar:
    st.header("Controls")

    selected_date = st.date_input("Game Date", value=date.today())

    season = st.selectbox(
        "Season",
        list(range(current_year, current_year - 26, -1)),
    )

    min_pa = st.number_input(
        "Minimum PA",
        min_value=0,
        max_value=700,
        value=100,
        step=10,
    )

    top_n = st.number_input(
        "Rows to Show",
        min_value=5,
        max_value=100,
        value=25,
        step=5,
    )

    force_refresh = st.button("Refresh Live Context")
    st.caption(
        "Probable pitchers and weather share a 15-minute cache. "
        "This button refreshes them immediately."
    )


@st.cache_data(show_spinner=True, ttl=900)
def load_schedule(game_date, refresh_count):
    return get_daily_schedule(str(game_date))


@st.cache_data(show_spinner=True, ttl=900)
def load_weather(schedule, refresh_count):
    return enrich_schedule_with_weather(schedule)


@st.cache_data(show_spinner=True)
def load_batter_stats(season, force_refresh):
    return get_batter_stats(season, force_refresh=force_refresh)


@st.cache_data(show_spinner=True)
def load_pitcher_stats(season, force_refresh):
    return get_pitcher_stats(season, force_refresh=force_refresh)


if force_refresh:
    load_schedule.clear()
    load_weather.clear()

schedule_df = load_schedule(selected_date, live_refresh_count)

if schedule_df.empty:
    st.warning("No MLB games found for this date.")
    st.stop()

schedule_df = load_weather(schedule_df, live_refresh_count)
batters_df = load_batter_stats(season, force_refresh)
pitchers_df = load_pitcher_stats(season, force_refresh)

cloud_status_html = """
<div class="status-box">
    <b>Data Mode:</b> Live pitchers, stadium weather, and SQLite history<br>
    Probable pitchers and game-time forecasts refresh every 15 minutes.
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


if schedule_df.empty:
    st.warning("No schedule data available.")
    st.stop()


schedule_df = add_game_column(schedule_df)
game_options = get_game_options(schedule_df)


with st.sidebar:
    st.markdown(
        """
        <div class="custom-label-row">
            <span class="custom-label-text">Game Filter</span>
            <span class="custom-help-wrap">
                <span class="custom-help-dot">?</span>
                <span class="custom-help-tooltip">
                    Choose a specific game to focus the schedule and matchup tables.
                </span>
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    selected_game = st.selectbox(
        "Game Filter",
        game_options,
        index=0,
        label_visibility="collapsed",
    )


filtered_schedule_df = filter_by_game(schedule_df, selected_game)
filtered_bvp_matchups = filter_by_game(bvp_matchups, selected_game)
filtered_hand_matchups = filter_by_game(hand_matchups, selected_game)
filtered_pitcher_k_matchups = filter_by_game(pitcher_k_matchups, selected_game)


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

    schedule_display = prepare_schedule_display(filtered_schedule_df)

    schedule_display_cols = [
        "away_logo",
        "away_team",
        "home_logo",
        "home_team",
        "away_probable_pitcher",
        "away_pitcher_hand",
        "home_probable_pitcher",
        "home_pitcher_hand",
        "venue_name",
        "roof_type",
        "weather_summary",
        "weather_edge",
    ]

    schedule_display_cols = [
        col for col in schedule_display_cols if col in schedule_display.columns
    ]

    show_table(schedule_display[schedule_display_cols])


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
        st.markdown(
            f"""
            <div class="section-shell">
            <div class="section-title">{display_game_date}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if filtered_bvp_matchups.empty:
            st.warning("No batter vs pitcher matchup data was found for this selection.")
        else:
            min_bvp_pa = st.slider(
                "Minimum PA vs Pitcher",
                min_value=0,
                max_value=50,
                value=0,
                step=1,
            )

            display_bvp = filtered_bvp_matchups[
                filtered_bvp_matchups["PA"] >= min_bvp_pa
            ].copy()

            display_bvp = display_bvp.head(int(top_n))
            display_bvp = prepare_batter_display(display_bvp)

            bvp_cols = [
                "grade_bar",
                "team_logo",
                "team",
                "batter",
                "opponent_logo",
                "opposing_pitcher",
                "opposing_pitcher_hand",
                "PA",
                "AB",
                "H",
                "BB",
                "SO",
                "HR",
                "RBI",
                "AVG",
                "OBP",
                "SLG",
                "OPS",
                "K%",
                "BB%",
                "weather_summary",
                "weather_edge",
                "hitter_weather_adjustment",
                "weather_adjusted_score",
                "matchup_grade",
            ]

            bvp_cols = [col for col in bvp_cols if col in display_bvp.columns]

            st.caption("Click one row below to view its career matchup game log.")

            bvp_event = show_table(
                display_bvp[bvp_cols],
                key="bvp_table",
                selectable=True,
            )

            selected_row = None

            try:
                selected_rows = bvp_event.selection.rows

                if selected_rows:
                    selected_row = display_bvp.iloc[selected_rows[0]]
            except Exception:
                selected_row = None

            st.divider()

            if selected_row is not None:
                display_bvp_game_log(selected_row, season)
            else:
                st.info("Select a batter-vs-pitcher row above to view the game log.")

    with tab2:
        st.markdown(
            f"""
            <div class="section-shell">
                <div class="section-title">{display_game_date}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if filtered_hand_matchups.empty:
            st.warning("No batter vs pitcher-hand split data was found for this selection.")
        else:
            min_hand_pa = st.slider(
                "Minimum PA vs Throwing Hand",
                min_value=0,
                max_value=300,
                value=20,
                step=5,
            )

            min_hand_obp = st.slider(
                "Minimum OBP vs Throwing Hand",
                min_value=0.150,
                max_value=0.500,
                value=0.320,
                step=0.005,
            )

            display_hand = filtered_hand_matchups[
                (filtered_hand_matchups["PA"] >= min_hand_pa)
                & (filtered_hand_matchups["OBP"] >= min_hand_obp)
            ].copy()

            display_hand = display_hand.head(int(top_n))
            display_hand = prepare_batter_display(display_hand)

            hand_cols = [
                "grade_bar",
                "team_logo",
                "team",
                "batter",
                "opponent_logo",
                "opposing_pitcher",
                "opposing_pitcher_hand",
                "split",
                "PA",
                "AB",
                "H",
                "BB",
                "SO",
                "HR",
                "RBI",
                "AVG",
                "OBP",
                "SLG",
                "OPS",
                "K%",
                "BB%",
                "weather_summary",
                "weather_edge",
                "hitter_weather_adjustment",
                "weather_adjusted_score",
                "matchup_grade",
            ]

            hand_cols = [col for col in hand_cols if col in display_hand.columns]

            show_table(display_hand[hand_cols])

    with tab3:
        st.markdown(
            f"""
            <div class="section-shell">
                <div class="section-title">{display_game_date}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if filtered_pitcher_k_matchups.empty:
            st.warning("No pitcher strikeout matchups were created for this selection.")
        else:
            required_projected_cols = [
                "Projected IP",
                "Projected Pitch Count",
                "Projected Ks",
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

            display_k = filtered_pitcher_k_matchups.head(int(top_n)).copy()
            display_k = prepare_pitcher_display(display_k)

            k_cols = [
                "grade_bar",
                "pitcher_team_logo",
                "pitcher",
                "pitcher_hand",
                "opponent_logo",
                "opponent",
                "Projected IP",
                "Projected Pitch Count",
                "Projected Ks",
                "ERA",
                "WHIP",
                "K%",
                "K/9",
                "opponent_avg_k%",
                "weather_summary",
                "weather_edge",
                "weather_k_adjustment",
                "k_matchup_score",
                "k_matchup_grade",
            ]

            k_cols = [col for col in k_cols if col in display_k.columns]

            st.caption("Click one pitcher row below to view his career game log against that opponent.")

            k_event = show_table(
                display_k[k_cols],
                key="pitcher_k_table",
                selectable=True,
            )

            selected_pitcher_row = None

            try:
                selected_rows = k_event.selection.rows

                if selected_rows:
                    selected_pitcher_row = display_k.iloc[selected_rows[0]]
            except Exception:
                selected_pitcher_row = None

            st.divider()

            if selected_pitcher_row is not None:
                display_pitcher_vs_team_game_log(selected_pitcher_row)
            else:
                st.info("Select a pitcher row above to view his career game log against that opponent.")


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

        **Weather Projection**
        - Uses the scheduled venue's MLB coordinates, elevation, field azimuth,
          roof type, and game start time.
        - Wind is projected relative to the center-field bearing, so the model
          distinguishes wind blowing out, in, or across the field.
        - Outdoor hitter rankings include wind and air-density adjustments.
        - Retractable-roof games show the forecast but remain neutral until roof
          status is known.
        - Weather adjustments are bounded matchup heuristics, not calibrated
          batted-ball or sportsbook projections.
        - Forecast source: [Open-Meteo](https://open-meteo.com/).

        **Row Markers**
        - Green bar = favorable
        - Yellow bar = neutral
        - Red bar = avoid
        - Blue bar = small sample
        - Gray bar = no history
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
        | **K Score** | Strikeout Matchup Score |
        | **Wx Adj** | Weather adjustment applied to hitter matchup ranking |
        | **Wx Score** | Weather-adjusted matchup ranking score |
        | **Wx K Adj** | Small weather run-environment adjustment to K score |
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
