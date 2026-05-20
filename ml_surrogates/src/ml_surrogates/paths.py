from pathlib import Path


def get_root() -> Path:
    current = Path(__file__).resolve().absolute()
    return next(parent for parent in current.parents if (parent / ".git").exists())
