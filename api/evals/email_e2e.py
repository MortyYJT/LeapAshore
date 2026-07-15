from __future__ import annotations

import argparse
import re
import time
from uuid import uuid4

import httpx


TOKEN_PATTERN = re.compile(r"(?:verify|reset)_token=([A-Za-z0-9_-]+)")


def wait_for_message(mail: httpx.Client, recipient: str, subject: str, timeout: float = 15) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = mail.get("/api/v1/messages")
        response.raise_for_status()
        for item in response.json().get("messages", []):
            recipients = {address["Address"] for address in item.get("To") or []}
            if recipient in recipients and item.get("Subject") == subject:
                body = mail.get(f"/view/{item['ID']}.txt")
                body.raise_for_status()
                return body.text
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {subject!r} to {recipient}")


def extract_token(message: str) -> str:
    match = TOKEN_PATTERN.search(message)
    if not match:
        raise AssertionError("Email did not contain an OfferPilot action token")
    return match.group(1)


def run(api_url: str, mailpit_url: str) -> dict[str, object]:
    email = f"smtp-e2e-{uuid4().hex[:10]}@example.com"
    password = "RuntimePass123!"
    new_password = "NewRuntimePass456!"
    with (
        httpx.Client(base_url=api_url.rstrip("/"), timeout=30, trust_env=False) as api,
        httpx.Client(base_url=mailpit_url.rstrip("/"), timeout=30, trust_env=False) as mail,
    ):
        registration = api.post("/auth/register", json={
            "email": email,
            "password": password,
            "display_name": "SMTP E2E",
            "accepted_terms": True,
        })
        assert registration.status_code == 201, registration.text
        assert registration.json()["delivery"] == "smtp"

        verification_token = extract_token(wait_for_message(mail, email, "验证你的 OfferPilot 邮箱"))
        assert api.post("/auth/verify-email", json={"token": verification_token}).status_code == 200
        assert api.post("/auth/login", json={"email": email, "password": password}).status_code == 200

        assert api.post("/auth/forgot-password", json={"email": email}).status_code == 200
        reset_token = extract_token(wait_for_message(mail, email, "重置你的 OfferPilot 密码"))
        assert api.post("/auth/reset-password", json={"token": reset_token, "password": new_password}).status_code == 200
        assert api.post("/auth/login", json={"email": email, "password": password}).status_code == 401
        assert api.post("/auth/login", json={"email": email, "password": new_password}).status_code == 200
    return {"email": email, "verification": "passed", "password_reset": "passed", "smtp": "passed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify OfferPilot email flows through a Mailpit SMTP inbox.")
    parser.add_argument("--api-url", default="http://localhost:8080/api")
    parser.add_argument("--mailpit-url", default="http://localhost:8025")
    args = parser.parse_args()
    print(run(args.api_url, args.mailpit_url))
