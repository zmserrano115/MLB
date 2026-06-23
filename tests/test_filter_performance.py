import ast
from pathlib import Path


def app_source_and_tree():
    source = Path("app.py").read_text(encoding="utf-8")
    return source, ast.parse(source)


def function_node(tree, name):
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


def test_live_context_cache_keys_are_shared_between_users():
    source, tree = app_source_and_tree()

    schedule_loader = function_node(tree, "load_schedule")
    weather_loader = function_node(tree, "load_published_weather")

    assert [arg.arg for arg in schedule_loader.args.args] == ["game_date"]
    assert [arg.arg for arg in weather_loader.args.args] == ["cache_version"]
    assert "data_snapshot_id" not in source


def test_matchup_filters_use_fragment_reruns_without_blocking_hand_splits():
    source, tree = app_source_and_tree()
    filter_fragment = function_node(tree, "render_matchup_filter_fragment")

    has_fragment_decorator = any(
        isinstance(decorator, ast.Attribute)
        and isinstance(decorator.value, ast.Name)
        and decorator.value.id == "st"
        and decorator.attr == "fragment"
        for decorator in filter_fragment.decorator_list
    )

    assert has_fragment_decorator
    assert "future.result(timeout=15)" not in source
    assert "filter_prebuilt_matchups(" in source
