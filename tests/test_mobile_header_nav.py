from pathlib import Path


def test_mobile_header_has_tab_scroll_control():
    source = (
        Path(__file__).parents[1] / "app.py"
    ).read_text(encoding="utf-8")

    assert 'key="app_header_nav_scroll"' in source
    assert 'id="header-tab-scroll"' in source
    assert "Show more navigation tabs" in source
    assert "nav.scrollBy({" in source
    assert 'nav.scrollTo({ left: 0, behavior: "smooth" });' in source
    assert "render_header_tab_scroll_control()" in source
