"""Values worked out from all the data are built once per state of the data
(app.db.session.remembered) — and never served stale, nor from a session's
own uncommitted changes."""
from __future__ import annotations

from datetime import date

from sqlmodel import Session, SQLModel, create_engine, delete

from app.db.models import Account, AccountType, ImportRecord, RawTransaction, Transaction, TransactionType
from app.db.session import remembered
from app.services.chains import chain_index


def _counting():
    built = []

    def build():
        built.append(len(built) + 1)
        return built[-1]

    return built, build


def _account(session, name="Giro") -> Account:
    account = Account(name=name, account_type=AccountType.CHECKING, currency="EUR")
    session.add(account)
    session.commit()
    return account


def _booking(session, account, description, record=None) -> Transaction:
    if record is None:
        record = ImportRecord(filename="f.csv", stored_path=f"{description}.csv", file_checksum=description,
                              account_id=account.id, status="imported")
        session.add(record)
        session.flush()
    raw = RawTransaction(import_id=record.id, source_row_index=0, original_description=description)
    session.add(raw)
    session.flush()
    tx = Transaction(raw_transaction_id=raw.id, account_id=account.id, transaction_date=date(2026, 3, 1),
                     normalized_description=description, amount_minor=-1000, currency="EUR",
                     transaction_type=TransactionType.EXPENSE, duplicate_fingerprint=description)
    session.add(tx)
    return tx


def test_built_once_until_something_is_committed(session):
    built, build = _counting()

    assert [remembered(session, "value", build) for _ in range(3)] == [1, 1, 1]
    assert built == [1]

    _account(session)  # commits
    assert remembered(session, "value", build) == 2
    assert remembered(session, "value", build) == 2


def test_each_name_has_its_own_value(session):
    assert remembered(session, "one", lambda: "a") == "a"
    assert remembered(session, "other", lambda: "b") == "b"
    assert remembered(session, "one", lambda: "never built") == "a"


def test_a_session_with_uncommitted_changes_gets_a_fresh_value_that_is_not_kept(session, engine):
    account = _account(session)
    built, build = _counting()
    assert remembered(session, "value", build) == 1

    _booking(session, account, "Shop")
    session.flush()  # written, not committed: only this session sees it
    assert remembered(session, "value", build) == 2
    assert remembered(session, "value", build) == 3  # built again each time, never kept

    with Session(engine) as other:  # everyone else still gets the value for the committed data
        assert remembered(other, "value", build) == 1

    session.rollback()
    assert remembered(session, "value", build) == 1  # as before: nothing was committed


def test_a_delete_statement_counts_as_an_uncommitted_change(session):
    account = _account(session)
    _booking(session, account, "Shop")
    session.commit()
    built, build = _counting()
    assert remembered(session, "value", build) == 1

    session.exec(delete(Transaction))  # no objects flushed: a statement
    assert remembered(session, "value", build) == 2

    session.commit()
    assert remembered(session, "value", build) == 3
    assert remembered(session, "value", build) == 3


def test_databases_do_not_share_what_is_remembered(session, tmp_path):
    assert remembered(session, "value", lambda: "this database") == "this database"

    other_engine = create_engine(f"sqlite:///{tmp_path / 'other.db'}")
    SQLModel.metadata.create_all(other_engine)
    with Session(other_engine) as other:
        assert remembered(other, "value", lambda: "the other one") == "the other one"
    other_engine.dispose()


def test_the_chains_follow_the_bookings(session):
    """chain_index is remembered — and still knows a chain as soon as its second branch is imported."""
    account = _account(session)
    _booking(session, account, "ROSSMANN KASSEL")
    session.commit()
    assert chain_index(session) == {}
    assert chain_index(session) is chain_index(session)  # the same object: not built again

    _booking(session, account, "ROSSMANN DRESDEN")
    session.commit()
    assert set(chain_index(session).values()) == {"ROSSMANN"}


def test_the_chains_stay_through_changes_that_are_not_about_payees(session):
    """Sorting a booking into a category is the most frequent change — and changes no chain."""
    account = _account(session)
    first = _booking(session, account, "ROSSMANN KASSEL")
    _booking(session, account, "ROSSMANN DRESDEN")
    session.commit()
    chains = chain_index(session)
    assert set(chains.values()) == {"ROSSMANN"}

    first.category = "Shopping"
    first.needs_review = False
    session.add(first)
    session.commit()
    assert chain_index(session) is chains  # not read from every booking again

    first.merchant = "Rossmann"  # a payee text changed: now it is
    session.add(first)
    session.commit()
    assert chain_index(session) is not chains

    chains = chain_index(session)
    session.exec(delete(Transaction).where(Transaction.id == first.id))  # a statement: may touch anything
    session.commit()
    assert chain_index(session) is not chains
    assert chain_index(session) == {}  # one branch left: no chain


def test_a_value_about_everything_is_built_again_after_any_commit(session):
    account = _account(session)
    tx = _booking(session, account, "Shop")
    session.commit()
    built, build = _counting()
    assert remembered(session, "about everything", build) == 1
    assert remembered(session, "about payees", build, payees_only=True) == 2

    tx.category = "Shopping"
    session.add(tx)
    session.commit()
    assert remembered(session, "about everything", build) == 3
    assert remembered(session, "about payees", build, payees_only=True) == 2
