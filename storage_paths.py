import os


def get_data_dir() -> str:
    """Return the configured data directory, or empty string for legacy mode."""
    return os.environ.get("DATA_DIR", "")


def get_sessions_dir() -> str:
    """Return the sessions directory path.

    Does NOT auto-create the directory; callers are responsible for
    ensuring it exists (matching the original ICloudSession behaviour).
    """
    base = get_data_dir()
    return os.path.join(base, "sessions") if base else "sessions"


def get_emails_file(account: str) -> str:
    """Return the email history file path for a given account."""
    base = get_data_dir()
    filename = f"emails-{account}.txt"
    return os.path.join(base, filename) if base else filename
