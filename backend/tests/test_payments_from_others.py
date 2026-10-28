"""Money paid onto a card from someone else's account (a friend repaying a
flight booked for them) is a refund of that expense, not a card payment.
Invented data."""
from __future__ import annotations

import io

from app.db.models import Transaction, TransactionType
from app.db.session import session_scope
from app.normalization.review import REFUND_FROM_SOMEONE_ELSE
from app.services.transfer_marking import retype_card_payments

GIRO_IBAN = "DE89370400440532013000"
FRIEND_IBAN = "DE02120300000000202051"

CARD_ROWS = (
    "Date,Description,Amount\n"
    "2026-05-03,Flug Beispielair,-500.00\n"
    "2026-05-04,Buchladen Musterstadt,-18.90\n"
    "2026-05-06,Tankstelle Beispiel,-61.20\n"
    "2026-05-08,Café Sonnenschein,-7.40\n"
    f"2026-05-10,Gutschrift Erika Muster {FRIEND_IBAN},500.00\n"
    f"2026-05-20,Zahlungseingang {GIRO_IBAN},120.00\n"
)


def _account(client, name, account_type, iban=None):
    body = {"name": name, "account_type": account_type, **({"iban": iban} if iban else {})}
    r = client.post("/api/accounts", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _import(client, account_id, rows, name="karte.csv"):
    preview = client.post("/api/imports/preview", data={"account_id": account_id},
                          files={"file": (name, io.BytesIO(rows.encode()), "text/csv")}).json()
    r = client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account_id})
    assert r.status_code == 200, r.text


def _by_amount(client, amount_minor):
    items = client.get("/api/transactions", params={"page_size": 100}).json()["items"]
    return next(t for t in items if t["amount_minor"] == amount_minor)


def test_a_friend_repaying_a_flight_cancels_the_expense(client):
    _account(client, "Giro", "checking", GIRO_IBAN)
    card = _account(client, "Visa", "credit_card")
    _import(client, card, CARD_ROWS)

    repaid = _by_amount(client, 50000)
    assert repaid["transaction_type"] == "expense" and not repaid["is_transfer"]
    assert repaid["needs_review"]
    own = _by_amount(client, 12000)
    assert own["is_transfer"]  # paid from the user's own account

    totals = client.get("/api/analytics/totals", params={"account_ids": card}).json()
    assert totals["expenses_minor"] == 1890 + 6120 + 740  # the flight: 500 spent, 500 repaid
    assert totals["income_minor"] == 0


def test_without_any_own_iban_known_it_stays_a_card_payment(client):
    card = _account(client, "Visa", "credit_card")
    _import(client, card, CARD_ROWS)
    assert _by_amount(client, 50000)["is_transfer"]
    assert _by_amount(client, 12000)["is_transfer"]


def test_existing_payments_are_sorted_once_an_own_iban_is_known(client):
    giro = _account(client, "Giro", "checking")
    card = _account(client, "Visa", "credit_card")
    _import(client, card, CARD_ROWS)
    assert _by_amount(client, 50000)["is_transfer"]

    r = client.patch(f"/api/accounts/{giro}", json={"iban": GIRO_IBAN})
    assert r.status_code == 200, r.text
    repaid_id = _by_amount(client, 50000)["id"]
    with session_scope() as session:
        assert retype_card_payments(session) == 1
        repaid = session.get(Transaction, repaid_id)
        assert repaid.transaction_type == TransactionType.EXPENSE and not repaid.is_transfer
        assert repaid.needs_review and repaid.review_reason == REFUND_FROM_SOMEONE_ELSE
        assert retype_card_payments(session) == 0  # settled: nothing flips back and forth
    assert _by_amount(client, 12000)["is_transfer"]


def test_a_type_the_user_chose_stays(client):
    """The "friend" was the user's own savings account, not in the app."""
    _account(client, "Giro", "checking", GIRO_IBAN)
    card = _account(client, "Visa", "credit_card")
    _import(client, card, CARD_ROWS)
    payment = _by_amount(client, 50000)
    assert not payment["is_transfer"]
    r = client.patch(f"/api/transactions/{payment['id']}", json={"transaction_type": "transfer"})
    assert r.status_code == 200, r.text
    with session_scope() as session:
        retype_card_payments(session)
    assert _by_amount(client, 50000)["is_transfer"]
