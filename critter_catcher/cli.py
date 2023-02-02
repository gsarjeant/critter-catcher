import asyncio
import click
import logging
from critter_catcher.manager import Config, start


@click.command()
@click.option(
    "--username",
    required=True,
    envvar="UFP_USERNAME",
    help="The username of the account that is used to connect to the Unifi controller. Must be a local account, NOT a Unifi account.",
)
@click.option(
    "--password",
    required=True,
    envvar="UFP_PASSWORD",
    help="The password of the account that is used to connect to the Unifi controller.",
)
@click.option(
    "--host",
    required=True,
    envvar="UFP_ADDRESS",
    help="The hostname or IP address of the Unifi controller.",
)
@click.option(
    "--port",
    default=443,
    envvar="UFP_PORT",
    help="The port to connect to on the Unifi controller.",
)
@click.option(
    "--verify-ssl",
    default=False,
    envvar="UFP_SSL_VERIFY",
    help="Whether or not to verify SSL when connecting to the Unifi controller. False if you're using the self-signed cert. True if you've installed your own cert.",
)
@click.option(
    "--download-dir",
    default="/data",
    envvar="CC_DOWNLOAD_DIR",
    help="Directory in which to save video from captured events.",
)
@click.option(
    "--ignore-camera-names",
    default=None,
    envvar="CC_IGNORE_CAMERA_NAMES",
    help="A list of cameras that will be excluded from event capture. The names match the names in the Unifi Protect application.",
)
# There's probably a slicker way to do this than by using datetimes and extracting the time,
# but this works without writing a custom class
@click.option(
    "--start-time",
    type=click.DateTime(formats=["%H:%M:%S"]),
    default="00:00:00",
    envvar="CC_START_TIME",
    help="The time each day to start recording. If unset, then recording starts at midnight.",
)
@click.option(
    "--end-time",
    type=click.DateTime(formats=["%H:%M:%S"]),
    default="11:59:59",
    envvar="CC_END_TIME",
    help="The time each day to end recording. If unset, then recording ends at 11:59:59 PM.",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    show_default=True,
    envvar="CC_VERBOSE",
    help="Increase logging verbosity (show debug messages).",
)
def cli(
    username,
    password,
    host,
    port,
    verify_ssl,
    download_dir,
    ignore_camera_names,
    start_time,
    end_time,
    verbose,
):
    logging.getLogger().setLevel(logging.INFO if not verbose else logging.DEBUG)

    logging.info(f"Start time: {start_time.time()}")
    logging.info(f"End time: {end_time.time()}")
    """Monitors a Unifi Controller for events from Unifi Protect and saves the event video to a local directory."""
    config = Config(
        host=host,
        port=port,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
        download_dir=download_dir,
        ignore_camera_names=ignore_camera_names,
        start_time=start_time.time(),
        end_time=end_time.time(),
        verbose=verbose,
    )
    asyncio.run(start(config))
