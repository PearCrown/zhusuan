from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
import json
import subprocess
from django.test import SimpleTestCase, override_settings
from django.core.management.base import CommandError
from core.db_archive import backup, restore, checksum, pg_environment, run_tool


class ArchiveTests(SimpleTestCase):
    def test_environment_keeps_password_out_of_argv_and_discards_inherited_pg_overrides(self):
        with patch.dict(os.environ,{"PGSERVICE":"unexpected","PGHOSTADDR":"elsewhere"}):
            env=pg_environment({"HOST":"host","PORT":"5432","NAME":"db","USER":"role","PASSWORD":"private","OPTIONS":{"sslmode":"verify-full","sslrootcert":"ca.pem"}})
        self.assertNotIn("PGSERVICE",env);self.assertNotIn("PGHOSTADDR",env)
        self.assertEqual(env["PGPASSWORD"],"private");self.assertEqual(env["PGSSLMODE"],"verify-full")

    def test_backup_refuses_overwrite_and_unknown_extension(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/"archive.dump";path.write_bytes(b"existing")
            with self.assertRaises(CommandError):backup(path)
            self.assertEqual(path.read_bytes(),b"existing")
            with self.assertRaises(CommandError):backup(Path(folder)/"not.sql")

    def test_backup_failure_removes_only_its_incomplete_output(self):
        with TemporaryDirectory() as folder,patch("core.db_archive.binary",return_value="pg_dump"),patch("core.db_archive.run_tool",side_effect=CommandError("safe")):
            path=Path(folder)/"archive.dump"
            with self.assertRaises(CommandError):backup(path)
            self.assertFalse(path.exists())

    def test_restore_refuses_live_database_role_and_mismatched_confirmation(self):
        from django.conf import settings
        db=settings.DATABASES["default"]
        for target,user,confirmation in [(db["NAME"],"other",db["NAME"]),("other",db["USER"],"other"),("other","other","wrong"),("host=elsewhere","other","host=elsewhere")]:
            with self.assertRaises(CommandError),patch("core.db_archive.psycopg.connect") as connection:
                restore("missing.dump",target,user,"TARGET_TEST_PASSWORD",confirmation)
            connection.assert_not_called()

    def test_tampered_archive_rejected_before_connect(self):
        with TemporaryDirectory() as folder,patch.dict(os.environ,{"TARGET_TEST_PASSWORD":"private"}),patch("core.db_archive.binary",return_value="pg_restore"),patch("core.db_archive.psycopg.connect") as connection:
            path=Path(folder)/"archive.dump";path.write_bytes(b"changed")
            Path(str(path)+".manifest.json").write_text(json.dumps({"format":1,"sha256":"0"*64,"bytes":7}))
            with self.assertRaises(CommandError):restore(path,"restore_target","restore_role","TARGET_TEST_PASSWORD","restore_target")
            connection.assert_not_called()

    def test_tool_error_and_timeout_do_not_expose_stderr(self):
        for outcome in [subprocess.CompletedProcess([],1,stderr=b"password=private"),subprocess.TimeoutExpired([],600)]:
            with patch("core.db_archive.subprocess.run",side_effect=outcome if isinstance(outcome,Exception) else None,return_value=outcome):
                with self.assertRaises(CommandError) as error:run_tool(["pg_dump"])
            self.assertNotIn("private",str(error.exception))

    def test_manifest_write_failure_removes_owned_archive_and_partial_manifest(self):
        with TemporaryDirectory() as folder,patch("core.db_archive.binary",return_value="pg_dump"),patch("core.db_archive.run_tool"),patch("core.db_archive.json.dump",side_effect=OSError("disk full")):
            path=Path(folder)/"archive.dump"
            with self.assertRaises(OSError):backup(path)
            self.assertFalse(path.exists());self.assertFalse(Path(str(path)+".manifest.json").exists())
