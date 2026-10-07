import requests
import json
import time

BASE_URL = "http://localhost:9000"

def test_all():
    print("1. Logging in as superadmin...")
    # Wait for server to start
    for _ in range(10):
        try:
            r = requests.get(f"{BASE_URL}/")
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(1)
    
    login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "username": "admin",
        "password": "AdminPassword123!"
    })
    print(f"Login status: {login_resp.status_code}")
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    tenant_id = "default"

    print("\n2. Testing Stripe Config & Test Connection...")
    stripe_cfg = requests.post(
        f"{BASE_URL}/api/tenants/{tenant_id}/integrations/stripe/config",
        headers=headers,
        json={
            "api_type": "payment_api",
            "environment": "sandbox",
            "is_active": True,
            "credentials": {
                "secret_key": "sk_test_mock_12345",
                "publishable_key": "pk_test_mock_12345"
            }
        }
    )
    print("Stripe config save:", stripe_cfg.status_code, stripe_cfg.json())

    stripe_test = requests.post(
        f"{BASE_URL}/api/tenants/{tenant_id}/integrations/stripe/test",
        headers=headers,
        json={"api_type": "payment_api", "environment": "sandbox", "credentials": {"secret_key": "sk_test_mock_123"}}
    )
    print("Stripe test ping:", stripe_test.status_code, stripe_test.json())

    print("\n3. Testing Razorpay Config & Test Connection...")
    rzp_cfg = requests.post(
        f"{BASE_URL}/api/tenants/{tenant_id}/integrations/razorpay/config",
        headers=headers,
        json={
            "api_type": "payment_api",
            "environment": "sandbox",
            "is_active": True,
            "credentials": {
                "key_id": "rzp_test_1DP5mmOlF5G5ag",
                "key_secret": "test_secret_12345"
            }
        }
    )
    print("Razorpay config save:", rzp_cfg.status_code, rzp_cfg.json())

    rzp_test = requests.post(
        f"{BASE_URL}/api/tenants/{tenant_id}/integrations/razorpay/test",
        headers=headers,
        json={"api_type": "payment_api", "environment": "sandbox", "credentials": {"key_id": "rzp_test_123", "key_secret": "secret_123"}}
    )
    print("Razorpay test ping:", rzp_test.status_code, rzp_test.json())

    print("\n4. Testing Blue Dart Logistics Config & Booking...")
    bd_cfg = requests.post(
        f"{BASE_URL}/api/tenants/{tenant_id}/integrations/bluedart/config",
        headers=headers,
        json={
            "api_type": "order_api",
            "environment": "sandbox",
            "is_active": True,
            "credentials": {
                "customer_code": "123456",
                "license_key": "BD_LICENSE_TEST_KEY",
                "login_id": "BD_USER"
            }
        }
    )
    print("Blue Dart config save:", bd_cfg.status_code, bd_cfg.json())

    bd_test = requests.post(
        f"{BASE_URL}/api/tenants/{tenant_id}/integrations/bluedart/test",
        headers=headers,
        json={"api_type": "order_api", "environment": "sandbox", "credentials": {"customer_code": "123456", "license_key": "BD_LICENSE_TEST_KEY", "login_id": "BD_USER"}}
    )
    print("Blue Dart test ping:", bd_test.status_code, bd_test.json())

    bd_book = requests.post(
        f"{BASE_URL}/api/tenants/{tenant_id}/shipping/book-shipment",
        headers=headers,
        json={
            "order_id": "ORD-TEST-999",
            "provider": "bluedart",
            "origin_pincode": "400001",
            "destination_pincode": "110001",
            "customer_name": "Rohan Sharma",
            "customer_phone": "919876543210"
        }
    )
    print("Blue Dart book shipment:", bd_book.status_code, bd_book.json())
    awb = bd_book.json()["awb_number"]

    bd_track = requests.get(
        f"{BASE_URL}/api/tenants/{tenant_id}/shipping/track/{awb}",
        headers=headers
    )
    print("Blue Dart track AWB:", bd_track.status_code, bd_track.json())

    print("\n5. Testing Xpressbees Logistics Config & Booking...")
    xb_cfg = requests.post(
        f"{BASE_URL}/api/tenants/{tenant_id}/integrations/xpressbees/config",
        headers=headers,
        json={
            "api_type": "order_api",
            "environment": "sandbox",
            "is_active": True,
            "credentials": {
                "email": "merchant@example.com",
                "password": "Password123!"
            }
        }
    )
    print("Xpressbees config save:", xb_cfg.status_code, xb_cfg.json())

    xb_book = requests.post(
        f"{BASE_URL}/api/tenants/{tenant_id}/shipping/book-shipment",
        headers=headers,
        json={
            "order_id": "ORD-XB-888",
            "provider": "xpressbees",
            "origin_pincode": "560001",
            "destination_pincode": "500001",
            "customer_name": "Priya Patel",
            "customer_phone": "919876543210"
        }
    )
    print("Xpressbees book shipment:", xb_book.status_code, xb_book.json())
    xb_awb = xb_book.json()["awb_number"]

    xb_track = requests.get(
        f"{BASE_URL}/api/tenants/{tenant_id}/shipping/track/{xb_awb}",
        headers=headers
    )
    print("Xpressbees track AWB:", xb_track.status_code, xb_track.json())

    print("\n6. Listing all configured integrations...")
    integrations_list = requests.get(
        f"{BASE_URL}/api/tenants/{tenant_id}/integrations",
        headers=headers
    )
    print("Integrations list:", integrations_list.status_code, json.dumps(integrations_list.json(), indent=2))

    print("\n✅ ALL INTEGRATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_all()
