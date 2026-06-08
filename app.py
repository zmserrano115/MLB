from datetime import date
from html import escape
import os
from urllib.parse import urlencode

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from src.mlb_schedule import get_daily_schedule
from src.weather import (
    enrich_schedule_with_weather,
    preserve_previous_weather,
)
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

    .research-table-shell {
        max-height: 540px;
        overflow: auto;
        overscroll-behavior: contain;
        -webkit-overflow-scrolling: touch;
        border: 1px solid var(--line);
        background: #ffffff;
        scrollbar-gutter: stable;
    }

    .research-table {
        width: max-content;
        min-width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        color: var(--text);
        font-size: 12px;
        font-variant-numeric: tabular-nums;
    }

    .research-table th,
    .research-table td {
        height: 36px;
        padding: 0 10px;
        border: 0;
        border-bottom: 1px solid #edf0f4;
        background: #ffffff;
        text-align: right;
        white-space: nowrap;
    }

    .research-table th {
        position: sticky;
        top: 0;
        z-index: 8;
        height: 38px;
        background: #eef2f6;
        color: #647184;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }

    .research-table tbody tr:hover td {
        background: #f7fafc;
    }

    .research-table .align-left {
        text-align: left;
    }

    .research-table .sticky-game {
        position: sticky;
        left: 0;
        z-index: 5;
        width: 92px;
        min-width: 92px;
        text-align: center;
        box-shadow: 1px 0 0 #dfe5ec;
    }

    .research-table .sticky-player {
        position: sticky;
        left: 92px;
        z-index: 5;
        width: 150px;
        min-width: 150px;
        text-align: left;
        box-shadow: 1px 0 0 #dfe5ec;
    }

    .research-table th.sticky-game,
    .research-table th.sticky-player {
        z-index: 10;
        background: #e8edf3;
    }

    .research-game {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 5px;
    }

    .research-game img {
        width: 24px;
        height: 24px;
        object-fit: contain;
    }

    .research-at {
        color: var(--muted-2);
        font-size: 10px;
        font-weight: 700;
    }

    .research-player-link {
        color: #245f96;
        font-weight: 700;
        text-decoration: none;
    }

    .research-player-link:hover {
        color: #123f69;
        text-decoration: underline;
    }

    .research-weather {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        min-width: 86px;
    }

    .research-weather .weather-svg {
        width: 17px;
        height: 17px;
    }

    .research-grade,
    .research-edge {
        display: inline-block;
        padding: 3px 7px;
        border-radius: 2px;
        font-size: 10px;
        font-weight: 700;
    }

    .research-grade.good,
    .research-edge.hitter {
        color: #247a4d;
        background: #edf8f2;
    }

    .research-grade.neutral,
    .research-edge.neutral {
        color: #687384;
        background: #f2f4f7;
    }

    .research-grade.avoid,
    .research-edge.pitcher {
        color: #b43b3b;
        background: #fff0f0;
    }

    .research-grade.sample {
        color: #3f6fa8;
        background: #eef5ff;
    }

    .research-grade.none {
        color: #687384;
        background: #f2f4f7;
    }

    .matchup-log-shell {
        margin-top: 18px;
        padding-top: 14px;
        border-top: 1px solid var(--line);
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

        .research-table-shell {
            max-height: 500px;
        }

        .research-table {
            font-size: 11px;
        }

        .research-table th,
        .research-table td {
            padding: 0 8px;
        }

        .research-table .sticky-game {
            width: 82px;
            min-width: 82px;
        }

        .research-table .sticky-player {
            left: 82px;
            width: 132px;
            min-width: 132px;
        }

        .research-game img {
            width: 21px;
            height: 21px;
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


def grade_cell_style(value):
    grade_class = matchup_grade_class(value)
    colors = {
        "good": ("#247a4d", "#edf8f2"),
        "neutral": ("#9a6810", "#fff8e8"),
        "avoid": ("#b43b3b", "#fff0f0"),
        "sample": ("#3f6fa8", "#eef5ff"),
        "none": ("#687384", "#f2f4f7"),
    }
    color, background = colors[grade_class]
    return f"color: {color}; background-color: {background}; font-weight: 700"


def weather_edge_cell_style(value):
    edge = str(value or "").lower()
    if "hitter boost" in edge:
        color, background = "#247a4d", "#edf8f2"
    elif "pitcher boost" in edge:
        color, background = "#b43b3b", "#fff0f0"
    elif "neutral" in edge:
        color, background = "#687384", "#f2f4f7"
    else:
        color, background = "#9a6810", "#fff8e8"
    return f"color: {color}; background-color: {background}; font-weight: 700"


def make_light_table(df):
    styler = (
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

    name_columns = [
        column for column in ("batter", "pitcher") if column in df.columns
    ]
    if name_columns:
        styler = styler.set_properties(
            subset=name_columns,
            **{
                "color": "#245f96",
                "font-weight": "700",
                "text-decoration": "underline",
            },
        )

    grade_columns = [
        column
        for column in ("matchup_grade", "k_matchup_grade", "history_grade")
        if column in df.columns
    ]
    for column in grade_columns:
        styler = styler.map(grade_cell_style, subset=[column])

    if "weather_edge" in df.columns:
        styler = styler.map(weather_edge_cell_style, subset=["weather_edge"])

    return styler


def show_table(df, key=None, selectable_column=None):
    table_data = make_light_table(df)
    row_height = 36
    table_height = min(row_height * (len(df) + 1) + 8, 540)

    kwargs = {
        "data": table_data,
        "width": "stretch",
        "height": max(table_height, 180),
        "hide_index": True,
        "column_config": table_column_config(),
        "row_height": row_height,
        "placeholder": "-",
    }

    if selectable_column:
        kwargs["on_select"] = "rerun"
        kwargs["selection_mode"] = "single-cell"
        kwargs["key"] = key

    return st.dataframe(**kwargs)


def apply_matchup_row_limit(df, row_setting):
    if row_setting == "All matchups":
        return df.copy()
    return df.head(int(row_setting)).copy()


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
        "game_away_logo": st.column_config.ImageColumn(
            "",
            width=28,
            pinned=True,
        ),
        "game_at": st.column_config.TextColumn(
            "",
            width=18,
            pinned=True,
            alignment="center",
        ),
        "game_home_logo": st.column_config.ImageColumn(
            "",
            width=28,
            pinned=True,
        ),
        "weather_icon_url": st.column_config.ImageColumn("", width=20),
        "team_logo": st.column_config.ImageColumn("", width=32),
        "opponent_logo": st.column_config.ImageColumn("", width=32),
        "away_logo": st.column_config.ImageColumn("", width=32),
        "home_logo": st.column_config.ImageColumn("", width=32),
        "pitcher_team_logo": st.column_config.ImageColumn("", width=32),
        "game": st.column_config.TextColumn("Game", width=190),
        "away_team": st.column_config.TextColumn("Away Team", width=145),
        "home_team": st.column_config.TextColumn("Home Team", width=145),
        "team": st.column_config.TextColumn("Team", width=125),
        "pitcher_team": st.column_config.TextColumn("Team", width=125),
        "opponent": st.column_config.TextColumn("Opponent", width=125),
        "opponent_team": st.column_config.TextColumn("Opponent", width=125),
        "away_probable_pitcher": st.column_config.TextColumn("Away Pitcher", width=145),
        "home_probable_pitcher": st.column_config.TextColumn("Home Pitcher", width=145),
        "away_pitcher_hand": st.column_config.TextColumn("Hand", width=60),
        "home_pitcher_hand": st.column_config.TextColumn("Hand", width=60),
        "batter": st.column_config.TextColumn(
            "Batter",
            width=135,
            help="Click a batter name cell to open the career game log.",
            pinned=True,
        ),
        "pitcher": st.column_config.TextColumn(
            "Pitcher",
            width=135,
            help="Click a pitcher name cell to open the opponent game log.",
            pinned=True,
        ),
        "opposing_pitcher": st.column_config.TextColumn("Pitcher", width=125),
        "pitcher_hand": st.column_config.TextColumn("Hand", width=60),
        "opposing_pitcher_hand": st.column_config.TextColumn("Hand", width=60),
        "split": st.column_config.TextColumn("Split", width=75),
        "home_away": st.column_config.TextColumn("H/A", width=60),
        "game_date": st.column_config.TextColumn("Date", width=95),
        "matchup_grade": st.column_config.TextColumn("Grade", width=115),
        "k_matchup_grade": st.column_config.TextColumn("Grade", width=115),
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
        "Season IP": st.column_config.NumberColumn("Season IP", width=85, format="%.1f"),
        "GS": st.column_config.NumberColumn("GS", width=55, format="%d"),
        "ERA": st.column_config.NumberColumn("ERA", width=65, format="%.2f"),
        "WHIP": st.column_config.NumberColumn("WHIP", width=70, format="%.2f"),
        "K/9": st.column_config.NumberColumn("K/9", width=65, format="%.2f"),
        "SwStr%": st.column_config.NumberColumn("SwStr%", width=75, format="%.2f"),
        "opponent_avg_k%": st.column_config.NumberColumn("Opp K%", width=80, format="%.2f"),
        "base_k_matchup_score": st.column_config.NumberColumn(
            "Base K Score",
            width=95,
            format="%.2f",
        ),
        "k_matchup_score": st.column_config.NumberColumn("K Score", width=80, format="%.2f"),
        "venue_name": st.column_config.TextColumn("Ballpark", width=145),
        "roof_type": st.column_config.TextColumn("Roof", width=90),
        "weather_condition": st.column_config.TextColumn("Weather", width=95),
        "weather_display": st.column_config.TextColumn(
            "Temp",
            width=65,
            help=(
                "Projected game-time temperature. Hover the weather icon in "
                "the schedule for the full forecast."
            ),
        ),
        "temperature_f": st.column_config.NumberColumn(
            "Temp F",
            width=70,
            format="%.0f",
        ),
        "humidity_pct": st.column_config.NumberColumn(
            "Humidity",
            width=80,
            format="%.0f%%",
        ),
        "precip_probability_pct": st.column_config.NumberColumn(
            "Rain",
            width=65,
            format="%.0f%%",
        ),
        "wind_speed_mph": st.column_config.NumberColumn(
            "Wind mph",
            width=85,
            format="%.0f",
        ),
        "wind_direction_cardinal": st.column_config.TextColumn(
            "Wind Dir",
            width=75,
        ),
        "wind_field_direction": st.column_config.TextColumn(
            "Field Wind",
            width=95,
        ),
        "wind_out_mph": st.column_config.NumberColumn(
            "Out mph",
            width=75,
            format="%+.1f",
        ),
        "wind_display": st.column_config.TextColumn(
            "Wind",
            width=75,
            help=(
                "Field-relative arrow and speed in mph: up = blowing out to "
                "center, down = blowing in, left/right = crosswind."
            ),
        ),
        "weather_edge": st.column_config.TextColumn(
            "Weather Edge",
            width=145,
            help=(
                "The bounded matchup effect from field-relative wind and air "
                "density. Retractable-roof games remain neutral."
            ),
        ),
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
        "ER": st.column_config.NumberColumn("ER", width=50, format="%d"),
    }


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
    "opposing_pitcher": "Pitcher",
    "opposing_pitcher_hand": "Hand",
    "pitcher_hand": "Hand",
    "Season IP": "Season IP",
    "Projected IP": "Proj IP",
    "Projected Pitch Count": "Proj PC",
    "Projected Ks": "Proj K",
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
    "k_matchup_score",
}
ONE_DECIMAL_RESEARCH_COLUMNS = {"Season IP"}
PERCENT_RESEARCH_COLUMNS = {"humidity_pct", "precip_probability_pct"}


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
    if " @ " in game_text:
        away_team, home_team = game_text.split(" @ ", 1)
    else:
        away_team, home_team = game_text, ""
    away_logo = team_logo_url(away_team)
    home_logo = team_logo_url(home_team)
    return (
        '<span class="research-game">'
        f'<img src="{escape(away_logo, quote=True)}" '
        f'alt="{escape(away_team, quote=True)}" title="{escape(away_team, quote=True)}">'
        '<span class="research-at">@</span>'
        f'<img src="{escape(home_logo, quote=True)}" '
        f'alt="{escape(home_team, quote=True)}" title="{escape(home_team, quote=True)}">'
        "</span>"
    )


def research_log_url(row, log_type):
    if log_type == "pitcher":
        params = {
            "log_type": "pitcher",
            "pitcher_id": row.get("pitcher_id"),
            "pitcher": row.get("pitcher"),
            "opponent": row.get("opponent"),
        }
    else:
        params = {
            "log_type": "bvp",
            "batter_id": row.get("batter_id"),
            "pitcher_id": row.get("opposing_pitcher_id"),
            "batter": row.get("batter"),
            "pitcher": row.get("opposing_pitcher"),
        }
    clean_params = {}
    for key, value in params.items():
        if is_missing_value(value):
            continue
        if key.endswith("_id"):
            numeric_value = pd.to_numeric(value, errors="coerce")
            if pd.notna(numeric_value):
                value = int(numeric_value)
        clean_params[key] = value
    return "?" + urlencode(clean_params) + "#matchup-log"


def research_edge_class(value):
    edge = str(value or "").lower()
    if "hitter boost" in edge:
        return "hitter"
    if "pitcher boost" in edge:
        return "pitcher"
    return "neutral"


def render_research_table(df, columns, player_column, log_type, table_key):
    header_cells = [
        '<th class="sticky-game"></th>',
        f'<th class="sticky-player">{escape(player_column.title())}</th>',
    ]
    data_columns = [
        column
        for column in columns
        if column not in {"game", player_column}
    ]
    for column in data_columns:
        label = RESEARCH_COLUMN_LABELS.get(column, column)
        width = RESEARCH_COLUMN_WIDTHS.get(column, 62)
        align_class = " align-left" if column in {
            "opposing_pitcher",
            "opponent",
            "split",
            "weather_condition",
            "wind_direction_cardinal",
            "wind_field_direction",
            "weather_edge",
            "matchup_grade",
            "k_matchup_grade",
        } else ""
        header_cells.append(
            f'<th class="{align_class.strip()}" '
            f'style="min-width:{width}px">{escape(label)}</th>'
        )

    body_rows = []
    for _, row in df.iterrows():
        player_name = str(row.get(player_column) or "Unknown")
        player_url = research_log_url(row, log_type)
        cells = [
            f'<td class="sticky-game">{research_game_html(row.get("game"))}</td>',
            '<td class="sticky-player">'
            f'<a class="research-player-link" href="{escape(player_url, quote=True)}">'
            f"{escape(player_name)}</a></td>",
        ]
        for column in data_columns:
            value = row.get(column)
            align_class = "align-left" if column in {
                "opposing_pitcher",
                "opponent",
                "split",
                "weather_condition",
                "wind_direction_cardinal",
                "wind_field_direction",
                "weather_edge",
                "matchup_grade",
                "k_matchup_grade",
            } else ""
            if column == "weather_condition":
                icon = weather_icon_svg(row.get("weather_icon"), size=17)
                content = (
                    '<span class="research-weather">'
                    f"{icon}<span>{escape(research_cell_value(column, value))}</span>"
                    "</span>"
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
            cells.append(f'<td class="{align_class}">{content}</td>')
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    st.html(
        f"""
        <div class="research-table-shell" id="{escape(table_key, quote=True)}">
            <table class="research-table">
                <thead><tr>{''.join(header_cells)}</tr></thead>
                <tbody>{''.join(body_rows)}</tbody>
            </table>
        </div>
        """
    )


def selected_log_from_query():
    log_type = st.query_params.get("log_type")
    if log_type == "bvp":
        return {
            "log_type": "bvp",
            "batter_id": st.query_params.get("batter_id"),
            "opposing_pitcher_id": st.query_params.get("pitcher_id"),
            "batter": st.query_params.get("batter"),
            "opposing_pitcher": st.query_params.get("pitcher"),
        }
    if log_type == "pitcher":
        return {
            "log_type": "pitcher",
            "pitcher_id": st.query_params.get("pitcher_id"),
            "pitcher": st.query_params.get("pitcher"),
            "opponent": st.query_params.get("opponent"),
        }
    return None


def display_bvp_game_log(selected_row):
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

    force_refresh = st.button("Refresh Live Context")


@st.cache_data(show_spinner=True, ttl=900)
def load_schedule(game_date, refresh_count):
    return get_daily_schedule(str(game_date))


@st.cache_data(show_spinner=True, ttl=900)
def load_weather(schedule, refresh_count, cache_version):
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

schedule_df = load_weather(schedule_df, live_refresh_count, cache_version=3)
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

game_filter_col, row_filter_col, _ = st.columns([2.2, 1.5, 2.3])
with game_filter_col:
    selected_game = st.selectbox(
        "Game",
        game_options,
        index=0,
    )
with row_filter_col:
    matchup_rows = st.selectbox(
        "Rows per chart",
        [10, 20, 30, 50, "All matchups"],
        index=2,
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
            with st.popover("Filters"):
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

            available_bvp_rows = len(display_bvp)
            display_bvp = apply_matchup_row_limit(display_bvp, matchup_rows)
            display_bvp = display_bvp.reset_index(drop=True)

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
            bvp_cols = [column for column in bvp_cols if column in display_bvp.columns]

            st.html(
                f'<div class="research-table-note">Showing {len(display_bvp):,} '
                f'of {available_bvp_rows:,} matchups. Click a batter name '
                "to open the career game log.</div>"
            )
            render_research_table(
                display_bvp,
                bvp_cols,
                player_column="batter",
                log_type="bvp",
                table_key="bvp-research-table",
            )

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
            with st.popover("Filters"):
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

            available_hand_rows = len(display_hand)
            display_hand = apply_matchup_row_limit(display_hand, matchup_rows)
            display_hand = display_hand.reset_index(drop=True)

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
                column for column in hand_cols if column in display_hand.columns
            ]

            st.html(
                f'<div class="research-table-note">Showing {len(display_hand):,} '
                f'of {available_hand_rows:,} matchups. Click a batter name '
                "to open the game log against today's probable pitcher.</div>"
            )
            render_research_table(
                display_hand,
                hand_cols,
                player_column="batter",
                log_type="bvp",
                table_key="hand-research-table",
            )

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

            available_pitcher_rows = len(filtered_pitcher_k_matchups)
            display_k = apply_matchup_row_limit(
                filtered_pitcher_k_matchups,
                matchup_rows,
            )
            display_k = display_k.reset_index(drop=True)

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
            k_cols = [column for column in k_cols if column in display_k.columns]

            st.html(
                f'<div class="research-table-note">Showing {len(display_k):,} '
                f'of {available_pitcher_rows:,} matchups. Click a pitcher name '
                "to open the career opponent game log.</div>"
            )
            render_research_table(
                display_k,
                k_cols,
                player_column="pitcher",
                log_type="pitcher",
                table_key="pitcher-research-table",
            )

    selected_log = selected_log_from_query()
    if selected_log is not None:
        st.html(
            '<div class="matchup-log-shell" id="matchup-log">'
            '<a class="research-player-link" href="?">Close game log</a>'
            "</div>"
        )
        if selected_log["log_type"] == "pitcher":
            display_pitcher_vs_team_game_log(selected_log)
        else:
            display_bvp_game_log(selected_log)


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
