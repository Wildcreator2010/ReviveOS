from revive_api.main import _paginate


def test_exact_final_page_has_no_next_cursor() -> None:
    selected, cursor = _paginate([1, 2], 2, None)

    assert selected == [1, 2]
    assert cursor is None


def test_non_final_page_has_next_cursor() -> None:
    selected, cursor = _paginate([1, 2, 3], 2, None)

    assert selected == [1, 2]
    assert cursor is not None
