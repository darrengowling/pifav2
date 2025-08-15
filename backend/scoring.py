from pydantic import BaseModel

class PerformanceStats(BaseModel):
    runs: int = 0
    wickets: int = 0
    catches: int = 0
    stumpings: int = 0
    run_outs: int = 0
    half_century: bool = False
    century: bool = False
    five_wicket_haul: bool = False

# Default point values
RUN_POINT = 1
WICKET_POINT = 25
CATCH_POINT = 10
STUMPING_POINT = 15
RUN_OUT_POINT = 10
HALF_CENTURY_BONUS = 50
CENTURY_BONUS = 100
FIVE_WICKET_BONUS = 75


def calculate_points(stats: PerformanceStats) -> int:
    """Calculate fantasy points for a player's performance."""
    points = 0
    points += stats.runs * RUN_POINT
    points += stats.wickets * WICKET_POINT
    points += stats.catches * CATCH_POINT
    points += stats.stumpings * STUMPING_POINT
    points += stats.run_outs * RUN_OUT_POINT
    if stats.century:
        points += CENTURY_BONUS
    elif stats.half_century:
        points += HALF_CENTURY_BONUS
    if stats.five_wicket_haul:
        points += FIVE_WICKET_BONUS
    return points
