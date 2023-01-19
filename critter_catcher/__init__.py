import asyncio
import logging
import os
import signal
from critter_catcher.unifi_protect_client_manager import UnifiProtectClientManager
from critter_catcher.unifi_protect_event_processor import (
    EventCamera,
    UnifiProtectEventProcessor,
)

logging.basicConfig(
    encoding="utf-8",
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %I:%M:%S %p",
    level=logging.DEBUG,
)
logger = logging.getLogger(__name__)


async def shutdown(signal, cancel_tasks) -> None:
    logger.info(f"Received signal {signal.name}")
    tasks = [t for t in cancel_tasks if t is not asyncio.current_task()]

    logger.debug(f"Cancelling {len(tasks)} pending tasks")
    for task in tasks:
        task.cancel()


async def main() -> None:
    host = os.environ["UDMP_HOST"]
    port = os.environ["UDMP_PORT"]
    username = os.environ["UDMP_USERNAME"]
    password = os.environ["UDMP_PASSWORD"]
    verify_ssl = os.environ["UDMP_VERIFY_SSL"] == "true"
    download_dir = os.environ["DOWNLOAD_DIR"]
    ignore_camera_names = os.environ.get("IGNORE_CAMERA_NAMES")

    # convert the comma-delimited list of ignored camera names to a list
    # (empty list if no cameras are ignored)
    ignore_camera_names = ignore_camera_names.split(",") if ignore_camera_names else []

    # Initialize the Unifi Protect API Client.
    protect_client_manager = UnifiProtectClientManager(
        host=host,
        port=port,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
    )
    await protect_client_manager.initialize()

    # Query the API client and inspect ignore_camera_names
    # to generate a list of EventCameras to pass to the event processor
    event_cameras = [
        EventCamera(id=id, name=name, ignore=(name in ignore_camera_names))
        for id, name in protect_client_manager.cameras.items()
    ]

    # Initialize the event processor
    protect_event_processor = UnifiProtectEventProcessor(event_cameras, download_dir)

    # subscribe to the Unifi Protect websocket, and call the event processor when messages are received.
    protect_client_manager.subscribe(protect_event_processor.process_event)

    # start async tasks and run until all tasks end (in this case, are cancelled)
    # asyncio.TaskGroup requires python 3.11+
    async with asyncio.TaskGroup() as tg:
        monitor_task = tg.create_task(
            protect_client_manager.monitor_websocket_connection()
        )
        download_task = tg.create_task(protect_event_processor.capture_event_video())

        # We need to keep track of the tasks in the task group,
        # so that we cancel only those tasks when a signal is caught.
        #
        # (The pyunifiprotect library creates its own tasks and expects to be able to handle them itself on shutdown)
        tasks = [monitor_task, download_task]

        # Set up signal handlers
        loop = asyncio.get_event_loop()
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)

        for s in signals:
            loop.add_signal_handler(
                s,
                lambda s=s: tg.create_task(shutdown(s, tasks)),
            )

    logger.info("All tasks cancelled. Shutting down.")
    await protect_client_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
