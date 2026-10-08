"""Setup helpers. Run the Etsy wizard with: python -m app.setup.etsy_wizard"""


def run_wizard() -> int:
    from app.setup.etsy_wizard import main

    return main()


__all__ = ["run_wizard"]
