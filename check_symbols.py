from services.api.app.db import get_db
from services.api.app import models

db = next(get_db())
print('WFO:', db.query(models.WfoSignalSummary.symbol).count())
print('Engine:', db.query(models.SignalEngineGlobalResult.symbol).count())
print('StockMaster:', db.query(models.StockMaster.symbol).count())
