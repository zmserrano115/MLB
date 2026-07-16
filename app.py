from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from html import escape
import json
import os
from pathlib import Path
from threading import Event, Lock
import time
from urllib.parse import urlencode

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.mlb_schedule import get_daily_schedule
from src import weather as weather_service
from src.advanced_bvp_data import (
    batch_batter_pitch_type_profiles,
    batch_pitcher_pitch_type_profiles,
)
from src.background import log_background_exception, start_daemon_thread
from src.stat_data import (
    get_batter_pitch_type_stats,
    get_batter_stats,
    get_pitcher_pitch_type_stats,
    get_pitcher_stats,
    get_batter_vs_pitcher_game_log,
    get_pitcher_vs_team_game_log,
)
from src import stat_data as stat_data_service
from src.live_game import (
    calculate_team_record_vs_pitcher,
    calculate_team_win_streak,
    get_active_team_rosters,
    get_game_boxscore,
    get_game_results,
    get_live_game_feed,
    get_people_career_game_logs,
    get_people_game_logs as fetch_people_game_logs,
    get_player_game_log,
    get_player_profile,
    get_season_team_results,
    is_final_state,
    player_headshot_url,
)
from src.matchups import (
    build_batter_vs_pitcher_matchups,
    build_batter_vs_hand_matchups,
    build_pitcher_k_matchups,
    filter_prebuilt_matchup_rows,
)
from src.injuries import add_injury_columns, fetch_injury_report
from src.recent_form import build_recent_bar_chart_html
from src.scoring import parse_baseball_ip
from src import database
from src.time_utils import current_app_date
from src.player_rankings import rank_hitters_by_wrc_plus
from src.ui.bvp_research_page import (
    BULLPEN_TAB_LABEL,
    PAGE_TAB_LABEL as HVP_PAGE_TAB_LABEL,
    render_bvp_research_page,
)


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

TEAM_PRIMARY_COLOR_BY_ID = {
    108: "#BA0021",
    109: "#A71930",
    110: "#DF4601",
    111: "#BD3039",
    112: "#0E3386",
    113: "#C6011F",
    114: "#E31937",
    115: "#33006F",
    116: "#0C2340",
    117: "#002D62",
    118: "#004687",
    119: "#005A9C",
    120: "#AB0003",
    121: "#002D72",
    133: "#003831",
    134: "#FDB827",
    135: "#2F241D",
    136: "#0C2C56",
    137: "#FD5A1E",
    138: "#C41E3A",
    139: "#092C5C",
    140: "#003278",
    141: "#134A8E",
    142: "#002B5C",
    143: "#E81828",
    144: "#CE1141",
    145: "#27251F",
    146: "#00A3E0",
    147: "#0C2340",
    158: "#12284B",
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

    html,
    body,
    .stApp {
        background: var(--bg) !important;
        font-family: var(--font-body) !important;
    }

    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    [data-testid="stMainBlockContainer"] {
        background: var(--bg);
        color: var(--text);
    }

    iframe {
        background: transparent !important;
    }

    [data-testid="stElementContainer"],
    [data-testid="stMarkdownContainer"],
    [data-testid="stVerticalBlock"],
    [data-testid="stHorizontalBlock"] {
        background: transparent;
    }

    div[data-testid="stSpinner"],
    [data-testid*="Skeleton"],
    [data-testid*="skeleton"] {
        background: var(--bg) !important;
    }

    .sr-only {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
    }

    .block-container {
        padding-top: 0.95rem;
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

    header[data-testid="stHeader"] [data-testid="stToolbar"],
    header[data-testid="stHeader"] [data-testid="stHeaderActionElements"],
    header[data-testid="stHeader"] [data-testid="stMainMenu"],
    header[data-testid="stHeader"] a[href*="github.com"],
    [data-testid="stDecoration"] {
        display: none !important;
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

    [class*="st-key-app_header_nav_mount"] {
        position: fixed;
        top: 8px;
        left: 318px;
        right: 136px;
        z-index: 999998;
        display: flex;
        align-items: center;
        height: 42px !important;
        min-height: 42px !important;
        width: auto !important;
        max-width: none !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: visible !important;
    }

    [class*="st-key-app_header_nav_mount"] [data-testid="stVerticalBlock"] {
        width: 100%;
        gap: 0 !important;
    }

    [class*="st-key-app_header_nav_mount"] [data-testid="stHorizontalBlock"] {
        align-items: center;
        display: flex !important;
        flex-wrap: nowrap !important;
        justify-content: flex-start;
        gap: 6px;
        height: 42px;
        overflow-x: auto;
        overflow-y: hidden;
        scrollbar-width: none;
        -webkit-overflow-scrolling: touch;
    }

    [class*="st-key-app_header_nav_mount"] [data-testid="stHorizontalBlock"]::-webkit-scrollbar {
        display: none;
    }

    [class*="st-key-app_header_nav_mount"] [data-testid="stColumn"] {
        display: flex;
        align-items: center;
        flex: 0 0 auto !important;
        width: auto !important;
        min-width: 0;
    }

    [class*="st-key-app_header_nav_mount"] [data-testid="stButton"] {
        width: auto;
        margin: 0 !important;
    }

    [class*="st-key-app_header_nav_mount"] .stButton > button {
        min-height: 42px;
        width: auto;
        padding: 0 14px;
        border: 1px solid transparent;
        border-bottom: 2px solid transparent;
        background: transparent;
        color: rgba(255, 255, 255, 0.76);
        font-family: var(--font-display) !important;
        font-size: 16px;
        font-weight: 400;
        letter-spacing: 0.045em;
        line-height: 1;
        text-transform: uppercase;
        white-space: nowrap;
        box-shadow: none;
    }

    [class*="st-key-app_header_nav_mount"] .stButton > button [data-testid="stMarkdownContainer"],
    [class*="st-key-app_header_nav_mount"] .stButton > button [data-testid="stMarkdownContainer"] p,
    [class*="st-key-app_header_nav_mount"] .stButton > button p,
    [class*="st-key-app_header_nav_mount"] .stButton > button span {
        font-family: var(--font-display) !important;
        font-size: 18px !important;
        font-weight: 400 !important;
        letter-spacing: 0.045em !important;
        line-height: 1 !important;
        margin: 0 !important;
        text-transform: uppercase;
        white-space: nowrap;
    }

    [class*="st-key-app_header_nav_mount"] .stButton > button:hover,
    [class*="st-key-app_header_nav_mount"] .stButton > button:focus-visible {
        border-color: rgba(255, 255, 255, 0.14);
        background: rgba(255, 255, 255, 0.08);
        color: #ffffff;
        outline: none;
        box-shadow: none;
    }

    [class*="st-key-app_nav_tab_active_"] .stButton > button {
        border-color: rgba(255, 255, 255, 0.18);
        border-bottom-color: #ffffff;
        background: rgba(255, 255, 255, 0.11);
        color: #ffffff;
    }

    .app-header-nav {
        position: fixed;
        top: 0;
        left: 315px;
        right: 155px;
        z-index: 999998;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 4px;
        height: 58px;
        overflow-x: auto;
        scrollbar-width: none;
        pointer-events: auto;
    }

    .app-header-nav::-webkit-scrollbar {
        display: none;
    }

    .app-header-nav a {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 36px;
        padding: 0 12px;
        border: 1px solid transparent;
        border-bottom: 2px solid transparent;
        color: rgba(255, 255, 255, 0.74) !important;
        font-family: var(--font-display) !important;
        font-size: 15px;
        line-height: 1;
        letter-spacing: 0.045em;
        text-decoration: none !important;
        text-transform: uppercase;
        white-space: nowrap;
    }

    .app-header-nav a:hover,
    .app-header-nav a:focus-visible {
        background: rgba(255, 255, 255, 0.08);
        border-color: rgba(255, 255, 255, 0.12);
        color: #ffffff !important;
        outline: none;
    }

    .app-header-nav a.active {
        background: rgba(255, 255, 255, 0.1);
        border-color: rgba(255, 255, 255, 0.16);
        border-bottom-color: #ffffff;
        color: #ffffff !important;
    }

    .section-shell {
        margin: 4px 0 2px 0;
        padding: 0;
        border: 0;
        background: transparent;
    }

    .aligned-page-title {
        margin: 0 0 0;
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

    .section-label {
        display: none;
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

    [data-baseweb="popover"] {
        z-index: 9990 !important;
        max-width: calc(100vw - 16px) !important;
    }

    .stSegmentedControl [data-baseweb="button-group"] {
        gap: 0;
        border-bottom: 1px solid var(--line);
        margin-bottom: 8px;
    }

    .st-key-active_view .stRadio [role="radiogroup"] {
        display: grid !important;
        grid-template-columns: repeat(8, minmax(0, 1fr));
        width: 100%;
    }

    [class*="st-key-box_tabs_"] .stRadio [role="radiogroup"] input,
    [class*="st-key-box_tabs_"] .stRadio [role="radiogroup"] svg {
        display: none !important;
    }

    [class*="st-key-box_tabs_"] .stRadio label[data-baseweb="radio"] > div:first-child,
    [class*="st-key-box_tabs_"] .stRadio [role="radiogroup"] label > div:first-child:not([data-testid="stMarkdownContainer"]) {
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

    .batting-order-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        margin: 10px 0 12px;
    }

    .batting-order-card {
        border: 1px solid var(--line);
        background: #ffffff;
        overflow: hidden;
    }

    .batting-order-title {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 9px 11px;
        border-bottom: 1px solid #d8dee6;
        color: #10243b;
        font-size: 13px;
        font-weight: 900;
    }

    .batting-order-title span {
        color: #718096;
        font-size: 10px;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    .batting-order-team-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .batting-order-team {
        min-width: 0;
        border-right: 1px solid #edf0f4;
    }

    .batting-order-team:last-child {
        border-right: 0;
    }

    .batting-order-team-head {
        display: flex;
        align-items: center;
        gap: 7px;
        padding: 8px 10px;
        border-bottom: 1px solid #edf0f4;
        color: #10243b;
        font-size: 12px;
        font-weight: 900;
    }

    .batting-order-team-head img {
        width: 24px;
        height: 24px;
        object-fit: contain;
    }

    .batting-order-row {
        display: grid;
        grid-template-columns: 24px 30px minmax(0, 1fr) 28px;
        align-items: center;
        gap: 7px;
        min-height: 34px;
        padding: 5px 9px;
        border-bottom: 1px solid #f0f3f6;
    }

    .batting-order-row:last-child {
        border-bottom: 0;
    }

    .batting-order-slot {
        color: #87919c;
        font-size: 11px;
        font-weight: 900;
        text-align: center;
        font-variant-numeric: tabular-nums;
    }

    .batting-order-row img {
        width: 26px;
        height: 26px;
        border: 1px solid #d8dee6;
        border-radius: 50%;
        background: #f3f5f7;
        object-fit: cover;
    }

    .batting-order-name {
        overflow: hidden;
        color: #10243b;
        font-size: 12px;
        font-weight: 800;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .batting-order-pos {
        color: #718096;
        font-size: 10px;
        font-weight: 900;
        text-align: right;
    }

    .live-lineup-section {
        margin-top: 14px;
    }

    .live-lineup-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
    }

    .live-lineup-card {
        min-width: 0;
        border: 1px solid var(--line);
        background: #ffffff;
        overflow: hidden;
    }

    .live-lineup-title {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 12px;
        border-bottom: 1px solid #d8dee6;
        color: #10243b;
        font-size: 14px;
        font-weight: 900;
    }

    .live-lineup-title img {
        width: 25px;
        height: 25px;
        object-fit: contain;
    }

    .live-lineup-title span {
        margin-left: auto;
        color: #718096;
        font-size: 10px;
        font-weight: 850;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }

    .live-lineup-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
    }

    .live-lineup-table th,
    .live-lineup-table td {
        padding: 7px 8px;
        border-bottom: 1px solid #edf0f4;
        text-align: right;
        white-space: nowrap;
    }

    .live-lineup-table th {
        color: #617083;
        font-size: 10px;
        font-weight: 900;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }

    .live-lineup-table td {
        color: #10243b;
        font-weight: 750;
        font-variant-numeric: tabular-nums;
    }

    .live-lineup-table tr:last-child td {
        border-bottom: 0;
    }

    .live-lineup-table .align-left {
        text-align: left;
    }

    .live-lineup-player {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        min-width: 0;
    }

    .live-lineup-player img {
        width: 24px;
        height: 24px;
        border: 1px solid #d8dee6;
        border-radius: 50%;
        background: #f3f5f7;
        object-fit: cover;
    }

    .live-lineup-stat-muted {
        color: #7b8794 !important;
    }

    [data-testid="stDialog"] [role="dialog"] {
        width: min(1180px, calc(100vw - 32px)) !important;
        max-width: 1180px !important;
        max-height: calc(100dvh - 80px) !important;
        overflow-y: auto !important;
        border: 1px solid #cbd5e1;
        border-radius: 0;
        background: #f8fafc;
    }

    [data-testid="stDialog"] [role="dialog"] > div {
        border-radius: 0;
    }

    [class*="dialog_close"] {
        display: flex;
        justify-content: flex-end;
        margin: -8px 0 -6px;
    }

    [class*="dialog_close"] .stButton {
        width: auto;
    }

    [class*="dialog_close"] .stButton > button {
        min-width: 36px;
        min-height: 34px;
        padding: 0 10px;
        border: 1px solid #cbd5e1;
        background: #ffffff;
        color: #31445b;
        font-size: 22px;
        line-height: 1;
    }

    .update-notice {
        padding: 4px 2px 0;
        color: #10243b;
    }

    .update-notice-kicker {
        margin-bottom: 8px;
        color: #63748a;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .update-notice-title {
        margin: 0 0 8px;
        color: #06172b;
        font-family: var(--font-display);
        font-size: 36px;
        letter-spacing: 0.03em;
        line-height: 1;
        text-transform: uppercase;
    }

    .update-notice-copy {
        max-width: 780px;
        margin: 0 0 16px;
        color: #405066;
        font-size: 14px;
        line-height: 1.45;
    }

    .update-notice-list {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        margin: 0 0 18px;
    }

    .update-notice-item {
        min-height: 86px;
        padding: 12px;
        border: 1px solid #d8dee6;
        border-left: 4px solid #245f96;
        background: #ffffff;
    }

    .update-notice-item strong,
    .update-notice-item span {
        display: block;
    }

    .update-notice-item strong {
        margin-bottom: 5px;
        color: #10243b;
        font-size: 14px;
        font-weight: 900;
    }

    .update-notice-item span {
        color: #526171;
        font-size: 12px;
        line-height: 1.35;
    }

    .st-key-dismiss_update_1_2 .stButton > button {
        min-height: 40px;
        border: 1px solid #173f67;
        background: #173f67;
        color: #ffffff;
        font-weight: 800;
    }

    @media (max-width: 760px) {
        .update-notice-list {
            grid-template-columns: 1fr;
        }
    }

    .live-game-scorebug {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
        align-items: center;
        gap: 18px;
        padding: 18px;
        border: 1px solid var(--line);
        background: #ffffff;
    }

    .live-game-team {
        display: flex;
        align-items: center;
        gap: 12px;
        min-width: 0;
        color: #0b2a4a;
    }

    .live-game-team:last-child {
        justify-content: flex-end;
        text-align: right;
    }

    .live-game-team img {
        width: 54px;
        height: 54px;
        object-fit: contain;
    }

    .live-game-team span {
        overflow: hidden;
        font-size: 16px;
        font-weight: 800;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .live-game-team strong {
        min-width: 52px;
        color: #06172b;
        font-size: 38px;
        line-height: 1;
        font-variant-numeric: tabular-nums;
    }

    .live-score-wrap {
        position: relative;
        display: inline-flex;
        align-items: center;
        gap: 4px;
        overflow: visible;
    }

    .live-score {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 52px;
        min-height: 48px;
        padding: 3px 6px;
    }

    .live-score.score-changed {
        animation: liveScoreChanged 2.8s cubic-bezier(0.18, 0.82, 0.24, 1) both;
    }

    .live-score-wrap .live-score-delta {
        position: absolute;
        left: 50%;
        bottom: calc(100% - 2px);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: auto;
        padding: 0;
        border: 0;
        background: transparent;
        color: #00b86b;
        font-size: 14px;
        font-weight: 900;
        line-height: 1;
        letter-spacing: 0.02em;
        text-shadow: 0 1px 0 #ffffff, 0 0 10px rgba(0, 184, 107, 0.24);
        overflow: visible;
        pointer-events: none;
        animation: liveScoreDelta 2.8s cubic-bezier(0.18, 0.82, 0.24, 1) both;
    }

    .live-game-team:last-child .live-score-delta {
        left: 50%;
        right: auto;
    }

    @keyframes liveScoreChanged {
        0% {
            color: #00a86b;
            text-shadow: 0 1px 0 #ffffff, 0 0 14px rgba(0, 184, 107, 0.32);
            transform: translateY(4px) scale(0.96);
        }
        18%, 62% {
            color: #00c875;
            text-shadow: 0 1px 0 #ffffff, 0 0 18px rgba(0, 184, 107, 0.38);
            transform: translateY(0) scale(1.04);
        }
        100% {
            color: #06172b;
            text-shadow: none;
            transform: scale(1);
        }
    }

    @keyframes liveScoreDelta {
        0% {
            opacity: 0;
            transform: translate(-50%, 12px) scale(0.78);
        }
        16% {
            opacity: 1;
            transform: translate(-50%, 0) scale(1.02);
        }
        70% {
            opacity: 1;
            transform: translate(-50%, -22px) scale(1);
        }
        100% {
            opacity: 0;
            transform: translate(-50%, -42px) scale(0.92);
        }
    }

    .live-game-status {
        min-width: 132px;
        color: #526171;
        text-align: center;
    }

    .live-game-status strong {
        display: block;
        color: #06172b;
        font-family: var(--font-display);
        font-size: 22px;
        font-weight: 400;
        letter-spacing: 0.045em;
    }

    .home-run-notice {
        position: relative;
        isolation: isolate;
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 82px;
        margin: 10px 0 12px;
        padding: 12px 24px;
        border: 1px solid #245f96;
        border-top-color: #f28a27;
        border-bottom-color: #f28a27;
        background:
            linear-gradient(90deg, #07192d 0%, #0b2a4a 48%, #07192d 100%);
        color: #ffffff;
        font-family: var(--font-display);
        font-size: 30px;
        letter-spacing: 0.12em;
        text-align: center;
        text-transform: uppercase;
        overflow: hidden;
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.08),
            0 5px 14px rgba(7, 25, 45, 0.16);
    }

    .home-run-notice.animate {
        animation: homeRunNotice 6.8s ease-out both;
    }

    .home-run-notice::before {
        content: "";
        position: absolute;
        z-index: 0;
        inset: 0;
        background:
            radial-gradient(ellipse at 50% 110%, rgba(255, 180, 46, 0.42) 0%, rgba(234, 80, 15, 0.18) 38%, transparent 70%);
        opacity: 0.72;
    }

    .home-run-notice.animate::before {
        opacity: 0;
        animation: homeRunGlow 6.8s ease-out both;
    }

    .home-run-notice::after {
        content: "";
        position: absolute;
        z-index: 1;
        inset: 0;
        background:
            linear-gradient(90deg, transparent 0 8%, rgba(255, 139, 31, 0.82) 28%, transparent 62%) 0 18% / 100% 1px no-repeat,
            linear-gradient(90deg, transparent 0 28%, rgba(255, 213, 119, 0.7) 48%, transparent 78%) 0 34% / 100% 1px no-repeat,
            linear-gradient(90deg, transparent 0 46%, rgba(255, 112, 22, 0.74) 65%, transparent 92%) 0 68% / 100% 1px no-repeat,
            linear-gradient(90deg, transparent 0 12%, rgba(255, 177, 63, 0.66) 34%, transparent 70%) 0 84% / 100% 1px no-repeat;
        opacity: 0.55;
    }

    .home-run-notice.animate::after {
        opacity: 0;
        animation: homeRunStreaks 6.8s ease-out both;
    }

    .home-run-notice strong {
        position: relative;
        z-index: 2;
        display: inline-flex;
        align-items: center;
        color: #ffffff;
        font-size: inherit;
        font-weight: 400;
        line-height: 1;
        letter-spacing: inherit;
        text-shadow:
            0 2px 0 #07192d,
            0 0 16px rgba(255, 126, 28, 0.46);
    }

    .home-run-notice.animate strong {
        animation: homeRunTextSlide 6.8s cubic-bezier(0.16, 0.82, 0.23, 1) both;
    }

    .home-run-fire {
        position: absolute;
        z-index: 1;
        left: -2%;
        right: -2%;
        bottom: -6px;
        height: 68px;
        pointer-events: none;
        filter:
            saturate(1.15)
            drop-shadow(0 -5px 9px rgba(242, 98, 20, 0.48));
        transform-origin: 50% 100%;
    }

    .home-run-notice.animate .home-run-fire {
        animation: homeRunFire 6.8s ease-out both;
    }

    .home-run-fire svg {
        display: block;
        width: 100%;
        height: 100%;
    }

    .home-run-fire .flame-back {
        fill: #c74312;
        opacity: 0.78;
        transform-origin: 50% 100%;
        animation: homeRunFlameLick 1.35s ease-in-out infinite alternate;
    }

    .home-run-fire .flame-mid {
        fill: #f47719;
        opacity: 0.9;
        transform-origin: 50% 100%;
        animation: homeRunFlameLick 1.05s ease-in-out infinite alternate-reverse;
    }

    .home-run-fire .flame-core {
        fill: #ffd05a;
        opacity: 0.72;
        transform-origin: 50% 100%;
        animation: homeRunFlameLick 0.9s ease-in-out infinite alternate;
    }

    .home-run-notice strong::before,
    .home-run-notice strong::after {
        content: "";
        width: clamp(38px, 8vw, 110px);
        height: 1px;
        margin: 0 18px;
        background: linear-gradient(90deg, transparent, #f39a43);
        box-shadow: 0 4px 0 rgba(255, 255, 255, 0.35);
    }

    .home-run-notice strong::after {
        background: linear-gradient(90deg, #f39a43, transparent);
    }

    @keyframes homeRunNotice {
        0% {
            opacity: 0;
            transform: scaleX(0.8);
        }
        10%, 86% {
            opacity: 1;
            transform: scaleX(1);
        }
        100% {
            opacity: 0;
            transform: scaleX(1.02);
        }
    }

    @keyframes homeRunTextSlide {
        0%, 8% {
            opacity: 0;
            transform: translateX(-42%) skewX(-8deg);
        }
        24%, 82% {
            opacity: 1;
            transform: translateX(0) skewX(-4deg);
        }
        100% {
            opacity: 0;
            transform: translateX(28%) skewX(-4deg);
        }
    }

    @keyframes homeRunFire {
        0% {
            opacity: 0;
            transform: translateY(28px) scaleY(0.45);
        }
        18%, 70% {
            opacity: 1;
            transform: translateY(0) scaleY(1);
        }
        86% {
            opacity: 0.78;
            transform: translateY(4px) scaleY(0.86);
        }
        100% {
            opacity: 0;
            transform: translateY(18px) scaleY(0.5);
        }
    }

    @keyframes homeRunGlow {
        0%, 100% { opacity: 0; }
        18%, 72% { opacity: 1; }
    }

    @keyframes homeRunStreaks {
        0%, 10% {
            opacity: 0;
            transform: translateX(-18%);
        }
        22%, 70% {
            opacity: 0.76;
            transform: translateX(0);
        }
        100% {
            opacity: 0;
        transform: translateX(18%);
        }
    }

    @keyframes homeRunFlameLick {
        0% { transform: translateY(4px) scaleY(0.92); }
        100% { transform: translateY(-4px) scaleY(1.08); }
    }

    .live-game-section {
        margin-top: 0;
        border-top: 1px solid var(--line);
        padding-top: 8px;
    }

    .live-game-section-heading {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 0;
    }

    .live-game-section-title {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 7px 10px;
        min-width: 0;
    }

    .live-game-section-title span,
    .live-game-section-title strong,
    .live-game-section-title em {
        display: inline-flex;
        align-items: center;
    }

    .live-game-section-title span {
        color: #718096;
        font-size: 10px;
        font-weight: 900;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .live-game-section-title strong {
        overflow: hidden;
        color: #06172b;
        font-size: 23px;
        line-height: 1;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .live-game-section-title em {
        min-height: 24px;
        padding: 2px 8px;
        border: 1px solid #cbd5e1;
        background: #f8fafc;
        color: #245f96;
        font-size: 12px;
        font-style: normal;
        font-weight: 900;
        letter-spacing: 0.02em;
        text-transform: uppercase;
    }

    [class*="st-key-live_game_compact_header_"] {
        margin-top: 0;
        padding-top: 6px;
        border-top: 1px solid var(--line);
    }

    [class*="st-key-live_game_compact_header_"] [data-testid="column"] {
        display: flex;
        align-items: center;
    }

    [class*="st-key-live_game_compact_header_"] [data-testid="stButton"] {
        margin: 0;
    }

    [class*="st-key-live_game_compact_header_"] [class*="st-key-app_back_"] [data-testid="stButton"] {
        width: 50px;
    }

    [class*="st-key-live_game_compact_header_"] [class*="st-key-app_back_"] [data-testid="stButton"] button {
        min-height: 42px;
        border-color: #cbd5e1 !important;
        background: #ffffff !important;
        color: #06172b !important;
        box-shadow: none !important;
        font-size: 17px !important;
        font-weight: 900 !important;
    }

    .live-game-section.compact {
        margin: 0;
        padding: 0;
        border: 0;
    }

    [class*="st-key-live_game_tab_"] [data-testid="stButton"] {
        width: 100%;
    }

    [class*="st-key-live_game_tab_"] .stButton > button {
        min-height: 44px;
        width: 100%;
        padding: 0 16px;
        border: 1px solid #cbd5e1;
        background: #ffffff;
        color: #06172b;
        font-family: var(--font-display) !important;
        font-size: 16px;
        font-weight: 400;
        letter-spacing: 0.045em;
        text-transform: uppercase;
        box-shadow: none;
    }

    [class*="st-key-live_game_tab_"] .stButton > button:hover,
    [class*="st-key-live_game_tab_"] .stButton > button:focus-visible {
        background: #edf3f8;
        border-color: #b8c6d6;
        color: #06172b;
        box-shadow: none;
    }

    [class*="st-key-live_game_tab_active_"] .stButton > button {
        background: #f3f7fb;
        border-bottom: 3px solid #245f96;
        color: #06172b;
    }

    .live-game-header-tabs {
        display: inline-flex;
        align-items: center;
        flex: 0 0 auto;
        border: 1px solid #cbd5e1;
        background: #ffffff;
    }

    .live-game-header-tab {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 92px;
        min-height: 38px;
        padding: 9px 15px;
        border-right: 1px solid #d8dee6;
        color: #06172b !important;
        font-family: var(--font-display);
        font-size: 15px;
        letter-spacing: 0.035em;
        text-decoration: none !important;
        text-transform: uppercase;
    }

    .live-game-header-tab:last-child {
        border-right: 0;
    }

    .live-game-header-tab.active {
        background: #f3f7fb;
        box-shadow: inset 0 -2px 0 #245f96;
        color: #06172b !important;
    }

    .live-game-header-tab:hover,
    .live-game-header-tab:focus-visible {
        background: #edf3f8;
        color: #06172b !important;
        text-decoration: none !important;
    }

    .live-game-layout {
        display: grid;
        grid-template-columns: minmax(0, 512px) minmax(360px, 1fr);
        grid-template-areas: "main side";
        gap: 12px;
        margin: 12px 0;
        align-content: start;
        align-items: start;
    }

    .live-game-refresh-shell {
        min-height: 700px;
        background: var(--bg);
    }

    [class*="st-key-live_game_live_shell_"] {
        min-height: 700px;
        background: var(--bg);
    }

    .live-main-area {
        grid-area: main;
        display: grid;
        grid-template-columns: 270px 230px;
        grid-template-areas:
            "atplate atplate"
            "field zone";
        gap: 12px;
        align-content: start;
        align-items: start;
        min-width: 0;
    }

    .live-field-area {
        grid-area: field;
    }

    .live-zone-area {
        grid-area: zone;
    }

    .live-side-area {
        grid-area: side;
        display: grid;
        grid-template-rows: auto minmax(0, 1fr);
        gap: 12px;
        min-height: 0;
    }

    .live-at-plate-area {
        grid-area: atplate;
        min-height: 0;
    }

    .live-situation-panel,
    .player-profile-hero,
    .player-card,
    .home-placeholder,
    .matchup-rank-strip {
        border: 1px solid var(--line);
        background: #ffffff;
    }

    .live-situation-panel {
        min-height: 146px;
        padding: 12px;
    }

    .strike-zone-card {
        display: flex;
        min-height: 100%;
        flex-direction: column;
    }

    .strike-zone-topline {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 6px;
    }

    .strike-zone-topline strong {
        color: #10243b;
        font-size: 10px;
    }

    .strike-zone-topline span,
    .strike-zone-meta span {
        color: #718096;
        font-size: 8px;
        font-weight: 900;
        letter-spacing: 0.07em;
        text-transform: uppercase;
    }

    .strike-zone-svg {
        display: block;
        width: 100%;
        aspect-ratio: 170 / 190;
        border: 1px solid #d8dee6;
        background: #fbfcfe;
    }

    .strike-zone-box {
        fill: rgba(232, 240, 247, 0.55);
        stroke: #173f67;
        stroke-width: 1.4;
        vector-effect: non-scaling-stroke;
    }

    .strike-zone-grid {
        stroke: #cfd8e3;
        stroke-width: 0.8;
        vector-effect: non-scaling-stroke;
    }

    .strike-zone-plate {
        fill: #ffffff;
        stroke: #9aa8b8;
        stroke-width: 1.2;
        vector-effect: non-scaling-stroke;
    }

    .strike-zone-pitch {
        stroke: #ffffff;
        stroke-width: 1.5;
        vector-effect: non-scaling-stroke;
    }

    .strike-zone-pitch-marker {
        transform-box: view-box;
        transform-origin: center;
    }

    .strike-zone-pitch-marker.animate {
        animation: pitchArrive 0.42s cubic-bezier(0.2, 0.86, 0.2, 1) both;
        animation-delay: var(--pitch-delay, 0s);
    }

    .strike-zone-pitch.ball {
        fill: #2f9967;
    }

    .strike-zone-pitch.strike {
        fill: #b42318;
    }

    .strike-zone-pitch.in-play {
        fill: #245f96;
    }

    .strike-zone-pitch.foul {
        fill: #6f7884;
    }

    .strike-zone-pitch.unknown {
        fill: #6b7888;
    }

    .strike-zone-pitch.latest {
        stroke: #06172b;
        stroke-width: 2.2;
    }

    .strike-zone-count-label {
        fill: #ffffff;
        font-size: 7px;
        font-weight: 900;
        text-anchor: middle;
        dominant-baseline: central;
        pointer-events: none;
    }

    .strike-zone-meta {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        align-items: baseline;
        gap: 8px;
        min-height: 24px;
        padding-top: 6px;
        color: #31445b;
        font-size: 9px;
    }

    .strike-zone-meta strong {
        color: #10243b;
    }

    .strike-zone-meta-detail {
        overflow: hidden;
        padding-left: 4px;
        color: #526171;
        font-size: 9px;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    @keyframes pitchArrive {
        0% {
            opacity: 0;
            transform: translate(var(--pitch-from-x, 0), -24px) scale(0.72);
        }
        68% {
            opacity: 1;
        }
        100% {
            opacity: 1;
            transform: translate(0, 0) scale(1);
        }
    }

    .live-count-board {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 12px;
        margin-top: 10px;
        padding: 8px 10px;
        border: 1px solid #d8dee6;
        background: #f8fafc;
    }

    .count-dot-group {
        display: inline-flex;
        align-items: center;
        gap: 5px;
    }

    .count-dot-label {
        margin-right: 2px;
        color: #6c7886;
        font-size: 9px;
        font-weight: 900;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }

    .count-dot {
        width: 11px;
        height: 11px;
        border: 1.5px solid #aab4c0;
        border-radius: 50%;
        background: #ffffff;
    }

    .count-dot.ball.active {
        border-color: #17603e;
        background: #2f9967;
        box-shadow: 0 0 0 2px #dcefe6;
    }

    .count-dot.strike.active,
    .count-dot.out.active {
        border-color: #173f67;
        background: #173f67;
    }

    .foul-count {
        margin-left: auto;
        color: #31445b;
        font-size: 10px;
        font-weight: 800;
        letter-spacing: 0.03em;
    }

    .base-diamond {
        position: relative;
        width: 112px;
        height: 92px;
        margin: 10px auto 0;
    }

    .base-diamond::before {
        content: "";
        position: absolute;
        left: 29px;
        top: 16px;
        width: 54px;
        height: 54px;
        border: 1px solid #cbd5e1;
        background: transparent;
        transform: rotate(45deg);
    }

    .base-diamond span {
        position: absolute;
        width: 20px;
        height: 20px;
        border: 2px solid #94a3b8;
        background: #ffffff;
        transform: rotate(45deg);
    }

    .base-diamond .first { left: 75px; top: 43px; }
    .base-diamond .second { left: 46px; top: 14px; }
    .base-diamond .third { left: 17px; top: 43px; }
    .base-diamond span.occupied {
        border-color: #173f67;
        background: #e8f0f7;
        z-index: 1;
    }

    .base-diamond .base-runner-headshot {
        position: absolute;
        left: 50%;
        top: 50%;
        width: 30px;
        height: 30px;
        border: 2px solid #ffffff;
        border-radius: 50%;
        background: #e8f0f7;
        object-fit: cover;
        transform: translate(-50%, -50%) rotate(-45deg);
        box-shadow: 0 0 0 1px #173f67;
    }

    .base-runner-list {
        display: grid;
        gap: 3px;
        margin-top: 6px;
        color: #596777;
        font-size: 9px;
        text-align: center;
    }

    .base-runner-list strong {
        color: #173f67;
        font-weight: 800;
    }

    .live-field-card {
        display: flex;
        min-height: 100%;
        flex-direction: column;
    }

    .live-field-topline {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 6px;
    }

    .live-field-topline span,
    .abs-tracker-title span {
        color: #718096;
        font-size: 8px;
        font-weight: 900;
        letter-spacing: 0.07em;
        text-transform: uppercase;
    }

    .live-field-topline strong {
        overflow: hidden;
        color: #10243b;
        font-size: 10px;
        text-align: right;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .live-field-svg {
        display: block;
        width: 100%;
        aspect-ratio: 250 / 225;
        border: 1px solid #d7dfe8;
        background: #f5f8fb;
    }

    .field-shape {
        fill: #dce8d3;
        stroke: #62758b;
        stroke-width: 1.4;
    }

    .field-grass {
        fill: #dbe8d0;
    }

    .field-stripe {
        fill: #cddfc2;
        opacity: 0.72;
    }

    .field-foul-line {
        fill: none;
        stroke: #7f8fa2;
        stroke-width: 0.9;
        stroke-opacity: 0.72;
    }

    .field-infield {
        fill: #e8bf66;
        fill-opacity: 0.58;
        stroke: none;
    }

    .field-base {
        fill: #ffffff;
        stroke: #ffffff;
        stroke-width: 1.8;
        filter: drop-shadow(0 1px 1px rgba(15, 31, 48, 0.18));
    }

    .field-base.occupied {
        fill: #dcebf7;
        stroke: #245f96;
        stroke-width: 1.8;
    }

    .field-home-plate {
        fill: #ffffff;
        stroke: #ffffff;
        stroke-width: 1.5;
        filter: drop-shadow(0 1px 1px rgba(15, 31, 48, 0.16));
    }

    .field-dimension {
        fill: #526171;
        font-size: 6.5px;
        font-weight: 800;
        text-anchor: middle;
    }

    .field-trajectory {
        fill: none;
        stroke: #64748b;
        stroke-linecap: round;
        stroke-width: 2.5;
        filter: drop-shadow(0 1px 1px rgba(15, 31, 48, 0.18));
        stroke-dasharray: 260;
        opacity: 0.95;
    }

    .field-trajectory.animate {
        opacity: 0;
        animation: fieldTrajectory 4.4s ease-out both;
    }

    .field-trajectory.hit {
        stroke: #187347;
    }

    .field-trajectory.out {
        stroke: #b42318;
    }

    .field-trajectory.warning {
        stroke: #b7791f;
    }

    .field-trajectory.home-run {
        stroke: #e06a24;
    }

    .field-hit-marker {
        fill: #ffffff;
        stroke: #64748b;
        stroke-width: 2.5;
        opacity: 1;
    }

    .field-hit-marker.animate {
        opacity: 0;
        animation: fieldHitMarker 4.4s ease-out both;
    }

    .field-hit-marker.hit {
        fill: #edf8f2;
        stroke: #187347;
    }

    .field-hit-marker.out {
        fill: #fff1f1;
        stroke: #b42318;
    }

    .field-hit-marker.warning {
        fill: #fff8e8;
        stroke: #b7791f;
    }

    .field-hit-marker.home-run {
        fill: #fff2e8;
        stroke: #e06a24;
    }

    .field-hit-marker.contact-latest {
        fill: #173f67;
        stroke: #ffffff;
        stroke-width: 1.6;
    }

    .field-hit-marker.contact-latest.out {
        fill: #b42318;
    }

    .field-hit-marker.contact-latest.warning {
        fill: #b7791f;
    }

    .field-ball-flight {
        display: none;
        fill: #ffffff;
        stroke: #173f67;
        stroke-width: 1.1;
        filter: drop-shadow(0 1px 2px rgba(15, 31, 48, 0.22));
        opacity: 0;
    }

    .field-ball-flight.animate {
        display: block;
        animation: fieldBallFlightFade 4.4s ease-out both;
    }

    .field-runner-ring {
        fill: #ffffff;
        stroke: #245f96;
        stroke-width: 1.5;
    }

    .live-field-footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        min-height: 28px;
        padding-top: 7px;
        color: #667587;
        font-size: 9px;
    }

    .live-field-footer strong {
        overflow: hidden;
        color: #10243b;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .live-field-footer span {
        flex: 0 0 auto;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }

    .field-contact-marker {
        fill: #173f67;
        stroke: #ffffff;
        stroke-width: 1.4;
        opacity: 0.94;
        vector-effect: non-scaling-stroke;
    }

    .field-contact-marker.hit {
        stroke: #ffffff;
    }

    .field-contact-marker.out {
        fill: #b42318;
        stroke: #ffffff;
    }

    .field-contact-marker.warning {
        fill: #b7791f;
        stroke: #ffffff;
    }

    .contact-field-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
        margin-top: 12px;
    }

    .contact-h2h-card,
    .contact-field-card,
    .momentum-card {
        border: 1px solid var(--line);
        background: #ffffff;
        padding: 12px;
    }

    .contact-h2h-card {
        margin-top: 12px;
    }

    .contact-h2h-header {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 10px;
    }

    .contact-h2h-header strong {
        color: #10243b;
        font-size: 12px;
    }

    .contact-h2h-header span {
        color: #718096;
        font-size: 9px;
        font-weight: 900;
        letter-spacing: 0.07em;
        text-transform: uppercase;
    }

    .contact-battle-head {
        display: grid;
        grid-template-columns: 1fr auto 1fr;
        align-items: center;
        gap: 12px;
        margin-bottom: 10px;
    }

    .contact-battle-team {
        display: flex;
        align-items: center;
        gap: 8px;
        color: #10243b;
        font-size: 12px;
        font-weight: 900;
    }

    .contact-battle-team.home {
        justify-content: flex-end;
    }

    .contact-battle-team img {
        width: 32px;
        height: 32px;
        object-fit: contain;
    }

    .contact-battle-vs {
        color: #718096;
        font-size: 9px;
        font-weight: 900;
        letter-spacing: 0.1em;
    }

    .contact-battle-list {
        display: grid;
        gap: 6px;
    }

    .contact-battle-row {
        display: grid;
        grid-template-columns: minmax(62px, 0.7fr) minmax(120px, 1fr) minmax(62px, 0.7fr);
        align-items: center;
        gap: 9px;
        padding: 7px 8px;
        border: 1px solid #e1e6ec;
        background: #fbfcfe;
    }

    .contact-battle-value {
        color: #10243b;
        font-size: 12px;
        font-weight: 900;
        font-variant-numeric: tabular-nums;
    }

    .contact-battle-value.home {
        text-align: right;
    }

    .contact-battle-mid {
        display: grid;
        grid-template-columns: 1fr auto 1fr;
        align-items: center;
        gap: 7px;
    }

    .contact-battle-label {
        color: #526171;
        font-size: 8px;
        font-weight: 900;
        letter-spacing: 0.07em;
        text-align: center;
        text-transform: uppercase;
        white-space: nowrap;
    }

    .contact-battle-line {
        height: 3px;
        background: #d8dee6;
    }

    .contact-battle-line.away {
        background: var(--away-color, #245f96);
    }

    .contact-battle-line.home {
        background: var(--home-color, #187347);
    }

    .contact-field-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 0;
    }

    .contact-field-team {
        display: inline-flex;
        min-width: 0;
        align-items: center;
        gap: 8px;
        color: #10243b;
        font-size: 12px;
        font-weight: 900;
    }

    .contact-field-team img {
        width: 28px;
        height: 28px;
        object-fit: contain;
    }

    .contact-field-totals {
        display: inline-flex;
        gap: 6px;
        color: #526171;
        font-size: 9px;
        font-weight: 900;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        white-space: nowrap;
    }

    .contact-field-totals span {
        padding: 2px 5px;
        border: 1px solid #d8dee6;
        background: #ffffff;
    }

    .momentum-card {
        margin-top: 12px;
    }

    .momentum-layout {
        display: grid;
        grid-template-columns: 44px minmax(0, 1fr);
        gap: 10px;
        align-items: stretch;
    }

    .momentum-logo-rail {
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        align-items: center;
        padding: 10px 0;
    }

    .momentum-logo-rail img {
        width: 34px;
        height: 34px;
        object-fit: contain;
    }

    .momentum-svg {
        display: block;
        width: 100%;
        min-height: 150px;
        border: 1px solid #d8dee6;
        background: #ffffff;
    }

    .momentum-midline {
        stroke: #b6c1ce;
        stroke-width: 1;
        stroke-dasharray: 3 5;
    }

    .momentum-segment {
        fill: none;
        stroke-width: 3;
        stroke-linecap: round;
        stroke-linejoin: round;
        vector-effect: non-scaling-stroke;
    }

    .momentum-axis {
        stroke: #e1e6ec;
        stroke-width: 1;
        vector-effect: non-scaling-stroke;
    }

    .momentum-inning-label {
        fill: #718096;
        font-size: 8px;
        font-weight: 900;
        text-anchor: middle;
    }

    .momentum-hover-zone {
        fill: #ffffff;
        opacity: 0.001;
        stroke: transparent;
        cursor: help;
        pointer-events: all;
        vector-effect: non-scaling-stroke;
    }

    .momentum-hover-dot {
        fill: #10243b;
        stroke: #ffffff;
        stroke-width: 1.5;
        opacity: 0.86;
        pointer-events: none;
        vector-effect: non-scaling-stroke;
    }

    .momentum-tooltip {
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.12s ease;
    }

    .momentum-tooltip-bg {
        fill: #10243b;
        stroke: #d8dee6;
        stroke-width: 1;
        vector-effect: non-scaling-stroke;
    }

    .momentum-tooltip text {
        fill: #ffffff;
        font-size: 6.8px;
        font-weight: 700;
    }

    .momentum-tooltip .muted {
        fill: #cbd5e1;
        font-size: 6.4px;
        font-weight: 900;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }

    @keyframes fieldTrajectory {
        0% { stroke-dashoffset: 260; opacity: 0; }
        12%, 68% { stroke-dashoffset: 0; opacity: 0.95; }
        100% { stroke-dashoffset: 0; opacity: 0; }
    }

    @keyframes fieldHitMarker {
        0% { opacity: 0; transform: scale(0.4); transform-origin: center; }
        20% { opacity: 0; transform: scale(0.4); transform-origin: center; }
        42%, 72% { opacity: 1; transform: scale(1.18); transform-origin: center; }
        100% { opacity: 0; transform: scale(0.92); transform-origin: center; }
    }

    @keyframes fieldBallFlightFade {
        0% { opacity: 0; }
        10%, 46% { opacity: 1; }
        74%, 100% { opacity: 0; }
    }

    .abs-challenge-tracker {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        align-items: stretch;
        margin-top: 10px;
        border: 1px solid #d8dee6;
        background: #ffffff;
    }

    .abs-tracker-title {
        display: flex;
        grid-column: 1 / -1;
        justify-content: center;
        padding: 6px 10px;
        border-bottom: 1px solid #d8dee6;
        background: #f4f7fa;
    }

    .abs-tracker-title strong {
        color: #10243b;
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }

    .abs-team-status {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        align-items: center;
        gap: 8px;
        padding: 8px 12px 8px 10px;
        border-right: 1px solid #e1e6ec;
        border-top: 3px solid var(--abs-team-color, #245f96);
    }

    .abs-team-status:last-child {
        border-right: 0;
    }

    .abs-team-copy {
        min-width: 0;
    }

    .abs-team-copy strong,
    .abs-team-copy span {
        display: block;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .abs-team-copy strong {
        color: #10243b;
        font-size: 11px;
    }

    .abs-team-copy span {
        margin-top: 2px;
        color: #6d7b8a;
        font-size: 8px;
    }

    .abs-challenge-count {
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .abs-challenge-dot {
        width: 10px;
        height: 10px;
        border: 1.5px solid #aab4c0;
        border-radius: 50%;
        background: #ffffff;
    }

    .abs-challenge-dot.active {
        border-color: var(--abs-team-color, #245f96);
        background: var(--abs-team-color, #245f96);
        box-shadow: 0 0 0 2px #dcebf7;
    }

    .current-hitters {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
    }

    .current-hitter-card {
        display: flex;
        align-items: center;
        gap: 8px;
        min-height: 56px;
        padding: 7px 8px;
        border: 1px solid #d8dee6;
        background: #f8fafc;
    }

    .live-player-link-card {
        cursor: pointer;
        text-align: left;
        transition: border-color 0.14s ease, background 0.14s ease, box-shadow 0.14s ease;
    }

    .live-profile-card-link {
        display: block;
        color: inherit;
        text-decoration: none;
    }

    .live-profile-card-link:hover .live-player-link-card,
    .live-profile-card-link:focus .live-player-link-card,
    .live-player-link-card:hover,
    .live-player-link-card:focus {
        border-color: #245f96;
        background: #edf5fb;
        box-shadow: inset 3px 0 0 #245f96;
        outline: none;
    }

    .live-profile-card-link:focus {
        outline: none;
    }

    .current-hitter-card img {
        width: 38px;
        height: 38px;
        border: 1px solid #d8dee6;
        border-radius: 50%;
        object-fit: cover;
    }

    .current-hitter-card strong,
    .current-hitter-card span {
        display: block;
    }

    .current-hitter-card span {
        margin-bottom: 3px;
        color: #7b8794;
        font-size: 8px;
        font-weight: 800;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }

    .live-pitcher-strip {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 8px;
        padding: 7px 8px;
        border: 1px solid #cbd5e1;
        border-left: 4px solid #173f67;
        background: #eef2f6;
    }

    .live-pitcher-strip img {
        width: 36px;
        height: 36px;
        border: 1px solid #cbd5e1;
        border-radius: 50%;
        background: #ffffff;
        object-fit: cover;
    }

    .live-pitcher-strip span,
    .live-pitcher-strip strong {
        display: block;
    }

    .live-pitcher-strip span {
        margin-bottom: 2px;
        color: #617083;
        font-size: 9px;
        font-weight: 900;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .live-pitcher-strip strong {
        color: #10243b;
        font-size: 12px;
    }

    .live-pitcher-identity {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 118px;
    }

    .live-pitcher-stats {
        display: grid;
        grid-template-columns: repeat(4, minmax(42px, 1fr));
        gap: 4px;
        margin-left: auto;
    }

    .live-pitcher-stat {
        min-width: 38px;
        padding: 4px 5px;
        border-left: 1px solid #cbd5e1;
        text-align: center;
    }

    .live-pitcher-stat span {
        margin: 0 0 2px;
        color: #708094;
        font-size: 8px;
    }

    .live-pitcher-stat strong {
        font-size: 12px;
        font-variant-numeric: tabular-nums;
    }

    .current-hitter-card.batter-changed {
        position: relative;
        animation: batterChanged 2.8s ease-out both;
    }

    .batter-change-chip {
        position: absolute;
        right: 7px;
        top: 6px;
        padding: 2px 5px;
        border: 1px solid #8fb4d6;
        background: #edf5fb;
        color: #245f96 !important;
        font-size: 8px !important;
        letter-spacing: 0.06em;
        animation: batterChip 2.8s ease-out both;
    }

    @keyframes batterChanged {
        0%, 42% {
            border-color: #6e9ec7;
            background: #edf5fb;
            box-shadow: inset 4px 0 0 #245f96;
        }
        100% {
            border-color: #d8dee6;
            background: #f8fafc;
            box-shadow: none;
        }
    }

    @keyframes batterChip {
        0%, 68% { opacity: 1; }
        100% { opacity: 0; }
    }

    .live-play-panel {
        display: flex;
        min-height: 360px;
        max-height: 560px;
        flex-direction: column;
        border: 1px solid var(--line);
        background: #ffffff;
        overflow: hidden;
    }

    .live-play-heading {
        padding: 9px 12px;
        border-bottom: 1px solid var(--line);
        color: #526171;
        font-size: 10px;
        font-weight: 900;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }

    .live-play-list {
        flex: 1 1 auto;
        min-height: 0;
        overflow-y: auto;
        overscroll-behavior: contain;
    }

    .live-play-empty {
        padding: 18px 12px;
        color: #718096;
        font-size: 11px;
        font-weight: 750;
    }

    .live-play-row {
        display: grid;
        grid-template-columns: 76px minmax(132px, 0.9fr) minmax(0, 1.6fr) auto;
        align-items: center;
        gap: 10px;
        padding: 9px 12px;
        border-bottom: 1px solid #e4e8ed;
        color: inherit;
        text-decoration: none;
    }

    .live-play-row:hover,
    .live-play-row:focus-visible {
        background: #f7fafc;
        outline: none;
    }

    .live-play-row.new-play {
        animation: livePlayEnter 0.36s cubic-bezier(0.2, 0.8, 0.2, 1) both;
    }

    .live-play-row:last-child {
        border-bottom: 0;
    }

    .live-play-row.scoring-play {
        border-left: 4px solid #245f96;
        background: #f2f7fc;
    }

    .live-play-row.scoring-play:hover,
    .live-play-row.scoring-play:focus-visible {
        background: #ebf3fb;
    }

    .play-result-chip {
        display: inline-flex;
        justify-content: center;
        padding: 3px 6px;
        border: 1px solid #cbd5e1;
        background: #f3f5f7;
        color: #31445b;
        font-size: 9px;
        font-weight: 900;
        letter-spacing: 0.035em;
        text-transform: uppercase;
        white-space: nowrap;
    }

    .play-result-chip.hit,
    .play-result-chip.home-run {
        border-color: #8fc5a6;
        background: #edf8f2;
        color: #187347;
    }

    .play-result-chip.out {
        border-color: #e6aaa4;
        background: #fff1f1;
        color: #b42318;
    }

    .play-result-chip.reach,
    .play-result-chip.warning {
        border-color: #e0c287;
        background: #fff8e8;
        color: #8a6415;
    }

    .play-score-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 34px;
        margin-left: 6px;
        padding: 2px 6px;
        border: 1px solid #8fb4d6;
        background: #edf5fb;
        color: #173f67;
        font-size: 9px;
        font-weight: 900;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }

    .live-play-matchup strong,
    .live-play-matchup span {
        display: block;
    }

    .live-play-matchup {
        display: flex;
        align-items: center;
        gap: 9px;
        min-width: 0;
    }

    .live-play-player-icons {
        position: relative;
        flex: 0 0 48px;
        width: 48px;
        height: 32px;
    }

    .live-play-player-icons img {
        position: absolute;
        top: 0;
        width: 32px;
        height: 32px;
        border: 2px solid #ffffff;
        border-radius: 50%;
        background: #eef2f6;
        object-fit: cover;
        box-shadow: 0 0 0 1px #cbd5e1;
    }

    .live-play-player-icons img:first-child {
        left: 0;
        z-index: 2;
    }

    .live-play-player-icons img:last-child {
        left: 17px;
        z-index: 1;
    }

    .live-play-matchup-copy {
        min-width: 0;
    }

    .live-play-matchup-copy strong,
    .live-play-matchup-copy span {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .live-play-matchup strong {
        color: #10243b;
        font-size: 11px;
    }

    .live-play-matchup span,
    .live-play-description,
    .live-play-meta {
        color: #687586;
        font-size: 10px;
    }

    .live-play-description {
        line-height: 1.35;
    }

    .live-play-meta {
        text-align: right;
        white-space: nowrap;
    }

    .play-detail-modal {
        display: none;
        position: fixed;
        inset: 0;
        z-index: 999999;
        align-items: center;
        justify-content: center;
        padding: 74px 24px 24px;
    }

    .play-detail-modal:target {
        display: flex;
    }

    .play-detail-scrim {
        position: absolute;
        inset: 0;
        background: rgba(6, 23, 43, 0.48);
        backdrop-filter: blur(2px);
    }

    .play-detail-modal-card {
        position: relative;
        z-index: 1;
        width: min(1040px, calc(100vw - 42px));
        max-height: calc(100vh - 108px);
        overflow: auto;
        border: 1px solid #cbd5e1;
        background: #ffffff;
        box-shadow: 0 18px 48px rgba(6, 23, 43, 0.28);
        padding: 14px;
    }

    .play-detail-modal-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 12px;
        padding-bottom: 10px;
        border-bottom: 1px solid #d8dee6;
    }

    .play-detail-modal-head span,
    .play-detail-modal-head strong {
        display: block;
    }

    .play-detail-modal-head span {
        color: #718096;
        font-size: 9px;
        font-weight: 900;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .play-detail-modal-head strong {
        color: #06172b;
        font-size: 18px;
        line-height: 1.2;
    }

    .play-detail-close {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 34px;
        height: 34px;
        border: 1px solid #173f67;
        background: #06172b;
        color: #ffffff;
        font-size: 22px;
        font-weight: 900;
        line-height: 1;
        text-decoration: none !important;
    }

    .play-detail-modal .play-detail-close,
    .play-detail-modal .play-detail-close:visited {
        color: #ffffff !important;
        text-decoration: none !important;
    }

    .play-detail-close:hover,
    .play-detail-close:focus-visible {
        background: #0b2a4a;
        color: #ffffff !important;
        text-decoration: none !important;
        outline: none;
    }

    .play-detail-matchup-strip {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
        gap: 12px;
        align-items: center;
        margin: 0 0 12px;
        padding: 4px 2px 10px;
        border: 0;
        background: transparent;
    }

    .play-detail-person {
        display: flex;
        align-items: center;
        gap: 12px;
        min-width: 0;
    }

    .play-detail-person.pitcher {
        justify-content: flex-end;
        text-align: right;
    }

    .play-detail-person.pitcher .play-detail-face-copy {
        order: 1;
    }

    .play-detail-person.pitcher .play-detail-face-img,
    .play-detail-person.pitcher .play-detail-face-placeholder {
        order: 2;
    }

    .play-detail-face-img,
    .play-detail-face-placeholder {
        flex: 0 0 74px;
        width: 74px;
        height: 74px;
        border: 2px solid #ffffff;
        border-radius: 50%;
        background: #ffffff;
        object-fit: cover;
        box-shadow: 0 0 0 1px #cbd5e1;
    }

    .play-detail-face-placeholder {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: #7a8796;
        font-size: 24px;
        font-weight: 900;
    }

    .play-detail-face-copy {
        min-width: 0;
    }

    .play-detail-face-copy span,
    .play-detail-face-copy strong {
        display: block;
    }

    .play-detail-face-copy span {
        color: #718096;
        font-size: 9px;
        font-weight: 900;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .play-detail-face-copy strong {
        overflow: hidden;
        color: #06172b;
        font-size: 18px;
        line-height: 1.2;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .play-detail-vs {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 28px;
        border: 1px solid #cbd5e1;
        border-radius: 50%;
        background: #ffffff;
        color: #526171;
        font-size: 10px;
        font-weight: 900;
        letter-spacing: 0.06em;
    }

    .play-detail-gamelog {
        min-width: 0;
        margin-top: 11px;
        padding: 8px 10px;
        border: 1px solid #e1e7ef;
        background: #f8fafc;
    }

    .play-detail-gamelog-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 7px;
    }

    .play-detail-gamelog-head span,
    .play-detail-gamelog-grid span {
        color: #718096;
        font-size: 8px;
        font-weight: 900;
        letter-spacing: 0.07em;
        text-transform: uppercase;
    }

    .play-detail-gamelog-head strong {
        overflow: hidden;
        color: #06172b;
        font-size: 11px;
        line-height: 1.2;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .play-detail-gamelog-grid {
        display: grid;
        grid-template-columns: 1.45fr repeat(3, minmax(30px, 0.7fr));
        gap: 3px 8px;
        align-items: baseline;
    }

    .play-detail-gamelog-grid strong {
        color: #10243b;
        font-size: 11px;
        font-variant-numeric: tabular-nums;
    }

    .play-detail-gamelog-empty {
        color: #526171;
        font-size: 11px;
        line-height: 1.35;
    }

    @keyframes livePlayEnter {
        0% {
            opacity: 0;
            transform: translateY(-10px);
        }
        100% {
            opacity: 1;
            transform: translateY(0);
        }
    }

    .play-detail-layout {
        display: grid;
        grid-template-columns: minmax(260px, 0.85fr) minmax(260px, 1fr);
        gap: 12px;
        align-items: start;
    }

    .play-detail-card {
        border: 1px solid var(--line);
        background: #ffffff;
        padding: 12px;
    }

    .play-detail-card h3 {
        margin: 0 0 7px;
        color: #10243b;
        font-size: 15px;
    }

    .play-detail-card p {
        margin: 0;
        color: #526171;
        font-size: 12px;
        line-height: 1.45;
    }

    .play-detail-stat-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 8px;
        margin-top: 10px;
    }

    .play-detail-stat {
        border-left: 1px solid #d8dee6;
        padding-left: 8px;
    }

    .play-detail-stat span,
    .play-detail-stat strong {
        display: block;
    }

    .play-detail-stat span {
        color: #718096;
        font-size: 9px;
        font-weight: 900;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }

    .play-detail-stat strong {
        color: #10243b;
        font-size: 18px;
        font-variant-numeric: tabular-nums;
    }

    .inning-efficiency-svg {
        display: block;
        width: 100%;
        height: auto;
        margin-top: 8px;
        border: 1px solid #d8dee6;
        background: #fbfcfe;
    }

    @media (prefers-reduced-motion: reduce) {
        .live-score.score-changed,
        .live-score-delta,
        .home-run-notice,
        .home-run-fire,
        .current-hitter-card.batter-changed,
        .batter-change-chip,
        .field-trajectory,
        .field-hit-marker,
        .field-ball-flight,
        .strike-zone-pitch-marker,
        .live-play-row:first-child {
            animation: none;
        }
    }

    .matchup-rank-strip {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        margin: 4px 0 10px;
    }

    .matchup-rank-item {
        padding: 10px 12px;
        border-right: 1px solid var(--line);
    }

    .matchup-rank-item:last-child {
        border-right: 0;
    }

    .matchup-rank-value {
        margin-top: 3px;
        color: #06172b;
        font-size: 18px;
        font-weight: 800;
    }

    .player-card-grid {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 10px;
        margin: 8px 0 14px;
    }

    .player-card {
        width: 100%;
        min-height: 210px;
        padding: 14px;
        color: #111827;
        text-align: left;
        cursor: pointer;
    }

    .player-card:hover,
    .player-card:focus-visible {
        border-color: #8fb4d6;
        background: #f7fafc;
        outline: none;
    }

    .player-card img {
        display: block;
        width: 88px;
        height: 88px;
        margin: 0 auto 10px;
        border: 1px solid #d8dee6;
        border-radius: 50%;
        background: #f3f5f7;
        object-fit: cover;
    }

    .player-card-rank {
        color: #7b8794;
        font-size: 10px;
        font-weight: 800;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }

    .player-card-name {
        display: block;
        margin-top: 4px;
        color: #06172b;
        font-size: 15px;
        font-weight: 800;
    }

    .player-card-team {
        display: block;
        margin-top: 3px;
        color: #526171;
        font-size: 11px;
    }

    .player-profile-hero {
        display: grid;
        grid-template-columns: 150px minmax(0, 1fr);
        gap: 20px;
        align-items: center;
        padding: 18px;
        margin-bottom: 10px;
    }

    .player-profile-hero > img {
        width: 132px;
        height: 132px;
        border: 1px solid #d8dee6;
        border-radius: 50%;
        background: #f3f5f7;
        object-fit: cover;
    }

    .player-profile-title {
        color: #06172b;
        font-family: var(--font-display);
        font-size: 34px;
        letter-spacing: 0.035em;
    }

    .player-profile-meta {
        color: #526171;
        font-size: 14px;
    }

    .profile-stat-grid {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        border: 1px solid var(--line);
        background: #ffffff;
        margin-bottom: 12px;
    }

    .profile-stat {
        padding: 11px 12px;
        border-right: 1px solid var(--line);
    }

    .profile-stat:last-child {
        border-right: 0;
    }

    .profile-stat strong {
        display: block;
        margin-top: 4px;
        color: #06172b;
        font-size: 20px;
    }

    .home-placeholder {
        min-height: 260px;
        padding: 48px 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #647184;
        text-align: center;
    }

    .team-streak-record {
        display: inline-flex;
        padding: 3px 7px;
        border: 1px solid #d8dee6;
        background: #f2f4f7;
        color: #687384;
        font-size: 10px;
        font-weight: 800;
    }

    .team-streak-record.good {
        border-color: #a5d6b7;
        background: #edf8f2;
        color: #247a4d;
    }

    .team-streak-record.bad {
        border-color: #e2b8b8;
        background: #fff0f0;
        color: #b43b3b;
    }

    .team-streak-logo {
        width: 38px;
        height: 38px;
        border: 0;
        border-radius: 0;
        background: transparent;
        object-fit: contain;
    }

    [class*="st-key-app_back_"] {
        display: flex;
        align-items: center;
        width: fit-content;
        margin: 0;
    }

    [class*="st-key-app_back_"] .stButton,
    [class*="st-key-app_back_"] .stButton > button {
        width: 40px;
    }

    [class*="st-key-app_back_"] .stButton > button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 40px;
        min-height: 40px;
        padding: 0;
        border: 1px solid #173f67;
        background: #06172b;
        color: #ffffff;
        font-size: 22px;
        font-weight: 900;
        line-height: 1;
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.10),
            0 2px 0 rgba(6, 23, 43, 0.16);
    }

    [class*="st-key-app_back_"] .stButton > button:hover,
    [class*="st-key-app_back_"] .stButton > button:focus-visible {
        border-color: #245f96;
        background: #0b2a4a;
        color: #ffffff;
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.14),
            0 0 0 2px rgba(36, 95, 150, 0.14);
    }

    .st-key-player_profile_back_bar {
        margin: 0 0 8px;
    }

    .st-key-live_game_header_bar {
        margin: 0 0 8px;
    }

    .st-key-streak_toolbar {
        width: min(100%, 370px);
        margin: -34px 0 2px auto;
    }

    .st-key-streak_toolbar [data-testid="stHorizontalBlock"] {
        gap: 7px;
    }

    .st-key-games_toolbar {
        position: relative;
        z-index: 2;
        width: min(100%, 660px);
        margin: -34px 0 2px auto;
    }

    .st-key-games_toolbar [data-testid="stHorizontalBlock"] {
        gap: 8px;
    }

    .roster-player-card-grid {
        max-height: 720px;
        overflow: auto;
        padding-right: 4px;
    }

    .matchup-rank-strip .research-grade {
        display: inline-block;
        padding: 3px 7px;
        border-radius: 2px;
        font-size: 11px;
        font-weight: 800;
    }

    .matchup-rank-strip .research-grade.good {
        color: #247a4d;
        background: #edf8f2;
    }

    .matchup-rank-strip .research-grade.neutral {
        color: #9a6810;
        background: #fff8e8;
    }

    .matchup-rank-strip .research-grade.avoid {
        color: #b43b3b;
        background: #fff0f0;
    }

    .matchup-rank-strip .research-grade.sample {
        color: #3f6fa8;
        background: #eef5ff;
    }

    .matchup-rank-strip .research-grade.none {
        color: #687384;
        background: #f2f4f7;
    }

    .leaderboard-name .team-streak-record {
        display: inline-flex;
        margin-top: 3px;
    }

    .st-key-matchup_toolbar,
    .st-key-matchup_filter_toolbar {
        margin: 0 0 6px;
    }

    .st-key-matchup_toolbar {
        position: relative;
        z-index: 2;
        width: 100%;
        margin: 0 0 6px;
    }

    .st-key-matchup_toolbar [data-testid="stHorizontalBlock"] {
        gap: 8px;
    }

    .st-key-matchup_toolbar .stRadio [role="radiogroup"] {
        display: flex !important;
        flex-wrap: nowrap !important;
        column-gap: 8px !important;
    }

    .st-key-matchup_toolbar .stRadio [role="radiogroup"] label {
        flex: 0 0 auto;
        margin-right: 0 !important;
        padding: 0 14px;
    }

    .st-key-matchup_toolbar .stRadio [role="radiogroup"] label:has(input:checked) {
        margin-bottom: -1px !important;
    }

    .st-key-matchup_toolbar [data-testid="stSelectbox"],
    .st-key-matchup_filter_toolbar [data-testid="stSelectbox"] {
        min-width: 0;
    }

    .st-key-matchup_filter_toolbar [data-testid="stHorizontalBlock"] {
        display: grid !important;
        grid-template-columns: minmax(190px, 1.25fr) minmax(170px, 1fr) minmax(170px, 1fr) !important;
        gap: 10px !important;
        align-items: end;
    }

    .st-key-matchup_filter_toolbar [data-testid="stColumn"] {
        min-width: 0 !important;
        width: 100% !important;
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

    [class*="st-key-box_tabs_"] .stRadio [role="radiogroup"] {
        gap: 0;
        border-bottom: 1px solid var(--line);
        margin-bottom: 4px;
    }

    [class*="st-key-box_tabs_"] .stRadio [role="radiogroup"] label {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        min-height: 40px;
        padding: 0 18px;
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

    [class*="st-key-box_tabs_"] .stRadio [role="radiogroup"] label:has(input:checked) {
        margin-bottom: -1px;
        border-color: var(--line);
        border-bottom-color: #245f96;
        background: var(--panel);
        color: var(--text);
        font-weight: 700;
    }

    [class*="st-key-box_tabs_"] .stRadio [role="radiogroup"] label:hover {
        color: var(--text);
        background: #f6f8fa;
    }

    [class*="st-key-box_tabs_"] .stRadio [role="radiogroup"] [data-testid="stMarkdownContainer"] p {
        font-size: 15px;
        font-family: var(--font-display) !important;
        font-weight: 400 !important;
        letter-spacing: 0.055em;
        margin: 0 !important;
        text-align: center;
        white-space: nowrap;
    }

    [class*="st-key-box_tabs_"] .stRadio [role="radiogroup"] [data-testid="stMarkdownContainer"] {
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

    div[data-testid="stStatusWidget"] {
        visibility: hidden;
    }

    @media (max-width: 680px) {
        header[data-testid="stHeader"]::before {
            top: 15px;
            left: 18px;
            font-size: 22px;
        }

        [class*="st-key-app_header_nav_mount"] {
            left: 148px;
            right: 46px;
            justify-content: flex-start;
        }

        [class*="st-key-app_header_nav_mount"] [data-testid="stHorizontalBlock"] {
            overflow-x: auto;
            scrollbar-width: none;
            -webkit-overflow-scrolling: touch;
        }

        [class*="st-key-app_header_nav_mount"] [data-testid="stHorizontalBlock"]::-webkit-scrollbar {
            display: none;
        }

        [class*="st-key-app_header_nav_mount"] [data-testid="stColumn"] {
            flex: 0 0 auto !important;
            width: auto !important;
        }

        [class*="st-key-app_header_nav_mount"] .stButton > button {
            min-height: 44px;
            padding: 0 12px;
            font-size: 14px;
        }

        .block-container {
            padding-right: 0.75rem;
            padding-left: 0.75rem;
        }

        .st-key-active_view .stRadio [role="radiogroup"] {
            grid-template-columns: repeat(4, minmax(0, 1fr));
        }

        .st-key-active_view .stRadio [role="radiogroup"] label {
            min-height: 46px;
            padding: 0 5px;
        }

        .st-key-active_view .stRadio [role="radiogroup"] p {
            font-size: 14px;
            letter-spacing: 0.035em;
        }

        [class*="st-key-box_tabs_"] .stRadio [role="radiogroup"] {
            overflow-x: auto;
            flex-wrap: nowrap !important;
            scrollbar-width: none;
            -webkit-overflow-scrolling: touch;
        }

        [class*="st-key-box_tabs_"] .stRadio [role="radiogroup"]::-webkit-scrollbar {
            display: none;
        }

        [class*="st-key-box_tabs_"] .stRadio [role="radiogroup"] label {
            flex: 0 0 auto;
            min-height: 46px;
            padding: 0 14px;
        }

        .st-key-matchup_toolbar {
            width: 100%;
            margin: 8px 0;
        }

        .st-key-matchup_toolbar > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] {
            display: grid !important;
            grid-template-columns: 44px minmax(0, 1fr) 44px !important;
            gap: 8px !important;
        }

        .st-key-matchup_toolbar > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(1) {
            grid-column: 1 / -1;
        }

        [data-baseweb="popover"] {
            max-width: calc(100vw - 16px) !important;
        }

        [data-baseweb="calendar"] {
            max-width: calc(100vw - 16px) !important;
            overflow-x: auto !important;
        }

        .st-key-matchup_filter_toolbar [data-testid="stHorizontalBlock"] {
            grid-template-columns: 1fr !important;
        }
    }

    @media (max-width: 1100px) {
        .st-key-games_toolbar,
        .st-key-streak_toolbar {
            width: 100%;
            margin: 8px 0;
        }

        .st-key-games_toolbar [data-testid="stColumn"],
        .st-key-streak_toolbar [data-testid="stColumn"] {
            width: 100% !important;
            min-width: 0 !important;
            flex: none !important;
        }

        .st-key-streak_toolbar [data-testid="stHorizontalBlock"] {
            display: grid !important;
            grid-template-columns: 44px minmax(0, 1fr) 44px !important;
            gap: 8px !important;
        }

        .st-key-games_toolbar [data-testid="stHorizontalBlock"] {
            display: grid !important;
            grid-template-columns: minmax(0, 1fr) 44px minmax(0, 1.15fr) 44px minmax(0, 1fr) !important;
            gap: 8px !important;
        }

        .contact-field-grid {
            grid-template-columns: 1fr;
        }

        .live-game-layout {
            grid-template-columns: minmax(0, 1fr) minmax(310px, 0.82fr);
            grid-template-areas: "main side";
        }

        .live-main-area {
            grid-template-columns: minmax(0, 1fr);
            grid-template-areas:
                "atplate"
                "field"
                "zone";
        }
    }

    @media (max-width: 900px) {
        .st-key-matchup_toolbar > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] {
            display: grid !important;
            grid-template-columns: 44px minmax(0, 1fr) 44px !important;
            gap: 8px !important;
        }

        .st-key-matchup_toolbar > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(1) {
            grid-column: 1 / -1;
        }

        .block-container {
            padding-top: 0.95rem;
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

        .player-card-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .st-key-streak_toolbar {
            width: 100%;
            margin-left: 0;
            margin-top: 0;
            margin-bottom: 8px;
        }

        .st-key-games_toolbar {
            width: 100%;
            margin: 0 0 8px;
        }

        .profile-stat-grid {
            grid-template-columns: repeat(3, minmax(0, 1fr));
        }

        .profile-stat:nth-child(3) {
            border-right: 0;
        }

        .live-game-scorebug,
        .live-game-layout,
        .player-profile-hero,
        .play-detail-layout {
            grid-template-columns: 1fr;
        }

        .live-game-layout {
            grid-template-areas:
                "main"
                "side";
        }

        .live-main-area {
            grid-template-columns: 1fr;
        }

        .live-lineup-grid {
            grid-template-columns: 1fr;
        }

        .play-detail-modal {
            align-items: stretch;
            padding: 64px 12px 12px;
        }

        .play-detail-modal-card {
            width: 100%;
            max-height: calc(100vh - 76px);
        }

        .play-detail-matchup-strip {
            grid-template-columns: 1fr;
            gap: 10px;
        }

        .play-detail-person.pitcher {
            justify-content: flex-start;
            text-align: left;
        }

        .play-detail-person.pitcher .play-detail-face-copy {
            order: 2;
        }

        .play-detail-person.pitcher .play-detail-face-img,
        .play-detail-person.pitcher .play-detail-face-placeholder {
            order: 1;
        }

        .play-detail-vs {
            justify-self: start;
            width: auto;
            height: auto;
            border: 0;
            background: transparent;
        }

        .abs-challenge-tracker {
            grid-template-columns: 1fr 1fr;
        }

        .abs-tracker-title {
            grid-column: 1 / -1;
            min-width: 0;
            border-right: 0;
            border-bottom: 1px solid #d8dee6;
        }

        .live-field-svg {
            min-height: 250px;
        }

        .current-hitters {
            grid-template-columns: 1fr;
        }

        .live-pitcher-strip {
            align-items: stretch;
            flex-direction: column;
        }

        .live-pitcher-stats {
            width: 100%;
            margin-left: 0;
        }

        .live-pitcher-stat:first-child {
            border-left: 0;
        }

        .live-play-row {
            grid-template-columns: 76px minmax(0, 1fr);
        }

        .live-play-description,
        .live-play-meta {
            grid-column: 1 / -1;
            text-align: left;
        }

        .live-game-team,
        .live-game-team:last-child {
            justify-content: center;
            text-align: center;
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


def is_missing_value(value):
    if value is None:
        return True

    try:
        missing = pd.isna(value)
        if isinstance(missing, bool):
            return missing
        if bool(missing):
            return True
    except (TypeError, ValueError):
        pass
    except Exception:
        pass

    try:
        text = str(value).strip()
    except Exception:
        return True

    return text == "" or text.lower() in {"nan", "nat", "none", "<na>"}


def safe_value(value, default=""):
    return default if is_missing_value(value) else value


def safe_text(value, default=""):
    return str(safe_value(value, default))


def row_value(row, *columns, default=""):
    for column in columns:
        try:
            value = row.get(column)
        except AttributeError:
            try:
                value = row[column]
            except Exception:
                value = None
        except Exception:
            value = None

        if not is_missing_value(value):
            return value

    return default


def row_text(row, *columns, default=""):
    return safe_text(row_value(row, *columns, default=default), default=default)


def team_logo_url(team_value):
    if is_missing_value(team_value):
        return ""

    team_value = str(team_value).strip()
    team_id = TEAM_ID_BY_NAME.get(team_value)

    if team_id is None:
        team_id = TEAM_ID_BY_ABBR.get(team_value.upper())

    if team_id is None:
        return ""

    return f"https://www.mlbstatic.com/team-logos/{team_id}.svg"


def team_abbreviation(team_value):
    if is_missing_value(team_value):
        return ""
    text = str(team_value).strip()
    team_id = TEAM_ID_BY_NAME.get(text)
    if team_id is None:
        upper = text.upper()
        if upper in TEAM_ID_BY_ABBR:
            return upper
        return ""
    for abbr, mapped_team_id in TEAM_ID_BY_ABBR.items():
        if mapped_team_id == team_id:
            return abbr
    return ""


def team_logo_fallback_url(team_value):
    if is_missing_value(team_value):
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
    if is_missing_value(team_value):
        return None

    text = str(team_value).strip()
    if not text:
        return None

    team_id = TEAM_ID_BY_NAME.get(text)
    if team_id is not None:
        return team_id

    return TEAM_ID_BY_ABBR.get(text.upper())


def safe_hex_color(value, default="#173f67"):
    text = safe_text(value, default=default).strip()
    if len(text) == 7 and text.startswith("#"):
        allowed = set("0123456789abcdefABCDEF")
        if all(character in allowed for character in text[1:]):
            return text
    return default


def team_primary_color(team_value, default="#173f67"):
    team_id = team_id_for_value(team_value)
    return safe_hex_color(TEAM_PRIMARY_COLOR_BY_ID.get(team_id), default)


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
            team_code = row_value(game, f"{side}_team_abbr", default=team_name)
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
    src = safe_text(src)
    fallback_src = safe_text(fallback_src)
    alt = safe_text(alt)
    title = safe_text(title)

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
    label = safe_text(alt, default="")
    if not label:
        label = safe_text(team_value, default="Team")
    if not label:
        label = "Team"
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

    team_name = row_text(row, f"{side}_team")
    if not team_name:
        return side.title()
    return "".join(word[0] for word in team_name.split()[-2:]).upper()


def score_value(value):
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return "-"
    return f"{int(number)}"


def game_status_text(row):
    status = row_text(row, "game_status", default="Scheduled")
    abstract_state = row_text(row, "abstract_game_state").lower()
    inning = row_text(row, "current_inning_ordinal", "current_inning")
    inning_state = row_text(row, "inning_state", "inning_half", default="Live")

    if abstract_state == "live" and inning:
        return f"{inning_state} {inning}"
    return status


def schedule_status_html(row):
    status = game_status_text(row)
    abstract_state = row_text(row, "abstract_game_state").lower()
    game_time_utc = row_text(row, "game_time_utc")
    is_scheduled = (
        abstract_state in {"", "preview"}
        and status.lower() in {"scheduled", "pre-game", "pregame"}
        and game_time_utc
    )
    if not is_scheduled:
        return f'<span class="score-status">{escape(status)}</span>'

    return (
        '<time class="score-status local-game-time" '
        f'datetime="{escape(game_time_utc, quote=True)}" '
        f'data-game-time-utc="{escape(game_time_utc, quote=True)}">'
        f"{escape(status)}</time>"
    )


def schedule_situation_html(row):
    outs = int(safe_value(row.get("outs"), 0))
    base_html = []
    for base, key in (
        ("first", "runner_on_first"),
        ("second", "runner_on_second"),
        ("third", "runner_on_third"),
    ):
        value = row.get(key)
        occupied_base = (
            False
            if is_missing_value(value)
            else value
            if isinstance(value, bool)
            else safe_text(value).strip().lower() in {"1", "true", "yes"}
        )
        occupied = " occupied" if occupied_base else ""
        base_html.append(f'<span class="mini-base {base}{occupied}"></span>')

    def dots(kind, active, total):
        return "".join(
            f'<span class="mini-dot {kind}{" active" if index < active else ""}"></span>'
            for index in range(total)
        )

    return (
        '<span class="schedule-situation-mini" aria-label="Live game situation">'
        f'<span class="mini-bases" title="Bases">{"".join(base_html)}</span>'
        f'<span class="mini-outs" title="Outs">Outs {dots("out", outs, 3)}</span>'
        "</span>"
    )


def game_button_label(row):
    away_team = row_text(row, "away_team", default="Away")
    home_team = row_text(row, "home_team", default="Home")
    return f"{away_team} @ {home_team}"


def current_query_value(name, default=None):
    value = st.query_params.get(name, default)
    if isinstance(value, list):
        return value[0] if value else default
    return value


def sync_active_view_query():
    active_view = st.session_state.get("active_view")
    st.session_state.selected_boxscore_game_pk = None
    for key in list(st.session_state):
        if key.endswith("_selected_log"):
            st.session_state[key] = None
    if active_view:
        st.query_params["view"] = active_view
    if active_view != "Players":
        st.query_params.pop("player", None)
        st.query_params.pop("profile_group", None)
        st.query_params.pop("return_view", None)
        st.query_params.pop("return_game_pk", None)
        st.session_state.selected_player_profile = None
        st.session_state.player_profile_return = None


def dashboard_view_slug(view):
    return "".join(
        character.lower() if character.isalnum() else "_"
        for character in safe_text(view)
    ).strip("_") or "view"


def select_dashboard_view(view):
    if view not in {
        "Matchups",
        "Games",
        "Weather",
        "Streaks",
        "Players",
        "Player Stats",
        "Team Stats",
        "Details",
    }:
        return
    st.session_state.active_view = view
    st.session_state.pending_active_view = view
    st.query_params["view"] = view
    if view != "Games":
        st.session_state.selected_boxscore_game_pk = None
        st.query_params.pop("game_pk", None)
        st.query_params.pop("game_tab", None)
    if view != "Players":
        st.session_state.selected_player_profile = None
        st.session_state.player_profile_return = None
        st.query_params.pop("player", None)
        st.query_params.pop("profile_group", None)
        st.query_params.pop("return_view", None)
        st.query_params.pop("return_game_pk", None)


def render_view_tabs(view_options):
    active_view = st.session_state.get("active_view", view_options[0])
    if active_view not in view_options:
        active_view = view_options[0]
        st.session_state.active_view = active_view

    with st.container(key="app_header_nav_mount"):
        nav_columns = st.columns(
            [max(5, len(option)) for option in view_options],
            gap="small",
            vertical_alignment="center",
        )
        for column, option in zip(nav_columns, view_options):
            state = "active" if option == active_view else "idle"
            slug = dashboard_view_slug(option)
            with column:
                with st.container(key=f"app_nav_tab_{state}_{slug}"):
                    st.button(
                        option,
                        key=f"app_nav_button_{slug}",
                        on_click=select_dashboard_view,
                        args=(option,),
                        use_container_width=True,
                    )
    return active_view


BACK_BUTTON_LABEL = "\u2190"


def render_universal_back_button(key, help_text="Back"):
    return st.button(
        BACK_BUTTON_LABEL,
        key=f"app_back_{key}",
        help=help_text,
        use_container_width=True,
    )


def player_profile_payload(
    player_id,
    player,
    team,
    group,
    season,
):
    player_id = pd.to_numeric(player_id, errors="coerce")
    if pd.isna(player_id):
        return None
    return {
        "action": "player_profile",
        "player_id": int(player_id),
        "player": safe_text(player, default="Player"),
        "team": safe_text(team),
        "group": "pitching" if group == "pitching" else "batting",
        "season": int(season),
    }


def navigate_to_player_profile(payload, source_view, game_pk=None):
    if not isinstance(payload, dict):
        return
    player_id = pd.to_numeric(payload.get("player_id"), errors="coerce")
    if pd.isna(player_id):
        return

    profile = dict(payload)
    profile["player_id"] = int(player_id)
    profile["action"] = "player_profile"
    profile["season"] = int(safe_value(profile.get("season"), app_today.year))
    st.session_state.selected_player_profile = profile
    st.session_state.player_profile_return = {
        "view": source_view,
        "game_pk": (
            int(game_pk)
            if game_pk is not None and not is_missing_value(game_pk)
            else None
        ),
    }
    st.session_state.pending_active_view = "Players"
    st.query_params["view"] = "Players"
    st.query_params["player"] = str(int(player_id))
    st.query_params["profile_group"] = profile.get("group", "batting")
    st.query_params["return_view"] = source_view
    if game_pk is not None and not is_missing_value(game_pk):
        st.query_params["return_game_pk"] = str(int(game_pk))
    st.rerun(scope="app")


def open_advanced_hvp(
    batter_id=None,
    pitcher_id=None,
    game_pk=None,
    opponent_team_id=None,
):
    st.session_state.pending_active_view = "Matchups"
    st.session_state.active_view = "Matchups"
    st.session_state.active_matchup_table = HVP_PAGE_TAB_LABEL
    st.query_params["view"] = "Matchups"
    st.query_params["matchup_table"] = HVP_PAGE_TAB_LABEL
    if batter_id is not None and not is_missing_value(batter_id):
        st.session_state.hvp_batter_id = int(batter_id)
    if pitcher_id is not None and not is_missing_value(pitcher_id):
        st.session_state.hvp_pitcher_id = int(pitcher_id)
    if game_pk is not None and not is_missing_value(game_pk):
        st.session_state.hvp_game_pk = int(game_pk)
        st.query_params["game_pk"] = str(int(game_pk))
    if opponent_team_id is not None and not is_missing_value(opponent_team_id):
        st.session_state.hvp_opponent_team_id = int(opponent_team_id)
    st.rerun(scope="app")


def handle_player_profile_event(event, source_view, game_pk=None):
    if not isinstance(event, dict) or event.get("type") != "select_player":
        return
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("action") != "player_profile":
        return
    event_key = f"profile_event_{source_view}_{game_pk or 'none'}"
    event_id = safe_text(event.get("event_id"))
    if not event_id or event_id == st.session_state.get(event_key):
        return
    st.session_state[event_key] = event_id
    navigate_to_player_profile(payload, source_view, game_pk=game_pk)


def return_from_player_profile():
    return_state = st.session_state.get("player_profile_return") or {}
    return_view = safe_text(return_state.get("view"), default="Players")
    return_game_pk = return_state.get("game_pk")
    st.session_state.selected_player_profile = None
    st.session_state.player_profile_return = None
    st.session_state.players_search = None
    st.query_params.pop("player", None)
    st.query_params.pop("profile_group", None)
    st.query_params.pop("return_view", None)
    st.query_params.pop("return_game_pk", None)
    if return_view not in {
        "Matchups",
        "Games",
        "Streaks",
        "Players",
        "Player Stats",
        "Team Stats",
        "Details",
    }:
        return_view = "Players"
    st.session_state.pending_active_view = return_view
    st.query_params["view"] = return_view
    if return_view == "Games" and not is_missing_value(return_game_pk):
        st.session_state.selected_boxscore_game_pk = int(return_game_pk)
    st.rerun(scope="app")


def render_box_tabs(tab_key, options, state_key, default=None):
    default = default or options[0]
    active_value = st.session_state.get(state_key, default)
    if active_value not in options:
        active_value = default
        st.session_state[state_key] = active_value

    with st.container(key=f"box_tabs_{dashboard_view_slug(state_key)}"):
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
    "balls",
    "strikes",
    "outs",
    "runner_on_first",
    "runner_on_second",
    "runner_on_third",
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

    icon_paths = paths.get(safe_text(icon_name, default="unknown"), paths["unknown"])
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


def scheduled_probable_pitcher_names(schedule_df):
    if schedule_df.empty:
        return []

    names = []
    seen = set()
    for column in ("away_probable_pitcher", "home_probable_pitcher"):
        if column not in schedule_df.columns:
            continue
        for name in schedule_df[column].dropna():
            text = str(name).strip()
            key = text.casefold()
            if not text or text.upper() == "TBD" or key in seen:
                continue
            names.append(text)
            seen.add(key)
    return names


def scheduled_pitcher_options(schedule_df, pitchers_df=None):
    if schedule_df.empty:
        return []

    recommended = scheduled_probable_pitcher_names(schedule_df)
    recommended_keys = {name.casefold() for name in recommended}
    names = set(recommended)

    if pitchers_df is not None and not pitchers_df.empty and "Name" in pitchers_df.columns:
        options_df = pitchers_df.copy()
        team_ids = schedule_team_ids(schedule_df)
        if team_ids and "team_id" in options_df.columns:
            options_df = options_df[
                pd.to_numeric(options_df["team_id"], errors="coerce").isin(team_ids)
            ].copy()
        names.update(
            str(name).strip()
            for name in options_df["Name"].dropna()
            if str(name).strip()
        )

    remaining = sorted(
        {
            name
            for name in names
            if name.casefold() not in recommended_keys
        },
        key=str.casefold,
    )
    return [*recommended, *remaining]


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


def filter_prebuilt_matchups(
    matchup_df,
    schedule_df,
    batters_df,
    selected_game="All Games",
    selected_batter=None,
    selected_pitcher=None,
):
    """Filter a prebuilt full-slate table without rebuilding matchup data."""
    if matchup_df.empty:
        return matchup_df

    allowed_schedule = filter_by_game(schedule_df, selected_game)
    allowed_schedule = filter_schedule_for_batter(
        allowed_schedule,
        batters_df,
        selected_batter,
    )
    allowed_schedule = filter_schedule_for_pitcher(
        allowed_schedule,
        selected_pitcher,
    )
    allowed_schedule = add_game_column(allowed_schedule)

    if allowed_schedule.empty or "game" not in allowed_schedule.columns:
        return matchup_df.iloc[0:0].copy()

    allowed_games = set(allowed_schedule["game"].dropna().astype(str))
    return filter_prebuilt_matchup_rows(
        matchup_df,
        allowed_games,
        selected_batter=selected_batter,
        selected_pitcher=selected_pitcher,
    )


def compact_weather_html(row):
    weather_icon_name = row_text(row, "weather_icon", default="unknown")
    weather_svg = weather_icon_svg(weather_icon_name, size=20)
    weather_display = row_text(row, "weather_display", default="?")
    weather_edge = row_text(row, "weather_edge", default="Neutral")
    weather_tooltip = escape(
        row_text(row, "weather_tooltip", default="Forecast unavailable."),
        quote=True,
    )
    return (
        '<span class="schedule-weather-chip schedule-tooltip" '
        f'data-tooltip="{weather_tooltip}" tabindex="0">'
        f"{weather_svg}<span>{escape(weather_display)}</span></span>"
        f'<span class="schedule-weather-edge">{escape(weather_edge)}</span>'
    )


def compact_wind_html(row):
    wind_speed = pd.to_numeric(row.get("wind_speed_mph"), errors="coerce")
    wind_speed_text = f"{float(wind_speed):.0f} mph" if pd.notna(wind_speed) else "N/A"
    degrees = pd.to_numeric(row.get("wind_direction_deg"), errors="coerce")
    cardinal = row_text(row, "wind_direction_cardinal")
    if pd.notna(degrees):
        direction_text = f"{int(round(float(degrees))) % 360}\u00b0"
        if cardinal:
            direction_text += f" {cardinal}"
    else:
        direction_text = row_text(row, "wind_field_direction", default="Dir TBD")
    wind_detail = weather_wind_precision_label(row)
    tooltip_text = row_text(row, "wind_tooltip", default="Wind forecast unavailable.")
    if wind_detail and wind_detail not in tooltip_text:
        tooltip_text = f"{wind_detail}. {tooltip_text}"
    wind_tooltip = escape(tooltip_text, quote=True)
    wind_angle = weather_wind_angle(row)
    return (
        '<span class="schedule-wind-chip schedule-tooltip" '
        f'data-tooltip="{wind_tooltip}" tabindex="0">'
        f'<span class="schedule-wind-arrow" style="--wind-angle:{wind_angle:.1f}deg" '
        'aria-hidden="true">&#8594;</span>'
        '<span class="schedule-wind-copy">'
        f'<span>{escape(wind_speed_text)}</span>'
        f'<small>{escape(direction_text)}</small>'
        "</span></span>"
    )


def pitcher_pair_html(row):
    away_pitcher = row_text(row, "away_probable_pitcher", default="TBD")
    home_pitcher = row_text(row, "home_probable_pitcher", default="TBD")
    away_hand = row_text(row, "away_pitcher_hand")
    home_hand = row_text(row, "home_pitcher_hand")

    away_text = escape(away_pitcher)
    if away_hand:
        away_text += f" ({escape(away_hand)})"
    home_text = escape(home_pitcher)
    if home_hand:
        home_text += f" ({escape(home_hand)})"
    return f'<div class="schedule-pitchers">{away_text}<span>{home_text}</span></div>'


def venue_html(row):
    venue = row_text(row, "venue_name", default="Venue TBD")
    roof = row_text(row, "roof_type", default="Roof unknown")
    return f'<div class="schedule-venue">{escape(venue)}<span>{escape(roof)}</span></div>'


def is_retractable_roof(row):
    return "retractable" in row_text(row, "roof_type").lower()


def weather_number_text(value, suffix="", decimals=0, default="N/A"):
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return f"{float(number):.{decimals}f}{suffix}"


def weather_wind_angle(row):
    wind_from = pd.to_numeric(row.get("wind_direction_deg"), errors="coerce")
    field_azimuth = pd.to_numeric(row.get("field_azimuth"), errors="coerce")
    if pd.notna(wind_from) and pd.notna(field_azimuth):
        wind_to = (float(wind_from) + 180.0) % 360.0
        difference = (wind_to - float(field_azimuth) + 180.0) % 360.0 - 180.0
        return difference - 90.0

    field_direction = row_text(row, "wind_field_direction").lower()
    if "out" in field_direction:
        return -90
    if "in" in field_direction:
        return 90
    if "r to l" in field_direction:
        return 180
    if "l to r" in field_direction:
        return 0

    arrow = row_text(row, "wind_arrow")
    return {
        "\u2191": -90,
        "\u2197": -45,
        "\u2192": 0,
        "\u2198": 45,
        "\u2193": 90,
        "\u2199": 135,
        "\u2190": 180,
        "\u2196": -135,
    }.get(arrow, 0)


def weather_opposite_cardinal(cardinal):
    directions = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    cardinal = safe_text(cardinal).upper()
    if cardinal not in directions:
        return ""
    return directions[(directions.index(cardinal) + 8) % len(directions)]


def weather_wind_precision_label(row):
    field_direction = row_text(row, "wind_field_direction", default="Direction TBD")
    cardinal = row_text(row, "wind_direction_cardinal")
    opposite = weather_opposite_cardinal(cardinal)
    degrees = pd.to_numeric(row.get("wind_direction_deg"), errors="coerce")
    field_azimuth = pd.to_numeric(row.get("field_azimuth"), errors="coerce")

    parts = [field_direction]
    if cardinal and opposite:
        parts.append(f"{cardinal} \u2192 {opposite}")
    if pd.notna(degrees):
        wind_to = (float(degrees) + 180.0) % 360.0
        parts.append(f"from {int(round(float(degrees))) % 360}\u00b0")
        parts.append(f"toward {int(round(wind_to)) % 360}\u00b0")
        if pd.notna(field_azimuth):
            field_delta = (wind_to - float(field_azimuth) + 180.0) % 360.0 - 180.0
            parts.append(f"field {field_delta:+.0f}\u00b0")
    return " \u00b7 ".join(parts)


def weather_edge_class(edge):
    edge_text = safe_text(edge).lower()
    if "hitter" in edge_text:
        return "hitter"
    if "pitcher" in edge_text:
        return "pitcher"
    if "roof" in edge_text:
        return "roof"
    if "indoor" in edge_text:
        return "indoor"
    return "neutral"


def weather_game_time_html(row):
    game_time_utc = row_text(row, "game_time_utc")
    fallback = row_text(row, "game_time_local", default=row_text(row, "game_time", default="TBD"))
    if game_time_utc:
        return f'<span data-game-time-utc="{escape(game_time_utc, quote=True)}">{escape(fallback)}</span>'
    return escape(fallback)


def weather_abs_number_text(value, suffix="", decimals=0, default="N/A"):
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return f"{abs(float(number)):.{decimals}f}{suffix}"


def weather_out_stat_label(row):
    out_component = pd.to_numeric(row.get("wind_out_mph"), errors="coerce")
    if pd.notna(out_component) and float(out_component) < 0:
        return "IN FROM CF"
    return "OUT TO CF"


def weather_edge_badge_text(row):
    adjustment = pd.to_numeric(row.get("hitter_weather_adjustment"), errors="coerce")
    adjustment_text = f"{float(adjustment):+.0f}% edge" if pd.notna(adjustment) else "edge N/A"
    label = row_text(row, "weather_edge", default="Neutral").upper()
    return label, adjustment_text


def weather_wind_flow_angle(row):
    wind_from = pd.to_numeric(row.get("wind_direction_deg"), errors="coerce")
    if pd.notna(wind_from):
        wind_to = (float(wind_from) + 180.0) % 360.0
        # Base trail artwork flows southwest to northeast.
        base_svg_angle = -35.0
        svg_angle = wind_to - 90.0
        return svg_angle - base_svg_angle

    cardinal = row_text(row, "wind_direction_cardinal").upper()
    cardinal_to_degrees = {
        "N": 0,
        "NNE": 22.5,
        "NE": 45,
        "ENE": 67.5,
        "E": 90,
        "ESE": 112.5,
        "SE": 135,
        "SSE": 157.5,
        "S": 180,
        "SSW": 202.5,
        "SW": 225,
        "WSW": 247.5,
        "W": 270,
        "WNW": 292.5,
        "NW": 315,
        "NNW": 337.5,
    }
    if cardinal in cardinal_to_degrees:
        wind_to = (cardinal_to_degrees[cardinal] + 180.0) % 360.0
        return (wind_to - 90.0) - (-35.0)

    return weather_wind_angle(row)


def WeatherFieldAnimation(row):
    wind_speed = pd.to_numeric(row.get("wind_speed_mph"), errors="coerce")
    wind_speed_value = float(wind_speed) if pd.notna(wind_speed) else 0.0
    angle = weather_wind_flow_angle(row)
    duration = max(7.4, 10.2 - min(wind_speed_value, 22.0) * 0.07)
    (
        wall_path,
        left_line_x,
        left_line_y,
        right_line_x,
        right_line_y,
        dimension_labels,
    ) = live_field_wall_geometry(row)
    home_x, home_y, infield_path, home_plate_path, _mound_x, _mound_y = live_field_infield_geometry()
    base_shapes = live_field_base_shapes()
    clip_id = "weather-field-grass-" + safe_text(row.get("game_pk"), default="game").replace("-", "")
    wind_gradient_id = f"{clip_id}-wind-gradient"
    streams = []
    for index, (x, y, length, rise, curve, delay, width, opacity) in enumerate(
        [
            (18, 212, 204, -160, -26, 0.0, 1.5, 0.34),
            (10, 146, 214, -84, 34, 2.1, 1.34, 0.31),
            (52, 80, 164, -48, -14, 4.2, 1.18, 0.27),
        ]
    ):
        first_control_x = x + (length * 0.30)
        first_control_y = y + (rise * 0.18) + curve
        second_control_x = x + (length * 0.68)
        second_control_y = y + (rise * 0.84) - (curve * 0.42)
        end_x = x + length
        end_y = y + rise
        stream_path = (
            f"M {x:.1f} {y:.1f} "
            f"C {first_control_x:.1f} {first_control_y:.1f} "
            f"{second_control_x:.1f} {second_control_y:.1f} "
            f"{end_x:.1f} {end_y:.1f}"
        )
        gusts = []
        for gust_index, (position, vertical_shift, scale) in enumerate(
            ((0.42, -5, 1.0), (0.68, 5, 0.82))
        ):
            inverse = 1 - position
            gust_x = (
                (inverse ** 3) * x
                + 3 * (inverse ** 2) * position * first_control_x
                + 3 * inverse * (position ** 2) * second_control_x
                + (position ** 3) * end_x
            )
            gust_y = (
                (inverse ** 3) * y
                + 3 * (inverse ** 2) * position * first_control_y
                + 3 * inverse * (position ** 2) * second_control_y
                + (position ** 3) * end_y
                + vertical_shift
            )
            gust_width = 27 * scale
            gust_height = 6.5 * scale
            gust_alpha = max(0.16, opacity - 0.08 - gust_index * 0.035)
            gusts.append(
                f'<path class="weather-wind-gust" '
                f'd="M {gust_x - gust_width * 0.55:.1f} {gust_y + gust_height * 0.22:.1f} '
                f'C {gust_x - gust_width * 0.20:.1f} {gust_y - gust_height * 0.78:.1f} '
                f'{gust_x + gust_width * 0.40:.1f} {gust_y - gust_height * 0.70:.1f} '
                f'{gust_x + gust_width * 0.62:.1f} {gust_y - gust_height * 0.08:.1f} '
                f'C {gust_x + gust_width * 0.23:.1f} {gust_y + gust_height * 0.62:.1f} '
                f'{gust_x - gust_width * 0.16:.1f} {gust_y + gust_height * 0.62:.1f} '
                f'{gust_x - gust_width * 0.55:.1f} {gust_y + gust_height * 0.22:.1f} Z" '
                f'style="--gust-alpha:{gust_alpha:.2f}"/>'
            )
        streams.append(
            '<g class="weather-wind-stream" '
            f'style="--wind-delay:-{delay:.1f}s;--wind-width:{width};--wind-alpha:{opacity}">'
            f'<path class="weather-wind-ribbon" d="{stream_path}" stroke="url(#{wind_gradient_id})"/>'
            f'<path class="weather-wind-core" d="{stream_path}"/>'
            f'{"".join(gusts)}'
            "</g>"
        )
    return (
        f'<svg class="live-field-svg weather-field-svg" viewBox="0 0 250 225" role="img" '
        f'aria-label="Weather wind flow over ballpark" style="--wind-angle:{angle:.1f}deg;--wind-duration:{duration:.2f}s">'
        f'<defs><clipPath id="{clip_id}"><path d="{wall_path}"/></clipPath>'
        f'<linearGradient id="{wind_gradient_id}" x1="0%" y1="100%" x2="100%" y2="0%">'
        '<stop offset="0%" stop-color="#426c8f" stop-opacity="0"/>'
        '<stop offset="45%" stop-color="#426c8f" stop-opacity="0.34"/>'
        '<stop offset="100%" stop-color="#426c8f" stop-opacity="0.06"/>'
        "</linearGradient></defs>"
        f'<g clip-path="url(#{clip_id})">'
        '<rect class="field-grass" x="0" y="0" width="250" height="225"/>'
        + "".join(
            f'<rect class="field-stripe" x="{x}" y="0" width="15" height="225"/>'
            for x in range(20, 230, 30)
        )
        + "</g>"
        f'<path class="field-shape" d="{wall_path}"/>'
        f'<path class="field-foul-line" d="M {home_x} {home_y + 5} '
        f'L {left_line_x} {left_line_y:.1f} M {home_x} {home_y + 5} '
        f'L {right_line_x} {right_line_y:.1f}"/>'
        f'<path class="field-infield" d="{infield_path}"/>'
        f'<path class="field-home-plate" d="{home_plate_path}"/>'
        f'{"".join(base_shapes)}'
        f'{"".join(dimension_labels)}'
        '<g class="weather-wind-layer">'
        f'{"".join(streams)}'
        "</g>"
        "</svg>"
    )


def WeatherGameCard(row):
    away_team = row_text(row, "away_team", default="Away")
    home_team = row_text(row, "home_team", default="Home")
    venue = row_text(row, "venue_name", default="Ballpark TBD")
    game_pk = row.get("game_pk")
    game_payload = {}
    if not is_missing_value(game_pk):
        game_payload = {"game_pk": int(game_pk)}
    event_payload = json.dumps(game_payload, separators=(",", ":"))
    game_href = (
        f"?view=Games&game_pk={int(game_pk)}"
        if not is_missing_value(game_pk)
        else "#"
    )
    weather_icon = weather_icon_svg(row.get("weather_icon"), size=18)
    weather_condition = row_text(row, "weather_condition", default="Forecast")
    weather_edge = row_text(row, "weather_edge", default="Neutral")
    temp_text = weather_number_text(row.get("temperature_f"), "\u00b0", decimals=0)
    humidity_text = weather_number_text(row.get("humidity_pct"), "%", decimals=0)
    rain_text = weather_number_text(row.get("precip_probability_pct"), "%", decimals=0)
    wind_speed_text = weather_number_text(row.get("wind_speed_mph"), " mph", decimals=0)
    wind_gust_text = weather_number_text(row.get("wind_gust_mph"), " mph", decimals=0)
    wind_field = row_text(row, "wind_field_direction", default="Direction TBD")
    out_label = weather_out_stat_label(row)
    wind_out_text = weather_abs_number_text(row.get("wind_out_mph"), " mph", decimals=0)
    wind_cross_text = weather_abs_number_text(row.get("wind_cross_mph"), " mph", decimals=1)
    air_density_text = weather_number_text(row.get("air_density_kg_m3"), " kg/m\u00b3", decimals=2, default="N/A")
    edge_class = weather_edge_class(weather_edge)
    edge_label, edge_adjustment = weather_edge_badge_text(row)
    roof_badge = (
        '<span class="weather-field-badge roof">Retractable roof</span>'
        if is_retractable_roof(row)
        else ""
    )
    return (
        '<a class="weather-game-card" target="_top" '
        f'href="{escape(game_href, quote=True)}" '
        f'data-research-event="{escape(event_payload, quote=True)}">'
        '<div class="weather-game-header">'
        '<div class="weather-matchup-block">'
        '<div class="weather-matchup-line">'
        f'{team_logo_img_html(away_team, alt=away_team, class_name="weather-team-logo")}'
        f'<strong>{escape(display_team_code(row, "away"))}</strong>'
        '<span>@</span>'
        f'{team_logo_img_html(home_team, alt=home_team, class_name="weather-team-logo")}'
        f'<strong>{escape(display_team_code(row, "home"))}</strong>'
        '</div>'
        f'<span>{escape(venue)}</span>'
        '</div>'
        '<div class="weather-summary-block">'
        f'<strong>{weather_icon}<span>{escape(temp_text)} {escape(weather_condition)}</span></strong>'
        f'<span>{weather_game_time_html(row)}</span>'
        '</div>'
        '</div>'
        '<div class="weather-edge-row">'
        f'<span class="weather-edge-pill {escape(edge_class)}">'
        f'<strong>{escape(edge_label)}</strong><em>{escape(edge_adjustment)}</em></span>'
        f'{roof_badge}'
        '</div>'
        '<div class="weather-stat-rail">'
        f'<span><em>{escape(out_label)}</em><strong>{escape(wind_out_text)}</strong></span>'
        f'<span><em>CROSS</em><strong>{escape(wind_cross_text)}</strong></span>'
        f'<span><em>AIR DENSITY</em><strong>{escape(air_density_text)}</strong></span>'
        '</div>'
        '<div class="weather-field-panel">'
        '<div class="weather-field-stage">'
        f"{WeatherFieldAnimation(row)}"
        '</div>'
        '</div>'
        '<div class="weather-bottom-grid">'
        f'<div><span>Wind</span><strong>{escape(wind_speed_text)} {escape(wind_field.lower())}</strong></div>'
        f'<div><span>Gust</span><strong>{escape(wind_gust_text)}</strong></div>'
        f'<div><span>Humidity</span><strong>{escape(humidity_text)}</strong></div>'
        f'<div><span>Rain</span><strong>{escape(rain_text)}</strong></div>'
        "</div>"
        "</a>"
    )


def render_weather_tab(schedule_df, selected_date):
    if schedule_df.empty:
        st.info("No weather games are available for this date.")
        return

    summary = f"{len(schedule_df)} games on {format_display_date(selected_date)}"
    weather_style_html = """
        <style>
            .weather-dashboard-shell {
                background: transparent;
            }
            .weather-slate-summary {
                margin: -2px 0 10px;
                color: #647184;
                font-family: "Source Sans 3", "Source Sans Pro", sans-serif;
                font-size: 12px;
                font-weight: 800;
                letter-spacing: 0.04em;
                text-transform: none;
            }
            .weather-dashboard-grid {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                grid-auto-rows: 1fr;
                gap: 12px;
            }
            .weather-game-card {
                display: flex;
                height: 426px;
                min-height: 426px;
                flex-direction: column;
                border: 1px solid var(--line);
                background: #ffffff;
                padding: 12px;
                overflow: hidden;
                color: inherit;
                cursor: pointer;
                font: inherit;
                text-align: left;
                text-decoration: none;
                width: 100%;
            }
            .weather-game-card:hover,
            .weather-game-card:focus-visible {
                border-color: #8fb4d6;
                background: #fbfdff;
                outline: none;
            }
            .weather-game-top {
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: 10px;
                padding-bottom: 8px;
                border-bottom: 1px solid #e1e6ec;
            }
            .weather-team-block {
                display: grid;
                gap: 6px;
            }
            .weather-teams {
                display: inline-grid;
                grid-template-columns: 26px auto 13px 26px auto;
                align-items: center;
                gap: 6px;
                color: #0b2a4a;
                font-size: 15px;
                font-weight: 900;
            }
            .weather-teams img {
                width: 26px;
                height: 26px;
                object-fit: contain;
            }
            .weather-teams b {
                color: #87919c;
                font-size: 10px;
            }
            .weather-forecast-line {
                text-align: right;
                color: #10243b;
                font-size: 12px;
                line-height: 1.25;
            }
            .weather-forecast-line strong,
            .weather-forecast-line span {
                display: block;
            }
            .weather-forecast-line strong {
                display: inline-flex;
                align-items: center;
                justify-content: flex-end;
                gap: 5px;
                color: #10243b;
                font-size: 18px;
                font-weight: 900;
            }
            .weather-forecast-line span {
                margin-top: 4px;
                color: #647184;
                font-size: 11px;
            }
            .weather-roof-alert {
                display: inline-flex;
                width: fit-content;
                margin-top: 7px;
                padding: 2px 6px;
                border: 1px solid #d7b65a;
                background: #fff8e6;
                color: #493b17;
                font-size: 9px;
                font-weight: 900;
                text-transform: uppercase;
                letter-spacing: 0.06em;
            }
            .weather-svg {
                width: 18px;
                height: 18px;
                flex: 0 0 auto;
            }
            .weather-field-panel {
                position: relative;
                margin-top: 10px;
                border: 1px solid #d8dee6;
                background: #f5f8fb;
            }
            .weather-field-svg {
                display: block;
                width: 100%;
                height: auto;
                min-height: 202px;
                max-height: 202px;
                background: #f8fafc;
            }
            .live-field-svg {
                display: block;
                width: 100%;
                min-height: 202px;
                background: #f5f8fb;
            }
            .weather-wind-layer {
                transform-box: view-box;
                transform-origin: 125px 112px;
                transform: rotate(var(--wind-angle, 0deg));
                pointer-events: none;
            }
            .weather-wind-band {
                stroke: #4f6f8b;
                stroke-width: var(--wind-width, 2.2);
                stroke-linecap: round;
                fill: none;
                opacity: var(--wind-alpha, 0.5);
                stroke-dasharray: 8 10;
                animation: weatherWindFlow var(--wind-duration, 2.6s) linear infinite;
                animation-delay: var(--wind-delay, 0s);
            }
            .weather-wind-arrowhead {
                fill: #4f6f8b;
            }
            .field-shape {
                fill: none;
                stroke: #62758b;
                stroke-width: 1.4;
            }
            .field-grass {
                fill: #dbe8d0;
            }
            .field-stripe {
                fill: #cddfc2;
                opacity: 0.72;
            }
            .field-infield {
                fill: #e8bf66;
                fill-opacity: 0.58;
                stroke: none;
            }
            .field-foul-line {
                fill: none;
                stroke: #7f8fa2;
                stroke-width: 0.9;
                stroke-opacity: 0.72;
                stroke-linecap: round;
            }
            .field-home-plate,
            .field-base {
                fill: #ffffff;
                stroke: #ffffff;
                stroke-width: 1.5;
                filter: drop-shadow(0 1px 1px rgba(15, 31, 48, 0.16));
            }
            .weather-card-footer {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                align-items: center;
                gap: 5px 10px;
                margin-top: auto;
                padding-top: 9px;
                color: #647184;
                font-size: 10px;
                font-weight: 700;
            }
            .weather-card-footer span {
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .weather-card-footer strong {
                color: #10243b;
                font-weight: 900;
            }
            .weather-venue-under {
                padding: 6px 6px 0;
                color: #10243b;
                font-size: 12px;
                font-weight: 900;
                text-align: center;
            }
            .weather-field-overlay {
                position: absolute;
                right: 8px;
                bottom: 8px;
                left: 8px;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 8px;
                pointer-events: none;
            }
            .weather-field-stats {
                position: absolute;
                top: 8px;
                left: 8px;
                display: flex;
                max-width: calc(100% - 16px);
                gap: 6px;
                pointer-events: none;
            }
            .weather-field-stats span {
                display: inline-flex;
                align-items: center;
                gap: 4px;
                min-height: 21px;
                padding: 3px 6px;
                border: 1px solid rgba(98, 117, 139, 0.28);
                background: rgba(255, 255, 255, 0.88);
                color: #647184;
                font-size: 8px;
                font-weight: 900;
                letter-spacing: 0.06em;
                text-transform: uppercase;
            }
            .weather-field-stats strong {
                color: #10243b;
                font-size: 9px;
                letter-spacing: 0;
                text-transform: none;
                white-space: nowrap;
            }
            .weather-field-badge {
                display: inline-flex;
                min-height: 22px;
                align-items: center;
                padding: 3px 7px;
                border: 1px solid #d7b65a;
                background: #fff8e6;
                color: #664b12;
                font-size: 9px;
                font-weight: 900;
                letter-spacing: 0.06em;
                text-transform: uppercase;
            }
            .weather-edge-pill {
                display: inline-flex;
                align-items: center;
                min-height: 22px;
                padding: 3px 8px;
                border: 1px solid #d4dce6;
                background: #f7fafc;
                color: #10243b;
                font-size: 10px;
                font-weight: 900;
                letter-spacing: 0.04em;
                text-transform: uppercase;
            }
            .weather-edge-pill.hitter {
                border-color: #b7dbc8;
                background: #edf8f1;
                color: #176338;
            }
            .weather-edge-pill.pitcher {
                border-color: #b8cde4;
                background: #edf4fb;
                color: #173f67;
            }
            .weather-edge-pill.roof,
            .weather-edge-pill.indoor {
                border-color: #d7b65a;
                background: #fff8e6;
                color: #664b12;
            }
            .weather-game-card {
                height: 452px;
                min-height: 452px;
                gap: 8px;
                border: 1px solid #d8dee6;
                background: #ffffff;
                padding: 12px;
            }
            .weather-game-card:hover,
            .weather-game-card:focus-visible {
                border-color: #aebdca;
                background: #fcfdff;
                box-shadow: inset 0 0 0 1px rgba(23, 63, 103, 0.04);
            }
            .weather-game-header {
                display: grid;
                grid-template-columns: minmax(0, 1fr) auto;
                align-items: start;
                gap: 12px;
                padding-bottom: 5px;
                border-bottom: 1px solid #e6ebf0;
            }
            .weather-matchup-block {
                display: grid;
                gap: 2px;
                min-width: 0;
            }
            .weather-matchup-line {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                min-width: 0;
                color: #06172b;
                line-height: 1;
            }
            .weather-team-logo {
                width: 25px;
                height: 25px;
                flex: 0 0 auto;
                object-fit: contain;
            }
            .weather-matchup-line strong {
                color: #06172b;
                font-size: 18px;
                font-weight: 950;
                letter-spacing: 0.01em;
                line-height: 1;
                white-space: nowrap;
            }
            .weather-matchup-line span {
                color: #647184;
                font-size: 12px;
                font-weight: 950;
                line-height: 1;
                white-space: nowrap;
            }
            .weather-matchup-block > span {
                overflow: hidden;
                color: #647184;
                font-size: 11px;
                font-weight: 800;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .weather-summary-block {
                display: grid;
                justify-items: end;
                gap: 2px;
                color: #10243b;
                text-align: right;
                white-space: nowrap;
            }
            .weather-summary-block strong {
                display: inline-flex;
                align-items: center;
                justify-content: flex-end;
                gap: 5px;
                color: #10243b;
                font-size: 15px;
                font-weight: 950;
                line-height: 1.1;
            }
            .weather-summary-block span {
                color: #647184;
                font-size: 11px;
                font-weight: 800;
            }
            .weather-edge-row {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 8px;
                min-height: 27px;
            }
            .weather-edge-pill {
                gap: 7px;
                min-height: 24px;
                padding: 3px 8px;
                border-radius: 999px;
                font-size: 9px;
                letter-spacing: 0.055em;
            }
            .weather-edge-pill strong,
            .weather-edge-pill em {
                font-style: normal;
                line-height: 1;
                white-space: nowrap;
            }
            .weather-edge-pill em {
                color: inherit;
                font-size: 10px;
                font-weight: 950;
                letter-spacing: 0;
                text-transform: none;
            }
            .weather-edge-pill.hitter {
                border-color: #b9dfca;
                background: #edf8f1;
                color: #176338;
            }
            .weather-field-badge {
                min-height: 22px;
                padding: 3px 7px;
                border-radius: 999px;
                font-size: 8px;
            }
            .weather-stat-rail {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 9px;
                padding: 3px 0 1px;
            }
            .weather-stat-rail span {
                display: grid;
                gap: 1px;
                min-width: 0;
            }
            .weather-stat-rail em {
                overflow: hidden;
                color: #7b8794;
                font-size: 8px;
                font-style: normal;
                font-weight: 950;
                letter-spacing: 0.07em;
                text-overflow: ellipsis;
                text-transform: uppercase;
                white-space: nowrap;
            }
            .weather-stat-rail strong {
                color: #06172b;
                font-size: 12px;
                font-weight: 950;
                font-variant-numeric: tabular-nums;
                white-space: nowrap;
            }
            .weather-field-panel {
                display: flex;
                justify-content: center;
                margin-top: 0;
                border: 0;
                background: #f4f7fa;
                overflow: hidden;
            }
            .weather-field-stage {
                width: min(100%, 275px);
                padding: 4px 8px 6px;
            }
            .weather-field-svg,
            .live-field-svg.weather-field-svg {
                width: 100%;
                min-height: 0;
                max-height: none;
                aspect-ratio: 250 / 225;
                border: 0;
                background: transparent;
                box-shadow: none;
                outline: 0;
            }
            .weather-field-panel .field-shape {
                fill: none;
                stroke: #526171;
                stroke-width: 1.15;
            }
            .weather-field-panel .field-grass {
                fill: #dce8d6;
            }
            .weather-field-panel .field-stripe {
                fill: #cfe1c7;
                opacity: 0.48;
            }
            .weather-field-panel .field-infield {
                fill: #e9c875;
                fill-opacity: 0.52;
            }
            .weather-field-panel .field-foul-line {
                stroke: #74859a;
                stroke-width: 0.75;
                stroke-opacity: 0.62;
            }
            .weather-field-panel .field-dimension {
                fill: #516275;
                font-size: 6.2px;
                font-weight: 900;
                opacity: 0.9;
            }
            .weather-wind-layer {
                transform-box: view-box;
                transform-origin: 125px 112px;
                transform: rotate(var(--wind-angle, 0deg));
                pointer-events: none;
            }
            .weather-wind-stream {
                transform-box: view-box;
                transform-origin: center;
                animation: weatherWindFlow var(--wind-duration, 8.8s) ease-in-out infinite;
                animation-delay: var(--wind-delay, 0s);
            }
            .weather-wind-ribbon {
                fill: none;
                stroke-width: 8.5;
                stroke-linecap: round;
                stroke-linejoin: round;
                opacity: 0.74;
                vector-effect: non-scaling-stroke;
            }
            .weather-wind-core {
                fill: none;
                stroke: #315f86;
                stroke-width: var(--wind-width, 1.35);
                stroke-linecap: round;
                stroke-linejoin: round;
                opacity: var(--wind-alpha, 0.3);
                vector-effect: non-scaling-stroke;
            }
            .weather-wind-gust {
                fill: #315f86;
                opacity: var(--gust-alpha, 0.22);
            }
            .weather-bottom-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 5px 12px;
                margin-top: auto;
                padding-top: 2px;
            }
            .weather-bottom-grid div {
                display: grid;
                grid-template-columns: 58px minmax(0, 1fr);
                align-items: baseline;
                gap: 7px;
                min-width: 0;
            }
            .weather-bottom-grid span {
                color: #7b8794;
                font-size: 10px;
                font-weight: 900;
            }
            .weather-bottom-grid strong {
                overflow: hidden;
                color: #06172b;
                font-size: 11px;
                font-weight: 900;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            @keyframes weatherWindFlow {
                0% { opacity: 0.86; transform: translate(0, 0) scale(1); }
                35% { opacity: 1; transform: translate(4px, -3px) scale(1.003); }
                70% { opacity: 0.9; transform: translate(7px, -5px) scale(1.006); }
                100% { opacity: 0.86; transform: translate(0, 0) scale(1); }
            }
            @media (max-width: 1120px) {
                .weather-dashboard-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            }
            @media (max-width: 720px) {
                .weather-dashboard-grid { grid-template-columns: 1fr; }
                .weather-game-card {
                    height: auto;
                    min-height: 0;
                }
                .weather-game-header {
                    grid-template-columns: 1fr;
                }
                .weather-summary-block {
                    justify-items: start;
                    text-align: left;
                }
                .weather-bottom-grid {
                    grid-template-columns: 1fr;
                }
            }
        </style>
    """
    weather_cards_html = "".join(
        WeatherGameCard(row) for _, row in schedule_df.reset_index(drop=True).iterrows()
    )
    st.markdown(
        weather_style_html
        + f"""
        <div class="weather-dashboard-shell">
        <div class="weather-slate-summary">{escape(summary)}</div>
        <div class="weather-dashboard-grid">
            {weather_cards_html}
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def selected_game_from_schedule_event(table_key, event, target_view=None):
    event_key = f"{table_key}_processed_event"
    if not isinstance(event, dict) or event.get("type") != "select_player":
        return False

    event_id = safe_text(event.get("event_id"))
    payload = event.get("payload")
    if (
        not event_id
        or event_id == st.session_state.get(event_key)
        or not isinstance(payload, dict)
    ):
        return False

    game_pk = payload.get("game_pk")
    if is_missing_value(game_pk):
        return False

    st.session_state[event_key] = event_id
    st.session_state.selected_boxscore_game_pk = int(game_pk)
    st.query_params["game_pk"] = str(int(game_pk))
    st.query_params.pop("play_index", None)
    if target_view:
        st.session_state.pending_active_view = target_view
        st.session_state.active_view = target_view
        st.query_params["view"] = target_view
    return True


def render_live_schedule_table(df):
    if df.empty:
        st.info("No games are available for this selection.")
        return

    rows = []
    for row_index, row in df.reset_index(drop=True).iterrows():
        game_pk = row.get("game_pk")
        if is_missing_value(game_pk):
            continue

        away_team = row_text(row, "away_team")
        home_team = row_text(row, "home_team")
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
        game_href = f"?view=Games&game_pk={int(game_pk)}"
        situation_html = schedule_situation_html(row)
        rows.append(
            f"""
            <div class="schedule-weather-row clean-schedule-row">
                <div>
                    <a class="schedule-game-button" target="_top"
                       href="{escape(game_href, quote=True)}"
                       data-research-event="{escape(game_payload, quote=True)}">
                        <span class="schedule-game-main">
                            <span class="overview-score">
                                {away_logo}
                                <span class="overview-team">{escape(away_code)}</span>
                                <span class="score-number">{escape(score_value(row.get("away_score")))}</span>
                                <span class="schedule-at">@</span>
                                {home_logo}
                                <span class="overview-team">{escape(home_code)}</span>
                                <span class="score-number">{escape(score_value(row.get("home_score")))}</span>
                            </span>
                            {situation_html}
                        </span>
                        {schedule_status_html(row)}
                    </a>
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
                min-height: 78px;
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
                padding: 8px 9px;
                border: 1px solid #d8dee6;
                background: #f8fafc;
                color: inherit;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 10px;
                text-align: left;
                text-decoration: none;
            }}
            .schedule-game-main {{
                display: grid;
                min-width: 0;
                gap: 5px;
            }}
            .schedule-game-button:hover,
            .schedule-game-button:focus-visible {{
                border-color: #8fb4d6;
                background: #f2f7fc;
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
            .schedule-situation-mini {{
                display: inline-flex;
                align-items: center;
                gap: 12px;
                width: fit-content;
                margin-top: 4px;
            }}
            .mini-bases {{
                position: relative;
                width: 44px;
                height: 28px;
                flex: 0 0 44px;
            }}
            .mini-base {{
                position: absolute;
                width: 11px;
                height: 11px;
                border: 1.7px solid #687b91;
                background: #ffffff;
                transform: rotate(45deg);
            }}
            .mini-base.first {{ left: 30px; top: 13px; }}
            .mini-base.second {{ left: 16px; top: 0; }}
            .mini-base.third {{ left: 2px; top: 13px; }}
            .mini-base.occupied {{
                border-color: #173f67;
                background: #245f96;
            }}
            .mini-outs {{
                display: inline-flex;
                align-items: center;
                gap: 3px;
                color: #647184;
                font-size: 9px;
                font-weight: 900;
                letter-spacing: 0.05em;
                text-transform: uppercase;
            }}
            .mini-dot {{
                width: 8px;
                height: 8px;
                border: 1px solid #aab4c0;
                border-radius: 50%;
                background: #ffffff;
            }}
            .mini-dot.out.active {{
                border-color: #173f67;
                background: #173f67;
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
                min-width: 28px;
                padding: 1px 4px;
                border: 0;
                background: transparent;
                color: #06172b;
                text-align: center;
                font-size: 18px;
                font-weight: 800;
                font-variant-numeric: tabular-nums;
            }}
            .score-status {{
                display: inline-flex;
                width: auto;
                margin-top: 0;
                padding: 4px 6px;
                border: 1px solid #d2dae4;
                background: #ffffff;
                color: #526171;
                font-size: 10px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                white-space: nowrap;
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
                align-items: center;
                gap: 7px;
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
                display: inline-grid;
                width: 22px;
                height: 22px;
                place-items: center;
                border: 1px solid #d8dee6;
                border-radius: 50%;
                background: #ffffff;
                color: #245f96;
                font-size: 15px;
                font-weight: 800;
                line-height: 1;
                transform: rotate(var(--wind-angle, 0deg));
                transform-origin: center;
            }}
            .schedule-wind-copy {{
                display: grid;
                gap: 1px;
                line-height: 1.05;
            }}
            .schedule-wind-copy small {{
                color: #647184;
                font-size: 10px;
                font-weight: 750;
                letter-spacing: 0.02em;
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
        table_height=max(150, 42 + (len(rows) * 79)),
        key="live-schedule-table",
        default=None,
    )
    if selected_game_from_schedule_event("live-schedule-table", table_event):
        st.rerun(scope="app")


def batting_order_side_html(boxscore_df, row, side):
    if boxscore_df is None or boxscore_df.empty:
        return ""
    side_df = filter_boxscore_team(boxscore_df, side)
    if side_df.empty or "Lineup" not in side_df.columns:
        return ""
    side_df = side_df.copy()
    side_df["_lineup_sort"] = pd.to_numeric(side_df["Lineup"], errors="coerce")
    side_df = side_df.sort_values(
        ["_lineup_sort", "PA", "Player"],
        ascending=[True, False, True],
        na_position="last",
    ).head(13)
    team_key = "away" if side == "Away" else "home"
    team_name = row_text(row, f"{team_key}_team", default=side)
    team_code = display_team_code(row, team_key)
    rows = []
    for _, player in side_df.iterrows():
        lineup = pd.to_numeric(player.get("Lineup"), errors="coerce")
        slot = f"{int(lineup)}" if pd.notna(lineup) else "-"
        player_name = row_text(player, "Player", default="Unknown")
        team = row_text(player, "Team", default=team_code)
        headshot = image_html(
            player_image_url(player.get("player_id"), width=56),
            f"{player_name} headshot",
            fallback_src=team_logo_fallback_url(team),
            lazy=False,
        )
        rows.append(
            '<div class="batting-order-row">'
            f'<span class="batting-order-slot">{escape(slot)}</span>'
            f"{headshot}"
            f'<span class="batting-order-name">{escape(player_name)}</span>'
            f'<span class="batting-order-pos">{escape(row_text(player, "Pos", default="-"))}</span>'
            "</div>"
        )
    if not rows:
        return ""
    return (
        '<div class="batting-order-team">'
        '<div class="batting-order-team-head">'
        f'{team_logo_img_html(team_name, alt=team_name)}'
        f"<span>{escape(team_code)}</span></div>"
        f'{"".join(rows)}</div>'
    )


def batting_order_game_card(row):
    game_pk = row.get("game_pk")
    if is_missing_value(game_pk):
        return ""
    try:
        boxscore = load_game_boxscore(int(game_pk))
    except Exception:
        return ""
    batting = boxscore.get("batting", pd.DataFrame())
    away_html = batting_order_side_html(batting, row, "Away")
    home_html = batting_order_side_html(batting, row, "Home")
    if not away_html and not home_html:
        return ""
    title = f"{display_team_code(row, 'away')} @ {display_team_code(row, 'home')}"
    return (
        '<div class="batting-order-card">'
        f'<div class="batting-order-title"><strong>{escape(title)}</strong>'
        '<span>Batting Order</span></div>'
        f'<div class="batting-order-team-grid">{away_html}{home_html}</div>'
        "</div>"
    )


def render_main_batting_orders(schedule_df):
    if schedule_df.empty:
        return
    cards = []
    for _, row in schedule_df.reset_index(drop=True).iterrows():
        card = batting_order_game_card(row)
        if card:
            cards.append(card)
    if not cards:
        return
    st.html(f'<div class="batting-order-grid">{"".join(cards)}</div>')


LIVE_PROJECTED_LINEUP_COLUMNS = ["AB", "H", "HR", "AVG", "SLG", "K%"]


def season_batter_lookup(batters_df):
    if batters_df is None or batters_df.empty or "player_id" not in batters_df.columns:
        return {}
    keep_columns = [
        column
        for column in [
            "player_id",
            "Name",
            "Team",
            "AB",
            "H",
            "HR",
            "AVG",
            "SLG",
            "K%",
            "SO",
            "PA",
        ]
        if column in batters_df.columns
    ]
    if not keep_columns:
        return {}
    stats_df = batters_df[keep_columns].copy()
    stats_df["player_id"] = pd.to_numeric(stats_df["player_id"], errors="coerce")
    stats_df = stats_df.dropna(subset=["player_id"]).drop_duplicates(
        subset=["player_id"],
        keep="first",
    )
    return {
        int(row["player_id"]): row
        for _, row in stats_df.iterrows()
    }


def live_lineup_slot(value):
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return "-"
    return str(int(number))


def live_lineup_stat_value(column, stat_row, boxscore_row):
    value = None
    if stat_row is not None:
        if column in stat_row.index:
            value = stat_row.get(column)
        if (
            column == "K%"
            and is_missing_value(value)
            and {"SO", "PA"}.issubset(stat_row.index)
        ):
            strikeouts = pd.to_numeric(stat_row.get("SO"), errors="coerce")
            plate_appearances = pd.to_numeric(stat_row.get("PA"), errors="coerce")
            if pd.notna(strikeouts) and pd.notna(plate_appearances) and plate_appearances:
                value = (float(strikeouts) / float(plate_appearances)) * 100
    if is_missing_value(value) and column in boxscore_row.index:
        value = boxscore_row.get(column)
    text = stats_cell_value(column, value)
    if text == "-":
        return '<span class="live-lineup-stat-muted">-</span>'
    return escape(text)


def live_projected_lineup_side_html(boxscore_df, row, side, batter_stats):
    if boxscore_df is None or boxscore_df.empty:
        return ""
    side_df = filter_boxscore_team(boxscore_df, side)
    if side_df.empty or "Lineup" not in side_df.columns:
        return ""
    side_df = side_df.copy()
    side_df["_lineup_sort"] = pd.to_numeric(side_df["Lineup"], errors="coerce")
    side_df = side_df.sort_values(
        ["_lineup_sort", "PA", "Player"],
        ascending=[True, False, True],
        na_position="last",
    ).head(13)
    team_key = "away" if side == "Away" else "home"
    team_name = row_text(row, f"{team_key}_team", default=side)
    team_code = display_team_code(row, team_key)
    body_rows = []
    for _, player in side_df.iterrows():
        player_id = pd.to_numeric(player.get("player_id"), errors="coerce")
        stat_row = None
        if pd.notna(player_id):
            stat_row = batter_stats.get(int(player_id))
        player_name = row_text(player, "Player", default="Unknown")
        team = row_text(player, "Team", default=team_code)
        headshot = image_html(
            player_image_url(player.get("player_id"), width=56),
            f"{player_name} headshot",
            fallback_src=team_logo_fallback_url(team),
            lazy=False,
        )
        stat_cells = "".join(
            "<td>"
            f"{live_lineup_stat_value(column, stat_row, player)}"
            "</td>"
            for column in LIVE_PROJECTED_LINEUP_COLUMNS
        )
        body_rows.append(
            "<tr>"
            f"<td>{escape(live_lineup_slot(player.get('Lineup')))}</td>"
            '<td class="align-left">'
            '<span class="live-lineup-player">'
            f"{headshot}"
            f"<span>{escape(player_name)}</span>"
            f'<span class="batting-order-pos">{escape(row_text(player, "Pos", default="-"))}</span>'
            "</span></td>"
            f"{stat_cells}"
            "</tr>"
        )
    if not body_rows:
        return ""
    header_cells = "".join(
        f"<th>{escape(column)}</th>"
        for column in ["#", "Batter", *LIVE_PROJECTED_LINEUP_COLUMNS]
    )
    return (
        '<div class="live-lineup-card">'
        '<div class="live-lineup-title">'
        f'{team_logo_img_html(team_name, alt=team_name)}'
        f"<strong>{escape(team_code)}</strong>"
        "<span>Projected Lineup</span>"
        "</div>"
        '<div class="research-table-shell">'
        '<table class="live-lineup-table">'
        f"<thead><tr>{header_cells}</tr></thead>"
        f'<tbody>{"".join(body_rows)}</tbody>'
        "</table></div></div>"
    )


def render_live_projected_lineups(row, game_pk, batters_df):
    try:
        boxscore = load_game_boxscore(int(game_pk))
    except Exception:
        return
    batting_df = boxscore.get("batting", pd.DataFrame())
    batter_stats = season_batter_lookup(batters_df)
    away_html = live_projected_lineup_side_html(
        batting_df,
        row,
        "Away",
        batter_stats,
    )
    home_html = live_projected_lineup_side_html(
        batting_df,
        row,
        "Home",
        batter_stats,
    )
    if not away_html and not home_html:
        return
    st.markdown(
        '<div class="live-lineup-section">'
        '<div class="section-shell game-log-heading">'
        '<div class="section-title">Projected Lineups · Season Stats</div>'
        "</div>"
        f'<div class="live-lineup-grid">{away_html}{home_html}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def boxscore_team_options(row):
    options = []
    for side, label in (("Home", "home"), ("Away", "away")):
        team_name = row_text(row, f"{label}_team", default=side)
        team_code = display_team_code(row, label)
        display = f"{team_name} ({team_code})" if team_code else team_name
        options.append({"label": display, "side": side})
    return options


def filter_boxscore_team(df, selected_side):
    if not selected_side or df.empty or "Side" not in df.columns:
        return df
    return df[df["Side"].astype(str).str.lower() == str(selected_side).lower()].copy()


def render_boxscore_dataframe(
    df,
    stat_columns,
    key,
    player_group,
    season_value,
    game_pk,
):
    if df.empty:
        st.info("No box-score rows are available yet.")
        return None

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
        player = row_text(row, "Player", default="Unknown")
        player_id = row.get("player_id")
        team = row_text(row, "Team")
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
                profile_payload = player_profile_payload(
                    player_id,
                    player,
                    team,
                    player_group,
                    season_value,
                )
                event_payload = json.dumps(
                    profile_payload or {},
                    separators=(",", ":"),
                )
                content = (
                    '<button type="button" class="research-player-link" '
                    f'data-research-event="{escape(event_payload, quote=True)}">'
                    '<span class="research-player-identity">'
                    f"{headshot}<span>{escape(player)}</span></span></button>"
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

    table_event = RESEARCH_TABLE_COMPONENT(
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
    handle_player_profile_event(
        table_event,
        "Games",
        game_pk=game_pk,
    )
    return table_event


def ScoreChangeView(score, score_delta=0):
    changed_class = " score-changed" if score_delta > 0 else ""
    delta_html = (
        f'<span class="live-score-delta">+{int(score_delta)}</span>'
        if score_delta > 0
        else ""
    )
    return (
        '<span class="live-score-wrap">'
        f'<strong class="live-score{changed_class}">'
        f"{escape(score_value(score))}</strong>{delta_html}</span>"
    )


def _count_dot_group(label, kind, active, total):
    active = max(0, min(int(safe_value(active, 0)), total))
    dots = "".join(
        f'<span class="count-dot {kind}{" active" if index < active else ""}"></span>'
        for index in range(total)
    )
    return (
        '<span class="count-dot-group">'
        f'<span class="count-dot-label">{escape(label)}</span>{dots}</span>'
    )


def CountDotsView(balls, strikes):
    return (
        _count_dot_group("Balls", "ball", balls, 3)
        + _count_dot_group("Strikes", "strike", strikes, 2)
    )


def OutsDotsView(outs):
    return _count_dot_group("Outs", "out", outs, 3)


HIT_PLAY_TYPES = {"single", "double", "triple", "home_run"}
OFFENSE_PLAY_TYPES = HIT_PLAY_TYPES | {"walk", "hit_by_pitch", "stolen_base"}
OUT_PLAY_TYPES = {"strikeout", "groundout", "flyout", "popout", "lineout", "forceout", "double_play", "sac_fly"}
FIELD_RESULT_COLORS = {
    "hit": "#187347",
    "out": "#b42318",
    "warning": "#b7791f",
    "neutral": "#6b7888",
}


def play_result_tone(result_type):
    result_type = safe_text(result_type, default="other")
    if result_type in HIT_PLAY_TYPES:
        return "hit"
    if result_type in OUT_PLAY_TYPES:
        return "out"
    if result_type == "error":
        return "warning"
    if result_type in {"walk", "hit_by_pitch", "stolen_base"}:
        return "reach"
    return "neutral"


def field_result_tone(result_type):
    tone = play_result_tone(result_type)
    if tone in {"hit", "reach"}:
        return "hit"
    if tone == "out":
        return "out"
    if tone == "warning":
        return "warning"
    return "neutral"


def field_result_color(result_type):
    return FIELD_RESULT_COLORS.get(
        field_result_tone(result_type),
        FIELD_RESULT_COLORS["neutral"],
    )


def BaseRunnerDiamondView(live_feed):
    bases = live_feed.get("bases") or {}
    base_html = []
    runner_labels = []
    for base in ("first", "second", "third"):
        runner = bases.get(base)
        occupied = " occupied" if runner else ""
        title = (
            safe_text(runner.get("name"), default=f"{base.title()} base occupied")
            if isinstance(runner, dict)
            else f"{base.title()} base empty"
        )
        runner_headshot = (
            image_html(
                runner.get("headshot"),
                f"{title} on {base} base",
                class_name="base-runner-headshot",
                title=title,
                lazy=False,
            )
            if isinstance(runner, dict)
            else ""
        )
        if isinstance(runner, dict):
            runner_labels.append(
                f"<span><strong>{escape(base.title())}:</strong> "
                f"{escape(title)}</span>"
            )
        base_html.append(
            f'<span class="{base}{occupied}" title="{escape(title, quote=True)}">'
            f"{runner_headshot}</span>"
        )
    runner_list = (
        f'<div class="base-runner-list">{"".join(runner_labels)}</div>'
        if runner_labels
        else ""
    )
    return f'<div class="base-diamond">{"".join(base_html)}</div>{runner_list}'


def _live_field_number(value, default):
    number = pd.to_numeric(value, errors="coerce")
    if pd.notna(number):
        return float(number)
    text = safe_text(value)
    if text:
        cleaned = (
            text.replace("feet", "")
            .replace("foot", "")
            .replace("ft", "")
            .replace("'", "")
            .strip()
        )
        number = pd.to_numeric(cleaned, errors="coerce")
        if pd.notna(number):
            return float(number)
    return float(default)


LIVE_FIELD_BASE_COORDS = {
    # Manual tuning guide:
    # x moves left/right, y moves up/down in the SVG viewBox below.
    # Keep home and second on the same x for symmetry.
    "home": (125, 210),
    "first": (158, 177),
    "second": (125, 144),
    "third": (92, 177),
}
LIVE_FIELD_BASE_SIZE = 8
LIVE_FIELD_LOCATION_TARGETS = {
    1: (125, 190),
    2: (125, 210),
    3: (160, 180),
    4: (145, 160),
    5: (90, 180),
    6: (105, 160),
    7: (65, 92),
    8: (125, 60),
    9: (185, 92),
}

VENUE_FIELD_DIMENSIONS = {
    108: {"left_line": 347, "left": 390, "left_center": 396, "center": 396, "right_center": 370, "right": 365, "right_line": 350},
    109: {"left_line": 330, "left": 374, "left_center": 413, "center": 407, "right_center": 374, "right": 374, "right_line": 334},
    110: {"left_line": 333, "left": 384, "left_center": 410, "center": 400, "right_center": 373, "right": 350, "right_line": 318},
    111: {"left_line": 310, "left": 379, "left_center": 390, "center": 420, "right_center": 380, "right": 380, "right_line": 302},
    112: {"left_line": 355, "left": 368, "left_center": 368, "center": 400, "right_center": 368, "right": 368, "right_line": 353},
    113: {"left_line": 328, "left": 379, "left_center": 379, "center": 404, "right_center": 370, "right": 370, "right_line": 325},
    114: {"left_line": 325, "left": 370, "left_center": 370, "center": 400, "right_center": 375, "right": 375, "right_line": 325},
    115: {"left_line": 347, "left": 390, "left_center": 390, "center": 415, "right_center": 375, "right": 375, "right_line": 350},
    116: {"left_line": 345, "left": 370, "left_center": 370, "center": 412, "right_center": 365, "right": 365, "right_line": 330},
    117: {"left_line": 315, "left": 362, "left_center": 404, "center": 409, "right_center": 373, "right": 373, "right_line": 326},
    118: {"left_line": 330, "left": 387, "left_center": 387, "center": 410, "right_center": 387, "right": 387, "right_line": 330},
    119: {"left_line": 330, "left": 375, "left_center": 375, "center": 400, "right_center": 375, "right": 375, "right_line": 330},
    120: {"left_line": 337, "left": 377, "left_center": 377, "center": 402, "right_center": 370, "right": 370, "right_line": 335},
    121: {"left_line": 335, "left": 385, "left_center": 385, "center": 408, "right_center": 375, "right": 375, "right_line": 330},
    133: {"left_line": 330, "left": 388, "left_center": 388, "center": 400, "right_center": 388, "right": 388, "right_line": 330},
    134: {"left_line": 325, "left": 389, "left_center": 389, "center": 399, "right_center": 375, "right": 375, "right_line": 320},
    135: {"left_line": 334, "left": 390, "left_center": 390, "center": 396, "right_center": 391, "right": 391, "right_line": 322},
    136: {"left_line": 331, "left": 378, "left_center": 378, "center": 401, "right_center": 381, "right": 381, "right_line": 326},
    137: {"left_line": 339, "left": 364, "left_center": 399, "center": 391, "right_center": 415, "right": 365, "right_line": 309},
    138: {"left_line": 336, "left": 375, "left_center": 375, "center": 400, "right_center": 375, "right": 375, "right_line": 335},
    139: {"left_line": 315, "left": 370, "left_center": 370, "center": 404, "right_center": 370, "right": 370, "right_line": 322},
    140: {"left_line": 329, "left": 372, "left_center": 372, "center": 407, "right_center": 374, "right": 374, "right_line": 326},
    141: {"left_line": 328, "left": 375, "left_center": 375, "center": 400, "right_center": 375, "right": 375, "right_line": 328},
    142: {"left_line": 339, "left": 377, "left_center": 377, "center": 411, "right_center": 367, "right": 367, "right_line": 328},
    143: {"left_line": 329, "left": 374, "left_center": 374, "center": 401, "right_center": 369, "right": 369, "right_line": 330},
    144: {"left_line": 335, "left": 385, "left_center": 385, "center": 400, "right_center": 375, "right": 375, "right_line": 325},
    145: {"left_line": 330, "left": 375, "left_center": 375, "center": 400, "right_center": 375, "right": 375, "right_line": 335},
    146: {"left_line": 344, "left": 386, "left_center": 386, "center": 407, "right_center": 392, "right": 392, "right_line": 335},
    147: {"left_line": 318, "left": 399, "left_center": 399, "center": 408, "right_center": 385, "right": 385, "right_line": 314},
    158: {"left_line": 344, "left": 371, "left_center": 371, "center": 400, "right_center": 374, "right": 374, "right_line": 345},
}


def contact_play_coordinates(play):
    play = play if isinstance(play, dict) else {}
    hit_data = play.get("hit_data") or {}
    hit_x = pd.to_numeric(hit_data.get("x"), errors="coerce")
    hit_y = pd.to_numeric(hit_data.get("y"), errors="coerce")
    if pd.isna(hit_x) or pd.isna(hit_y):
        hit_x, hit_y = LIVE_FIELD_LOCATION_TARGETS.get(
            int(_live_field_number(hit_data.get("location"), 0)),
            (float("nan"), float("nan")),
        )
    if pd.isna(hit_x) or pd.isna(hit_y):
        return None
    return max(8.0, min(242.0, float(hit_x))), max(18.0, min(208.0, float(hit_y)))


def field_dimensions_from_source(source):
    if source is None or not hasattr(source, "get"):
        source = {}
    dimensions = source.get("field_dimensions")
    if isinstance(dimensions, dict):
        result = dict(dimensions)
    else:
        result = {}
    aliases = {
        "left_line": ("field_left_line", "left_line", "leftLine"),
        "left": ("field_left", "left"),
        "left_center": ("field_left_center", "left_center", "leftCenter"),
        "center": ("field_center", "center"),
        "right_center": ("field_right_center", "right_center", "rightCenter"),
        "right": ("field_right", "right"),
        "right_line": ("field_right_line", "right_line", "rightLine"),
    }
    for key, candidates in aliases.items():
        if not is_missing_value(result.get(key)):
            continue
        for candidate in candidates:
            value = source.get(candidate)
            if not is_missing_value(value):
                result[key] = value
                break

    home_team_id = pd.to_numeric(source.get("home_team_id"), errors="coerce")
    if pd.notna(home_team_id):
        fallback = VENUE_FIELD_DIMENSIONS.get(int(home_team_id), {})
        for key, value in fallback.items():
            if is_missing_value(result.get(key)):
                result[key] = value
    return result


def pitch_marker_tone(pitch):
    pitch = pitch if isinstance(pitch, dict) else {}
    if pitch.get("is_in_play"):
        return "in-play"
    call_text = safe_text(pitch.get("call"), pitch.get("description")).lower()
    if "foul" in call_text:
        count_before = pitch.get("count_before") or {}
        count_after = pitch.get("count_after") or {}
        strikes_before = pd.to_numeric(count_before.get("strikes"), errors="coerce")
        strikes_after = pd.to_numeric(count_after.get("strikes"), errors="coerce")
        is_strikeout_foul = (
            bool(pitch.get("is_out"))
            or "strikeout" in call_text
            or "strike 3" in call_text
        )
        if pd.notna(strikes_before):
            return "strike" if int(strikes_before) < 2 or is_strikeout_foul else "foul"
        first_two_strikes = pd.notna(strikes_after) and int(strikes_after) <= 2
        return "strike" if is_strikeout_foul or first_two_strikes else "foul"
    if pitch.get("is_strike"):
        return "strike"
    if pitch.get("is_ball"):
        return "ball"
    if "strike" in call_text:
        return "strike"
    if "ball" in call_text:
        return "ball"
    if "play" in call_text:
        return "in-play"
    return "unknown"


def pitch_release_offset(live_feed):
    pitcher = (live_feed or {}).get("current_pitcher") or {}
    hand = safe_text(pitcher.get("throwing_hand")).strip().lower()
    if hand.startswith("l"):
        return "-42px"
    if hand.startswith("r"):
        return "42px"
    return "0"


def pitch_zone_fallback_coordinates(zone):
    zone = pd.to_numeric(zone, errors="coerce")
    if pd.isna(zone):
        return None
    zone = int(zone)
    zone_map = {
        1: (-0.48, 3.08),
        2: (0.0, 3.08),
        3: (0.48, 3.08),
        4: (-0.48, 2.5),
        5: (0.0, 2.5),
        6: (0.48, 2.5),
        7: (-0.48, 1.92),
        8: (0.0, 1.92),
        9: (0.48, 1.92),
        11: (-1.08, 3.22),
        12: (1.08, 3.22),
        13: (-1.08, 1.72),
        14: (1.08, 1.72),
    }
    return zone_map.get(zone)


def pitch_zone_svg_coordinates(pitch, zone_top, zone_bottom):
    pitch = pitch if isinstance(pitch, dict) else {}
    p_x = pd.to_numeric(pitch.get("p_x"), errors="coerce")
    p_z = pd.to_numeric(pitch.get("p_z"), errors="coerce")
    if pd.isna(p_x) or pd.isna(p_z):
        fallback = pitch_zone_fallback_coordinates(pitch.get("zone"))
        if fallback is None:
            return None
        p_x, p_z = fallback
    plate_center_x = 85.0
    feet_to_px = 42.0
    zone_center_y = 94.0
    zone_height = 86.0
    zone_mid = (zone_top + zone_bottom) / 2
    zone_span = max(1.0, zone_top - zone_bottom)
    x = plate_center_x + (float(p_x) * feet_to_px)
    y = zone_center_y - (((float(p_z) - zone_mid) / zone_span) * zone_height)
    return max(16.0, min(154.0, x)), max(18.0, min(178.0, y))


def _live_pitch_key(pitch):
    pitch = pitch if isinstance(pitch, dict) else {}
    play_id = pitch.get("play_id")
    event_index = pitch.get("event_index")
    if play_id is not None or event_index is not None:
        return ("pitch", safe_text(play_id), safe_text(event_index))
    return (
        "pitch",
        safe_text(pitch.get("description")),
        safe_text(pitch.get("code")),
        safe_text(pitch.get("pitch_code")),
        safe_text(pitch.get("start_speed")),
        safe_text(pitch.get("p_x")),
        safe_text(pitch.get("p_z")),
    )


def _live_play_key(play):
    play = play if isinstance(play, dict) else {}
    play_index = play.get("play_index")
    if play_index is not None:
        return ("play", safe_text(play_index))
    return (
        "play",
        safe_text(play.get("inning")),
        safe_text(play.get("half_inning")),
        safe_text((play.get("batter") or {}).get("player_id")),
        safe_text(play.get("result_type")),
        safe_text(play.get("description")),
    )


def StrikeZoneView(live_feed, animate_pitch_key=None):
    pitches = [
        pitch
        for pitch in (live_feed.get("current_pitches") or [])
        if isinstance(pitch, dict)
    ][-12:]
    latest_pitch = live_feed.get("latest_pitch") or (pitches[-1] if pitches else {})
    top_values = [
        pd.to_numeric(pitch.get("strike_zone_top"), errors="coerce")
        for pitch in pitches
    ]
    bottom_values = [
        pd.to_numeric(pitch.get("strike_zone_bottom"), errors="coerce")
        for pitch in pitches
    ]
    zone_top = next((float(value) for value in reversed(top_values) if pd.notna(value)), 3.5)
    zone_bottom = next((float(value) for value in reversed(bottom_values) if pd.notna(value)), 1.55)
    zone_x = 50.0
    zone_y = 51.0
    zone_w = 70.0
    zone_h = 86.0
    zone_grid = (
        f'<line class="strike-zone-grid" x1="{zone_x + zone_w / 3:.1f}" y1="{zone_y}" '
        f'x2="{zone_x + zone_w / 3:.1f}" y2="{zone_y + zone_h}"/>'
        f'<line class="strike-zone-grid" x1="{zone_x + (zone_w * 2 / 3):.1f}" y1="{zone_y}" '
        f'x2="{zone_x + (zone_w * 2 / 3):.1f}" y2="{zone_y + zone_h}"/>'
        f'<line class="strike-zone-grid" x1="{zone_x}" y1="{zone_y + zone_h / 3:.1f}" '
        f'x2="{zone_x + zone_w}" y2="{zone_y + zone_h / 3:.1f}"/>'
        f'<line class="strike-zone-grid" x1="{zone_x}" y1="{zone_y + (zone_h * 2 / 3):.1f}" '
        f'x2="{zone_x + zone_w}" y2="{zone_y + (zone_h * 2 / 3):.1f}"/>'
    )
    pitch_markers = []
    release_offset = pitch_release_offset(live_feed)
    for index, pitch in enumerate(pitches, start=1):
        coordinates = pitch_zone_svg_coordinates(pitch, zone_top, zone_bottom)
        if coordinates is None:
            continue
        x, y = coordinates
        tone = pitch_marker_tone(pitch)
        latest_class = " latest" if pitch is latest_pitch or pitch == latest_pitch else ""
        pitch_key = _live_pitch_key(pitch)
        animate_class = (
            " animate"
            if animate_pitch_key is not None and pitch_key == animate_pitch_key
            else ""
        )
        pitch_label = row_text(pitch, "pitch_code", "pitch_type")
        call_label = row_text(pitch, "call", "description", default="Pitch")
        speed = pd.to_numeric(pitch.get("start_speed"), errors="coerce")
        speed_label = f" · {float(speed):.1f} mph" if pd.notna(speed) else ""
        title = f"{index}. {call_label}{speed_label}"
        delay = min(0.18, (index - 1) * 0.018)
        pitch_markers.append(
            f'<g class="strike-zone-pitch-marker{animate_class}" '
            f'style="--pitch-from-x:{release_offset};--pitch-delay:{delay:.3f}s">'
            f'<circle class="strike-zone-pitch {tone}{latest_class}" '
            f'cx="{x:.1f}" cy="{y:.1f}" r="6.1">'
            f"<title>{escape(title)}</title></circle>"
            f'<text class="strike-zone-count-label" x="{x:.1f}" y="{y:.1f}">{index}</text>'
            "</g>"
        )

    latest_call = (
        row_text(latest_pitch, "call", "description", default="No pitch data")
        if isinstance(latest_pitch, dict)
        else " No pitch data"
    )
    latest_type = safe_text(
        latest_pitch.get("pitch_type") if isinstance(latest_pitch, dict) else "",
        default="",
    )
    latest_speed = pd.to_numeric(
        latest_pitch.get("start_speed") if isinstance(latest_pitch, dict) else None,
        errors="coerce",
    )
    latest_meta = []
    if latest_type:
        latest_meta.append(latest_type)
    if pd.notna(latest_speed):
        latest_meta.append(f"{float(latest_speed):.1f} mph")
    return (
        '<div class="strike-zone-card">'
        '<div class="strike-zone-topline"><span></span>'
        '<strong>Strike Zone</strong></div>'
        '<svg class="strike-zone-svg" viewBox="0 0 170 190" '
        'role="img" aria-label="Live strike zone pitch map">'
        '<rect class="strike-zone-box" x="50" y="51" width="70" height="86"/>'
        f"{zone_grid}"
        f'{"".join(pitch_markers)}</svg>'
        '<div class="strike-zone-meta">'
        f"<div><span>Latest</span><strong>{escape(latest_call)}</strong></div>"
        f'<div class="strike-zone-meta-detail">{escape(" · ".join(latest_meta))}</div>'
        "</div></div>"
    )


def live_field_wall_geometry(live_feed):
    dimensions = field_dimensions_from_source(live_feed)
    dimension_specs = (
        ("left_line", 22, 330),
        ("left", 39, 370),
        ("left_center", 76, 390),
        ("center", 125, 400),
        ("right_center", 174, 390),
        ("right", 211, 370),
        ("right_line", 228, 330),
    )
    wall_points = []
    dimension_labels = []
    for key, x, default_distance in dimension_specs:
        distance = _live_field_number(dimensions.get(key), default_distance)
        y = max(24.0, min(82.0, 205.0 - (distance * 0.42)))
        wall_points.append((x, y))
        dimension_labels.append(
            f'<text class="field-dimension" x="{x}" y="{max(12, y - 4):.1f}">'
            f"{int(round(distance))}</text>"
        )

    wall_path = "M 125 218 " + " ".join(
        f"L {x} {y:.1f}" for x, y in wall_points
    ) + " Z"
    left_line_x, left_line_y = wall_points[0]
    right_line_x, right_line_y = wall_points[-1]
    return wall_path, left_line_x, left_line_y, right_line_x, right_line_y, dimension_labels


def live_field_infield_geometry():
    home_x, home_y = LIVE_FIELD_BASE_COORDS["home"]
    first_x, first_y = LIVE_FIELD_BASE_COORDS["first"]
    second_x, second_y = LIVE_FIELD_BASE_COORDS["second"]
    third_x, third_y = LIVE_FIELD_BASE_COORDS["third"]
    infield_path = (
        f"M {home_x} {home_y} L {first_x} {first_y} "
        f"L {second_x} {second_y} L {third_x} {third_y} Z"
    )
    home_plate_path = (
        f"M {home_x - 5} {home_y - 2} L {home_x + 5} {home_y - 2} "
        f"L {home_x + 4} {home_y + 3} L {home_x} {home_y + 6} "
        f"L {home_x - 4} {home_y + 3} Z"
    )
    mound_x = (home_x + second_x) / 2
    mound_y = (home_y + second_y) / 2
    return home_x, home_y, infield_path, home_plate_path, mound_x, mound_y


def live_field_base_shape(base, x, y, occupied=False):
    occupied_class = " occupied" if occupied else ""
    half_base = LIVE_FIELD_BASE_SIZE / 2
    return (
        f'<rect class="field-base{occupied_class}" x="{x - half_base}" '
        f'y="{y - half_base}" width="{LIVE_FIELD_BASE_SIZE}" '
        f'height="{LIVE_FIELD_BASE_SIZE}" transform="rotate(45 {x} {y})"/>'
    )


def live_field_base_shapes(bases=None):
    bases = bases if isinstance(bases, dict) else {}
    return [
        live_field_base_shape(base, x, y, occupied=isinstance(bases.get(base), dict))
        for base, (x, y) in LIVE_FIELD_BASE_COORDS.items()
        if base != "home"
    ]


def live_field_grass_layer(wall_path, clip_id):
    stripes = "".join(
        f'<rect class="field-stripe" x="{x}" y="0" width="15" height="225"/>'
        for x in range(20, 230, 30)
    )
    return (
        f'<defs><clipPath id="{clip_id}"><path d="{wall_path}"/></clipPath></defs>'
        f'<g clip-path="url(#{clip_id})">'
        '<rect class="field-grass" x="0" y="0" width="250" height="225"/>'
        f"{stripes}</g>"
    )


def LiveFieldView(live_feed, animate_contact_key=None):
    (
        wall_path,
        left_line_x,
        left_line_y,
        right_line_x,
        right_line_y,
        dimension_labels,
    ) = live_field_wall_geometry(live_feed)

    home_x, home_y, infield_path, home_plate_path, _mound_x, _mound_y = live_field_infield_geometry()
    base_positions = {
        base: coords
        for base, coords in LIVE_FIELD_BASE_COORDS.items()
        if base != "home"
    }
    bases = live_feed.get("bases") or {}
    base_shapes = []
    runner_defs = []
    runner_shapes = []
    for base, (x, y) in base_positions.items():
        runner = bases.get(base)
        occupied = isinstance(runner, dict)
        base_shapes.append(live_field_base_shape(base, x, y, occupied=occupied))
        if not occupied:
            continue
        runner_name = safe_text(
            runner.get("name"),
            default=f"Runner on {base}",
        )
        headshot = safe_text(runner.get("headshot"))
        runner_defs.append(
            f'<clipPath id="runner-clip-{base}">'
            f'<circle cx="{x}" cy="{y}" r="10"/></clipPath>'
        )
        if headshot:
            runner_shapes.append(
                f'<circle class="field-runner-ring" cx="{x}" cy="{y}" r="11"/>'
                f'<image href="{escape(headshot, quote=True)}" '
                f'x="{x - 10}" y="{y - 10}" width="20" height="20" '
                f'preserveAspectRatio="xMidYMid slice" '
                f'clip-path="url(#runner-clip-{base})">'
                f"<title>{escape(runner_name)}</title></image>"
            )
        else:
            runner_shapes.append(
                f'<circle class="field-runner-ring" cx="{x}" cy="{y}" r="8">'
                f"<title>{escape(runner_name)}</title></circle>"
            )

    latest_play = live_feed.get("latest_batted_ball") or {}
    hit_data = latest_play.get("hit_data") or {}
    hit_coordinates = contact_play_coordinates(latest_play)

    trajectory_html = ""
    footer_label = ""
    footer_meta = ""
    if hit_coordinates is not None:
        hit_x, hit_y = hit_coordinates
        control_x = home_x + ((hit_x - home_x) * 0.46)
        control_y = max(24.0, ((home_y + hit_y) / 2) - 19)
        result_type = safe_text(
            latest_play.get("result_type"),
            default="other",
        )
        result_label = safe_text(
            latest_play.get("result_label"),
            default="Ball in play",
        )
        batter_name = safe_text(
            (latest_play.get("batter") or {}).get("name"),
            default="Batter",
        )
        description = safe_text(
            latest_play.get("description"),
            default=result_label,
        )
        tone_class = field_result_tone(result_type)
        home_run_class = " home-run" if result_type == "home_run" else ""
        contact_key = _contact_play_key(latest_play)
        animate_class = (
            " animate"
            if animate_contact_key is not None and contact_key == animate_contact_key
            else ""
        )
        path_data = (
            f"M {home_x} {home_y} Q {control_x:.1f} {control_y:.1f} "
            f"{hit_x:.1f} {hit_y:.1f}"
        )
        trajectory_html = (
            f'<path class="field-trajectory {tone_class}{home_run_class}{animate_class}" '
            f'd="{path_data}"/>'
            f'<circle class="field-ball-flight{animate_class}" r="3.2">'
            f'<animateMotion dur="1.05s" path="{path_data}" fill="freeze" />'
            "</circle>"
            f'<circle class="field-hit-marker {tone_class}{home_run_class}{animate_class}" '
            f'cx="{hit_x:.1f}" cy="{hit_y:.1f}" r="4.5">'
            f"<title>{escape(description)}</title></circle>"
        )
        footer_label = f"{result_label} - {batter_name}"
        hit_meta = []
        distance = pd.to_numeric(hit_data.get("distance"), errors="coerce")
        launch_speed = pd.to_numeric(
            hit_data.get("launch_speed"),
            errors="coerce",
        )
        if pd.notna(distance):
            hit_meta.append(f"{int(round(float(distance)))} ft")
        if pd.notna(launch_speed):
            hit_meta.append(f"{float(launch_speed):.1f} mph")
        footer_meta = " &middot; ".join(hit_meta)

    footer_html = ""
    if footer_label or footer_meta:
        footer_html = (
            '<div class="live-field-footer">'
            f"<strong>{escape(footer_label)}</strong>"
            f"<span>{footer_meta}</span></div>"
        )
    venue_name = safe_text(
        live_feed.get("venue_name"),
        default="Current ballpark",
    )
    return (
        '<div class="live-field-card">'
        '<div class="live-field-topline"><span></span>'
        f"<strong>{escape(venue_name)}</strong></div>"
        '<svg class="live-field-svg" viewBox="0 0 250 225" '
        'role="img" aria-label="Live batted ball field view">'
        f'{live_field_grass_layer(wall_path, "live-field-main-grass")}'
        f'<defs>{"".join(runner_defs)}</defs>'
        f'<path class="field-shape" d="{wall_path}" fill="none"/>'
        f'<path class="field-foul-line" d="M {home_x} {home_y + 5} '
        f'L {left_line_x} {left_line_y:.1f} M {home_x} {home_y + 5} '
        f'L {right_line_x} {right_line_y:.1f}"/>'
        f'<path class="field-infield" d="{infield_path}"/>'
        f'<path class="field-home-plate" d="{home_plate_path}"/>'
        f'{"".join(base_shapes)}{"".join(runner_shapes)}'
        f'{"".join(dimension_labels)}{trajectory_html}</svg>'
        f"{footer_html}</div>"
    )


def _field_static_svg(live_feed, marker_html, trajectory_html="", aria_label="Field view"):
    (
        wall_path,
        left_line_x,
        left_line_y,
        right_line_x,
        right_line_y,
        dimension_labels,
    ) = live_field_wall_geometry(live_feed)
    home_x, home_y, infield_path, home_plate_path, _mound_x, _mound_y = live_field_infield_geometry()
    base_shapes = live_field_base_shapes()
    clip_id = "contact-field-grass-" + "".join(
        character.lower()
        for character in safe_text(aria_label, default="field")
        if character.isalnum()
    )[:32]

    return (
        '<svg class="live-field-svg" viewBox="0 0 250 225" '
        f'role="img" aria-label="{escape(aria_label, quote=True)}">'
        f'{live_field_grass_layer(wall_path, clip_id)}'
        f'<path class="field-shape" d="{wall_path}" fill="none"/>'
        f'<path class="field-foul-line" d="M {home_x} {home_y + 5} '
        f'L {left_line_x} {left_line_y:.1f} M {home_x} {home_y + 5} '
        f'L {right_line_x} {right_line_y:.1f}"/>'
        f'<path class="field-infield" d="{infield_path}"/>'
        f'<path class="field-home-plate" d="{home_plate_path}"/>'
        f'{"".join(base_shapes)}'
        f'{"".join(dimension_labels)}{marker_html}{trajectory_html}</svg>'
    )


def contact_team_plays(live_feed, side):
    plays = live_feed.get("contact_plays") or []
    return [
        play
        for play in plays
        if safe_text(play.get("batting_side"), default="").lower() == side
    ]


def LiveContactFieldView(live_feed, side):
    side = "away" if side == "away" else "home"
    team_name = safe_text(live_feed.get(f"{side}_team"), default=side.title())
    team_color = team_primary_color(team_name)
    contacts = contact_team_plays(live_feed, side)
    latest_index = None
    if contacts:
        latest_index = contacts[-1].get("play_index")

    markers = []
    trajectory_html = ""
    hit_count = 0
    out_count = 0
    home_x, home_y = LIVE_FIELD_BASE_COORDS["home"]
    latest_contact_key = live_feed.get("_latest_contact_play_key")
    for play in contacts:
        coordinates = contact_play_coordinates(play)
        if coordinates is None:
            continue
        hit_x, hit_y = coordinates
        result_type = safe_text(play.get("result_type"), default="other")
        tone_class = field_result_tone(result_type)
        marker_color = field_result_color(result_type)
        if result_type in HIT_PLAY_TYPES:
            hit_count += 1
        elif tone_class == "out":
            out_count += 1
        description = safe_text(play.get("description"), default="Contact")
        markers.append(
            f'<circle class="field-contact-marker {tone_class}" '
            f'cx="{hit_x:.1f}" cy="{hit_y:.1f}" r="4.1" '
            f'style="fill:{marker_color}">'
            f"<title>{escape(description)}</title></circle>"
        )
        is_latest = (
            _contact_play_key(play) == latest_contact_key
            if latest_contact_key is not None
            else latest_index is not None and play.get("play_index") == latest_index
        )
        if is_latest:
            control_x = home_x + ((hit_x - home_x) * 0.46)
            control_y = max(24.0, ((home_y + hit_y) / 2) - 19)
            path_data = (
                f"M {home_x} {home_y} Q {control_x:.1f} {control_y:.1f} "
                f"{hit_x:.1f} {hit_y:.1f}"
            )
            trajectory_html = (
                f'<path class="field-trajectory {tone_class}" d="{path_data}" '
                f'style="stroke:{marker_color}"/>'
                '<circle class="field-ball-flight" r="3.2">'
                f'<animateMotion dur="1.05s" path="{path_data}" fill="freeze" />'
                "</circle>"
                f'<circle class="field-hit-marker contact-latest {tone_class}" '
                f'cx="{hit_x:.1f}" cy="{hit_y:.1f}" r="4.6" '
                f'style="fill:{marker_color}">'
                f"<title>{escape(description)}</title></circle>"
            )

    return (
        f'<div class="contact-field-card" style="border-top:3px solid {team_color}">'
        '<div class="contact-field-header">'
        f'<div class="contact-field-team">{team_logo_img_html(team_name, alt=team_name)}'
        f"<span>{escape(team_name)}</span></div>"
        '<div class="contact-field-totals">'
        f"<span>{hit_count} Hits</span><span>{out_count} Outs</span>"
        "</div></div>"
        f'{_field_static_svg(live_feed, "".join(markers), trajectory_html, f"{team_name} contact field")}'
        "</div>"
    )


def contact_side_summary(live_feed, side):
    summary = (live_feed.get("team_batting_summary") or {}).get(side) or {}
    if summary:
        return {
            "hitting": f'{int(safe_value(summary.get("hits"), 0))}/{int(safe_value(summary.get("at_bats"), 0))}',
            "avg": safe_text(summary.get("avg"), default="-"),
            "obp": safe_text(summary.get("obp"), default="-"),
            "ops": safe_text(summary.get("ops"), default="-"),
            "strikeouts": int(safe_value(summary.get("strikeouts"), 0)),
            "walks": int(safe_value(summary.get("walks"), 0)),
            "home_runs": int(safe_value(summary.get("home_runs"), 0)),
            "stolen_bases": int(safe_value(summary.get("stolen_bases"), 0)),
        }

    contacts = contact_team_plays(live_feed, side)
    hits = 0
    outs = 0
    runs = 0
    exit_velocities = []
    for play in contacts:
        result_type = safe_text(play.get("result_type"), default="other")
        tone_class = field_result_tone(result_type)
        if result_type in HIT_PLAY_TYPES:
            hits += 1
        elif tone_class == "out":
            outs += 1
        runs += int(safe_value(play.get("runs_scored"), 0))
        launch_speed = pd.to_numeric(
            (play.get("hit_data") or {}).get("launch_speed"),
            errors="coerce",
        )
        if pd.notna(launch_speed):
            exit_velocities.append(float(launch_speed))
    avg_ev = (
        f"{sum(exit_velocities) / len(exit_velocities):.1f}"
        if exit_velocities
        else "-"
    )
    return {
        "hitting": f"{hits}/{max(hits + outs, len(contacts))}",
        "avg": "-",
        "obp": "-",
        "ops": "-",
        "strikeouts": 0,
        "walks": 0,
        "home_runs": runs if runs else 0,
        "stolen_bases": 0,
    }


def ContactHeadToHeadStats(live_feed):
    away_team = safe_text(live_feed.get("away_team"), default="Away")
    home_team = safe_text(live_feed.get("home_team"), default="Home")
    away_summary = contact_side_summary(live_feed, "away")
    home_summary = contact_side_summary(live_feed, "home")
    away_color = team_primary_color(away_team)
    home_color = team_primary_color(home_team)

    rows = (
        ("Hitting", "hitting"),
        ("Batting AVG", "avg"),
        ("OBP", "obp"),
        ("OPS", "ops"),
        ("Strikeouts", "strikeouts"),
        ("Walks", "walks"),
        ("Home Runs", "home_runs"),
        ("Stolen Bases", "stolen_bases"),
    )

    def battle_row(label, key):
        away_value = safe_text(away_summary.get(key), default="-")
        home_value = safe_text(home_summary.get(key), default="-")
        return (
            '<div class="contact-battle-row">'
            f'<div class="contact-battle-value">{escape(away_value)}</div>'
            '<div class="contact-battle-mid">'
            '<span class="contact-battle-line away"></span>'
            f'<span class="contact-battle-label">{escape(label)}</span>'
            '<span class="contact-battle-line home"></span>'
            "</div>"
            f'<div class="contact-battle-value home">{escape(home_value)}</div>'
            "</div>"
        )

    return (
        f'<div class="contact-h2h-card" style="--away-color:{away_color};--home-color:{home_color}">'
        '<div class="contact-h2h-header">'
        '<strong>Head-to-Head</strong>'
        '<span>Live team batting comparison</span></div>'
        '<div class="contact-battle-head">'
        f'<div class="contact-battle-team">{team_logo_img_html(away_team, alt=away_team)}'
        f"<span>{escape(away_team)}</span></div>"
        '<div class="contact-battle-vs">VS</div>'
        f'<div class="contact-battle-team home"><span>{escape(home_team)}</span>'
        f"{team_logo_img_html(home_team, alt=home_team)}</div>"
        "</div>"
        '<div class="contact-battle-list">'
        f'{"".join(battle_row(label, key) for label, key in rows)}'
        "</div></div>"
    )


def contact_momentum_delta(play):
    result_type = safe_text(play.get("result_type"), default="other")
    runs = int(safe_value(play.get("runs_scored"), 0))
    if result_type == "home_run":
        return 2.2 + (runs * 0.65)
    if result_type == "triple":
        return 1.7 + (runs * 0.45)
    if result_type == "double":
        return 1.25 + (runs * 0.4)
    if result_type == "single":
        return 0.85 + (runs * 0.4)
    if result_type == "error":
        return 0.75 + (runs * 0.35)
    if field_result_tone(result_type) == "out":
        return -0.55
    return 0.15


def contact_play_inning_slot(play, fallback_index=0):
    inning = pd.to_numeric(play.get("inning"), errors="coerce")
    if pd.isna(inning):
        return float(fallback_index)
    half = safe_text(play.get("half_inning"), default="top").lower()
    return ((max(1, int(inning)) - 1) * 2) + (1 if half == "bottom" else 0)


def momentum_path_segment(start, end):
    mid_x = (start[0] + end[0]) / 2
    return (
        f'M {start[0]:.1f} {start[1]:.1f} '
        f'C {mid_x:.1f} {start[1]:.1f} {mid_x:.1f} {end[1]:.1f} '
        f'{end[0]:.1f} {end[1]:.1f}'
    )


def svg_tooltip_line(text, max_length=42):
    text = safe_text(text)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3].rstrip()}..."


def LiveMomentumGraph(live_feed):
    plays = live_feed.get("contact_plays") or []
    away_team = safe_text(live_feed.get("away_team"), default="Away")
    home_team = safe_text(live_feed.get("home_team"), default="Home")
    away_color = team_primary_color(away_team, "#245f96")
    home_color = team_primary_color(home_team, "#187347")
    points = [(34.0, 78.0, 0.0)]
    hover_targets = []
    edge = 0.0
    slots = [contact_play_inning_slot(play, index) for index, play in enumerate(plays, start=1)]
    slot_counts = {}
    for slot in slots:
        slot_counts[slot] = slot_counts.get(slot, 0) + 1
    slot_seen = {}
    max_slot = max(17.0, max(slots, default=17.0))
    for index, play in enumerate(plays, start=1):
        delta = contact_momentum_delta(play)
        batting_side = safe_text(play.get("batting_side"), default="away").lower()
        if batting_side == "home":
            edge -= delta
        else:
            edge += delta
        edge = max(-7.0, min(7.0, edge))
        slot = contact_play_inning_slot(play, index)
        slot_seen[slot] = slot_seen.get(slot, 0) + 1
        slot_offset = (
            (slot_seen[slot] / (slot_counts.get(slot, 1) + 1)) * 0.76
            if slot_counts.get(slot, 1) > 1
            else 0.38
        )
        x = 34.0 + (((slot + slot_offset) / max(1.0, max_slot + 1.0)) * 536.0)
        y = 78.0 - (edge * 8.0)
        y = max(18.0, min(138.0, y))
        points.append((x, y, edge))
        team_name = away_team if batting_side != "home" else home_team
        result_label = safe_text(play.get("result_label"), default="Contact")
        description = safe_text(play.get("description"), default=result_label)
        inning = safe_text(play.get("inning"))
        half = safe_text(play.get("half_inning")).title()
        inning_text = f"{half} {inning}".strip()
        runs = int(safe_value(play.get("runs_scored"), 0))
        title_parts = [
            text
            for text in (
                inning_text,
                team_name,
                result_label,
                f"+{runs} run{'s' if runs != 1 else ''}" if runs else "",
                description,
            )
            if text
        ]
        run_text = f"+{runs} run{'s' if runs != 1 else ''}" if runs else "No runs"
        tooltip_lines = [
            svg_tooltip_line(f"{inning_text} - {team_name}", 24),
            svg_tooltip_line(f"{result_label} - {run_text}", 24),
        ]
        hover_targets.append(
            {
                "x": x,
                "y": y,
                "title": " | ".join(title_parts),
                "lines": tooltip_lines,
            }
        )

    segments = []
    for start, end in zip(points, points[1:]):
        mid_edge = (start[2] + end[2]) / 2
        stroke = away_color if mid_edge >= 0 else home_color
        segments.append(
            f'<path class="momentum-segment" d="{momentum_path_segment(start, end)}" '
            f'stroke="{stroke}"/>'
        )
    if len(points) == 1:
        segments.append(
            '<line class="momentum-segment" x1="34" y1="78" x2="570" y2="78" '
            'stroke="#94a3b8"/>'
        )
    hover_markers = []
    tooltip_markers = []
    tooltip_rules = []
    for target_index, target in enumerate(hover_targets):
        tooltip_x = target["x"] + 12
        if tooltip_x > 458:
            tooltip_x = target["x"] - 128
        tooltip_x = max(8, min(458, tooltip_x))
        tooltip_y = target["y"] - 31
        if tooltip_y < 7:
            tooltip_y = target["y"] + 16
        tooltip_y = max(7, min(112, tooltip_y))
        text_lines = "".join(
            f'<text x="{tooltip_x + 7:.1f}" y="{tooltip_y + 12 + (line_index * 10):.1f}" '
            f'class="{"muted" if line_index == 0 else ""}">{escape(line)}</text>'
            for line_index, line in enumerate(target["lines"])
        )
        target_class = f"momentum-hover-point-{target_index}"
        tooltip_class = f"momentum-tooltip-{target_index}"
        tooltip_rules.append(
            f".{target_class}:hover ~ .{tooltip_class},"
            f".{target_class}:focus ~ .{tooltip_class}{{opacity:1;}}"
        )
        hover_markers.append(
            f'<g class="momentum-hover-group {target_class}" tabindex="0" '
            f'aria-label="{escape(target["title"], quote=True)}">'
            f'<circle class="momentum-hover-zone" cx="{target["x"]:.1f}" '
            f'cy="{target["y"]:.1f}" r="14"/>'
            f'<circle class="momentum-hover-dot" cx="{target["x"]:.1f}" '
            f'cy="{target["y"]:.1f}" r="3.2"/></g>'
        )
        tooltip_markers.append(
            f'<g class="momentum-tooltip {tooltip_class}">'
            f'<rect class="momentum-tooltip-bg" x="{tooltip_x:.1f}" y="{tooltip_y:.1f}" '
            'width="120" height="28" rx="0"/>'
            f"{text_lines}</g>"
        )
    inning_ticks = []
    for inning in range(1, 10):
        x = 34.0 + ((((inning - 1) * 2 + 0.5) / 18.0) * 536.0)
        inning_ticks.append(
            f'<line class="momentum-axis" x1="{x:.1f}" y1="20" x2="{x:.1f}" y2="138"/>'
            f'<text class="momentum-inning-label" x="{x:.1f}" y="150">{inning}</text>'
        )
    return (
        '<div class="momentum-card">'
        '<div class="contact-h2h-header"><strong>Momentum</strong>'
        '<span>Hover line shifts for play context</span></div>'
        '<div class="momentum-layout">'
        '<div class="momentum-logo-rail">'
        f"{team_logo_img_html(away_team, alt=away_team)}"
        f"{team_logo_img_html(home_team, alt=home_team)}"
        "</div>"
        '<svg class="momentum-svg" viewBox="0 0 600 156" role="img" '
        'aria-label="Live team edge momentum graph">'
        f'{"".join(inning_ticks)}'
        '<line class="momentum-midline" x1="24" y1="78" x2="584" y2="78"/>'
        f'{"".join(segments)}'
        f'<style>{"".join(tooltip_rules)}</style>'
        f'{"".join(hover_markers)}'
        f'{"".join(tooltip_markers)}'
        "</svg></div></div>"
    )


def LiveContactTabView(live_feed):
    return (
        f"{LiveMomentumGraph(live_feed)}"
        f"{ContactHeadToHeadStats(live_feed)}"
        '<div class="contact-field-grid">'
        f'{LiveContactFieldView(live_feed, "away")}'
        f'{LiveContactFieldView(live_feed, "home")}'
        "</div>"
    )


def AbsChallengeTrackerView(live_feed):
    challenges = live_feed.get("abs_challenges") or {}
    enabled = bool(challenges.get("enabled"))
    if not enabled:
        return ""

    def team_status(side):
        team_name = safe_text(
            live_feed.get(f"{side}_team"),
            default=side.title(),
        )
        team_color = team_primary_color(team_name)
        status = challenges.get(side) or {}
        remaining = max(0, int(safe_value(status.get("remaining"), 0)))
        successful = max(0, int(safe_value(status.get("successful"), 0)))
        failed = max(0, int(safe_value(status.get("failed"), 0)))
        total_slots = max(2, min(4, remaining + failed))
        dots = "".join(
            '<span class="abs-challenge-dot active"></span>'
            if index < remaining
            else '<span class="abs-challenge-dot"></span>'
            for index in range(total_slots)
        )
        history = (
            f"{successful} won &middot; {failed} lost"
            if successful or failed
            else ""
        )
        challenge_title = f"{remaining} remaining"
        return (
            f'<div class="abs-team-status abs-{side}" '
            f'style="--abs-team-color:{team_color}" '
            f'title="{escape(team_name, quote=True)} ABS challenges">'
            '<div class="abs-team-copy">'
            f"<strong>{remaining} left</strong>"
            f"<span>{history}</span></div>"
            f'<div class="abs-challenge-count" title="{challenge_title}">'
            f"{dots}</div></div>"
        )

    return (
        '<div class="abs-challenge-tracker">'
        '<div class="abs-tracker-title">'
        "<strong>ABS Challenges</strong></div>"
        f'{team_status("away")}{team_status("home")}</div>'
    )


def _live_player_profile_href(player, group, game_pk=None):
    player = player if isinstance(player, dict) else {}
    player_id = pd.to_numeric(player.get("player_id"), errors="coerce")
    if pd.isna(player_id):
        return ""
    params = {
        "view": "Players",
        "player": str(int(player_id)),
        "profile_group": "pitching" if group == "pitching" else "batting",
        "return_view": "Games",
    }
    if game_pk is not None and not is_missing_value(game_pk):
        params["return_game_pk"] = str(int(game_pk))
    return f"?{urlencode(params)}"


def _wrap_live_profile_card(card_html, player, group, game_pk=None):
    href = _live_player_profile_href(player, group, game_pk)
    if not href:
        return card_html
    player_name = safe_text(player.get("name"), default="player")
    return (
        f'<a class="live-profile-card-link" href="{escape(href, quote=True)}" '
        f'aria-label="Open {escape(player_name, quote=True)} profile">'
        f"{card_html}</a>"
    )


def _live_player_card_html(label, player, changed=False, game_pk=None):
    player = player if isinstance(player, dict) else {}
    player_name = safe_text(player.get("name"), default="Not available")
    lineup_number = pd.to_numeric(player.get("lineup_number"), errors="coerce")
    label_text = (
        f"#{int(lineup_number)} {label}"
        if pd.notna(lineup_number)
        else label
    )
    headshot = image_html(
        player.get("headshot"),
        f"{player_name} headshot",
        fallback_src="",
    )
    changed_class = " batter-changed" if changed else ""
    changed_chip = (
        '<span class="batter-change-chip">Now Batting</span>'
        if changed
        else ""
    )
    card_html = (
        f'<div class="current-hitter-card live-player-link-card{changed_class}">'
        f"{changed_chip}"
        f"{headshot}"
        f"<div><span>{escape(label_text)}</span><strong>{escape(player_name)}</strong></div>"
        "</div>"
    )
    return _wrap_live_profile_card(card_html, player, "batting", game_pk)


def _live_pitcher_strip_html(player, game_pk=None):
    player = player if isinstance(player, dict) else {}
    player_name = safe_text(player.get("name"), default="Not available")
    headshot = image_html(
        player.get("headshot"),
        f"{player_name} headshot",
        fallback_src="",
    )
    stats = (
        ("Pitch Count", player.get("pitch_count")),
        ("Ks", player.get("strikeouts")),
        ("Hits", player.get("hits_allowed")),
        ("ERA", player.get("era")),
    )
    stat_html = "".join(
        '<div class="live-pitcher-stat">'
        f"<span>{escape(label)}</span>"
        f"<strong>{escape(safe_text(value, default='-'))}</strong>"
        "</div>"
        for label, value in stats
    )
    card_html = (
        '<div class="live-pitcher-strip live-player-link-card">'
        '<div class="live-pitcher-identity">'
        f"{headshot}"
        f"<div><span>Pitching</span><strong>{escape(player_name)}</strong></div>"
        "</div>"
        f'<div class="live-pitcher-stats">{stat_html}</div>'
        "</div>"
    )
    return _wrap_live_profile_card(card_html, player, "pitching", game_pk)


def BatterPitcherView(live_feed, batter_changed=False, game_pk=None):
    return (
        f'{_live_pitcher_strip_html(live_feed.get("current_pitcher"), game_pk)}'
        '<div class="current-hitters">'
        f'{_live_player_card_html("Batter", live_feed.get("current_batter"), batter_changed, game_pk)}'
        f'{_live_player_card_html("On Deck", live_feed.get("on_deck"), False, game_pk)}'
        "</div>"
    )


def AtPlateView(live_feed, batter_changed=False, game_pk=None):
    return (
        '<div class="current-hitters">'
        f'{_live_player_card_html("Batter", live_feed.get("current_batter"), batter_changed, game_pk)}'
        f'{_live_player_card_html("On Deck", live_feed.get("on_deck"), False, game_pk)}'
        "</div>"
    )


def PlayResultChip(play):
    result_type = safe_text(play.get("result_type"), default="other")
    label = safe_text(play.get("result_label"), default="Other")
    tone = "home-run" if result_type == "home_run" else play_result_tone(result_type)
    return (
        f'<span class="play-result-chip {tone}">{escape(label)}</span>'
    )


def _play_count_text(count):
    count = count if isinstance(count, dict) else {}
    return (
        f"{int(safe_value(count.get('balls'), 0))}-"
        f"{int(safe_value(count.get('strikes'), 0))}"
    )


def _recent_plays_html(live_feed):
    plays = live_feed.get("recent_plays") or []
    if not plays:
        return ""

    rows = []
    for play in reversed(plays):
        batter_data = play.get("batter") or {}
        pitcher_data = play.get("pitcher") or {}
        batter = safe_text(
            batter_data.get("name"),
            default="Batter",
        )
        pitcher = safe_text(
            pitcher_data.get("name"),
            default="Pitcher",
        )
        batter_icon = image_html(
            batter_data.get("headshot"),
            f"{batter} headshot",
            fallback_src="",
            lazy=False,
        )
        pitcher_icon = image_html(
            pitcher_data.get("headshot"),
            f"{pitcher} headshot",
            fallback_src="",
            lazy=False,
        )
        description = safe_text(play.get("description"), default="Play recorded.")
        half = safe_text(play.get("half_inning")).title()
        inning = safe_text(play.get("inning"))
        inning_text = f"{half} {inning}".strip()
        count_text = (
            f"{_play_count_text(play.get('count_before'))} → "
            f"{_play_count_text(play.get('count_after'))}"
        )
        runs_scored = int(safe_value(play.get("runs_scored"), 0))
        runs_text = f" · +{runs_scored} run{'s' if runs_scored != 1 else ''}" if runs_scored else ""
        rows.append(
            '<div class="live-play-row">'
            f"{PlayResultChip(play)}"
            '<div class="live-play-matchup">'
            f'<div class="live-play-player-icons">{batter_icon}{pitcher_icon}</div>'
            '<div class="live-play-matchup-copy">'
            f"<strong>{escape(batter)}</strong>"
            f"<span>vs {escape(pitcher)}</span></div></div>"
            f'<div class="live-play-description">{escape(description)}</div>'
            f'<div class="live-play-meta">{escape(inning_text)} · '
            f"{escape(count_text)}{escape(runs_text)}"
            "</div></div>"
        )
    return (
        '<div class="live-play-panel">'
        '<div class="live-play-heading">Plays</div>'
        f'{"".join(rows)}</div>'
    )


def html_fragment_id(*values):
    text = "-".join(safe_text(value) for value in values if not is_missing_value(value))
    fragment = "".join(
        character.lower() if character.isalnum() else "-"
        for character in text
    )
    fragment = "-".join(part for part in fragment.split("-") if part)
    return fragment or "detail"


def _play_batting_side(play):
    side = safe_text((play or {}).get("batting_side")).lower()
    if side in {"away", "home"}:
        return side
    half = safe_text((play or {}).get("half_inning")).lower()
    if half == "top":
        return "away"
    if half == "bottom":
        return "home"
    return ""


def play_opponent_team(live_feed, play):
    side = _play_batting_side(play)
    if side == "away":
        return safe_text((live_feed or {}).get("home_team"), default="Opponent")
    if side == "home":
        return safe_text((live_feed or {}).get("away_team"), default="Opponent")
    return "Opponent"


@st.cache_data(show_spinner=False, ttl=600)
def load_batter_opponent_game_log(player_id, season, opponent_team):
    player_id = pd.to_numeric(player_id, errors="coerce")
    if pd.isna(player_id):
        return pd.DataFrame()
    try:
        rows = database.get_batter_season_game_logs_from_db(int(player_id), int(season))
    except Exception:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    opponent = safe_text(opponent_team).casefold()
    if opponent and "opponent" in frame.columns:
        frame = frame[
            frame["opponent"].fillna("").astype(str).str.casefold().eq(opponent)
        ]
    if frame.empty:
        return frame
    frame["_game_date_sort"] = pd.to_datetime(
        frame.get("game_date"),
        errors="coerce",
    )
    frame = frame.sort_values(
        ["_game_date_sort", "game_pk"],
        ascending=[False, False],
        na_position="last",
    )
    return frame.drop(columns=["_game_date_sort"], errors="ignore").head(5)


def short_game_date(value):
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        text = safe_text(value, default="-")
        return text[:5] if text != "-" else "-"
    return timestamp.strftime("%m/%d")


def compact_stat_value(value, default="-"):
    if is_missing_value(value):
        return default
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.notna(numeric):
        if float(numeric).is_integer():
            return str(int(numeric))
        return f"{float(numeric):.3f}".replace("0.", ".")
    return safe_text(value, default=default)


def BatterOpponentGameLogHtml(live_feed, play, limit=4):
    batter = (play or {}).get("batter") or {}
    opponent = play_opponent_team(live_feed, play)
    season = int(safe_value(
        getattr(st.session_state.get("selected_game_date", None), "year", None),
        app_today.year if "app_today" in globals() else current_app_date().year,
    ))
    rows = load_batter_opponent_game_log(
        batter.get("player_id"),
        season,
        opponent,
    )
    rows = rows.head(limit) if not rows.empty else rows
    opponent_code = team_abbreviation(opponent) or opponent
    title = f"Games vs {opponent_code}"
    if rows.empty:
        return (
            '<div class="play-detail-gamelog">'
            '<div class="play-detail-gamelog-head">'
            f'<strong>{escape(title)}</strong><span>Season</span></div>'
            '<div class="play-detail-gamelog-empty">'
            f'No {season} game log found against {escape(opponent)}.</div></div>'
        )

    cells = ["<span>Date</span><span>PA</span><span>AB</span><span>K</span>"]
    for _, row in rows.iterrows():
        cells.append(
            f"<strong>{escape(short_game_date(row.get('game_date')))}</strong>"
            f"<strong>{escape(compact_stat_value(row.get('PA')))}</strong>"
            f"<strong>{escape(compact_stat_value(row.get('AB')))}</strong>"
            f"<strong>{escape(compact_stat_value(row.get('SO')))}</strong>"
        )
    return (
        '<div class="play-detail-gamelog">'
        '<div class="play-detail-gamelog-head">'
        f'<strong>{escape(title)}</strong>'
        f'<span>Last {len(rows)}</span></div>'
        f'<div class="play-detail-gamelog-grid">{"".join(cells)}</div></div>'
    )


def build_live_opponent_game_log_payload(live_feed):
    payload = {}
    plays = (live_feed or {}).get("completed_plays") or []
    seen = set()
    for play in plays:
        batter = play.get("batter") or {}
        batter_id = pd.to_numeric(batter.get("player_id"), errors="coerce")
        if pd.isna(batter_id):
            continue
        opponent = play_opponent_team(live_feed, play)
        season = int(safe_value(
            getattr(st.session_state.get("selected_game_date", None), "year", None),
            app_today.year if "app_today" in globals() else current_app_date().year,
        ))
        key = (int(batter_id), opponent.casefold())
        if key in seen:
            continue
        seen.add(key)
        rows = load_batter_opponent_game_log(int(batter_id), season, opponent)
        if rows.empty:
            continue
        records = []
        for _, row in rows.head(4).iterrows():
            records.append(
                {
                    "date": short_game_date(row.get("game_date")),
                    "PA": compact_stat_value(row.get("PA")),
                    "AB": compact_stat_value(row.get("AB")),
                    "K": compact_stat_value(row.get("SO")),
                }
            )
        payload[f"{int(batter_id)}|{opponent.casefold()}"] = {
            "title": f"Games vs {team_abbreviation(opponent) or opponent}",
            "rows": records,
            "season": season,
            "opponent": opponent,
        }
    return payload


def PlayDetailMatchupFacesHtml(batter, pitcher, game_log_html=""):
    batter = batter if isinstance(batter, dict) else {}
    pitcher = pitcher if isinstance(pitcher, dict) else {}
    batter_name = safe_text(batter.get("name"), default="Batter")
    pitcher_name = safe_text(pitcher.get("name"), default="Pitcher")
    batter_headshot = batter.get("headshot") or player_image_url(
        batter.get("player_id"),
        width=160,
    )
    pitcher_headshot = pitcher.get("headshot") or player_image_url(
        pitcher.get("player_id"),
        width=160,
    )

    def face_image(src, name):
        image = image_html(
            src,
            f"{name} headshot",
            class_name="play-detail-face-img",
            fallback_src="",
            lazy=False,
        )
        if image:
            return image
        initial = safe_text(name, default="?").strip()[:1].upper() or "?"
        return f'<span class="play-detail-face-placeholder">{escape(initial)}</span>'

    center_html = game_log_html or '<span class="play-detail-vs">VS</span>'
    return (
        '<div class="play-detail-matchup-strip">'
        '<div class="play-detail-person batter">'
        f'{face_image(batter_headshot, batter_name)}'
        '<div class="play-detail-face-copy">'
        '<span>Batter</span>'
        f'<strong>{escape(batter_name)}</strong>'
        '</div></div>'
        f"{center_html}"
        '<div class="play-detail-person pitcher">'
        f'{face_image(pitcher_headshot, pitcher_name)}'
        '<div class="play-detail-face-copy">'
        '<span>Pitcher</span>'
        f'<strong>{escape(pitcher_name)}</strong>'
        '</div></div></div>'
    )


def PlayDetailModalHtml(live_feed, play, modal_id, close_target):
    batter = play.get("batter") or {}
    pitcher = play.get("pitcher") or {}
    batter_name = safe_text(batter.get("name"), default="Batter")
    pitcher_name = safe_text(pitcher.get("name"), default="Pitcher")
    description = safe_text(play.get("description"), default="Play recorded.")
    inning = f"{safe_text(play.get('half_inning')).title()} {safe_text(play.get('inning'))}".strip()
    result_label = safe_text(play.get("result_label"), default="Play")
    runs = int(safe_value(play.get("runs_scored"), 0))
    record = batter_game_record(live_feed, batter.get("player_id"))
    game_log_html = BatterOpponentGameLogHtml(live_feed, play)
    pitch_list = play.get("pitches") or []
    zone_feed = {
        "current_pitches": pitch_list,
        "latest_pitch": pitch_list[-1] if pitch_list else None,
        "current_pitcher": pitcher or live_feed.get("current_pitcher"),
    }
    stat_items = "".join(
        '<div class="play-detail-stat">'
        f"<span>{escape(label)}</span><strong>{escape(safe_text(value, default='0'))}</strong>"
        "</div>"
        for label, value in record.items()
    )
    run_text = f"+{runs} run{'s' if runs != 1 else ''}" if runs else "No runs scored on this play."
    return (
        f'<div id="{escape(modal_id, quote=True)}" class="play-detail-modal" '
        'role="dialog" aria-modal="true" '
        f'aria-labelledby="{escape(modal_id, quote=True)}-title">'
        f'<a class="play-detail-scrim" href="#{escape(close_target, quote=True)}" '
        'aria-label="Close play detail"></a>'
        '<div class="play-detail-modal-card">'
        '<div class="play-detail-modal-head">'
        '<div>'
        '<span>At-Bat Detail</span>'
        f'<strong id="{escape(modal_id, quote=True)}-title">'
        f'{escape(batter_name)} vs {escape(pitcher_name)}</strong>'
        '</div>'
        f'<a class="play-detail-close" href="#{escape(close_target, quote=True)}" '
        'aria-label="Close play detail">&times;</a>'
        '</div>'
        f'{PlayDetailMatchupFacesHtml(batter, pitcher)}'
        '<div class="play-detail-layout">'
        '<div class="play-detail-card">'
        f'<h3>{escape(result_label)}</h3>'
        f'<p>{escape(inning)}</p>'
        f'<p>{escape(description)}</p>'
        f'<div class="play-detail-stat-grid">{stat_items}</div>'
        f'{game_log_html}'
        '</div>'
        '<div class="play-detail-card">'
        '<h3>At-Bat Strike Zone</h3>'
        f'{StrikeZoneView(zone_feed)}'
        '</div>'
        '<div class="play-detail-card">'
        '<h3>Game Record</h3>'
        f'<p>{escape(batter_name)} has {record["H"]} hit(s), '
        f'{record["TB"]} total base(s), and {record["RBI"]} run(s) driven in this game.</p>'
        '</div>'
        '<div class="play-detail-card">'
        '<h3>Efficiency By Inning</h3>'
        f'<p>{escape(run_text)}</p>'
        f'{BatterInningEfficiencyChart(live_feed, batter.get("player_id"))}'
        '</div>'
        '</div></div></div>'
    )


def LivePlaysPanel(live_feed, game_pk=None, animate_play_key=None):
    plays = live_feed.get("completed_plays") or live_feed.get("recent_plays") or []
    panel_id = html_fragment_id("live-plays", game_pk if game_pk is not None else "game")
    if not plays:
        return (
            f'<div id="{escape(panel_id, quote=True)}" class="live-play-panel">'
            '<div class="live-play-heading">Plays</div>'
            '<div class="live-play-list">'
            '<div class="live-play-empty">No completed plays yet.</div>'
            "</div></div>"
        )

    rows = []
    modals = []
    for fallback_index, play in enumerate(reversed(plays), start=1):
        batter_data = play.get("batter") or {}
        pitcher_data = play.get("pitcher") or {}
        batter = safe_text(batter_data.get("name"), default="Batter")
        pitcher = safe_text(pitcher_data.get("name"), default="Pitcher")
        batter_icon = image_html(
            batter_data.get("headshot"),
            f"{batter} headshot",
            fallback_src="",
            lazy=False,
        )
        pitcher_icon = image_html(
            pitcher_data.get("headshot"),
            f"{pitcher} headshot",
            fallback_src="",
            lazy=False,
        )
        description = safe_text(play.get("description"), default="Play recorded.")
        half = safe_text(play.get("half_inning")).title()
        inning = safe_text(play.get("inning"))
        inning_text = f"{half} {inning}".strip()
        runs_scored = int(safe_value(play.get("runs_scored"), 0))
        scoring = runs_scored > 0 or bool(play.get("is_scoring_play"))
        scoring_class = " scoring-play" if scoring else ""
        runs_badge = (
            f'<span class="play-score-badge">+{runs_scored} R</span>'
            if runs_scored
            else ""
        )
        play_index = play.get("play_index")
        if play_index is None:
            play_index = f"recent-{fallback_index}"
        play_key = _live_play_key(play)
        row_class = " new-play" if animate_play_key is not None and play_key == animate_play_key else ""
        modal_id = html_fragment_id(
            "play-detail",
            game_pk if game_pk is not None else "game",
            play_index,
            fallback_index,
        )
        href = f"#{modal_id}"
        modals.append(PlayDetailModalHtml(live_feed, play, modal_id, panel_id))
        rows.append(
            f'<a class="live-play-row{scoring_class}{row_class}" href="{escape(href, quote=True)}">'
            f"{PlayResultChip(play)}"
            '<div class="live-play-matchup">'
            f'<div class="live-play-player-icons">{batter_icon}{pitcher_icon}</div>'
            '<div class="live-play-matchup-copy">'
            f"<strong>{escape(batter)}</strong>"
            f"<span>vs {escape(pitcher)}</span></div></div>"
            f'<div class="live-play-description">{escape(description)}</div>'
            f'<div class="live-play-meta">{escape(inning_text)}{runs_badge}</div></a>'
        )
    return (
        f'<div id="{escape(panel_id, quote=True)}" class="live-play-panel">'
        '<div class="live-play-heading">Plays</div>'
        f'<div class="live-play-list">{"".join(rows)}</div></div>'
        f'{"".join(modals)}'
    )


def LiveGameClientUpdater(game_pk, live_feed):
    initial_timestamp = safe_text((live_feed or {}).get("feed_timestamp"))
    opponent_game_logs = build_live_opponent_game_log_payload(live_feed)
    updater_html = """
    <script>
    (() => {
      const GAME_PK = __GAME_PK__;
      const INITIAL_TIMESTAMP = __INITIAL_TIMESTAMP__;
      const OPPONENT_GAME_LOGS = __OPPONENT_GAME_LOGS__;
      const FEED_URL = `https://statsapi.mlb.com/api/v1.1/game/${GAME_PK}/feed/live`;
      let lastTimestamp = INITIAL_TIMESTAMP || "";
      let previousScores = null;
      let inflight = false;

      const parentWindow = window.parent;
      const parentDocument = parentWindow.document;

      function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, (char) => ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        }[char]));
      }

      function safeInt(value, fallback = 0) {
        const number = Number(value);
        return Number.isFinite(number) ? Math.trunc(number) : fallback;
      }

      function safeFloat(value) {
        const number = Number(value);
        return Number.isFinite(number) ? number : null;
      }

      function playerHeadshot(id, width = 80) {
        const playerId = Number(id);
        if (!Number.isFinite(playerId)) return "";
        return `https://img.mlbstatic.com/mlb-photos/image/upload/w_${width},d_people:generic:headshot:silo:current.png,q_auto:best,f_auto/v1/people/${Math.trunc(playerId)}/headshot/67/current`;
      }

      function imageHtml(src, alt, className = "") {
        if (!src) return "";
        const classAttr = className ? ` class="${escapeHtml(className)}"` : "";
        return `<img${classAttr} src="${escapeHtml(src)}" alt="${escapeHtml(alt)}" loading="lazy" referrerpolicy="no-referrer">`;
      }

      function teamLogo(teamId, name) {
        const id = Number(teamId);
        if (!Number.isFinite(id)) return "";
        return imageHtml(`https://www.mlbstatic.com/team-logos/${Math.trunc(id)}.svg`, name || "Team");
      }

      function livePlayer(player) {
        player = player || {};
        return {
          player_id: player.id,
          name: player.fullName || player.lastName || "",
          headshot: playerHeadshot(player.id),
        };
      }

      function lineupNumber(value) {
        const text = String(value || "").trim();
        return /^\\d/.test(text) ? Number(text[0]) : null;
      }

      function boxscoreLineupLookup(boxscore) {
        const lookup = {};
        ["away", "home"].forEach((side) => {
          const players = boxscore?.teams?.[side]?.players || {};
          Object.entries(players).forEach(([key, player]) => {
            const playerId = player?.person?.id || Number(String(key).replace("ID", ""));
            const lineup = lineupNumber(player?.battingOrder);
            if (Number.isFinite(Number(playerId)) && lineup !== null) {
              lookup[Math.trunc(Number(playerId))] = lineup;
            }
          });
        });
        return lookup;
      }

      function playerWithLineup(player, lookup) {
        const result = livePlayer(player);
        const lineup = lookup[Math.trunc(Number(result.player_id))];
        if (lineup) result.lineup_number = lineup;
        return result;
      }

      function livePitcher(player, boxscore, pitchHand) {
        const result = livePlayer(player);
        const playerId = Math.trunc(Number(result.player_id));
        if (Number.isFinite(playerId)) {
          ["away", "home"].some((side) => {
            const record = boxscore?.teams?.[side]?.players?.[`ID${playerId}`];
            if (!record) return false;
            const gameStats = record?.stats?.pitching || {};
            const seasonStats = record?.seasonStats?.pitching || {};
            result.pitch_count = safeInt(gameStats.pitchesThrown);
            result.strikeouts = safeInt(gameStats.strikeOuts);
            result.hits_allowed = safeInt(gameStats.hits);
            result.era = gameStats.era || seasonStats.era || "";
            return true;
          });
        }
        if (pitchHand) {
          result.throwing_hand = pitchHand.code || pitchHand.description || pitchHand.abbreviation || "";
        }
        return result;
      }

      function countFromEvent(event) {
        const count = event?.count || {};
        return {
          balls: safeInt(count.balls),
          strikes: safeInt(count.strikes),
          outs: safeInt(count.outs),
        };
      }

      function pitchEvent(event) {
        const details = event?.details || {};
        const pitchData = event?.pitchData || {};
        const coordinates = pitchData.coordinates || {};
        const pitchType = details.type || {};
        const call = details.call || {};
        return {
          play_id: event?.playId,
          event_index: event?.index,
          description: details.description || call.description || "",
          code: details.code || call.code,
          call: call.description || details.description || "",
          is_strike: Boolean(details.isStrike),
          is_ball: Boolean(details.isBall),
          is_in_play: Boolean(details.isInPlay),
          is_out: Boolean(details.isOut),
          count_after: countFromEvent(event),
          zone: safeInt(details.zone, null),
          pitch_type: pitchType.description || pitchType.code || "",
          pitch_code: pitchType.code || "",
          start_speed: safeFloat(pitchData.startSpeed),
          p_x: safeFloat(coordinates.pX),
          p_z: safeFloat(coordinates.pZ),
          strike_zone_top: safeFloat(pitchData.strikeZoneTop),
          strike_zone_bottom: safeFloat(pitchData.strikeZoneBottom),
        };
      }

      function normalizeCount(count) {
        count = count || {};
        return {
          balls: safeInt(count.balls),
          strikes: safeInt(count.strikes),
          outs: safeInt(count.outs),
        };
      }

      function annotatePitchCounts(pitches) {
        let previousCount = null;
        return (pitches || []).map((pitch) => {
          const countAfter = normalizeCount(pitch?.count_after);
          const countBefore = previousCount
            ? { ...previousCount }
            : { balls: 0, strikes: 0, outs: countAfter.outs };
          previousCount = countAfter;
          return { ...pitch, count_before: countBefore, count_after: countAfter };
        });
      }

      const RESULT_LABELS = {
        single: "Single",
        double: "Double",
        triple: "Triple",
        home_run: "Home Run",
        walk: "Walk",
        hit_by_pitch: "HBP",
        strikeout: "Strikeout",
        groundout: "Groundout",
        flyout: "Flyout",
        popout: "Popout",
        lineout: "Lineout",
        forceout: "Forceout",
        double_play: "Double Play",
        sac_fly: "Sac Fly",
        error: "Error",
        other: "Other",
      };

      function classifyPlay(play) {
        const result = play?.result || {};
        const combined = `${result.eventType || ""} ${result.event || ""} ${result.description || ""}`.toLowerCase();
        const rules = [
          ["home_run", ["home run", "homers"]],
          ["hit_by_pitch", ["hit by pitch"]],
          ["strikeout", ["strikeout", "strikes out"]],
          ["double_play", ["double play"]],
          ["sac_fly", ["sac fly", "sacrifice fly"]],
          ["forceout", ["forceout", "force out"]],
          ["groundout", ["groundout", "grounds out"]],
          ["flyout", ["flyout", "flies out"]],
          ["popout", ["popout", "pops out"]],
          ["lineout", ["lineout", "lines out"]],
          ["triple", ["triple"]],
          ["double", ["double"]],
          ["single", ["single"]],
          ["walk", ["intent walk", "intentional walk", "walk"]],
          ["error", ["error", "field error"]],
        ];
        const match = rules.find(([_type, terms]) => terms.some((term) => combined.includes(term)));
        return match ? match[0] : "other";
      }

      function playRunsScored(play) {
        return (play?.runners || []).filter((runner) => runner?.details?.isScoringEvent).length;
      }

      function parseLivePlay(play, teams) {
        const result = play?.result || {};
        const about = play?.about || {};
        const matchup = play?.matchup || {};
        const pitchEvents = (play?.playEvents || []).filter((event) => event?.isPitch);
        const pitches = annotatePitchCounts(pitchEvents.map(pitchEvent));
        const hitEvent = [...(play?.playEvents || [])].reverse().find((event) => event?.hitData);
        const hitData = hitEvent?.hitData;
        const resultType = classifyPlay(play);
        const side = String(about.halfInning || "").toLowerCase() === "top" ? "away" : "home";
        return {
          play_index: about.atBatIndex,
          completed: Boolean(about.isComplete),
          inning: about.inning,
          half_inning: about.halfInning,
          batter: livePlayer(matchup.batter),
          pitcher: livePlayer(matchup.pitcher),
          result_type: resultType,
          result_label: RESULT_LABELS[resultType] || "Other",
          description: result.description || result.event || "",
          count_before: pitchEvents.length > 1 ? countFromEvent(pitchEvents[pitchEvents.length - 2]) : { balls: 0, strikes: 0, outs: countFromEvent(pitchEvents[pitchEvents.length - 1] || play).outs },
          count_after: pitchEvents.length ? countFromEvent(pitchEvents[pitchEvents.length - 1]) : countFromEvent(play),
          runs_scored: playRunsScored(play),
          away_score: result.awayScore,
          home_score: result.homeScore,
          is_scoring_play: Boolean(about.isScoringPlay),
          batting_side: side,
          batting_team: teams?.[side]?.name,
          hit_data: hitData ? {
            x: safeFloat(hitData.coordinates?.coordX),
            y: safeFloat(hitData.coordinates?.coordY),
            launch_speed: safeFloat(hitData.launchSpeed),
            launch_angle: safeFloat(hitData.launchAngle),
            distance: safeFloat(hitData.totalDistance),
            trajectory: hitData.trajectory,
            hardness: hitData.hardness,
            location: safeInt(hitData.location, null),
          } : null,
          pitches,
        };
      }

      function countFouls(currentPlay) {
        return (currentPlay?.playEvents || []).filter((event) => {
          if (!event?.isPitch) return false;
          const text = `${event.details?.description || ""} ${event.details?.call?.description || ""}`.toLowerCase();
          return text.includes("foul");
        }).length;
      }

      function parseFeed(data) {
        const gameData = data.gameData || {};
        const liveData = data.liveData || {};
        const linescore = liveData.linescore || {};
        const plays = liveData.plays || {};
        const currentPlay = plays.currentPlay || {};
        const matchup = currentPlay.matchup || {};
        const offense = linescore.offense || {};
        const defense = linescore.defense || {};
        const boxscore = liveData.boxscore || {};
        const lookup = boxscoreLineupLookup(boxscore);
        const teams = gameData.teams || {};
        const venue = gameData.venue || {};
        const fieldInfo = venue.fieldInfo || {};
        const pitchEvents = annotatePitchCounts(
          (currentPlay.playEvents || []).filter((event) => event?.isPitch).map(pitchEvent)
        );
        const currentBatter = matchup.batter || offense.batter || {};
        const currentPitcher = matchup.pitcher || defense.pitcher || {};
        const onDeck = offense.onDeck || {};
        const completed = (plays.allPlays || []).filter((play) => play?.about?.isComplete).map((play) => parseLivePlay(play, teams));
        const contactPlays = completed.filter((play) => play.hit_data);
        const absChallenges = gameData.absChallenges || {};
        return {
          feed_timestamp: data.metaData?.timeStamp || "",
          abstract_state: gameData.status?.abstractGameState || "",
          detailed_state: gameData.status?.detailedState || "",
          inning: linescore.currentInning,
          inning_ordinal: linescore.currentInningOrdinal,
          inning_state: linescore.inningState || linescore.inningHalf || "",
          away_score: linescore.teams?.away?.runs,
          home_score: linescore.teams?.home?.runs,
          away_team: teams.away?.name || "Away",
          away_team_id: teams.away?.id,
          home_team: teams.home?.name || "Home",
          home_team_id: teams.home?.id,
          venue_name: venue.name || "",
          field_dimensions: {
            left_line: safeInt(fieldInfo.leftLine, null),
            left: safeInt(fieldInfo.left, null),
            left_center: safeInt(fieldInfo.leftCenter, null),
            center: safeInt(fieldInfo.center, null),
            right_center: safeInt(fieldInfo.rightCenter, null),
            right: safeInt(fieldInfo.right, null),
            right_line: safeInt(fieldInfo.rightLine, null),
          },
          abs_challenges: {
            enabled: Boolean(absChallenges.hasChallenges),
            away: {
              remaining: safeInt(absChallenges.away?.remaining),
              successful: safeInt(absChallenges.away?.usedSuccessful),
              failed: safeInt(absChallenges.away?.usedFailed),
            },
            home: {
              remaining: safeInt(absChallenges.home?.remaining),
              successful: safeInt(absChallenges.home?.usedSuccessful),
              failed: safeInt(absChallenges.home?.usedFailed),
            },
          },
          balls: safeInt(currentPlay.count?.balls),
          strikes: safeInt(currentPlay.count?.strikes),
          outs: safeInt(currentPlay.count?.outs),
          fouls: countFouls(currentPlay),
          current_pitches: pitchEvents.slice(-12),
          latest_pitch: pitchEvents[pitchEvents.length - 1] || null,
          current_batter: playerWithLineup(currentBatter, lookup),
          current_pitcher: livePitcher(currentPitcher, boxscore, matchup.pitchHand || currentPitcher.pitchHand),
          on_deck: playerWithLineup(onDeck, lookup),
          bases: {
            first: offense.first ? livePlayer(offense.first) : null,
            second: offense.second ? livePlayer(offense.second) : null,
            third: offense.third ? livePlayer(offense.third) : null,
          },
          completed_plays: completed,
          recent_plays: completed.slice(-8),
          contact_plays: contactPlays,
          latest_completed_play: completed[completed.length - 1] || null,
          latest_batted_ball: contactPlays[contactPlays.length - 1] || null,
        };
      }

      function scoreHtml(score, previous) {
        const value = score == null ? "-" : String(score);
        const delta = Number.isFinite(Number(previous)) && Number(score) > Number(previous)
          ? `<span class="live-score-delta">+${Number(score) - Number(previous)}</span>`
          : "";
        const changed = delta ? " score-changed" : "";
        return `<span class="live-score-wrap"><strong class="live-score${changed}">${escapeHtml(value)}</strong>${delta}</span>`;
      }

      function gameHeader(feed) {
        const statusTitle = String(feed.abstract_state || "").toLowerCase() === "live"
          ? `${feed.inning_state || ""} ${feed.inning_ordinal || ""}`.trim()
          : feed.detailed_state || "";
        const old = previousScores || {};
        return `<div class="live-game-scorebug">
          <div class="live-game-team">
            ${teamLogo(feed.away_team_id, feed.away_team)}
            <span>${escapeHtml(feed.away_team)}</span>
            ${scoreHtml(feed.away_score, old.away)}
          </div>
          <div class="live-game-status">
            <strong>${escapeHtml(statusTitle)}</strong>
            <span>${escapeHtml(feed.detailed_state || "")}</span>
          </div>
          <div class="live-game-team">
            ${scoreHtml(feed.home_score, old.home)}
            <span>${escapeHtml(feed.home_team)}</span>
            ${teamLogo(feed.home_team_id, feed.home_team)}
          </div>
        </div>`;
      }

      function countDots(label, kind, active, total) {
        let dots = "";
        for (let index = 0; index < total; index += 1) {
          dots += `<span class="count-dot ${kind}${index < safeInt(active) ? " active" : ""}"></span>`;
        }
        return `<span class="count-dot-group"><span class="count-dot-label">${label}</span>${dots}</span>`;
      }

      function playerCard(label, player) {
        player = player || {};
        const name = player.name || "--";
        const lineup = player.lineup_number ? `<span>#${escapeHtml(player.lineup_number)}</span>` : "";
        return `<div class="current-hitter-card live-player-link-card">
          ${imageHtml(player.headshot, `${name} headshot`)}
          <div class="current-hitter-copy">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(name)}</strong>
            ${lineup}
          </div>
        </div>`;
      }

      function pitcherStrip(player) {
        player = player || {};
        const name = player.name || "Pitcher";
        const stats = [
          ["Pitch Count", player.pitch_count],
          ["Ks", player.strikeouts],
          ["Hits", player.hits_allowed],
          ["ERA", player.era],
        ].map(([label, value]) => `<span class="live-pitcher-stat"><em>${escapeHtml(label)}</em><strong>${escapeHtml(value ?? "-")}</strong></span>`).join("");
        return `<div class="live-pitcher-strip">
          <div class="live-pitcher-identity">${imageHtml(player.headshot, `${name} headshot`)}<div><span>Pitching</span><strong>${escapeHtml(name)}</strong></div></div>
          <div class="live-pitcher-stats">${stats}</div>
        </div>`;
      }

      function baseDiamond(feed) {
        const bases = feed.bases || {};
        const baseHtml = ["first", "second", "third"].map((base) => {
          const runner = bases[base];
          const title = runner ? runner.name : `${base} base empty`;
          return `<span class="${base}${runner ? " occupied" : ""}" title="${escapeHtml(title)}">${runner ? imageHtml(runner.headshot, title, "base-runner-headshot") : ""}</span>`;
        }).join("");
        const labels = ["first", "second", "third"].filter((base) => bases[base]).map((base) => `<span><strong>${base[0].toUpperCase() + base.slice(1)}:</strong> ${escapeHtml(bases[base].name)}</span>`).join("");
        return `<div class="base-diamond">${baseHtml}</div>${labels ? `<div class="base-runner-list">${labels}</div>` : ""}`;
      }

      function absTracker(feed) {
        const challenges = feed.abs_challenges || {};
        if (!challenges.enabled) return "";
        const teamStatus = (side) => {
          const status = challenges[side] || {};
          const remaining = Math.max(0, safeInt(status.remaining));
          const successful = Math.max(0, safeInt(status.successful));
          const failed = Math.max(0, safeInt(status.failed));
          const totalSlots = Math.max(2, Math.min(4, remaining + failed));
          let dots = "";
          for (let index = 0; index < totalSlots; index += 1) {
            dots += `<span class="abs-challenge-dot${index < remaining ? " active" : ""}"></span>`;
          }
          const teamName = side === "away" ? feed.away_team : feed.home_team;
          const history = successful || failed ? `${successful} won &middot; ${failed} lost` : "";
          return `<div class="abs-team-status abs-${side}" style="--abs-team-color:#245f96" title="${escapeHtml(teamName || side)} ABS challenges">
            <div class="abs-team-copy"><strong>${remaining} left</strong><span>${history}</span></div>
            <div class="abs-challenge-count" title="${remaining} remaining">${dots}</div>
          </div>`;
        };
        return `<div class="abs-challenge-tracker">
          <div class="abs-tracker-title"><strong>ABS Challenges</strong></div>
          ${teamStatus("away")}${teamStatus("home")}
        </div>`;
      }

      const VENUE_DEFAULTS = { left_line: 330, left: 370, left_center: 390, center: 400, right_center: 390, right: 370, right_line: 330 };
      function fieldDimensions(feed) {
        return { ...VENUE_DEFAULTS, ...(feed.field_dimensions || {}) };
      }
      function fieldNumber(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) && number > 0 ? number : fallback;
      }
      function fieldGeometry(feed) {
        const dims = fieldDimensions(feed);
        const specs = [
          ["left_line", 22, 330], ["left", 39, 370], ["left_center", 76, 390],
          ["center", 125, 400], ["right_center", 174, 390], ["right", 211, 370],
          ["right_line", 228, 330],
        ];
        const points = specs.map(([key, x, fallback]) => {
          const distance = fieldNumber(dims[key], fallback);
          const y = Math.max(24, Math.min(82, 205 - (distance * 0.42)));
          return { key, x, y, distance };
        });
        const wallPath = `M 125 218 ${points.map((point) => `L ${point.x} ${point.y.toFixed(1)}`).join(" ")} Z`;
        const labels = points.map((point) => `<text class="field-dimension" x="${point.x}" y="${Math.max(12, point.y - 4).toFixed(1)}">${Math.round(point.distance)}</text>`).join("");
        return { wallPath, left: points[0], right: points[points.length - 1], labels };
      }
      function contactCoords(play) {
        const hit = play?.hit_data || {};
        let x = Number(hit.x);
        let y = Number(hit.y);
        if (!Number.isFinite(x) || !Number.isFinite(y)) {
          const fallback = { 1: [125, 190], 2: [125, 210], 3: [160, 180], 4: [145, 160], 5: [90, 180], 6: [105, 160], 7: [65, 92], 8: [125, 60], 9: [185, 92] }[safeInt(hit.location)];
          if (!fallback) return null;
          [x, y] = fallback;
        }
        return [Math.max(8, Math.min(242, x)), Math.max(18, Math.min(208, y))];
      }
      function fieldView(feed) {
        const geometry = fieldGeometry(feed);
        const clipId = `live-field-${GAME_PK}`;
        const stripes = Array.from({ length: 7 }, (_, i) => `<rect class="field-stripe" x="${20 + (i * 30)}" y="0" width="15" height="225"/>`).join("");
        const latest = feed.latest_batted_ball || {};
        const coords = contactCoords(latest);
        const hitTone = playTone(latest.result_type);
        const trajectory = coords ? `<path class="field-trajectory ${hitTone}" d="M 125 210 Q ${((125 + coords[0]) / 2).toFixed(1)} ${Math.min(190, coords[1] + 30).toFixed(1)} ${coords[0].toFixed(1)} ${coords[1].toFixed(1)}"/>` : "";
        const marker = coords ? `<circle class="field-hit-marker ${hitTone}" cx="${coords[0].toFixed(1)}" cy="${coords[1].toFixed(1)}" r="4.5"/>` : "";
        const bases = feed.bases || {};
        const baseShapes = [["first", 158, 177], ["second", 125, 144], ["third", 92, 177]].map(([base, x, y]) => `<rect class="field-base${bases[base] ? " occupied" : ""}" x="${x - 4}" y="${y - 4}" width="8" height="8" transform="rotate(45 ${x} ${y})"/>`).join("");
        const footer = latest.description ? escapeHtml(latest.description) : "No batted ball data";
        const meta = latest.hit_data?.distance ? `${Math.round(latest.hit_data.distance)} ft` : "";
        return `<div class="live-field-card">
          <div class="live-field-topline"><span></span><strong>${escapeHtml(feed.venue_name || "")}</strong></div>
          <svg class="live-field-svg" viewBox="0 0 250 225" role="img" aria-label="Live batted ball field view">
            <defs><clipPath id="${clipId}"><path d="${geometry.wallPath}"/></clipPath></defs>
            <g clip-path="url(#${clipId})"><rect class="field-grass" x="0" y="0" width="250" height="225"/>${stripes}</g>
            <path class="field-shape" d="${geometry.wallPath}"/>
            <path class="field-foul-line" d="M 125 215 L ${geometry.left.x} ${geometry.left.y.toFixed(1)} M 125 215 L ${geometry.right.x} ${geometry.right.y.toFixed(1)}"/>
            <path class="field-infield" d="M 125 210 L 158 177 L 125 144 L 92 177 Z"/>
            <path class="field-home-plate" d="M 120 208 L 130 208 L 129 213 L 125 216 L 121 213 Z"/>
            ${baseShapes}${geometry.labels}${trajectory}${marker}
          </svg>
          <div class="live-field-footer"><strong>${footer}</strong><span>${escapeHtml(meta)}</span></div>
        </div>`;
      }

      function pitchTone(pitch) {
        const text = `${pitch?.call || ""} ${pitch?.description || ""}`.toLowerCase();
        if (pitch?.is_in_play) return "in-play";
        if (text.includes("foul")) {
          const isStrikeoutFoul = Boolean(pitch?.is_out) || text.includes("strikeout") || text.includes("strike 3");
          const strikesBefore = Number(pitch?.count_before?.strikes);
          if (Number.isFinite(strikesBefore)) {
            return strikesBefore < 2 || isStrikeoutFoul ? "strike" : "foul";
          }
          const strikesAfter = Number(pitch?.count_after?.strikes);
          return isStrikeoutFoul || (Number.isFinite(strikesAfter) && strikesAfter <= 2) ? "strike" : "foul";
        }
        if (pitch?.is_strike || text.includes("strike")) return "strike";
        if (pitch?.is_ball || text.includes("ball")) return "ball";
        return "unknown";
      }
      function pitchCoords(pitch, top, bottom) {
        let px = Number(pitch?.p_x);
        let pz = Number(pitch?.p_z);
        if (!Number.isFinite(px) || !Number.isFinite(pz)) {
          const fallback = { 1: [-0.48, 3.08], 2: [0, 3.08], 3: [0.48, 3.08], 4: [-0.48, 2.5], 5: [0, 2.5], 6: [0.48, 2.5], 7: [-0.48, 1.92], 8: [0, 1.92], 9: [0.48, 1.92], 11: [-1.08, 3.22], 12: [1.08, 3.22], 13: [-1.08, 1.72], 14: [1.08, 1.72] }[safeInt(pitch?.zone)];
          if (!fallback) return null;
          [px, pz] = fallback;
        }
        const zoneMid = (top + bottom) / 2;
        const zoneSpan = Math.max(1, top - bottom);
        const x = 85 + (px * 42);
        const y = 94 - (((pz - zoneMid) / zoneSpan) * 86);
        return [Math.max(16, Math.min(154, x)), Math.max(18, Math.min(178, y))];
      }
      function pitchReleaseOffset(feed) {
        const hand = String(feed?.current_pitcher?.throwing_hand || "").trim().toLowerCase();
        if (hand.startsWith("l")) return "-42px";
        if (hand.startsWith("r")) return "42px";
        return "0";
      }
      function strikeZone(feed) {
        const pitches = (feed.current_pitches || []).slice(-12);
        const latest = feed.latest_pitch || pitches[pitches.length - 1] || {};
        const top = [...pitches].reverse().map((p) => Number(p.strike_zone_top)).find(Number.isFinite) || 3.5;
        const bottom = [...pitches].reverse().map((p) => Number(p.strike_zone_bottom)).find(Number.isFinite) || 1.55;
        const releaseOffset = pitchReleaseOffset(feed);
        const markers = pitches.map((pitch, index) => {
          const coords = pitchCoords(pitch, top, bottom);
          if (!coords) return "";
          const [x, y] = coords;
          const latestClass = pitch === latest ? " latest" : "";
          const animateClass = pitch === latest ? " animate" : "";
          const delay = Math.min(0.18, index * 0.018).toFixed(3);
          const title = `${index + 1}. ${pitch.call || pitch.description || "Pitch"}${pitch.start_speed ? ` · ${Number(pitch.start_speed).toFixed(1)} mph` : ""}`;
          return `<g class="strike-zone-pitch-marker${animateClass}" style="--pitch-from-x:${releaseOffset};--pitch-delay:${delay}s"><circle class="strike-zone-pitch ${pitchTone(pitch)}${latestClass}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="6.1"><title>${escapeHtml(title)}</title></circle><text class="strike-zone-count-label" x="${x.toFixed(1)}" y="${y.toFixed(1)}">${index + 1}</text></g>`;
        }).join("");
        const latestCall = latest.call || latest.description || "No pitch data";
        const latestMeta = [latest.pitch_type, latest.start_speed ? `${Number(latest.start_speed).toFixed(1)} mph` : ""].filter(Boolean).join(" · ");
        return `<div class="strike-zone-card">
          <div class="strike-zone-topline"><span></span><strong>Strike Zone</strong></div>
          <svg class="strike-zone-svg" viewBox="0 0 170 190" role="img" aria-label="Live strike zone pitch map">
            <rect class="strike-zone-box" x="50" y="51" width="70" height="86"/>
            <line class="strike-zone-grid" x1="73.3" y1="51" x2="73.3" y2="137"/>
            <line class="strike-zone-grid" x1="96.7" y1="51" x2="96.7" y2="137"/>
            <line class="strike-zone-grid" x1="50" y1="79.7" x2="120" y2="79.7"/>
            <line class="strike-zone-grid" x1="50" y1="108.3" x2="120" y2="108.3"/>
            ${markers}
          </svg>
          <div class="strike-zone-meta"><div><span>Latest</span><strong>${escapeHtml(latestCall)}</strong></div><div class="strike-zone-meta-detail">${escapeHtml(latestMeta)}</div></div>
        </div>`;
      }

      function playTone(resultType) {
        if (["single", "double", "triple", "home_run"].includes(resultType)) return "hit";
        if (["strikeout", "groundout", "flyout", "popout", "lineout", "forceout", "double_play", "sac_fly"].includes(resultType)) return "out";
        if (["walk", "hit_by_pitch", "stolen_base"].includes(resultType)) return "reach";
        if (resultType === "error") return "warning";
        return "neutral";
      }
      function playChip(play) {
        const tone = play.result_type === "home_run" ? "home-run" : playTone(play.result_type);
        return `<span class="play-result-chip ${tone}">${escapeHtml(play.result_label || "Other")}</span>`;
      }
      function fragmentId(...values) {
        return values.filter((value) => value !== undefined && value !== null && value !== "").join("-").replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase() || "detail";
      }
      function batterRecord(feed, batterId) {
        const plays = (feed.completed_plays || []).filter((play) => Number(play.batter?.player_id) === Number(batterId));
        const hitBases = { single: 1, double: 2, triple: 3, home_run: 4 };
        const pa = plays.length;
        const ab = plays.filter((play) => !["walk", "hit_by_pitch", "sac_fly"].includes(play.result_type)).length;
        const hits = plays.filter((play) => ["single", "double", "triple", "home_run"].includes(play.result_type)).length;
        const tb = plays.reduce((total, play) => total + (hitBases[play.result_type] || 0), 0);
        const hr = plays.filter((play) => play.result_type === "home_run").length;
        const strikeouts = plays.filter((play) => play.result_type === "strikeout").length;
        const rbi = plays.reduce((total, play) => total + safeInt(play.runs_scored), 0);
        return { PA: pa, AB: ab, H: hits, TB: tb, HR: hr, K: strikeouts, RBI: rbi };
      }
      function opponentForPlay(feed, play) {
        const side = play?.batting_side || (String(play?.half_inning || "").toLowerCase() === "top" ? "away" : "home");
        return side === "away" ? feed.home_team || "Opponent" : feed.away_team || "Opponent";
      }
      function gameLogGrid(title, eyebrow, rows) {
        const header = `<span>Date</span><span>PA</span><span>AB</span><span>K</span>`;
        const body = rows.map((row) => `<strong>${escapeHtml(row.date || "-")}</strong><strong>${escapeHtml(row.PA ?? "-")}</strong><strong>${escapeHtml(row.AB ?? "-")}</strong><strong>${escapeHtml(row.K ?? row.SO ?? "-")}</strong>`).join("");
        return `<div class="play-detail-gamelog">
          <div class="play-detail-gamelog-head"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(eyebrow)}</span></div>
          <div class="play-detail-gamelog-grid">${header}${body}</div>
        </div>`;
      }
      function modalGameLog(feed, play, batter) {
        const opponent = opponentForPlay(feed, play);
        const key = `${Number(batter?.player_id)}|${String(opponent || "").toLowerCase()}`;
        const stored = OPPONENT_GAME_LOGS[key];
        if (stored?.rows?.length) {
          return gameLogGrid(stored.title || `Games vs ${opponent}`, `Last ${stored.rows.length}`, stored.rows);
        }
        const record = batterRecord(feed, batter?.player_id);
        return gameLogGrid(`This game vs ${opponent}`, "Live", [{
          date: "Today",
          PA: record.PA,
          AB: record.AB,
          K: record.K,
        }]);
      }
      function modalFace(player, label, className) {
        player = player || {};
        const name = player.name || label;
        const image = imageHtml(player.headshot, `${name} headshot`, "play-detail-face-img");
        const fallback = `<span class="play-detail-face-placeholder">${escapeHtml(String(name || "?").trim().slice(0, 1).toUpperCase() || "?")}</span>`;
        return `<div class="play-detail-person ${className}">
          ${image || fallback}
          <div class="play-detail-face-copy"><span>${escapeHtml(label)}</span><strong>${escapeHtml(name)}</strong></div>
        </div>`;
      }
      function modalMatchupFaces(batter, pitcher, gameLogHtml) {
        return `<div class="play-detail-matchup-strip">
          ${modalFace(batter, "Batter", "batter")}
          ${gameLogHtml || '<span class="play-detail-vs">VS</span>'}
          ${modalFace(pitcher, "Pitcher", "pitcher")}
        </div>`;
      }
      function modalHtml(feed, play, modalId, closeTarget) {
        const batter = play.batter || {};
        const pitcher = play.pitcher || {};
        const record = batterRecord(feed, batter.player_id);
        const stats = Object.entries(record).map(([label, value]) => `<div class="play-detail-stat"><span>${label}</span><strong>${value}</strong></div>`).join("");
        const zoneFeed = { current_pitches: play.pitches || [], latest_pitch: (play.pitches || []).slice(-1)[0], current_pitcher: pitcher };
        const inning = `${play.half_inning || ""} ${play.inning || ""}`.trim();
        const runText = play.runs_scored ? `+${play.runs_scored} run${play.runs_scored === 1 ? "" : "s"}` : "No runs scored on this play.";
        return `<div id="${modalId}" class="play-detail-modal" role="dialog" aria-modal="true">
          <a class="play-detail-scrim" href="#${closeTarget}" aria-label="Close play detail"></a>
          <div class="play-detail-modal-card">
            <div class="play-detail-modal-head"><div><span>At-Bat Detail</span><strong>${escapeHtml(batter.name || "Batter")} vs ${escapeHtml(pitcher.name || "Pitcher")}</strong></div><a class="play-detail-close" href="#${closeTarget}" aria-label="Close play detail">&times;</a></div>
            ${modalMatchupFaces(batter, pitcher)}
            <div class="play-detail-layout">
              <div class="play-detail-card"><h3>${escapeHtml(play.result_label || "Play")}</h3><p>${escapeHtml(inning)}</p><p>${escapeHtml(play.description || "Play recorded.")}</p><div class="play-detail-stat-grid">${stats}</div>${modalGameLog(feed, play, batter)}</div>
              <div class="play-detail-card"><h3>At-Bat Strike Zone</h3>${strikeZone(zoneFeed)}</div>
              <div class="play-detail-card"><h3>Game Record</h3><p>${escapeHtml(batter.name || "Batter")} has ${record.H} hit(s), ${record.TB} total base(s), and ${record.RBI} run(s) driven in this game.</p></div>
              <div class="play-detail-card"><h3>Efficiency By Inning</h3><p>${escapeHtml(runText)}</p></div>
            </div>
          </div>
        </div>`;
      }
      function playsPanel(feed) {
        const plays = feed.completed_plays?.length ? feed.completed_plays : feed.recent_plays || [];
        const panelId = fragmentId("live-plays", GAME_PK);
        if (!plays.length) return `<div id="${panelId}" class="live-play-panel"><div class="live-play-heading">Plays</div><div class="live-play-list"><div class="live-play-empty">No completed plays yet.</div></div></div>`;
        const reversed = [...plays].reverse();
        const rows = [];
        const modals = [];
        reversed.forEach((play, index) => {
          const playIndex = play.play_index ?? `recent-${index + 1}`;
          const modalId = fragmentId("play-detail-live", GAME_PK, playIndex, index + 1);
          const runsBadge = play.runs_scored ? `<span class="play-score-badge">+${play.runs_scored} R</span>` : "";
          const batter = play.batter || {};
          const pitcher = play.pitcher || {};
          rows.push(`<a class="live-play-row${play.runs_scored || play.is_scoring_play ? " scoring-play" : ""}" href="#${modalId}">
            ${playChip(play)}
            <div class="live-play-matchup"><div class="live-play-player-icons">${imageHtml(batter.headshot, `${batter.name} headshot`)}${imageHtml(pitcher.headshot, `${pitcher.name} headshot`)}</div><div class="live-play-matchup-copy"><strong>${escapeHtml(batter.name || "Batter")}</strong><span>vs ${escapeHtml(pitcher.name || "Pitcher")}</span></div></div>
            <div class="live-play-description">${escapeHtml(play.description || "Play recorded.")}</div>
            <div class="live-play-meta">${escapeHtml(`${play.half_inning || ""} ${play.inning || ""}`.trim())}${runsBadge}</div>
          </a>`);
          modals.push(modalHtml(feed, play, modalId, panelId));
        });
        return `<div id="${panelId}" class="live-play-panel"><div class="live-play-heading">Plays</div><div class="live-play-list">${rows.join("")}</div></div>${modals.join("")}`;
      }

      function renderLive(feed) {
        return `${gameHeader(feed)}
          ${absTracker(feed)}
          <div class="live-game-layout">
            <div class="live-main-area">
              <div class="live-situation-panel live-at-plate-area">
                <div class="metric-label">At The Plate</div>
                <div class="current-hitters">${playerCard("Batter", feed.current_batter)}${playerCard("On Deck", feed.on_deck)}</div>
                <div class="live-count-board">${countDots("Balls", "ball", feed.balls, 3)}${countDots("Strikes", "strike", feed.strikes, 2)}${countDots("Outs", "out", feed.outs, 3)}<span class="foul-count">Fouls ${safeInt(feed.fouls)}</span></div>
              </div>
              <div class="live-situation-panel live-field-area">${fieldView(feed)}</div>
              <div class="live-situation-panel live-zone-area">${strikeZone(feed)}</div>
            </div>
            <div class="live-side-area">${pitcherStrip(feed.current_pitcher)}${playsPanel(feed)}</div>
          </div>`;
      }

      function modalIsOpen() {
        return String(parentWindow.location.hash || "").startsWith("#play-detail-live-");
      }

      function markUpdaterActive() {
        const root = parentDocument.querySelector(".live-game-refresh-shell");
        if (root) {
          root.dataset.liveUpdater = "client";
          root.dataset.livePolling = "active";
        }
      }

      async function refreshLive() {
        if (inflight || modalIsOpen()) return;
        inflight = true;
        try {
          const response = await fetch(`${FEED_URL}?ts=${Date.now()}`, { cache: "no-store" });
          if (!response.ok) return;
          const data = await response.json();
          const timestamp = data?.metaData?.timeStamp || "";
          const root = parentDocument.querySelector(".live-game-refresh-shell");
          if (!root) return;
          root.dataset.liveCheckedAt = String(Date.now());
          root.dataset.liveUpdater = "client";
          root.dataset.livePolling = "active";
          if (timestamp && timestamp === lastTimestamp) return;
          const feed = parseFeed(data);
          const playsList = root.querySelector(".live-play-list");
          const playsScrollTop = playsList ? playsList.scrollTop : null;
          const nextTimestamp = timestamp || String(Date.now());
          root.classList.add("is-live-patching");
          root.innerHTML = renderLive(feed);
          if (playsScrollTop !== null) {
            const nextPlaysList = root.querySelector(".live-play-list");
            if (nextPlaysList) nextPlaysList.scrollTop = playsScrollTop;
          }
          root.classList.remove("is-live-patching");
          root.dataset.livePatchedAt = nextTimestamp;
          root.dataset.liveUpdater = "client";
          root.dataset.livePolling = "active";
          lastTimestamp = nextTimestamp;
          previousScores = { away: feed.away_score, home: feed.home_score };
        } catch (error) {
          // Keep the existing DOM if the client-side live fetch fails.
        } finally {
          inflight = false;
        }
      }

      setTimeout(markUpdaterActive, 300);
      setTimeout(refreshLive, 1800);
      setInterval(refreshLive, 5000);
    })();
    </script>
    """
    components.html(
        updater_html.replace("__GAME_PK__", json.dumps(int(game_pk))).replace(
            "__INITIAL_TIMESTAMP__",
            json.dumps(initial_timestamp),
        ).replace(
            "__OPPONENT_GAME_LOGS__",
            json.dumps(opponent_game_logs),
        ),
        height=0,
    )


def batter_play_rows(live_feed, batter_id):
    batter_id = pd.to_numeric(batter_id, errors="coerce")
    if pd.isna(batter_id):
        return []
    return [
        play
        for play in (live_feed.get("completed_plays") or [])
        if pd.to_numeric(
            (play.get("batter") or {}).get("player_id"),
            errors="coerce",
        )
        == int(batter_id)
    ]


def batter_game_record(live_feed, batter_id):
    plays = batter_play_rows(live_feed, batter_id)
    hit_bases = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
    pa = len(plays)
    ab = sum(
        1
        for play in plays
        if safe_text(play.get("result_type"))
        not in {"walk", "hit_by_pitch", "sac_fly"}
    )
    hits = sum(1 for play in plays if safe_text(play.get("result_type")) in HIT_PLAY_TYPES)
    total_bases = sum(hit_bases.get(safe_text(play.get("result_type")), 0) for play in plays)
    home_runs = sum(1 for play in plays if safe_text(play.get("result_type")) == "home_run")
    strikeouts = sum(1 for play in plays if safe_text(play.get("result_type")) == "strikeout")
    runs_batted_in = sum(int(safe_value(play.get("runs_scored"), 0)) for play in plays)
    return {
        "PA": pa,
        "AB": ab,
        "H": hits,
        "TB": total_bases,
        "HR": home_runs,
        "K": strikeouts,
        "RBI": runs_batted_in,
    }


def BatterInningEfficiencyChart(live_feed, batter_id):
    plays = batter_play_rows(live_feed, batter_id)
    if not plays:
        return ""
    hit_bases = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
    inning_totals = {inning: {"pa": 0, "tb": 0} for inning in range(1, 10)}
    for play in plays:
        inning = pd.to_numeric(play.get("inning"), errors="coerce")
        if pd.isna(inning):
            continue
        inning = max(1, min(9, int(inning)))
        inning_totals[inning]["pa"] += 1
        inning_totals[inning]["tb"] += hit_bases.get(
            safe_text(play.get("result_type")),
            0,
        )
    max_value = max(
        (values["tb"] / values["pa"] if values["pa"] else 0)
        for values in inning_totals.values()
    )
    max_value = max(max_value, 1.0)
    bars = []
    for inning, values in inning_totals.items():
        efficiency = values["tb"] / values["pa"] if values["pa"] else 0
        height = (efficiency / max_value) * 74
        x = 24 + ((inning - 1) * 25)
        y = 96 - height
        label = f"{efficiency:.2f} TB/PA" if values["pa"] else "No PA"
        bars.append(
            f'<rect x="{x}" y="{y:.1f}" width="14" height="{height:.1f}" '
            'fill="#245f96"><title>'
            f"{escape(label)}</title></rect>"
            f'<text x="{x + 7}" y="114" text-anchor="middle">{inning}</text>'
        )
    return (
        '<svg class="inning-efficiency-svg" viewBox="0 0 260 126" role="img" '
        'aria-label="Batter efficiency by inning">'
        '<line x1="18" y1="96" x2="248" y2="96" stroke="#d8dee6"/>'
        '<text x="18" y="16" fill="#718096" font-size="9" font-weight="800">'
        'TB / PA by inning</text>'
        f'{"".join(bars)}</svg>'
    )


def selected_live_play(live_feed):
    selected_index = safe_text(current_query_value("play_index"))
    if not selected_index:
        return None
    for play in live_feed.get("completed_plays") or []:
        if safe_text(play.get("play_index")) == selected_index:
            return play
    return None


def dismiss_play_detail_dialog():
    st.query_params.pop("play_index", None)


@st.dialog(
    "Play Detail",
    width="large",
    on_dismiss=dismiss_play_detail_dialog,
)
def render_play_detail_dialog(live_feed, play):
    batter = play.get("batter") or {}
    pitcher = play.get("pitcher") or {}
    batter_name = safe_text(batter.get("name"), default="Batter")
    pitcher_name = safe_text(pitcher.get("name"), default="Pitcher")
    description = safe_text(play.get("description"), default="Play recorded.")
    inning = f"{safe_text(play.get('half_inning')).title()} {safe_text(play.get('inning'))}".strip()
    runs = int(safe_value(play.get("runs_scored"), 0))
    record = batter_game_record(live_feed, batter.get("player_id"))
    pitch_list = play.get("pitches") or []
    zone_feed = {
        "current_pitches": pitch_list,
        "latest_pitch": pitch_list[-1] if pitch_list else None,
        "current_pitcher": pitcher or live_feed.get("current_pitcher"),
    }
    stat_items = "".join(
        '<div class="play-detail-stat">'
        f"<span>{escape(label)}</span><strong>{escape(safe_text(value, default='0'))}</strong>"
        "</div>"
        for label, value in record.items()
    )
    run_text = f"+{runs} run{'s' if runs != 1 else ''}" if runs else "No runs scored on this play."
    st.markdown(
        f"""
        <div class="play-detail-layout">
            <div class="play-detail-card">
                <h3>{escape(batter_name)} vs {escape(pitcher_name)}</h3>
                <p>{escape(inning)} | {escape(play.get("result_label", "Play"))}</p>
                <p>{escape(description)}</p>
                <div class="play-detail-stat-grid">{stat_items}</div>
            </div>
            <div class="play-detail-card">
                <h3>At-Bat Strike Zone</h3>
                {StrikeZoneView(zone_feed)}
            </div>
            <div class="play-detail-card">
                <h3>Game Record</h3>
                <p>{escape(batter_name)} has {record["H"]} hit(s), {record["TB"]} total base(s), and {record["RBI"]} run(s) driven in this game.</p>
            </div>
            <div class="play-detail-card">
                <h3>Efficiency By Inning</h3>
                <p>{escape(run_text)}</p>
                {BatterInningEfficiencyChart(live_feed, batter.get("player_id"))}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def LiveGameHeader(
    away_team,
    home_team,
    away_score,
    home_score,
    status_title,
    detailed_state,
    score_changes,
):
    return (
        '<div class="live-game-scorebug">'
        '<div class="live-game-team">'
        f"{team_logo_img_html(away_team, alt=away_team)}"
        f"<span>{escape(away_team)}</span>"
        f'{ScoreChangeView(away_score, score_changes.get("away", 0))}'
        "</div>"
        '<div class="live-game-status">'
        f"<strong>{escape(status_title)}</strong>"
        f"<span>{escape(detailed_state)}</span>"
        "</div>"
        '<div class="live-game-team">'
        f'{ScoreChangeView(home_score, score_changes.get("home", 0))}'
        f"<span>{escape(home_team)}</span>"
        f"{team_logo_img_html(home_team, alt=home_team)}"
        "</div>"
        "</div>"
    )


HOME_RUN_NOTICE_SECONDS = 6.8


def _live_game_animation_state(game_pk, live_feed):
    key = f"live_game_previous_state_{int(game_pk)}"
    home_run_until_key = f"live_game_home_run_until_{int(game_pk)}"
    previous = st.session_state.get(key)
    latest_play = live_feed.get("latest_completed_play") or {}
    latest_pitch = live_feed.get("latest_pitch") or {}
    latest_contact = live_feed.get("latest_batted_ball") or {}
    latest_contact_key = (
        _contact_play_key(latest_contact)
        if isinstance(latest_contact, dict) and latest_contact.get("hit_data")
        else None
    )
    current = {
        "away_score": pd.to_numeric(live_feed.get("away_score"), errors="coerce"),
        "home_score": pd.to_numeric(live_feed.get("home_score"), errors="coerce"),
        "latest_play_key": _live_play_key(latest_play) if latest_play else None,
        "latest_play_type": latest_play.get("result_type"),
        "latest_pitch_key": _live_pitch_key(latest_pitch) if latest_pitch else None,
        "latest_contact_key": latest_contact_key,
        "current_batter_id": (live_feed.get("current_batter") or {}).get(
            "player_id"
        ),
    }
    score_changes = {"away": 0, "home": 0}
    animation_keys = {
        "pitch": None,
        "contact": None,
        "play": None,
        "home_run": False,
    }
    home_run = False
    batter_changed = False
    if isinstance(previous, dict):
        for side in ("away", "home"):
            old_score = pd.to_numeric(
                previous.get(f"{side}_score"),
                errors="coerce",
            )
            new_score = current[f"{side}_score"]
            if pd.notna(old_score) and pd.notna(new_score) and new_score > old_score:
                score_changes[side] = int(new_score - old_score)
        home_run = (
            current["latest_play_key"] is not None
            and current["latest_play_key"] != previous.get("latest_play_key")
            and current["latest_play_type"] == "home_run"
        )
        if home_run:
            st.session_state[home_run_until_key] = time.time() + HOME_RUN_NOTICE_SECONDS
            animation_keys["home_run"] = True
        for event_name, state_key in (
            ("pitch", "latest_pitch_key"),
            ("contact", "latest_contact_key"),
            ("play", "latest_play_key"),
        ):
            if (
                current[state_key] is not None
                and current[state_key] != previous.get(state_key)
            ):
                animation_keys[event_name] = current[state_key]
        batter_changed = (
            current["current_batter_id"] is not None
            and previous.get("current_batter_id") is not None
            and current["current_batter_id"]
            != previous.get("current_batter_id")
        )
    if st.session_state.get(home_run_until_key, 0) > time.time():
        home_run = True
    st.session_state[key] = current
    return score_changes, home_run, batter_changed, animation_keys


def _contact_play_key(play):
    play = play if isinstance(play, dict) else {}
    hit_data = play.get("hit_data") or {}
    play_index = play.get("play_index")
    if play_index is not None:
        return ("play_index", play_index)
    return (
        play.get("inning"),
        play.get("half_inning"),
        safe_text((play.get("batter") or {}).get("player_id")),
        safe_text(play.get("result_type")),
        safe_text(play.get("description")),
        safe_text(hit_data.get("x")),
        safe_text(hit_data.get("y")),
        safe_text(hit_data.get("location")),
    )

def _merge_contact_play_history(game_pk, live_feed):
    live_feed = live_feed if isinstance(live_feed, dict) else {}
    history_key = f"live_game_contact_history_{int(game_pk)}"
    persisted_loaded_key = f"live_game_contact_history_loaded_{int(game_pk)}"
    if st.session_state.get(persisted_loaded_key):
        persisted_contacts = []
    else:
        persisted_contacts = database.load_live_game_contacts(game_pk)
        st.session_state[persisted_loaded_key] = True
    current_contacts = [
        play
        for play in (live_feed.get("contact_plays") or [])
        if isinstance(play, dict) and play.get("hit_data")
    ]
    history = st.session_state.get(history_key, [])
    existing_keys = {
        _contact_play_key(play)
        for play in [*persisted_contacts, *history]
    }
    has_new_contact = any(
        _contact_play_key(play) not in existing_keys
        for play in current_contacts
    )
    merged = []
    seen = set()
    for play in [*persisted_contacts, *history, *current_contacts]:
        play_key = _contact_play_key(play)
        if play_key in seen:
            continue
        seen.add(play_key)
        merged.append(play)
    merged = merged[-120:]
    st.session_state[history_key] = merged
    live_feed["contact_plays"] = merged
    if has_new_contact and merged:
        database.save_live_game_contacts(game_pk, merged)
    if current_contacts:
        live_feed["_latest_contact_play_key"] = _contact_play_key(current_contacts[-1])
    return live_feed


def _live_game_feed_state(game_pk):
    feed_key = f"live_game_latest_feed_{int(game_pk)}"
    final_key = f"live_game_final_{int(game_pk)}"
    updated_key = f"live_game_updated_at_{int(game_pk)}"

    if st.session_state.get(final_key) and st.session_state.get(feed_key):
        return st.session_state[feed_key], False

    try:
        feed = load_live_game_feed(int(game_pk))
        if feed:
            feed = _merge_contact_play_history(game_pk, feed)
            st.session_state[feed_key] = feed
            st.session_state[updated_key] = time.time()
            if safe_text(feed.get("abstract_state")).lower() == "final":
                st.session_state[final_key] = True
            return feed, False
    except Exception:
        pass

    return st.session_state.get(feed_key, {}), True


def dismiss_live_game_dialog():
    game_pk = st.session_state.get("selected_boxscore_game_pk")
    if game_pk is not None:
        st.session_state.pop(f"live_game_previous_state_{int(game_pk)}", None)
        st.session_state.pop(f"live_game_home_run_until_{int(game_pk)}", None)
    st.session_state.selected_boxscore_game_pk = None
    st.session_state.selected_game = "All Games"
    st.query_params.pop("game_pk", None)
    st.query_params.pop("game_tab", None)
    st.query_params.pop("play_index", None)


LIVE_GAME_DETAIL_TABS = (
    ("Live", "live"),
    ("Stats", "stats"),
    ("Box Score", "box_score"),
)


def selected_live_game_detail_view():
    selected_slug = safe_text(
        current_query_value("game_tab"),
        default="live",
    ).lower()
    selected_slug = selected_slug.replace("-", "_").replace(" ", "_")
    for label, slug in LIVE_GAME_DETAIL_TABS:
        if selected_slug == slug:
            return label
    return "Live"


def select_live_game_detail_tab(game_pk, slug):
    st.session_state.selected_boxscore_game_pk = int(game_pk)
    st.query_params["view"] = "Games"
    st.query_params["game_pk"] = str(int(game_pk))
    st.query_params["game_tab"] = slug
    st.query_params.pop("play_index", None)


def render_live_game_header_tabs(game_pk, active_label):
    tab_columns = st.columns(
        [1, 1, 1],
        gap="small",
        vertical_alignment="center",
    )
    for column, (label, slug) in zip(tab_columns, LIVE_GAME_DETAIL_TABS):
        state = "active" if label == active_label else "idle"
        with column:
            with st.container(key=f"live_game_tab_{state}_{slug}_{int(game_pk)}"):
                st.button(
                    label,
                    key=f"live_game_tab_button_{slug}_{int(game_pk)}",
                    on_click=select_live_game_detail_tab,
                    args=(int(game_pk), slug),
                    use_container_width=True,
                )


def live_game_header_tabs_html(game_pk, active_label):
    tab_links = []
    for label, slug in LIVE_GAME_DETAIL_TABS:
        params = {
            "view": "Games",
            "game_pk": str(int(game_pk)),
            "game_tab": slug,
        }
        active_class = " active" if label == active_label else ""
        tab_links.append(
            f'<a class="live-game-header-tab{active_class}" '
            f'href="?{escape(urlencode(params), quote=True)}" '
            'target="_self">'
            f"{escape(label)}</a>"
        )
    return (
        '<nav class="live-game-header-tabs" aria-label="Live game views">'
        f'{"".join(tab_links)}</nav>'
    )


@st.fragment
def render_live_game_live_tab(schedule_df, game_pk):
    row = selected_game_row(schedule_df, game_pk)
    if row is None:
        st.warning("This game is no longer available in the selected schedule.")
        return

    live_feed, feed_error = _live_game_feed_state(game_pk)
    # Freeze one response for the whole render so batter, count, bases,
    # pitcher stats, and plays always advance together.
    live_feed = deepcopy(live_feed)

    away_team = safe_text(
        live_feed.get("away_team"),
        default=row_text(row, "away_team", default="Away"),
    )
    home_team = safe_text(
        live_feed.get("home_team"),
        default=row_text(row, "home_team", default="Home"),
    )
    away_score = live_feed.get("away_score")
    if away_score is None:
        away_score = row.get("away_score")
    home_score = live_feed.get("home_score")
    if home_score is None:
        home_score = row.get("home_score")
    inning = safe_text(
        live_feed.get("inning_ordinal"),
        default=row_text(row, "current_inning_ordinal", "current_inning"),
    )
    inning_state = safe_text(
        live_feed.get("inning_state"),
        default=row_text(row, "inning_state", "inning_half"),
    )
    detailed_state = safe_text(
        live_feed.get("detailed_state"),
        default=game_status_text(row),
    )
    status_title = (
        f"{inning_state} {inning}".strip()
        if safe_text(live_feed.get("abstract_state")).lower() == "live"
        else detailed_state
    )
    score_changes, home_run, batter_changed, animation_keys = _live_game_animation_state(
        game_pk,
        live_feed,
    )

    header_html = LiveGameHeader(
        away_team,
        home_team,
        away_score,
        home_score,
        status_title,
        detailed_state,
        score_changes,
    )
    home_run_html = ""
    if home_run:
        home_run_animation_class = " animate" if animation_keys.get("home_run") else ""
        home_run_html = (
            f'<div class="home-run-notice{home_run_animation_class}" role="status" aria-label="Home Run">'
            '<span class="home-run-fire" aria-hidden="true">'
            '<svg viewBox="0 0 1200 90" preserveAspectRatio="none" '
            'xmlns="http://www.w3.org/2000/svg">'
            '<path class="flame-back" d="M0 90V70 '
            'C36 72 42 39 71 52 C94 62 104 22 132 40 '
            'C164 62 175 20 202 33 C229 47 232 9 263 31 '
            'C294 53 307 18 335 39 C362 59 373 15 406 31 '
            'C438 46 442 11 475 35 C505 56 520 19 552 38 '
            'C586 58 595 11 626 32 C660 55 675 18 708 39 '
            'C742 60 752 13 784 31 C818 50 826 15 858 37 '
            'C890 59 904 20 936 38 C968 56 978 17 1011 34 '
            'C1046 52 1056 23 1088 43 C1124 65 1138 37 1166 55 '
            'C1184 66 1193 63 1200 60 V90Z"/>'
            '<path class="flame-mid" d="M0 90V78 '
            'C43 79 54 58 84 66 C112 73 116 37 145 51 '
            'C174 66 188 31 218 47 C245 62 257 25 286 45 '
            'C319 67 333 33 365 51 C397 70 405 35 438 50 '
            'C470 65 486 29 519 48 C553 69 566 35 599 51 '
            'C634 68 647 29 681 49 C715 68 731 34 764 51 '
            'C798 69 813 31 846 48 C881 68 894 36 927 52 '
            'C961 69 976 33 1009 49 C1042 66 1057 39 1088 55 '
            'C1123 73 1144 50 1171 63 C1187 71 1194 69 1200 66 V90Z"/>'
            '<path class="flame-core" d="M28 90V82 '
            'C70 76 76 62 103 70 C132 78 135 50 160 61 '
            'C190 75 204 44 232 60 C263 77 274 48 302 63 '
            'C333 80 348 49 377 64 C409 80 422 52 453 65 '
            'C488 80 502 47 532 64 C565 81 581 52 612 66 '
            'C646 82 660 48 692 64 C728 82 742 52 775 66 '
            'C810 82 826 50 858 64 C893 81 909 52 941 66 '
            'C976 82 992 54 1025 68 C1059 82 1078 61 1107 70 '
            'C1138 80 1160 72 1178 76 V90Z"/>'
            '</svg></span>'
            "<strong>Home Run</strong></div>"
        )
    live_layout_html = (
        '<div class="live-game-refresh-shell">'
        f"{header_html}"
        f"{home_run_html}"
        f"{AbsChallengeTrackerView(live_feed)}"
        '<div class="live-game-layout">'
        '<div class="live-main-area">'
        '<div class="live-situation-panel live-at-plate-area">'
        '<div class="metric-label">At The Plate</div>'
        f"{AtPlateView(live_feed, batter_changed, game_pk)}"
        '<div class="live-count-board">'
        f'{CountDotsView(live_feed.get("balls"), live_feed.get("strikes"))}'
        f'{OutsDotsView(live_feed.get("outs"))}'
        f'<span class="foul-count">Fouls {int(safe_value(live_feed.get("fouls"), 0))}</span>'
        "</div></div>"
        '<div class="live-situation-panel live-field-area">'
        f'{LiveFieldView(live_feed, animation_keys.get("contact"))}'
        "</div>"
        '<div class="live-situation-panel live-zone-area">'
        f'{StrikeZoneView(live_feed, animation_keys.get("pitch"))}'
        "</div>"
        "</div>"
        '<div class="live-side-area">'
        f'{_live_pitcher_strip_html(live_feed.get("current_pitcher"), game_pk)}'
        f'{LivePlaysPanel(live_feed, game_pk, animation_keys.get("play"))}'
        "</div></div></div>"
    )
    st.markdown(live_layout_html, unsafe_allow_html=True)
    LiveGameClientUpdater(game_pk, live_feed)
    selected_play = selected_live_play(live_feed)
    if selected_play is not None:
        render_play_detail_dialog(live_feed, selected_play)


@st.fragment
def render_live_game_contact_tab(schedule_df, game_pk):
    row = selected_game_row(schedule_df, game_pk)
    if row is None:
        st.warning("This game is no longer available in the selected schedule.")
        return

    live_feed, _feed_error = _live_game_feed_state(game_pk)
    live_feed = deepcopy(live_feed)
    if not live_feed:
        st.info("Stats will appear when the live feed starts.")
        return
    st.markdown(LiveContactTabView(live_feed), unsafe_allow_html=True)


def render_live_game_box_score_tab(row, game_pk):
    team_options = boxscore_team_options(row)
    option_labels = [option["label"] for option in team_options]
    side_by_label = {
        option["label"]: option["side"]
        for option in team_options
    }
    selected_team_label = render_box_tabs(
        f"boxscore-team-tabs-{game_pk}",
        option_labels,
        f"boxscore_team_side_{game_pk}",
        option_labels[0],
    )
    selected_side = side_by_label[selected_team_label]

    try:
        boxscore = load_game_boxscore(int(game_pk))
    except Exception:
        boxscore = {"batting": pd.DataFrame(), "pitching": pd.DataFrame()}
        st.warning("The live box score is temporarily unavailable.")

    boxscore_group = render_box_tabs(
        f"boxscore-group-tabs-{game_pk}",
        ["Hitters", "Pitchers"],
        f"boxscore_group_{game_pk}",
        "Hitters",
    )
    season_value = pd.to_datetime(row.get("game_date"), errors="coerce")
    season_value = (
        int(season_value.year)
        if pd.notna(season_value)
        else int(st.session_state.selected_game_date.year)
    )
    if boxscore_group == "Hitters":
        render_boxscore_dataframe(
            filter_boxscore_team(boxscore.get("batting", pd.DataFrame()), selected_side),
            ["Lineup", "Pos", "AB", "R", "H", "RBI", "BB", "SO", "HR", "SB", "AVG", "OPS"],
            key=f"boxscore_hitters_{game_pk}",
            player_group="batting",
            season_value=season_value,
            game_pk=game_pk,
        )
    else:
        render_boxscore_dataframe(
            filter_boxscore_team(boxscore.get("pitching", pd.DataFrame()), selected_side),
            ["IP", "H", "R", "ER", "BB", "SO", "HR", "PC-ST", "ERA", "WHIP"],
            key=f"boxscore_pitchers_{game_pk}",
            player_group="pitching",
            season_value=season_value,
            game_pk=game_pk,
        )


@st.dialog(
    "Game Center",
    width="large",
    on_dismiss=dismiss_live_game_dialog,
)
def render_live_game_dialog(schedule_df, game_pk):
    row = selected_game_row(schedule_df, game_pk)
    if row is None:
        st.warning("This game is no longer available in the selected schedule.")
        return
    detail_view = render_box_tabs(
        f"live-game-detail-tabs-{game_pk}",
        ["Live", "Stats", "Box Score"],
        f"live_game_detail_view_{game_pk}",
        "Live",
    )
    if detail_view == "Live":
        render_live_game_live_tab(schedule_df, game_pk)
    elif detail_view == "Stats":
        render_live_game_contact_tab(schedule_df, game_pk)
    else:
        render_live_game_box_score_tab(row, game_pk)


def render_live_game_section(schedule_df, game_pk, batters_df=None):
    row = selected_game_row(schedule_df, game_pk)
    if row is None:
        st.warning("This game is no longer available in the selected schedule.")
        return

    away_team = row_text(row, "away_team", default="Away")
    home_team = row_text(row, "home_team", default="Home")
    status = game_status_text(row)
    heading = f"{display_team_code(row, 'away')} @ {display_team_code(row, 'home')}"
    detail_view = selected_live_game_detail_view()
    with st.container(key=f"live_game_compact_header_{int(game_pk)}"):
        back_col, header_col, tabs_col = st.columns(
            [0.045, 0.565, 0.39],
            gap="small",
            vertical_alignment="center",
        )
        with back_col:
            if render_universal_back_button(
                f"live_game_{int(game_pk)}",
                help_text="Back to all games",
            ):
                dismiss_live_game_dialog()
                st.rerun(scope="app")
        with header_col:
            st.markdown(
                f"""
                <div class="live-game-section compact">
                    <div class="live-game-section-heading">
                        <div class="live-game-section-title">
                            <span>Game Center</span>
                            <strong>{escape(heading)}</strong>
                            <em>{escape(status)}</em>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with tabs_col:
            render_live_game_header_tabs(game_pk, detail_view)
    if detail_view == "Live":
        with st.container(key=f"live_game_live_shell_{int(game_pk)}"):
            render_live_game_live_tab(schedule_df, game_pk)
        render_live_projected_lineups(row, game_pk, batters_df)
    elif detail_view == "Stats":
        render_live_game_contact_tab(schedule_df, game_pk)
    else:
        render_live_game_box_score_tab(row, game_pk)


def selected_boxscore_game_pk(schedule_df):
    game_pk = st.session_state.get("selected_boxscore_game_pk")
    query_game_pk = pd.to_numeric(current_query_value("game_pk"), errors="coerce")
    current_game_pk = pd.to_numeric(game_pk, errors="coerce")
    if pd.notna(query_game_pk) and (
        pd.isna(current_game_pk) or int(current_game_pk) != int(query_game_pk)
    ):
        game_pk = int(query_game_pk)
        st.session_state.selected_boxscore_game_pk = game_pk
    if selected_game_row(schedule_df, game_pk) is None:
        return None
    return int(game_pk)


def render_selected_game_boxscore(schedule_df, batters_df=None):
    game_pk = selected_boxscore_game_pk(schedule_df)
    if game_pk is None:
        return False
    render_live_game_section(schedule_df, int(game_pk), batters_df=batters_df)
    return True


@st.fragment
def render_games_tab(schedule_df, filtered_schedule_df, selected_game, selected_date, batters_df=None):
    if render_selected_game_boxscore(schedule_df, batters_df=batters_df):
        return

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

    st.html(
        '<div class="research-table-note">'
        "Click a game or score to open its live box score."
        "</div>"
    )

    render_live_schedule_table(filtered_schedule_df)


BATTER_STREAK_METRICS = [
    {"label": "Hits", "stat": "H", "threshold": 1},
    {"label": "H + R + RBI", "stat": "H_R_RBI", "threshold": 2},
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


def add_composite_streak_columns(df):
    if df is None or df.empty:
        return df
    result = df.copy()
    if all(column in result.columns for column in ("H", "R", "RBI")):
        result["H_R_RBI"] = sum(
            pd.to_numeric(result[column], errors="coerce").fillna(0)
            for column in ("H", "R", "RBI")
        )
    return result


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
        game_state = row_text(row, "abstract_game_state").lower()
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


def live_streak_game_pks(schedule):
    return tuple(row[0] for row in live_streak_game_rows(schedule))


def apply_live_streak_schedule_context(frame, game_rows):
    if frame is None or frame.empty or "game_pk" not in frame.columns:
        return frame
    context = {
        int(game_pk): {
            "game": game_label,
            "abstract_game_state": abstract_state,
            "game_status": game_status,
        }
        for game_pk, game_label, abstract_state, game_status in game_rows
    }
    result = frame.copy()
    numeric_game_pk = pd.to_numeric(result["game_pk"], errors="coerce")
    for column in ("game", "abstract_game_state", "game_status"):
        existing_values = (
            result[column].tolist()
            if column in result.columns
            else [""] * len(result)
        )
        result[column] = [
            context.get(int(game_pk), {}).get(column, row_value)
            if pd.notna(game_pk)
            else row_value
            for game_pk, row_value in zip(numeric_game_pk, existing_values)
        ]
    return result


def collect_live_stats_from_games(game_rows):
    batting_frames = []
    pitching_frames = []

    def load_one_game(game_pk, game_label="", abstract_state="", game_status=""):
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
            executor.submit(
                load_one_game,
                *(game_row if isinstance(game_row, tuple) else (game_row,)),
            )
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
def start_live_streak_monitor(game_pks):
    game_pks = tuple(int(game_pk) for game_pk in game_pks)
    state = {
        "lock": Lock(),
        "ready": Event(),
        "batting": pd.DataFrame(),
        "pitching": pd.DataFrame(),
        "updated_at": None,
    }

    if not game_pks:
        return state

    def refresh_forever():
        while True:
            try:
                batting, pitching = collect_live_stats_from_games(game_pks)
                with state["lock"]:
                    state["batting"] = batting
                    state["pitching"] = pitching
                    state["updated_at"] = time.time()
            except Exception:
                log_background_exception("live streak monitor")
            finally:
                state["ready"].set()
            time.sleep(30)

    start_daemon_thread("live-streak-monitor", refresh_forever)
    return state


def monitored_live_streak_stats(schedule):
    game_rows = live_streak_game_rows(schedule)
    game_pks = tuple(row[0] for row in game_rows)
    state = start_live_streak_monitor(game_pks)
    if game_rows and state["batting"].empty and state["pitching"].empty:
        state["ready"].wait(timeout=5)
    with state["lock"]:
        batting = apply_live_streak_schedule_context(
            state["batting"].copy(),
            game_rows,
        )
        pitching = apply_live_streak_schedule_context(
            state["pitching"].copy(),
            game_rows,
        )
        return batting, pitching


def live_played(row, group):
    if row is None:
        return False
    if group == "pitching":
        pitch_count = pd.to_numeric(row.get("Pitch Count"), errors="coerce")
        if pd.notna(pitch_count) and pitch_count > 0:
            return True
        return row_text(row, "IP", default="0.0") not in {"", "0.0", "0"}

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
    historical_logs = add_composite_streak_columns(historical_logs)
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
    historical_logs = add_composite_streak_columns(historical_logs)
    live_df = add_composite_streak_columns(live_df)
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


def render_streak_leaderboard(
    streak_df,
    metric_label,
    key,
    player_group,
    season_value,
):
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
        streak = int(row_value(row, "Streak", default=0))
        width = max(3, round((streak / max_streak) * 100, 1)) if streak else 3
        status = row_text(row, "Status", default="Pending")
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
            row_text(row, "Headshot"),
            f"{row_text(row, 'Player', default='Player')} headshot",
            class_name="leaderboard-headshot",
        )
        injury_tooltip = row.get("injury_tooltip")
        injury_badge = (
            '<span class="streak-injury-badge" '
            f'title="{escape(str(injury_tooltip), quote=True)}">inj</span>'
            if not is_missing_value(injury_tooltip)
            else ""
        )
        profile_payload = player_profile_payload(
            row.get("player_id"),
            row.get("Player"),
            row.get("Team"),
            player_group,
            season_value,
        )
        profile_json = json.dumps(
            profile_payload or {},
            separators=(",", ":"),
        )
        rows.append(
            f"""
            <div class="leaderboard-row">
                <div class="leaderboard-rank">{rank}</div>
                {headshot}
                <div class="leaderboard-name">
                    <button type="button" class="research-player-link"
                            data-research-event="{escape(profile_json, quote=True)}">
                        <strong>{escape(row_text(row, "Player", default="Unknown"))}{injury_badge}</strong>
                    </button>
                    <span>{escape(row_text(row, "Team"))} | Today: {escape(today_text)}</span>
                </div>
                <div class="leaderboard-bar-track">
                    <span class="leaderboard-bar-fill" style="width:{width}%"></span>
                </div>
                <div class="leaderboard-count">{streak}</div>
                <span class="live-chip {status_class}">{escape(status)}</span>
            </div>
            """
        )

    table_event = RESEARCH_TABLE_COMPONENT(
        table_html=f"""
            <div class="leaderboard-shell" id="{escape(key, quote=True)}">
                {''.join(rows)}
            </div>
        """,
        table_height=min(540, max(90, len(rows) * 59)),
        key=key,
        default=None,
    )
    handle_player_profile_event(table_event, "Streaks")


def team_record_class(record):
    wins = int(safe_value(record.get("wins"), 0))
    losses = int(safe_value(record.get("losses"), 0))
    if wins > losses:
        return "good"
    if losses > wins:
        return "bad"
    return "neutral"


def historical_pitcher_game_pks(schedule, pitcher_logs):
    if schedule is None or schedule.empty or pitcher_logs is None or pitcher_logs.empty:
        return ()

    game_pks = set()
    player_ids = pd.to_numeric(
        pitcher_logs.get("player_id", pd.Series(dtype=float)),
        errors="coerce",
    )
    opponent_ids = pd.to_numeric(
        pitcher_logs.get("opponent_id", pd.Series(dtype=float)),
        errors="coerce",
    )
    games_started = pd.to_numeric(
        pitcher_logs.get("GS", pd.Series(1, index=pitcher_logs.index)),
        errors="coerce",
    ).fillna(0)

    for _, game in schedule.iterrows():
        for side, opponent_side in (("away", "home"), ("home", "away")):
            team_id = pd.to_numeric(game.get(f"{side}_team_id"), errors="coerce")
            pitcher_id = pd.to_numeric(
                game.get(f"{opponent_side}_probable_pitcher_id"),
                errors="coerce",
            )
            if pd.isna(team_id) or pd.isna(pitcher_id):
                continue
            matches = pitcher_logs[
                player_ids.eq(int(pitcher_id))
                & opponent_ids.eq(int(team_id))
                & games_started.ge(1)
            ]
            game_pks.update(
                int(game_pk)
                for game_pk in pd.to_numeric(
                    matches.get("game_pk", pd.Series(dtype=float)),
                    errors="coerce",
                ).dropna()
            )
    return tuple(sorted(game_pks))


def build_team_win_streak_rows(
    schedule,
    season_results_df,
    historical_results_df,
    pitcher_logs,
):
    rows = []
    if schedule is None or schedule.empty:
        return pd.DataFrame()

    for _, game in schedule.iterrows():
        for side, opponent_side in (("away", "home"), ("home", "away")):
            team_id = game.get(f"{side}_team_id")
            team_name = row_text(game, f"{side}_team", default=side.title())
            team_code = row_text(game, f"{side}_team_abbr", default=team_name)
            pitcher_id = game.get(f"{opponent_side}_probable_pitcher_id")
            pitcher_name = row_text(
                game,
                f"{opponent_side}_probable_pitcher",
                default="Starter TBD",
            )
            record = calculate_team_record_vs_pitcher(
                historical_results_df,
                pitcher_logs,
                team_id,
                pitcher_id,
            )
            rows.append(
                {
                    "Team": team_name,
                    "TeamCode": team_code,
                    "team_id": team_id,
                    "Streak": calculate_team_win_streak(
                        season_results_df,
                        team_id,
                    ),
                    "Pitcher": pitcher_name,
                    "Record": record,
                }
            )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(
        ["Streak", "Team"],
        ascending=[False, True],
    ).reset_index(drop=True)


def render_team_win_streaks(schedule, selected_date_value):
    season_value = pd.to_datetime(selected_date_value).year
    try:
        results_df = load_team_season_results(
            season_value,
            selected_date_value,
        )
    except Exception:
        results_df = pd.DataFrame()

    active_pitcher_ids = set()
    for _, game in schedule.iterrows():
        for side, opponent_side in (("away", "home"), ("home", "away")):
            team_id = game.get(f"{side}_team_id")
            if calculate_team_win_streak(results_df, team_id) < 1:
                continue
            pitcher_id = pd.to_numeric(
                game.get(f"{opponent_side}_probable_pitcher_id"),
                errors="coerce",
            )
            if pd.notna(pitcher_id):
                active_pitcher_ids.add(int(pitcher_id))
    pitcher_ids = tuple(sorted(active_pitcher_ids))
    try:
        pitcher_logs = (
            load_probable_pitcher_career_logs(
                pitcher_ids,
                selected_date_value,
            )
            if pitcher_ids
            else pd.DataFrame()
        )
    except Exception:
        pitcher_logs = pd.DataFrame()

    historical_game_pks = historical_pitcher_game_pks(
        schedule,
        pitcher_logs,
    )
    try:
        historical_results = (
            load_historical_game_results(historical_game_pks)
            if historical_game_pks
            else pd.DataFrame()
        )
    except Exception:
        historical_results = pd.DataFrame()

    streaks = build_team_win_streak_rows(
        schedule,
        results_df,
        historical_results,
        pitcher_logs,
    )
    if streaks.empty:
        st.info("Team win-streak history is not available for this slate yet.")
        return

    active = streaks[
        pd.to_numeric(streaks["Streak"], errors="coerce").fillna(0) > 0
    ].copy()
    if active.empty:
        st.info("No teams on this slate currently have an active win streak.")
        return

    max_streak = max(1, int(active["Streak"].max()))
    rows = []
    for rank, (_, row) in enumerate(active.iterrows(), start=1):
        streak = int(safe_value(row.get("Streak"), 0))
        width = max(3, round((streak / max_streak) * 100, 1))
        record = row.get("Record") or {}
        wins = int(safe_value(record.get("wins"), 0))
        losses = int(safe_value(record.get("losses"), 0))
        pitcher_name = row_text(row, "Pitcher", default="today's starter")
        record_text = f"{wins}-{losses} vs {pitcher_name}"
        rows.append(
            f"""
            <div class="leaderboard-row">
                <div class="leaderboard-rank">{rank}</div>
                {team_logo_img_html(row.get("TeamCode"), alt=row.get("Team"), class_name="team-streak-logo")}
                <div class="leaderboard-name">
                    <strong>{escape(row_text(row, "Team", default="Unknown"))}</strong>
                    <span class="team-streak-record {team_record_class(record)}">{escape(record_text)}</span>
                </div>
                <div class="leaderboard-bar-track">
                    <span class="leaderboard-bar-fill" style="width:{width}%"></span>
                </div>
                <div class="leaderboard-count">{streak}</div>
                <span class="live-chip">Wins</span>
            </div>
            """
        )
    st.html(f'<div class="leaderboard-shell">{"".join(rows)}</div>')


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

    streak_group = render_box_tabs(
        "streak-group-tabs",
        ["Batter Streaks", "Pitcher Streaks", "Team Win Streaks"],
        "active_streak_group",
        "Batter Streaks",
    )

    if streak_group == "Team Win Streaks":
        render_team_win_streaks(schedule, selected_date_value)
        return

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
            player_group="pitching",
            season_value=season_value,
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
        limit=150 if active_metric_label == "H + R + RBI" else None,
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
    if (
        active_metric_label == "H + R + RBI"
        and (batter_logs.empty or "R" not in batter_logs.columns)
    ):
        try:
            batter_logs = merge_streak_history(
                batter_logs,
                load_batter_composite_streak_logs(
                    batter_ids,
                    season_value,
                ),
            )
        except Exception:
            pass
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
        player_group="batting",
        season_value=season_value,
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
        result = rank_hitters_by_wrc_plus(result)
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
            "wRC+",
            "K%",
            "BB%",
        ]

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
    "wRC+": "wRC+",
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
    if column == "wRC+" and pd.notna(number):
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
        value = row_value(row, "Name", "team_name", "Team")
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
        team_code = row_text(row, "Team")
        team_name = row_text(row, "Name", "team_name", default=team_code)
        display_name = team_code if not is_missing_value(row.get("Player")) else team_name
        logo = team_logo_img_html(
            team_code if team_code else team_name,
            alt=team_name,
            class_name="stats-identity-img",
        )
        return (
            '<span class="research-log-opponent">'
            f"{logo}"
            f"<span>{escape(display_name)}</span>"
            "</span>"
        )

    player = row_text(row, "Player", default="Unknown")
    player_id = row.get("player_id")
    team_code = row_text(row, "Team")
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
                    event_payload = json.dumps(
                        player_profile_payload(
                            row.get("player_id"),
                            row.get("Player"),
                            row.get("Team"),
                            player_log_group,
                            season,
                        )
                        or {},
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
        handle_player_profile_event(table_event, "Player Stats")


def render_team_stats_tab(batter_stats_df, pitcher_stats_df):
    st.markdown(
        """
        <div class="section-shell">
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
    selected_player = safe_text(selected_player).strip()
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
            <div class="section-title">Season Player Leaders · wRC+ Hitter Ranking</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.html(
        '<div class="research-table-note">'
        "Click a player name to open their full profile. "
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
            ["Player", "Team", "wRC+", "PA", "AB", "R", "H", "BB", "HBP", "K", "HR", "RBI", "SB", "AVG", "OBP", "SLG", "OPS", "K%", "BB%"],
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


def build_player_directory(batter_stats_df, pitcher_stats_df, season_value):
    frames = []
    for stats_df, player_type, group, label in (
        (batter_stats_df, "batter", "batting", "Batter"),
        (pitcher_stats_df, "pitcher", "pitching", "Pitcher"),
    ):
        leaders = prepare_player_stats(stats_df, player_type)
        if leaders.empty:
            continue
        leaders = leaders.copy()
        leaders.insert(0, "Rank", range(1, len(leaders) + 1))
        leaders["group"] = group
        leaders["player_type"] = label
        leaders["season"] = int(season_value)
        frames.append(leaders)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def player_directory_payload(row):
    return player_profile_payload(
        row.get("player_id"),
        row.get("Player"),
        row.get("Team"),
        row.get("group"),
        row.get("season"),
    )


def render_player_cards(leaders, card_key, limit=5, roster=False):
    if leaders.empty:
        st.info("Current player rankings are not available yet.")
        return

    display_leaders = leaders.copy()
    if limit is not None:
        display_leaders = display_leaders.head(limit)
    cards = []
    for _, row in display_leaders.iterrows():
        player_name = row_text(row, "Player", default="Player")
        team = row_text(row, "Team")
        rank = pd.to_numeric(row.get("Rank"), errors="coerce")
        rank_text = (
            f"Rank #{int(rank)}"
            if pd.notna(rank)
            else "Active Roster"
        )
        player_type = row_text(
            row,
            "Position",
            "player_type",
            default="Player",
        )
        payload = json.dumps(
            player_directory_payload(row) or {},
            separators=(",", ":"),
        )
        headshot = image_html(
            player_image_url(row.get("player_id"), width=160),
            f"{player_name} headshot",
            fallback_src=team_logo_fallback_url(team),
        )
        cards.append(
            f"""
            <button type="button" class="player-card"
                    data-research-event="{escape(payload, quote=True)}">
                {headshot}
                <span class="player-card-rank">{escape(rank_text)}</span>
                <span class="player-card-name">{escape(player_name)}</span>
                <span class="player-card-team">{escape(team)} · {escape(player_type)}</span>
            </button>
            """
        )
    grid_class = (
        "player-card-grid roster-player-card-grid"
        if roster
        else "player-card-grid"
    )
    row_count = max(1, (len(cards) + 4) // 5)
    event = RESEARCH_TABLE_COMPONENT(
        table_html=f'<div class="{grid_class}">{"".join(cards)}</div>',
        table_height=(
            min(740, max(235, row_count * 220))
            if roster
            else 235
        ),
        key=card_key,
        default=None,
    )
    handle_player_profile_event(event, "Players")


def player_team_options(player_directory):
    if player_directory.empty:
        return {}
    teams = {}
    for _, row in player_directory.iterrows():
        team_id = pd.to_numeric(row.get("team_id"), errors="coerce")
        team_name = row_text(row, "team_name", default=row_text(row, "Team"))
        team_abbr = row_text(row, "Team", default=team_name)
        if pd.isna(team_id) or not team_name:
            continue
        teams[team_name] = (int(team_id), team_name, team_abbr)
    return dict(sorted(teams.items(), key=lambda item: item[0].casefold()))


def enrich_roster_with_rankings(roster_df, player_directory, season_value):
    if roster_df is None or roster_df.empty:
        return pd.DataFrame()

    ranked_by_group = {}
    ranked_any = {}
    for _, row in player_directory.iterrows():
        player_id = pd.to_numeric(row.get("player_id"), errors="coerce")
        if pd.isna(player_id):
            continue
        player_id = int(player_id)
        ranked_by_group[(player_id, row_text(row, "group"))] = row
        ranked_any.setdefault(player_id, row)

    rows = []
    for _, roster_row in roster_df.iterrows():
        player_id = pd.to_numeric(roster_row.get("player_id"), errors="coerce")
        if pd.isna(player_id):
            continue
        player_id = int(player_id)
        group = row_text(roster_row, "group", default="batting")
        ranked_row = ranked_by_group.get(
            (player_id, group),
            ranked_any.get(player_id),
        )
        combined = roster_row.to_dict()
        if ranked_row is not None:
            for key, value in ranked_row.items():
                if key not in {"Player", "Team", "team_name", "team_id", "group"}:
                    combined[key] = value
        combined["player_id"] = player_id
        combined["group"] = group
        combined["season"] = int(season_value)
        combined["player_type"] = (
            "Pitcher" if group == "pitching" else "Batter"
        )
        rows.append(combined)
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(
        ["group", "Position", "Player"],
        ascending=[False, True, True],
        na_position="last",
    ).reset_index(drop=True)


def profile_stat_columns(group):
    if group == "pitching":
        return ["IP", "GS", "K", "ERA", "WHIP", "K/9"]
    return ["PA", "H", "HR", "RBI", "AVG", "OPS"]


def profile_game_log_columns(group, game_log_df):
    if group == "pitching":
        requested = [
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
        requested = [
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
            "R",
            "SB",
            "AVG",
            "OBP",
            "SLG",
            "OPS",
            "K%",
            "BB%",
        ]
    return [column for column in requested if column in game_log_df.columns]


PITCH_TYPE_PROFILE_COLUMNS = [
    "PITCH",
    "AB",
    "AVG",
    "SLG",
    "ISO",
    "H",
    "1B",
    "2B",
    "3B",
    "HR",
    "K",
]


def render_pitch_type_profile_table(pitch_type_df, table_key):
    if pitch_type_df.empty:
        return

    columns = [
        column
        for column in PITCH_TYPE_PROFILE_COLUMNS
        if column in pitch_type_df.columns
    ]
    if not columns:
        return

    header_cells = []
    for index, column in enumerate(columns):
        label = RESEARCH_COLUMN_LABELS.get(column, column)
        width = RESEARCH_COLUMN_WIDTHS.get(column, 62)
        align_class = "align-left" if column == "PITCH" else ""
        header_cells.append(
            f'<th class="{align_class}" style="min-width:{width}px" '
            'aria-sort="none">'
            f'<button type="button" class="research-sort-button" '
            f'data-column-index="{index}">'
            f"<span>{escape(label)}</span>"
            '<span class="research-sort-indicator" aria-hidden="true"></span>'
            "</button></th>"
        )

    body_rows = []
    for _, row in pitch_type_df.iterrows():
        cells = []
        for column in columns:
            value = row.get(column)
            sort_value, sort_kind = research_sort_metadata(row, column)
            align_class = "align-left" if column == "PITCH" else ""
            cells.append(
                f'<td class="{align_class}" '
                f'data-sort-value="{escape(sort_value, quote=True)}" '
                f'data-sort-kind="{sort_kind}">'
                f"{escape(research_cell_value(column, value))}</td>"
            )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    table_height = min(430, max(108, 44 + (len(pitch_type_df) * 36)))
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


def render_player_profile(profile, player_directory, default_season):
    return_state = st.session_state.get("player_profile_return") or {}
    return_view = safe_text(return_state.get("view"), default="Players")
    return_destination_label = (
        "Live Game"
        if return_view == "Games" and return_state.get("game_pk")
        else return_view
    )
    with st.container(key="player_profile_back_bar"):
        if render_universal_back_button(
            "player_profile",
            help_text=f"Back to {return_destination_label}",
        ):
            return_from_player_profile()

    player_id = int(profile["player_id"])
    group = safe_text(profile.get("group"), default="batting")
    ranked_rows = player_directory[
        pd.to_numeric(
            player_directory.get("player_id", pd.Series(dtype=float)),
            errors="coerce",
        ).eq(player_id)
    ].copy()
    group_rows = ranked_rows[
        ranked_rows.get("group", pd.Series(dtype=str)).eq(group)
    ]
    if not group_rows.empty:
        ranked_row = group_rows.iloc[0]
    elif not ranked_rows.empty:
        ranked_row = ranked_rows.iloc[0]
        group = row_text(ranked_row, "group", default=group)
    else:
        ranked_row = pd.Series(dtype=object)

    try:
        metadata = load_player_profile(player_id)
    except Exception:
        metadata = {}

    player_name = safe_text(
        metadata.get("name"),
        default=safe_text(
            profile.get("player"),
            default=row_text(ranked_row, "Player", default="Player"),
        ),
    )
    team = safe_text(
        metadata.get("team"),
        default=safe_text(
            profile.get("team"),
            default=row_text(ranked_row, "Team"),
        ),
    )
    position = safe_text(
        metadata.get("position"),
        default="P" if group == "pitching" else "Position unavailable",
    )
    rank = pd.to_numeric(ranked_row.get("Rank"), errors="coerce")
    rank_text = f"#{int(rank)} {group.title()} Rank" if pd.notna(rank) else "Rank unavailable"
    headshot = safe_text(
        metadata.get("headshot"),
        default=player_image_url(player_id, width=180),
    )

    st.markdown(
        f"""
        <div class="player-profile-hero">
            {image_html(headshot, f"{player_name} headshot", fallback_src=team_logo_fallback_url(team))}
            <div>
                <div class="player-profile-title">{escape(player_name)}</div>
                <div class="player-profile-meta">
                    {escape(team)} · {escape(position)} · {escape(rank_text)}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    hvp_button_label = (
        "Open Advanced HVP as Batter"
        if group == "batting"
        else "Open Advanced HVP as Pitcher"
    )
    if st.button(
        hvp_button_label,
        key=f"player_profile_hvp_{player_id}_{group}",
        use_container_width=False,
    ):
        open_advanced_hvp(
            batter_id=player_id if group == "batting" else None,
            pitcher_id=player_id if group == "pitching" else None,
            game_pk=return_state.get("game_pk"),
        )

    stat_items = []
    for column in profile_stat_columns(group):
        stat_items.append(
            '<div class="profile-stat">'
            f'<div class="metric-label">{escape(column)}</div>'
            f"<strong>{escape(stats_cell_value(column, ranked_row.get(column)))}</strong>"
            "</div>"
        )
    st.html(f'<div class="profile-stat-grid">{"".join(stat_items)}</div>')

    season_options = list(range(int(default_season), 2004, -1))
    profile_season_key = f"player_profile_season_{player_id}_{group}"
    if st.session_state.get(profile_season_key) not in season_options:
        st.session_state[profile_season_key] = int(
            safe_value(profile.get("season"), default_season)
        )
    selected_season = st.selectbox(
        "Game log season",
        season_options,
        key=profile_season_key,
    )

    if group == "batting":
        pitch_type_by_hand = {
            "vs LHP": load_batter_pitch_type_profile(
                player_id,
                selected_season,
                "L",
            ),
            "vs RHP": load_batter_pitch_type_profile(
                player_id,
                selected_season,
                "R",
            ),
        }
        pitch_type_options = [
            label
            for label, data_frame in pitch_type_by_hand.items()
            if not data_frame.empty
        ]
        if pitch_type_options:
            pitch_hand_label = render_box_tabs(
                "Pitch type split",
                pitch_type_options,
                f"player_profile_pitch_type_hand_{player_id}_{selected_season}",
                pitch_type_options[0],
            )
            pitcher_hand = "L" if "LHP" in pitch_hand_label else "R"
            pitch_type_df = pitch_type_by_hand[pitch_hand_label]
        else:
            pitcher_hand = None
            pitch_type_df = pd.DataFrame()
        if not pitch_type_df.empty:
            numeric_sort = pd.to_numeric(
                pitch_type_df.get("AB"),
                errors="coerce",
            )
            pitch_type_df = (
                pitch_type_df.assign(_ab_sort=numeric_sort)
                .sort_values(
                    ["_ab_sort", "PITCH"],
                    ascending=[False, True],
                    na_position="last",
                )
                .drop(columns="_ab_sort")
                .reset_index(drop=True)
            )
            st.markdown(
                """
                <div class="section-shell game-log-heading">
                    <div class="section-title">Pitch Type Splits</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            render_pitch_type_profile_table(
                pitch_type_df,
                table_key=(
                    f"player-pitch-types-{player_id}-"
                    f"{selected_season}-{pitcher_hand}"
                ),
            )

    game_log_df = load_database_player_game_log(
        player_id,
        group,
        selected_season,
    )
    st.markdown(
        f"""
        <div class="section-shell game-log-heading">
            <div class="section-title">{escape(player_name)} · {selected_season}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if game_log_df.empty:
        st.info("No completed-game history is available for this player and season.")
        return

    game_log_df = game_log_df.copy()
    game_log_df["_game_date_sort"] = pd.to_datetime(
        game_log_df.get("game_date"),
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
    columns = profile_game_log_columns(group, game_log_df)
    render_game_log_table(
        game_log_df[columns],
        columns,
        log_type=group,
        table_key=f"player-profile-{player_id}-{group}-{selected_season}",
    )
    chart_column = "SO" if group == "pitching" else "TB"
    chart_html = build_recent_bar_chart_html(
        game_log_df,
        value_column=chart_column,
        title=(
            "Strikeouts - Last 5 Games"
            if group == "pitching"
            else "Total Bases - Last 5 Games"
        ),
        subtitle=player_name,
        scale_floor=10 if group == "pitching" else 4,
        accent="#173f67" if group == "pitching" else "#245f96",
    )
    if chart_html:
        st.html(chart_html)


def render_players_tab(batter_stats_df, pitcher_stats_df, season_value):
    player_directory = build_player_directory(
        batter_stats_df,
        pitcher_stats_df,
        season_value,
    )
    selected_profile = st.session_state.get("selected_player_profile")
    query_player_id = pd.to_numeric(
        current_query_value("player"),
        errors="coerce",
    )
    if selected_profile is None and pd.notna(query_player_id):
        query_group = safe_text(current_query_value("profile_group")).lower()
        query_rows = player_directory[
            pd.to_numeric(
                player_directory.get("player_id", pd.Series(dtype=float)),
                errors="coerce",
            ).eq(int(query_player_id))
        ]
        if query_group in {"batting", "pitching"} and "group" in query_rows:
            group_rows = query_rows[
                query_rows["group"].astype(str).str.lower().eq(query_group)
            ]
            if not group_rows.empty:
                query_rows = group_rows
        if not query_rows.empty:
            return_game_pk = pd.to_numeric(
                current_query_value("return_game_pk"),
                errors="coerce",
            )
            selected_profile = player_directory_payload(query_rows.iloc[0])
            st.session_state.selected_player_profile = selected_profile
            st.session_state.player_profile_return = {
                "view": safe_text(current_query_value("return_view"), default="Players"),
                "game_pk": int(return_game_pk) if pd.notna(return_game_pk) else None,
            }

    if selected_profile is not None:
        render_player_profile(
            selected_profile,
            player_directory,
            season_value,
        )
        return

    st.markdown(
        """
        <div class="section-shell">
            <div class="section-title">Player Profiles</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if player_directory.empty:
        st.info("Current player data is not available yet.")
        return

    search_labels = {}
    for _, row in player_directory.iterrows():
        label = (
            f"{row_text(row, 'Player')} — {row_text(row, 'Team')} "
            f"({row_text(row, 'player_type')})"
        )
        search_labels[label] = player_directory_payload(row)
    selected_label = st.selectbox(
        "Search players",
        sorted(search_labels, key=str.casefold),
        index=None,
        placeholder="Search player...",
        key="players_search",
        label_visibility="collapsed",
    )
    if selected_label:
        navigate_to_player_profile(
            search_labels[selected_label],
            "Players",
        )

    player_group = render_box_tabs(
        "players-leader-tabs",
        ["Batters", "Pitchers", "Teams"],
        "players_leader_group",
        "Batters",
    )
    if player_group == "Teams":
        team_options = player_team_options(player_directory)
        selected_team = st.selectbox(
            "Team roster",
            list(team_options),
            index=None,
            key="players_team_filter",
            placeholder="Select team...",
            label_visibility="collapsed",
        )
        if not selected_team:
            return
        team_record = team_options[selected_team]
        try:
            roster_df = load_active_team_rosters(
                (team_record,),
                app_today,
            )
        except Exception:
            roster_df = pd.DataFrame()
        roster_players = enrich_roster_with_rankings(
            roster_df,
            player_directory,
            season_value,
        )
        render_player_cards(
            roster_players,
            card_key=f"team-roster-cards-{team_record[0]}",
            limit=None,
            roster=True,
        )
        return

    group = "batting" if player_group == "Batters" else "pitching"
    leaders = player_directory[player_directory["group"] == group].copy()
    render_player_cards(
        leaders,
        card_key=f"top-player-cards-{group}",
        limit=5,
    )


def matchup_grade_class(grade):
    value = safe_text(grade).lower()
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
    "PITCH": "Pitch",
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
    "PITCH": 150,
}

INTEGER_RESEARCH_COLUMNS = {
    "PA",
    "AB",
    "H",
    "1B",
    "2B",
    "3B",
    "TB",
    "BB",
    "HBP",
    "SO",
    "K",
    "HR",
    "RBI",
    "GS",
    "BF",
    "R",
    "ER",
    "Projected Pitch Count",
}
THREE_DECIMAL_RESEARCH_COLUMNS = {"AVG", "OBP", "SLG", "OPS", "ISO"}
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
    game_text = safe_text(game)
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
    game_text = safe_text(game).strip()
    if " @ " not in game_text:
        return game_text

    away_team, home_team = game_text.split(" @ ", 1)
    if safe_text(player_team).strip() == home_team:
        return f"{home_team} vs {away_team}"
    return f"{away_team} @ {home_team}"


def research_log_payload(row, log_type, matchup_rank=None, matchup_total=None):
    if log_type == "pitcher":
        payload = {
            "log_type": "pitcher",
            "pitcher_id": row.get("pitcher_id"),
            "pitcher": row.get("pitcher"),
            "opponent": row.get("opponent"),
            "matchup_grade": row.get("k_matchup_grade"),
            "matchup_score": row.get("k_matchup_score"),
        }
    else:
        payload = {
            "log_type": "bvp",
            "batter_id": row.get("batter_id"),
            "opposing_pitcher_id": row.get("opposing_pitcher_id"),
            "batter": row.get("batter"),
            "opposing_pitcher": row.get("opposing_pitcher"),
            "matchup_grade": row.get("matchup_grade"),
            "matchup_score": row.get("weather_adjusted_score"),
        }
    payload["matchup_rank"] = matchup_rank
    payload["matchup_total"] = matchup_total
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
    edge = safe_text(value).lower()
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
    for matchup_rank, (_, row) in enumerate(df.iterrows(), start=1):
        player_name = row_text(row, player_column, default="Unknown")
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
            research_log_payload(
                row,
                log_type,
                matchup_rank=matchup_rank,
                matchup_total=len(df),
            ),
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
                    row_text(row, "weather_tooltip"),
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
                    row_text(row, "wind_tooltip"),
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
    team = row_text(row, "team")
    opponent = row_text(row, "opponent")
    if team and opponent:
        if row_text(row, "home_away").lower() == "home":
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


def selected_log_from_event(table_key, event):
    selected_key = f"{table_key}_selected_log"
    event_key = f"{table_key}_processed_event"
    if isinstance(event, dict) and event.get("type") == "select_player":
        event_id = safe_text(event.get("event_id"))
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
    render_matchup_log_dialog(table_key, selected_log)


def dismiss_matchup_log_dialog():
    for key in list(st.session_state):
        if key.endswith("_selected_log"):
            st.session_state[key] = None


@st.dialog(
    "Matchup Game Log",
    width="large",
    on_dismiss=dismiss_matchup_log_dialog,
)
def render_matchup_log_dialog(table_key, selected_log):
    matchup_rank = pd.to_numeric(
        selected_log.get("matchup_rank"),
        errors="coerce",
    )
    matchup_total = pd.to_numeric(
        selected_log.get("matchup_total"),
        errors="coerce",
    )
    matchup_grade = safe_text(
        selected_log.get("matchup_grade"),
        default="Not rated",
    )
    matchup_score = selected_log.get("matchup_score")
    score_text = research_cell_value("k_matchup_score", matchup_score)
    rank_text = (
        f"#{int(matchup_rank)} of {int(matchup_total)}"
        if pd.notna(matchup_rank) and pd.notna(matchup_total)
        else "Not ranked"
    )
    st.markdown(
        f"""
        <div class="matchup-rank-strip">
            <div class="matchup-rank-item">
                <div class="metric-label">Matchup Rank</div>
                <div class="matchup-rank-value">{escape(rank_text)}</div>
            </div>
            <div class="matchup-rank-item">
                <div class="metric-label">Grade</div>
                <div class="matchup-rank-value">
                    <span class="research-grade {matchup_grade_class(matchup_grade)}">{escape(matchup_grade)}</span>
                </div>
            </div>
            <div class="matchup-rank-item">
                <div class="metric-label">Score</div>
                <div class="matchup-rank-value">{escape(score_text)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

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

    if st.button(
        "Open Advanced HVP Research",
        key=f"open_hvp_from_log_{int(batter_id)}_{int(pitcher_id)}",
    ):
        open_advanced_hvp(
            batter_id=int(batter_id),
            pitcher_id=int(pitcher_id),
        )

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


def advanced_heat_class(column, value):
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return "neutral"
    if column in {"AVG", "split_AVG"}:
        if number >= 0.280:
            return "good"
        if number <= 0.220:
            return "avoid"
    if column in {"SLG", "OPS", "split_SLG", "split_OPS"}:
        if number >= (0.800 if "OPS" in column else 0.450):
            return "good"
        if number <= (0.650 if "OPS" in column else 0.360):
            return "avoid"
    if column in {"K%", "split_K%"}:
        if number <= 18:
            return "good"
        if number >= 27:
            return "avoid"
    if column in {"BB%", "split_BB%"}:
        if number >= 10:
            return "good"
        if number <= 5:
            return "avoid"
    if column == "HR" and number >= 2:
        return "good"
    return "neutral"


def advanced_matchup_insight(row):
    parts = []
    ab = int(safe_value(row.get("AB"), 0))
    hits = int(safe_value(row.get("H"), 0))
    avg = pd.to_numeric(row.get("AVG"), errors="coerce")
    slg = pd.to_numeric(row.get("SLG"), errors="coerce")
    k_rate = pd.to_numeric(row.get("split_K%"), errors="coerce")
    bb_rate = pd.to_numeric(row.get("split_BB%"), errors="coerce")
    split = row_text(row, "split", default=row_text(row, "opposing_pitcher_hand"))
    if ab > 0 and pd.notna(avg):
        parts.append(f"{hits}-for-{ab} direct history")
    else:
        parts.append("No direct history")
    if pd.notna(slg):
        if slg >= 0.450:
            parts.append("power lean")
        elif slg <= 0.360 and ab >= 8:
            parts.append("limited damage")
    if pd.notna(k_rate):
        if k_rate >= 27:
            parts.append(f"K risk vs {split}")
        elif k_rate <= 18:
            parts.append(f"contact lean vs {split}")
    if pd.notna(bb_rate) and bb_rate >= 10:
        parts.append("walk path")
    weather_edge = row_text(row, "weather_edge")
    if weather_edge and weather_edge.lower() != "neutral":
        parts.append(weather_edge)
    return " | ".join(parts[:4])


def build_advanced_matchup_rows(bvp_df, hand_df):
    if bvp_df.empty:
        return pd.DataFrame()
    hand_lookup = {}
    if hand_df is not None and not hand_df.empty:
        for _, split_row in hand_df.iterrows():
            key = (
                safe_text(split_row.get("batter_id")),
                safe_text(split_row.get("opposing_pitcher_id")),
            )
            hand_lookup[key] = split_row

    rows = []
    for _, row in bvp_df.iterrows():
        result = row.to_dict()
        split_row = hand_lookup.get(
            (
                safe_text(row.get("batter_id")),
                safe_text(row.get("opposing_pitcher_id")),
            )
        )
        if split_row is not None:
            for column in ("PA", "AVG", "SLG", "OPS", "K%", "BB%"):
                result[f"split_{column}"] = split_row.get(column)
            result["split"] = split_row.get("split")
        result["advanced_insight"] = advanced_matchup_insight(result)
        rows.append(result)
    result_df = pd.DataFrame(rows)
    if "weather_adjusted_score" in result_df.columns:
        result_df = result_df.sort_values(
            ["weather_adjusted_score", "SLG", "OPS"],
            ascending=[False, False, False],
            na_position="last",
        )
    return result_df.reset_index(drop=True)


def advanced_cell_html(row, column):
    value = row.get(column)
    label_column = column.replace("split_", "")
    if column == "batter":
        player_name = row_text(row, "batter", default="Unknown")
        player_id = row.get("batter_id")
        headshot_html = image_html(
            player_image_url(player_id, width=64),
            f"{player_name} headshot",
            class_name="research-headshot",
        )
        payload = json.dumps(
            research_log_payload(row, "bvp"),
            separators=(",", ":"),
        )
        return (
            '<button type="button" class="research-player-link" '
            f'data-research-event="{escape(payload, quote=True)}">'
            '<span class="research-player-identity">'
            f"{headshot_html}<span>{escape(player_name)}</span>"
            "</span></button>"
        )
    if column == "matchup":
        pitcher = row_text(row, "opposing_pitcher", default="Pitcher")
        hand = row_text(row, "opposing_pitcher_hand")
        return f"{escape(pitcher)} <span class=\"advanced-muted\">{escape(hand)}</span>"
    if column == "weather_edge":
        return (
            f'<span class="research-edge {research_edge_class(value)}">'
            f"{escape(research_cell_value(column, value))}</span>"
        )
    if column == "matchup_grade":
        return (
            f'<span class="research-grade {matchup_grade_class(value)}">'
            f"{escape(research_cell_value(column, value))}</span>"
        )
    if column == "advanced_insight":
        return escape(safe_text(value, default="-"))
    if column.startswith("split_"):
        value_text = research_cell_value(label_column, value)
    else:
        value_text = research_cell_value(column, value)
    heat_class = advanced_heat_class(column, value)
    return f'<span class="advanced-heat {heat_class}">{escape(value_text)}</span>'


PITCH_SWATCH_COLORS = [
    "#1882c5",
    "#ff5b16",
    "#4058c9",
    "#ff1d25",
    "#36a66a",
    "#a64bd4",
    "#d39d25",
    "#15a8a8",
]


def normalize_pitcher_hand(value):
    text = safe_text(value).strip().upper()
    if text in {"L", "R"}:
        return text
    if text.startswith("LEFT"):
        return "L"
    if text.startswith("RIGHT"):
        return "R"
    return ""


def pitch_color(row, index):
    code = safe_text(row.get("pitch_code"), default=row.get("PITCH")).upper()
    preferred = {
        "FF": "#1882c5",
        "FA": "#1882c5",
        "SI": "#ff5b16",
        "FT": "#ff5b16",
        "CH": "#4058c9",
        "SL": "#ff1d25",
        "ST": "#ff1d25",
        "CU": "#36a66a",
        "KC": "#36a66a",
        "FC": "#a64bd4",
        "FS": "#d39d25",
        "SW": "#15a8a8",
    }
    if code in preferred:
        return preferred[code]
    return PITCH_SWATCH_COLORS[index % len(PITCH_SWATCH_COLORS)]


def advanced_percent_text(value):
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return "-"
    return f"{float(number):.1f}%"


def advanced_speed_text(value):
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return "-"
    if abs(float(number) - round(float(number))) < 0.05:
        return f"{float(number):.0f}<span>mph</span>"
    return f"{float(number):.1f}<span>mph</span>"


def advanced_pitch_label_html(row, index):
    pitch_name = row_text(row, "PITCH", "pitch_code", default="Pitch")
    pitch_code = row_text(row, "pitch_code")
    code_html = (
        f'<em>{escape(pitch_code)}</em>'
        if pitch_code and pitch_code.upper() not in pitch_name.upper()
        else ""
    )
    return (
        '<span class="advanced-pitch-label">'
        f'<i style="background:{pitch_color(row, index)}"></i>'
        f"<strong>{escape(pitch_name)}</strong>{code_html}</span>"
    )


def advanced_empty_table_html(message):
    return (
        '<div class="advanced-card-empty">'
        f"{escape(message)}"
        "</div>"
    )


def pitcher_pitch_mix_html(pitch_mix_df):
    if pitch_mix_df is None or pitch_mix_df.empty:
        return advanced_empty_table_html("No pitcher pitch-mix history loaded.")

    rows = []
    for index, (_, pitch_row) in enumerate(pitch_mix_df.head(8).iterrows()):
        percent = pd.to_numeric(pitch_row.get("PERCENTAGE"), errors="coerce")
        bar_width = max(0, min(100, float(percent))) if pd.notna(percent) else 0
        rows.append(
            "<tr>"
            f"<td>{advanced_pitch_label_html(pitch_row, index)}</td>"
            f"<td>{escape(research_cell_value('COUNT', pitch_row.get('COUNT')))}</td>"
            '<td><span class="advanced-probability" '
            f'style="--probability:{bar_width:.1f}%">'
            f"<b>{escape(advanced_percent_text(percent))}</b></span></td>"
            f"<td>{advanced_speed_text(pitch_row.get('AVG SPEED'))}</td>"
            "</tr>"
        )
    return (
        '<table class="advanced-card-table advanced-pitch-mix-table">'
        "<thead><tr><th>Pitch</th><th>Count</th><th>Percentage</th><th>Avg Speed</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def batter_pitch_results_html(pitch_type_df):
    if pitch_type_df is None or pitch_type_df.empty:
        return advanced_empty_table_html("No plate appearances found for this split.")

    columns = [
        column
        for column in ("PITCH", "AB", "AVG", "SLG", "ISO", "H", "HR", "K")
        if column in pitch_type_df.columns
    ]
    header = "".join(f"<th>{escape(RESEARCH_COLUMN_LABELS.get(column, column))}</th>" for column in columns)
    rows = []
    for index, (_, pitch_row) in enumerate(pitch_type_df.head(8).iterrows()):
        cells = []
        for column in columns:
            if column == "PITCH":
                cells.append(f"<td>{advanced_pitch_label_html(pitch_row, index)}</td>")
            else:
                cells.append(
                    f"<td>{escape(research_cell_value(column, pitch_row.get(column)))}</td>"
                )
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<table class="advanced-card-table advanced-batter-pitch-table">'
        f"<thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def matchup_pitcher_team(row):
    batter_team = row_text(row, "team")
    game_text = row_text(row, "game")
    if " @ " in game_text:
        first_team, second_team = game_text.split(" @ ", 1)
    elif " vs " in game_text:
        first_team, second_team = game_text.split(" vs ", 1)
    else:
        return ""
    if batter_team and batter_team == first_team:
        return second_team
    if batter_team and batter_team == second_team:
        return first_team
    return ""


def advanced_stat_chip_html(label, column, row):
    return (
        '<span class="advanced-stat-chip">'
        f"<em>{escape(label)}</em>"
        f"<strong>{escape(research_cell_value(column, row.get(column)))}</strong>"
        "</span>"
    )


def advanced_bvp_card_html(
    row,
    pitch_mix_df,
    pitch_type_df,
    analysis_season,
    comparison_seasons,
    split_hand,
    focus_mode,
    is_recommended_pitcher,
):
    batter_name = row_text(row, "batter", default="Batter")
    batter_id = row.get("batter_id")
    batter_team = row_text(row, "team")
    batter_team_code = team_abbreviation(batter_team) or batter_team
    pitcher_name = row_text(row, "opposing_pitcher", default="Pitcher")
    pitcher_team = matchup_pitcher_team(row)
    pitcher_team_code = team_abbreviation(pitcher_team) or pitcher_team
    pitcher_hand = normalize_pitcher_hand(row.get("opposing_pitcher_hand"))
    hand_label = f"{pitcher_hand}HP" if pitcher_hand else "Hand N/A"
    split_label = f"vs {split_hand}HP" if split_hand else "Split N/A"
    headshot_html = image_html(
        player_image_url(batter_id, width=72),
        f"{batter_name} headshot",
        class_name="advanced-card-headshot",
        fallback_src=team_logo_fallback_url(batter_team),
    )
    season_tabs = "".join(
        '<span class="active">' + escape(str(option)) + "</span>"
        if int(option) == int(analysis_season)
        else "<span>" + escape(str(option)) + "</span>"
        for option in comparison_seasons
    )
    hand_tabs = []
    for option in ("L", "R"):
        option_label = f"vs {option}HP"
        active_class = " active" if split_hand == option else ""
        hand_tabs.append(f'<span class="{active_class.strip()}">{escape(option_label)}</span>')
    recommended_html = (
        '<span class="advanced-recommended-pill">Recommended starter</span>'
        if is_recommended_pitcher
        else ""
    )
    stat_html = "".join(
        [
            advanced_stat_chip_html("BvP PA", "PA", row),
            advanced_stat_chip_html("AVG", "AVG", row),
            advanced_stat_chip_html("SLG", "SLG", row),
            advanced_stat_chip_html("OPS", "OPS", row),
            advanced_stat_chip_html("HR", "HR", row),
        ]
    )
    insight = row_text(row, "advanced_insight", default="No direct history")
    pitch_mix_section = (
        '<section><div class="advanced-card-section-title">'
        "<strong>Pitcher Pitch Probability</strong>"
        f"<span>{escape(str(analysis_season))}</span></div>"
        f"{pitcher_pitch_mix_html(pitch_mix_df)}</section>"
    )
    batter_pitch_section = (
        '<section><div class="advanced-card-section-title">'
        "<strong>Batter Results By Pitch</strong>"
        f"<span>{escape(split_label)}</span></div>"
        f"{batter_pitch_results_html(pitch_type_df)}</section>"
    )
    if focus_mode == "Pitcher mix":
        detail_sections = pitch_mix_section
    elif focus_mode == "Batter results":
        detail_sections = batter_pitch_section
    else:
        detail_sections = pitch_mix_section + batter_pitch_section

    return f"""
    <article class="advanced-bvp-card">
        <header>
            <div class="advanced-card-player">
                {headshot_html}
                <div>
                    <strong>{escape(batter_name)}</strong>
                    <span><b>{escape(batter_team_code)}</b> vs {escape(pitcher_name)} <em>{escape(hand_label)}</em></span>
                </div>
            </div>
            <div class="advanced-card-badges">
                {recommended_html}
                <span>{escape(pitcher_team_code)}</span>
            </div>
        </header>
        <div class="advanced-card-tabs">
            {season_tabs}
            {''.join(hand_tabs)}
        </div>
        <div class="advanced-card-stats">{stat_html}</div>
        <p class="advanced-card-insight">{escape(insight)}</p>
        {detail_sections}
    </article>
    """


def advanced_bvp_cards_html(cards):
    return f"""
    <style>
        .advanced-bvp-controls-note {{
            color: #778191;
            font-size: 12px;
            margin: -4px 0 14px;
        }}
        .advanced-bvp-card-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 18px;
            margin-top: 12px;
        }}
        .advanced-bvp-card {{
            background: #171717;
            border: 1px solid #2a2d32;
            border-radius: 8px;
            padding: 12px;
            color: #e7e9ee;
            box-shadow: 0 12px 22px rgba(0, 0, 0, 0.18);
        }}
        .advanced-bvp-card header {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 10px;
        }}
        .advanced-card-player {{
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 0;
        }}
        .advanced-card-headshot {{
            width: 44px;
            height: 44px;
            border-radius: 7px;
            object-fit: cover;
            background: #090a0c;
        }}
        .advanced-card-player strong {{
            display: block;
            font-size: 15px;
            line-height: 1.15;
        }}
        .advanced-card-player span {{
            color: #a9b0bb;
            display: block;
            font-size: 12px;
            margin-top: 3px;
        }}
        .advanced-card-player b,
        .advanced-card-player em,
        .advanced-card-badges span {{
            background: #2b2d31;
            border-radius: 4px;
            color: #f1f3f6;
            font-style: normal;
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 0;
            padding: 2px 4px;
        }}
        .advanced-card-player b {{
            background: #bd1019;
        }}
        .advanced-card-badges {{
            display: flex;
            flex-wrap: wrap;
            justify-content: flex-end;
            gap: 5px;
        }}
        .advanced-recommended-pill {{
            background: #173f67 !important;
            color: #eef7ff !important;
        }}
        .advanced-card-tabs {{
            align-items: center;
            border-bottom: 1px solid #303238;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 10px;
            padding-bottom: 10px;
        }}
        .advanced-card-tabs span {{
            border: 1px solid transparent;
            border-radius: 6px;
            color: #9ca3af;
            font-size: 12px;
            font-weight: 800;
            padding: 5px 8px;
        }}
        .advanced-card-tabs .active {{
            border-color: #50545d;
            background: #202125;
            color: #f3f5f7;
        }}
        .advanced-card-stats {{
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 6px;
            margin: 8px 0;
        }}
        .advanced-stat-chip {{
            background: #111214;
            border: 1px solid #292c31;
            border-radius: 6px;
            padding: 7px 6px;
            min-width: 0;
        }}
        .advanced-stat-chip em {{
            color: #8c95a1;
            display: block;
            font-size: 10px;
            font-style: normal;
            font-weight: 800;
            text-transform: uppercase;
        }}
        .advanced-stat-chip strong {{
            color: #f4f6f8;
            display: block;
            font-size: 14px;
            margin-top: 2px;
        }}
        .advanced-card-insight {{
            color: #b8bec7;
            font-size: 12px;
            line-height: 1.35;
            margin: 8px 0 12px;
            min-height: 32px;
        }}
        .advanced-card-section-title {{
            align-items: center;
            display: flex;
            justify-content: space-between;
            gap: 8px;
            margin: 12px 0 6px;
        }}
        .advanced-card-section-title strong {{
            color: #d9dde4;
            font-size: 12px;
            text-transform: uppercase;
        }}
        .advanced-card-section-title span {{
            color: #8f98a5;
            font-size: 11px;
            font-weight: 800;
        }}
        .advanced-card-table {{
            border-collapse: collapse;
            font-size: 12px;
            table-layout: fixed;
            width: 100%;
        }}
        .advanced-card-table th {{
            border-bottom: 1px solid #303238;
            color: #aeb6c2;
            font-size: 11px;
            padding: 8px 6px;
            text-align: right;
            text-transform: uppercase;
        }}
        .advanced-card-table th:first-child,
        .advanced-card-table td:first-child {{
            text-align: left;
            width: 42%;
        }}
        .advanced-card-table td {{
            border-bottom: 1px solid #2b2d31;
            color: #eef0f4;
            padding: 8px 6px;
            text-align: right;
            vertical-align: middle;
        }}
        .advanced-pitch-label {{
            align-items: center;
            display: inline-flex;
            gap: 8px;
            min-width: 0;
            max-width: 100%;
        }}
        .advanced-pitch-label i {{
            border-radius: 50%;
            display: inline-block;
            flex: 0 0 auto;
            height: 10px;
            width: 10px;
        }}
        .advanced-pitch-label strong {{
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .advanced-pitch-label em {{
            color: #aeb6c2;
            font-style: normal;
            font-weight: 800;
        }}
        .advanced-probability {{
            background: #101113;
            border-radius: 5px;
            display: block;
            height: 24px;
            overflow: hidden;
            position: relative;
        }}
        .advanced-probability::before {{
            background: linear-gradient(90deg, rgba(24, 130, 197, 0.38), rgba(24, 130, 197, 0.12));
            content: "";
            inset: 0 auto 0 0;
            position: absolute;
            width: var(--probability);
        }}
        .advanced-probability b {{
            display: block;
            line-height: 24px;
            position: relative;
            z-index: 1;
        }}
        .advanced-card-table td span span {{
            color: #aeb6c2;
            font-size: 10px;
            margin-left: 1px;
        }}
        .advanced-card-empty {{
            align-items: center;
            border: 1px dashed #303238;
            border-radius: 7px;
            color: #9ca3af;
            display: flex;
            justify-content: center;
            min-height: 78px;
            padding: 12px;
            text-align: center;
        }}
        @media (max-width: 900px) {{
            .advanced-bvp-card-grid {{
                grid-template-columns: 1fr;
            }}
            .advanced-card-stats {{
                grid-template-columns: repeat(3, minmax(0, 1fr));
            }}
        }}
    </style>
    <div class="advanced-bvp-card-grid">{"".join(cards)}</div>
    """


def pitcher_team_matches_game_side(pitcher_row, game, side):
    pitcher_team_id = pd.to_numeric(pitcher_row.get("team_id"), errors="coerce")
    game_team_id = pd.to_numeric(game.get(f"{side}_team_id"), errors="coerce")
    if pd.notna(pitcher_team_id) and pd.notna(game_team_id):
        return int(pitcher_team_id) == int(game_team_id)

    pitcher_team_values = {
        safe_text(pitcher_row.get("team_name")).casefold(),
        safe_text(pitcher_row.get("Team")).casefold(),
    }
    game_team_values = {
        safe_text(game.get(f"{side}_team")).casefold(),
        safe_text(game.get(f"{side}_team_abbr")).casefold(),
    }
    pitcher_team_values.discard("")
    game_team_values.discard("")
    return bool(pitcher_team_values & game_team_values)


def selected_pitcher_advanced_matchups(
    schedule_df,
    batters_df,
    pitchers_df,
    selected_game,
    selected_batter,
    selected_pitcher,
    season,
):
    if (
        not selected_pitcher
        or schedule_df.empty
        or batters_df.empty
        or pitchers_df is None
        or pitchers_df.empty
        or "Name" not in pitchers_df.columns
    ):
        return pd.DataFrame(), pd.DataFrame()

    pitcher_rows = pitchers_df[
        pitchers_df["Name"].fillna("").astype(str).str.strip().str.casefold()
        == str(selected_pitcher).strip().casefold()
    ]
    if pitcher_rows.empty:
        return pd.DataFrame(), pd.DataFrame()

    schedule_scope = filter_by_game(schedule_df, selected_game)
    schedule_scope = filter_schedule_for_batter(
        schedule_scope,
        batters_df,
        selected_batter,
    )
    if schedule_scope.empty:
        return pd.DataFrame(), pd.DataFrame()

    override_rows = []
    for _, pitcher_row in pitcher_rows.iterrows():
        pitcher_id = pd.to_numeric(pitcher_row.get("player_id"), errors="coerce")
        if pd.isna(pitcher_id):
            continue
        pitcher_hand = normalize_pitcher_hand(
            row_value(
                pitcher_row,
                "opposing_pitcher_hand",
                "pitcher_hand",
                "throwing_hand",
                "Throws",
                "Hand",
            )
        )
        for _, game in schedule_scope.iterrows():
            for side in ("away", "home"):
                if not pitcher_team_matches_game_side(pitcher_row, game, side):
                    continue
                game_row = game.copy()
                game_row[f"{side}_probable_pitcher"] = selected_pitcher
                game_row[f"{side}_probable_pitcher_id"] = int(pitcher_id)
                if pitcher_hand:
                    game_row[f"{side}_pitcher_hand"] = pitcher_hand
                override_rows.append(game_row)

    if not override_rows:
        return pd.DataFrame(), pd.DataFrame()

    override_schedule = pd.DataFrame(override_rows).drop_duplicates(
        subset=["game_pk"],
        keep="first",
    )
    include_names = [selected_batter] if selected_batter else None
    bvp_rows = build_batter_vs_pitcher_matchups(
        schedule_df=override_schedule,
        batters_df=batters_df,
        season=int(season),
        min_pa=0,
        include_batter_names=include_names,
    )
    hand_rows = build_batter_vs_hand_matchups(
        schedule_df=override_schedule,
        batters_df=batters_df,
        season=int(season),
        min_pa=0,
        include_batter_names=include_names,
    )
    for frame in (bvp_rows, hand_rows):
        if frame.empty or "opposing_pitcher" not in frame.columns:
            continue
        frame.drop(
            frame[
                frame["opposing_pitcher"].fillna("").astype(str).str.strip().str.casefold()
                != str(selected_pitcher).strip().casefold()
            ].index,
            inplace=True,
        )
        frame.reset_index(drop=True, inplace=True)
    return bvp_rows, hand_rows


def render_advanced_bvp_section(
    filtered_bvp_matchups,
    filtered_hand_matchups,
    schedule_df=None,
    batters_df=None,
    pitchers_df=None,
    selected_game="All Games",
    season=None,
    selected_batter=None,
    selected_pitcher=None,
):
    if filtered_bvp_matchups.empty:
        fallback_bvp, fallback_hand = selected_pitcher_advanced_matchups(
            schedule_df if schedule_df is not None else pd.DataFrame(),
            batters_df if batters_df is not None else pd.DataFrame(),
            pitchers_df if pitchers_df is not None else pd.DataFrame(),
            selected_game,
            selected_batter,
            selected_pitcher,
            season or current_app_date().year,
        )
        filtered_bvp_matchups = fallback_bvp
        filtered_hand_matchups = fallback_hand
    if filtered_bvp_matchups.empty:
        st.warning("No advanced batter-vs-pitcher matchup data was found for this selection.")
        return

    season = int(season or current_app_date().year)
    comparison_seasons = [season]
    if season - 1 >= 2005:
        comparison_seasons.append(season - 1)

    with st.container(key="advanced_bvp_customizer"):
        control_columns = st.columns(
            [0.78, 0.72, 0.78, 0.52],
            gap="small",
            vertical_alignment="bottom",
        )
        with control_columns[0]:
            focus_mode = render_box_tabs(
                "Advanced BVP focus",
                ["Pitcher mix", "Both", "Batter results"],
                "advanced_bvp_focus_mode",
                "Pitcher mix",
            )
        with control_columns[1]:
            analysis_season_label = render_box_tabs(
                "Advanced BVP season",
                [str(option) for option in comparison_seasons],
                "advanced_bvp_analysis_season",
                str(comparison_seasons[0]),
            )
            analysis_season = int(analysis_season_label)
        with control_columns[2]:
            split_mode = render_box_tabs(
                "Advanced BVP split",
                ["Matchup hand", "vs LHP", "vs RHP"],
                "advanced_bvp_split_mode",
                "Matchup hand",
            )
        with control_columns[3]:
            card_limit = st.slider(
                "Players",
                min_value=2,
                max_value=24,
                value=8,
                step=1,
                key="advanced_bvp_card_limit",
                label_visibility="collapsed",
            )
        sort_mode = st.selectbox(
            "Sort cards",
            ["Best matchup", "Most BvP history", "Batter name"],
            key="advanced_bvp_sort_mode",
            label_visibility="collapsed",
        )
        st.html(
            '<div class="advanced-bvp-controls-note">'
            "Pitcher mix is season pitch probability from completed-game pitch events. "
            "Batter results are split by pitch type for the selected hand."
            "</div>"
        )

    display_bvp = default_matchup_display(
        filtered_bvp_matchups,
        "matchup_grade",
        selected_batter=selected_batter,
        selected_pitcher=selected_pitcher,
        limit=60,
    )
    advanced_df = build_advanced_matchup_rows(display_bvp, filtered_hand_matchups)
    if advanced_df.empty:
        st.warning("No advanced batter-vs-pitcher matchup data was found for this selection.")
        return
    if sort_mode == "Most BvP history":
        advanced_df = advanced_df.sort_values(
            ["PA", "AB", "AVG"],
            ascending=[False, False, False],
            na_position="last",
        )
    elif sort_mode == "Batter name":
        advanced_df = advanced_df.sort_values(
            "batter",
            ascending=True,
            na_position="last",
            key=lambda series: series.fillna("").astype(str).str.casefold(),
        )
    else:
        advanced_df = advanced_df.sort_values(
            ["weather_adjusted_score", "SLG", "OPS", "PA"],
            ascending=[False, False, False, False],
            na_position="last",
        )

    recommended_pitchers = set(
        name.casefold()
        for name in scheduled_probable_pitcher_names(
            filter_by_game(
                schedule_df if schedule_df is not None else pd.DataFrame(),
                selected_game,
            )
        )
    )
    visible_rows = []
    for _, row in advanced_df.head(card_limit).iterrows():
        pitcher_id = pd.to_numeric(row.get("opposing_pitcher_id"), errors="coerce")
        batter_id = pd.to_numeric(row.get("batter_id"), errors="coerce")
        matchup_hand = normalize_pitcher_hand(row.get("opposing_pitcher_hand"))
        if split_mode == "vs LHP":
            split_hand = "L"
        elif split_mode == "vs RHP":
            split_hand = "R"
        else:
            split_hand = matchup_hand
        visible_rows.append(
            {
                "row": row,
                "pitcher_id": int(pitcher_id) if pd.notna(pitcher_id) else None,
                "batter_id": int(batter_id) if pd.notna(batter_id) else None,
                "split_hand": split_hand,
            }
        )

    visible_pitcher_ids = tuple(
        dict.fromkeys(
            item["pitcher_id"]
            for item in visible_rows
            if item["pitcher_id"] is not None
        )
    )
    db_key = database.db_cache_key()
    pitcher_profiles = load_pitcher_pitch_type_profiles(
        visible_pitcher_ids,
        analysis_season,
        db_key,
    )
    batter_profiles_by_hand = {}
    for split_hand in tuple(
        dict.fromkeys(
            item["split_hand"]
            for item in visible_rows
            if item["batter_id"] is not None and item["split_hand"]
        )
    ):
        batter_ids = tuple(
            dict.fromkeys(
                item["batter_id"]
                for item in visible_rows
                if item["batter_id"] is not None
                and item["split_hand"] == split_hand
            )
        )
        batter_profiles_by_hand[split_hand] = load_batter_pitch_type_profiles(
            batter_ids,
            analysis_season,
            split_hand,
            db_key,
        )

    cards = []
    for item in visible_rows:
        row = item["row"]
        pitcher_id = item["pitcher_id"]
        batter_id = item["batter_id"]
        split_hand = item["split_hand"]
        pitch_mix_df = pitcher_profiles.get(pitcher_id, pd.DataFrame())
        pitch_type_df = (
            batter_profiles_by_hand
            .get(split_hand, {})
            .get(batter_id, pd.DataFrame())
        )

        cards.append(
            advanced_bvp_card_html(
                row,
                pitch_mix_df,
                pitch_type_df,
                analysis_season,
                comparison_seasons,
                split_hand,
                focus_mode,
                row_text(row, "opposing_pitcher").casefold()
                in recommended_pitchers,
            )
        )

    st.html(advanced_bvp_cards_html(cards))
    st.html(
        f'<div class="research-table-note">Showing {min(card_limit, len(advanced_df)):,} '
        f"of {len(advanced_df):,} player breakdowns.</div>"
    )


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

    display_bvp = filtered_bvp_matchups.copy()
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

    display_hand = filtered_hand_matchups.copy()
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


@st.fragment
def render_matchup_filter_fragment(
    schedule_df,
    batters_df,
    pitchers_df,
    season,
    active_matchup_table,
    bvp_matchups,
    hand_matchups,
    pitcher_k_matchups,
):
    """Keep common matchup filters on a fragment-only rerun path."""
    if active_matchup_table in {HVP_PAGE_TAB_LABEL, BULLPEN_TAB_LABEL}:
        render_bvp_research_page(
            schedule_df=schedule_df,
            batters_df=batters_df,
            pitchers_df=pitchers_df,
            season=season,
            selected_date=st.session_state.selected_game_date,
            database_cache_key=database.db_cache_key(),
            active_roster_loader=load_active_team_rosters,
            analysis_mode=(
                "Projected Bullpen"
                if active_matchup_table == BULLPEN_TAB_LABEL
                else "Specific Pitcher"
            ),
        )
        return

    game_options = get_game_options(schedule_df)
    if st.session_state.get("selected_game") not in game_options:
        st.session_state.selected_game = "All Games"

    with st.container(key="matchup_filter_toolbar"):
        game_column, batter_column, pitcher_column = st.columns(
            [1.25, 1, 1],
            gap="small",
            vertical_alignment="bottom",
        )
        with game_column:
            selected_game = st.selectbox(
                "Game",
                game_options,
                key="selected_game",
                label_visibility="collapsed",
            )

        matchup_schedule_df = filter_by_game(schedule_df, selected_game)
        batter_options = scheduled_batter_options(
            batters_df,
            matchup_schedule_df,
        )
        pitcher_options = scheduled_pitcher_options(matchup_schedule_df, pitchers_df)
        recommended_pitchers = scheduled_probable_pitcher_names(matchup_schedule_df)

        if st.session_state.get("selected_batter") not in [
            None,
            *batter_options,
        ]:
            st.session_state.selected_batter = None
        if st.session_state.get("selected_pitcher") not in [
            None,
            *pitcher_options,
        ]:
            st.session_state.selected_pitcher = None

        with batter_column:
            selected_batter = st.selectbox(
                "Batter",
                batter_options,
                index=None,
                placeholder="Batter...",
                key="selected_batter",
                label_visibility="collapsed",
            )
        with pitcher_column:
            selected_pitcher = st.selectbox(
                "Pitcher",
                pitcher_options,
                index=None,
                placeholder="Pitcher...",
                key="selected_pitcher",
                label_visibility="collapsed",
            )

    if active_matchup_table == "Hitter vs Pitcher":
        render_bvp_table_fragment(
            filter_prebuilt_matchups(
                bvp_matchups,
                schedule_df,
                batters_df,
                selected_game,
                selected_batter,
                selected_pitcher,
            ),
            selected_batter=selected_batter,
            selected_pitcher=selected_pitcher,
        )
    elif active_matchup_table == "Hitter vs Throwing Hand":
        render_hand_table_fragment(
            filter_prebuilt_matchups(
                hand_matchups,
                schedule_df,
                batters_df,
                selected_game,
                selected_batter,
                selected_pitcher,
            ),
            selected_batter=selected_batter,
            selected_pitcher=selected_pitcher,
        )
    elif active_matchup_table == "Pitcher vs Opponent":
        render_pitcher_table_fragment(
            filter_prebuilt_matchups(
                pitcher_k_matchups,
                schedule_df,
                batters_df,
                selected_game,
                selected_batter,
                selected_pitcher,
            ),
            selected_pitcher=selected_pitcher,
        )


@st.fragment(run_every="1s")
def render_hand_split_loading(preload_future):
    if preload_future is None or preload_future.done():
        st.rerun(scope="app")
    st.info("Preparing throwing-hand splits in the background...")


UPDATE_NOTICE_VERSION = "1.2"
UPDATE_NOTICE_STORAGE_KEY = f"all-rise-update-{UPDATE_NOTICE_VERSION}-seen"
UPDATE_NOTICE_SESSION_KEY = f"show_update_notice_{UPDATE_NOTICE_VERSION.replace('.', '_')}"
UPDATE_NOTICE_PREVIEW_PARAM = "preview_update"


def dismiss_update_notice():
    st.session_state[UPDATE_NOTICE_SESSION_KEY] = False
    st.query_params.pop(UPDATE_NOTICE_PREVIEW_PARAM, None)


def force_update_notice_preview():
    return safe_text(current_query_value(UPDATE_NOTICE_PREVIEW_PARAM)).lower() in {
        "1",
        "true",
        "update-1.2",
    }


@st.dialog(
    f"Update {UPDATE_NOTICE_VERSION}",
    width="large",
    on_dismiss=dismiss_update_notice,
)
def render_update_notice_dialog():
    st.markdown(
        f"""
        <div class="update-notice">
            <div class="update-notice-kicker">All Rise Analytics</div>
            <h2 class="update-notice-title">Update {UPDATE_NOTICE_VERSION} is live</h2>
            <p class="update-notice-copy">
                New live game tools, deeper Stats views, and upgraded Streaks tracking are now available.
                Here is what is worth checking out first.
            </p>
            <div class="update-notice-list">
                <div class="update-notice-item">
                    <strong>Stats tab for live games</strong>
                    <span>Open a game and switch to Stats to see contact locations, hits, outs, strike zone activity, and momentum.</span>
                </div>
                <div class="update-notice-item">
                    <strong>Contact charts now carry over</strong>
                    <span>Batted-ball locations can stay available when you revisit a game, including previous-day games that have contact data.</span>
                </div>
                <div class="update-notice-item">
                    <strong>Streaks got sharper</strong>
                    <span>Track batter, pitcher, and team win streaks with updated categories, cleaner leaderboards, and better matchup context.</span>
                </div>
                <div class="update-notice-item">
                    <strong>Live player profiles</strong>
                    <span>Tap the current pitcher, batter, or on-deck hitter from Game Center to jump straight into their profile.</span>
                </div>
                <div class="update-notice-item">
                    <strong>Game cards show more at a glance</strong>
                    <span>Live games can now show base runners, outs, count context, weather, and your local start time right from the slate.</span>
                </div>
                <div class="update-notice-item">
                    <strong>Pitch tracking added</strong>
                    <span>Use the strike zone view to follow balls, strikes, and balls in play during live game action.</span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Check out Update 1.2", key="dismiss_update_1_2"):
        dismiss_update_notice()
        st.rerun(scope="app")


def render_update_notice_probe():
    event = RESEARCH_TABLE_COMPONENT(
        table_html="",
        table_height=1,
        local_storage_key=UPDATE_NOTICE_STORAGE_KEY,
        local_storage_value=UPDATE_NOTICE_VERSION,
        local_storage_event_type="update_notice",
        key=f"update-notice-probe-{UPDATE_NOTICE_VERSION}",
        default=None,
    )
    if isinstance(event, dict) and event.get("type") == "update_notice":
        event_key = f"update_notice_event_{UPDATE_NOTICE_VERSION}"
        event_id = safe_text(event.get("event_id"))
        if event_id and event_id != st.session_state.get(event_key):
            st.session_state[event_key] = event_id
            st.session_state[UPDATE_NOTICE_SESSION_KEY] = True


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
    for secret_name in (
        "MLB_DB_URL",
        "TURSO_DATABASE_URL",
        "TURSO_AUTH_TOKEN",
        "TURSO_READ_ONLY",
        "TURSO_DATA_VERSION",
    ):
        if secret_name in st.secrets:
            os.environ.setdefault(secret_name, str(st.secrets[secret_name]))
except Exception:
    pass


if "selected_game_date" not in st.session_state:
    st.session_state.selected_game_date = app_today


render_update_notice_probe()
if force_update_notice_preview():
    st.session_state[UPDATE_NOTICE_SESSION_KEY] = True
if st.session_state.get(UPDATE_NOTICE_SESSION_KEY):
    render_update_notice_dialog()


def shift_selected_date(days):
    st.session_state.selected_game_date += timedelta(days=days)


view_options = [
    "Matchups",
    "Games",
    "Weather",
    "Streaks",
    "Players",
    "Player Stats",
    "Team Stats",
    "Details",
]
pending_active_view = st.session_state.pop("pending_active_view", None)
previous_active_view = st.session_state.get("active_view")
query_view = current_query_value("view")
query_matchup_table = safe_text(current_query_value("matchup_table"))
legacy_hvp_table_labels = {"Advanced BvP"}
if pending_active_view in view_options:
    initial_view = pending_active_view
elif query_view in view_options:
    initial_view = query_view
elif previous_active_view in view_options:
    initial_view = previous_active_view
else:
    initial_view = "Games"
if initial_view == "Overview":
    initial_view = "Games"
if initial_view not in view_options:
    initial_view = "Games"
st.session_state.active_view = initial_view
query_game_pk = pd.to_numeric(current_query_value("game_pk"), errors="coerce")
is_hvp_query = (
    initial_view == "Matchups"
    and (
        query_matchup_table.casefold() == HVP_PAGE_TAB_LABEL.casefold()
        or query_matchup_table in legacy_hvp_table_labels
    )
)
if initial_view == "Games" and pd.isna(query_game_pk):
    st.session_state.selected_boxscore_game_pk = None
    st.query_params.pop("game_tab", None)
elif initial_view != "Games":
    st.session_state.selected_boxscore_game_pk = None
    if not is_hvp_query:
        st.query_params.pop("game_pk", None)
    st.query_params.pop("game_tab", None)
if initial_view != "Players" or not current_query_value("player"):
    st.session_state.selected_player_profile = None
    st.session_state.player_profile_return = None
active_view = render_view_tabs(view_options)
view_loading = st.empty()
if active_view not in {"Games", "Details"}:
    database.ensure_database()
needs_schedule = active_view in {"Games", "Matchups", "Weather", "Streaks"}
needs_weather = active_view in {"Games", "Matchups", "Weather"}
MATCHUP_TABLE_OPTIONS = [
    "Hitter vs Pitcher",
    "Hitter vs Throwing Hand",
    HVP_PAGE_TAB_LABEL,
    "Pitcher vs Opponent",
    BULLPEN_TAB_LABEL,
]
matchup_table_options = MATCHUP_TABLE_OPTIONS
session_matchup_table = st.session_state.get("active_matchup_table")
if session_matchup_table in legacy_hvp_table_labels:
    session_matchup_table = HVP_PAGE_TAB_LABEL
if query_matchup_table in legacy_hvp_table_labels:
    query_matchup_table = HVP_PAGE_TAB_LABEL
if session_matchup_table in matchup_table_options:
    active_matchup_table = session_matchup_table
elif query_matchup_table in matchup_table_options:
    active_matchup_table = query_matchup_table
elif any(
    query_matchup_table.casefold() == option.casefold()
    for option in matchup_table_options
):
    active_matchup_table = next(
        option
        for option in matchup_table_options
        if query_matchup_table.casefold() == option.casefold()
    )
else:
    active_matchup_table = st.session_state.get(
        "active_matchup_table",
        matchup_table_options[0],
    )
if active_matchup_table not in matchup_table_options:
    active_matchup_table = matchup_table_options[0]
    st.session_state.active_matchup_table = active_matchup_table
st.session_state.active_matchup_table = active_matchup_table
hand_split_preload_future = None
if active_view == "Matchups" and active_matchup_table == "Hitter vs Throwing Hand":
    _, hand_split_preload_future = start_hand_split_preload(
        st.session_state.selected_game_date.year
    )

game_filter_slot = None
selected_date = st.session_state.selected_game_date

if active_view in {"Games", "Weather", "Streaks"}:
    page_title = {
        "Games": "Today's Games",
        "Weather": "Weather Watch",
        "Streaks": "Streak Leaders",
    }[active_view]
    st.markdown(
        f"""
        <div class="section-shell aligned-page-title">
            <div class="section-title">{page_title} <span class="title-date">{format_display_date(selected_date)}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

if needs_schedule and active_view != "Weather":
    toolbar_key = {
        "Games": "games_toolbar",
        "Weather": "weather_toolbar",
        "Streaks": "streak_toolbar",
        "Matchups": "matchup_toolbar",
    }[active_view]
    with st.container(key=toolbar_key):
        if active_view == "Matchups":
            if active_matchup_table == HVP_PAGE_TAB_LABEL:
                active_matchup_table = render_box_tabs(
                    "matchup-table-tabs",
                    matchup_table_options,
                    "active_matchup_table",
                    matchup_table_options[0],
                )
                st.query_params["matchup_table"] = active_matchup_table
                previous_column = None
                date_column = None
                next_column = None
            else:
                toolbar_columns = st.columns(
                    [0.74, 0.05, 0.16, 0.05],
                    gap="small",
                    vertical_alignment="bottom",
                )
                with toolbar_columns[0]:
                    active_matchup_table = render_box_tabs(
                        "matchup-table-tabs",
                        matchup_table_options,
                        "active_matchup_table",
                        matchup_table_options[0],
                    )
                    st.query_params["matchup_table"] = active_matchup_table
                previous_column = toolbar_columns[1]
                date_column = toolbar_columns[2]
                next_column = toolbar_columns[3]
        elif active_view == "Games":
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
        else:
            toolbar_columns = st.columns(
                [0.38, 1.45, 0.38],
                gap="small",
                vertical_alignment="bottom",
            )
            previous_column = toolbar_columns[0]
            date_column = toolbar_columns[1]
            next_column = toolbar_columns[2]

        if previous_column is not None:
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


@st.cache_data(show_spinner=False, ttl=30)
def load_schedule(game_date):
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
            log_background_exception("injury monitor")

    start_daemon_thread("injury-monitor", refresh_once)
    return state


def monitored_injury_report(team_ids, game_date):
    state = start_injury_monitor(tuple(team_ids), str(game_date))
    with state["lock"]:
        return dict(state["report"])


@st.cache_data(show_spinner=False, ttl=600)
def load_published_weather(cache_version):
    fetcher = getattr(
        weather_service,
        "fetch_published_weather_cache",
        None,
    )
    if not fetcher:
        return pd.DataFrame()
    return fetcher(
        cache_bust=f"{app_today.isoformat()}-{cache_version}",
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
                log_background_exception("live stat monitor")
                state["ready"].set()
            time.sleep(600)

    start_daemon_thread("live-stat-monitor", refresh_forever)
    return state


def monitored_live_stat_tables(season):
    state = start_live_stat_monitor(int(season))
    with state["lock"]:
        return state["batters"].copy(), state["pitchers"].copy()


@st.cache_data(show_spinner=False, ttl=3600, max_entries=24)
def load_bvp_matchups(schedule_df, batters_df, season, db_key):
    return build_batter_vs_pitcher_matchups(
        schedule_df=schedule_df,
        batters_df=batters_df,
        season=int(season),
        min_pa=0,
    )


@st.cache_data(show_spinner=False, ttl=3600, max_entries=24)
def load_hand_matchups(schedule_df, batters_df, season, db_key):
    return build_batter_vs_hand_matchups(
        schedule_df=schedule_df,
        batters_df=batters_df,
        season=int(season),
        min_pa=0,
    )


@st.cache_data(show_spinner=False, ttl=3600, max_entries=24)
def load_pitcher_matchups(schedule_df, batters_df, pitchers_df, db_key):
    return build_pitcher_k_matchups(
        schedule_df=schedule_df,
        batters_df=batters_df,
        pitchers_df=pitchers_df,
        min_pa=0,
    )


@st.cache_data(show_spinner=False, ttl=9)
def load_game_boxscore(game_pk):
    return get_game_boxscore(int(game_pk))


@st.cache_data(show_spinner=False, ttl=2, max_entries=32)
def load_live_game_feed(game_pk):
    return get_live_game_feed(int(game_pk))


@st.cache_data(show_spinner=False, ttl=600)
def load_player_profile(player_id):
    return get_player_profile(int(player_id))


@st.cache_data(show_spinner=False, ttl=900)
def load_team_season_results(season, through_date):
    return get_season_team_results(int(season), str(through_date))


@st.cache_data(show_spinner=False, ttl=21600)
def load_probable_pitcher_career_logs(player_ids, through_date):
    return get_people_career_game_logs(
        tuple(player_ids),
        "pitching",
        str(through_date),
    )


@st.cache_data(show_spinner=False, ttl=21600)
def load_historical_game_results(game_pks):
    return get_game_results(tuple(game_pks))


@st.cache_data(show_spinner=False, ttl=600)
def load_active_team_rosters(team_records, roster_date):
    return get_active_team_rosters(
        tuple(team_records),
        str(roster_date),
    )


@st.cache_data(show_spinner=False, ttl=600, max_entries=256)
def _load_database_player_game_log(player_id, group, season, db_key):
    try:
        live_rows = get_player_game_log(
            int(player_id),
            group,
            int(season),
        )
        if not live_rows.empty:
            return live_rows
    except Exception:
        log_background_exception("player game log live fallback")

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


def load_database_player_game_log(player_id, group, season):
    return _load_database_player_game_log(
        int(player_id),
        group,
        int(season),
        database.db_cache_key(),
    )


@st.cache_data(show_spinner=False, ttl=600, max_entries=256)
def _load_batter_pitch_type_profile(player_id, season, pitcher_hand, db_key):
    return pd.DataFrame(
        get_batter_pitch_type_stats(
            int(player_id),
            int(season),
            pitcher_hand=pitcher_hand,
        )
    )


def load_batter_pitch_type_profile(player_id, season, pitcher_hand):
    return _load_batter_pitch_type_profile(
        int(player_id),
        int(season),
        pitcher_hand,
        database.db_cache_key(),
    )


@st.cache_data(show_spinner=False, ttl=600, max_entries=128)
def load_batter_pitch_type_profiles(batter_ids, season, pitcher_hand, db_key):
    return batch_batter_pitch_type_profiles(
        tuple(batter_ids),
        int(season),
        pitcher_hand,
    )


@st.cache_data(show_spinner=False, ttl=600, max_entries=256)
def _load_pitcher_pitch_type_profile(player_id, season, db_key):
    return pd.DataFrame(
        get_pitcher_pitch_type_stats(
            int(player_id),
            int(season),
        )
    )


def load_pitcher_pitch_type_profile(player_id, season):
    return _load_pitcher_pitch_type_profile(
        int(player_id),
        int(season),
        database.db_cache_key(),
    )


@st.cache_data(show_spinner=False, ttl=600, max_entries=128)
def load_pitcher_pitch_type_profiles(pitcher_ids, season, db_key):
    return batch_pitcher_pitch_type_profiles(tuple(pitcher_ids), int(season))


@st.cache_data(show_spinner=False, ttl=1800, max_entries=32)
def _load_batter_streak_logs(player_ids, season, db_key):
    loader = getattr(database, "get_batter_streak_game_logs_from_db", None)
    if loader is None:
        return pd.DataFrame()
    return pd.DataFrame(loader(tuple(player_ids), season))


@st.cache_data(show_spinner=False, ttl=1800)
def load_batter_composite_streak_logs(player_ids, season):
    return fetch_people_game_logs(
        tuple(player_ids),
        "hitting",
        int(season),
    )


def load_batter_streak_logs(player_ids, season):
    return _load_batter_streak_logs(
        tuple(player_ids),
        int(season),
        database.db_cache_key(),
    )


@st.cache_data(show_spinner=False, ttl=1800, max_entries=32)
def _load_pitcher_streak_logs(player_ids, season, db_key):
    loader = getattr(database, "get_pitcher_streak_game_logs_from_db", None)
    if loader is None:
        return pd.DataFrame()
    return pd.DataFrame(loader(tuple(player_ids), season))


def load_pitcher_streak_logs(player_ids, season):
    return _load_pitcher_streak_logs(
        tuple(player_ids),
        int(season),
        database.db_cache_key(),
    )


def streak_history_cache_path(group, season):
    # Local-only cache generated by this app; never read from remote downloads.
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
                log_background_exception("streak history monitor")
                state["ready"].set()
            time.sleep(300)

    start_daemon_thread("streak-history-monitor", refresh_forever)
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


if active_view in {"Games", "Matchups", "Streaks", "Players", "Team Stats", "Player Stats"}:
    start_live_stat_monitor(season)

if needs_schedule:
    try:
        live_schedule_df = load_schedule(selected_date)
    except Exception:
        view_loading.empty()
        st.warning(
            "The live MLB schedule is temporarily unavailable. "
            "Check your connection and try again."
        )
        if st.button("Retry schedule", key="retry_schedule"):
            load_schedule.clear()
            st.rerun(scope="app")
        st.stop()

    if live_schedule_df.attrs.get("schedule_source") == "saved":
        st.warning(
            "Live schedule updates are temporarily unavailable. "
            "Showing the last saved schedule for this date."
        )

    if live_schedule_df.empty:
        view_loading.empty()
        st.warning("No MLB games found for this date.")
        st.stop()

    if needs_weather:
        schedule_df = weather_schedule_frame(live_schedule_df)
        published_weather = load_published_weather(cache_version=3)
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
    start_live_streak_monitor(live_streak_game_pks(schedule_df))

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
    "Games",
    "Matchups",
    "Streaks",
    "Players",
    "Team Stats",
    "Player Stats",
}
needs_matchups = active_view == "Matchups"

batters_df = pd.DataFrame()
pitchers_df = pd.DataFrame()
bvp_matchups = pd.DataFrame()
hand_matchups = pd.DataFrame()
pitcher_k_matchups = pd.DataFrame()
hand_splits_loading = False

if needs_stats:
    batters_df, pitchers_df = monitored_live_stat_tables(season)
    pitchers_df = ensure_probable_pitcher_rows(pitchers_df, schedule_df)

if active_view == "Games":
    query_game_pk = pd.to_numeric(current_query_value("game_pk"), errors="coerce")
    if pd.notna(query_game_pk):
        query_game_row = selected_game_row(schedule_df, int(query_game_pk))
        if query_game_row is not None:
            query_game_label = row_text(query_game_row, "game")
            if query_game_label in game_options:
                st.session_state.selected_game = query_game_label
    if st.session_state.get("selected_game") not in game_options:
        st.session_state.selected_game = "All Games"
    selected_game = game_filter_slot.selectbox(
        "Game",
        game_options,
        key="selected_game",
        label_visibility="collapsed",
    )
else:
    selected_game = "All Games"

if needs_matchups and active_matchup_table not in {HVP_PAGE_TAB_LABEL, BULLPEN_TAB_LABEL}:
    # Build each table from the full slate. Game/player controls below only
    # filter these cached results, so changing a filter does not rebuild stats.
    hitter_pool = matchup_batter_pool(
        batters_df,
        schedule_df,
        max_per_team=max(1, len(batters_df)),
        min_pa=0,
    )
    pitcher_pool = matchup_batter_pool(
        batters_df,
        schedule_df,
        max_per_team=7,
        min_pa=100,
    )

    if active_matchup_table == "Hitter vs Pitcher":
        bvp_matchups = load_bvp_matchups(
            schedule_df,
            hitter_pool,
            season,
            database.db_cache_key(),
        )
    if active_matchup_table == "Hitter vs Throwing Hand":
        hand_splits_loading = (
            hand_split_preload_future is not None
            and not hand_split_preload_future.done()
        )
        if not hand_splits_loading:
            hand_matchups = load_hand_matchups(
                schedule_df,
                hitter_pool,
                season,
                database.db_cache_key(),
            )
    if active_matchup_table == "Pitcher vs Opponent":
        pitcher_k_matchups = load_pitcher_matchups(
            schedule_df,
            pitcher_pool,
            pitchers_df,
            database.db_cache_key(),
        )

    injury_report = monitored_injury_report(
        sorted(schedule_team_ids(schedule_df)),
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
filtered_bvp_matchups = bvp_matchups
filtered_hand_matchups = hand_matchups
filtered_pitcher_k_matchups = pitcher_k_matchups


if active_view == "Games":
    render_games_tab(
        schedule_df,
        filtered_schedule_df,
        selected_game,
        selected_date,
        batters_df=batters_df,
    )

elif active_view == "Weather":
    render_weather_tab(schedule_df, selected_date)

elif active_view == "Matchups":
    if hand_splits_loading:
        render_hand_split_loading(hand_split_preload_future)
    else:
        render_matchup_filter_fragment(
            schedule_df,
            batters_df,
            pitchers_df,
            season,
            active_matchup_table,
            filtered_bvp_matchups,
            filtered_hand_matchups,
            filtered_pitcher_k_matchups,
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

elif active_view == "Players":
    render_players_tab(batters_df, pitchers_df, season)

elif active_view == "Player Stats":
    render_player_stats_tab(batters_df, pitchers_df, season)

elif active_view == "Details":
    how_tab, glossary_tab = st.tabs(["How It Works", "Glossary"])

    with how_tab:
        st.markdown(
            """
            ### How the app works

            - **Games:** Use today's schedule to check live scores, weather, probable pitchers, and click a game for the box score.
            - **Weather:** Review game-by-game forecast, animated wind direction, and retractable-roof alerts.
            - **Matchups:** Compare hitter and pitcher matchups, then click a player name to open the related game log.
            - **Streaks:** See the top active hitting and pitching streaks with live game updates.
            - **Players:** Search current players, open a full profile, and browse season game logs.
            - **Player Stats:** Sort season player leaderboards and click a player to open their profile.
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
