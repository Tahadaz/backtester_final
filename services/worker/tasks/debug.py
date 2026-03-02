import os
def ping_job():
    return {"pid": os.getpid(), "ok": True}
