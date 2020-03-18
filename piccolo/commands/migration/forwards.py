from __future__ import annotations
import asyncio
import pprint
import typing as t

import click

from piccolo.commands.migration.base import (
    BaseMigrationManager,
    MigrationModule,
    PiccoloAppModule,
)
from piccolo.conf.apps import AppConfig
from piccolo.migrations.tables import Migration
from piccolo.migrations.auto import MigrationManager


class ForwardsMigrationManager(BaseMigrationManager):
    def __init__(self, app_name: str, *args, **kwargs):
        self.app_name = app_name

    def run_migrations(self, app_modules: t.List[PiccoloAppModule]) -> None:
        already_ran = Migration.get_migrations_which_ran()
        print(f"Already ran:\n{already_ran}\n")

        for app_module in app_modules:
            app_config: AppConfig = getattr(app_module, "APP_CONFIG")

            migration_modules: t.Dict[
                str, MigrationModule
            ] = self.get_migration_modules(app_config.migrations_folder_path)

            ids = self.get_migration_ids(migration_modules)
            print(f"Migration ids = {ids}")

            havent_run = sorted(set(ids) - set(already_ran))
            for _id in havent_run:
                migration_module = migration_modules[_id]
                response = asyncio.run(migration_module.forwards())

                if isinstance(response, MigrationManager):
                    asyncio.run(response.run())

                print(f"Ran {_id}")
                Migration.insert().add(
                    Migration(name=_id, app_name=self.app_name)
                ).run_sync()

    def run(self):
        print("Running migrations ...")
        self.create_migration_table()

        app_modules = self.get_app_modules()

        print("Config Modules:")
        pprint.pprint(app_modules)
        print("\n")

        self.run_migrations(app_modules)


@click.command()
@click.argument("app_name")
def forwards(app_name: str):
    """
    Runs any migrations which haven't been run yet, or up to a specific
    migration.
    """
    manager = ForwardsMigrationManager(app_name=app_name)
    manager.run()
