"""One payee behind many branch texts; card bills by their payee. Invented data."""
from __future__ import annotations

import io

from app.normalization.merchant import normalize_merchant
from app.services.chains import find_chains, stem
from app.services.rule_patterns import derive_category_pattern


def test_branch_parts_are_cut_off():
    assert stem("SUPERMARKT SOL C/JACA VALENCIA") == ("SUPERMARKT SOL", True)
    assert stem("SUPERMARKT SOL AV.DE FRANCIA VALENCIA") == ("SUPERMARKT SOL", True)
    assert stem("DROGERIE FLINK KASSEL") == ("DROGERIE FLINK", True)
    assert stem("DROGERIE FLINK GMBH & CO.KG KASSEL") == ("DROGERIE FLINK", True)
    assert stem("BUCHLADEN MUSTER FILIALE") == ("BUCHLADEN MUSTER", True)
    # a town is the name of a city's office; a lone everyday word is no payee
    assert stem("STADT KASSEL") == ("STADT KASSEL", False)
    # inside a name a word may be a town somewhere: only a town at the end counts
    assert stem("CAFE DE LA PAZ") == ("CAFE DE LA PAZ", False)


def test_chains_are_found_from_the_bookings_themselves():
    chains = find_chains({
        "SUPERMARKT SOL C/JACA VALENCIA", "SUPERMARKT SOL AV.DE FRANCIA VALENCIA", "SUPERMARKT SOL GODELLA",
        "DROGERIE FLINK", "DROGERIE FLINK KASSEL",
        "DEUTSCHE BAHN", "DEUTSCHE BANK",             # nothing cut off: different payees
        "STADT KASSEL", "STADT BIELEFELD",            # a city's office each
        "CAFE DE COCO VALENCIA", "CAFE DE LA ABUELA",  # "CAFE DE" is no name
    })
    assert chains == {
        "SUPERMARKT SOL C/JACA VALENCIA": "SUPERMARKT SOL", "SUPERMARKT SOL AV.DE FRANCIA VALENCIA": "SUPERMARKT SOL",
        "SUPERMARKT SOL GODELLA": "SUPERMARKT SOL",
        "DROGERIE FLINK": "DROGERIE FLINK", "DROGERIE FLINK KASSEL": "DROGERIE FLINK",
    }


def test_a_booking_word_broken_over_two_lines_is_not_the_payee():
    assert derive_category_pattern("KARTENVERFÜGUN G APOTHEKE SONNENSCHEIN") == "APOTHEKE SONNENSCHEIN"


def test_the_merchant_behind_a_payment_app():
    assert normalize_merchant("Lastschrift PUNKTE PAY / Drogerie Flink / P AYPROVIDER X1Y2Z3 Einkauf", []) == "Drogerie Flink"


def _import(client, account, rows, name):
    body = ("Datum,Beschreibung,Betrag\n" + rows).encode()
    preview = client.post("/api/imports/preview", data={"account_id": account},
                          files={"file": (name, io.BytesIO(body), "text/csv")}).json()
    r = client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account})
    assert r.status_code == 200, r.text


def test_one_category_learned_for_a_whole_chain(client):
    giro = client.post("/api/accounts", json={"name": "Giro", "account_type": "checking"}).json()["id"]
    _import(client, giro, "".join(
        f"2026-03-{d:02d},Kartenzahlung KOLONIAL SOL {branch},-{d}.00\n"
        for d, branch in [(1, "C/JACA VALENCIA"), (2, "AV.DE FRANCIA VALENCIA"), (3, "C/JACA VALENCIA"), (4, "GODELLA")]
    ), "giro.csv")
    groups = client.get("/api/transactions/review-groups").json()["groups"]
    assert [(g["label"], g["count"]) for g in groups] == [("KOLONIAL SOL", 4)]
    one = groups[0]["transactions"][0]["id"]
    r = client.post(f"/api/transactions/{one}/category-rule", json={"category": "Groceries"})
    assert r.json()["category_rule"]["pattern"] == "KOLONIAL SOL" and r.json()["applied_to"] == 3


def test_a_payee_that_paid_a_card_bill_before_is_a_card_bill(client, tmp_path):
    from tests.pdf_fixtures import write_text_pdf

    giro = client.post("/api/accounts", json={"name": "Giro", "account_type": "checking"}).json()["id"]
    card = client.post("/api/accounts", json={"name": "Karte", "account_type": "credit_card"}).json()["id"]
    path = write_text_pdf(tmp_path / "karte.pdf", [
        "Credit Card Statement", "VISA ending 1234", "Statement Period: 01.03.2026 - 31.03.2026",
        "02.03.2026 Buchladen Beispiel 40.00 EUR", "Statement Total: 40.00 EUR",
    ])
    preview = client.post("/api/imports/preview", data={"account_id": card},
                          files={"file": ("karte.pdf", io.BytesIO(path.read_bytes()), "application/pdf")}).json()
    assert client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": card}).status_code == 200
    # the March bill is linked to its statement; the bills of months without a statement only name the issuer
    _import(client, giro,
            "2026-04-05,Lastschrift KARTENBANK MUSTER AG RECHNUNG VOM 31.03.26,-40.00\n"
            "2026-05-05,Lastschrift KARTENBANK MUSTER AG RECHNUNG VOM 30.04.26,-75.10\n"
            "2026-06-05,Lastschrift KARTENBANK MUSTER AG RECHNUNG VOM 31.05.26,-12.00\n", "giro.csv")
    items = client.get("/api/transactions", params={"account_id": giro, "include_transfers": True}).json()["items"]
    by_amount = {t["amount_minor"]: t for t in items}
    assert by_amount[-4000]["is_transfer"]  # settles the imported statement
    assert by_amount[-7510]["category"] == "Card bills" and not by_amount[-7510]["needs_review"]
    assert by_amount[-1200]["category"] == "Card bills"


def test_an_issuers_debit_without_any_category_is_a_card_bill_too(session, checking_account, credit_card_account):
    """SQL "IN (..., NULL)" never matches a missing category: it must still be found."""
    from datetime import date

    from app.db.models import CreditCardStatement, ImportRecord, ImportStatus, RawTransaction, Transaction
    from app.services.transfer_marking import sort_card_bill_payees

    record = ImportRecord(filename="k.pdf", stored_path="k.pdf", file_checksum="c", status=ImportStatus.IMPORTED,
                          account_id=credit_card_account.id, detected_transaction_count=0)
    session.add(record)
    session.flush()
    statement = CreditCardStatement(account_id=credit_card_account.id, import_id=record.id,
                                    statement_period_end=date(2026, 3, 31), statement_total_minor=4000)
    session.add(statement)
    session.flush()

    def debit(day: int, amount: int, category: str | None, settles: int | None = None) -> Transaction:
        raw = RawTransaction(import_id=record.id, source_row_index=day)
        session.add(raw)
        session.flush()
        tx = Transaction(raw_transaction_id=raw.id, account_id=checking_account.id, transaction_date=date(2026, 4, day),
                         normalized_description="KARTENBANK MUSTER AG RECHNUNG", merchant="KARTENBANK MUSTER AG",
                         category=category, amount_minor=amount, duplicate_fingerprint=f"f{day}",
                         settles_statement_id=settles, is_transfer=settles is not None)
        session.add(tx)
        session.flush()
        return tx

    debit(5, -4000, "Transfers", settles=statement.id)
    unsorted = debit(6, -7510, None)
    session.commit()
    assert sort_card_bill_payees(session) == 1
    session.refresh(unsorted)
    assert unsorted.category == "Card bills"


def test_a_bare_payment_line_read_as_a_refund_before_becomes_a_transfer(session, credit_card_account):
    from datetime import date

    from app.db.models import ImportRecord, ImportStatus, RawTransaction, Transaction, TransactionType
    from app.services.transfer_marking import retype_card_payments

    record = ImportRecord(filename="k.pdf", stored_path="k.pdf", file_checksum="p", status=ImportStatus.IMPORTED,
                          account_id=credit_card_account.id, detected_transaction_count=2)
    session.add(record)
    session.flush()
    made = []
    for i, text in enumerate(["Payment", "BUCHLADEN BEISPIEL Erstattung"]):
        raw = RawTransaction(import_id=record.id, source_row_index=i, original_description=text)
        session.add(raw)
        session.flush()
        tx = Transaction(raw_transaction_id=raw.id, account_id=credit_card_account.id, transaction_date=date(2026, 9, 30),
                         normalized_description=text, merchant=text, category="Other Expense", amount_minor=8000,
                         transaction_type=TransactionType.EXPENSE, duplicate_fingerprint=f"p{i}")
        session.add(tx)
        made.append(tx)
    session.commit()
    assert retype_card_payments(session) == 1
    payment, refund = made
    session.refresh(payment)
    session.refresh(refund)
    assert payment.transaction_type == TransactionType.TRANSFER and payment.is_transfer and payment.category == "Transfers"
    assert refund.transaction_type == TransactionType.EXPENSE  # a refund stays a refund
