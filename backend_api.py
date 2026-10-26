"""
backend_api.py — Campus Chat Backend entrypoint (wrapper around backend_api_original.py).
"""
from backend_api_original import *

if __name__ == "__main__":
    import os
    import atexit

    sync_interval_hours = int(os.getenv("SYNC_INTERVAL_HOURS", "6"))
    sync_enabled = os.getenv("SYNC_ENABLED", "true").lower() in ("true", "1", "yes")
    if sync_enabled and "sync_service_w4" in globals() and sync_service_w4:
        try:
            sync_service_w4.start_scheduler(interval_hours=sync_interval_hours)
            atexit.register(sync_service_w4.stop_scheduler)
            print(f"🔄 VJTI Website Sync Scheduler started (interval={sync_interval_hours}h)")
        except Exception as e:
            print(f"⚠️  Could not start VJTI Website Sync Scheduler: {e}")

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)