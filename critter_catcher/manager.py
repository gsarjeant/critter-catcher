import asyncio
import logging
import signal
from dataclasses import dataclass
from pyunifiprotect import ProtectApiClient
from typing import Callable
from pyunifiprotect import ProtectApiClient
from typing import Callable, List
from critter_catcher.event_processor import (
    get_callback_and_iterator,
    process,
    EventCamera,
)


logger = logging.getLogger(__name__)


# Move cameras definition here and just store the list of cameras in the config instead of the list of names
@dataclass
class Config:
    host: str
    port: int
    username: str
    password: str
    verify_ssl: bool
    download_dir: str
    ignore_camera_names: str
    verbose: bool


def _make_camera_list(
    protect: ProtectApiClient, ignore_camera_names: List[str]
) -> List[EventCamera]:
    return [
        EventCamera(
            id=camera.id, name=camera.name, ignore=(camera.name in ignore_camera_names)
        )
        for camera in protect.bootstrap.cameras.values()
    ]


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


async def start(config: Config) -> None:

    logger.debug(f"Verify SSL: {config.verify_ssl}")
    # convert the comma-delimited list of ignored camera names to a list
    # (empty list if no cameras are ignored)
    ignore_camera_names = (
        config.ignore_camera_names.split(",") if config.ignore_camera_names else []
    )

    protect = ProtectApiClient(
        config.host,
        config.port,
        config.username,
        config.password,
        verify_ssl=config.verify_ssl,
    )
    await protect.update()
    config.protect = protect

    cameras = _make_camera_list(protect, ignore_camera_names)
    # subscribe to the Unifi Protect websocket, and call the event processor when messages are received.
    event_callback, events = get_callback_and_iterator(cameras)
    unsub = protect.subscribe_websocket(event_callback)

    # start async tasks and run until all tasks end (in this case, are cancelled)
    # asyncio.TaskGroup requires python 3.11+
    async with asyncio.TaskGroup() as tg:
        tasks = []
        tasks.append(
            tg.create_task(monitor_websocket_connection(protect, unsub, event_callback))
        )
        tasks.append(
            tg.create_task(process(events, protect, cameras, config.download_dir))
        )

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


async def monitor_websocket_connection(
    protect: ProtectApiClient, unsub: Callable[[], None], callback: Callable[[], None]
) -> None:
    while True:
        await asyncio.sleep(60)

        logger.debug("Checking connection to websocket")
        if protect.check_ws():
            logger.debug("Connected to Unifi Protect")
        else:
            logger.warning("Lost connection to Unifi Protect. Cleaning up connection.")

            unsub()
            await protect.close_session()

            while True:
                logger.warning("Attempting to reconnect to Unifi Protect.")

                try:
                    logger.warning("Reinitializing protect client")
                    await protect.update(force=True)
                    if protect.check_ws():
                        logger.warning("Resubscribing to websocket")
                        unsub = protect.subscribe_websocket(callback)
                        break
                    else:
                        logger.warning("Unable to reconnect to Unifi Protect.")
                except Exception as e:
                    logger.warning(
                        "Unexpected exception trying to reconnnect to Unifi Protect"
                    )
                    logger.exception(e)

                await asyncio.sleep(10)

            logger.warning("Reconnected to Unifi Protect.")
