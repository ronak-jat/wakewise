import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from main import app
from database import Base, engine, get_db
from models import User
from security import hash_password, create_access_token


class TestProductionCORS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

        # Create test admin user in DB
        db = next(get_db())
        admin_email = "cors_admin@test.com"
        admin = db.query(User).filter(User.email == admin_email).first()
        if not admin:
            admin = User(
                name="CORS Admin",
                email=admin_email,
                password=hash_password("adminpass123"),
                role="ADMIN",
                provider="LOCAL"
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)

        cls.admin_token = create_access_token(data={"sub": admin.email, "role": admin.role, "id": admin.id})
        cls.admin_headers = {
            "Authorization": f"Bearer {cls.admin_token}",
            "Origin": "https://wakewise-nine.vercel.app"
        }
        db.close()

    def test_cors_health_endpoint(self):
        """GET /api/health from production Vercel frontend receives CORS allow-origin."""
        resp = self.client.get("/api/health", headers={"Origin": "https://wakewise-nine.vercel.app"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "https://wakewise-nine.vercel.app")
        self.assertEqual(resp.headers.get("access-control-allow-credentials"), "true")

    def test_cors_preflight_options_admin_announcements(self):
        """OPTIONS /api/admin/announcements receives 200 OK and valid preflight headers."""
        resp = self.client.options(
            "/api/admin/announcements",
            headers={
                "Origin": "https://wakewise-nine.vercel.app",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type"
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "https://wakewise-nine.vercel.app")
        self.assertIn("POST", resp.headers.get("access-control-allow-methods", ""))
        self.assertEqual(resp.headers.get("access-control-allow-credentials"), "true")

    def test_cors_admin_announcements_unauthorized_has_cors(self):
        """GET /api/admin/announcements without token returns 401 WITH CORS headers."""
        resp = self.client.get(
            "/api/admin/announcements",
            headers={"Origin": "https://wakewise-nine.vercel.app"}
        )
        self.assertEqual(resp.status_code, 401)
        # Verify CORS headers are preserved even on 401 error
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "https://wakewise-nine.vercel.app")
        self.assertEqual(resp.headers.get("access-control-allow-credentials"), "true")

    def test_cors_admin_announcements_authenticated(self):
        """GET /api/admin/announcements with Admin token returns 200 with CORS headers."""
        resp = self.client.get("/api/admin/announcements", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "https://wakewise-nine.vercel.app")
        self.assertEqual(resp.headers.get("access-control-allow-credentials"), "true")

    def test_cors_notifications_endpoint(self):
        """GET /api/notifications/ returns CORS headers."""
        resp = self.client.get("/api/notifications/", headers=self.admin_headers)
        self.assertIn(resp.status_code, [200, 401])
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "https://wakewise-nine.vercel.app")

    def test_cors_admin_coach_assignments(self):
        """GET /api/admin/coach-assignments returns CORS headers."""
        resp = self.client.get("/api/admin/coach-assignments", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "https://wakewise-nine.vercel.app")

    def test_cors_localhost_origins_supported(self):
        """Localhost origins remain supported for development."""
        resp = self.client.get("/api/health", headers={"Origin": "http://localhost:8000"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "http://localhost:8000")

    def test_cors_vercel_preview_regex_supported(self):
        """Vercel preview branch domains match the regex."""
        resp = self.client.get("/api/health", headers={"Origin": "https://wakewise-preview-test123.vercel.app"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "https://wakewise-preview-test123.vercel.app")

    def test_cors_disallows_untrusted_origins(self):
        """Untrusted external origins do not receive allow-origin header."""
        resp = self.client.get("/api/health", headers={"Origin": "https://untrusted-malicious-site.com"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.headers.get("access-control-allow-origin"))


if __name__ == "__main__":
    unittest.main()
