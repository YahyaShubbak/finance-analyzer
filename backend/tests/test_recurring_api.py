"""End-to-end tests for /api/recurring/*, exercising real imported data
through the actual pipeline (import -> normalization -> transfer
detection -> recurring detection), not hand-constructed rows."""
from __future__ import annotations

import io


def _create_account(client, name, account_type, currency="EUR"):
    r = client.post("/api/accounts", json={"name": name, "account_type": account_type, "currency": currency})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import_csv(client, filename, content: bytes, account_id: int):
    files = {"file": (filename, io.BytesIO(content), "text/csv")}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert preview.status_code == 200, preview.text
    p = preview.json()
    commit = client.post("/api/imports/commit", json={"staging_id": p["staging_id"], "account_id": account_id})
    assert commit.status_code == 200, commit.text
    return commit.json()


def test_monthly_recurring_series_detected_from_import(client):
    checking_id = _create_account(client, "Checking", "checking")
    _import_csv(
        client, "netflix.csv",
        b"Date,Description,Amount\n"
        b"2026-01-05,Netflix,-12.99\n"
        b"2026-02-05,Netflix,-12.99\n"
        b"2026-03-05,Netflix,-12.99\n"
        b"2026-04-05,Netflix,-12.99\n",
        checking_id,
    )

    r = client.get("/api/recurring/series")
    assert r.status_code == 200, r.text
    series = r.json()["series"]
    assert len(series) == 1
    item = series[0]
    assert item["interval"] == "monthly"
    assert item["sign"] == "expense"
    assert item["occurrence_count"] == 4
    assert item["last_amount_minor"] == -1299
    assert item["next_expected_date"] == "2026-05-05"
    assert item["currency"] == "EUR"


def test_duplicate_rows_excluded_from_occurrence_count(client):
    checking_id = _create_account(client, "Checking", "checking")
    _import_csv(
        client, "netflix1.csv",
        b"Date,Description,Amount\n"
        b"2026-01-05,Netflix,-12.99\n"
        b"2026-02-05,Netflix,-12.99\n"
        b"2026-03-05,Netflix,-12.99\n",
        checking_id,
    )
    # Re-import the same January row (plus an unrelated row so the file
    # checksum differs and this isn't rejected as a whole-file duplicate)
    # -> the January row should be flagged an exact duplicate and excluded.
    _import_csv(
        client, "netflix1_again.csv",
        b"Date,Description,Amount\n"
        b"2026-01-05,Netflix,-12.99\n"
        b"2026-01-06,Unrelated Row,-1.00\n",
        checking_id,
    )

    series = client.get("/api/recurring/series").json()["series"]
    netflix = [s for s in series if s["key"] == "netflix"]
    assert len(netflix) == 1
    assert netflix[0]["occurrence_count"] == 3


def test_transfer_pair_not_reported_as_recurring(client):
    """A recurring monthly transfer between the user's own accounts (e.g.
    a savings sweep) must not show up as a 'recurring payment' — it's
    already excluded from income/expense accounting as a transfer, and
    recurring detection must agree, not double-report it."""
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")

    for month_day in ["2026-01-10", "2026-02-10", "2026-03-10"]:
        _import_csv(
            client, f"checking_out_{month_day}.csv",
            f"Date,Description,Amount\n{month_day},Monthly Savings Sweep,-20000.00\n".encode(),
            checking_id,
        )
    for month_day in ["2026-01-11", "2026-02-11", "2026-03-11"]:
        _import_csv(
            client, f"savings_in_{month_day}.csv",
            f"Date,Description,Amount\n{month_day},Monthly Savings Sweep,20000.00\n".encode(),
            savings_id,
        )

    rerun = client.post("/api/transfers/rerun-detection")
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["pairs_matched"] == 3

    series = client.get("/api/recurring/series").json()["series"]
    keys = [s["key"] for s in series]
    assert "monthly savings sweep" not in keys


def test_archived_account_excluded_from_recurring_series(client):
    checking_id = _create_account(client, "Checking", "checking")
    _import_csv(
        client, "netflix.csv",
        b"Date,Description,Amount\n"
        b"2026-01-05,Netflix,-12.99\n"
        b"2026-02-05,Netflix,-12.99\n"
        b"2026-03-05,Netflix,-12.99\n",
        checking_id,
    )
    assert client.get("/api/recurring/series").json()["series"] != []

    client.patch(f"/api/accounts/{checking_id}", json={"is_archived": True})
    assert client.get("/api/recurring/series").json()["series"] == []


def test_forecast_sums_recurring_and_baseline(client):
    checking_id = _create_account(client, "Checking", "checking")
    _import_csv(
        client, "netflix.csv",
        b"Date,Description,Amount\n"
        b"2026-01-05,Netflix,-12.99\n"
        b"2026-02-05,Netflix,-12.99\n"
        b"2026-03-05,Netflix,-12.99\n"
        b"2026-04-05,Netflix,-12.99\n",
        checking_id,
    )

    r = client.get("/api/recurring/forecast", params={"months": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["months"] == 2
    assert len(body["points"]) == 2
    for point in body["points"]:
        assert point["projected_net_minor"] == point["recurring_net_minor"] + point["baseline_net_minor"]


def test_forecast_invalid_months_returns_422(client):
    assert client.get("/api/recurring/forecast", params={"months": 0}).status_code == 422
    assert client.get("/api/recurring/forecast", params={"months": 25}).status_code == 422


def test_empty_database_returns_empty_results_not_error(client):
    series = client.get("/api/recurring/series")
    assert series.status_code == 200
    assert series.json()["series"] == []

    forecast = client.get("/api/recurring/forecast")
    assert forecast.status_code == 200
    body = forecast.json()
    assert body["series_count"] == 0
    assert len(body["points"]) == 3
    for point in body["points"]:
        assert point["projected_net_minor"] == 0
