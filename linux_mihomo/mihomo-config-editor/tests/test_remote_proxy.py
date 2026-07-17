import contextlib
import errno
import io
import posixpath
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import server


class FakeAttributes:
    def __init__(self, mode, filename=None):
        self.st_mode = mode
        self.filename = filename


class FakeRemoteFile(io.BytesIO):
    def __init__(self, sftp, path, mode, initial=b""):
        super().__init__(initial)
        self.sftp = sftp
        self.path = path
        self.mode = mode

    def close(self):
        if not self.closed and "w" in self.mode:
            existing = self.sftp.files.get(self.path)
            file_mode = existing["mode"] if existing else 0o600
            self.sftp.files[self.path] = {"data": self.getvalue(), "mode": file_mode}
        super().close()


class FakeSftp:
    def __init__(self, home="/home/tester"):
        self.home = home
        self.files = {}
        self.directories = {home: 0o700}
        self.fail_rename_targets = set()

    def add_file(self, path, text, mode=0o644):
        self.files[path] = {"data": text.encode("utf-8"), "mode": mode}

    def text(self, path):
        return self.files[path]["data"].decode("utf-8")

    def lstat(self, path):
        if path in self.files:
            return FakeAttributes(stat.S_IFREG | self.files[path]["mode"])
        if path in self.directories:
            return FakeAttributes(stat.S_IFDIR | self.directories[path])
        raise OSError(errno.ENOENT, "missing")

    stat = lstat

    def open(self, path, mode):
        if "r" in mode:
            if path not in self.files:
                raise OSError(errno.ENOENT, "missing")
            return FakeRemoteFile(self, path, mode, self.files[path]["data"])
        return FakeRemoteFile(self, path, mode)

    def chmod(self, path, mode):
        self.files[path]["mode"] = mode

    def mkdir(self, path, mode=0o777):
        self.directories[path] = mode

    def remove(self, path):
        if path not in self.files:
            raise OSError(errno.ENOENT, "missing")
        del self.files[path]

    def listdir_attr(self, path):
        return [
            FakeAttributes(stat.S_IFREG | item["mode"], posixpath.basename(file_path))
            for file_path, item in self.files.items()
            if posixpath.dirname(file_path) == path
        ]

    def posix_rename(self, source, target):
        if target in self.fail_rename_targets:
            raise OSError(errno.EACCES, "rename denied")
        self.files[target] = self.files.pop(source)

    def rename(self, source, target):
        self.posix_rename(source, target)

    def normalize(self, _path):
        return self.home


class RemoteProxyTests(unittest.TestCase):
    def setUp(self):
        self.template_path = Path(__file__).resolve().parents[1] / "static" / "proxy_setting.sh"
        self.template = server.read_proxy_template(self.template_path)
        self.home = "/home/tester"
        self.credentials = {"host": "192.0.2.10", "username": "tester", "password": "not-saved"}
        self.tempdir = tempfile.TemporaryDirectory()
        self.credentials_db_path = Path(self.tempdir.name) / "remote_credentials.db"
        self.credentials_key_path = Path(self.tempdir.name) / "remote_credentials.key"

    def tearDown(self):
        self.tempdir.cleanup()

    def session_for(self, sftp):
        @contextlib.contextmanager
        def session(_credentials):
            yield sftp, self.home, "aa:bb:cc"

        return session

    def test_reconcile_removes_legacy_definitions_and_is_idempotent(self):
        legacy = """# old proxy note
export HTTP_PROXY="http://old:7890"
export HTTPS_PROXY="http://old:7890"
export ALL_PROXY="http://old:7890"
export http_proxy="$HTTP_PROXY"
export https_proxy="$HTTPS_PROXY"
export all_proxy="$ALL_PROXY"
export NO_PROXY="localhost"
export no_proxy="$NO_PROXY"
export PATH="$PATH:/tools"
"""
        updated, removed = server.reconcile_remote_proxy_text(legacy, self.template)

        self.assertEqual(removed, 8)
        self.assertEqual(updated.count(server.REMOTE_PROXY_START_MARKER), 1)
        self.assertIn('export PATH="$PATH:/tools"', updated)
        self.assertEqual(sum(server.is_proxy_variable_definition(line) for line in updated.splitlines()), 8)

        unchanged, second_removed = server.reconcile_remote_proxy_text(updated, self.template)
        self.assertEqual(unchanged, updated)
        self.assertEqual(second_removed, 0)

    def test_remove_deletes_unmarked_legacy_proxy_variables(self):
        legacy = """# old proxy note
export HTTP_PROXY="http://old:7890"
HTTPS_PROXY=http://old:7890
export ALL_PROXY=http://old:7890
http_proxy=$HTTP_PROXY
https_proxy=$HTTPS_PROXY
all_proxy=$ALL_PROXY
NO_PROXY=localhost,127.0.0.1
no_proxy=$NO_PROXY
export PATH="$PATH:/tools"
"""
        updated, removed = server.remove_remote_proxy_text(legacy)

        self.assertEqual(removed, 8)
        self.assertFalse(any(server.is_proxy_variable_definition(line) for line in updated.splitlines()))
        self.assertNotIn(server.REMOTE_PROXY_START_MARKER, updated)
        self.assertIn('export PATH="$PATH:/tools"', updated)

    def test_remote_host_candidates_include_commented_entries_but_exclude_local_hosts(self):
        config_text = """lan-allowed-ips:
  - 127.0.0.1/32
  - 10.100.10.33/32
  - 10.100.10.16/32
  # - 10.100.10.40/32
  - 10.100.10.16/32
  - 10.0.0.0/8
"""
        self.assertEqual(server.extract_remote_host_candidates(config_text), ["10.100.10.16", "10.100.10.40"])

    def test_successful_manual_login_is_encrypted_and_reused_without_browser_password(self):
        sftp = FakeSftp(self.home)
        sftp.add_file(f"{self.home}/.bashrc", "export HTTP_PROXY=http://old\n")

        with mock.patch.object(server, "remote_sftp_session", self.session_for(sftp)):
            preview = server.preview_remote_proxy(
                self.template_path,
                self.credentials_db_path,
                self.credentials_key_path,
                self.credentials,
            )

        self.assertEqual(preview["credentialSource"], "manual")
        self.assertTrue(self.credentials_db_path.is_file())
        self.assertTrue(self.credentials_key_path.is_file())
        self.assertNotIn(self.credentials["password"].encode("utf-8"), self.credentials_db_path.read_bytes())
        self.assertEqual(self.credentials_db_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.credentials_key_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            server.lookup_saved_remote_login(self.credentials_db_path, {"host": self.credentials["host"]}),
            {"ok": True, "host": self.credentials["host"], "found": True, "username": "tester"},
        )
        reused = server.resolve_remote_credentials(
            {"host": self.credentials["host"], "username": "", "password": ""},
            self.credentials_db_path,
            self.credentials_key_path,
        )
        self.assertEqual(reused["username"], self.credentials["username"])
        self.assertEqual(reused["password"], self.credentials["password"])
        self.assertEqual(reused["credentialSource"], "saved")

    def test_public_preview_never_includes_remote_content(self):
        sftp = FakeSftp(self.home)
        bashrc = f"{self.home}/.bashrc"
        sftp.add_file(bashrc, "export HTTP_PROXY=http://old\n")

        with mock.patch.object(server, "remote_sftp_session", self.session_for(sftp)):
            preview = server.preview_remote_proxy(
                self.template_path,
                self.credentials_db_path,
                self.credentials_key_path,
                self.credentials,
            )
        public_plan = preview["files"]

        self.assertEqual({item["key"] for item in public_plan}, {"bashrc", "codexEnv"})
        self.assertTrue(all("content" not in item and "finalText" not in item for item in public_plan))
        self.assertEqual(public_plan[0]["action"], "update")
        self.assertEqual(preview["hostFingerprint"], "aa:bb:cc")

    def test_apply_creates_env_backs_up_existing_files_and_returns_content(self):
        sftp = FakeSftp(self.home)
        bashrc = f"{self.home}/.bashrc"
        sftp.add_file(bashrc, "# old\nexport HTTP_PROXY=http://old\n", mode=0o640)
        initial_plan = server.build_remote_proxy_plan(sftp, self.home, self.template)
        body = {
            **self.credentials,
            "baseHashes": {item["key"]: item["baseHash"] for item in initial_plan},
        }

        with mock.patch.object(server, "remote_sftp_session", self.session_for(sftp)):
            result = server.apply_remote_proxy(
                self.template_path,
                self.credentials_db_path,
                self.credentials_key_path,
                body,
            )

        env_path = f"{self.home}/.codex/.env"
        self.assertIn(f"{self.home}/.codex", sftp.directories)
        self.assertIn(server.REMOTE_PROXY_START_MARKER, sftp.text(bashrc))
        self.assertIn(server.REMOTE_PROXY_START_MARKER, sftp.text(env_path))
        self.assertEqual(sftp.files[bashrc]["mode"], 0o640)
        self.assertEqual(sftp.files[env_path]["mode"], 0o600)
        self.assertTrue(any(".bashrc.mihomo-proxy." in path for path in sftp.files))
        self.assertEqual({item["label"] for item in result["files"]}, {"~/.bashrc", "~/.codex/.env"})
        self.assertTrue(all(server.REMOTE_PROXY_START_MARKER in item["content"] for item in result["files"]))

    def test_apply_keeps_only_three_newest_backups_per_remote_file(self):
        sftp = FakeSftp(self.home)
        bashrc = f"{self.home}/.bashrc"
        sftp.add_file(bashrc, "export HTTP_PROXY=http://old\n")
        for timestamp in ("20260717-100000-000000", "20260717-100001-000000", "20260717-100002-000000"):
            sftp.add_file(f"{bashrc}.mihomo-proxy.{timestamp}.deadbeef.bak", "old backup\n")
        initial_plan = server.build_remote_proxy_plan(sftp, self.home, self.template)
        body = {
            **self.credentials,
            "baseHashes": {item["key"]: item["baseHash"] for item in initial_plan},
        }

        with mock.patch.object(server, "remote_sftp_session", self.session_for(sftp)):
            server.apply_remote_proxy(
                self.template_path,
                self.credentials_db_path,
                self.credentials_key_path,
                body,
            )

        bashrc_backups = [
            path for path in sftp.files
            if path.startswith(f"{bashrc}.mihomo-proxy.") and path.endswith(".bak")
        ]
        self.assertEqual(len(bashrc_backups), 3)
        self.assertFalse(any("20260717-100000-000000" in path for path in bashrc_backups))

    def test_apply_rejects_changed_remote_content_before_writing(self):
        sftp = FakeSftp(self.home)
        bashrc = f"{self.home}/.bashrc"
        sftp.add_file(bashrc, "export HTTP_PROXY=http://old\n")
        initial_plan = server.build_remote_proxy_plan(sftp, self.home, self.template)
        body = {
            **self.credentials,
            "baseHashes": {item["key"]: item["baseHash"] for item in initial_plan},
        }
        sftp.add_file(bashrc, "export HTTP_PROXY=http://changed\n")

        with mock.patch.object(server, "remote_sftp_session", self.session_for(sftp)):
            with self.assertRaises(server.ApiError) as raised:
                server.apply_remote_proxy(
                    self.template_path,
                    self.credentials_db_path,
                    self.credentials_key_path,
                    body,
                )

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(sftp.text(bashrc), "export HTTP_PROXY=http://changed\n")
        self.assertFalse(any("mihomo-proxy" in path for path in sftp.files))

    def test_remove_operation_deletes_unmarked_remote_variables_and_returns_content(self):
        sftp = FakeSftp(self.home)
        bashrc = f"{self.home}/.bashrc"
        legacy = "export HTTP_PROXY=http://old\nexport https_proxy=$HTTPS_PROXY\nexport PATH=$PATH:/tools\n"
        sftp.add_file(bashrc, legacy)
        initial_plan = server.build_remote_proxy_plan(sftp, self.home, self.template)
        body = {
            **self.credentials,
            "baseHashes": {item["key"]: item["baseHash"] for item in initial_plan},
        }

        with mock.patch.object(server, "remote_sftp_session", self.session_for(sftp)):
            result = server.apply_remote_proxy(
                self.template_path,
                self.credentials_db_path,
                self.credentials_key_path,
                body,
                operation="remove",
            )

        self.assertEqual(result["operation"], "remove")
        self.assertEqual(sftp.text(bashrc), "export PATH=$PATH:/tools\n")
        bashrc_result = next(item for item in result["files"] if item["key"] == "bashrc")
        self.assertEqual(bashrc_result["action"], "remove")
        self.assertEqual(bashrc_result["content"], "export PATH=$PATH:/tools\n")

    def test_apply_rolls_back_prior_file_when_second_write_fails(self):
        sftp = FakeSftp(self.home)
        bashrc = f"{self.home}/.bashrc"
        env_path = f"{self.home}/.codex/.env"
        sftp.directories[f"{self.home}/.codex"] = 0o700
        original_bashrc = "export HTTP_PROXY=http://old\n"
        original_env = "export HTTPS_PROXY=http://old\n"
        sftp.add_file(bashrc, original_bashrc)
        sftp.add_file(env_path, original_env, mode=0o600)
        initial_plan = server.build_remote_proxy_plan(sftp, self.home, self.template)
        body = {
            **self.credentials,
            "baseHashes": {item["key"]: item["baseHash"] for item in initial_plan},
        }
        sftp.fail_rename_targets.add(env_path)

        with mock.patch.object(server, "remote_sftp_session", self.session_for(sftp)):
            with self.assertRaises(server.ApiError) as raised:
                server.apply_remote_proxy(
                    self.template_path,
                    self.credentials_db_path,
                    self.credentials_key_path,
                    body,
                )

        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(sftp.text(bashrc), original_bashrc)
        self.assertEqual(sftp.text(env_path), original_env)
        self.assertEqual(raised.exception.details["rollback"], [{"label": "~/.bashrc", "restored": True}])


if __name__ == "__main__":
    unittest.main()
