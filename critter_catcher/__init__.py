import logging
from critter_catcher import cli

logging.basicConfig(
    encoding="utf-8",
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %I:%M:%S %p %Z",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    cli.cli()


if __name__ == "__main__":
    main()
