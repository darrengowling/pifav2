from backend.scoring import PerformanceStats, calculate_points


def test_calculate_points_basic():
    stats = PerformanceStats(runs=30, wickets=2, catches=1, stumpings=0, run_outs=1)
    assert calculate_points(stats) == 30 + 2*25 + 1*10 + 1*10


def test_calculate_points_with_bonuses():
    stats = PerformanceStats(runs=120, wickets=5, catches=0, stumpings=0, run_outs=0, century=True, five_wicket_haul=True)
    expected = 120 + 5*25 + 100 + 75
    assert calculate_points(stats) == expected
