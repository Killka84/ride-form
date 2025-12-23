import os
from typing import Optional

from dotenv import load_dotenv
import uvicorn


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    v = value.strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    return default


def main() -> None:
    load_dotenv()

    host = os.getenv("UVICORN_HOST", "127.0.0.1")
    port = int(os.getenv("UVICORN_PORT", "8000"))
    reload = _parse_bool(os.getenv("UVICORN_RELOAD"), default=False)

    ssl_certfile = os.getenv("UVICORN_SSL_CERTFILE") or None
    ssl_keyfile = os.getenv("UVICORN_SSL_KEYFILE") or None
    if bool(ssl_certfile) ^ bool(ssl_keyfile):
        raise SystemExit("Set both UVICORN_SSL_CERTFILE and UVICORN_SSL_KEYFILE (or neither).")

    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=reload,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )


if __name__ == "__main__":
    main()

