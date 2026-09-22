"""Migrate, seed and start the same backend image locally or on a managed host."""

import os
import subprocess


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    subprocess.run(["python", "-m", "app.seed"], check=True)
    os.execvp(
        "uvicorn",
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(port), "--no-proxy-headers"],
    )


if __name__ == "__main__":
    main()
