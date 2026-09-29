from alembic import command
from alembic.script import ScriptDirectory

from tests.conftest import alembic_config


def test_migration_history_has_a_single_head():
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    assert len(heads) == 1, heads


def test_models_match_migrated_schema():
    # The session fixture has already built the test database from empty with
    # `alembic upgrade head`; this fails if the models declare anything the
    # migrations do not create.
    command.check(alembic_config())


def test_latest_migration_downgrades_and_reapplies_cleanly():
    config = alembic_config()
    command.downgrade(config, "-1")
    command.upgrade(config, "head")
    command.check(config)
