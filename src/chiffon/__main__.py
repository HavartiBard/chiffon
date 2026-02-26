"""Entry point for python -m chiffon."""

from .cli import main

if __name__ == "__main__":
    # Pass command line arguments excluding the module name
    import sys

    main(sys.argv[1:])
