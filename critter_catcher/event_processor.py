import asyncio
import logging
import pytz
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data import WSAction, WSSubscriptionMessage
from pyunifiprotect.data.nvr import Event
from pyunifiprotect.data.types import EventType
from typing import Callable, AsyncIterator, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class EventCamera:
    id: int
    name: str
    ignore: bool


def get_callback_and_iterator(
    cameras: List[EventCamera],
) -> Tuple[Callable[[], None], AsyncIterator]:
    event_queue = asyncio.Queue()
    logger.debug(f"cameras: {str([c for c in cameras])}")

    def enqueue_event(msg: WSSubscriptionMessage) -> None:
        obj = msg.new_obj

        if isinstance(obj, Event):
            if obj.type not in [EventType.MOTION, EventType.SMART_DETECT]:
                logger.debug(f"Unhandled event type: {obj.type}")
                return

            (event_id, camera_id) = obj.id.split("-")
            event_camera = next(filter(lambda ec: ec.id == camera_id, cameras))

            if event_camera.ignore:
                logger.debug(f"Event from ignored camera: {event_camera.name}")
                return

            if msg.action == WSAction.ADD:
                logger.debug(f"Event: {event_id} - Started (type: {obj.type})")
                logger.debug(f"Event: {event_id} - Camera: {event_camera.name}")
                return
            if msg.action != WSAction.UPDATE:
                return
            if obj.end is None:
                return

            event_queue.put_nowait(obj)
            logger.info(f"Event: {event_id} - enqueued.")

    async def get_events() -> AsyncIterator:
        while True:
            yield await event_queue.get()

    return enqueue_event, get_events()


async def process(
    events: AsyncIterator,
    protect: ProtectApiClient,
    cameras: List[EventCamera],
    download_dir: str,
):
    async for event in events:
        (event_id, camera_id) = event.id.split("-")
        event_camera = next(filter(lambda ec: ec.id == camera_id, cameras))

        logger.debug(f"Event: {event_id} - Event complete")
        logger.debug(
            f"Event: {event_id} - Consumed by task: {asyncio.current_task().get_name()}"
        )
        logger.debug(f"Event: {event_id} - Event Type: {event.type}")
        if event.type == EventType.SMART_DETECT:
            obj_dict = event.unifi_dict_to_dict(event.unifi_dict())
            # The API returns a list of smart detect types.
            # I've only ever seen one item in the list for any single event in practice,
            # but maybe you can get "Person" and "Package" or something like that.
            # Concatenate the list for logging purposes.
            smart_detect_types = ",".join(
                [sdt.value for sdt in obj_dict["smart_detect_types"]]
            )

            logger.debug(
                f"Event: {event_id} - Smart detect types: {smart_detect_types}"
            )

        event.start = event.start.replace(tzinfo=pytz.utc).astimezone(
            protect.bootstrap.nvr.timezone
        )
        event.end = event.end.replace(tzinfo=pytz.utc).astimezone(
            protect.bootstrap.nvr.timezone
        )

        logger.debug(f"Event: {event_id} - Camera: {event_camera.name}")
        logger.debug(
            f"Event: {event_id} - Start time: {event.start.date()} {event.start.time()}"
        )
        logger.debug(
            f"Event: {event_id} -   End time: {event.end.date()} {event.end.time()}"
        )

        time_since_event_ended = (
            datetime.utcnow().replace(tzinfo=timezone.utc) - event.end
        )
        sleep_time = (
            timedelta(seconds=5 * 1.5) - time_since_event_ended
        ).total_seconds()

        if sleep_time > 0:
            logger.info(
                f"  Sleeping ({sleep_time}s) to ensure clip is ready to download..."
            )
            await asyncio.sleep(sleep_time)

        logger.debug(f"Event: {event_id} - Downloading video...")

        display_camera_name = event_camera.name.replace(" ", "-")
        display_datetime = event.start.strftime("%Y%m%d-%H%M%S")
        event_filename = (
            f"{display_camera_name}-{display_datetime}-{event.type.value}.mp4"
        )
        output_file = f"{download_dir}/{event_filename}"

        async def callback(step: int, current: int, total: int) -> None:
            logger.debug(
                f"Downloading {total} bytes - Current chunk: {step}, total saved: {current}"
            )

        logger.debug("Confirming authentication ...")
        if not protect.is_authenticated():
            logger.warning(
                "Authentication has expired. Reauthenticating before attempting to fetch event video."
            )
            await protect.authenticate()

            if protect.is_authenticated():
                logger.info("Session is reuthenticated.")
            else:
                logger.error("Unexpected error reauthenticating. Skipping download.")
                break

        await event.get_video(output_file=output_file, progress_callback=callback)

        logger.info(f"Event: {event_id} - Video saved to {output_file}")
        logger.info(f"Event: {event_id} - Processed.")


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
