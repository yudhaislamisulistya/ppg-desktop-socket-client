import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "provisioner_app",
    ROOT / "provisioner" / "app.py",
)
PROVISIONER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROVISIONER)


class ProvisionerTest(unittest.TestCase):
    def test_registration_validation_and_acl_are_idempotent(self):
        device_id, username, password = PROVISIONER.validate_registration(
            {
                "device_id": " PPG-002 ",
                "mqtt_username": "PPG-002",
                "mqtt_password": "example-password-123!",
            }
        )
        self.assertEqual((device_id, username, password), (
            "PPG-002",
            "PPG-002",
            "example-password-123!",
        ))

        acl = "user storage\ntopic read ppg/+/raw\n"
        first = PROVISIONER.render_device_acl(acl, device_id)
        second = PROVISIONER.render_device_acl(first, device_id)
        self.assertEqual(first, second)
        self.assertEqual(first.count("# BEGIN DEVICE PPG-002"), 1)
        self.assertIn("topic readwrite ppg/PPG-002/metrics", first)

        with self.assertRaisesRegex(ValueError, "harus sama"):
            PROVISIONER.validate_registration(
                {
                    "device_id": "PPG-002",
                    "mqtt_username": "other-user",
                    "mqtt_password": "example-password-123!",
                }
            )

    def test_existing_account_password_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            password_file = config_dir / "passwords"
            acl_file = config_dir / "acl"
            password_file.write_text("PPG-002:$7$existing-hash\n", encoding="utf-8")
            acl_file.write_text("user storage\ntopic read ppg/+/raw\n", encoding="utf-8")

            with (
                patch.object(PROVISIONER, "PASSWORD_FILE", password_file),
                patch.object(PROVISIONER, "ACL_FILE", acl_file),
                patch.object(PROVISIONER, "update_password") as update_password,
                patch.object(PROVISIONER.os, "kill"),
            ):
                status = PROVISIONER.register_device(
                    "PPG-002",
                    "PPG-002",
                    "different-password!",
                )

            self.assertEqual(status, "already_registered")
            update_password.assert_not_called()
            self.assertIn(
                "topic readwrite ppg/PPG-002/metrics",
                acl_file.read_text(encoding="utf-8"),
            )

    def test_registration_endpoint_creates_account_without_extra_field(self):
        PROVISIONER.RegistrationHandler.registration_enabled = True
        PROVISIONER.registration_attempts.clear()
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            PROVISIONER.RegistrationHandler,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/api/devices/register"
        body = json.dumps(
            {
                "device_id": "PPG-002",
                "mqtt_username": "PPG-002",
                "mqtt_password": "strong-password!",
            }
        ).encode()

        try:
            request = urllib.request.Request(
                url,
                data=body,
                method="POST",
            )
            with patch.object(
                PROVISIONER,
                "register_device",
                return_value="registered",
            ) as register:
                with urllib.request.urlopen(request) as response:
                    result = json.loads(response.read())

            register.assert_called_once_with(
                "PPG-002",
                "PPG-002",
                "strong-password!",
            )
            self.assertEqual(result["status"], "registered")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(1)


if __name__ == "__main__":
    unittest.main()
