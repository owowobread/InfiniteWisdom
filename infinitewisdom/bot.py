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
import functools
import logging
import os
import sys

from infinitewisdom.const import COMMAND_START, REPLY_COMMAND_DELETE, IMAGE_ANALYSIS_TYPE_HUMAN, COMMAND_FORCE_ANALYSIS, \
    REPLY_COMMAND_INFO, COMMAND_INSPIRE, REPLY_COMMAND_TEXT

parent_dir = os.path.abspath(os.path.join(os.path.abspath(__file__), "..", ".."))
sys.path.append(parent_dir)

from infinitewisdom.config.config import Config
from prometheus_client import start_http_server
from telegram import InlineQueryResultPhoto, ChatAction, Update, InlineQueryResultCachedPhoto, ParseMode
from telegram.ext import CommandHandler, Filters, InlineQueryHandler, MessageHandler, Updater, \
    ChosenInlineResultHandler, CallbackContext

from infinitewisdom.analysis import ImageAnalyser
from infinitewisdom.analysis.googlevision import GoogleVision
from infinitewisdom.analysis.microsoftazure import AzureComputerVision
from infinitewisdom.analysis.tesseract import Tesseract
from infinitewisdom.analysis.worker import AnalysisWorker
from infinitewisdom.crawler import Crawler
from infinitewisdom.persistence import Entity, ImageDataPersistence
from infinitewisdom.stats import INSPIRE_TIME, INLINE_TIME, START_TIME, CHOSEN_INLINE_RESULTS
from infinitewisdom.uploader import TelegramUploader
from infinitewisdom.util import _send_photo, _send_message, parse_telegram_command

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)


def respond_on_error(func: callable):
    """
    Decorator that wraps functions and responds with an error message to the user if an error occurs.
    Note that this decorator should be applied after the ```restricted``` decorator to prevent leaking error messages.
    :return: the decorated method
    """

    if not callable(func):
        raise AttributeError("Unsupported type: {}".format(func))

    @functools.wraps(func)
    def wrapper(self, update: Update, context: CallbackContext, *args, **kwargs):
        bot = context.bot
        message = update.message
        chat_id = message.chat_id
        username = update.effective_user.username

        whitelist = self._config.TELEGRAM_ADMIN_USERNAMES.value

        try:
            return func(self, update, context, *args, **kwargs)
        except Exception as err:
            import traceback
            exception_text = "\n".join(list(map(lambda x: "{}:{}\n\t{}".format(x.filename, x.lineno, x.line),
                                                traceback.extract_tb(err.__traceback__))))
            if username in whitelist:
                _send_message(bot,
                              chat_id,
                              ":boom: There was an error running your command:\n\n```\n{}\n```".format(
                                  exception_text),
                              parse_mode=ParseMode.MARKDOWN,
                              reply_to=message.message_id)
            raise err

    return wrapper


def restricted(func: callable):
    """
    Decorator that can be used on command callbacks to restrict its usage to admin users
    :return: the decorated method
    """

    if not callable(func):
        raise AttributeError("Unsupported type: {}".format(func))

    @functools.wraps(func)
    def wrapper(self, update: Update, context: CallbackContext, *args, **kwargs):
        bot = context.bot
        message = update.message
        chat_id = message.chat_id
        command, argument = parse_telegram_command(message.text)
        username = update.effective_user.username

        whitelist = self._config.TELEGRAM_ADMIN_USERNAMES.value
        if username is None or username not in whitelist:
            _send_message(bot,
                          chat_id,
                          ":no_entry_sign: You do not have the required permissions to run this command.".format(
                              command),
                          parse_mode=ParseMode.MARKDOWN,
                          reply_to=message.message_id)
            return

        # otherwise call wrapped function as normal
        return func(self, update, context, *args, **kwargs)

    return wrapper


def requires_command_argument(error_message: str = None):
    """
    Decorator to indicate that a command requires an argument to be called.
    :return:
    """

    if error_message is None:
        error_message = ":exclamation: This command requires an argument."

    def decorator(func: callable):
        if not callable(func):
            raise AttributeError("Unsupported type: {}".format(func))

        @functools.wraps(func)
        def wrapper(self, update: Update, context: CallbackContext, *args, **kwargs):
            bot = context.bot
            message = update.effective_message
            command, argument = parse_telegram_command(message.text)
            chat_id = message.chat_id

            if argument is None:
                _send_message(bot, chat_id,
                              error_message,
                              reply_to=message.message_id)
                return

            # otherwise call wrapped function as normal
            return func(self, update, context, *args, **kwargs)

        return wrapper

    return decorator


def requires_image_reply(func):
    """
    Decorator to indicate that a command requires to be run as a reply to an image.
    :return:
    """

    if not callable(func):
        raise AttributeError("Unsupported type: {}".format(func))

    @functools.wraps(func)
    def wrapped(self, update: Update, context: CallbackContext, *args, **kwargs):
        bot = context.bot
        message = update.effective_message
        chat_id = message.chat_id
        reply_to_message = message.reply_to_message

        if reply_to_message.effective_attachment is None:
            _send_message(bot, chat_id,
                          ":exclamation: You must directly reply to an image send by this bot to use reply commands.",
                          reply_to=message.message_id)
            return

        reply_to_message = message.reply_to_message
        reply_image = next(iter(sorted(reply_to_message.effective_attachment, key=lambda x: x.file_size, reverse=True)),
                           None)
        telegram_file_id = reply_image.file_id
        entity = self._persistence.find_by_telegram_file_id(telegram_file_id)

        # otherwise call wrapped function as normal
        return func(self, update, context, entity, *args, **kwargs)

    return wrapped


class InfiniteWisdomBot:
    """
    The main entry class of the InfiniteWisdom telegram bot
    """

    def __init__(self, config: Config, persistence: ImageDataPersistence, image_analysers: [ImageAnalyser]):
        """
        Creates an instance.
        :param config: configuration object
        """
        self._config = config
        self._persistence = persistence
        self._image_analysers = image_analysers

        self._updater = Updater(token=self._config.TELEGRAM_BOT_TOKEN.value, use_context=True)
        LOGGER.debug("Using bot id '{}' ({})".format(self._updater.bot.id, self._updater.bot.name))

        self._dispatcher = self._updater.dispatcher
        self._dispatcher.add_handler(
            CommandHandler(COMMAND_START,
                           filters=(~ Filters.reply) & (~ Filters.forwarded),
                           callback=self._start_callback))

        self._dispatcher.add_handler(
            CommandHandler(COMMAND_INSPIRE,
                           filters=(~ Filters.reply) & (~ Filters.forwarded),
                           callback=self._inspire_callback))

        self._dispatcher.add_handler(
            CommandHandler(COMMAND_FORCE_ANALYSIS,
                           filters=(~ Filters.reply) & (~ Filters.forwarded),
                           callback=self._forceanalysis_callback))

        self._dispatcher.add_handler(
            CommandHandler(REPLY_COMMAND_INFO,
                           filters=Filters.command & Filters.reply & (~ Filters.forwarded),
                           callback=self._reply_info_command_callback))

        self._dispatcher.add_handler(
            CommandHandler(REPLY_COMMAND_TEXT,
                           filters=Filters.command & Filters.reply & (~ Filters.forwarded),
                           callback=self._reply_text_command_callback))

        self._dispatcher.add_handler(
            CommandHandler(COMMAND_FORCE_ANALYSIS,
                           filters=Filters.command & Filters.reply & (~ Filters.forwarded),
                           callback=self._reply_force_analysis_command_callback))

        self._dispatcher.add_handler(
            CommandHandler(REPLY_COMMAND_DELETE,
                           filters=Filters.command & Filters.reply & (~ Filters.forwarded),
                           callback=self._reply_delete_command_callback))

        # unknown command handler
        self._dispatcher.add_handler(
            MessageHandler(
                filters=Filters.command & (~ Filters.forwarded),
                callback=self._unknown_command_callback))

        self._dispatcher.add_handler(InlineQueryHandler(self._inline_query_callback))
        self._dispatcher.add_handler(ChosenInlineResultHandler(self._inline_result_chosen_callback))

    @property
    def bot(self):
        return self._updater.bot

    def start(self):
        """
        Starts up the bot.
        This means filling the url pool and listening for messages.
        """
        self._updater.start_polling()

    def stop(self):
        """
        Shuts down the bot.
        """
        self._updater.stop()

    @START_TIME.time()
    def _start_callback(self, update: Update, context: CallbackContext) -> None:
        """
        Welcomes a new user with an example image and a greeting message
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        self._send_random_quote(update, context)
        greeting_message = self._config.TELEGRAM_GREETING_MESSAGE.value
        if greeting_message is not None and len(greeting_message) > 0:
            _send_message(bot=bot, chat_id=update.message.chat_id, message=greeting_message)

    @respond_on_error
    @INSPIRE_TIME.time()
    def _inspire_callback(self, update: Update, context: CallbackContext) -> None:
        """
        /inspire command handler
        :param update: the chat update object
        :param context: telegram context
        """
        self._send_random_quote(update, context)

    @restricted
    @respond_on_error
    @requires_command_argument(
        error_message=":exclamation: You have to provide the image hash as an argument to the command.")
    def _forceanalysis_callback(self, update: Update, context: CallbackContext) -> None:
        """
        /forceanalysis command handler (with an argument)
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        message = update.message
        chat_id = message.chat_id
        command, argument = parse_telegram_command(message.text)

        entity = self._persistence.find_by_image_hash(argument)
        if entity is None:
            _send_message(bot, chat_id,
                          ":exclamation: No entity found for hash: {}".format(argument),
                          reply_to=message.message_id)
            return

        entity.analyser = None
        entity.analyser_quality = None
        self._persistence.update(entity)
        _send_message(bot, chat_id,
                      ":wrench: Reset analyser data for image with hash: {})".format(entity.image_hash),
                      reply_to=message.message_id)

    @restricted
    @respond_on_error
    @requires_image_reply
    def _reply_info_command_callback(self, update: Update, context: CallbackContext,
                                     entity_of_reply: Entity or None) -> None:
        """
        /info reply command handler
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        message = update.effective_message
        chat_id = message.chat_id

        _send_message(bot, chat_id, "{}".format(entity_of_reply),
                      parse_mode=ParseMode.MARKDOWN,
                      reply_to=message.message_id)

    @restricted
    @respond_on_error
    @requires_image_reply
    def _reply_text_command_callback(self, update: Update, context: CallbackContext,
                                     entity_of_reply: Entity or None) -> None:
        """
        /text reply command handler
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        message = update.effective_message
        chat_id = message.chat_id
        command, args = parse_telegram_command(message.text)

        entity_of_reply.analyser = IMAGE_ANALYSIS_TYPE_HUMAN
        entity_of_reply.analyser_quality = 1.0
        entity_of_reply.text = args
        self._persistence.update(entity_of_reply)
        _send_message(bot, chat_id,
                      ":wrench: Updated text for referenced image to '{}' (Hash: {})".format(entity_of_reply.text,
                                                                                             entity_of_reply.image_hash),
                      reply_to=message.message_id)

    @restricted
    @respond_on_error
    @requires_image_reply
    def _reply_delete_command_callback(self, update: Update, context: CallbackContext,
                                       entity_of_reply: Entity or None) -> None:
        """
        /text reply command handler
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        message = update.effective_message
        chat_id = message.chat_id
        is_edit = hasattr(message, 'edited_message') and message.edited_message is not None

        if is_edit:
            LOGGER.debug("Ignoring edited delete command")
            return

        self._persistence.delete(entity_of_reply)
        _send_message(bot, chat_id,
                      "Deleted referenced image from persistence (Hash: {})".format(entity_of_reply.image_hash),
                      reply_to=message.message_id)

    @restricted
    @respond_on_error
    @requires_image_reply
    def _reply_force_analysis_command_callback(self, update: Update, context: CallbackContext,
                                               entity_of_reply: Entity or None) -> None:
        """
        /forceanalysis reply command handler
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        message = update.effective_message
        chat_id = message.chat_id

        entity_of_reply.analyser = None
        entity_of_reply.analyser_quality = None
        self._persistence.update(entity_of_reply)
        _send_message(bot, chat_id,
                      ":wrench: Reset analyser data for the referenced image. (Hash: {})".format(
                          entity_of_reply.image_hash),
                      reply_to=message.message_id)

    @respond_on_error
    def _unknown_command_callback(self, update: Update, context: CallbackContext) -> None:
        """
        Handles unknown commands send by a user
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        message = update.message
        chat_id = message.chat_id
        from_user = message.from_user
        command, args = parse_telegram_command(message.text)

        from_user_is_admin = from_user.username in self._config.TELEGRAM_ADMIN_USERNAMES.value
        if from_user_is_admin:
            _send_message(bot, chat_id, ":eyes: Unsupported command: `/{}`".format(command),
                          parse_mode=ParseMode.MARKDOWN,
                          reply_to=message.message_id)
            return
        else:
            self._inspire_callback(update, context)

    @INLINE_TIME.time()
    def _inline_query_callback(self, update: Update, context: CallbackContext) -> None:
        """
        Responds to an inline client request with a list of 16 randomly chosen images
        :param update: the chat update object
        :param context: telegram context
        """
        LOGGER.debug('Inline query')

        query = update.inline_query.query
        offset = update.inline_query.offset
        if not offset:
            offset = 0
        else:
            offset = int(offset)
        badge_size = self._config.TELEGRAM_INLINE_BADGE_SIZE.value

        if len(query) > 0:
            entities = self._persistence.find_by_text(query, badge_size, offset)
        else:
            entities = self._persistence.get_random(page_size=badge_size)

        results = list(map(lambda x: self._entity_to_inline_query_result(x), entities))
        LOGGER.debug('Inline query "{}": {}+{} results'.format(query, len(results), offset))

        if len(results) > 0:
            new_offset = offset + badge_size
        else:
            new_offset = ''

        update.inline_query.answer(
            results,
            next_offset=new_offset
        )

    @staticmethod
    def _inline_result_chosen_callback(update: Update, context: CallbackContext):
        """
        Called when an inline result is chosen by a user
        :param update: the chat update object
        :param context: telegram context
        """
        CHOSEN_INLINE_RESULTS.inc()

    def _send_random_quote(self, update: Update, context: CallbackContext) -> None:
        """
        Sends a quote from the pool to the requesting chat
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        chat_id = update.message.chat_id
        bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        entity = self._persistence.get_random()
        LOGGER.debug("Sending random quote '{}' to chat id: {}".format(entity.image_hash, chat_id))

        caption = None
        if self._config.TELEGRAM_CAPTION_IMAGES_WITH_TEXT.value:
            caption = entity.text

        if entity.telegram_file_id is not None:
            _send_photo(bot=bot, chat_id=chat_id, file_id=entity.telegram_file_id, caption=caption)
            return

        image_bytes = self._persistence._image_data_store.get(entity.image_hash)
        file_id = _send_photo(bot=bot, chat_id=chat_id, image_data=image_bytes, caption=caption)
        entity.telegram_file_id = file_id
        self._persistence.update(entity, image_bytes)

    @staticmethod
    def _entity_to_inline_query_result(entity: Entity):
        """
        Creates a telegram inline query result object for the given entity
        :param entity: the entity to use
        :return: inline result object
        """
        if entity.telegram_file_id is not None:
            return InlineQueryResultCachedPhoto(
                id=entity.url,
                photo_file_id=str(entity.telegram_file_id),
            )
        else:
            return InlineQueryResultPhoto(
                id=entity.url,
                photo_url=entity.url,
                thumb_url=entity.url,
                photo_height=50,
                photo_width=50
            )


if __name__ == '__main__':
    config = Config()

    persistence = ImageDataPersistence(config)

    image_analysers = []
    if config.IMAGE_ANALYSIS_TESSERACT_ENABLED.value:
        image_analysers.append(Tesseract())
    if config.IMAGE_ANALYSIS_GOOGLE_VISION_ENABLED.value:
        auth_file = config.IMAGE_ANALYSIS_GOOGLE_VISION_AUTH_FILE.value
        capacity = config.IMAGE_ANALYSIS_GOOGLE_VISION_CAPACITY.value
        image_analysers.append(GoogleVision(auth_file, capacity))
    if config.IMAGE_ANALYSIS_MICROSOFT_AZURE_ENABLED.value:
        key = config.IMAGE_ANALYSIS_MICROSOFT_AZURE_SUBSCRIPTION_KEY.value
        region = config.IMAGE_ANALYSIS_MICROSOFT_AZURE_REGION.value
        capacity = config.IMAGE_ANALYSIS_MICROSOFT_AZURE_CAPACITY.value
        image_analysers.append(AzureComputerVision(key, region, capacity))

    # start prometheus server
    start_http_server(config.STATS_PORT.value)

    wisdom_bot = InfiniteWisdomBot(config, persistence, image_analysers)
    crawler = Crawler(config, persistence, image_analysers)
    analysis_worker = AnalysisWorker(config, persistence, image_analysers)
    telegram_uploader = TelegramUploader(config, persistence, wisdom_bot._updater.bot)

    wisdom_bot.start()
    crawler.start()
    analysis_worker.start()

    telegram_uploader.start()
