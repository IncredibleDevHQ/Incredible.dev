"""Postgres keeps precise timestamps and isolates users in non-public schemas."""

from __future__ import annotations

import pytest

from design_agent.surfaces.web.auth import user_schema
from design_agent.surfaces.web.postgres import pg_schema, validate_schema


def test_schema_is_postgres_compatible_and_does_not_lose_timestamp_precision():
    schema = pg_schema()
    assert " REAL" not in schema
    assert "DOUBLE PRECISION" in schema
    assert "PRAGMA" not in schema
    assert "brand TEXT" in schema and "preview TEXT" in schema


@pytest.mark.parametrize("value", ["public", "auth", "user_x;DROP SCHEMA public", "../other", ""])
def test_only_uuid_based_user_schemas_can_be_selected(value):
    with pytest.raises(ValueError):
        validate_schema(value)


def test_schema_identity_is_deterministic_and_cannot_contain_sql():
    assert (
        user_schema("11111111-1111-4111-8111-111111111111")
        == "user_11111111111141118111111111111111"
    )
    assert validate_schema(user_schema("11111111-1111-4111-8111-111111111111"))
