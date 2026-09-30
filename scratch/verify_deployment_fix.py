import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from fastapi.testclient import TestClient
from main import app
from config import settings
from database import Base, engine, get_db
from models import User
from security import hash_password, create_access_token


class TestDeploymentAndCrossDeviceAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

        # Ensure test user and admin exist
        db = next(get_db())
        test_user = db.query(User).filter(User.email == "crossdevice_user@test.com").first()
        if not test_user:
            test_user = User(
                name="Cross Device User",
                email="crossdevice_user@test.com",
                password=hash_password("ValidPassword123!"),
                role="USER",
                provider="LOCAL"
            )
            db.add(test_user)
            db.commit()
            db.refresh(test_user)

        test_admin = db.query(User).filter(User.email == "crossdevice_admin@test.com").first()
        if not test_admin:
            test_admin = User(
                name="Cross Device Admin",
                email="crossdevice_admin@test.com",
                password=hash_password("AdminSecurePass123!"),
                role="ADMIN",
                provider="LOCAL"
            )
            db.add(test_admin)
            db.commit()
            db.refresh(test_admin)

        db.close()

    def test_01_cors_allowed_origins_list(self):
        origins = settings.get_allowed_origins()
        self.assertIn("https://wakewise.dev", origins)
        self.assertIn("https://www.wakewise.dev", origins)
        self.assertIn("https://web-production-de20d.up.railway.app", origins)
        self.assertIn("http://localhost:8000", origins)
        self.assertIn("http://127.0.0.1:8000", origins)
        self.assertIn("http://localhost:3000", origins)
        self.assertIn("http://127.0.0.1:3000", origins)
        self.assertNotIn("*", origins)
        self.assertNotIn("https://wakewise-nine.vercel.app", origins)

    def test_02_options_preflight_login_railway(self):
        """OPTIONS /api/auth/login from Railway deployment returns 200 OK + CORS headers."""
        resp = self.client.options(
            "/api/auth/login",
            headers={
                "Origin": "https://web-production-de20d.up.railway.app",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type"
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "https://web-production-de20d.up.railway.app")
        self.assertEqual(resp.headers.get("access-control-allow-credentials"), "true")
        self.assertIn("POST", resp.headers.get("access-control-allow-methods", ""))

    def test_03_options_preflight_login_custom_domain(self):
        """OPTIONS /api/auth/login from wakewise.dev returns 200 OK + CORS headers."""
        resp = self.client.options(
            "/api/auth/login",
            headers={
                "Origin": "https://wakewise.dev",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type"
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "https://wakewise.dev")
        self.assertEqual(resp.headers.get("access-control-allow-credentials"), "true")

    def test_04_login_post_cross_device_success(self):
        """POST /api/auth/login without prior session (simulating fresh incognito / mobile)."""
        resp = self.client.post(
            "/api/auth/login",
            headers={"Origin": "https://wakewise.dev"},
            json={
                "email": "crossdevice_user@test.com",
                "password": "ValidPassword123!"
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "https://wakewise.dev")
        self.assertEqual(resp.headers.get("access-control-allow-credentials"), "true")
        data = resp.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["token_type"], "bearer")
        self.assertEqual(data["user"]["email"], "crossdevice_user@test.com")
        self.assertEqual(data["user"]["role"], "USER")

    def test_05_admin_login_post_custom_domain_success(self):
        """POST /api/auth/login for admin from wakewise.dev."""
        resp = self.client.post(
            "/api/auth/login",
            headers={"Origin": "https://wakewise.dev"},
            json={
                "email": "crossdevice_admin@test.com",
                "password": "AdminSecurePass123!"
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "https://wakewise.dev")
        data = resp.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["user"]["role"], "ADMIN")

    def test_06_login_post_invalid_password_returns_401_with_cors(self):
        """Invalid credentials return 401 Unauthorized with CORS headers preserved."""
        resp = self.client.post(
            "/api/auth/login",
            headers={"Origin": "https://wakewise.dev"},
            json={
                "email": "crossdevice_user@test.com",
                "password": "WrongPassword999!"
            }
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "https://wakewise.dev")
        self.assertEqual(resp.headers.get("access-control-allow-credentials"), "true")

    def test_07_untrusted_origin_blocked(self):
        """Untrusted origin does not get Access-Control-Allow-Origin header."""
        resp = self.client.get(
            "/api/health",
            headers={"Origin": "https://evil-hacker-site.com"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.headers.get("access-control-allow-origin"))


if __name__ == "__main__":
    unittest.main()
