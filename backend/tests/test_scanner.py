"""Pure unit tests, no database."""

from app.scanner.rules import Child, plan, top_by_volume


def test_top_by_volume_skips_delisted() -> None:
    meta = {"universe": [{"name": "A"}, {"name": "B", "isDelisted": True}, {"name": "C"}]}
    contexts = [{"dayNtlVlm": "10"}, {"dayNtlVlm": "999"}, {"dayNtlVlm": "50"}]
    assert top_by_volume(meta, contexts, 2) == ["C", "A"]


def _child(
    pid: int, asset: str, enabled: bool = True, busy: bool = False, by: str | None = None
) -> Child:
    return Child(pid, asset, enabled, by, busy)


def test_new_candidate_creates_a_child() -> None:
    assert plan([], ["SOL"], 10, set()).create == ["SOL"]


def test_flat_child_off_the_list_is_disabled_busy_one_kept() -> None:
    children = [_child(1, "SOL"), _child(2, "ETH", busy=True)]
    out = plan(children, [], 10, set())
    assert out.disable == [1] and out.create == [] and out.enable == []


def test_old_child_is_re_enabled_only_if_the_scanner_disabled_it() -> None:
    children = [
        _child(1, "SOL", enabled=False, by="scanner"),
        _child(2, "ETH", enabled=False, by="owner"),
    ]
    out = plan(children, ["SOL", "ETH"], 10, set())
    assert out.enable == [1] and out.create == []


def test_slots_cap_new_children_best_first() -> None:
    children = [_child(1, "BTC", busy=True)]
    out = plan(children, ["SOL", "ETH", "XRP"], 3, set())
    assert out.create == ["SOL", "ETH"]  # BTC holds 1 of 3 slots


def test_taken_assets_and_disabled_scanner() -> None:
    assert plan([], ["SOL", "ETH"], 10, {"SOL"}).create == ["ETH"]
    children = [_child(1, "SOL"), _child(2, "ETH", busy=True)]
    out = plan(children, ["SOL", "XRP"], 10, set(), scanning=False)
    assert out.disable == [1] and out.create == [] and out.enable == []
