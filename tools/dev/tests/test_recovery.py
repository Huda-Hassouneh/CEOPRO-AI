"""Recovery contracts: no Docker, provider or application mutation required."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dev
import testing


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="recovery with spaces ")
        self.root = Path(self.temp.name)
        self.state = self.root / ".dev"
        self.state.mkdir()
        self.c = {"root": str(self.root), "id": "b"*12, "ports": dict(dev.PORTS),
                  "admin_password": "admin-test", "app_password": "app-test",
                  "storage_password": "storage-test", "jwt": "jwt-test", "vault": "vault-test"}
        self.patches = [patch.object(dev, "ROOT", self.root), patch.object(dev, "STATE", self.state)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def test_test_services_are_opt_in_loopback_tmpfs_without_volumes(self):
        dev.compose_file(self.c)
        services = json.loads((self.state / "compose.json").read_text())["services"]
        for name, port in (("test-redis", 6379), ("test-storage", 9000)):
            s = services[name]
            self.assertEqual(s["profiles"], ["tests"])
            self.assertEqual(s["ports"], [f"127.0.0.1::{port}"])
            self.assertEqual(s["tmpfs"], ["/data"])
            self.assertNotIn("volumes", s)
        self.assertNotIn("profiles", services["redis"])
        self.assertEqual(services["redis"]["volumes"], ["redis:/data"])
        self.assertEqual(services["storage"]["volumes"], ["storage:/data"])

    def test_backend_database_and_worker_credentials_are_separate(self):
        env = testing.test_environment(self.c, "keel_billing_test_dev_abcdef123456")
        self.assertEqual(env["AI_TEST_DATABASE_URL"], env["DATABASE_URL"])
        self.assertIn("keel_dev_admin:", env["DATABASE_URL"])
        self.assertIn("ceopro_app:", env["SCRAPER_DATABASE_URL"])
        self.assertTrue(env["SCRAPER_DATABASE_URL"].endswith("/keel_billing_test_dev_abcdef123456"))
        self.assertNotIn("KEEL_ALLOW_DISPOSABLE_PROVIDER_PROMOTION", env)
        self.assertNotIn("CORS_ALLOWED_ORIGINS", env)
        self.assertEqual(env["FRONTEND_BASE_URL"], "http://localhost:5173")
        self.assertEqual(env["MINIO_ENDPOINT"], "http://" + env["AI_TEST_MINIO_ENDPOINT"])

    def test_test_environment_does_not_import_provider_keys_or_opt_ins(self):
        (self.state / "integrations.env").write_text("GROQ_API_KEY=private-test\nAI_TEST_EMBEDDINGS=1\n")
        with patch.dict(os.environ, {"STRIPE_E2E_SECRET_KEY": "sk_live_fake", "AI_TEST_SENTIMENT": "1"}):
            env = testing.test_environment(self.c, "keel_billing_test_dev_abcdef123456")
        for key in ("GROQ_API_KEY", "STRIPE_E2E_SECRET_KEY", "AI_TEST_SENTIMENT", "AI_TEST_EMBEDDINGS"):
            self.assertNotIn(key, env)

    def test_non_test_database_name_is_rejected(self):
        with self.assertRaises(dev.DevError):
            testing.test_environment(self.c, "keel_dev_protected")

    def test_cleanup_targets_only_the_two_disposable_services(self):
        with patch.object(dev, "check_docker"), patch.object(dev, "compose_file"), \
             patch.object(dev, "verify_containers"), patch.object(dev, "stop_processes") as stop, \
             patch.object(dev, "docker") as docker:
            testing.cleanup(self.c)
        stop.assert_called_once_with({"test-api", "test-frontend"})
        self.assertEqual([call.args[1:] for call in docker.call_args_list],
                         [("stop", "test-redis", "test-storage"), ("rm", "-f", "test-redis", "test-storage")])

    def test_cleanup_refuses_foreign_ownership_before_stopping_anything(self):
        with patch.object(dev, "check_docker"), patch.object(dev, "compose_file"), \
             patch.object(dev, "verify_containers", side_effect=dev.DevError("foreign ownership")), \
             patch.object(dev, "stop_processes") as stop, patch.object(dev, "docker") as docker:
            with self.assertRaises(dev.DevError):
                testing.cleanup(self.c)
        stop.assert_not_called()
        docker.assert_not_called()

    def test_reused_pid_from_previous_boot_is_never_stopped(self):
        dev.write_json(self.state / "processes.json", {"test-api": {"pid": 1234, "created": 10}})
        with patch.object(dev, "owned", return_value=False), patch("psutil.boot_time", return_value=20), \
             patch("psutil.Process") as process:
            dev.stop_processes({"test-api"})
        process.assert_not_called()
        self.assertEqual(dev.processes(), {})

    def test_current_boot_identity_mismatch_is_preserved(self):
        record = {"pid": 1234, "created": 30}
        dev.write_json(self.state / "processes.json", {"test-api": record})
        with patch.object(dev, "owned", return_value=False), patch("psutil.boot_time", return_value=20), \
             patch("psutil.pid_exists", return_value=True):
            with self.assertRaises(dev.DevError):
                dev.stop_processes({"test-api"})
        self.assertEqual(dev.processes()["test-api"], record)

    def test_browser_api_is_restricted_but_existing_auth_fixture_has_admin_setup(self):
        env = testing.test_environment(self.c, "keel_billing_test_dev_abcdef123456")
        with patch.object(dev, "start_process") as start, patch.object(dev, "wait_for"), \
             patch.object(dev, "integrations", return_value={"CHROMIUM_PATH": "test-chrome"}), \
             patch.object(testing, "logged") as logged:
            testing.browser(self.c, env, self.state, "browser-ci")
        api_env = start.call_args_list[0].kwargs["env"]
        self.assertIn("ceopro_app:", api_env["DATABASE_URL"])
        self.assertNotIn("AI_TEST_DATABASE_URL", api_env)
        account = next(call for call in logged.call_args_list if call.args[1].name == "account.log")
        self.assertIn("keel_dev_admin:", account.args[2]["DATABASE_URL"])

    def test_local_browser_path_does_not_require_external_provider_configuration(self):
        (self.state / "integrations.env").write_text("STRIPE_SECRET_KEY=sk_test_\nCHROMIUM_PATH=test-chrome\n")
        self.assertEqual(dev.integrations(validate_providers=False)["CHROMIUM_PATH"], "test-chrome")
        with self.assertRaises(dev.DevError):
            dev.integrations()

    def test_stopping_test_processes_preserves_normal_process_records(self):
        normal = {"pid": 5678, "created": 40}
        dev.write_json(self.state / "processes.json", {"api": normal, "test-api": {"pid": 1234, "created": 10}})
        with patch.object(dev, "owned", return_value=False), patch("psutil.boot_time", return_value=20):
            dev.stop_processes({"test-api"})
        self.assertEqual(dev.processes(), {"api": normal})
