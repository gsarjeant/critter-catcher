import asyncio
import logging
import pytz
from critter_catcher.dataclasses import Config, EventCamera
from datetime import datetime, timedelta, timezone
from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data import WSAction, WSSubscriptionMessage
from pyunifiprotect.data.nvr import Event
from pyunifiprotect.data.types import EventType
from typing import Callable, AsyncIterator, List, Tuple

logger = logging.getLogger(__name__)


def get_callback_and_iterator(
    cameras: List[EventCamera],
) -> Tuple[Callable[[], None], AsyncIterator]:
    event_queue = asyncio.Queue()
    logger.debug(f"cameras: {str([c for c in cameras])}")

    def enqueue_event(msg: WSSubscriptionMessage) -> None:
        obj = msg.new_obj

        if not isinstance(obj, Event):
            return

        if obj.type not in [EventType.MOTION, EventType.SMART_DETECT]:
            logger.debug(f"Unhandled event type: {obj.type}")
            return

        logger.debug(f"Event ID: {obj.id}")
        logger.debug(f"Event dict: {obj.unifi_dict_to_dict(obj.unifi_dict())}")
        event_id = obj.id
        camera_id = obj.camera_id
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


async def _sleep_if_necessary(event: Event) -> None:
    time_since_event_ended = datetime.utcnow().replace(tzinfo=timezone.utc) - event.end
    sleep_time = (timedelta(seconds=5 * 1.5) - time_since_event_ended).total_seconds()

    if sleep_time > 0:
        logger.info(
            f"  Sleeping ({sleep_time}s) to ensure clip is ready to download..."
        )
        await asyncio.sleep(sleep_time)


async def _validate_authentication(protect: ProtectApiClient) -> bool:
    logger.debug("Checking authentication...")
    if protect.is_authenticated():
        logger.debug("Session is authenticated")
        return True

    logger.warning("Session is no longer authenticated. Reauthenticating...")
    await protect.authenticate()

    if not protect.is_authenticated():
        logger.error("Unexpected error reauthenticating session.")
        return False

    logger.warning("Session is reauthenticated.")
    return True


# Events should be captured only if they start after the specified start time
# and before the specified end time.
# If either is unset, then it is ignored.
def _event_time_is_in_capture_window(event: Event, config: Config) -> bool:
    after_start_time = not config.start_time or event.start.time() >= config.start_time
    before_end_time = not config.end_time or event.start.time() <= config.end_time

    # Both start and end time are defined. Make sure the event time falls between them.
    if config.start_time and config.end_time:
        if config.start_time < config.end_time:
            # The capture range is contained within a single day.
            return after_start_time and before_end_time

        # The capture time spans an overnight
        return after_start_time or before_end_time

    # Only start time is defined (stop capturing at midnight). Make sure the event started after the start time.
    if config.start_time:
        return after_start_time

    # Only end time is defined (start capturing at midnight). Make sure the event started before the end time.
    if config.end_time:
        return before_end_time

    # Neither start time nor end time is defined. Always capture.
    return True


async def _download_progress_callback(step: int, current: int, total: int) -> None:
    logger.debug(
        f"Downloading {total} bytes - Current chunk: {step}, total saved: {current}"
    )


async def process(
    events: AsyncIterator,
    protect: ProtectApiClient,
    cameras: List[EventCamera],
    config: Config,
):
    download_dir = config.download_dir

    async for event in events:
        logger.debug(
            f"Event ID: {event.id}"
        )

        event_id = event.id
        camera_id = event.camera_id
        event_camera = next(filter(lambda ec: ec.id == camera_id, cameras))

        # Convert event start and end times to match the timezone of the unifi controller
        event.start = event.start.replace(tzinfo=pytz.utc).astimezone(
            protect.bootstrap.nvr.timezone
        )
        event.end = event.end.replace(tzinfo=pytz.utc).astimezone(
            protect.bootstrap.nvr.timezone
        )

        # Determine whether the event time is in the capture window.
        if not _event_time_is_in_capture_window(event, config):
            logger.debug(
                f"Event: {event_id} is outside of capture window ({event.start.time()}). Skipping capture."
            )
            continue

        logger.debug(f"Event: {event_id} - In capture window. Processing...")
        logger.debug(f"Event: {event_id} - Event Type: {event.type}")

        if event.type == EventType.SMART_DETECT:
            obj_dict = event.unifi_dict_to_dict(event.unifi_dict())
            # The API returns a list of smart detect types.
            # Concatenate the list for logging purposes.
            smart_detect_types = ",".join(
                [sdt.value for sdt in obj_dict["smart_detect_types"]]
            )

            logger.debug(
                f"Event: {event_id} - Smart detect types: {smart_detect_types}"
            )

        logger.debug(
            f"Event: {event_id} - Start: {event.start.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        logger.debug(
            f"Event: {event_id} -   End: {event.end.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # Make sure that enough time has passed for the controller to finish storing the event clip
        await _sleep_if_necessary(event)

        # Make sure we're still authenticated before trying to capture the video.
        if not await _validate_authentication(protect):
            logger.error("Unable to authenticate. Skipping download.")
            continue

        logger.debug(f"Event: {event_id} - Downloading video...")
        display_camera_name = event_camera.name.replace(" ", "-")
        display_datetime = event.start.strftime("%Y%m%d-%H%M%S")
        event_filename = (
            f"{display_camera_name}-{display_datetime}-{event.type.value}.mp4"
        )
        output_file = f"{download_dir}/{event_filename}"

        await event.get_video(
            output_file=output_file, progress_callback=_download_progress_callback
        )

        logger.info(f"Event: {event_id} - Video saved to {output_file}")
        logger.info(f"Event: {event_id} - Processed.")
