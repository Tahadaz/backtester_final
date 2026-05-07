from services.api.app.db import get_db
from services.api.app.routers.analytics import get_predictive_ability_leaderboard

db = next(get_db())
try:
    res = get_predictive_ability_leaderboard(engine_horizon="short", lookback_days=0, return_calc_method="open_to_open", db=db)
    print("Success:", len(res.rows))
except Exception as e:
    import traceback
    traceback.print_exc()
