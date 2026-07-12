from html import escape

import pandas as pd

from all_rise.domain import recent_form as _domain_recent_form


def recent_game_values(game_log_df, value_column, limit=5):
    if game_log_df is None or game_log_df.empty or value_column not in game_log_df:
        return []

    columns = ["game_date", value_column]
    if "home_away" in game_log_df.columns:
        columns.append("home_away")
    recent = game_log_df[columns].copy()
    recent["parsed_date"] = pd.to_datetime(recent["game_date"], errors="coerce")
    recent["value"] = pd.to_numeric(recent[value_column], errors="coerce").fillna(0)
    recent = recent.sort_values("parsed_date", ascending=False).head(limit)
    recent = recent.sort_values("parsed_date")

    values = []
    for _, row in recent.iterrows():
        parsed_date = row["parsed_date"]
        label = (
            f"{parsed_date.month}/{parsed_date.day}"
            if pd.notna(parsed_date)
            else str(row["game_date"])
        )
        home_away = str(row.get("home_away") or "").strip().lower()
        if home_away in {"home", "away"}:
            label = f"{label} ({home_away[0].upper()})"
        values.append(
            {
                "date": label,
                "value": float(row["value"]),
            }
        )
    return values


def build_recent_bar_chart_html(
    game_log_df,
    value_column,
    title,
    subtitle,
    scale_floor,
    accent="#245f96",
):
    values = recent_game_values(game_log_df, value_column)
    if not values:
        return ""

    scale_max = max(float(scale_floor), max(item["value"] for item in values), 1.0)
    bars = []
    for item in values:
        value = item["value"]
        height = 4 if value <= 0 else max(10, round((value / scale_max) * 100))
        display_value = f"{value:.0f}" if value.is_integer() else f"{value:.1f}"
        aria_label = escape(
            f"{item['date']}: {display_value} {value_column}",
            quote=True,
        )
        bars.append(
            '<div class="recent-bar-item" '
            f'aria-label="{aria_label}">'
            f'<div class="recent-bar-value">{display_value}</div>'
            '<div class="recent-bar-track">'
            f'<div class="recent-bar-fill" style="height:{height}%"></div>'
            "</div>"
            f'<div class="recent-bar-date">{escape(item["date"])}</div>'
            "</div>"
        )

    return f"""
    <style>
      .recent-form-card {{
        margin: 10px 0 4px;
        padding: 12px 14px 10px;
        border: 1px solid #d6dde6;
        border-radius: 8px;
        background: #fff;
        color: #111827;
        font-family: "Source Sans 3", "Source Sans Pro", sans-serif;
      }}
      .recent-form-heading {{
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 8px;
      }}
      .recent-form-title {{
        font-size: 13px;
        font-weight: 750;
      }}
      .recent-form-subtitle {{
        color: #647184;
        font-size: 11px;
      }}
      .recent-bar-grid {{
        display: grid;
        grid-template-columns: repeat(5, minmax(38px, 1fr));
        align-items: end;
        gap: clamp(8px, 2.5vw, 18px);
        height: 92px;
      }}
      .recent-bar-item {{
        display: grid;
        grid-template-rows: 18px 56px 16px;
        align-items: end;
        min-width: 0;
        text-align: center;
      }}
      .recent-bar-value {{
        color: #31445b;
        font-size: 11px;
        font-weight: 700;
      }}
      .recent-bar-track {{
        position: relative;
        height: 56px;
        border-radius: 4px 4px 2px 2px;
        background: #f2f5f8;
        overflow: hidden;
      }}
      .recent-bar-fill {{
        position: absolute;
        right: 0;
        bottom: 0;
        left: 0;
        min-height: 3px;
        border-radius: 4px 4px 2px 2px;
        background: {escape(accent, quote=True)};
      }}
      .recent-bar-date {{
        color: #647184;
        font-size: 10px;
        line-height: 1.2;
      }}
      @media (max-width: 680px) {{
        .recent-form-card {{
          padding: 10px 11px 8px;
        }}
        .recent-form-heading {{
          align-items: flex-start;
          flex-direction: column;
          gap: 1px;
          margin-bottom: 6px;
        }}
        .recent-bar-grid {{
          gap: 7px;
          height: 86px;
        }}
      }}
    </style>
    <div class="recent-form-card">
      <div class="recent-form-heading">
        <div class="recent-form-title">{escape(title)}</div>
        <div class="recent-form-subtitle">{escape(subtitle)}</div>
      </div>
      <div class="recent-bar-grid" role="img"
           aria-label="{escape(title, quote=True)}">
        {''.join(bars)}
      </div>
    </div>
    """


recent_game_values = _domain_recent_form.recent_game_values
