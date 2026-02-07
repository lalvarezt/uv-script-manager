"""Tests for database migration system."""

from pathlib import Path

from tinydb import TinyDB

from uv_helper.migrations import (
    CURRENT_SCHEMA_VERSION,
    MIGRATIONS,
    Migration001AddSourceType,
    Migration002AddCopyParentDir,
    Migration003AddRefType,
    MigrationRunner,
)
from uv_helper.state import StateManager


class TestMigration001AddSourceType:
    """Tests for Migration001AddSourceType."""

    def test_adds_source_type_to_existing_scripts(self, tmp_path: Path) -> None:
        """Test that migration adds source_type to scripts without it."""
        # Create database with script missing source_type
        db_path = tmp_path / "test.json"
        db = TinyDB(db_path)
        scripts_table = db.table("scripts")

        # Insert scripts without source_type (old format)
        scripts_table.insert(
            {
                "name": "script1.py",
                "source_url": "https://github.com/user/repo",
                "ref": "main",
            }
        )
        scripts_table.insert(
            {
                "name": "script2.py",
                "source_url": "https://github.com/user/repo2",
                "ref": "dev",
            }
        )

        # Run migration
        migration = Migration001AddSourceType()
        migration.migrate(db)

        # Verify source_type was added
        all_scripts = scripts_table.all()
        assert len(all_scripts) == 2
        assert all(script.get("source_type") == "git" for script in all_scripts)

        db.close()

    def test_preserves_existing_source_type(self, tmp_path: Path) -> None:
        """Test that migration preserves existing source_type."""
        # Create database with script that already has source_type
        db_path = tmp_path / "test.json"
        db = TinyDB(db_path)
        scripts_table = db.table("scripts")

        # Insert script with source_type already set
        scripts_table.insert(
            {
                "name": "script.py",
                "source_type": "local",
                "source_path": "/path/to/script",
            }
        )

        # Run migration
        migration = Migration001AddSourceType()
        migration.migrate(db)

        # Verify source_type was not changed
        script = scripts_table.get(doc_id=1)
        assert script["source_type"] == "local"  # type: ignore[index]

        db.close()

    def test_empty_database(self, tmp_path: Path) -> None:
        """Test migration on empty database."""
        db_path = tmp_path / "test.json"
        db = TinyDB(db_path)

        # Run migration on empty database
        migration = Migration001AddSourceType()
        migration.migrate(db)

        # Should not raise any errors
        scripts_table = db.table("scripts")
        assert len(scripts_table.all()) == 0

        db.close()


class TestMigration002AddCopyParentDir:
    """Tests for Migration002AddCopyParentDir."""

    def test_adds_copy_parent_dir_to_existing_scripts(self, tmp_path: Path) -> None:
        """Test that migration adds copy_parent_dir to scripts without it."""
        # Create database with script missing copy_parent_dir
        db_path = tmp_path / "test.json"
        db = TinyDB(db_path)
        scripts_table = db.table("scripts")

        # Insert scripts without copy_parent_dir (old format)
        scripts_table.insert(
            {
                "name": "script1.py",
                "source_type": "local",
                "source_path": "/path/to/script1",
            }
        )
        scripts_table.insert(
            {
                "name": "script2.py",
                "source_type": "git",
                "source_url": "https://github.com/user/repo",
            }
        )

        # Run migration
        migration = Migration002AddCopyParentDir()
        migration.migrate(db)

        # Verify copy_parent_dir was added with default False
        all_scripts = scripts_table.all()
        assert len(all_scripts) == 2
        assert all(script.get("copy_parent_dir") is False for script in all_scripts)

        db.close()

    def test_preserves_existing_copy_parent_dir(self, tmp_path: Path) -> None:
        """Test that migration preserves existing copy_parent_dir."""
        # Create database with script that already has copy_parent_dir
        db_path = tmp_path / "test.json"
        db = TinyDB(db_path)
        scripts_table = db.table("scripts")

        # Insert script with copy_parent_dir already set
        scripts_table.insert(
            {
                "name": "script.py",
                "source_type": "local",
                "source_path": "/path/to/package",
                "copy_parent_dir": True,
            }
        )

        # Run migration
        migration = Migration002AddCopyParentDir()
        migration.migrate(db)

        # Verify copy_parent_dir was not changed
        script = scripts_table.get(doc_id=1)
        assert script["copy_parent_dir"] is True  # type: ignore[index]

        db.close()

    def test_empty_database(self, tmp_path: Path) -> None:
        """Test migration on empty database."""
        db_path = tmp_path / "test.json"
        db = TinyDB(db_path)

        # Run migration on empty database
        migration = Migration002AddCopyParentDir()
        migration.migrate(db)

        # Should not raise any errors
        scripts_table = db.table("scripts")
        assert len(scripts_table.all()) == 0

        db.close()


class TestMigration003AddRefType:
    """Tests for Migration003AddRefType."""

    def test_infers_ref_type_for_legacy_rows(self, tmp_path: Path) -> None:
        """Test that migration infers default/branch/tag/commit from existing ref values."""
        db_path = tmp_path / "test.json"
        db = TinyDB(db_path)
        scripts_table = db.table("scripts")

        scripts_table.insert({"name": "default.py", "ref": None})
        scripts_table.insert({"name": "branch.py", "ref": "main"})
        scripts_table.insert({"name": "tag.py", "ref": "v1.2.3"})
        scripts_table.insert({"name": "commit.py", "ref": "deadbeef"})

        migration = Migration003AddRefType()
        migration.migrate(db)

        scripts_by_name = {script["name"]: script for script in scripts_table.all()}
        assert scripts_by_name["default.py"]["ref_type"] == "default"
        assert scripts_by_name["branch.py"]["ref_type"] == "branch"
        assert scripts_by_name["tag.py"]["ref_type"] == "tag"
        assert scripts_by_name["commit.py"]["ref_type"] == "commit"

        db.close()


class TestMigrationRunner:
    """Tests for MigrationRunner."""

    def test_get_schema_version_empty_db(self, tmp_path: Path) -> None:
        """Test get_schema_version returns 0 for empty database."""
        db_path = tmp_path / "test.json"
        db = TinyDB(db_path)

        runner = MigrationRunner(db, db_path)
        version = runner.get_schema_version()

        assert version == 0

        db.close()

    def test_mark_and_get_schema_version(self, tmp_path: Path) -> None:
        """Test schema version tracking through mark_migration_applied."""
        db_path = tmp_path / "test.json"
        db = TinyDB(db_path)

        runner = MigrationRunner(db, db_path)

        # Mark first migration
        runner.mark_migration_applied(MIGRATIONS[0])

        # Get version
        version = runner.get_schema_version()
        assert version == 1

        # Mark next migration
        runner.mark_migration_applied(MIGRATIONS[1])
        version = runner.get_schema_version()
        assert version == 2

        db.close()

    def test_needs_migration_empty_db(self, tmp_path: Path) -> None:
        """Test needs_migration returns True for empty database."""
        db_path = tmp_path / "test.json"
        db = TinyDB(db_path)

        runner = MigrationRunner(db, db_path)
        assert runner.needs_migration() is True

        db.close()

    def test_needs_migration_current_version(self, tmp_path: Path) -> None:
        """Test needs_migration returns False when at current version."""
        db_path = tmp_path / "test.json"
        db = TinyDB(db_path)

        runner = MigrationRunner(db, db_path)
        runner.mark_migration_applied(MIGRATIONS[-1])

        assert runner.needs_migration() is False

        db.close()

    def test_run_migrations_from_empty(self, tmp_path: Path) -> None:
        """Test running all migrations from scratch."""
        # Create database with old-format scripts
        db_path = tmp_path / "test.json"
        db = TinyDB(db_path)
        scripts_table = db.table("scripts")

        # Insert script without source_type
        scripts_table.insert(
            {
                "name": "test.py",
                "source_url": "https://github.com/user/repo",
                "ref": "main",
            }
        )

        # Run all migrations
        runner = MigrationRunner(db, db_path)
        runner.run_migrations(MIGRATIONS)

        # Verify migration was applied
        script = scripts_table.get(doc_id=1)
        assert script["source_type"] == "git"  # type: ignore[index]
        assert script["copy_parent_dir"] is False  # type: ignore[index]

        # Verify schema version was updated
        assert runner.get_schema_version() == CURRENT_SCHEMA_VERSION

        db.close()

    def test_run_migrations_already_current(self, tmp_path: Path) -> None:
        """Test run_migrations does nothing when already at current version."""
        db_path = tmp_path / "test.json"
        db = TinyDB(db_path)

        runner = MigrationRunner(db, db_path)
        runner.mark_migration_applied(MIGRATIONS[-1])

        # Should not run any migrations
        runner.run_migrations(MIGRATIONS)

        # Version should still be current
        assert runner.get_schema_version() == CURRENT_SCHEMA_VERSION

        db.close()


class TestStateManagerMigration:
    """Tests for StateManager integration with migrations."""

    def test_state_manager_runs_migrations_on_init(self, tmp_path: Path) -> None:
        """Test that StateManager automatically runs migrations on initialization."""
        # Create database with old-format script
        state_file = tmp_path / "state.json"
        db = TinyDB(state_file)
        scripts_table = db.table("scripts")

        # Insert script without source_type (old format but with required fields)
        scripts_table.insert(
            {
                "name": "old_script.py",
                "source_url": "https://github.com/user/repo",
                "ref": "main",
                "installed_at": "2025-01-01T12:00:00",
                "repo_path": str(tmp_path / "repo"),
                "symlink_path": str(tmp_path / "bin" / "old_script.py"),
                "dependencies": [],
                "commit_hash": "abc123",
            }
        )
        db.close()

        # Initialize StateManager (should trigger migrations)
        state_manager = StateManager(state_file)

        # Verify migrations were applied
        script = state_manager.get_script("old_script.py")
        assert script is not None
        assert script.source_type == "git"
        assert script.copy_parent_dir is False

    def test_state_manager_migrations_idempotent(self, tmp_path: Path) -> None:
        """Test that running StateManager init multiple times doesn't re-run migrations."""
        state_file = tmp_path / "state.json"

        # First init - runs migrations
        state_manager1 = StateManager(state_file)

        # Check version
        runner = MigrationRunner(state_manager1.db, state_file)
        version_after_first = runner.get_schema_version()
        assert version_after_first == CURRENT_SCHEMA_VERSION

        # Second init - should not re-run migrations
        state_manager2 = StateManager(state_file)

        # Version should still be the same
        runner2 = MigrationRunner(state_manager2.db, state_file)
        version_after_second = runner2.get_schema_version()
        assert version_after_second == version_after_first

    def test_state_manager_applies_migration_003_on_init(self, tmp_path: Path) -> None:
        """Test that StateManager applies ref_type migration for schema version 2 databases."""
        state_file = tmp_path / "state.json"
        db = TinyDB(state_file)

        metadata_table = db.table("metadata")
        metadata_table.insert({"schema_version": 2})

        scripts_table = db.table("scripts")
        scripts_table.insert(
            {
                "name": "legacy.py",
                "source_type": "git",
                "source_url": "https://github.com/user/repo",
                "ref": "deadbeef",
                "installed_at": "2025-01-01T12:00:00",
                "repo_path": str(tmp_path / "repo"),
                "symlink_path": str(tmp_path / "bin" / "legacy.py"),
                "dependencies": [],
                "commit_hash": "deadbeef",
                "copy_parent_dir": False,
            }
        )
        db.close()

        state_manager = StateManager(state_file)
        script = state_manager.get_script("legacy.py")

        assert script is not None
        assert script.ref_type == "commit"

        runner = MigrationRunner(state_manager.db, state_file)
        assert runner.get_schema_version() == CURRENT_SCHEMA_VERSION
