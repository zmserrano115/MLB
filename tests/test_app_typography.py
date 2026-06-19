from pathlib import Path


def test_app_limits_display_font_to_titles_tabs_and_filters():
    source = Path("app.py").read_text(encoding="utf-8")

    assert "family=Bebas+Neue&family=Manrope" in source
    assert '--font-body: "Manrope", "Segoe UI", Helvetica, sans-serif;' in source
    assert '--font-display: "Bebas Neue", "Arial Narrow", sans-serif;' in source
    assert ".section-title {" in source
    assert '[data-testid="stSelectbox"] [data-baseweb="select"] *' in source
    assert "h1, h2, h3, h4, h5, h6 {" in source
