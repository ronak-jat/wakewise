import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base, get_db
from models import User
from security import hash_password, create_access_token

TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db


class TestAuthAndAdminSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)
        cls.client = TestClient(app)

        db = TestingSessionLocal()
        cls.normal_user = User(
            name="Normal User",
            email="regular_user@alarm.com",
            password=hash_password("password123"),
            role="USER",
            provider="LOCAL"
        )
        cls.admin_user = User(
            name="System Admin",
            email="super_admin@alarm.com",
            password=hash_password("adminpass123"),
            role="ADMIN",
            provider="LOCAL"
        )
        db.add(cls.normal_user)
        db.add(cls.admin_user)
        db.commit()
        db.refresh(cls.normal_user)
        db.refresh(cls.admin_user)
        cls.normal_user_id = cls.normal_user.id
        cls.admin_user_id = cls.admin_user.id
        db.close()

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=test_engine)
        app.dependency_overrides.clear()

    def test_01_normal_user_login_returns_user_role(self):
        resp = self.client.post("/api/auth/login", json={
            "email": "regular_user@alarm.com",
            "password": "password123"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["user"]["role"].upper(), "USER")

    def test_02_admin_user_login_returns_admin_role(self):
        resp = self.client.post("/api/auth/login", json={
            "email": "super_admin@alarm.com",
            "password": "adminpass123"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["user"]["role"].upper(), "ADMIN")

    def test_03_invalid_login_returns_generic_error(self):
        resp = self.client.post("/api/auth/login", json={
            "email": "super_admin@alarm.com",
            "password": "wrong_password"
        })
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Incorrect email or password", resp.json()["detail"])

    def test_04_public_registration_cannot_self_escalate_to_admin(self):
        resp = self.client.post("/api/auth/register", json={
            "name": "Hacker Trying Admin",
            "email": "hacker@alarm.com",
            "password": "secretpass123",
            "role": "ADMIN"
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["data"]["role"].upper(), "USER")

    def test_05_unauthenticated_admin_api_returns_401(self):
        resp = self.client.get("/api/admin/dashboard")
        self.assertEqual(resp.status_code, 401)

    def test_06_normal_user_calling_admin_api_returns_403(self):
        user_token = create_access_token(data={"sub": "regular_user@alarm.com", "role": "USER", "id": self.normal_user_id})
        resp = self.client.get(
            "/api/admin/dashboard",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Administrator access required", resp.json()["detail"])

    def test_07_admin_user_calling_admin_api_returns_200(self):
        admin_token = create_access_token(data={"sub": "super_admin@alarm.com", "role": "ADMIN", "id": self.admin_user_id})
        resp = self.client.get(
            "/api/admin/dashboard",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("total_users", data)


if __name__ == "__main__":
    unittest.main()
