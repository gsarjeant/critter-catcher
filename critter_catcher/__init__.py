import asyncio
import logging
import os
import signal
from pyunifiprotect import ProtectApiClient
from typing import Callable, List
from critter_catcher.unifi_protect_event_processor import (
    get_event_callback_and_processor,
    monitor_websocket_connection,
)


logging.basicConfig(
    encoding="utf-8",
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %I:%M:%S %p",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _cancel_tasks(signal: signal, tasks_to_cancel: List[asyncio.Task]) -> None:
    logger.info(f"Received signal {signal.name}")
    tasks = [t for t in tasks_to_cancel if t is not asyncio.current_task()]

    logger.debug(f"Cancelling {len(tasks)} pending tasks")
    for task in tasks:
        task.cancel()


async def _stop(protect: ProtectApiClient, unsub: Callable[[], None]) -> None:
    # Unsubscribe from the Unifi Protect websocket
    logger.info("Unsubscribing from websocket")
    unsub()

    # Close Unifi Protect session
    if protect is not None:
        logger.info("Closing session")
        await protect.close_session()
    else:
        logger.warning("Client was destroyed before closing session.")


async def _start(
    username, password, host, port, verify_ssl, download_dir, ignore_camera_names
) -> None:

    logger.debug(f"Verify SSL: {verify_ssl}")
    # convert the comma-delimited list of ignored camera names to a list
    # (empty list if no cameras are ignored)
    ignore_camera_names = ignore_camera_names.split(",") if ignore_camera_names else []

    protect = ProtectApiClient(host, port, username, password, verify_ssl=verify_ssl)
    await protect.update()

    # subscribe to the Unifi Protect websocket, and call the event processor when messages are received.
    enqueue_event, process_events = get_event_callback_and_processor(
        protect, ignore_camera_names, download_dir
    )
    unsub = protect.subscribe_websocket(enqueue_event)

    # start async tasks and run until all tasks end (in this case, are cancelled)
    # asyncio.TaskGroup requires python 3.11+
    async with asyncio.TaskGroup() as tg:
        tasks = []
        tasks.append(
            tg.create_task(monitor_websocket_connection(protect, unsub, enqueue_event))
        )
        tasks.append(tg.create_task(process_events()))

        # Set up signal handlers
        # NOTE: I'm explicitly cancelling only those tasks that I added in the task group.
        #       The pyunifiprotect library creates its own tasks and expects to be able to handle them itself on shutdown.
        loop = asyncio.get_event_loop()
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)

        for s in signals:
            loop.add_signal_handler(
                s,
                lambda s=s: tg.create_task(_cancel_tasks(s, tasks)),
            )

    # Once all tasks in the task group are cancelled (generally on receipt of a handled signal),
    # the task group will exit. At that point, clean things up and end the process.
    logger.info("All managed tasks cancelled. Shutting down.")
    await _stop(protect, unsub)


def main(
    username, password, host, port, verify_ssl, download_dir, ignore_camera_names
) -> None:
    asyncio.run(
        _start(
            username,
            password,
            host,
            port,
            verify_ssl,
            download_dir,
            ignore_camera_names,
        )
    )


if __name__ == "__main__":
    username = os.environ["UFP_USERNAME"]
    password = os.environ["UFP_PASSWORD"]
    host = os.environ["UFP_ADDRESS"]
    port = os.environ["UFP_PORT"]
    verify_ssl = os.environ.get("UFP_SSL_VERIFY", False)
    download_dir = os.environ["CC_DOWNLOAD_DIR"]
    ignore_camera_names = os.environ.get("CC_IGNORE_CAMERA_NAMES")
    main(username, password, host, port, verify_ssl, download_dir, ignore_camera_names)
