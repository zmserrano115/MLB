from pathlib import Path


def test_research_table_component_supports_in_place_interactions():
    component_path = (
        Path(__file__).parents[1]
        / "components"
        / "research_table"
        / "index.html"
    )
    source = component_path.read_text(encoding="utf-8")

    assert "streamlit:componentReady" in source
    assert "streamlit:setComponentValue" in source
    assert "research-sort-button" in source
    assert "applySort(columnIndex, direction)" in source
    assert "research-log-opponent" in source
    assert "research-injury-badge" in source
    assert "data-tooltip" in source
    assert "game-log-table-shell" in source
    assert "Math.min(502, requestedHeight)" in source
    assert "window.location" not in source
