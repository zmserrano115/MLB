from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import escape
import json
import os
from pathlib import Path
from threading import Event, Lock, Thread
import time
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
from src import stat_data as stat_data_service
from src.live_game import (
    get_game_boxscore,
    get_people_game_logs as fetch_people_game_logs,
    get_player_game_log,
    is_final_state,
    player_headshot_url,
)
from src.matchups import (
    build_batter_vs_pitcher_matchups,
    build_batter_vs_hand_matchups,
    build_pitcher_k_matchups,
)
from src.injuries import add_injury_columns, fetch_injury_report
from src.recent_form import build_recent_bar_chart_html
from src.scoring import parse_baseball_ip
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
    "ANA": 108,
    "AZ": 109,
    "ATL": 144,
    "BAL": 110,
    "BOS": 111,
    "CHC": 112,
    "CHN": 112,
    "CWS": 145,
    "CHW": 145,
    "CHA": 145,
    "CIN": 113,
    "CLE": 114,
    "COL": 115,
    "DET": 116,
    "HOU": 117,
    "KC": 118,
    "KCR": 118,
    "KCA": 118,
    "LAA": 108,
    "LAD": 119,
    "LAN": 119,
    "MIA": 146,
    "MIL": 158,
    "MIN": 142,
    "NYM": 121,
    "NYN": 121,
    "NYY": 147,
    "NYA": 147,
    "ATH": 133,
    "OAK": 133,
    "PHI": 143,
    "PIT": 134,
    "SD": 135,
    "SDP": 135,
    "SDN": 135,
    "SF": 137,
    "SFG": 137,
    "SFN": 137,
    "SEA": 136,
    "STL": 138,
    "SLN": 138,
    "TB": 139,
    "TBR": 139,
    "TBA": 139,
    "TEX": 140,
    "TOR": 141,
    "WSH": 120,
    "WSN": 120,
    "WAS": 120,
}

ESPN_TEAM_CODE_BY_ABBR = {
    "ARI": "ari",
    "ANA": "laa",
    "AZ": "ari",
    "ATL": "atl",
    "BAL": "bal",
    "BOS": "bos",
    "CHC": "chc",
    "CHN": "chc",
    "CWS": "chw",
    "CHW": "chw",
    "CHA": "chw",
    "CIN": "cin",
    "CLE": "cle",
    "COL": "col",
    "DET": "det",
    "HOU": "hou",
    "KC": "kc",
    "KCR": "kc",
    "KCA": "kc",
    "LAA": "laa",
    "LAD": "lad",
    "LAN": "lad",
    "MIA": "mia",
    "MIL": "mil",
    "MIN": "min",
    "NYM": "nym",
    "NYN": "nym",
    "NYY": "nyy",
    "NYA": "nyy",
    "ATH": "ath",
    "OAK": "oak",
    "PHI": "phi",
    "PIT": "pit",
    "SD": "sd",
    "SDP": "sd",
    "SDN": "sd",
    "SF": "sf",
    "SFG": "sf",
    "SFN": "sf",
    "SEA": "sea",
    "STL": "stl",
    "SLN": "stl",
    "TB": "tb",
    "TBR": "tb",
    "TBA": "tb",
    "TEX": "tex",
    "TOR": "tor",
    "WSH": "wsh",
    "WSN": "wsh",
    "WAS": "wsh",
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
        padding-top: 3.625rem;
        padding-bottom: 1.25rem;
        max-width: 1480px;
    }

    .stApp [data-testid="stVerticalBlock"] {
        gap: 0.75rem;
    }

    h1, h2, h3, h4, h5, h6,
    p, li, span, label, div {
        font-family: var(--font-body);
    }

    h1, h2, h3, h4, h5, h6 {
        font-family: var(--font-display) !important;
        font-weight: 400 !important;
        letter-spacing: 0.035em;
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
        margin: 10px 0 7px 0;
        padding: 0;
        border: 0;
        background: transparent;
    }

    .game-log-heading {
        margin-top: 4px;
    }

    [class*="close_player_log"],
    [class*="close_log"] {
        display: flex;
        justify-content: flex-end;
        margin: 0 0 -2px;
    }

    [class*="close_player_log"] .stButton,
    [class*="close_log"] .stButton {
        width: auto;
    }

    [class*="close_player_log"] .stButton > button,
    [class*="close_log"] .stButton > button {
        min-height: 32px;
        width: auto;
        padding: 4px 10px;
        border: 1px solid #cbd5e1;
        border-radius: 4px;
        background: rgba(255, 255, 255, 0.78);
        color: #526171;
        font-size: 12px;
        font-weight: 600;
        box-shadow: none;
    }

    [class*="close_player_log"] .stButton > button:hover,
    [class*="close_log"] .stButton > button:hover {
        border-color: #94a3b8;
        background: #ffffff;
        color: #173f67;
    }

    .section-label,
    .metric-label {
        color: var(--muted-2);
        font-family: var(--font-display) !important;
        font-size: 11px;
        font-weight: 400;
        text-transform: uppercase;
        letter-spacing: 0.09em;
        margin-bottom: 4px;
    }

    .section-title {
        color: var(--text);
        font-family: var(--font-display) !important;
        font-size: 26px;
        line-height: 1.15;
        font-weight: 400;
        letter-spacing: 0.035em;
        margin-bottom: 0;
    }

    .section-title .title-date {
        font-family: var(--font-display) !important;
    }

    [data-testid="stSelectbox"] [data-baseweb="select"] *,
    [data-testid="stMultiSelect"] [data-baseweb="select"] *,
    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    [data-testid="stDateInput"] input,
    [data-testid="stSelectbox"] [data-testid="stWidgetLabel"] *,
    [data-testid="stMultiSelect"] [data-testid="stWidgetLabel"] *,
    [data-testid="stTextInput"] [data-testid="stWidgetLabel"] *,
    [data-testid="stNumberInput"] [data-testid="stWidgetLabel"] *,
    [data-testid="stDateInput"] [data-testid="stWidgetLabel"] * {
        font-family: var(--font-display) !important;
        font-weight: 400 !important;
        letter-spacing: 0.035em;
    }

    [data-baseweb="popover"] [role="option"],
    [data-baseweb="popover"] [role="option"] * {
        font-family: var(--font-display) !important;
        font-weight: 400 !important;
        letter-spacing: 0.035em;
    }

    .stSegmentedControl [data-baseweb="button-group"] {
        gap: 0;
        border-bottom: 1px solid var(--line);
        margin-bottom: 8px;
    }

    .st-key-active_view .stRadio [role="radiogroup"] {
        display: grid !important;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        width: 100%;
    }

    .stRadio [role="radiogroup"] input,
    .stRadio [role="radiogroup"] svg {
        display: none !important;
    }

    .stRadio label[data-baseweb="radio"] > div:first-child,
    .stRadio [role="radiogroup"] label > div:first-child:not([data-testid="stMarkdownContainer"]) {
        display: none !important;
        width: 0 !important;
        height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }

    .stSegmentedControl button {
        min-height: 42px;
        padding: 9px 20px !important;
        border-radius: 0 !important;
        border: 1px solid transparent !important;
        border-bottom: 0 !important;
        background: transparent !important;
        color: var(--muted) !important;
        box-shadow: none !important;
        font-weight: 500 !important;
    }

    .stSegmentedControl button[aria-pressed="true"] {
        border-color: var(--line) !important;
        background: var(--panel) !important;
        color: var(--text) !important;
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
        margin: 0 0 10px 0;
    }

    .slate-item {
        min-height: 66px;
        padding: 10px 14px;
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
        padding: 12px 14px;
        margin: 8px 0 12px 0;
        color: var(--muted);
        font-size: 14px;
        line-height: 1.65;
        box-shadow: none;
    }

    .score-number {
        min-width: 22px;
        padding: 2px 5px;
        border: 1px solid #cbd5e1;
        background: #f8fafc;
        color: #0f172a;
        text-align: center;
        font-weight: 800;
        font-variant-numeric: tabular-nums;
    }

    .score-status,
    .live-chip {
        display: inline-flex;
        align-items: center;
        width: fit-content;
        padding: 2px 6px;
        border: 1px solid #d2dae4;
        background: #f7fafc;
        color: #526171;
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .live-chip.hot {
        border-color: #a5d6b7;
        background: #edf8f2;
        color: #247a4d;
    }

    .live-chip.ended {
        border-color: #e2b8b8;
        background: #fff0f0;
        color: #b43b3b;
    }

    .boxscore-title {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px;
    }

    .boxscore-title .score-status {
        margin-top: 2px;
    }

    .boxscore-shell {
        margin: 8px 0 6px;
        padding: 12px 14px;
        border: 1px solid var(--line);
        background: var(--panel);
    }

    .boxscore-scoreboard {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 12px;
    }

    .boxscore-team {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        color: #0b2a4a;
        font-size: 16px;
        font-weight: 800;
    }

    .boxscore-team strong {
        min-width: 28px;
        padding: 3px 7px;
        border: 1px solid #cbd5e1;
        background: #f8fafc;
        color: #0f172a;
        text-align: center;
        font-size: 18px;
    }

    .boxscore-logo {
        width: 34px;
        height: 34px;
        object-fit: contain;
    }

    .st-key-matchup_toolbar {
        margin: 0 0 6px;
    }

    .st-key-matchup_toolbar [data-testid="stSelectbox"] {
        min-width: 0;
    }

    .leaderboard-shell {
        border: 1px solid var(--line);
        background: var(--panel);
        margin-bottom: 10px;
    }

    .leaderboard-row {
        display: grid;
        grid-template-columns: 42px 44px minmax(145px, 1fr) minmax(100px, 1.2fr) 74px 88px;
        align-items: center;
        gap: 10px;
        min-height: 58px;
        padding: 9px 12px;
        border-bottom: 1px solid #edf0f4;
    }

    .leaderboard-row:last-child {
        border-bottom: 0;
    }

    .leaderboard-rank {
        color: var(--muted-2);
        font-size: 12px;
        font-weight: 800;
        text-align: center;
    }

    .leaderboard-headshot {
        width: 36px;
        height: 36px;
        border: 1px solid #d8dee6;
        border-radius: 50%;
        background: #f3f5f7;
        object-fit: cover;
    }

    .leaderboard-name {
        min-width: 0;
    }

    .leaderboard-name strong {
        display: block;
        overflow: hidden;
        color: var(--text);
        font-size: 13px;
        line-height: 1.25;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .leaderboard-name span {
        color: var(--muted);
        font-size: 11px;
    }

    .streak-injury-badge {
        display: inline-flex;
        align-items: center;
        margin-left: 6px;
        padding: 1px 5px;
        border: 1px solid #e2b8b8;
        border-radius: 3px;
        background: #fff0f0;
        color: #b43b3b;
        font-size: 9px;
        font-weight: 800;
        letter-spacing: 0.04em;
        line-height: 1.4;
        text-transform: uppercase;
        vertical-align: middle;
        cursor: help;
    }

    .leaderboard-bar-track {
        height: 8px;
        background: #edf1f5;
        overflow: hidden;
    }

    .leaderboard-bar-fill {
        display: block;
        height: 8px;
        background: #245f96;
    }

    .leaderboard-count {
        color: var(--text);
        font-size: 22px;
        font-weight: 800;
        text-align: right;
        font-variant-numeric: tabular-nums;
    }

    .leaderboard-empty {
        padding: 14px;
        color: var(--muted);
        font-size: 13px;
    }

    .stats-identity-img {
        width: 24px;
        height: 24px;
        flex: 0 0 auto;
        object-fit: contain;
    }

    .stats-headshot {
        border: 1px solid var(--line);
        border-radius: 50%;
        background: #f3f5f7;
        object-fit: cover;
    }

    .schedule-at {
        color: var(--muted);
        font-weight: 700;
    }

    .research-table-note {
        color: var(--muted);
        font-size: 11px;
        margin: -2px 0 6px 0;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        border-bottom: 1px solid var(--line);
        padding-bottom: 0;
    }

    .stTabs [data-baseweb="tab"] {
        height: 42px;
        border-radius: 0;
        border: 1px solid transparent;
        border-bottom: 2px solid transparent;
        padding-left: 20px;
        padding-right: 20px;
        color: var(--muted);
        background: transparent;
        font-family: var(--font-display) !important;
        font-size: 16px;
        font-weight: 400;
        letter-spacing: 0.055em;
    }

    .stTabs [aria-selected="true"] {
        color: var(--text) !important;
        background: var(--panel) !important;
        border: 1px solid var(--line) !important;
        border-bottom: 2px solid #245f96 !important;
    }

    .stRadio [role="radiogroup"] {
        gap: 0;
        border-bottom: 1px solid var(--line);
        margin-bottom: 6px;
    }

    .stRadio [role="radiogroup"] label {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        min-height: 48px;
        padding: 0 22px;
        border: 1px solid transparent;
        border-bottom: 2px solid transparent;
        border-radius: 0;
        background: transparent;
        color: var(--muted);
        font-weight: 500;
        cursor: pointer;
        gap: 0 !important;
        text-align: center;
    }

    .stRadio [role="radiogroup"] label:has(input:checked) {
        margin-bottom: -1px;
        border-color: var(--line);
        border-bottom-color: #245f96;
        background: var(--panel);
        color: var(--text);
        font-weight: 700;
    }

    .stRadio [role="radiogroup"] label:hover {
        color: var(--text);
        background: #f6f8fa;
    }

    .stRadio [role="radiogroup"] [data-testid="stMarkdownContainer"] p {
        font-size: 16px;
        font-family: var(--font-display) !important;
        font-weight: 400 !important;
        letter-spacing: 0.055em;
        margin: 0 !important;
        text-align: center;
        white-space: nowrap;
    }

    .stRadio [role="radiogroup"] [data-testid="stMarkdownContainer"] {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 100%;
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

    .view-loading {
        position: fixed;
        z-index: 999998;
        top: 64px;
        right: 16px;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 7px 10px;
        border: 1px solid #cbd5e1;
        background: rgba(255, 255, 255, 0.96);
        color: #31445b;
        font-size: 12px;
        font-weight: 600;
        box-shadow: 0 4px 14px rgba(15, 31, 48, 0.12);
        pointer-events: none;
    }

    .view-loading-wheel {
        width: 15px;
        height: 15px;
        border: 2px solid #cbd5e1;
        border-top-color: #245f96;
        border-radius: 50%;
        animation: view-loading-spin 0.7s linear infinite;
    }

    @keyframes view-loading-spin {
        to {
            transform: rotate(360deg);
        }
    }

    @media (max-width: 680px) {
        header[data-testid="stHeader"]::before {
            top: 15px;
            left: 18px;
            font-size: 22px;
        }

        .block-container {
            padding-right: 0.75rem;
            padding-left: 0.75rem;
        }

        .st-key-active_view .stRadio [role="radiogroup"] {
            grid-template-columns: repeat(3, minmax(0, 1fr));
        }

        .st-key-active_view .stRadio [role="radiogroup"] label {
            min-height: 46px;
            padding: 0 5px;
        }

        .st-key-active_view .stRadio [role="radiogroup"] p {
            font-size: 14px;
            letter-spacing: 0.035em;
        }

        .stRadio [role="radiogroup"] {
            overflow-x: auto;
            flex-wrap: nowrap !important;
            scrollbar-width: none;
            -webkit-overflow-scrolling: touch;
        }

        .stRadio [role="radiogroup"]::-webkit-scrollbar {
            display: none;
        }

        .stRadio [role="radiogroup"] label {
            flex: 0 0 auto;
            min-height: 46px;
            padding: 0 14px;
        }

        .st-key-matchup_toolbar [data-testid="stHorizontalBlock"]:has(
            > [data-testid="stColumn"]:nth-child(6)
        ) {
            display: grid !important;
            grid-template-columns: 44px minmax(0, 1fr) 44px !important;
            gap: 8px !important;
        }

        .st-key-matchup_toolbar [data-testid="stColumn"] {
            width: 100% !important;
            min-width: 0 !important;
            flex: none !important;
        }

        .st-key-matchup_toolbar [data-testid="stHorizontalBlock"]:has(
            > [data-testid="stColumn"]:nth-child(6)
        ) > [data-testid="stColumn"]:nth-child(1),
        .st-key-matchup_toolbar [data-testid="stHorizontalBlock"]:has(
            > [data-testid="stColumn"]:nth-child(6)
        ) > [data-testid="stColumn"]:nth-child(2),
        .st-key-matchup_toolbar [data-testid="stHorizontalBlock"]:has(
            > [data-testid="stColumn"]:nth-child(6)
        ) > [data-testid="stColumn"]:nth-child(3) {
            grid-column: 1 / -1;
        }

        .st-key-matchup_toolbar [data-testid="stHorizontalBlock"]:has(
            > [data-testid="stColumn"]:nth-child(6)
        ) > [data-testid="stColumn"]:nth-child(4) {
            grid-column: 1;
            grid-row: 4;
        }

        .st-key-matchup_toolbar [data-testid="stHorizontalBlock"]:has(
            > [data-testid="stColumn"]:nth-child(6)
        ) > [data-testid="stColumn"]:nth-child(5) {
            grid-column: 2;
            grid-row: 4;
        }

        .st-key-matchup_toolbar [data-testid="stHorizontalBlock"]:has(
            > [data-testid="stColumn"]:nth-child(6)
        ) > [data-testid="stColumn"]:nth-child(6) {
            grid-column: 3;
            grid-row: 4;
        }

        .st-key-matchup_toolbar [data-testid="stHorizontalBlock"]:not(
            :has(> [data-testid="stColumn"]:nth-child(6))
        ) {
            display: grid !important;
            grid-template-columns: 44px minmax(0, 1fr) 44px !important;
            gap: 8px !important;
        }

        .st-key-matchup_toolbar [data-testid="stHorizontalBlock"]:not(
            :has(> [data-testid="stColumn"]:nth-child(6))
        ) > [data-testid="stColumn"]:nth-child(1) {
            grid-column: 1 / -1;
        }

        .st-key-matchup_toolbar [data-testid="stHorizontalBlock"]:not(
            :has(> [data-testid="stColumn"]:nth-child(6))
        ) > [data-testid="stColumn"]:nth-child(2) {
            grid-column: 1;
            grid-row: 2;
        }

        .st-key-matchup_toolbar [data-testid="stHorizontalBlock"]:not(
            :has(> [data-testid="stColumn"]:nth-child(6))
        ) > [data-testid="stColumn"]:nth-child(3) {
            grid-column: 2;
            grid-row: 2;
        }

        .st-key-matchup_toolbar [data-testid="stHorizontalBlock"]:not(
            :has(> [data-testid="stColumn"]:nth-child(6))
        ) > [data-testid="stColumn"]:nth-child(4) {
            grid-column: 3;
            grid-row: 2;
        }

        .st-key-matchup_toolbar [data-testid="stHorizontalBlock"]:not(
            :has(> [data-testid="stColumn"]:nth-child(6))
        ) > [data-testid="stColumn"]:nth-child(5) {
            display: none;
        }
    }

    @media (max-width: 900px) {
        .block-container {
            padding-top: 3.625rem;
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

        .leaderboard-row {
            grid-template-columns: 34px 40px minmax(0, 1fr) 58px;
        }

        .leaderboard-row .leaderboard-bar-track,
        .leaderboard-row .live-chip {
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

    return f"https://www.mlbstatic.com/team-logos/{team_id}.svg"


def team_logo_fallback_url(team_value):
    if team_value is None or pd.isna(team_value):
        return ""

    team_value = str(team_value).strip()
    team_id = TEAM_ID_BY_NAME.get(team_value)
    code = team_value.upper()

    if team_id is not None:
        for abbr, mapped_team_id in TEAM_ID_BY_ABBR.items():
            if mapped_team_id == team_id:
                code = abbr
                break

    espn_code = ESPN_TEAM_CODE_BY_ABBR.get(code)
    if not espn_code:
        return ""

    return f"https://a.espncdn.com/i/teamlogos/mlb/500/{espn_code}.png"


def team_id_for_value(team_value):
    if team_value is None or pd.isna(team_value):
        return None

    text = str(team_value).strip()
    if not text:
        return None

    team_id = TEAM_ID_BY_NAME.get(text)
    if team_id is not None:
        return team_id

    return TEAM_ID_BY_ABBR.get(text.upper())


def add_team_ids_from_names(df):
    if df.empty or "team_id" in df.columns:
        return df

    result = df.copy()
    source_column = "team_name" if "team_name" in result.columns else "Team"
    if source_column not in result.columns:
        return result

    result["team_id"] = result[source_column].apply(team_id_for_value)
    return result


def ensure_probable_pitcher_rows(pitchers_df, schedule_df):
    result = pitchers_df.copy()
    existing_ids = set(
        pd.to_numeric(
            result.get("player_id", pd.Series(dtype=float)),
            errors="coerce",
        ).dropna().astype(int)
    )
    rows = []
    for _, game in schedule_df.iterrows():
        for side in ("away", "home"):
            player_id = pd.to_numeric(
                game.get(f"{side}_probable_pitcher_id"),
                errors="coerce",
            )
            player_name = game.get(f"{side}_probable_pitcher")
            if pd.isna(player_id) or is_missing_value(player_name):
                continue
            player_id = int(player_id)
            if player_id in existing_ids:
                continue
            team_name = game.get(f"{side}_team")
            team_id = game.get(f"{side}_team_id")
            team_code = game.get(f"{side}_team_abbr") or team_name
            rows.append(
                {
                    "player_id": player_id,
                    "Name": player_name,
                    "team_id": team_id,
                    "team_name": team_name,
                    "Team": team_code,
                    "G": 0,
                    "GS": 0,
                    "IP": 0.0,
                    "Pitches": 0,
                    "H": 0,
                    "SO": 0,
                    "BB": 0,
                    "HR": 0,
                    "BF": 0,
                    "ERA": None,
                    "WHIP": None,
                    "K/9": None,
                    "BB/9": None,
                    "K%": None,
                    "BB%": None,
                    "SwStr%": None,
                }
            )
            existing_ids.add(player_id)
    if rows:
        result = pd.concat([result, pd.DataFrame(rows)], ignore_index=True)
    return result


def local_batter_season_stats(season):
    loader = getattr(database, "get_batter_season_stats_from_db", None)
    if loader is not None:
        return loader(int(season))

    with database.read_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                gl.batter_id AS player_id,
                MAX(bp.player_name) AS Name,
                MAX(gl.batting_team) AS team_name,
                MAX(gl.batting_team) AS Team,
                COUNT(DISTINCT gl.game_pk) AS G,
                SUM(gl.PA) AS PA,
                SUM(gl.AB) AS AB,
                SUM(gl.H) AS H,
                0 AS R,
                SUM(gl.BB) AS BB,
                SUM(gl.HBP) AS HBP,
                SUM(gl.SO) AS SO,
                SUM(gl.HR) AS HR,
                SUM(gl.RBI) AS RBI,
                0 AS SB,
                SUM(gl.TB) AS TB,
                SUM(gl.SF) AS SF,
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(SUM(gl.H) * 1.0 / SUM(gl.AB), 3) ELSE 0 END AS AVG,
                CASE WHEN SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF) > 0
                    THEN ROUND(
                        (SUM(gl.H) + SUM(gl.BB) + SUM(gl.HBP)) * 1.0 /
                        (SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF)),
                        3
                    ) ELSE 0 END AS OBP,
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(SUM(gl.TB) * 1.0 / SUM(gl.AB), 3) ELSE 0 END AS SLG,
                CASE WHEN SUM(gl.AB) > 0
                    AND SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF) > 0
                    THEN ROUND(
                        (SUM(gl.H) + SUM(gl.BB) + SUM(gl.HBP)) * 1.0 /
                        (SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF)) +
                        SUM(gl.TB) * 1.0 / SUM(gl.AB),
                        3
                    ) ELSE 0 END AS OPS,
                CASE WHEN SUM(gl.PA) > 0
                    THEN ROUND(SUM(gl.SO) * 100.0 / SUM(gl.PA), 2) ELSE 0 END AS "K%",
                CASE WHEN SUM(gl.PA) > 0
                    THEN ROUND(SUM(gl.BB) * 100.0 / SUM(gl.PA), 2) ELSE 0 END AS "BB%"
            FROM batter_pitcher_game_logs gl
            LEFT JOIN players bp ON gl.batter_id = bp.player_id
            WHERE gl.season = ?
            GROUP BY gl.batter_id
            HAVING Name IS NOT NULL
            """,
            (int(season),),
        ).fetchall()
    return [dict(row) for row in rows]


def local_pitcher_season_stats(season):
    loader = getattr(database, "get_pitcher_season_stats_from_db", None)
    if loader is not None:
        return loader(int(season))

    with database.read_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                ps.pitcher_id AS player_id,
                ps.pitcher_name AS Name,
                COALESCE(latest.team, '') AS team_name,
                COALESCE(latest.team, '') AS Team,
                ps.games AS G,
                ps.starts AS GS,
                ps.IP,
                CASE
                    WHEN ps.avg_pitch_count_per_start IS NOT NULL
                        AND ps.starts IS NOT NULL
                    THEN ROUND(ps.avg_pitch_count_per_start * ps.starts, 0)
                    ELSE NULL
                END AS Pitches,
                ps.H,
                ps.ERA,
                ps.WHIP,
                ps.K9 AS "K/9",
                CASE WHEN ps.IP_outs > 0
                    THEN ROUND(ps.BB * 27.0 / ps.IP_outs, 2) ELSE 0 END AS "BB/9",
                ps.SO,
                ps.BB,
                ps.HR,
                ps.BF,
                ps.K_pct AS "K%",
                CASE WHEN ps.BF > 0
                    THEN ROUND(ps.BB * 100.0 / ps.BF, 2) ELSE 0 END AS "BB%",
                NULL AS "SwStr%"
            FROM pitcher_stats ps
            LEFT JOIN (
                SELECT pgl.pitcher_id, pgl.team
                FROM pitcher_game_logs pgl
                INNER JOIN (
                    SELECT pitcher_id, MAX(game_date) AS latest_game_date
                    FROM pitcher_game_logs
                    WHERE season = ?
                    GROUP BY pitcher_id
                ) recent
                    ON recent.pitcher_id = pgl.pitcher_id
                    AND recent.latest_game_date = pgl.game_date
                WHERE pgl.season = ?
                GROUP BY pgl.pitcher_id
            ) latest ON latest.pitcher_id = ps.pitcher_id
            WHERE ps.season = ?
            """,
            (int(season), int(season), int(season)),
        ).fetchall()
    return [dict(row) for row in rows]


def image_html(src, alt, class_name="", fallback_src="", title="", lazy=True):
    if not src and fallback_src:
        src = fallback_src
        fallback_src = ""

    if not src:
        return ""

    classes = f' class="{escape(class_name, quote=True)}"' if class_name else ""
    title_attr = f' title="{escape(title, quote=True)}"' if title else ""
    loading_attr = ' loading="lazy"' if lazy else ""
    onerror = "this.style.display='none';"
    if fallback_src:
        onerror = f"this.onerror=null;this.src={json.dumps(fallback_src)};"

    return (
        f"<img{classes} src=\"{escape(src, quote=True)}\" "
        f"alt=\"{escape(alt, quote=True)}\"{title_attr}{loading_attr} "
        f"referrerpolicy=\"no-referrer\" "
        f"onerror=\"{escape(onerror, quote=True)}\">"
    )


def team_logo_img_html(team_value, alt=None, class_name="stats-identity-img"):
    label = str(alt or team_value or "Team")
    return image_html(
        team_logo_url(team_value),
        label,
        class_name=class_name,
        fallback_src=team_logo_fallback_url(team_value),
        title=label,
    )


def player_image_url(player_id, width=72):
    return player_headshot_url(player_id, width=width)


def display_team_code(row, side):
    value = row.get(f"{side}_team_abbr")
    if not is_missing_value(value):
        return str(value)

    team_name = str(row.get(f"{side}_team") or "")
    if not team_name:
        return side.title()
    return "".join(word[0] for word in team_name.split()[-2:]).upper()


def score_value(value):
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return "-"
    return f"{int(number)}"


def game_status_text(row):
    status = str(row.get("game_status") or "Scheduled")
    abstract_state = str(row.get("abstract_game_state") or "")
    inning = row.get("current_inning_ordinal") or row.get("current_inning")
    inning_state = row.get("inning_state") or row.get("inning_half")

    if abstract_state.lower() == "live" and inning:
        return f"{inning_state or 'Live'} {inning}"
    return status


def game_button_label(row):
    away_team = str(row.get("away_team") or "Away")
    home_team = str(row.get("home_team") or "Home")
    return f"{away_team} @ {home_team}"


def current_query_value(name, default=None):
    value = st.query_params.get(name, default)
    if isinstance(value, list):
        return value[0] if value else default
    return value


def render_view_tabs(view_options):
    active_view = st.session_state.get(
        "active_view",
        current_query_value("view", view_options[0]),
    )
    if active_view not in view_options:
        active_view = view_options[0]
        st.session_state.active_view = active_view

    return st.radio(
        "Dashboard views",
        view_options,
        horizontal=True,
        key="active_view",
        label_visibility="collapsed",
    )


def render_box_tabs(tab_key, options, state_key, default=None):
    default = default or options[0]
    active_value = st.session_state.get(state_key, default)
    if active_value not in options:
        active_value = default
        st.session_state[state_key] = active_value

    return st.radio(
        tab_key,
        options,
        horizontal=True,
        key=state_key,
        label_visibility="collapsed",
    )


def selected_game_row(schedule_df, game_pk):
    if schedule_df.empty or game_pk is None or "game_pk" not in schedule_df.columns:
        return None

    game_pk = pd.to_numeric(game_pk, errors="coerce")
    if pd.isna(game_pk):
        return None

    matches = schedule_df[
        pd.to_numeric(schedule_df["game_pk"], errors="coerce") == int(game_pk)
    ]
    if matches.empty:
        return None
    return matches.iloc[0]


LIVE_SCHEDULE_COLUMNS = {
    "away_score",
    "home_score",
    "game_status",
    "abstract_game_state",
    "current_inning",
    "current_inning_ordinal",
    "inning_state",
    "inning_half",
}


def weather_schedule_frame(schedule_df):
    return schedule_df.drop(
        columns=[
            column
            for column in LIVE_SCHEDULE_COLUMNS
            if column in schedule_df.columns
        ],
        errors="ignore",
    )


def merge_live_schedule_columns(schedule_df, live_schedule_df):
    if (
        schedule_df is None
        or live_schedule_df is None
        or schedule_df.empty
        or live_schedule_df.empty
        or "game_pk" not in schedule_df.columns
        or "game_pk" not in live_schedule_df.columns
    ):
        return schedule_df

    live_columns = [
        column
        for column in LIVE_SCHEDULE_COLUMNS
        if column in live_schedule_df.columns
    ]

    if not live_columns:
        return schedule_df

    result = schedule_df.copy()

    live = live_schedule_df.copy()

    # Remove duplicate column names if Streamlit/live data accidentally creates them
    live = live.loc[:, ~live.columns.duplicated()].copy()
    result = result.loc[:, ~result.columns.duplicated()].copy()

    # Normalize game_pk so int/string mismatches do not break the merge
    result["_merge_game_pk"] = pd.to_numeric(result["game_pk"], errors="coerce")
    live["_merge_game_pk"] = pd.to_numeric(live["game_pk"], errors="coerce")

    live = live.dropna(subset=["_merge_game_pk"]).copy()
    result["_merge_game_pk"] = result["_merge_game_pk"].astype("Int64")

    if live.empty:
        return result.drop(columns=["_merge_game_pk"], errors="ignore")

    live["_merge_game_pk"] = live["_merge_game_pk"].astype("Int64")

    # Keep one live row per game so map() always returns one scalar value
    live = live.drop_duplicates("_merge_game_pk", keep="last")
    live = live.set_index("_merge_game_pk")

    for column in live_columns:
        if column not in live.columns:
            continue

        if column not in result.columns:
            result[column] = pd.NA

        mapped_values = result["_merge_game_pk"].map(live[column])
        result[column] = mapped_values.combine_first(result[column])

    return result.drop(columns=["_merge_game_pk"], errors="ignore")


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


def schedule_team_ids(schedule_df):
    if schedule_df.empty:
        return set()
    return {
        int(team_id)
        for column in ("away_team_id", "home_team_id")
        for team_id in schedule_df.get(column, pd.Series(dtype=float)).dropna()
    }


def scheduled_batter_options(batters_df, schedule_df):
    if batters_df.empty or schedule_df.empty or "Name" not in batters_df.columns:
        return []

    team_ids = schedule_team_ids(schedule_df)
    options_df = batters_df.copy()
    if team_ids and "team_id" in options_df.columns:
        options_df = options_df[
            pd.to_numeric(options_df["team_id"], errors="coerce").isin(team_ids)
        ].copy()

    return sorted(
        {
            str(name).strip()
            for name in options_df["Name"].dropna()
            if str(name).strip()
        },
        key=str.casefold,
    )


def scheduled_pitcher_options(schedule_df):
    if schedule_df.empty:
        return []

    names = set()
    for column in ("away_probable_pitcher", "home_probable_pitcher"):
        if column not in schedule_df.columns:
            continue
        names.update(
            str(name).strip()
            for name in schedule_df[column].dropna()
            if str(name).strip() and str(name).strip().upper() != "TBD"
        )
    return sorted(names, key=str.casefold)


def filter_schedule_for_batter(schedule_df, batters_df, selected_batter):
    if (
        not selected_batter
        or schedule_df.empty
        or batters_df.empty
        or "Name" not in batters_df.columns
        or "team_id" not in batters_df.columns
    ):
        return schedule_df

    player_rows = batters_df[
        batters_df["Name"].fillna("").astype(str).str.casefold()
        == str(selected_batter).casefold()
    ]
    team_ids = {
        int(team_id)
        for team_id in pd.to_numeric(
            player_rows.get("team_id", pd.Series(dtype=float)),
            errors="coerce",
        ).dropna()
    }
    if not team_ids:
        return schedule_df

    return schedule_df[
        pd.to_numeric(schedule_df.get("away_team_id"), errors="coerce").isin(team_ids)
        | pd.to_numeric(schedule_df.get("home_team_id"), errors="coerce").isin(team_ids)
    ].copy()


def filter_schedule_for_pitcher(schedule_df, selected_pitcher):
    if not selected_pitcher or schedule_df.empty:
        return schedule_df

    selected = str(selected_pitcher).strip().casefold()
    away = schedule_df.get("away_probable_pitcher", pd.Series(dtype=str))
    home = schedule_df.get("home_probable_pitcher", pd.Series(dtype=str))
    return schedule_df[
        away.fillna("").astype(str).str.strip().str.casefold().eq(selected)
        | home.fillna("").astype(str).str.strip().str.casefold().eq(selected)
    ].copy()


def matchup_batter_pool(
    batters_df,
    schedule_df,
    selected_batter=None,
    max_per_team=3,
    min_pa=125,
):
    if batters_df.empty or schedule_df.empty:
        return pd.DataFrame()

    team_ids = schedule_team_ids(schedule_df)
    pool = batters_df.copy()
    if team_ids and "team_id" in pool.columns:
        pool = pool[
            pd.to_numeric(pool["team_id"], errors="coerce").isin(team_ids)
        ].copy()

    if pool.empty:
        return pool

    pool["PA_numeric"] = pd.to_numeric(pool.get("PA"), errors="coerce").fillna(0)
    pool["OPS_numeric"] = pd.to_numeric(pool.get("OPS"), errors="coerce").fillna(0)

    selected_mask = pd.Series(False, index=pool.index)
    if selected_batter and "Name" in pool.columns:
        selected_mask = (
            pool["Name"].fillna("").astype(str).str.strip().str.casefold()
            == str(selected_batter).strip().casefold()
        )

    eligible = pool[pool["PA_numeric"] >= min_pa].copy()
    if not eligible.empty and "team_id" in eligible.columns:
        eligible = eligible.sort_values(
            ["team_id", "PA_numeric", "OPS_numeric", "Name"],
            ascending=[True, False, False, True],
        )
        eligible = eligible.groupby("team_id", group_keys=False).head(max_per_team)

    selected_rows = pool[selected_mask].copy()
    result = pd.concat([eligible, selected_rows], ignore_index=True)
    if result.empty:
        result = pool.sort_values(
            ["PA_numeric", "OPS_numeric", "Name"],
            ascending=[False, False, True],
        ).head(max_per_team * max(1, len(team_ids)))

    result = result.drop_duplicates(subset=["player_id"], keep="first")
    return result.drop(columns=["PA_numeric", "OPS_numeric"], errors="ignore")


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


def compact_weather_html(row):
    weather_icon_name = str(row.get("weather_icon") or "unknown")
    weather_svg = weather_icon_svg(weather_icon_name, size=20)
    weather_display = str(row.get("weather_display") or "?")
    weather_edge = str(row.get("weather_edge") or "Neutral")
    weather_tooltip = escape(
        str(row.get("weather_tooltip") or "Forecast unavailable."),
        quote=True,
    )
    return (
        '<span class="schedule-weather-chip schedule-tooltip" '
        f'data-tooltip="{weather_tooltip}" tabindex="0">'
        f"{weather_svg}<span>{escape(weather_display)}</span></span>"
        f'<span class="schedule-weather-edge">{escape(weather_edge)}</span>'
    )


def compact_wind_html(row):
    wind_arrow = str(row.get("wind_arrow") or "\u00b7")
    wind_speed = pd.to_numeric(row.get("wind_speed_mph"), errors="coerce")
    wind_speed_text = f"{float(wind_speed):.0f} mph" if pd.notna(wind_speed) else "N/A"
    wind_tooltip = escape(
        str(row.get("wind_tooltip") or "Wind forecast unavailable."),
        quote=True,
    )
    return (
        '<span class="schedule-wind-chip schedule-tooltip" '
        f'data-tooltip="{wind_tooltip}" tabindex="0">'
        f'<span class="schedule-wind-arrow">{escape(wind_arrow)}</span>'
        f"{escape(wind_speed_text)}</span>"
    )


def pitcher_pair_html(row):
    away_pitcher = str(row.get("away_probable_pitcher") or "TBD")
    home_pitcher = str(row.get("home_probable_pitcher") or "TBD")
    away_hand = str(row.get("away_pitcher_hand") or "")
    home_hand = str(row.get("home_pitcher_hand") or "")

    away_text = escape(away_pitcher)
    if away_hand:
        away_text += f" ({escape(away_hand)})"
    home_text = escape(home_pitcher)
    if home_hand:
        home_text += f" ({escape(home_hand)})"
    return f'<div class="schedule-pitchers">{away_text}<span>{home_text}</span></div>'


def venue_html(row):
    venue = str(row.get("venue_name") or "Venue TBD")
    roof = str(row.get("roof_type") or "Roof unknown")
    return f'<div class="schedule-venue">{escape(venue)}<span>{escape(roof)}</span></div>'


def selected_game_from_schedule_event(table_key, event):
    event_key = f"{table_key}_processed_event"
    if not isinstance(event, dict) or event.get("type") != "select_player":
        return

    event_id = str(event.get("event_id") or "")
    payload = event.get("payload")
    if (
        not event_id
        or event_id == st.session_state.get(event_key)
        or not isinstance(payload, dict)
    ):
        return

    game_pk = payload.get("game_pk")
    if is_missing_value(game_pk):
        return

    st.session_state[event_key] = event_id
    st.session_state.selected_boxscore_game_pk = int(game_pk)


def render_live_schedule_table(df):
    if df.empty:
        st.info("No games are available for this selection.")
        return

    rows = []
    for row_index, row in df.reset_index(drop=True).iterrows():
        game_pk = row.get("game_pk")
        if is_missing_value(game_pk):
            continue

        away_team = str(row.get("away_team") or "")
        home_team = str(row.get("home_team") or "")
        away_logo = team_logo_img_html(
            away_team,
            alt=away_team,
            class_name="schedule-team-logo",
        )
        home_logo = team_logo_img_html(
            home_team,
            alt=home_team,
            class_name="schedule-team-logo",
        )
        away_code = display_team_code(row, "away")
        home_code = display_team_code(row, "home")
        game_payload = json.dumps(
            {"game_pk": int(game_pk)},
            separators=(",", ":"),
        )
        rows.append(
            f"""
            <div class="schedule-weather-row clean-schedule-row">
                <div>
                    <button type="button" class="schedule-game-button"
                            data-research-event="{escape(game_payload, quote=True)}">
                        <span class="overview-score">
                            {away_logo}
                            <span class="overview-team">{escape(away_code)}</span>
                            <span class="score-number">{escape(score_value(row.get("away_score")))}</span>
                            <span class="schedule-at">@</span>
                            {home_logo}
                            <span class="overview-team">{escape(home_code)}</span>
                            <span class="score-number">{escape(score_value(row.get("home_score")))}</span>
                        </span>
                        <span class="score-status">{escape(game_status_text(row))}</span>
                    </button>
                </div>
                {pitcher_pair_html(row)}
                {venue_html(row)}
                <div>{compact_weather_html(row)}</div>
                <div>{compact_wind_html(row)}</div>
            </div>
            """
        )

    table_event = RESEARCH_TABLE_COMPONENT(
        table_html=f"""
        <style>
            .schedule-weather-table {{
                box-sizing: border-box;
                width: 100%;
                border: 1px solid var(--line, #d8dee6);
                background: #ffffff;
                overflow: visible;
            }}
            .schedule-weather-head,
            .schedule-weather-row {{
                display: grid;
                grid-template-columns: minmax(245px, 1.15fr) minmax(155px, 0.82fr) minmax(112px, 0.58fr) minmax(100px, 0.46fr) minmax(100px, 0.48fr);
                align-items: center;
                column-gap: 14px;
                padding: 11px 15px;
                min-width: 0;
            }}
            .schedule-weather-head {{
                background: #eef2f6;
                border-bottom: 1px solid #d8dee6;
                color: #526171;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.07em;
                text-transform: uppercase;
            }}
            .schedule-weather-row {{
                min-height: 68px;
                border-bottom: 1px solid #edf0f4;
                color: #111827;
                font-size: 13px;
            }}
            .schedule-weather-row > div {{
                min-width: 0;
            }}
            .schedule-weather-row:last-child {{
                border-bottom: 0;
            }}
            .schedule-game-button {{
                width: 100%;
                margin: 0;
                padding: 0;
                border: 0;
                background: transparent;
                color: inherit;
                cursor: pointer;
                text-align: left;
            }}
            .schedule-game-button:hover .score-number,
            .schedule-game-button:focus-visible .score-number {{
                border-color: #8fb4d6;
                background: #eef6ff;
            }}
            .schedule-game-button:focus-visible {{
                outline: 2px solid #245f96;
                outline-offset: 2px;
            }}
            .overview-score {{
                display: inline-grid;
                grid-template-columns: 30px 38px 26px 14px 30px 38px 26px;
                align-items: center;
                gap: 6px;
            }}
            .schedule-team-logo {{
                width: 28px;
                height: 28px;
                object-fit: contain;
            }}
            .overview-team {{
                color: #0b2a4a;
                font-size: 15px;
                font-weight: 800;
                letter-spacing: 0.02em;
            }}
            .schedule-game-logos,
            .schedule-weather-chip,
            .schedule-wind-chip {{
                display: inline-flex;
                align-items: center;
                gap: 8px;
            }}
            .schedule-game-logos img {{
                width: 30px;
                height: 30px;
                object-fit: contain;
            }}
            .score-number {{
                min-width: 24px;
                padding: 2px 5px;
                border: 1px solid #cbd5e1;
                background: #f8fafc;
                color: #0f172a;
                text-align: center;
                font-weight: 800;
                font-variant-numeric: tabular-nums;
            }}
            .score-status {{
                display: inline-flex;
                width: fit-content;
                margin-top: 7px;
                padding: 2px 6px;
                border: 1px solid #d2dae4;
                background: #f7fafc;
                color: #526171;
                font-size: 10px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.04em;
            }}
            .schedule-at {{
                color: #7b8794;
                font-weight: 800;
            }}
            .schedule-pitchers,
            .schedule-venue {{
                line-height: 1.45;
            }}
            .schedule-pitchers span,
            .schedule-venue span {{
                display: block;
                color: #647184;
                font-size: 11px;
            }}
            .schedule-weather-chip,
            .schedule-wind-chip {{
                width: fit-content;
                font-size: 13px;
                font-weight: 650;
                white-space: nowrap;
            }}
            .schedule-wind-chip {{
                gap: 4px;
            }}
            .schedule-weather-edge {{
                display: block;
                margin-top: 3px;
                color: #647184;
                font-size: 10px;
                font-weight: 650;
                white-space: nowrap;
            }}
            .schedule-wind-arrow {{
                color: #87919c;
                font-size: 22px;
                font-weight: 800;
                line-height: 1;
            }}
            .weather-svg {{
                flex: 0 0 auto;
            }}
            @media (max-width: 900px) {{
                .schedule-weather-head,
                .schedule-weather-row {{
                    grid-template-columns: minmax(245px, 1.2fr) minmax(165px, 0.9fr) minmax(105px, 0.5fr) minmax(95px, 0.45fr);
                }}
                .schedule-weather-head > div:nth-child(3),
                .schedule-weather-row > div:nth-child(3) {{
                    display: none;
                }}
            }}
            @media (max-width: 680px) {{
                .schedule-weather-head,
                .schedule-weather-row {{
                    grid-template-columns: minmax(0, 1fr);
                    gap: 7px;
                }}
                .schedule-weather-head > div:not(:first-child) {{
                    display: none;
                }}
            }}
        </style>
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
        """,
        table_height=max(150, 42 + (len(rows) * 69)),
        key="live-schedule-table",
        default=None,
    )
    selected_game_from_schedule_event("live-schedule-table", table_event)


def boxscore_team_options(row):
    options = []
    for side, label in (("Home", "home"), ("Away", "away")):
        team_name = str(row.get(f"{label}_team") or side)
        team_code = display_team_code(row, label)
        display = f"{team_name} ({team_code})" if team_code else team_name
        options.append({"label": display, "side": side})
    return options


def filter_boxscore_team(df, selected_side):
    if not selected_side or df.empty or "Side" not in df.columns:
        return df
    return df[df["Side"].astype(str).str.lower() == str(selected_side).lower()].copy()


def render_boxscore_dataframe(df, stat_columns, key):
    if df.empty:
        st.info("No box-score rows are available yet.")
        return

    columns = [
        "Player",
        "Team",
        *[column for column in stat_columns if column in df.columns],
    ]
    header_cells = []
    for column in columns:
        align_class = "align-left" if column in {"Player", "Team", "Pos"} else ""
        min_width = 190 if column == "Player" else 64
        header_cells.append(
            f'<th class="{align_class}" style="min-width:{min_width}px">'
            f"{escape(column)}</th>"
        )

    body_rows = []
    for _, row in df.reset_index(drop=True).iterrows():
        player = str(row.get("Player") or "Unknown")
        player_id = row.get("player_id")
        team = str(row.get("Team") or "")
        headshot = image_html(
            player_image_url(player_id, width=72),
            f"{player} headshot",
            class_name="research-headshot",
            fallback_src=team_logo_fallback_url(team),
        )
        cells = []
        for column in columns:
            align_class = "align-left" if column in {"Player", "Team", "Pos"} else ""
            if column == "Player":
                content = (
                    '<span class="research-player-identity">'
                    f"{headshot}<span>{escape(player)}</span></span>"
                )
            elif column == "Team":
                content = (
                    '<span class="research-log-opponent">'
                    f"{team_logo_img_html(team, alt=team, class_name='stats-identity-img')}"
                    f"<span>{escape(team)}</span></span>"
                )
            else:
                content = escape(stats_cell_value(column, row.get(column)))
            cells.append(f'<td class="{align_class}">{content}</td>')
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    RESEARCH_TABLE_COMPONENT(
        table_html=f"""
        <div class="research-table-shell stats-table-shell boxscore-table-shell">
            <table class="research-table stats-table">
                <thead><tr>{''.join(header_cells)}</tr></thead>
                <tbody>{''.join(body_rows)}</tbody>
            </table>
        </div>
        """,
        table_height=min(560, max(150, 42 + (len(body_rows) * 40))),
        key=key,
        default=None,
    )


def render_selected_game_boxscore(schedule_df):
    game_pk = st.session_state.get("selected_boxscore_game_pk")
    row = selected_game_row(schedule_df, game_pk)
    if row is None:
        return

    away_team = str(row.get("away_team") or "Away")
    home_team = str(row.get("home_team") or "Home")
    away_code = display_team_code(row, "away")
    home_code = display_team_code(row, "home")
    heading_columns = st.columns([8, 1], vertical_alignment="center")
    with heading_columns[0]:
        st.markdown(
            f"""
            <div class="boxscore-shell">
                <div class="section-label">Live Box Score</div>
                <div class="boxscore-scoreboard">
                    <div class="boxscore-team">
                        {team_logo_img_html(away_team, alt=away_team, class_name="boxscore-logo")}
                        <span>{escape(away_code)}</span>
                        <strong>{escape(score_value(row.get("away_score")))}</strong>
                    </div>
                    <span class="schedule-at">@</span>
                    <div class="boxscore-team">
                        {team_logo_img_html(home_team, alt=home_team, class_name="boxscore-logo")}
                        <span>{escape(home_code)}</span>
                        <strong>{escape(score_value(row.get("home_score")))}</strong>
                    </div>
                    <span class="score-status">{escape(game_status_text(row))}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with heading_columns[1]:
        if st.button(
            "Close",
            key="close_boxscore",
            type="tertiary",
            use_container_width=True,
        ):
            st.session_state.selected_boxscore_game_pk = None
            return

    team_options = boxscore_team_options(row)
    team_filter_key = f"boxscore_team_side_{game_pk}"
    option_labels = [option["label"] for option in team_options]
    side_by_label = {
        option["label"]: option["side"]
        for option in team_options
    }
    selected_team_label = render_box_tabs(
        f"boxscore-team-tabs-{game_pk}",
        option_labels,
        team_filter_key,
        option_labels[0],
    )
    selected_side = side_by_label[selected_team_label]

    boxscore = load_game_boxscore(int(game_pk))
    boxscore_group = render_box_tabs(
        f"boxscore-group-tabs-{game_pk}",
        ["Hitters", "Pitchers"],
        f"boxscore_group_{game_pk}",
        "Hitters",
    )
    if boxscore_group == "Hitters":
        render_boxscore_dataframe(
            filter_boxscore_team(boxscore.get("batting", pd.DataFrame()), selected_side),
            ["Pos", "AB", "R", "H", "RBI", "BB", "SO", "HR", "SB", "AVG", "OPS"],
            key=f"boxscore_hitters_{game_pk}",
        )
    else:
        render_boxscore_dataframe(
            filter_boxscore_team(boxscore.get("pitching", pd.DataFrame()), selected_side),
            ["IP", "H", "R", "ER", "BB", "SO", "HR", "PC-ST", "ERA", "WHIP"],
            key=f"boxscore_pitchers_{game_pk}",
        )


@st.fragment
def render_games_tab(schedule_df, filtered_schedule_df, selected_game, selected_date):
    selected_game_display = selected_game if selected_game != "All Games" else "Full slate"
    live_game_count = (
        filtered_schedule_df.get("abstract_game_state", pd.Series(dtype=str))
        .astype(str)
        .str.lower()
        .eq("live")
        .sum()
    )
    final_game_count = (
        filtered_schedule_df.get("game_status", pd.Series(dtype=str))
        .astype(str)
        .str.lower()
        .str.contains("final", na=False)
        .sum()
    )

    st.markdown(
        f"""
        <div class="slate-strip">
            <div class="slate-item">
                <div class="metric-label">Games</div>
                <div class="slate-value">{len(filtered_schedule_df)}</div>
            </div>
            <div class="slate-item">
                <div class="metric-label">Live</div>
                <div class="slate-value">{int(live_game_count)}</div>
            </div>
            <div class="slate-item">
                <div class="metric-label">Final</div>
                <div class="slate-value">{int(final_game_count)}</div>
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
            <div class="section-title">Today's Games <span class="title-date">{format_display_date(selected_date)}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.html(
        '<div class="research-table-note">'
        "Click a game or score to open its live box score."
        "</div>"
    )

    render_live_schedule_table(filtered_schedule_df)
    render_selected_game_boxscore(schedule_df)


BATTER_STREAK_METRICS = [
    {"label": "Hits", "stat": "H", "threshold": 1},
    {"label": "HR", "stat": "HR", "threshold": 1},
    {"label": "RBI", "stat": "RBI", "threshold": 1},
    {"label": "Runs", "stat": "R", "threshold": 1},
    {"label": "SB", "stat": "SB", "threshold": 1},
    {"label": "Ks", "stat": "SO", "threshold": 1},
]

PITCHER_STREAK_METRICS = [
    {"label": "5+ Ks", "stat": "SO", "threshold": 5},
    {"label": "6+ Ks", "stat": "SO", "threshold": 6},
    {"label": "7+ Ks", "stat": "SO", "threshold": 7},
    {"label": "8+ Ks", "stat": "SO", "threshold": 8},
    {"label": "9+ Ks", "stat": "SO", "threshold": 9},
]


def streak_candidates_from_stats(stats_df, player_type, schedule, limit=None):
    if stats_df.empty or "player_id" not in stats_df.columns:
        return pd.DataFrame()

    candidates = stats_df.copy()
    if not schedule.empty:
        team_ids = {
            int(team_id)
            for column in ("away_team_id", "home_team_id")
            for team_id in schedule.get(column, pd.Series(dtype=float)).dropna()
        }
        if team_ids and "team_id" in candidates.columns:
            candidates = candidates[
                pd.to_numeric(candidates["team_id"], errors="coerce").isin(team_ids)
            ].copy()

    candidates = candidates.rename(columns={"Name": "Player"})
    candidates["player_id"] = pd.to_numeric(candidates["player_id"], errors="coerce")
    candidates = candidates.dropna(subset=["player_id", "Player"])
    candidates["player_id"] = candidates["player_id"].astype(int)
    sort_column = "GS" if player_type == "pitcher" else "PA"
    candidates["sort_value"] = pd.to_numeric(
        candidates.get(sort_column),
        errors="coerce",
    ).fillna(0)
    candidates = candidates.sort_values(
        ["sort_value", "Player"],
        ascending=[False, True],
    )
    candidates = candidates[["player_id", "Player", "Team"]]
    if limit is not None:
        candidates = candidates.head(limit)
    return candidates.reset_index(drop=True)


def live_streak_game_rows(schedule):
    rows = []
    for _, row in schedule.iterrows():
        game_pk = row.get("game_pk")
        if is_missing_value(game_pk):
            continue
        game_state = str(row.get("abstract_game_state") or "").lower()
        game_status = row.get("game_status")
        if game_state != "live" and not is_final_state(game_state, game_status):
            continue
        rows.append(
            (
                int(game_pk),
                game_button_label(row),
                row.get("abstract_game_state"),
                row.get("game_status"),
            )
        )
    return tuple(rows)


def collect_live_stats_from_games(game_rows):
    batting_frames = []
    pitching_frames = []

    def load_one_game(game_pk, game_label, abstract_state, game_status):
        try:
            boxscore = get_game_boxscore(int(game_pk))
        except Exception:
            return []

        frames = []
        for frame, target in (
            (boxscore.get("batting", pd.DataFrame()), "batting"),
            (boxscore.get("pitching", pd.DataFrame()), "pitching"),
        ):
            if frame.empty:
                continue
            frame = frame.copy()
            frame["game_pk"] = int(game_pk)
            frame["game"] = game_label
            frame["abstract_game_state"] = abstract_state
            frame["game_status"] = game_status
            frames.append((target, frame))
        return frames

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(game_rows)))) as executor:
        futures = [
            executor.submit(load_one_game, *game_row)
            for game_row in game_rows
        ]
        for future in as_completed(futures):
            for target, frame in future.result():
                if target == "batting":
                    batting_frames.append(frame)
                else:
                    pitching_frames.append(frame)

    batting = pd.concat(batting_frames, ignore_index=True) if batting_frames else pd.DataFrame()
    pitching = pd.concat(pitching_frames, ignore_index=True) if pitching_frames else pd.DataFrame()
    return batting, pitching


@st.cache_resource
def start_live_streak_monitor(game_rows):
    state = {
        "lock": Lock(),
        "ready": Event(),
        "batting": pd.DataFrame(),
        "pitching": pd.DataFrame(),
        "updated_at": None,
    }

    if not game_rows:
        return state

    def refresh_forever():
        while True:
            try:
                batting, pitching = collect_live_stats_from_games(game_rows)
                with state["lock"]:
                    state["batting"] = batting
                    state["pitching"] = pitching
                    state["updated_at"] = time.time()
            except Exception:
                pass
            finally:
                state["ready"].set()
            time.sleep(30)

    Thread(target=refresh_forever, daemon=True).start()
    return state


def monitored_live_streak_stats(schedule):
    game_rows = live_streak_game_rows(schedule)
    state = start_live_streak_monitor(game_rows)
    if game_rows and state["batting"].empty and state["pitching"].empty:
        state["ready"].wait(timeout=5)
    with state["lock"]:
        return state["batting"].copy(), state["pitching"].copy()


def live_played(row, group):
    if row is None:
        return False
    if group == "pitching":
        pitch_count = pd.to_numeric(row.get("Pitch Count"), errors="coerce")
        if pd.notna(pitch_count) and pitch_count > 0:
            return True
        return str(row.get("IP") or "0.0") not in {"", "0.0", "0"}

    plate_appearances = pd.to_numeric(row.get("PA"), errors="coerce")
    return pd.notna(plate_appearances) and plate_appearances > 0


def build_entering_streak_rows(
    candidates,
    metrics,
    historical_logs,
    selected_date,
):
    rows = []
    if candidates.empty:
        return pd.DataFrame()

    if historical_logs is None:
        historical_logs = pd.DataFrame()
    if not historical_logs.empty and "player_id" in historical_logs.columns:
        historical_logs = historical_logs.copy()
        historical_logs["player_id"] = pd.to_numeric(
            historical_logs["player_id"],
            errors="coerce",
        )

    available_columns = set(historical_logs.columns)
    active_metrics = [
        metric for metric in metrics if metric.get("stat") in available_columns
    ]
    if not active_metrics:
        return pd.DataFrame()

    streak_cache = {}
    if not historical_logs.empty and "game_date" in historical_logs.columns:
        logs = historical_logs.copy()
        logs["parsed_date"] = pd.to_datetime(logs["game_date"], errors="coerce")
        logs = logs.dropna(subset=["player_id", "parsed_date"])
        selected_day = pd.to_datetime(selected_date).date()
        logs = logs[logs["parsed_date"].dt.date < selected_day]
        logs = logs.sort_values(
            ["player_id", "parsed_date"],
            ascending=[True, False],
        )

        for metric in active_metrics:
            stat_column = metric["stat"]
            if stat_column not in logs.columns:
                continue
            values = pd.to_numeric(logs[stat_column], errors="coerce").fillna(0)
            metric_logs = logs.assign(
                _meets=(values >= metric["threshold"]).astype(int)
            )
            for player_id, player_logs in metric_logs.groupby("player_id", sort=False):
                if player_logs.empty:
                    streak_cache[(int(player_id), metric["label"])] = 0
                    continue
                streak_cache[(int(player_id), metric["label"])] = int(
                    player_logs["_meets"].cumprod().sum()
                )

    for _, player in candidates.iterrows():
        player_id = int(player.get("player_id"))

        for metric in active_metrics:
            streak = streak_cache.get((player_id, metric["label"]), 0)
            rows.append(
                {
                    "Metric": metric["label"],
                    "Player": player.get("Player"),
                    "Team": player.get("Team"),
                    "player_id": player_id,
                    "Headshot": player_image_url(player_id, width=80),
                    "Streak": 0 if streak is None else streak,
                    "Today": None,
                    "Status": "Entering today",
                }
            )

    return pd.DataFrame(rows)


def build_fast_live_streak_rows(
    candidates,
    metrics,
    historical_logs,
    group,
    live_df,
    selected_date,
):
    result = build_entering_streak_rows(
        candidates,
        metrics,
        historical_logs,
        selected_date,
    )
    if result.empty:
        return result

    live_by_player = {}
    if (
        live_df is not None
        and not live_df.empty
        and "player_id" in live_df.columns
    ):
        working_live = live_df.copy()
        working_live["player_id"] = pd.to_numeric(
            working_live["player_id"],
            errors="coerce",
        )
        live_by_player = {
            int(row["player_id"]): row
            for _, row in working_live.dropna(subset=["player_id"]).iterrows()
        }

    metric_by_label = {
        metric["label"]: metric
        for metric in metrics
    }
    for index, streak_row in result.iterrows():
        player_id = int(streak_row["player_id"])
        current = live_by_player.get(player_id)
        if current is None:
            result.at[index, "Status"] = "Pre-game"
            continue

        metric = metric_by_label.get(streak_row["Metric"])
        if metric is None:
            continue
        current_value = pd.to_numeric(
            current.get(metric["stat"]),
            errors="coerce",
        )
        played = live_played(current, group)
        if pd.notna(current_value):
            result.at[index, "Today"] = float(current_value)

        current_is_final = is_final_state(
            current.get("abstract_game_state"),
            current.get("game_status"),
        )
        if pd.notna(current_value) and float(current_value) >= metric["threshold"]:
            result.at[index, "Streak"] = int(streak_row["Streak"]) + 1
            result.at[index, "Status"] = (
                "Final +1" if current_is_final else "Live +1"
            )
        elif played and current_is_final:
            result.at[index, "Streak"] = 0
            result.at[index, "Status"] = "Ended"
        elif played:
            result.at[index, "Status"] = "In progress"
        else:
            result.at[index, "Status"] = "Pre-game"

    return result


def render_streak_leaderboard(streak_df, metric_label, key):
    if streak_df.empty or "Metric" not in streak_df.columns:
        st.html('<div class="leaderboard-empty">No local completed-game streak data is available for this metric.</div>')
        return

    metric_df = streak_df[streak_df["Metric"] == metric_label].copy()
    if metric_df.empty:
        st.html('<div class="leaderboard-empty">No local completed-game streak data is available for this metric.</div>')
        return

    metric_df["Streak"] = pd.to_numeric(metric_df["Streak"], errors="coerce").fillna(0)
    metric_df["Today"] = pd.to_numeric(metric_df["Today"], errors="coerce")
    metric_df = metric_df[metric_df["Streak"] > 0].copy()
    if metric_df.empty:
        st.html('<div class="leaderboard-empty">No active streaks were found for this metric.</div>')
        return
    metric_df = metric_df.sort_values(
        ["Streak", "Today", "Player"],
        ascending=[False, False, True],
    )
    max_streak = max(1, int(metric_df["Streak"].max()))

    rows = []
    for rank, (_, row) in enumerate(metric_df.iterrows(), start=1):
        streak = int(row.get("Streak") or 0)
        width = max(3, round((streak / max_streak) * 100, 1)) if streak else 3
        status = str(row.get("Status") or "Pending")
        status_class = (
            "hot"
            if status in {"Live +1", "Final +1"}
            else "ended"
            if status == "Ended"
            else ""
        )
        today_value = row.get("Today")
        today_text = "-" if pd.isna(today_value) else f"{float(today_value):.0f}"
        headshot = image_html(
            str(row.get("Headshot") or ""),
            f"{row.get('Player') or 'Player'} headshot",
            class_name="leaderboard-headshot",
        )
        injury_tooltip = row.get("injury_tooltip")
        injury_badge = (
            '<span class="streak-injury-badge" '
            f'title="{escape(str(injury_tooltip), quote=True)}">inj</span>'
            if not is_missing_value(injury_tooltip)
            else ""
        )
        rows.append(
            f"""
            <div class="leaderboard-row">
                <div class="leaderboard-rank">{rank}</div>
                {headshot}
                <div class="leaderboard-name">
                    <strong>{escape(str(row.get("Player") or "Unknown"))}{injury_badge}</strong>
                    <span>{escape(str(row.get("Team") or ""))} | Today: {escape(today_text)}</span>
                </div>
                <div class="leaderboard-bar-track">
                    <span class="leaderboard-bar-fill" style="width:{width}%"></span>
                </div>
                <div class="leaderboard-count">{streak}</div>
                <span class="live-chip {status_class}">{escape(status)}</span>
            </div>
            """
        )

    st.html(
        f"""
        <div class="leaderboard-shell" id="{escape(key, quote=True)}">
            {''.join(rows)}
        </div>
        """
    )


@st.fragment
def render_streaks_tab(
    schedule,
    bvp_matchups_df,
    pitcher_matchups_df,
    batter_stats_df,
    pitcher_stats_df,
    selected_game_value,
    selected_date_value,
):
    live_batting, live_pitching = monitored_live_streak_stats(schedule)
    season_value = pd.to_datetime(selected_date_value).year
    if selected_game_value == "All Games":
        injury_team_ids = set()
        for stats_df in (batter_stats_df, pitcher_stats_df):
            if stats_df.empty or "team_id" not in stats_df.columns:
                continue
            injury_team_ids.update(
                int(team_id)
                for team_id in pd.to_numeric(
                    stats_df["team_id"],
                    errors="coerce",
                ).dropna()
            )
    else:
        injury_team_ids = schedule_team_ids(schedule)
    injury_report = monitored_injury_report(
        sorted(injury_team_ids),
        selected_date_value,
    )

    st.markdown(
        f"""
        <div class="section-shell">
            <div class="section-label">Live Streaks</div>
            <div class="section-title">Streak Leaders <span class="title-date">{format_display_date(selected_date_value)}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    streak_group = render_box_tabs(
        "streak-group-tabs",
        ["Batter Streaks", "Pitcher Streaks"],
        "active_streak_group",
        "Batter Streaks",
    )

    if streak_group == "Pitcher Streaks":
        metrics = PITCHER_STREAK_METRICS
        metric_labels = [metric["label"] for metric in metrics]
        active_metric_label = render_box_tabs(
            "pitcher-streak-metric-tabs",
            metric_labels,
            "active_pitcher_streak_metric",
            metric_labels[0],
        )
        active_metric = [
            metric for metric in metrics if metric["label"] == active_metric_label
        ]
        candidate_schedule = (
            pd.DataFrame()
            if selected_game_value == "All Games"
            else schedule
        )
        pitcher_candidates = streak_candidates_from_stats(
            pitcher_stats_df,
            "pitcher",
            candidate_schedule,
        )
        pitcher_ids = (
            tuple(pitcher_candidates["player_id"].tolist())
            if "player_id" in pitcher_candidates.columns
            else ()
        )
        _, pitcher_logs = monitored_streak_history(
            (),
            pitcher_ids,
            season_value,
        )
        missing_pitcher_ids = missing_streak_player_ids(
            pitcher_logs,
            pitcher_ids,
        )
        if missing_pitcher_ids:
            pitcher_logs = merge_streak_history(
                pitcher_logs,
                load_pitcher_streak_logs(
                    tuple(sorted(missing_pitcher_ids)),
                    season_value,
                ),
            )
        pitcher_streaks = build_fast_live_streak_rows(
            pitcher_candidates,
            active_metric,
            pitcher_logs,
            "pitching",
            live_pitching,
            selected_date_value,
        )
        pitcher_streaks = add_injury_columns(
            pitcher_streaks,
            "player_id",
            injury_report,
        )
        render_streak_leaderboard(
            pitcher_streaks,
            active_metric_label,
            key=f"pitcher-streak-{active_metric_label}",
        )
        return

    metrics = BATTER_STREAK_METRICS
    metric_labels = [metric["label"] for metric in metrics]
    active_metric_label = render_box_tabs(
        "batter-streak-metric-tabs",
        metric_labels,
        "active_batter_streak_metric",
        metric_labels[0],
    )
    active_metric = [
        metric for metric in metrics if metric["label"] == active_metric_label
    ]
    batter_candidates = streak_candidates_from_stats(
        batter_stats_df,
        "batter",
        (
            pd.DataFrame()
            if selected_game_value == "All Games"
            else schedule
        ),
    )
    batter_ids = (
        tuple(batter_candidates["player_id"].tolist())
        if "player_id" in batter_candidates.columns
        else ()
    )
    batter_logs, _ = monitored_streak_history(
        batter_ids,
        (),
        season_value,
    )
    missing_batter_ids = missing_streak_player_ids(
        batter_logs,
        batter_ids,
    )
    if missing_batter_ids:
        batter_logs = merge_streak_history(
            batter_logs,
            load_batter_streak_logs(
                tuple(sorted(missing_batter_ids)),
                season_value,
            ),
        )
    batter_streaks = build_fast_live_streak_rows(
        batter_candidates,
        active_metric,
        batter_logs,
        "batting",
        live_batting,
        selected_date_value,
    )
    batter_streaks = add_injury_columns(
        batter_streaks,
        "player_id",
        injury_report,
    )
    render_streak_leaderboard(
        batter_streaks,
        active_metric_label,
        key=f"batter-streak-{active_metric_label}",
    )


def weighted_rate(values, weights):
    values = pd.to_numeric(values, errors="coerce")
    weights = pd.to_numeric(weights, errors="coerce").fillna(0)
    valid = values.notna() & (weights > 0)
    if not valid.any():
        return None
    return (values[valid] * weights[valid]).sum() / weights[valid].sum()


def numeric_sum(df, column):
    if column not in df.columns:
        return 0.0
    return pd.to_numeric(df[column], errors="coerce").fillna(0).sum()


def safe_rate(numerator, denominator):
    numerator = pd.to_numeric(numerator, errors="coerce")
    denominator = pd.to_numeric(denominator, errors="coerce")
    if pd.isna(numerator) or pd.isna(denominator) or float(denominator) == 0:
        return None
    return float(numerator) / float(denominator)


def team_games_from_group(group, fallback_column="G"):
    if fallback_column in group.columns:
        games = pd.to_numeric(group[fallback_column], errors="coerce")
        if games.notna().any():
            max_games = games.max()
            if pd.notna(max_games) and max_games > 0:
                return float(max_games)
    return 1.0


def apply_per_game_mode(df, total_columns, games_column="G"):
    result = df.copy()
    games = pd.to_numeric(result.get(games_column), errors="coerce").replace(0, pd.NA)
    for column in total_columns:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce") / games
    return result


def prepare_team_batting_stats(df, mode="Total"):
    if df.empty:
        return pd.DataFrame()

    rows = []
    for (team, team_name), group in df.groupby(["Team", "team_name"], dropna=False):
        games = team_games_from_group(group)
        pa = numeric_sum(group, "PA")
        ab = numeric_sum(group, "AB")
        hits = numeric_sum(group, "H")
        walks = numeric_sum(group, "BB")
        hbp = numeric_sum(group, "HBP")
        sac_flies = numeric_sum(group, "SF")
        total_bases = numeric_sum(group, "TB")
        strikeouts = numeric_sum(group, "SO")
        slg = safe_rate(total_bases, ab)
        obp = safe_rate(hits + walks + hbp, ab + walks + hbp + sac_flies)
        rows.append(
            {
                "Team": team,
                "Name": team_name,
                "G": games,
                "H": hits,
                "R": numeric_sum(group, "R"),
                "HR": numeric_sum(group, "HR"),
                "RBI": numeric_sum(group, "RBI"),
                "SB": numeric_sum(group, "SB"),
                "BB": walks,
                "K": strikeouts,
                "AVG": safe_rate(hits, ab),
                "SLG": slg,
                "OPS": (obp + slg) if obp is not None and slg is not None else None,
                "K%": (strikeouts / pa) * 100 if pa else None,
            }
        )

    result = pd.DataFrame(rows)
    if mode == "Per Game":
        result = apply_per_game_mode(
            result,
            ["H", "R", "HR", "RBI", "SB", "BB", "K"],
        )
    if "OPS" in result.columns:
        result = result.sort_values("OPS", ascending=False, na_position="last")
    return result.reset_index(drop=True)


def prepare_team_pitching_stats(df, mode="Total"):
    if df.empty:
        return pd.DataFrame()

    rows = []
    working = df.copy()
    working["IP_decimal"] = working["IP"].apply(parse_baseball_ip) if "IP" in working else None
    for (team, team_name), group in working.groupby(["Team", "team_name"], dropna=False):
        starts = numeric_sum(group, "GS")
        games = starts if starts else team_games_from_group(group)
        rows.append(
            {
                "Team": team,
                "Name": team_name,
                "G": games,
                "ERA": weighted_rate(group.get("ERA"), group.get("IP_decimal")),
                "WHIP": weighted_rate(group.get("WHIP"), group.get("IP_decimal")),
                "K": numeric_sum(group, "SO"),
                "BB": numeric_sum(group, "BB"),
                "HR": numeric_sum(group, "HR"),
                "H": numeric_sum(group, "H"),
            }
        )

    result = pd.DataFrame(rows)
    if mode == "Per Game":
        result = apply_per_game_mode(result, ["K", "BB", "HR", "H"])
    if "ERA" in result.columns:
        result = result.sort_values("ERA", ascending=True, na_position="last")
    return result.reset_index(drop=True)


def normalized_score(df, column, higher_is_better=True):
    if column not in df.columns:
        return pd.Series(0.0, index=df.index)

    values = pd.to_numeric(df[column], errors="coerce")
    valid = values.dropna()
    if valid.empty:
        return pd.Series(0.0, index=df.index)

    min_value = valid.min()
    max_value = valid.max()
    if max_value == min_value:
        score = pd.Series(0.0, index=df.index)
        score[values.notna()] = 0.5
        return score

    score = (values - min_value) / (max_value - min_value)
    if not higher_is_better:
        score = 1 - score
    return score.fillna(0)


def capped_volume_score(df, column, quantile=0.85, floor=1):
    if column not in df.columns:
        return pd.Series(0.0, index=df.index)

    values = pd.to_numeric(df[column], errors="coerce").fillna(0)
    positive = values[values > 0]
    if positive.empty:
        return pd.Series(0.0, index=df.index)

    target = max(float(positive.quantile(quantile)), float(floor), 1.0)
    return (values / target).clip(upper=1).fillna(0)


def add_batter_leader_score(result):
    pa_volume = capped_volume_score(result, "PA", floor=80)
    ab_volume = capped_volume_score(result, "AB", floor=65)
    sample_factor = 0.35 + (0.65 * pa_volume)

    result["leader_score"] = (
        0.18 * normalized_score(result, "OPS") * sample_factor
        + 0.12 * normalized_score(result, "AVG") * sample_factor
        + 0.10 * normalized_score(result, "OBP") * sample_factor
        + 0.10 * normalized_score(result, "SLG") * sample_factor
        + 0.10 * pa_volume
        + 0.06 * ab_volume
        + 0.08 * normalized_score(result, "H")
        + 0.07 * normalized_score(result, "HR")
        + 0.07 * normalized_score(result, "RBI")
        + 0.05 * normalized_score(result, "BB")
        + 0.04 * normalized_score(result, "R")
        + 0.03 * normalized_score(result, "SB")
        + 0.02 * normalized_score(result, "HBP")
        + 0.05 * normalized_score(result, "K%", higher_is_better=False)
        + 0.03 * normalized_score(result, "BB%")
    )
    return result


def add_pitcher_leader_score(result):
    result = result.copy()
    if "IP" in result.columns:
        result["IP_decimal"] = result["IP"].apply(parse_baseball_ip)
    else:
        result["IP_decimal"] = 0

    ip_volume = capped_volume_score(result, "IP_decimal", floor=35)
    start_volume = capped_volume_score(result, "GS", floor=6)
    workload_factor = 0.35 + (0.65 * ip_volume)
    innings = pd.to_numeric(result["IP_decimal"], errors="coerce").replace(0, pd.NA)
    result["HR_per_IP"] = pd.to_numeric(result.get("HR"), errors="coerce") / innings
    result["H_per_IP"] = pd.to_numeric(result.get("H"), errors="coerce") / innings

    result["leader_score"] = (
        0.22 * normalized_score(result, "ERA", higher_is_better=False) * workload_factor
        + 0.18 * normalized_score(result, "WHIP", higher_is_better=False) * workload_factor
        + 0.11 * ip_volume
        + 0.07 * start_volume
        + 0.12 * normalized_score(result, "K")
        + 0.10 * normalized_score(result, "K/9")
        + 0.06 * normalized_score(result, "K%")
        + 0.06 * normalized_score(result, "BB%", higher_is_better=False)
        + 0.04 * normalized_score(result, "BB/9", higher_is_better=False)
        + 0.02 * normalized_score(result, "HR_per_IP", higher_is_better=False)
        + 0.02 * normalized_score(result, "H_per_IP", higher_is_better=False)
    )
    return result


def prepare_player_stats(df, player_type):
    if df.empty:
        return pd.DataFrame()

    result = df.copy()
    result = result.rename(columns={"Name": "Player"})
    identity_columns = ["player_id", "team_id", "team_name"]
    if player_type == "pitcher":
        result = result.rename(columns={"SO": "K"})
        result = add_pitcher_leader_score(result)
        columns = [
            *identity_columns,
            "Player",
            "Team",
            "IP",
            "GS",
            "H",
            "BB",
            "K",
            "HR",
            "ERA",
            "WHIP",
            "K/9",
            "K%",
        ]
        result = result.sort_values(
            ["leader_score", "IP_decimal", "Player"],
            ascending=[False, False, True],
            na_position="last",
        )
    else:
        result = result.rename(columns={"SO": "K"})
        result = add_batter_leader_score(result)
        columns = [
            *identity_columns,
            "Player",
            "Team",
            "PA",
            "AB",
            "R",
            "H",
            "BB",
            "HBP",
            "K",
            "HR",
            "RBI",
            "AVG",
            "OBP",
            "SLG",
            "OPS",
            "K%",
            "BB%",
        ]
        result = result.sort_values(
            ["leader_score", "PA", "AB", "Player"],
            ascending=[False, False, False, True],
            na_position="last",
        )

    columns = [column for column in columns if column in result.columns]
    return result[columns].reset_index(drop=True)


STATS_COLUMN_LABELS = {
    "Rank": "Rank",
    "Team": "Team",
    "Player": "Player",
    "G": "G",
    "H": "H",
    "R": "R",
    "HR": "HR",
    "RBI": "RBI",
    "SB": "SB",
    "BB": "BB",
    "K": "K",
    "PA": "PA",
    "AB": "AB",
    "HBP": "HBP",
    "AVG": "AVG",
    "OBP": "OBP",
    "SLG": "SLG",
    "OPS": "OPS",
    "K%": "K%",
    "BB%": "BB%",
    "IP": "IP",
    "GS": "GS",
    "ERA": "ERA",
    "WHIP": "WHIP",
    "K/9": "K/9",
}

STATS_ALIGN_LEFT_COLUMNS = {"Team", "Player"}
STATS_THREE_DECIMAL_COLUMNS = {"AVG", "OBP", "SLG", "OPS"}
STATS_TWO_DECIMAL_COLUMNS = {"K%", "BB%", "ERA", "WHIP", "K/9"}


def stats_cell_value(column, value, mode="Total"):
    if column == "Rank":
        return str(value)
    if is_missing_value(value):
        return "-"

    number = pd.to_numeric(value, errors="coerce")
    if column in STATS_THREE_DECIMAL_COLUMNS and pd.notna(number):
        return f"{float(number):.3f}".replace("0.", ".")
    if column in STATS_TWO_DECIMAL_COLUMNS and pd.notna(number):
        return f"{float(number):.2f}"
    if column == "G" and pd.notna(number):
        return f"{float(number):.0f}"
    if (
        mode == "Per Game"
        and column in {"H", "R", "HR", "RBI", "SB", "BB", "K"}
        and pd.notna(number)
    ):
        return f"{float(number):.2f}"
    if pd.notna(number):
        return f"{float(number):.0f}"
    return str(value)


def stats_sort_metadata(row, column):
    if column == "Team":
        value = row.get("Name") or row.get("team_name") or row.get("Team")
    else:
        value = row.get(column)
    if is_missing_value(value):
        return "", "missing"
    number = pd.to_numeric(value, errors="coerce")
    if pd.notna(number):
        return str(float(number)), "number"
    return str(value).strip().lower(), "text"


def stats_identity_html(row, column, event_payload=None):
    if column == "Team":
        team_code = str(row.get("Team") or "")
        team_name = str(row.get("Name") or row.get("team_name") or team_code)
        display_name = team_code if row.get("Player") else team_name
        logo = team_logo_img_html(
            team_code or team_name,
            alt=team_name,
            class_name="stats-identity-img",
        )
        return (
            '<span class="research-log-opponent">'
            f"{logo}"
            f"<span>{escape(display_name)}</span>"
            "</span>"
        )

    player = str(row.get("Player") or "Unknown")
    player_id = row.get("player_id")
    team_code = str(row.get("Team") or "")
    logo = image_html(
        player_image_url(player_id, width=64),
        f"{player} headshot",
        class_name="stats-identity-img stats-headshot",
        fallback_src=team_logo_fallback_url(team_code),
    )
    if not logo:
        logo = team_logo_img_html(
            team_code,
            alt=team_code,
            class_name="stats-identity-img",
        )
    identity = (
        '<span class="research-player-identity">'
        f"{logo}"
        f"<span>{escape(player)}</span>"
        "</span>"
    )
    if event_payload:
        return (
            '<button type="button" class="research-player-link" '
            f'data-research-event="{escape(event_payload, quote=True)}">'
            f"{identity}</button>"
        )
    return f'<span class="research-log-opponent">{identity}</span>'


def render_clean_stats_table(
    df,
    columns,
    table_key,
    mode="Total",
    player_log_group=None,
    season=None,
):
    if df.empty:
        st.info("No stats are available for this selection.")
        return

    table_df = df.copy().reset_index(drop=True)
    preserve_rank = "Rank" in table_df.columns
    if not preserve_rank:
        table_df.insert(0, "Rank", range(1, len(table_df) + 1))
    display_columns = ["Rank", *[column for column in columns if column in table_df.columns]]

    header_cells = []
    for index, column in enumerate(display_columns):
        label = STATS_COLUMN_LABELS.get(column, column)
        align_class = "align-left" if column in STATS_ALIGN_LEFT_COLUMNS else ""
        if column == "Rank":
            header_cells.append(
                f'<th class="{align_class}" style="min-width:58px">{escape(label)}</th>'
            )
            continue
        header_cells.append(
            f'<th class="{align_class}" aria-sort="none">'
            f'<button type="button" class="research-sort-button" data-column-index="{index}">'
            f"<span>{escape(label)}</span>"
            '<span class="research-sort-indicator" aria-hidden="true"></span>'
            "</button></th>"
        )

    body_rows = []
    for _, row in table_df.iterrows():
        cells = []
        for column in display_columns:
            sort_value, sort_kind = stats_sort_metadata(row, column)
            align_class = "align-left" if column in STATS_ALIGN_LEFT_COLUMNS else ""
            rank_attr = (
                " data-rank-cell"
                if column == "Rank" and not preserve_rank
                else ""
            )
            if column in STATS_ALIGN_LEFT_COLUMNS:
                event_payload = None
                if column == "Player" and player_log_group:
                    player_id = pd.to_numeric(
                        row.get("player_id"),
                        errors="coerce",
                    )
                    event_payload = json.dumps(
                        {
                            "log_type": "player_season",
                            "group": player_log_group,
                            "player_id": (
                                int(player_id)
                                if pd.notna(player_id)
                                else None
                            ),
                            "player": row.get("Player"),
                            "team": row.get("Team"),
                            "season": season,
                        },
                        separators=(",", ":"),
                    )
                content = stats_identity_html(
                    row,
                    column,
                    event_payload=event_payload,
                )
            else:
                content = escape(stats_cell_value(column, row.get(column), mode=mode))
            cells.append(
                f'<td class="{align_class}"{rank_attr} '
                f'data-sort-value="{escape(sort_value, quote=True)}" '
                f'data-sort-kind="{sort_kind}">{content}</td>'
            )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    table_event = RESEARCH_TABLE_COMPONENT(
        table_html=f"""
        <div class="research-table-shell stats-table-shell" id="{escape(table_key, quote=True)}">
            <table class="research-table stats-table">
                <thead><tr>{''.join(header_cells)}</tr></thead>
                <tbody>{''.join(body_rows)}</tbody>
            </table>
        </div>
        """,
        table_height=min(542, max(82, 42 + (len(table_df) * 38))),
        key=table_key,
        default=None,
    )
    if player_log_group:
        render_selected_player_season_log(
            table_key,
            selected_log_from_event(table_key, table_event),
        )


def render_team_stats_tab(batter_stats_df, pitcher_stats_df):
    st.markdown(
        """
        <div class="section-shell">
            <div class="section-label">Team Stats</div>
            <div class="section-title">Season Team Leaders</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    stats_group = render_box_tabs(
        "team-stats-tabs",
        ["Batting", "Pitching"],
        "active_team_stats_group",
        "Batting",
    )
    if stats_group == "Batting":
        mode = st.segmented_control(
            "Batting Mode",
            ["Total", "Per Game"],
            default="Total",
            key="team_batting_mode",
            label_visibility="collapsed",
        ) or "Total"
        render_clean_stats_table(
            prepare_team_batting_stats(batter_stats_df, mode=mode),
            ["Team", "G", "H", "R", "HR", "RBI", "SB", "BB", "K", "AVG", "SLG", "OPS", "K%"],
            table_key=f"team-batting-stats-{mode}",
            mode=mode,
        )
        return

    mode = st.segmented_control(
        "Pitching Mode",
        ["Total", "Per Game"],
        default="Total",
        key="team_pitching_mode",
        label_visibility="collapsed",
    ) or "Total"
    render_clean_stats_table(
        prepare_team_pitching_stats(pitcher_stats_df, mode=mode),
        ["Team", "G", "ERA", "WHIP", "K", "BB", "HR", "H"],
        table_key=f"team-pitching-stats-{mode}",
        mode=mode,
    )


def player_leader_options(df):
    if df.empty or "Player" not in df.columns:
        return []
    return sorted(
        {
            str(player).strip()
            for player in df["Player"].dropna()
            if str(player).strip()
        },
        key=str.casefold,
    )


def filter_player_leaders_for_search(df, selected_player):
    selected_player = str(selected_player or "").strip()
    if df.empty:
        return df

    ranked = df.copy().reset_index(drop=True)
    ranked.insert(0, "Rank", range(1, len(ranked) + 1))
    if not selected_player:
        return df.head(100)

    player_names = ranked.get("Player", pd.Series(dtype=str)).fillna("").astype(str)
    return ranked[
        player_names.str.strip().str.casefold() == selected_player.casefold()
    ].copy()


@st.fragment
def render_player_stats_tab(batter_stats_df, pitcher_stats_df, season):
    st.markdown(
        """
        <div class="section-shell">
            <div class="section-label">Player Stats</div>
            <div class="section-title">Season Player Leaders</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.html(
        '<div class="research-table-note">'
        "Click a player name to open their season game log. "
        "Click a column heading to sort the leaderboard."
        "</div>"
    )
    stats_group = render_box_tabs(
        "player-stats-tabs",
        ["Batters", "Pitchers"],
        "active_player_stats_group",
        "Batters",
    )
    if stats_group == "Batters":
        batter_leaders = prepare_player_stats(batter_stats_df, "batter")
        batter_leader_options = player_leader_options(batter_leaders)
        if st.session_state.get("player_stats_batter_search") not in [
            None,
            *batter_leader_options,
        ]:
            st.session_state.player_stats_batter_search = None
        batter_search = st.selectbox(
            "Search batter leaders",
            batter_leader_options,
            index=None,
            placeholder="Search batter...",
            key="player_stats_batter_search",
            label_visibility="collapsed",
        )
        render_clean_stats_table(
            filter_player_leaders_for_search(batter_leaders, batter_search),
            ["Player", "Team", "PA", "AB", "R", "H", "BB", "HBP", "K", "HR", "RBI", "SB", "AVG", "OBP", "SLG", "OPS", "K%", "BB%"],
            table_key="player-batter-stats",
            player_log_group="batting",
            season=season,
        )
        return

    pitcher_leaders = prepare_player_stats(pitcher_stats_df, "pitcher")
    pitcher_leader_options = player_leader_options(pitcher_leaders)
    if st.session_state.get("player_stats_pitcher_search") not in [
        None,
        *pitcher_leader_options,
    ]:
        st.session_state.player_stats_pitcher_search = None
    pitcher_search = st.selectbox(
        "Search pitcher leaders",
        pitcher_leader_options,
        index=None,
        placeholder="Search pitcher...",
        key="player_stats_pitcher_search",
        label_visibility="collapsed",
    )
    render_clean_stats_table(
        filter_player_leaders_for_search(pitcher_leaders, pitcher_search),
        ["Player", "Team", "IP", "GS", "H", "BB", "K", "HR", "ERA", "WHIP", "K/9", "K%"],
        table_key="player-pitcher-stats",
        player_log_group="pitching",
        season=season,
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
        f"{image_html(first_logo, first_team, fallback_src=team_logo_fallback_url(first_team), title=first_team)}"
        f'<span class="research-at">{separator}</span>'
        f"{image_html(second_logo, second_team, fallback_src=team_logo_fallback_url(second_team), title=second_team)}"
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
        player_id_column = f"{player_column}_id"
        player_id = row.get(player_id_column)
        headshot_html = image_html(
            player_image_url(player_id, width=64),
            f"{player_name} headshot",
            class_name="research-headshot",
        )
        player_identity_html = (
            '<span class="research-player-identity">'
            f"{headshot_html}<span>{escape(player_name)}</span>"
            "</span>"
        )
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
            f"{player_identity_html}</button>"
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
        f"{image_html(logo, opponent, fallback_src=team_logo_fallback_url(opponent), title=opponent)}"
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


def render_selected_player_season_log(table_key, selected_log):
    if selected_log is None:
        return

    if st.button(
        "\u00d7 Close log",
        key=f"{table_key}_close_player_log",
        type="tertiary",
    ):
        st.session_state[f"{table_key}_selected_log"] = None
        return

    player_id = pd.to_numeric(selected_log.get("player_id"), errors="coerce")
    if pd.isna(player_id):
        st.warning("Player ID was not found for this row.")
        return

    group = selected_log.get("group") or "batting"
    season_value = int(selected_log.get("season") or season)
    player_name = str(selected_log.get("player") or "Player")
    game_log_df = load_database_player_game_log(
        int(player_id),
        group,
        season_value,
    )

    st.markdown(
        f"""
        <div class="section-shell game-log-heading">
            <div class="section-label">Season Game Log</div>
            <div class="section-title">
                {escape(player_name)} - {season_value}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if game_log_df.empty:
        st.warning("No completed-game history was found for this season.")
        return

    game_log_df = game_log_df.copy()
    if "game_date" in game_log_df.columns:
        game_log_df["_game_date_sort"] = pd.to_datetime(
            game_log_df["game_date"],
            errors="coerce",
        )
        game_log_df = (
            game_log_df.sort_values(
                "_game_date_sort",
                ascending=False,
                na_position="last",
            )
            .drop(columns="_game_date_sort")
            .reset_index(drop=True)
        )

    if group == "pitching":
        game_log_cols = [
            "game_date",
            "team",
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
            "ER",
        ]
    else:
        game_log_cols = [
            "game_date",
            "team",
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

    game_log_cols = [
        column
        for column in game_log_cols
        if column in game_log_df.columns
    ]
    render_game_log_table(
        game_log_df[game_log_cols],
        game_log_cols,
        log_type=group,
        table_key=f"{table_key}-{int(player_id)}-{season_value}-game-log",
    )
    if group == "pitching":
        chart_html = build_recent_bar_chart_html(
            game_log_df,
            value_column="SO",
            title="Strikeouts - Last 5 Games",
            subtitle=player_name,
            scale_floor=10,
            accent="#173f67",
        )
    else:
        chart_html = build_recent_bar_chart_html(
            game_log_df,
            value_column="TB",
            title="Total Bases - Last 5 Games",
            subtitle=player_name,
            scale_floor=4,
            accent="#245f96",
        )
    if chart_html:
        st.html(chart_html)


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
        "\u00d7 Close log",
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


def default_matchup_display(df, grade_column, selected_batter=None, selected_pitcher=None, limit=100):
    if df.empty:
        return df
    if selected_batter or selected_pitcher or grade_column not in df.columns:
        return df.reset_index(drop=True)

    hidden_grades = {"small sample", "no history", "no data"}
    grade_values = df[grade_column].fillna("").astype(str).str.strip().str.casefold()
    display_df = df[~grade_values.isin(hidden_grades)].copy()
    return display_df.head(limit).reset_index(drop=True)


@st.fragment
def render_bvp_table_fragment(
    filtered_bvp_matchups,
    selected_batter=None,
    selected_pitcher=None,
):
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
    display_bvp = default_matchup_display(
        display_bvp,
        "matchup_grade",
        selected_batter=selected_batter,
        selected_pitcher=selected_pitcher,
    )

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
def render_hand_table_fragment(
    filtered_hand_matchups,
    selected_batter=None,
    selected_pitcher=None,
):
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
    display_hand = default_matchup_display(
        display_hand,
        "matchup_grade",
        selected_batter=selected_batter,
        selected_pitcher=selected_pitcher,
    )

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
def render_pitcher_table_fragment(
    filtered_pitcher_k_matchups,
    selected_pitcher=None,
):
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

    display_k = default_matchup_display(
        filtered_pitcher_k_matchups,
        "k_matchup_grade",
        selected_pitcher=selected_pitcher,
        limit=40,
    )

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


@st.cache_resource
def start_hand_split_preload(season):
    preload = getattr(
        stat_data_service,
        "preload_hitter_hand_splits",
        None,
    )
    if preload is None:
        return None, None
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(preload, int(season))
    return executor, future


app_today = current_app_date()
try:
    if "MLB_DB_URL" in st.secrets:
        os.environ.setdefault("MLB_DB_URL", st.secrets["MLB_DB_URL"])
except Exception:
    pass


if "selected_game_date" not in st.session_state:
    st.session_state.selected_game_date = app_today
if "data_snapshot_id" not in st.session_state:
    st.session_state.data_snapshot_id = uuid.uuid4().hex


def shift_selected_date(days):
    st.session_state.selected_game_date += timedelta(days=days)


view_options = [
    "Matchups",
    "Games",
    "Streaks",
    "Player Stats",
    "Team Stats",
    "Details",
]
initial_view = current_query_value("view", "Matchups")
initial_view = st.session_state.get("active_view", initial_view)
if initial_view == "Overview":
    initial_view = "Games"
if initial_view not in view_options:
    initial_view = "Matchups"
st.session_state.active_view = initial_view
active_view = render_view_tabs(view_options)
view_loading = st.empty()
view_loading.markdown(
    f"""
    <div class="view-loading" role="status" aria-live="polite">
        <span class="view-loading-wheel" aria-hidden="true"></span>
        <span>Loading {escape(active_view)}...</span>
    </div>
    """,
    unsafe_allow_html=True,
)
if active_view not in {"Games", "Details"}:
    database.ensure_database()
needs_schedule = active_view in {"Games", "Matchups", "Streaks"}
needs_weather = active_view in {"Games", "Matchups"}
hand_split_preload_future = None
if (
    active_view == "Matchups"
    and st.session_state.get(
        "active_matchup_table",
        "Hitter vs Pitcher",
    )
    == "Hitter vs Throwing Hand"
):
    _, hand_split_preload_future = start_hand_split_preload(
        st.session_state.selected_game_date.year
    )

batter_filter_slot = None
game_filter_slot = None
pitcher_filter_slot = None
selected_date = st.session_state.selected_game_date

if needs_schedule:
    with st.container(key="matchup_toolbar"):
        if active_view == "Matchups":
            toolbar_columns = st.columns(
                [1.8, 2.25, 1.8, 0.38, 1.45, 0.38],
                gap="small",
                vertical_alignment="bottom",
            )
            with toolbar_columns[0]:
                batter_filter_slot = st.empty()
            with toolbar_columns[1]:
                game_filter_slot = st.empty()
            with toolbar_columns[2]:
                pitcher_filter_slot = st.empty()
            previous_column = toolbar_columns[3]
            date_column = toolbar_columns[4]
            next_column = toolbar_columns[5]
        else:
            toolbar_columns = st.columns(
                [2.7, 0.38, 1.45, 0.38, 3.25],
                gap="small",
                vertical_alignment="bottom",
            )
            with toolbar_columns[0]:
                game_filter_slot = st.empty()
            previous_column = toolbar_columns[1]
            date_column = toolbar_columns[2]
            next_column = toolbar_columns[3]

        with previous_column:
            st.button(
                "\u2039",
                key="previous_game_date",
                help="Previous day",
                on_click=shift_selected_date,
                args=(-1,),
                use_container_width=True,
            )
        with date_column:
            selected_date = st.date_input(
                "Game Date",
                key="selected_game_date",
                label_visibility="collapsed",
            )
        with next_column:
            st.button(
                "\u203a",
                key="next_game_date",
                help="Next day",
                on_click=shift_selected_date,
                args=(1,),
                use_container_width=True,
            )

season = selected_date.year
data_snapshot_id = st.session_state.data_snapshot_id


@st.cache_data(show_spinner=False, ttl=30)
def load_schedule(game_date, snapshot_id):
    return get_daily_schedule(str(game_date))


def injury_cache_path(game_date):
    return (
        Path(__file__).parent
        / "data"
        / "precomputed"
        / f"injuries-{game_date}.json"
    )


@st.cache_resource
def start_injury_monitor(team_ids, game_date):
    team_ids = tuple(team_ids)
    game_date = str(game_date)
    cached_report = {}
    cache_path = injury_cache_path(game_date)
    try:
        cached_report = {
            int(player_id): detail
            for player_id, detail in json.loads(
                cache_path.read_text(encoding="utf-8")
            ).items()
        }
    except Exception:
        cached_report = {}

    state = {
        "lock": Lock(),
        "report": cached_report,
        "updated_at": None,
    }

    def refresh_once():
        try:
            report = fetch_injury_report(team_ids, game_date)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(report, separators=(",", ":")),
                encoding="utf-8",
            )
            with state["lock"]:
                state["report"] = report
                state["updated_at"] = time.time()
        except Exception:
            return

    Thread(target=refresh_once, daemon=True).start()
    return state


def monitored_injury_report(team_ids, game_date):
    state = start_injury_monitor(tuple(team_ids), str(game_date))
    with state["lock"]:
        return dict(state["report"])


@st.cache_data(show_spinner=False, ttl=600)
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


@st.cache_resource
def start_live_stat_monitor(season):
    state = {
        "lock": Lock(),
        "ready": Event(),
        "batters": pd.DataFrame(local_batter_season_stats(int(season))),
        "pitchers": pd.DataFrame(local_pitcher_season_stats(int(season))),
        "updated_at": None,
    }
    state["batters"] = add_team_ids_from_names(state["batters"])
    state["pitchers"] = add_team_ids_from_names(state["pitchers"])

    def refresh_forever():
        while True:
            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    batter_future = executor.submit(
                        get_batter_stats,
                        int(season),
                        False,
                    )
                    pitcher_future = executor.submit(
                        get_pitcher_stats,
                        int(season),
                        False,
                    )
                    batters = batter_future.result()
                    pitchers = pitcher_future.result()
                with state["lock"]:
                    state["batters"] = batters
                    state["pitchers"] = pitchers
                    state["updated_at"] = time.time()
                    state["ready"].set()
            except Exception:
                state["ready"].set()
            time.sleep(600)

    Thread(target=refresh_forever, daemon=True).start()
    return state


def monitored_live_stat_tables(season):
    state = start_live_stat_monitor(int(season))
    with state["lock"]:
        return state["batters"].copy(), state["pitchers"].copy()


@st.cache_data(show_spinner=False, ttl=3600)
def load_bvp_matchups(schedule_df, batters_df, season):
    return build_batter_vs_pitcher_matchups(
        schedule_df=schedule_df,
        batters_df=batters_df,
        season=int(season),
        min_pa=0,
    )


@st.cache_data(show_spinner=False, ttl=3600)
def load_hand_matchups(schedule_df, batters_df, season):
    return build_batter_vs_hand_matchups(
        schedule_df=schedule_df,
        batters_df=batters_df,
        season=int(season),
        min_pa=0,
    )


@st.cache_data(show_spinner=False, ttl=3600)
def load_pitcher_matchups(schedule_df, batters_df, pitchers_df):
    return build_pitcher_k_matchups(
        schedule_df=schedule_df,
        batters_df=batters_df,
        pitchers_df=pitchers_df,
        min_pa=0,
    )


@st.cache_data(show_spinner=False, ttl=20)
def load_game_boxscore(game_pk):
    return get_game_boxscore(int(game_pk))


@st.cache_data(show_spinner=False, ttl=600)
def load_database_player_game_log(player_id, group, season):
    try:
        live_rows = get_player_game_log(
            int(player_id),
            group,
            int(season),
        )
        if not live_rows.empty:
            return live_rows
    except Exception:
        pass

    if group == "pitching":
        loader = getattr(
            database,
            "get_pitcher_season_game_logs_from_db",
            None,
        )
    else:
        loader = getattr(
            database,
            "get_batter_season_game_logs_from_db",
            None,
        )
    if loader is None:
        return pd.DataFrame()
    rows = loader(int(player_id), int(season))
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def load_batter_streak_logs(player_ids, season):
    loader = getattr(database, "get_batter_streak_game_logs_from_db", None)
    if loader is None:
        return pd.DataFrame()
    return pd.DataFrame(loader(tuple(player_ids), season))


@st.cache_data(show_spinner=False)
def load_pitcher_streak_logs(player_ids, season):
    loader = getattr(database, "get_pitcher_streak_game_logs_from_db", None)
    if loader is None:
        return pd.DataFrame()
    return pd.DataFrame(loader(tuple(player_ids), season))


def streak_history_cache_path(group, season):
    return (
        Path(__file__).parent
        / "data"
        / "precomputed"
        / f"{group}-streak-history-{int(season)}.pkl"
    )


@st.cache_resource
def start_streak_history_monitor(batter_ids, pitcher_ids, season):
    batter_ids = tuple(batter_ids)
    pitcher_ids = tuple(pitcher_ids)
    season = int(season)

    def read_cache(group):
        try:
            return pd.read_pickle(streak_history_cache_path(group, season))
        except Exception:
            return pd.DataFrame()

    def merge_history(cached, refreshed):
        if refreshed is None or refreshed.empty:
            return cached
        if cached is None or cached.empty:
            return refreshed

        combined = pd.concat([cached, refreshed], ignore_index=True)
        duplicate_keys = [
            column
            for column in ("player_id", "game_pk")
            if column in combined.columns
        ]
        if len(duplicate_keys) < 2:
            duplicate_keys = [
                column
                for column in ("player_id", "game_date")
                if column in combined.columns
            ]
        if len(duplicate_keys) == 2:
            combined = combined.drop_duplicates(
                duplicate_keys,
                keep="last",
            )
        return combined.reset_index(drop=True)

    state = {
        "lock": Lock(),
        "ready": Event(),
        "batting": read_cache("hitting"),
        "pitching": read_cache("pitching"),
        "updated_at": None,
    }

    def refresh_forever():
        while True:
            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    batter_future = (
                        executor.submit(
                            fetch_people_game_logs,
                            batter_ids,
                            "hitting",
                            season,
                        )
                        if batter_ids
                        else None
                    )
                    pitcher_future = (
                        executor.submit(
                            fetch_people_game_logs,
                            pitcher_ids,
                            "pitching",
                            season,
                        )
                        if pitcher_ids
                        else None
                    )
                    refreshed_batting = (
                        batter_future.result()
                        if batter_future is not None
                        else pd.DataFrame()
                    )
                    refreshed_pitching = (
                        pitcher_future.result()
                        if pitcher_future is not None
                        else pd.DataFrame()
                    )
                with state["lock"]:
                    batting = merge_history(
                        state["batting"],
                        refreshed_batting,
                    )
                    pitching = merge_history(
                        state["pitching"],
                        refreshed_pitching,
                    )

                for group, player_ids, frame in (
                    ("hitting", batter_ids, batting),
                    ("pitching", pitcher_ids, pitching),
                ):
                    if not player_ids:
                        continue
                    path = streak_history_cache_path(group, season)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    frame.to_pickle(path)

                with state["lock"]:
                    state["batting"] = batting
                    state["pitching"] = pitching
                    state["updated_at"] = time.time()
                    state["ready"].set()
            except Exception:
                state["ready"].set()
            time.sleep(300)

    Thread(target=refresh_forever, daemon=True).start()
    return state


def missing_streak_player_ids(history, player_ids):
    player_ids = {
        int(player_id)
        for player_id in player_ids
    }
    if not player_ids:
        return set()
    if history is None or history.empty or "player_id" not in history.columns:
        return player_ids
    cached_ids = {
        int(player_id)
        for player_id in pd.to_numeric(
            history["player_id"],
            errors="coerce",
        ).dropna()
    }
    return player_ids - cached_ids


def merge_streak_history(history, fallback):
    if fallback is None or fallback.empty:
        return history
    if history is None or history.empty:
        return fallback
    combined = pd.concat([history, fallback], ignore_index=True)
    duplicate_keys = [
        column
        for column in ("player_id", "game_pk")
        if column in combined.columns
    ]
    if len(duplicate_keys) < 2:
        duplicate_keys = [
            column
            for column in ("player_id", "game_date")
            if column in combined.columns
        ]
    if len(duplicate_keys) == 2:
        combined = combined.drop_duplicates(
            duplicate_keys,
            keep="last",
        )
    return combined.reset_index(drop=True)


def monitored_streak_history(batter_ids, pitcher_ids, season):
    batter_ids = tuple(batter_ids)
    pitcher_ids = tuple(pitcher_ids)
    state = start_streak_history_monitor(
        batter_ids,
        pitcher_ids,
        int(season),
    )
    needs_requested_history = bool(missing_streak_player_ids(
        state["batting"],
        batter_ids,
    )) or bool(missing_streak_player_ids(
        state["pitching"],
        pitcher_ids,
    ))
    if needs_requested_history:
        state["ready"].wait(timeout=6)
    with state["lock"]:
        return state["batting"].copy(), state["pitching"].copy()


if active_view in {"Matchups", "Streaks", "Team Stats", "Player Stats"}:
    start_live_stat_monitor(season)

if needs_schedule:
    live_schedule_df = load_schedule(selected_date, data_snapshot_id)

    if live_schedule_df.empty:
        view_loading.empty()
        st.warning("No MLB games found for this date.")
        st.stop()

    if needs_weather:
        schedule_df = weather_schedule_frame(live_schedule_df)
        published_weather = load_published_weather(
            cache_version=3,
            snapshot_id=data_snapshot_id,
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
        schedule_df = merge_live_schedule_columns(schedule_df, live_schedule_df)
        if schedule_df.get(
            "weather_status",
            pd.Series(dtype=str),
        ).eq("Forecast available").any():
            weather_session_cache[weather_cache_key] = schedule_df.copy()
    else:
        schedule_df = live_schedule_df.copy()
else:
    live_schedule_df = pd.DataFrame()
    schedule_df = pd.DataFrame()

if needs_schedule and not schedule_df.empty:
    start_live_streak_monitor(live_streak_game_rows(schedule_df))

cloud_status_html = """
<div class="status-box">
    <b>Data Mode:</b> Live pitchers, stadium weather, and SQLite history<br>
    Browser refresh loads the latest probable pitchers and game-time forecasts.
    Completed-game matchup and pitcher history comes from the local database.
</div>
"""

if needs_schedule and schedule_df.empty:
    view_loading.empty()
    st.warning("No schedule data available.")
    st.stop()


schedule_df = add_game_column(schedule_df)
game_options = get_game_options(schedule_df)

needs_stats = active_view in {
    "Matchups",
    "Streaks",
    "Team Stats",
    "Player Stats",
}
needs_matchups = active_view == "Matchups"
matchup_table_options = [
    "Hitter vs Pitcher",
    "Hitter vs Throwing Hand",
    "Pitcher vs Opponent",
]
active_matchup_table = st.session_state.get(
    "active_matchup_table",
    matchup_table_options[0],
)
if active_matchup_table not in matchup_table_options:
    active_matchup_table = matchup_table_options[0]
    st.session_state.active_matchup_table = active_matchup_table

batters_df = pd.DataFrame()
pitchers_df = pd.DataFrame()
bvp_matchups = pd.DataFrame()
hand_matchups = pd.DataFrame()
pitcher_k_matchups = pd.DataFrame()
batter_options = []
pitcher_options = []

if needs_stats:
    batters_df, pitchers_df = monitored_live_stat_tables(season)
    pitchers_df = ensure_probable_pitcher_rows(pitchers_df, schedule_df)

if st.session_state.get("selected_game") not in game_options:
    st.session_state.selected_game = "All Games"

if needs_schedule:
    selected_game = game_filter_slot.selectbox(
        "Game",
        game_options,
        key="selected_game",
        label_visibility="collapsed",
    )
else:
    selected_game = "All Games"

matchup_schedule_df = filter_by_game(schedule_df, selected_game)
selected_batter = None
selected_pitcher = None
if needs_matchups:
    batter_options = scheduled_batter_options(batters_df, matchup_schedule_df)
    pitcher_options = scheduled_pitcher_options(matchup_schedule_df)

    if st.session_state.get("selected_batter") not in [None, *batter_options]:
        st.session_state.selected_batter = None
    if st.session_state.get("selected_pitcher") not in [None, *pitcher_options]:
        st.session_state.selected_pitcher = None

    selected_batter = batter_filter_slot.selectbox(
        "Batter",
        batter_options,
        index=None,
        placeholder="Batter...",
        key="selected_batter",
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
else:
    if batter_filter_slot is not None:
        batter_filter_slot.empty()
    if pitcher_filter_slot is not None:
        pitcher_filter_slot.empty()

if needs_matchups:
    build_schedule_df = filter_schedule_for_batter(
        matchup_schedule_df,
        batters_df,
        selected_batter,
    )
    build_schedule_df = filter_schedule_for_pitcher(
        build_schedule_df,
        selected_pitcher,
    )
    hitter_pool = matchup_batter_pool(
        batters_df,
        build_schedule_df,
        selected_batter=selected_batter,
        max_per_team=7 if selected_game == "All Games" else 10,
        min_pa=50,
    )
    pitcher_pool = matchup_batter_pool(
        batters_df,
        build_schedule_df,
        max_per_team=7,
        min_pa=100,
    )

    if active_matchup_table == "Hitter vs Pitcher":
        bvp_matchups = load_bvp_matchups(
            build_schedule_df,
            hitter_pool,
            season,
        )
    elif active_matchup_table == "Hitter vs Throwing Hand":
        if hand_split_preload_future is not None:
            try:
                hand_split_preload_future.result(timeout=15)
            except Exception:
                pass
        hand_matchups = load_hand_matchups(
            build_schedule_df,
            hitter_pool,
            season,
        )
    elif active_matchup_table == "Pitcher vs Opponent":
        pitcher_k_matchups = load_pitcher_matchups(
            build_schedule_df,
            pitcher_pool,
            pitchers_df,
        )

    injury_report = monitored_injury_report(
        sorted(schedule_team_ids(build_schedule_df)),
        selected_date,
    )
    if not bvp_matchups.empty:
        bvp_matchups = add_injury_columns(
            bvp_matchups,
            "batter_id",
            injury_report,
        )
    if not hand_matchups.empty:
        hand_matchups = add_injury_columns(
            hand_matchups,
            "batter_id",
            injury_report,
        )
    if not pitcher_k_matchups.empty:
        pitcher_k_matchups = add_injury_columns(
            pitcher_k_matchups,
            "pitcher_id",
            injury_report,
        )

filtered_schedule_df = filter_by_game(schedule_df, selected_game)
filtered_bvp_matchups = filter_by_players(
    bvp_matchups,
    selected_batter,
    selected_pitcher,
)
filtered_hand_matchups = filter_by_players(
    hand_matchups,
    selected_batter,
    selected_pitcher,
)
filtered_pitcher_k_matchups = filter_by_players(
    pitcher_k_matchups,
    selected_batter,
    selected_pitcher,
)


if active_view == "Games":
    render_games_tab(
        schedule_df,
        filtered_schedule_df,
        selected_game,
        selected_date,
    )

elif active_view == "Matchups":
    active_matchup_table = render_box_tabs(
        "matchup-table-tabs",
        matchup_table_options,
        "active_matchup_table",
        matchup_table_options[0],
    )

    if active_matchup_table == "Hitter vs Pitcher":
        render_bvp_table_fragment(
            filtered_bvp_matchups,
            selected_batter=selected_batter,
            selected_pitcher=selected_pitcher,
        )
    elif active_matchup_table == "Hitter vs Throwing Hand":
        render_hand_table_fragment(
            filtered_hand_matchups,
            selected_batter=selected_batter,
            selected_pitcher=selected_pitcher,
        )
    elif active_matchup_table == "Pitcher vs Opponent":
        render_pitcher_table_fragment(
            filtered_pitcher_k_matchups,
            selected_pitcher=selected_pitcher,
        )

elif active_view == "Streaks":
    render_streaks_tab(
        filtered_schedule_df,
        filtered_bvp_matchups,
        filtered_pitcher_k_matchups,
        batters_df,
        pitchers_df,
        selected_game,
        selected_date,
    )

elif active_view == "Team Stats":
    render_team_stats_tab(batters_df, pitchers_df)

elif active_view == "Player Stats":
    render_player_stats_tab(batters_df, pitchers_df, season)

elif active_view == "Details":
    how_tab, glossary_tab = st.tabs(["How It Works", "Glossary"])

    with how_tab:
        st.markdown(
            """
            ### How the app works

            - **Games:** Use today's schedule to check live scores, weather, probable pitchers, and click a game for the box score.
            - **Matchups:** Compare hitter and pitcher matchups, then click a player name to open the related game log.
            - **Streaks:** See the top active hitting and pitching streaks with live game updates.
            - **Player Stats:** Sort season player leaderboards and use the headshot/team columns to scan players quickly.
            - **Team Stats:** Rank team batting and pitching totals, or switch to per-game views above each table.
            - **Details:** Check app notes here and use the Glossary tab for stat definitions.
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

    with glossary_tab:
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
            | **SO/K** | Strikeouts |
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

view_loading.empty()
