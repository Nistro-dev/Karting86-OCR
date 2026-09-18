from apex_ocr.ocr.calibration import aggregate_sample_validity, find_most_robust_threshold


def test_picks_center_of_longest_contiguous_valid_run():
    validity = {40: False, 45: False, 50: True, 55: True, 60: True, 65: True, 70: False, 75: True, 80: False}
    # plage valide contiguë la plus longue : 50-65 (4 valeurs) -> centre = 60
    assert find_most_robust_threshold(validity) == 60


def test_returns_none_if_nothing_valid():
    assert find_most_robust_threshold({40: False, 45: False}) is None


def test_returns_none_for_empty_input():
    assert find_most_robust_threshold({}) is None


def test_single_valid_value():
    assert find_most_robust_threshold({100: True}) == 100


def test_prefers_a_wide_plateau_over_an_isolated_lucky_hit():
    validity = {40: True, 45: False, 50: True, 55: True, 60: True, 65: True, 70: True, 75: False}
    assert find_most_robust_threshold(validity) == 60  # centre de 50-70


def test_aggregate_requires_majority_of_samples_not_a_single_lucky_one():
    thresholds = [90, 100, 110, 150]
    samples = [
        {90, 100, 110},  # 150 rate cet échantillon
        {90, 100, 110, 150},
        {90, 100, 110},
        {150},  # échantillon bruité où seul 150 "marche" par chance
    ]
    validity = aggregate_sample_validity(samples, thresholds, min_ratio=0.7)
    assert validity == {90: True, 100: True, 110: True, 150: False}


def test_aggregate_empty_samples_returns_all_invalid():
    assert aggregate_sample_validity([], [90, 100], min_ratio=0.7) == {90: False, 100: False}
