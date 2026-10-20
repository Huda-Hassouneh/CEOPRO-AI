from unittest.mock import patch


def create_verified_test_account(client, payload):
    """Exercise the current pending-registration and email-verification flow."""
    sent_codes = []
    with patch(
        "src.ai.core.notifications.send_email_verification_email",
        side_effect=lambda _email, code: sent_codes.append(code) or True,
    ):
        pending = client.post("/auth/signup", json=payload)

    assert pending.status_code == 202, pending.text
    registration = pending.json()
    assert registration["status"] == "pending_verification"
    assert registration["delivery"] == "sent"
    assert sent_codes

    response = client.post(
        "/auth/email/verify",
        json={
            "email": registration["email"],
            "registration_token": registration["registration_token"],
            "code": sent_codes[-1],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()
