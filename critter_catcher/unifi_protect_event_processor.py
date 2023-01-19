import asyncio
import logging
from dataclasses import dataclass
from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data import WSAction, WSSubscriptionMessage
from pyunifiprotect.data.nvr import Event
from pyunifiprotect.data.types import EventType
from typing import AsyncIterator, List

logger = logging.getLogger(__name__)


@dataclass
class EventCamera:
    id: int
    name: str
    ignore: bool


def _make_camera_list(protect: ProtectApiClient, ignore_camera_names: List[str]):
    return [
        EventCamera(
            id=camera.id, name=camera.name, ignore=(camera.name in ignore_camera_names)
        )
        for camera in protect.bootstrap.cameras.values()
    ]


def get_event_callback_and_processor(
    protect: ProtectApiClient, ignore_camera_names: List[str], download_dir: str
):
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

            logger.debug(f"Event: {event_id} - Camera: {event_camera.name}")
            logger.debug(
                f"Event: {event_id} - Start time (UTC): {event.start.date()} {event.start.time()}"
            )
            logger.debug(
                f"Event: {event_id} -   End time (UTC): {event.end.date()} {event.end.time()}"
            )
            logger.debug(f"Event: {event_id} - Downloading video...")

            event_filename = f"{event_camera.name}-{event_id}-{event.type.value}.mp4"
            output_file = f"{download_dir}/{event_filename}"
            await event.get_video(output_file=output_file)

            logger.info(f"Event: {event_id} - Video saved to {output_file}")
            logger.info(f"Event: {event_id} - Processed.")

    return enqueue_event, process_events
