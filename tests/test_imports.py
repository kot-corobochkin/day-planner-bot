def test_application_factory_imports() -> None:
    from app.main import build_application

    assert build_application is not None


def test_move_task_indexes_accept_comma_separated_unique_numbers() -> None:
    from app.bot.handlers import _parse_task_indexes

    assert _parse_task_indexes("1, 2, 2, 6", maximum=6) == [1, 2, 6]


def test_move_task_indexes_reject_out_of_range_numbers() -> None:
    from app.bot.handlers import _parse_task_indexes

    assert _parse_task_indexes("1, 7", maximum=6) is None
