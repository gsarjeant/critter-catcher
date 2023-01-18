import asyncio
import logging
from pyunifiprotect import ProtectApiClient
from typing import Dict

logger = logging.getLogger(__name__)


class UnifiProtectClientManager(object):
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        verify_ssl: bool,
        port: int = 443,
    ):

        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self._protect_api_client = ProtectApiClient(
            host, port, username, password, verify_ssl=verify_ssl
        )

        self._bootstrap = None
        self._cameras = {}
        self._callback = None
        self._unsub = None

    async def initialize(self) -> None:
        self._bootstrap = await self._protect_api_client.update()
        logger.info("Unifi Protect API client initialized.")
        self._cameras = self._get_cameras()

    def _get_cameras(self) -> Dict[str, str]:
        logger.info("Finding cameras ...")
        cameras = {}
        for camera in self._protect_api_client.bootstrap.cameras.values():
            cameras[camera.id] = camera.name
            logger.info(f"    Camera name: {camera.name} - id: {camera.id}")

        return cameras

    @property
    def protect_api_client(self):
        return self._protect_api_client

    @property
    def cameras(self):
        return self._cameras

    def subscribe(self, callback):
        self._callback = callback
        self._unsub = self._protect_api_client.subscribe_websocket(self._callback)
        logger.debug("Listening for events on Unifi Protect websocket...")

    async def monitor_websocket_connection(self) -> None:
        while True:
            await asyncio.sleep(60)

            logger.debug("Checking connection to websocket")
            if self._protect_api_client.check_ws():
                logger.debug("Connected to Unifi Protect")
            else:
                logger.warning(
                    "Lost connection to Unifi Protect. Cleaning up connection."
                )

                self._unsub()
                await self._protect_api_client.close_session()

                while True:
                    logger.warning("Attempting to reconnect to Unifi Protect.")

                    try:
                        logger.warning("Reinitializing protect client")
                        await self._protect_api_client.update(force=True)
                        if self._protect_api_client.check_ws():
                            logger.warning("Resubscribing to websocket")
                            self._unsub = self._protect_api_client.subscribe_websocket(
                                self._callback
                            )
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

    @property
    def protect_api_client(self) -> ProtectApiClient:
        return self._protect_api_client

    async def shutdown(self):
        # Unsubscribe from the Unifi Protect websocket
        self._unsub()

        # Close Unifi Protect session
        if self._protect_api_client is not None:
            await self._protect_api_client.close_session()
