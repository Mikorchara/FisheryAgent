"""Explicit offline-only entry point. No real-data/config/secret options."""
from .offline import main

if __name__ == '__main__':
    raise SystemExit(main())
