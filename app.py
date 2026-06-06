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
    .stApp {
        background: #080d16;
        color: #f8fafc;
    }

    .block-container {
        padding-top: 1.4rem;
        padding-bottom: 2.5rem;
        max-width: 1280px;
    }

    h1, h2, h3 {
        letter-spacing: -0.03em;
    }

    p {
        color: #cbd5e1;
    }

    .top-bar {
        border-bottom: 1px solid rgba(148, 163, 184, 0.18);
        padding-bottom: 18px;
        margin-bottom: 22px;
    }

    .brand-title {
        font-size: 34px;
        font-weight: 750;
        color: #f8fafc;
        margin-bottom: 2px;
        letter-spacing: -0.04em;
    }

    .brand-subtitle {
        font-size: 15px;
        color: #94a3b8;
        max-width: 850px;
        line-height: 1.55;
    }

    .section-card {
        background: rgba(15, 23, 42, 0.62);
        border: 1px solid rgba(148, 163, 184, 0.16);
        border-radius: 16px;
        padding: 20px 22px;
        margin-bottom: 18px;
    }

    .small-card {
        background: rgba(15, 23, 42, 0.50);
        border: 1px solid rgba(148, 163, 184, 0.14);
        border-radius: 14px;
        padding: 16px 18px;
        min-height: 112px;
    }

    .card-label {
        color: #94a3b8;
        font-size: 13px;
        font-weight: 650;
        letter-spacing: 0.02em;
        margin-bottom: 8px;
    }

    .card-value {
        color: #f8fafc;
        font-size: 30px;
        font-weight: 760;
        line-height: 1.1;
    }

    .card-note {
        color: #94a3b8;
        font-size: 13px;
        margin-top: 6px;
    }

    .home-title {
        font-size: 24px;
        font-weight: 720;
        color: #f8fafc;
        margin-bottom: 10px;
    }

    .home-copy {
        font-size: 15px;
        color: #cbd5e1;
        line-height: 1.6;
    }

    .pill-row {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        margin-top: 14px;
    }

    .pill {
        border: 1px solid rgba(148, 163, 184, 0.18);
        color: #cbd5e1;
        background: rgba(2, 6, 23, 0.28);
        border-radius: 999px;
        padding: 7px 11px;
        font-size: 13px;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
        background: transparent;
        border-bottom: 1px solid rgba(148, 163, 184, 0.16);
        padding-bottom: 0px;
    }

    .stTabs [data-baseweb="tab"] {
        height: 44px;
        white-space: nowrap;
        border-radius: 10px 10px 0px 0px;
        padding-left: 18px;
        padding-right: 18px;
        background: transparent;
        color: #94a3b8;
        border: 1px solid transparent;
    }

    .stTabs [aria-selected="true"] {
        background: rgba(15, 23, 42, 0.72) !important;
        color: #f8fafc !important;
        border: 1px solid rgba(148, 163, 184, 0.16) !important;
        border-bottom: 1px solid rgba(15, 23, 42, 0.72) !important;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid rgba(148, 163, 184, 0.16);
        border-radius: 14px;
        overflow: hidden;
        background: rgba(15, 23, 42, 0.42);
    }

    div[data-testid="stSidebar"] {
        background: #0b1220;
        border-right: 1px solid rgba(148, 163, 184, 0.14);
    }

    .stButton > button {
        border-radius: 10px;
        border: 1px solid rgba(148, 163, 184, 0.22);
        background: rgba(15, 23, 42, 0.85);
        color: #f8fafc;
    }

    .stButton > button:hover {
        border-color: rgba(203, 213, 225, 0.40);
        color: white;
    }

    .status-box {
        background: rgba(15, 23, 42, 0.52);
        border: 1px solid rgba(148, 163, 184, 0.14);
        border-radius: 14px;
        padding: 14px 16px;
        margin-top: 16px;
        margin-bottom: 12px;
        color: #cbd5e1;
        font-size: 14px;
        line-height: 1.6;
    }

    .disclaimer-box {
        background: rgba(15, 23, 42, 0.48);
        border: 1px solid rgba(148, 163, 184, 0.14);
        border-radius: 14px;
        padding: 14px 16px;
        margin-top: 18px;
        color: #cbd5e1;
        font-size: 14px;
        line-height: 1.55;
    }
    </style>
    """,
    unsafe_allow_html=True
)


st.markdown(
    """
    <div class="top-bar">
        <div class="brand-title">All Rise Analytics</div>
        <div class="brand-subtitle">
            MLB matchup research dashboard for hitter history, handedness splits,
            and pitcher strikeout context.
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
        "color: #111827; "
        "font-weight: 650; "
        "border-bottom: 1px solid rgba(15,23,42,0.10); "
        "font-size: 14px;"
    )

    if "elite" in grade_lower or "strong" in grade_lower:
        style = "background-color: #bbf7d0; border-left: 5px solid #16a34a; " + base_style
    elif "good" in grade_lower:
        style = "background-color: #dcfce7; border-left: 5px solid #22c55e; " + base_style
    elif "avoid" in grade_lower:
        style = "background-color: #fecaca; border-left: 5px solid #dc2626; " + base_style
    elif "neutral" in grade_lower:
        style = "background-color: #fef3c7; border-left: 5px solid #ca8a04; " + base_style
    elif "small sample" in grade_lower:
        style = "background-color: #dbeafe; border-left: 5px solid #2563eb; " + base_style
    elif "no history" in grade_lower:
        style = "background-color: #e5e7eb; border-left: 5px solid #6b7280; " + base_style
    else:
        style = (
            "background-color: rgba(15, 23, 42, 0.86); "
            "color: #e5e7eb; "
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
                    ("background-color", "#111827"),
                    ("color", "#e5e7eb"),
                    ("font-weight", "700"),
                    ("font-size", "13px"),
                    ("border-bottom", "1px solid rgba(148,163,184,0.22)"),
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

    if pitcher_id is None or pd.isna(pitcher_id):
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
    "Select Game",
    game_options,
    index=0,
    help="Choose a specific game to focus the matchup tables."
)

filtered_schedule_df = filter_by_game(schedule_df, selected_game)
filtered_bvp_matchups = filter_by_game(bvp_matchups, selected_game)
filtered_hand_matchups = filter_by_game(hand_matchups, selected_game)
filtered_pitcher_k_matchups = filter_by_game(pitcher_k_matchups, selected_game)


main_tab, matchup_tab, info_tab = st.tabs([
    "Home",
    "Matchups",
    "Methodology & Status"
])


with main_tab:
    st.markdown(
        """
        <div class="section-card">
            <div class="home-title">Daily MLB matchup board</div>
            <div class="home-copy">
                This dashboard organizes current MLB games into practical matchup views:
                hitter history against probable pitchers, batter splits by pitcher hand,
                and pitcher strikeout opportunities against opposing lineups.
            </div>
            <div class="pill-row">
                <span class="pill">Batter vs Pitcher</span>
                <span class="pill">Handedness Splits</span>
                <span class="pill">Strikeout Targets</span>
                <span class="pill">Career Game Logs</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    metric_col1, metric_col2, metric_col3 = st.columns(3)

    with metric_col1:
        st.markdown(
            f"""
            <div class="small-card">
                <div class="card-label">Games on Slate</div>
                <div class="card-value">{len(schedule_df)}</div>
                <div class="card-note">Current schedule board</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with metric_col2:
        st.markdown(
            f"""
            <div class="small-card">
                <div class="card-label">BvP Rows</div>
                <div class="card-value">{len(filtered_bvp_matchups)}</div>
                <div class="card-note">Based on selected game filter</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with metric_col3:
        st.markdown(
            f"""
            <div class="small-card">
                <div class="card-label">Strikeout Rows</div>
                <div class="card-value">{len(filtered_pitcher_k_matchups)}</div>
                <div class="card-note">Probable pitcher K board</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.subheader("Today's Games")

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

    st.info("Open the Matchups tab to view hitter tables, strikeout targets, and clickable game logs.")


with matchup_tab:
    st.subheader("Matchup Tables")

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
        st.markdown("Direct hitter history against today's opposing probable pitcher.")

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
            "Hitter splits against the same throwing hand as today's opposing probable pitcher."
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
            "Pitcher strikeout opportunities using projected workload and opposing hitter K tendencies."
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
    st.subheader("How the matchup tables work")

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