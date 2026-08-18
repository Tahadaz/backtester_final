from core.quant_core.edge_policy import passes_edge_policy


def _payload(**overrides):
    payload = {
        "edge_score": 50.0,
        "n": 30,
        "action_expected_return_net": 0.01,
        "action_expected_return_net_ci_lower": 0.001,
        "hit_ci_lower": 0.51,
        "mc_luck_pvalue_net_adj": 0.05,
        "label_shuffle_pvalue_net_adj": 0.05,
        "freshness_status": "passed",
        "proven_edge_net": True,
    }
    payload.update(overrides)
    return payload


def test_threshold_is_user_configurable() -> None:
    assert passes_edge_policy(_payload(edge_score=12.0), min_edge_score=10, required_conditions=[])
    assert not passes_edge_policy(_payload(edge_score=12.0), min_edge_score=20, required_conditions=[])


def test_each_condition_is_independently_selectable() -> None:
    assert passes_edge_policy(
        _payload(),
        min_edge_score=0,
        required_conditions=[
            "sample_size", "positive_expectancy", "positive_ci_lower", "hit_rate_ci",
            "mc_luck", "label_shuffle", "freshness", "proven_edge",
        ],
    )
    assert not passes_edge_policy(
        _payload(mc_luck_pvalue_net_adj=0.051),
        min_edge_score=0,
        required_conditions=["mc_luck"],
    )


def test_pit_provenance_field_names_are_supported() -> None:
    assert passes_edge_policy(
        {"edge_score": 25, "proof_n": 35, "expected_return_net": 0.02, "ci_lower_net": 0.001},
        min_edge_score=20,
        required_conditions=["sample_size", "positive_expectancy", "positive_ci_lower"],
    )
