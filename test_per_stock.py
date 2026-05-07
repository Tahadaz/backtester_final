import traceback
from services.api.app.db import get_db
from services.api.app.routers.analytics import get_predictive_ability

db = next(get_db())
try:
    res = get_predictive_ability(
        symbol="ATW", source="engine_expanded", horizon="short",
        categories=None, fwd_horizons=None, lookback_days=0,
        return_calc_method="open_to_open", db=db,
    )
    print("Success:", len(res.cells), "cells, n_obs:", res.n_obs)
except Exception:
    traceback.print_exc()
