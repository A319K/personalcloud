"""
settings.py — Loads and validates all configuration from the .env file.

Uses python-dotenv to populate environment variables and exposes a single
`settings` singleton used throughout the application.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)


class Settings:
    """Central settings object populated from environment variables."""

    # Storage backend: "r2" or "minio"
    STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "minio").lower()

    # Cloudflare R2
    R2_ACCOUNT_ID: str = os.getenv("R2_ACCOUNT_ID", "")
    R2_ACCESS_KEY_ID: str = os.getenv("R2_ACCESS_KEY_ID", "")
    R2_SECRET_ACCESS_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
    R2_BUCKET_NAME: str = os.getenv("R2_BUCKET_NAME", "personalcloud")

    # MinIO
    MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
    MINIO_ACCESS_KEY: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    MINIO_BUCKET_NAME: str = os.getenv("MINIO_BUCKET_NAME", "personalcloud")

    # Database (Neon PostgreSQL with pgvector)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # File watching
    WATCH_FOLDER: str = os.getenv("WATCH_FOLDER", str(Path.home() / "Documents"))
    SUPPORTED_EXTENSIONS: list[str] = [
        ext.strip()
        for ext in os.getenv(
            "SUPPORTED_EXTENSIONS",
            ".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.xlsx,.csv",
        ).split(",")
    ]

    # Paths to exclude from syncing and indexing (comma-separated directory names / patterns)
    EXCLUDE_PATHS: list[str] = [
        p.strip()
        for p in os.getenv(
            "EXCLUDE_PATHS",
            "node_modules,.venv,venv,__pycache__,.git,dist,build,.next,.egg-info",
        ).split(",")
        if p.strip()
    ]

    # API server
    API_HOST: str = os.getenv("API_HOST", "127.0.0.1")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    def validate(self) -> list[str]:
        """
        Validate that all required config values are present.

        Returns a list of human-readable error messages (empty list = valid).
        """
        errors: list[str] = []

        if not self.DATABASE_URL:
            errors.append("DATABASE_URL is not set. Run `personalcloud init` first.")

        if self.STORAGE_BACKEND == "r2":
            for field in ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME"]:
                if not getattr(self, field):
                    errors.append(f"{field} is required when STORAGE_BACKEND=r2")
        elif self.STORAGE_BACKEND == "minio":
            for field in ["MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET_NAME"]:
                if not getattr(self, field):
                    errors.append(f"{field} is required when STORAGE_BACKEND=minio")
        else:
            errors.append(f"Unknown STORAGE_BACKEND '{self.STORAGE_BACKEND}'. Must be 'r2' or 'minio'.")

        return errors

    @property
    def watch_folder_path(self) -> Path:
        """Return the WATCH_FOLDER as an expanded absolute Path."""
        return Path(self.WATCH_FOLDER).expanduser().resolve()

    @property
    def bucket_name(self) -> str:
        """Return the bucket name for the active storage backend."""
        if self.STORAGE_BACKEND == "r2":
            return self.R2_BUCKET_NAME
        return self.MINIO_BUCKET_NAME


# Global singleton — import this everywhere
settings = Settings()
