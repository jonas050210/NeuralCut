"""Allow `python -m neuralcut` to start the application."""

from neuralcut.main import main

if __name__ == "__main__":
    raise SystemExit(main())
