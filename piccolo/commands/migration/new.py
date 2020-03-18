from __future__ import annotations
import asyncio
import datetime
import os
import sys
import typing as t
from types import ModuleType

import black
import click

from piccolo.commands.migration.base import (
    BaseMigrationManager,
    MigrationModule,
)
from piccolo.conf.apps import AppConfig, AppRegistry
from piccolo.migrations.auto import (
    SchemaSnapshot,
    MigrationManager,
    DiffableTable,
    SchemaDiffer,
)
from piccolo.migrations.template import render_template


MIGRATION_MODULES: t.Dict[str, ModuleType] = {}


def _create_migrations_folder(migrations_path: str) -> bool:
    """
    Creates the folder that migrations live in. Returns True/False depending
    on whether it was created or not.
    """
    if os.path.exists(migrations_path):
        return False
    else:
        os.mkdir(migrations_path)
        for filename in ("__init__.py", "config.py"):
            with open(os.path.join(migrations_path, filename), "w"):
                pass
        return True


def _create_new_migration(app_config: AppConfig, auto=False) -> None:
    """
    Creates a new migration file on disk.
    """
    _id = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    path = os.path.join(app_config.migrations_folder_path, f"{_id}.py")
    with open(path, "w") as f:
        if auto:
            alter_statements = AutoMigrationManager().get_alter_statements(
                app_config=app_config
            )
            file_contents = render_template(
                migration_id=_id, auto=True, alter_statements=alter_statements,
            )
        else:
            file_contents = f.write(
                render_template(migration_id=_id, auto=False)
            )

        # Beautify the file contents a bit.
        file_contents = black.format_str(
            file_contents, mode=black.FileMode(line_length=82)
        )

        f.write(file_contents)


###############################################################################


class AutoMigrationManager(BaseMigrationManager):
    def get_alter_statements(self, app_config: AppConfig):
        """
        Works out which alter statements are required.
        """
        alter_statements: t.List[str] = []

        for config_module in self.get_app_modules():
            migrations_folder = config_module.APP_CONFIG.migrations_folder_path

            migration_modules: t.Dict[
                str, MigrationModule
            ] = self.get_migration_modules(migrations_folder)

            migration_managers: t.List[MigrationManager] = []

            for _, migration_module in migration_modules.items():
                response = asyncio.run(migration_module.forwards())
                if isinstance(response, MigrationManager):
                    migration_managers.append(response)

            schema_snapshot = SchemaSnapshot(migration_managers)
            snapshot = schema_snapshot.get_snapshot()

            # Now get the current schema:
            current_diffable_tables = [
                DiffableTable(
                    class_name=i.__name__,
                    tablename=i._meta.tablename,
                    columns=i._meta.columns,
                )
                for i in app_config.table_classes
            ]

            # Compare the current schema with the snapshot
            differ = SchemaDiffer(
                schema=current_diffable_tables, schema_snapshot=snapshot
            )
            alter_statements = differ.get_alter_statements()

        return alter_statements


###############################################################################


@click.argument("app_name")
@click.option(
    "--auto", is_flag=True, help="Auto create the migration contents."
)
@click.command()
def new(app_name: str, auto: bool):
    """
    Creates a new file like piccolo_migrations/2018-09-04T19:44:09.py
    """
    print("Creating new migration ...")

    try:
        import piccolo_conf
    except ImportError:
        print("Can't find piccolo_conf")
        sys.exit(1)

    try:
        app_registry: AppRegistry = piccolo_conf.APP_REGISTRY
    except AttributeError:
        print("APP_REGISTRY isn't defined in piccolo_conf")
        sys.exit(1)

    app_config: AppConfig = app_registry.get_app_config(app_name)

    _create_migrations_folder(app_config.migrations_folder_path)
    _create_new_migration(app_config=app_config, auto=auto)
