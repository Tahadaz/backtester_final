from services.api.app.db import get_db
from services.api.app import models

db = next(get_db())
print('ScoreHistory rows:', db.query(models.SignalScoreHistory).count())
