# InfiniteWisdomBot - A Telegram bot that sends inspirational quotes of infinite wisdom...
# Copyright (C) 2019  Max Rosin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
import logging
import time

from telegram import Bot

from infinitewisdom import RegularIntervalWorker
from infinitewisdom.config.config import AppConfig
from infinitewisdom.persistence import ImageDataPersistence, _session_scope
from infinitewisdom.stats import UPLOADER_TIME, UPLOADER_QUEUE_LENGTH
from infinitewisdom.util import send_photo, download_image_bytes

LOGGER = logging.getLogger(__name__)


class TelegramUploader(RegularIntervalWorker):
    """
    Worker that sends every image that has not yet been uploaded to telegram servers to a specified chat
    to use telegram backend for as image hoster.
    """

    def __init__(self, config: AppConfig, persistence: ImageDataPersistence, bot: Bot):
        super().__init__(config.UPLOADER_INTERVAL.value)
        self._persistence = persistence
        self._bot = bot
        self._chat_id = config.UPLOADER_CHAT_ID.value

        with _session_scope() as session:
            self._not_uploaded_ids = set(self._persistence.get_not_uploaded_image_ids(session, self._bot.token))

    def start(self):
        if self._chat_id is None:
            LOGGER.debug("No chat id configured, not starting uploader.")
            return
        super().start()

    def add_image_to_queue(self, image_entity_id: int):
        self._not_uploaded_ids.add(image_entity_id)

    @UPLOADER_TIME.time()
    def _run(self):
        with _session_scope() as session:
            queue_length = len(self._not_uploaded_ids)
            UPLOADER_QUEUE_LENGTH.set(queue_length)
            if queue_length <= 0:
                # sleep for a longer time period to reduce load
                time.sleep(60)
                return

            image_id = self._not_uploaded_ids.pop()

            entity = self._persistence.get_image(session, image_id)
            image_data = self._persistence.get_image_data(entity)
            if image_data is None:
                LOGGER.warning("Missing image data for entity, trying to download: {}".format(entity))
                try:
                    image_data = download_image_bytes(entity.url)
                    self._persistence.update(session, entity, image_data)
                    entity = self._persistence.get_image(session, image_id)
                except Exception as e:
                    LOGGER.error(
                        "Error trying to download missing image data for url '{}', deleting entity.".format(entity.url),
                        e)
                    self._persistence.delete(session, entity)
                    return

            file_ids = send_photo(bot=self._bot, chat_id=self._chat_id, image_data=image_data)
            bot_token = self._persistence.get_bot_token(session, self._bot.token)
            for file_id in file_ids:
                entity.add_file_id(bot_token, file_id)
            self._persistence.update(session, entity, image_data)
            LOGGER.debug(
                "Send image '{}' to chat '{}' and updated entity with file_id {}.".format(
                    entity.url, self._chat_id, file_ids))
