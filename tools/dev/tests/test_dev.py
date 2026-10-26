"""No Docker/network required: verify local safety and command contracts."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "dev.py"
spec = importlib.util.spec_from_file_location("keel_dev", SOURCE)
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)


class DevTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="keel test with spaces ")
        self.root = Path(self.temp.name)
        self.state = self.root / ".dev"
        self.state.mkdir()
        self.patches = [patch.object(dev, "ROOT", self.root), patch.object(dev, "STATE", self.state)]
        for p in self.patches:
            p.start()
        self.c = {"root": str(self.root), "id": "a"*12, "ports": dict(dev.PORTS),
                  "admin_password": "admin-test", "app_password": "app-test", "storage_password": "storage-test",
                  "jwt": "jwt-test", "vault": "vault-test"}
        dev.write_json(self.state / "config.json", self.c)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def test_clone_identity_cannot_be_reused(self):
        self.c["root"] = "another clone"
        dev.write_json(self.state / "config.json", self.c)
        with self.assertRaises(dev.DevError):
            dev.config()

    def test_duplicate_ports_rejected(self):
        self.c["ports"]["api"] = self.c["ports"]["frontend"]
        dev.write_json(self.state / "config.json", self.c)
        with self.assertRaises(dev.DevError):
            dev.config()

    def test_ports_skip_busy_and_duplicate_values(self):
        with patch.object(dev, "available", side_effect=lambda p: p != 8000):
            self.assertEqual(dev.allocate_ports({"a":8000, "b":8000}), {"a":8001,"b":8002})

    def test_no_inherited_secret_or_remote_database(self):
        with patch.dict(os.environ, {"DATABASE_URL":"postgresql://production", "STRIPE_SECRET_KEY":"sk_live_fake"}):
            env = dev.environment(self.c)
        self.assertNotIn("STRIPE_SECRET_KEY", env)
        self.assertIn("ceopro_app:app-test@127.0.0.1", env["DATABASE_URL"])
        self.assertNotIn("admin-test", str(env))
        self.assertNotIn("KEEL_ALLOW_DISPOSABLE_PROVIDER_PROMOTION", env)

    def test_only_migration_environment_gets_admin_password(self):
        self.assertIn("keel_dev_admin:admin-test@", dev.environment(self.c, admin=True)["DATABASE_URL"])

    def test_exact_frontend_api_pair(self):
        env = dev.environment(self.c)
        self.assertEqual(env["CORS_ALLOWED_ORIGINS"], env["FRONTEND_BASE_URL"])
        self.assertEqual(env["VITE_API_BASE_URL"], "/api")
        self.assertEqual(env["KEEL_API_PROXY_TARGET"], "http://127.0.0.1:8000")

    def test_managed_overrides_refused(self):
        (self.state / "integrations.env").write_text("DATABASE_URL=postgresql://remote", encoding="utf-8")
        with self.assertRaises(dev.DevError):
            dev.integrations()

    def test_live_stripe_refused(self):
        (self.state / "integrations.env").write_text("STRIPE_SECRET_KEY=sk_live_fake\nSTRIPE_WEBHOOK_SECRET=whsec_fake", encoding="utf-8")
        with self.assertRaises(dev.DevError):
            dev.integrations()

    def test_incomplete_stripe_refused(self):
        (self.state / "integrations.env").write_text("STRIPE_SECRET_KEY=sk_test_fake", encoding="utf-8")
        with self.assertRaises(dev.DevError):
            dev.integrations()

    def test_provider_config_does_not_execute_shell(self):
        (self.state / "integrations.env").write_text("GROQ_API_KEY=$(do-not-execute)", encoding="utf-8")
        self.assertEqual(dev.integrations()["GROQ_API_KEY"], "$(do-not-execute)")

    def test_compose_scoped_names_volumes_and_loopback(self):
        dev.compose_file(self.c)
        c = json.loads((self.state / "compose.json").read_text())
        self.assertEqual(set(c["services"]), {"postgres","redis","storage","mail"})
        for service in c["services"].values():
            self.assertNotIn("container_name", service)
            self.assertEqual(service["labels"]["com.keel.dev.root"], str(self.root))
            self.assertTrue(all(p.startswith("127.0.0.1:") for p in service["ports"]))
        self.assertEqual(set(c["volumes"]), {"postgres","redis","storage"})

    def test_lock_never_removes_active_lock(self):
        path = self.state / "command.lock"
        path.write_text("123")
        with self.assertRaises(dev.DevError):
            with dev.command_lock():
                self.fail()
        self.assertEqual(path.read_text(), "123")

    def test_lock_released_on_failure(self):
        with self.assertRaises(RuntimeError):
            with dev.command_lock():
                raise RuntimeError()
        self.assertFalse((self.state / "command.lock").exists())

    def test_full_mode_has_original_worker_modules(self):
        self.assertEqual(len(dev.WORKERS), 8)
        self.assertTrue(set(dev.CORE) < set(dev.WORKERS))

    def test_existing_environment_files_not_referenced_for_loading(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("load_dotenv", code)
        self.assertNotIn('"backend/.env"', code)
        self.assertNotIn("FLUSHALL", code)
        self.assertNotIn("down\", \"-v", code)

    def test_redaction_for_tail_and_follow(self):
        self.assertEqual(dev.redact("sk_test_hidden whsec_hidden postgresql://user:pass@host/db"), "<redacted> <redacted> postgresql://<redacted>")

    def test_failed_readiness_is_not_success(self):
        with self.assertRaises(dev.DevError):
            dev.wait_for("synthetic failed readiness", lambda: False, timeout=0)

    def test_native_stderr_not_terminating_in_windows_wrapper(self):
        wrapper = (SOURCE.parents[2] / "dev.ps1").read_text(encoding="utf-8")
        self.assertIn("$ErrorActionPreference = 'Continue'", wrapper)
        self.assertIn("exit $LASTEXITCODE", wrapper)

    def test_constraints_are_sanitized_from_real_manifests(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('constraints = STATE / "constraints.txt"', code)
        self.assertNotIn('-c ../../backend', (SOURCE.parent / "requirements.txt").read_text())

    def test_fatal_worker_error_is_actionable_without_timeout(self):
        def failed():
            raise dev.DevError("forecast failed; inspect forecast.log")
        with self.assertRaisesRegex(dev.DevError, "forecast.log"):
            dev.wait_for("forecast", failed, timeout=1)

    def test_legacy_local_entry_delegates_to_same_runtime(self):
        script = (SOURCE.parents[2] / "keel").read_text(encoding="utf-8")
        self.assertIn('exec bash "$ROOT/dev.sh" up', script)

    def test_seed_is_bounded_and_never_overwrites(self):
        spec = importlib.util.spec_from_file_location("keel_fixtures", SOURCE.parent / "fixtures.py")
        fixtures = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixtures)
        source = self.root / "backend/mocks/e2e_pipeline_demo.csv"
        source.parent.mkdir(parents=True)
        source.write_text("product_name,quantity\n" + "Synthetic,1\n" * 100, encoding="utf-8")
        target, created = fixtures.generate(self.root, self.state / "fixtures")
        self.assertTrue(created)
        self.assertEqual(len(target.read_text().splitlines()), 21)
        target.write_text("developer edit", encoding="utf-8")
        _, created = fixtures.generate(self.root, self.state / "fixtures")
        self.assertFalse(created)
        self.assertEqual(target.read_text(), "developer edit")

    def test_vite_isolation_is_explicit_and_does_not_change_manual_start(self):
        self.assertEqual(dev.environment(self.c)["KEEL_DEV_ISOLATED"], "1")
        config = (SOURCE.parents[2] / "frontend/vite.config.js").read_text(encoding="utf-8")
        self.assertIn("envDir: process.env.KEEL_DEV_ISOLATED === '1' ? false : undefined", config)

    def test_failed_migration_cannot_report_success(self):
        from types import SimpleNamespace
        with patch.object(dev.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(dev.DevError, "Migration runner failed"):
                dev.database(self.c, "migrate")
