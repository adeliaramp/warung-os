from analytics.classifier import classify


def test_classify_smooth():
    assert classify(1.0, 0.3) == "smooth"


def test_classify_erratic():
    assert classify(1.0, 0.6) == "erratic"


def test_classify_intermittent():
    assert classify(1.5, 0.3) == "intermittent"


def test_classify_lumpy():
    assert classify(1.5, 0.6) == "lumpy"
