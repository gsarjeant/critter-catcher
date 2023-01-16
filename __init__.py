import asyncio
import logging
import os
from typing import AsyncIterator, Callable, Tuple
from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data import WSAction, WSSubscriptionMessage
from pyunifiprotect.data.nvr import Event
from pyunifiprotect.data.types import EventType

cameras = {}
ignore_cameras = ["Front Door"]
logging.basicConfig(encoding="utf-8", level=logging.INFO)
logger = logging.getLogger(__name__)


def get_download_event_handlers() -> Tuple[Callable, AsyncIterator]:
    q = asyncio.Queue()

    def publish_event(msg: WSSubscriptionMessage) -> None:
        obj = msg.new_obj

        if isinstance(obj, Event):
            if obj.type is not EventType.MOTION:
                return

            (event_id, camera_id) = obj.id.split("-")
            camera_name = cameras[camera_id]
            if camera_name in ignore_cameras:
                return

            if msg.action == WSAction.ADD:
                logger.info(
                    f"Camera: {camera_name}, Event: {event_id} - started (type: {obj.type})."
                )
                return
            if msg.action != WSAction.UPDATE:
                return
            if obj.end is None:
                return

            q.put_nowait(obj)
            logger.info(f"Camera: {camera_name}, Event: {event_id} - placed in queue.")

    async def event_emitter() -> AsyncIterator:
        while True:
            yield await q.get()

    return publish_event, event_emitter()


async def download(events: AsyncIterator) -> None:
    async for event in events:
        (event_id, camera_id) = event.id.split("-")
        camera_name = cameras[camera_id]

        logger.info(f"Camera: {camera_name}, Event: {event_id} - complete.")
        logger.info(f"    Start time (UTC): {event.start.date()} {event.start.time()}")
        logger.info(f"      End time (UTC): {event.end.date()} {event.end.time()}")

        await event.get_video(
            output_file=f"/Users/greg/critters/{camera_name}-{event_id}.mp4"
        )

        logger.info(f"Camera: {camera_name}, Event: {event_id} - video saved.")


async def initialize_protect_client():
    host = os.environ["UDMP_HOST"]
    port = os.environ["UDMP_PORT"]
    username = os.environ["UDMP_USERNAME"]
    password = os.environ["UDMP_PASSWORD"]
    verify_ssl = os.environ["UDMP_VERIFY_SSL"] == "true"

    protect = ProtectApiClient(host, port, username, password, verify_ssl=verify_ssl)

    await protect.update()

    logger.info("Protect client initialized.")
    logger.debug("Listing cameras ...")
    for camera in protect.bootstrap.cameras.values():
        cameras[camera.id] = camera.name
        logger.debug(f"    Name: {camera.name} - id: {camera.id}")

    return protect


async def reconnect_websocket_if_disconnected(
    protect: ProtectApiClient, unsub: Callable, publish_event: Callable
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
                    await protect.close_session()
                    logger.warning("Reinitializing protect client")
                    await protect.update(force=True)
                    if protect.check_ws():
                        logger.warning("Resubscribing to websocket")
                        unsub = protect.subscribe_websocket(publish_event)
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


async def main() -> None:
    try:
        protect = await initialize_protect_client()

        logger.debug("Listening for events...")
        publish_event, event_emitter = get_download_event_handlers()
        unsub = protect.subscribe_websocket(publish_event)

        # asyncio.TaskGroup requires python 3.11+
        async with asyncio.TaskGroup() as tg:
            download_task = tg.create_task(download(event_emitter))
            websocket_task = tg.create_task(
                reconnect_websocket_if_disconnected(protect, unsub, publish_event)
            )

    except asyncio.CancelledError:
        logger.info("Done listening. Unsubscribing.")
        # remove subscription
        unsub()

        # Close protect session
        if protect is not None:
            await protect.close_session()


if __name__ == "__main__":
    asyncio.run(main())
