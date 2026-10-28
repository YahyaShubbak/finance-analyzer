from datetime import date

from app.normalization.transfers import TransferCandidate, find_transfer_pairs


def test_matching_transfer_pair_detected():
    candidates = [
        TransferCandidate(id=1, account_id=1, transaction_date=date(2026, 3, 15), amount_minor=-50000),
        TransferCandidate(id=2, account_id=2, transaction_date=date(2026, 3, 16), amount_minor=50000),
    ]
    pairs = find_transfer_pairs(candidates)
    assert pairs == [(1, 2)]


def test_same_account_not_matched_as_transfer():
    # Same amount, opposite sign, but same account -> not a transfer (e.g. refund)
    candidates = [
        TransferCandidate(id=1, account_id=1, transaction_date=date(2026, 3, 15), amount_minor=-5000),
        TransferCandidate(id=2, account_id=1, transaction_date=date(2026, 3, 15), amount_minor=5000),
    ]
    assert find_transfer_pairs(candidates) == []


def test_gap_too_large_not_matched():
    candidates = [
        TransferCandidate(id=1, account_id=1, transaction_date=date(2026, 3, 1), amount_minor=-5000),
        TransferCandidate(id=2, account_id=2, transaction_date=date(2026, 3, 20), amount_minor=5000),
    ]
    assert find_transfer_pairs(candidates) == []


def test_unrelated_transactions_not_matched():
    candidates = [
        TransferCandidate(id=1, account_id=1, transaction_date=date(2026, 3, 1), amount_minor=-4567),
        TransferCandidate(id=2, account_id=2, transaction_date=date(2026, 3, 1), amount_minor=250000),
    ]
    assert find_transfer_pairs(candidates) == []


def test_each_transaction_used_at_most_once():
    candidates = [
        TransferCandidate(id=1, account_id=1, transaction_date=date(2026, 3, 1), amount_minor=-5000),
        TransferCandidate(id=2, account_id=2, transaction_date=date(2026, 3, 1), amount_minor=5000),
        TransferCandidate(id=3, account_id=3, transaction_date=date(2026, 3, 2), amount_minor=5000),
    ]
    pairs = find_transfer_pairs(candidates)
    assert len(pairs) == 1
    used_ids = {i for pair in pairs for i in pair}
    assert len(used_ids) == 2


def test_amounts_must_match_exactly_without_iban_evidence():
    # A €0.50 difference could just as well be an unrelated refund.
    candidates = [
        TransferCandidate(id=1, account_id=1, transaction_date=date(2026, 3, 1), amount_minor=-50000),
        TransferCandidate(id=2, account_id=2, transaction_date=date(2026, 3, 2), amount_minor=49950),
    ]
    assert find_transfer_pairs(candidates) == []


def test_a_difference_is_never_paired_even_between_own_accounts():
    """500.00 out, 499.50 in (a wire fee): as a pair, the fee would vanish from every total."""
    candidates = [
        TransferCandidate(id=1, account_id=1, transaction_date=date(2026, 3, 1), amount_minor=-50000,
                          counterparty_iban="DE02120300000000202051"),
        TransferCandidate(id=2, account_id=2, transaction_date=date(2026, 3, 2), amount_minor=49950),
    ]
    assert find_transfer_pairs(candidates, account_ibans={2: "DE02120300000000202051"}) == []


def test_payments_to_and_from_third_parties_are_no_transfer():
    """Rent to the landlord's IBAN, a friend repaying the same amount into the savings account."""
    candidates = [
        TransferCandidate(id=1, account_id=1, transaction_date=date(2026, 3, 3), amount_minor=-50000,
                          counterparty_iban="DE02500105170137075030"),
        TransferCandidate(id=2, account_id=2, transaction_date=date(2026, 3, 3), amount_minor=50000,
                          counterparty_iban="DE12500105170648489890"),
    ]
    ibans = {1: "DE89370400440532013000", 2: "DE02120300000000202051"}
    assert find_transfer_pairs(candidates, account_ibans=ibans) == []
    # naming each other's IBAN: a transfer
    candidates[0] = TransferCandidate(id=1, account_id=1, transaction_date=date(2026, 3, 3), amount_minor=-50000,
                                      counterparty_iban="DE02120300000000202051")
    candidates[1] = TransferCandidate(id=2, account_id=2, transaction_date=date(2026, 3, 3), amount_minor=50000,
                                      counterparty_iban="DE89370400440532013000")
    assert find_transfer_pairs(candidates, account_ibans=ibans) == [(1, 2)]


def test_iban_evidence_does_not_excuse_large_difference():
    candidates = [
        TransferCandidate(id=1, account_id=1, transaction_date=date(2026, 3, 1), amount_minor=-50000,
                          counterparty_iban="DE02120300000000202051"),
        TransferCandidate(id=2, account_id=2, transaction_date=date(2026, 3, 2), amount_minor=45000),  # €50 off
    ]
    assert find_transfer_pairs(candidates, account_ibans={2: "DE02120300000000202051"}) == []


def test_different_currencies_never_paired():
    candidates = [
        TransferCandidate(id=1, account_id=1, transaction_date=date(2026, 3, 1), amount_minor=-90000, currency="EUR"),
        TransferCandidate(id=2, account_id=2, transaction_date=date(2026, 3, 1), amount_minor=90000, currency="USD"),
    ]
    assert find_transfer_pairs(candidates) == []


def test_positive_side_with_two_equal_partners_is_ambiguous():
    # Two outgoing -500 from different accounts, one incoming +500: the
    # incoming side can't tell which one it belongs to.
    candidates = [
        TransferCandidate(id=1, account_id=1, transaction_date=date(2026, 3, 1), amount_minor=-50000),
        TransferCandidate(id=2, account_id=2, transaction_date=date(2026, 3, 1), amount_minor=-50000),
        TransferCandidate(id=3, account_id=3, transaction_date=date(2026, 3, 1), amount_minor=50000),
    ]
    assert find_transfer_pairs(candidates) == []


def test_ambiguous_amount_matches_not_silently_chosen():
    # Two equally-good candidates within tolerance -> ambiguous, skip both.
    candidates = [
        TransferCandidate(id=1, account_id=1, transaction_date=date(2026, 3, 1), amount_minor=-50000),
        TransferCandidate(id=2, account_id=2, transaction_date=date(2026, 3, 1), amount_minor=50000),
        TransferCandidate(id=3, account_id=3, transaction_date=date(2026, 3, 1), amount_minor=50000),
    ]
    assert find_transfer_pairs(candidates) == []
