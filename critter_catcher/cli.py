import click
import critter_catcher


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
    required=True,
    envvar="CC_DOWNLOAD_DIR",
    help="Directory in which to save video from captured events.",
)
@click.option(
    "--ignore-camera-names",
    default=None,
    envvar="CC_IGNORE_CAMERA_NAMES",
    help="A list of cameras that will be excluded from event capture. The names match the names in the Unifi Protect application.",
)
def cli(username, password, host, port, verify_ssl, download_dir, ignore_camera_names):
    critter_catcher.main(
        username,
        password,
        host,
        port,
        verify_ssl,
        download_dir,
        ignore_camera_names,
    )
