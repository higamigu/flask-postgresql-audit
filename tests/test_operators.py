import json

import pytest
from sqlalchemy import text

from .app import audit, db

JSONB_SUBTRACT = "SELECT {schema}jsonb_subtract((:new)::jsonb, (:old)::jsonb)"


@pytest.mark.parametrize(
    ("old", "new", "result"),
    (
        ({}, {}, {}),
        ({"age": 13}, {"age": 14}, {"age": 14}),
        ({"name": "Someone"}, {"name": "Someone"}, {}),
        ({"name": "Someone"}, {"name": "Else"}, {"name": "Else"}),
        ({"ids": [1, 2, 3]}, {"ids": [1, 2]}, {"ids": [1, 2]}),
        ({"ids": [1, 2]}, {"ids": []}, {"ids": []}),
        ({"ids": [1, 2]}, {"ids": [1, 2, 3]}, {"ids": [1, 2, 3]}),
        ({"ids": {}}, {"ids": None}, {"ids": None}),
        ({"ids": None}, {"ids": {}}, {"ids": {}}),
        ({"name": "Someone", "age": 15}, {"name": "Else", "age": 15}, {"name": "Else"}),
    ),
)
def test_jsonb_subtract(test_client, old, new, result):
    assert (
        db.session.scalar(
            text(JSONB_SUBTRACT.format(schema=audit.context["schema_prefix"])),
            {"old": json.dumps(old), "new": json.dumps(new)},
        )
        == result
    )


JSONB_ARRAY_SUBTRACT = (
    "SELECT {schema}jsonb_array_subtract((:arg1)::jsonb, (:arg2)::jsonb)"
)


@pytest.mark.parametrize(
    ("arg1", "arg2", "result"),
    (
        ([1, 2, 3], [2], [1, 3]),
        ([1, 2, 3], [1, 2, 3], []),
        ([1, 2, 3], [4, 5], [1, 2, 3]),
        (["a", "b", "c"], ["b"], ["a", "c"]),
        ([], [1, 2], []),
        ([1, 2], [], [1, 2]),
        ([1, 2, 2, 3], [2], [1, 3]),
        ([{"a": 1}, {"b": 2}], [{"a": 1}], [{"b": 2}]),
        ([1, 2, 3], 2, [1, 3]),
        ([1, 2, 3], None, [1, 2, 3]),
        ([1, 2], {"a": 1}, [1, 2]),
        ({"a": 1}, [1, 2], {"a": 1}),
    ),
)
def test_jsonb_array_subtract(test_client, arg1, arg2, result):
    assert (
        db.session.scalar(
            text(JSONB_ARRAY_SUBTRACT.format(schema=audit.context["schema_prefix"])),
            {"arg1": json.dumps(arg1), "arg2": json.dumps(arg2)},
        )
        == result
    )
