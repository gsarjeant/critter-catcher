import asyncio
import logging
from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data import WSAction, WSSubscriptionMessage
from pyunifiprotect.data.nvr import Event
from pyunifiprotect.data.types import EventType
from typing import AsyncIterator, List

logger = logging.getLogger(__name__)


class UnifiProtectEventProcessor:
    def __init__(
        self,
        protect_api_client: ProtectApiClient,
        ignore_camera_ids: List,
        download_dir: str,
    ) -> None:
        self._protect_api_client = protect_api_client
        self._event_queue = asyncio.Queue()
        self._ignore_camera_ids = ignore_camera_ids
        self._download_dir = download_dir

    def process_event(self, msg: WSSubscriptionMessage) -> None:
        obj = msg.new_obj

        if isinstance(obj, Event):
            if obj.type not in [EventType.MOTION, EventType.SMART_DETECT]:
                logger.info(f"Unhandled event type: {obj.type}")
                return

            (event_id, camera_id) = obj.id.split("-")

            if camera_id in self._ignore_camera_ids:
                logger.debug(f"Event from ignored camera: {camera_id}")
                return

            if msg.action == WSAction.ADD:
                logger.info(f"Event: {event_id} - Started (type: {obj.type})")
                logger.info(f"Event: {event_id} - Camera: {camera_id}")
                return
            if msg.action != WSAction.UPDATE:
                return
            if obj.end is None:
                return

            self._event_queue.put_nowait(obj)
            logger.info(f"Event: {event_id} - placed in queue.")

    async def _get_events(self) -> AsyncIterator:
        while True:
            yield await self._event_queue.get()

    async def capture_event_video(self) -> None:
        async for event in self._get_events():
            (event_id, camera_id) = event.id.split("-")

            logger.info(f"Event: {event_id} - Event complete")
            logger.info(
                f"Event: {event_id} - Consumed by task: {asyncio.current_task().get_name()}"
            )
            logger.info(f"Event: {event_id} - Event Type: {event.type}")
            if event.type == EventType.SMART_DETECT:
                obj_dict = event.unifi_dict_to_dict(event.unifi_dict())
                logger.info(f"{str(obj_dict)}")
                # The API returns a list of smart detect types.
                # I've only ever seen one in practice, but maybe you can get "Person" and "Package" or something like that.
                # Concatenate the list for logging purposes.
                smart_detect_types = ",".join(
                    [sdt.value for sdt in obj_dict["smart_detect_types"]]
                )

                logger.info(
                    f"Event: {event_id} - Smart detect types: {smart_detect_types}"
                )

            logger.info(f"Event: {event_id} - Camera: {camera_id}")
            logger.info(
                f"Event: {event_id} - Start time (UTC): {event.start.date()} {event.start.time()}"
            )
            logger.info(
                f"Event: {event_id} -   End time (UTC): {event.end.date()} {event.end.time()}"
            )
            logger.info(f"Event: {event_id} - Downloading video...")

            event_filename = f"{camera_id}-{event_id}-{event.type.value}.mp4"
            output_file = f"{self._download_dir}/{event_filename}"
            await event.get_video(output_file=output_file)

            logger.info(f"Event: {event_id} - Video saved to {output_file}")
            logger.info(f"Event: {event_id} - Event processing complete")
