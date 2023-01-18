import asyncio
import logging
import os
from critter_catcher.unifi_protect_client_manager import UnifiProtectClientManager
from critter_catcher.unifi_protect_event_processor import (
    EventCamera,
    UnifiProtectEventProcessor,
)

logging.basicConfig(
    encoding="utf-8",
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %I:%M:%S %p",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def main() -> None:

    try:
        host = os.environ["UDMP_HOST"]
        port = os.environ["UDMP_PORT"]
        username = os.environ["UDMP_USERNAME"]
        password = os.environ["UDMP_PASSWORD"]
        verify_ssl = os.environ["UDMP_VERIFY_SSL"] == "true"
        download_dir = os.environ["DOWNLOAD_DIR"]
        ignore_camera_names = os.environ.get("IGNORE_CAMERA_NAMES")

        # convert the comma-delimited list of ignored camera names to a list
        # (empty list if no cameras are ignored)
        ignore_camera_names = (
            ignore_camera_names.split(",") if ignore_camera_names else []
        )

        # Initialize the Unifi Protect API Client.
        protect_client_manager = UnifiProtectClientManager(
            host=host,
            port=port,
            username=username,
            password=password,
            verify_ssl=verify_ssl,
        )
        protect_api_client = await protect_client_manager.initialize()

        # Query the API client and inspect ignore_camera_names
        # to generate a list of EventCameras to pass to the event processor
        event_cameras = [
            EventCamera(id=id, name=name, ignore=(name in ignore_camera_names))
            for id, name in protect_client_manager.cameras.items()
        ]
        #        ignore_camera_ids = [
        #            id
        #            for id, name in protect_client_manager.cameras.items()
        #            if name in ignore_camera_names
        #        ]

        # Initialize the event processor
        protect_event_processor = UnifiProtectEventProcessor(
            protect_api_client, event_cameras, download_dir
        )

        # subscribe to the Unifi Protect websocket, and call the event processor when messages are received.
        protect_client_manager.subscribe(protect_event_processor.process_event)

        # start async tasks and run until interrupted
        # asyncio.TaskGroup requires python 3.11+
        async with asyncio.TaskGroup() as tg:
            websocket_task = tg.create_task(
                protect_client_manager.monitor_websocket_connection()
            )
            download_task = tg.create_task(
                protect_event_processor.capture_event_video()
            )

    except asyncio.CancelledError:
        logger.info("Done listening. Unsubscribing.")
        await protect_client_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
