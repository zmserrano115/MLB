from src.ui.bvp_research_page import _pa_strike_zone_html, _pitch_table_html


def test_strike_zone_uses_larger_plate_free_canvas():
    html = _pa_strike_zone_html([])

    assert 'viewBox="0 0 170 160"' in html
    assert 'x="35" y="15" width="100" height="125"' in html
    assert "hvp-pa-zone-plate" not in html


def test_pitch_table_removes_location_and_spin_columns():
    html = _pitch_table_html(
        [
            {
                "pitch_number": 1,
                "balls": 0,
                "strikes": 0,
                "pitch_type": "FF",
                "release_speed": 96.2,
                "pitch_description": "called_strike",
                "plate_x": 0.12,
                "plate_z": 2.84,
                "release_spin_rate": 2420,
            }
        ],
        "strikeout",
    )

    assert "<th>Location</th>" not in html
    assert "<th>Spin</th>" not in html
    assert "2420" not in html


def test_only_decisive_pitch_row_is_colored_for_hit_or_out():
    pitches = [
        {"pitch_number": 1, "pitch_type": "FF", "pitch_description": "called_strike"},
        {"pitch_number": 2, "pitch_type": "SL", "pitch_description": "in_play,_no_out"},
    ]

    hit_html = _pitch_table_html(pitches, "single")
    out_html = _pitch_table_html(pitches, "field_out")
    walk_html = _pitch_table_html(pitches, "walk")

    assert hit_html.count('class="hvp-pitch-row-hit"') == 1
    assert 'class="hvp-pitch-row-out"' not in hit_html
    assert out_html.count('class="hvp-pitch-row-out"') == 1
    assert 'class="hvp-pitch-row-hit"' not in out_html
    assert "hvp-pitch-row-hit" not in walk_html
    assert "hvp-pitch-row-out" not in walk_html
