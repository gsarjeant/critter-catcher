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


class UnifiProtectEventProcessor:
    def __init__(
        self,
        event_cameras: List[EventCamera],
        download_dir: str,
    ) -> None:
        self._event_queue = asyncio.Queue()
        self._event_cameras = event_cameras
        self._download_dir = download_dir

        logger.info(f"cameras: {str([c for c in event_cameras])}")

    def _get_event_camera(self, camera_id):
        # TODO: This is making two prety big assumptions:
        #       1. I didn't somehow end up with more than one EventCamera with a given ID.
        #       2. The requested camera_id actually exists.
        #       Put in a check to ensure that those are true.
        return next(filter(lambda ec: ec.id == camera_id, self._event_cameras))

    def process_event(self, msg: WSSubscriptionMessage) -> None:
        obj = msg.new_obj

        if isinstance(obj, Event):
            if obj.type not in [EventType.MOTION, EventType.SMART_DETECT]:
                logger.info(f"Unhandled event type: {obj.type}")
                return

            (event_id, camera_id) = obj.id.split("-")
            event_camera = self._get_event_camera(camera_id)

            if event_camera.ignore:
                logger.info(f"Event from ignored camera: {event_camera.name}")
                return

            if msg.action == WSAction.ADD:
                logger.info(f"Event: {event_id} - Started (type: {obj.type})")
                logger.info(f"Event: {event_id} - Camera: {event_camera.name}")
                return
            if msg.action != WSAction.UPDATE:
                return
            if obj.end is None:
                return

            self._event_queue.put_nowait(obj)
            logger.info(f"Event: {event_id} - placed in queue.")

    async def capture_event_video(self) -> None:
        async def _get_events() -> AsyncIterator:
            while True:
                yield await self._event_queue.get()

        async for event in _get_events():
            (event_id, camera_id) = event.id.split("-")
            event_camera = self._get_event_camera(camera_id)

            logger.info(f"Event: {event_id} - Event complete")
            logger.info(
                f"Event: {event_id} - Consumed by task: {asyncio.current_task().get_name()}"
            )
            logger.info(f"Event: {event_id} - Event Type: {event.type}")
            if event.type == EventType.SMART_DETECT:
                obj_dict = event.unifi_dict_to_dict(event.unifi_dict())
                # The API returns a list of smart detect types.
                # I've only ever seen one item in the list for any single event in practice,
                # but maybe you can get "Person" and "Package" or something like that.
                # Concatenate the list for logging purposes.
                smart_detect_types = ",".join(
                    [sdt.value for sdt in obj_dict["smart_detect_types"]]
                )

                logger.info(
                    f"Event: {event_id} - Smart detect types: {smart_detect_types}"
                )

            logger.info(f"Event: {event_id} - Camera: {event_camera.name}")
            logger.info(
                f"Event: {event_id} - Start time (UTC): {event.start.date()} {event.start.time()}"
            )
            logger.info(
                f"Event: {event_id} -   End time (UTC): {event.end.date()} {event.end.time()}"
            )
            logger.info(f"Event: {event_id} - Downloading video...")

            event_filename = f"{event_camera.name}-{event_id}-{event.type.value}.mp4"
            output_file = f"{self._download_dir}/{event_filename}"
            await event.get_video(output_file=output_file)

            logger.info(f"Event: {event_id} - Video saved to {output_file}")
            logger.info(f"Event: {event_id} - Event processing complete")
