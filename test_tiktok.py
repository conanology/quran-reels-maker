"""Legacy manual verification entry point, intentionally inert during collection.

Live credentials, publishing, paid AI and shared production state are outside the
regression suite. Use the isolated tests in tests/ for synthetic validation.
"""
__test__ = False


def main():
    raise SystemExit("Legacy live verification is disabled. Run the isolated regression suite (python -m pytest tests); live integration requires a separately reviewed harness and explicit authorization.")


if __name__ == "__main__":
    main()
