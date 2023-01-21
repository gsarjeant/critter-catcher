import asyncio
from datetime import datetime, timedelta, timezone
import logging
import pytz
from dataclasses import dataclass
from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data import WSAction, WSSubscriptionMessage
from pyunifiprotect.data.nvr import Event
from pyunifiprotect.data.types import EventType
from typing import Callable, Awaitable, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class EventCamera:
    id: int
    name: str
    ignore: bool


def _make_camera_list(
    protect: ProtectApiClient, ignore_camera_names: List[str]
) -> List[EventCamera]:
    return [
        EventCamera(
            id=camera.id, name=camera.name, ignore=(camera.name in ignore_camera_names)
        )
        for camera in protect.bootstrap.cameras.values()
    ]


def get_event_callback_and_processor(
    protect: ProtectApiClient, ignore_camera_names: List[str], download_dir: str
) -> Tuple[Callable[[], None], Awaitable]:
    event_queue = asyncio.Queue()
    cameras = _make_camera_list(protect, ignore_camera_names)
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

    async def process_events() -> None:
        while True:
            event = await event_queue.get()

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

            event_filename = f"{event_camera.name}-{event_id}-{event.type.value}.mp4"
            output_file = f"{download_dir}/{event_filename}"
            await event.get_video(output_file=output_file)

            logger.info(f"Event: {event_id} - Video saved to {output_file}")
            logger.info(f"Event: {event_id} - Processed.")

    return enqueue_event, process_events


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
