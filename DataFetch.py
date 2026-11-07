"""Compatibility entry point for the CatChat messaging service."""
from catchat_server import app

if __name__ == "__main__":
    import os

    app.run(
        host=os.getenv("CATCHAT_HOST", "127.0.0.1"),
        port=int(os.getenv("CATCHAT_PORT", "7800")),
        threaded=True,
    )
