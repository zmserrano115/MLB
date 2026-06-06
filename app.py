# app.py

from datetime import date
from pathlib import Path
import json

import pandas as pd
import streamlit as st
from pandas.errors import EmptyDataError

from src.mlb_schedule import get_daily_schedule
from src.stat_data import (
    get_batter_stats,
    get_pitcher_stats,
    get_batter_vs_pitcher_game_log,
    get_pitcher_vs_team_game_log
)
from src.matchups import (
    build_batter_vs_pitcher_matchups,
    build_batter_vs_hand_matchups,
    build_pitcher_k_matchups
)


st.set_page_config(
    page_title="All Rise Analytics",
    layout="wide"
)


PRECOMPUTED_DIR = Path("data") / "precomputed"


st.markdown(
    """
    <style>
    :root {
        --bg: #04152b;
        --panel: #071d36;
        --panel-soft: #0a213d;
        --panel-light: #102a4a;
        --text: #ffffff;
        --muted: #b8c7d8;
        --muted-2: #8ea1b7;
        --line: rgba(255, 255, 255, 0.09);
        --line-soft: rgba(255, 255, 255, 0.06);
        --accent: #1d6ed0;
        --accent-soft: #17365c;
    }

    .stApp {
        background: var(--bg);
        color: var(--text);
    }

    .block-container {
        padding-top: 1.1rem;
        padding-bottom: 2.5rem;
        max-width: 1280px;
    }

    h1, h2, h3 {
        letter-spacing: -0.03em;
    }

    p, li {
        color: var(--muted);
    }

    .top-nav {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 6px 0 18px 0;
        border-bottom: 1px solid var(--line);
        margin-bottom: 24px;
    }

    .brand-wrap {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .brand-name {
        font-size: 28px;
        font-weight: 760;
        color: #ffffff;
        letter-spacing: -0.04em;
    }

    .brand-line {
        font-size: 14px;
        color: var(--muted-2);
    }

    .nav-badge {
        background: var(--accent-soft);
        color: #ffffff;
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 999px;
        padding: 7px 12px;
        font-size: 13px;
        font-weight: 650;
    }

    .hero {
        background: linear-gradient(180deg, #08213f 0%, #071d36 100%);
        border: 1px solid var(--line);
        border-radius: 18px;
        padding: 30px 32px;
        margin-bottom: 22px;
    }

    .hero-kicker {
        color: #d7e7fb;
        font-size: 13px;
        font-weight: 700;
        margin-bottom: 12px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }

    .hero-title {
        color: #ffffff;
        font-size: 44px;
        line-height: 1.04;
        font-weight: 780;
        letter-spacing: -0.05em;
        margin-bottom: 12px;
        max-width: 880px;
    }

    .hero-copy {
        color: #d5dfeb;
        font-size: 16px;
        line-height: 1.65;
        max-width: 900px;
    }

    .pill-row {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        margin-top: 20px;
    }

    .pill {
        background: #17365c;
        color: #f4f8fc;
        border: 1px solid rgba(255,255,255,0.09);
        border-radius: 999px;
        padding: 8px 12px;
        font-size: 13px;
        font-weight: 600;
    }

    .content-card {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 18px 20px;
        margin-bottom: 18px;
    }

    .content-card-soft {
        background: rgba(7, 29, 54, 0.72);
        border: 1px solid var(--line-soft);
        border-radius: 16px;
        padding: 18px 20px;
        margin-bottom: 18px;
    }

    .metric-card {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 18px 20px;
        min-height: 112px;
    }

    .metric-label {
        color: var(--muted-2);
        font-size: 13px;
        font-weight: 700;
        margin-bottom: 8px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .metric-value {
        color: #ffffff;
        font-size: 32px;
        font-weight: 780;
        line-height: 1.05;
    }

    .metric-note {
        color: var(--muted);
        font-size: 13px;
        margin-top: 8px;
    }

    .section-label {
        color: var(--muted-2);
        font-size: 13px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        margin-bottom: 8px;
    }

    .section-title {
        color: #ffffff;
        font-size: 25px;
        line-height: 1.15;
        font-weight: 760;
        letter-spacing: -0.04em;
        margin-bottom: 8px;
    }

    .section-copy {
        color: var(--muted);
        font-size: 15px;
        line-height: 1.6;
        max-width: 900px;
    }

    .selected-game-box {
        background: #08213f;
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 16px 18px;
        margin-bottom: 18px;
    }

    .selected-game-label {
        color: var(--muted-2);
        font-size: 13px;
        text-transform: uppercase;
        font-weight: 700;
        letter-spacing: 0.07em;
        margin-bottom: 4px;
    }

    .selected-game-value {
        color: #ffffff;
        font-size: 20px;
        font-weight: 730;
        letter-spacing: -0.02em;
    }

    .status-box {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 16px 18px;
        margin-top: 12px;
        margin-bottom: 16px;
        color: var(--muted);
        font-size: 14px;
        line-height: 1.65;
    }

    .disclaimer-box {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 16px 18px;
        margin-top: 16px;
        color: var(--muted);
        font-size: 14px;
        line-height: 1.6;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        border-bottom: 1px solid var(--line);
        padding-bottom: 4px;
    }

    .stTabs [data-baseweb="tab"] {
        height: 42px;
        border-radius: 10px 10px 0 0;
        padding-left: 18px;
        padding-right: 18px;
        color: var(--muted-2);
        background: transparent;
        font-weight: 650;
    }

    .stTabs [aria-selected="true"] {
        color: #ffffff !important;
        background: var(--panel) !important;
        border: 1px solid var(--line) !important;
        border-bottom: 1px solid var(--panel) !important;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid var(--line);
        border-radius: 14px;
        overflow: hidden;
        background: var(--panel);
    }

    .stButton > button {
        border-radius: 10px;
        border: 1px solid rgba(255,255,255,0.10);
        background: var(--accent-soft);
        color: #ffffff;
        font-weight: 650;
    }

    .stButton > button:hover {
        border-color: rgba(255,255,255,0.20);
        background: #1d4473;
        color: #ffffff;
    }

    div[data-testid="stSidebar"] {
        background: #071a31;
        border-right: 1px solid var(--line-soft);
    }

    div[data-testid="stSidebar"] h1,
    div[data-testid="stSidebar"] h2,
    div[data-testid="stSidebar"] h3 {
        color: #ffffff;
    }

    .block-spacer {
        height: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True
)


st.markdown(
    """
    <div class="top-nav">
        <div class="brand-wrap">
            <div class="brand-name">All Rise Analytics</div>
            <div class="brand-line">MLB matchup research dashboard</div>
        </div>
        <div class="nav-badge">Daily Matchup Board</div>
    </div>
    """,
    unsafe_allow_html=True
)


def read_precomputed_csv(file_name):
    file_path = PRECOMPUTED_DIR / file_name

    if not file_path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(file_path)
    except EmptyDataError:
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def read_precomputed_metadata():
    file_path = PRECOMPUTED_DIR / "latest_metadata.json"

    if not file_path.exists():
        return {}

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def precomputed_files_available():
    required_files = [
        PRECOMPUTED_DIR / "latest_schedule.csv",
        PRECOMPUTED_DIR / "latest_batter_vs_pitcher.csv",
        PRECOMPUTED_DIR / "latest_batter_vs_hand.csv",
        PRECOMPUTED_DIR / "latest_pitcher_k_matchups.csv"
    ]

    return all(file.exists() for file in required_files)


def load_precomputed_data():
    schedule_df = read_precomputed_csv("latest_schedule.csv")
    bvp_matchups = read_precomputed_csv("latest_batter_vs_pitcher.csv")
    hand_matchups = read_precomputed_csv("latest_batter_vs_hand.csv")
    pitcher_k_matchups = read_precomputed_csv("latest_pitcher_k_matchups.csv")
    metadata = read_precomputed_metadata()

    return schedule_df, bvp_matchups, hand_matchups, pitcher_k_matchups, metadata


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


def row_color_by_grade(row):
    grade = ""

    if "matchup_grade" in row:
        grade = str(row["matchup_grade"])
    elif "k_matchup_grade" in row:
        grade = str(row["k_matchup_grade"])

    grade_lower = grade.lower()

    base_style = (
        "color: #111827; "
        "font-weight: 650; "
        "border-bottom: 1px solid rgba(0,0,0,0.08); "
        "font-size: 14px;"
    )

    if "elite" in grade_lower or "strong" in grade_lower:
        style = "background-color: #cfead9; border-left: 5px solid #16834a; " + base_style
    elif "good" in grade_lower:
        style = "background-color: #e1f3e8; border-left: 5px solid #279a5c; " + base_style
    elif "avoid" in grade_lower:
        style = "background-color: #f2c7c7; border-left: 5px solid #c63f3f; " + base_style
    elif "neutral" in grade_lower:
        style = "background-color: #f1e3b5; border-left: 5px solid #b98b13; " + base_style
    elif "small sample" in grade_lower:
        style = "background-color: #d8e6f7; border-left: 5px solid #3d73bd; " + base_style
    elif "no history" in grade_lower:
        style = "background-color: #e5e7eb; border-left: 5px solid #6b7280; " + base_style
    else:
        style = (
            "background-color: #0a213d; "
            "color: #f8fafc; "
            "border-bottom: 1px solid rgba(255,255,255,0.05); "
            "font-size: 14px;"
        )

    return [style] * len(row)


def style_matchup_table(df):
    if df.empty:
        return df

    format_dict = {}

    for col in ["AVG", "OBP", "SLG", "OPS"]:
        if col in df.columns:
            format_dict[col] = "{:.3f}"

    for col in [
        "K%",
        "BB%",
        "opponent_avg_k%",
        "k_matchup_score",
        "Season IP",
        "Projected IP",
        "Projected Pitch Count",
        "Projected Ks",
        "Pitch Count"
    ]:
        if col in df.columns:
            format_dict[col] = "{:.2f}"

    for col in ["ERA", "WHIP", "K/9"]:
        if col in df.columns:
            format_dict[col] = "{:.2f}"

    styler = df.style.apply(row_color_by_grade, axis=1).format(format_dict, na_rep="")

    styler = styler.set_table_styles(
        [
            {
                "selector": "th",
                "props": [
                    ("background-color", "#102a4a"),
                    ("color", "#f8fafc"),
                    ("font-weight", "700"),
                    ("font-size", "13px"),
                    ("border-bottom", "1px solid rgba(255,255,255,0.08)"),
                    ("padding", "10px 12px")
                ]
            },
            {
                "selector": "td",
                "props": [
                    ("padding", "9px 12px"),
                    ("white-space", "nowrap")
                ]
            }
        ]
    )

    return styler


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
            int(season)
        )

    if game_log_df.empty:
        st.warning("No individual career game-log history was found for this matchup.")
        return

    game_log_cols = [
        "game_date",
        "home_away",
        "team",
        "opponent",
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
        "BB%"
    ]

    game_log_cols = [col for col in game_log_cols if col in game_log_df.columns]

    st.dataframe(
        style_matchup_table(game_log_df[game_log_cols]),
        width="stretch",
        hide_index=True
    )


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
            opponent_team=opponent_team
        )

    if game_log_df.empty:
        st.warning("No pitcher-vs-team career game-log history was found for this matchup.")
        return

    game_log_cols = [
        "game_date",
        "opponent",
        "IP",
        "Pitch Count",
        "BF",
        "H",
        "BB",
        "HBP",
        "SO",
        "HR",
        "R"
    ]

    game_log_cols = [col for col in game_log_cols if col in game_log_df.columns]

    st.dataframe(
        style_matchup_table(game_log_df[game_log_cols]),
        width="stretch",
        hide_index=True
    )


current_year = date.today().year
has_precomputed = precomputed_files_available()


with st.sidebar:
    st.header("Controls")

    use_precomputed = st.checkbox(
        "Use cloud data",
        value=has_precomputed,
        help="Uses data refreshed by GitHub Actions instead of rebuilding live."
    )

    selected_date = st.date_input("Game Date", value=date.today())

    season = st.selectbox(
        "Season",
        list(range(current_year, current_year - 26, -1))
    )

    min_pa = st.number_input(
        "Minimum PA",
        min_value=0,
        max_value=700,
        value=100,
        step=10
    )

    top_n = st.number_input(
        "Rows to Show",
        min_value=5,
        max_value=100,
        value=25,
        step=5
    )

    force_refresh = st.button("Refresh Baseball Data")


@st.cache_data(show_spinner=True)
def load_schedule(game_date):
    return get_daily_schedule(str(game_date))


@st.cache_data(show_spinner=True)
def load_batter_stats(season, force_refresh):
    return get_batter_stats(season, force_refresh=force_refresh)


@st.cache_data(show_spinner=True)
def load_pitcher_stats(season, force_refresh):
    return get_pitcher_stats(season, force_refresh=force_refresh)


cloud_status_html = ""

if use_precomputed and has_precomputed:
    schedule_df, bvp_matchups, hand_matchups, pitcher_k_matchups, metadata = load_precomputed_data()
    season = int(metadata.get("season", season))

    cloud_status_html = f"""
    <div class="status-box">
        <b>Data Mode:</b> Cloud precomputed data<br>
        <b>Last refreshed:</b> {metadata.get("last_refreshed", "Unknown")}<br>
        <b>Game date:</b> {metadata.get("game_date", "Unknown")} |
        <b>Season:</b> {metadata.get("season", "Unknown")} |
        <b>Minimum PA:</b> {metadata.get("minimum_pa", "Unknown")}
    </div>
    """

else:
    if use_precomputed and not has_precomputed:
        st.warning("Precomputed cloud data files were not found. The app will build live data instead.")

    schedule_df = load_schedule(selected_date)

    if schedule_df.empty:
        st.warning("No MLB games found for this date.")
        st.stop()

    batters_df = load_batter_stats(season, force_refresh)
    pitchers_df = load_pitcher_stats(season, force_refresh)

    cloud_status_html = """
    <div class="status-box">
        <b>Data Mode:</b> Live data build<br>
        Live mode may take longer because the app is not using precomputed cloud files.
    </div>
    """

    with st.spinner("Building batter vs pitcher matchups..."):
        bvp_matchups = build_batter_vs_pitcher_matchups(
            schedule_df=schedule_df,
            batters_df=batters_df,
            season=season,
            min_pa=min_pa
        )

    with st.spinner("Building batter vs pitcher hand matchups..."):
        hand_matchups = build_batter_vs_hand_matchups(
            schedule_df=schedule_df,
            batters_df=batters_df,
            season=season,
            min_pa=min_pa
        )

    with st.spinner("Building pitcher strikeout matchups..."):
        pitcher_k_matchups = build_pitcher_k_matchups(
            schedule_df=schedule_df,
            batters_df=batters_df,
            pitchers_df=pitchers_df,
            min_pa=min_pa
        )


if schedule_df.empty:
    st.warning("No schedule data available.")
    st.stop()


schedule_df = add_game_column(schedule_df)
game_options = get_game_options(schedule_df)

selected_game = st.sidebar.selectbox(
    "Game Filter",
    game_options,
    index=0,
    help="Choose a specific game to focus the matchup tables."
)

filtered_schedule_df = filter_by_game(schedule_df, selected_game)
filtered_bvp_matchups = filter_by_game(bvp_matchups, selected_game)
filtered_hand_matchups = filter_by_game(hand_matchups, selected_game)
filtered_pitcher_k_matchups = filter_by_game(pitcher_k_matchups, selected_game)


main_tab, matchup_tab, info_tab = st.tabs([
    "Overview",
    "Matchups",
    "Methodology & Status"
])


with main_tab:
    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">MLB Matchup Dashboard</div>
            <div class="hero-title">Smarter matchup research for the daily slate</div>
            <div class="hero-copy">
                Review current MLB games, compare hitter advantages, evaluate pitcher-hand splits,
                and identify strikeout opportunities through a cleaner daily workflow.
            </div>
            <div class="pill-row">
                <span class="pill">Batter vs Pitcher</span>
                <span class="pill">Throwing Hand Splits</span>
                <span class="pill">Strikeout Targets</span>
                <span class="pill">Career Logs</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    metric_col1, metric_col2, metric_col3 = st.columns(3)

    with metric_col1:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">Games</div>
                <div class="metric-value">{len(schedule_df)}</div>
                <div class="metric-note">Games currently listed on the slate</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with metric_col2:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">BvP Rows</div>
                <div class="metric-value">{len(filtered_bvp_matchups)}</div>
                <div class="metric-note">Direct hitter vs pitcher rows</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with metric_col3:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">K Targets</div>
                <div class="metric-value">{len(filtered_pitcher_k_matchups)}</div>
                <div class="metric-note">Pitcher strikeout matchup rows</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    selected_game_display = selected_game if selected_game != "All Games" else "Full slate"

    st.markdown(
        f"""
        <div class="selected-game-box">
            <div class="selected-game-label">Current View</div>
            <div class="selected-game-value">{selected_game_display}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <div class="content-card">
            <div class="section-label">Schedule</div>
            <div class="section-title">Today's Games</div>
            <div class="section-copy">
                Use the game filter in the sidebar to narrow the schedule and matchup tables.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    schedule_display_cols = [
        "away_team",
        "home_team",
        "away_probable_pitcher",
        "away_pitcher_hand",
        "home_probable_pitcher",
        "home_pitcher_hand"
    ]

    schedule_display_cols = [
        col for col in schedule_display_cols if col in filtered_schedule_df.columns
    ]

    st.dataframe(
        filtered_schedule_df[schedule_display_cols],
        width="stretch",
        hide_index=True
    )


with matchup_tab:
    st.markdown(
        """
        <div class="content-card">
            <div class="section-label">Analysis</div>
            <div class="section-title">Matchup Tables</div>
            <div class="section-copy">
                Explore hitter history, pitcher-hand splits, and strikeout opportunities.
                Click supported rows to open career game logs.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    batter_cols = [
        "game",
        "team",
        "batter",
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
        "matchup_grade"
    ]

    tab1, tab2, tab3 = st.tabs([
        "Hitter vs Pitcher",
        "Hitter vs Throwing Hand",
        "Strikeout Targets"
    ])

    with tab1:
        st.markdown(
            """
            <div class="content-card-soft">
                <div class="section-label">Direct History</div>
                <div class="section-title">Hitter vs Pitcher</div>
                <div class="section-copy">
                    Direct matchup history between each hitter and today's opposing probable pitcher.
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        if filtered_bvp_matchups.empty:
            st.warning("No batter vs pitcher matchup data was found for this selection.")
        else:
            available_cols = [
                col for col in batter_cols if col in filtered_bvp_matchups.columns
            ]

            min_bvp_pa = st.slider(
                "Minimum PA vs Opposing Pitcher",
                min_value=0,
                max_value=50,
                value=0,
                step=1
            )

            display_bvp = filtered_bvp_matchups[
                filtered_bvp_matchups["PA"] >= min_bvp_pa
            ].copy()

            display_bvp = display_bvp.head(int(top_n))

            st.write("Click one row below to view its career matchup game log.")

            bvp_event = st.dataframe(
                style_matchup_table(display_bvp[available_cols]),
                width="stretch",
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="bvp_table"
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
            """
            <div class="content-card-soft">
                <div class="section-label">Splits</div>
                <div class="section-title">Hitter vs Throwing Hand</div>
                <div class="section-copy">
                    Hitter performance against the same throwing hand as today's opposing probable pitcher.
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        if filtered_hand_matchups.empty:
            st.warning("No batter vs pitcher-hand split data was found for this selection.")
        else:
            available_cols = [
                col for col in batter_cols if col in filtered_hand_matchups.columns
            ]

            min_hand_pa = st.slider(
                "Minimum PA vs Pitcher Hand",
                min_value=0,
                max_value=300,
                value=20,
                step=5
            )

            min_hand_obp = st.slider(
                "Minimum OBP vs Pitcher Hand",
                min_value=0.150,
                max_value=0.500,
                value=0.320,
                step=0.005
            )

            display_hand = filtered_hand_matchups[
                (filtered_hand_matchups["PA"] >= min_hand_pa) &
                (filtered_hand_matchups["OBP"] >= min_hand_obp)
            ].copy()

            display_hand = display_hand.head(int(top_n))

            st.dataframe(
                style_matchup_table(display_hand[available_cols]),
                width="stretch",
                hide_index=True
            )

    with tab3:
        st.markdown(
            """
            <div class="content-card-soft">
                <div class="section-label">Pitching</div>
                <div class="section-title">Strikeout Targets</div>
                <div class="section-copy">
                    Pitcher strikeout opportunities using projected workload and opposing hitter strikeout tendencies.
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        if filtered_pitcher_k_matchups.empty:
            st.warning("No pitcher strikeout matchups were created for this selection.")
        else:
            required_projected_cols = [
                "Projected IP",
                "Projected Pitch Count",
                "Projected Ks"
            ]

            missing_projected_cols = [
                col for col in required_projected_cols
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
                "pitcher_team",
                "pitcher_hand",
                "opponent",
                "Projected IP",
                "Projected Pitch Count",
                "Projected Ks",
                "ERA",
                "WHIP",
                "K%",
                "K/9",
                "opponent_avg_k%",
                "k_matchup_score",
                "k_matchup_grade"
            ]

            k_cols = [
                col for col in k_cols if col in filtered_pitcher_k_matchups.columns
            ]

            display_k = filtered_pitcher_k_matchups.head(int(top_n)).copy()

            st.write("Click one pitcher row below to view his career game log against that opponent.")

            k_event = st.dataframe(
                style_matchup_table(display_k[k_cols]),
                width="stretch",
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="pitcher_k_table"
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
        <div class="content-card">
            <div class="section-label">Reference</div>
            <div class="section-title">Methodology & Status</div>
            <div class="section-copy">
                A quick explanation of how the tables should be read and the current refresh state.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        """
        **Hitter vs Pitcher**
        - Direct hitter history against today's probable pitcher.
        - Best used with sample size context.

        **Hitter vs Throwing Hand**
        - Hitter split against right-handed or left-handed pitchers.
        - Usually more reliable than direct batter-vs-pitcher history because the sample is larger.

        **Strikeout Targets**
        - Uses projected innings, projected pitch count, pitcher strikeout ability,
          and opponent hitter strikeout tendencies.
        - Click a pitcher row to view career game logs against that opponent.

        **Row Colors**
        - Green = favorable
        - Yellow = neutral
        - Red = avoid
        - Blue = small sample
        - Gray = no history
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
        unsafe_allow_html=True
    )

    st.subheader("Data Refresh Status")
    st.markdown(cloud_status_html, unsafe_allow_html=True)