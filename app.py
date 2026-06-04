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
    get_batter_vs_pitcher_game_log
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
    .stApp {
        background: linear-gradient(180deg, #040816 0%, #071122 100%);
    }

    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }

    h1, h2, h3 {
        letter-spacing: 0.2px;
    }

    .hero-box {
        background: linear-gradient(135deg, rgba(12, 25, 48, 0.95), rgba(7, 15, 28, 0.90));
        border: 1px solid rgba(125, 211, 252, 0.25);
        border-radius: 18px;
        padding: 26px 30px;
        margin-bottom: 20px;
        box-shadow: 0 0 22px rgba(14, 165, 233, 0.08);
    }

    .hero-title {
        font-size: 40px;
        font-weight: 800;
        color: #f8fbff;
        margin-bottom: 4px;
        letter-spacing: 0.5px;
    }

    .hero-subtitle {
        font-size: 18px;
        color: #9bdcff;
        font-weight: 600;
        margin-bottom: 10px;
    }

    .hero-text {
        font-size: 15px;
        color: #cbd5e1;
        max-width: 900px;
        line-height: 1.5;
    }

    .metric-card {
        background: rgba(12, 20, 35, 0.78);
        border: 1px solid rgba(125, 211, 252, 0.20);
        border-radius: 15px;
        padding: 16px 18px;
        margin-bottom: 18px;
    }

    .metric-label {
        color: #9ca3af;
        font-size: 13px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.8px;
    }

    .metric-value {
        color: #f8fafc;
        font-size: 28px;
        font-weight: 800;
        margin-top: 3px;
    }

    .metric-note {
        color: #7dd3fc;
        font-size: 13px;
        margin-top: 2px;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: rgba(10, 18, 30, 0.55);
        padding: 8px;
        border-radius: 14px;
        border: 1px solid rgba(95, 170, 255, 0.16);
        backdrop-filter: blur(6px);
    }

    .stTabs [data-baseweb="tab"] {
        height: 44px;
        white-space: nowrap;
        border-radius: 10px;
        padding-left: 16px;
        padding-right: 16px;
        background: rgba(255, 255, 255, 0.05);
        color: #d8e7ff;
        border: 1px solid rgba(120, 170, 255, 0.10);
    }

    .stTabs [aria-selected="true"] {
        background: rgba(30, 50, 85, 0.90) !important;
        color: #7dd3fc !important;
        border: 1px solid rgba(125, 211, 252, 0.40) !important;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid rgba(120, 170, 255, 0.16);
        border-radius: 14px;
        overflow: hidden;
        background: rgba(8, 14, 24, 0.35);
        backdrop-filter: blur(6px);
    }

    div[data-testid="stSidebar"] {
        background: rgba(7, 15, 28, 0.96);
    }

    .stButton > button {
        border-radius: 10px;
        border: 1px solid rgba(125, 211, 252, 0.25);
        background: rgba(20, 35, 60, 0.85);
        color: #e6f1ff;
    }

    .stButton > button:hover {
        border-color: rgba(125, 211, 252, 0.50);
        color: white;
    }

    .cloud-box {
        background: rgba(12, 20, 35, 0.75);
        border: 1px solid rgba(125, 211, 252, 0.22);
        border-radius: 14px;
        padding: 14px 18px;
        margin-top: 20px;
        margin-bottom: 18px;
    }

    .disclaimer-box {
        background: rgba(15, 23, 42, 0.75);
        border: 1px solid rgba(148, 163, 184, 0.22);
        border-radius: 14px;
        padding: 15px 18px;
        margin-top: 18px;
        color: #cbd5e1;
        font-size: 14px;
        line-height: 1.5;
    }
    </style>
    """,
    unsafe_allow_html=True
)


st.markdown(
    """
    <div class="hero-box">
        <div class="hero-title">All Rise Analytics</div>
        <div class="hero-subtitle">Daily MLB Matchup Intelligence</div>
        <div class="hero-text">
            Analyze hitter-vs-pitcher history, handedness splits, and pitcher strikeout opportunities
            using current MLB matchup data. Use the filters to focus on a specific game, compare batter
            advantages, and review matchup history.
        </div>
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


def row_color_by_grade(row):
    grade = ""

    if "matchup_grade" in row:
        grade = str(row["matchup_grade"])
    elif "k_matchup_grade" in row:
        grade = str(row["k_matchup_grade"])

    grade_lower = grade.lower()

    base_style = (
        "color: #05070a; "
        "font-weight: 700; "
        "border-bottom: 1px solid rgba(0,0,0,0.12); "
        "font-size: 14px;"
    )

    if "elite" in grade_lower or "strong" in grade_lower:
        style = (
            "background-color: #86efac; "
            "border-left: 6px solid #16a34a; "
            + base_style
        )
    elif "good" in grade_lower:
        style = (
            "background-color: #bbf7d0; "
            "border-left: 6px solid #22c55e; "
            + base_style
        )
    elif "avoid" in grade_lower:
        style = (
            "background-color: #fca5a5; "
            "border-left: 6px solid #dc2626; "
            + base_style
        )
    elif "neutral" in grade_lower:
        style = (
            "background-color: #fde68a; "
            "border-left: 6px solid #ca8a04; "
            + base_style
        )
    elif "small sample" in grade_lower:
        style = (
            "background-color: #bfdbfe; "
            "border-left: 6px solid #2563eb; "
            + base_style
        )
    elif "no history" in grade_lower:
        style = (
            "background-color: #e5e7eb; "
            "border-left: 6px solid #6b7280; "
            + base_style
        )
    else:
        style = (
            "background-color: rgba(15, 23, 42, 0.85); "
            "color: #e8eef9; "
            "border-bottom: 1px solid rgba(255,255,255,0.06); "
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

    for col in ["K%", "BB%", "opponent_avg_k%", "k_matchup_score"]:
        if col in df.columns:
            format_dict[col] = "{:.2f}"

    styler = df.style.apply(row_color_by_grade, axis=1).format(format_dict, na_rep="")

    styler = styler.set_table_styles(
        [
            {
                "selector": "th",
                "props": [
                    ("background-color", "#111827"),
                    ("color", "#e5f0ff"),
                    ("font-weight", "700"),
                    ("font-size", "14px"),
                    ("border-bottom", "2px solid rgba(125,211,252,0.35)"),
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

    with st.spinner("Loading career batter-vs-pitcher game log..."):
        game_log_df = get_batter_vs_pitcher_game_log(
            int(batter_id),
            int(pitcher_id),
            int(season)
        )

    if game_log_df.empty:
        st.warning(
            "No individual career game-log history was found for this matchup."
        )
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

    game_log_cols = [
        col for col in game_log_cols if col in game_log_df.columns
    ]

    st.dataframe(
        style_matchup_table(game_log_df[game_log_cols]),
        width="stretch",
        hide_index=True
    )


current_year = date.today().year
has_precomputed = precomputed_files_available()


with st.sidebar:
    st.header("Filters")

    use_precomputed = st.checkbox(
        "Use cloud precomputed data",
        value=has_precomputed,
        help="Uses data refreshed by GitHub Actions instead of rebuilding live."
    )

    selected_date = st.date_input("Game Date", value=date.today())

    season = st.selectbox(
        "Season Data",
        list(range(current_year, current_year - 26, -1))
    )

    min_pa = st.number_input(
        "Minimum Team Season PA to Include Batter",
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
    <div class="cloud-box">
        <b>Cloud Data Mode:</b> Using precomputed GitHub Actions data.<br>
        <b>Last refreshed:</b> {metadata.get("last_refreshed", "Unknown")}<br>
        <b>Game date:</b> {metadata.get("game_date", "Unknown")} |
        <b>Season:</b> {metadata.get("season", "Unknown")} |
        <b>Minimum PA:</b> {metadata.get("minimum_pa", "Unknown")}
    </div>
    """

else:
    if use_precomputed and not has_precomputed:
        st.warning(
            "Precomputed cloud data files were not found. The app will build live data instead."
        )

    schedule_df = load_schedule(selected_date)

    if schedule_df.empty:
        st.warning("No MLB games found for this date.")
        st.stop()

    batters_df = load_batter_stats(season, force_refresh)
    pitchers_df = load_pitcher_stats(season, force_refresh)

    cloud_status_html = """
    <div class="cloud-box">
        <b>Live Data Mode:</b> Building data directly from MLB sources.<br>
        This mode may take longer because the app is not using precomputed cloud files.
    </div>
    """

    with st.spinner("Building batter vs pitcher matchups... first run may take a few minutes."):
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

st.header("Today's Games and Probable Pitchers")

game_options = get_game_options(schedule_df)

selected_game = st.selectbox(
    "Select Game",
    game_options,
    index=0,
    help="Choose a specific game to focus the matchup tables."
)

filtered_schedule_df = filter_by_game(schedule_df, selected_game)
filtered_bvp_matchups = filter_by_game(bvp_matchups, selected_game)
filtered_hand_matchups = filter_by_game(hand_matchups, selected_game)
filtered_pitcher_k_matchups = filter_by_game(pitcher_k_matchups, selected_game)


metric_col1, metric_col2, metric_col3 = st.columns(3)

with metric_col1:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">Games on Slate</div>
            <div class="metric-value">{len(schedule_df)}</div>
            <div class="metric-note">Current matchup board</div>
        </div>
        """,
        unsafe_allow_html=True
    )

with metric_col2:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">BvP Matchups</div>
            <div class="metric-value">{len(filtered_bvp_matchups)}</div>
            <div class="metric-note">Filtered to selected game</div>
        </div>
        """,
        unsafe_allow_html=True
    )

with metric_col3:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">K Matchups</div>
            <div class="metric-value">{len(filtered_pitcher_k_matchups)}</div>
            <div class="metric-note">Probable pitcher strikeout board</div>
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


st.header("Matchup Tables")


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
    st.subheader("Hitter vs Pitcher")
    st.write(
        "This section shows each hitter's direct history against today's opposing probable pitcher."
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
    st.subheader("Hitter vs Throwing Hand")
    st.write(
        "This section shows each hitter's split against the same throwing hand "
        "as today's opposing probable pitcher."
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
    st.subheader("Strikeout Targets")

    if filtered_pitcher_k_matchups.empty:
        st.warning("No pitcher strikeout matchups were created for this selection.")
    else:
        k_cols = [
            "game",
            "pitcher",
            "pitcher_team",
            "pitcher_hand",
            "opponent",
            "IP",
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

        st.dataframe(
            style_matchup_table(display_k[k_cols]),
            width="stretch",
            hide_index=True
        )


st.header("How the Matchup Tables Work")

st.markdown(
    """
    **Hitter vs Pitcher**
    - Direct hitter history against today's probable pitcher.
    - Click a row to see the career matchup game log.

    **Hitter vs Throwing Hand**
    - Hitter split against right-handed or left-handed pitchers.
    - Usually more reliable than direct batter-vs-pitcher history.

    **Strikeout Targets**
    - Uses pitcher strikeout ability and opponent hitter strikeout tendencies.

    **Row Colors**
    - Dark green = Strong or Elite
    - Light green = Good
    - Yellow = Neutral
    - Red = Avoid
    - Blue = Small Sample
    - Gray = No History
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

st.header("Data Refresh Status")
st.markdown(cloud_status_html, unsafe_allow_html=True)