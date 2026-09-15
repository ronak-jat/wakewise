import urllib.request
import urllib.error
import json
import time

BASE_URL = "https://web-production-de20d.up.railway.app"

def test_health():
    print("Testing /api/health...")
    for attempt in range(12):
        try:
            req = urllib.request.Request(f"{BASE_URL}/api/health", headers={"Origin": "https://wakewise-nine.vercel.app"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"Status: {resp.status}")
                print(f"Allow-Origin: {resp.headers.get('Access-Control-Allow-Origin')}")
                data = json.loads(resp.read().decode("utf-8"))
                print(f"Body: {data}")
                return True
        except Exception as e:
            print(f"Attempt {attempt+1} waiting for Railway deployment: {e}")
            time.sleep(5)
    return False

def test_preflight():
    print("\nTesting OPTIONS /api/admin/announcements...")
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/api/admin/announcements",
            headers={
                "Origin": "https://wakewise-nine.vercel.app",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type"
            },
            method="OPTIONS"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"Preflight status: {resp.status}")
            print(f"Allow-Origin: {resp.headers.get('Access-Control-Allow-Origin')}")
            print(f"Allow-Methods: {resp.headers.get('Access-Control-Allow-Methods')}")
            return True
    except Exception as e:
        print(f"Preflight error: {e}")
        return False

def test_invalid_login_safe():
    print("\nTesting POST /api/auth/login safe rejection...")
    try:
        payload = json.dumps({"email": "nonexistent_test_user_xyz@test.com", "password": "DummyPassword123!"}).encode("utf-8")
        req = urllib.request.Request(
            f"{BASE_URL}/api/auth/login",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Origin": "https://wakewise-nine.vercel.app"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"Status: {resp.status}")
    except urllib.error.HTTPError as e:
        print(f"HTTP Status (expected 401): {e.code}")
        print(f"Allow-Origin: {e.headers.get('Access-Control-Allow-Origin')}")
        err_body = e.read().decode("utf-8")
        print(f"Response: {err_body}")
        return e.code == 401
    except Exception as e:
        print(f"Login test error: {e}")
        return False

if __name__ == "__main__":
    h_ok = test_health()
    p_ok = test_preflight()
    l_ok = test_invalid_login_safe()
    print(f"\nResults: Health={h_ok}, Preflight={p_ok}, SafeAuth={l_ok}")
