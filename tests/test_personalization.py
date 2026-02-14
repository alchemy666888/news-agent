from news_agent.personalization import PersonalizationModel


def test_personalization_weight_moves_with_feedback() -> None:
    p = PersonalizationModel()
    assert p.weight_for("social") == 1.0

    p.record_engagement("social")
    p.record_engagement("social")
    assert p.weight_for("social") > 1.0

    p.record_dismissal("social")
    p.record_dismissal("social")
    p.record_dismissal("social")
    assert p.weight_for("social") < 1.0
