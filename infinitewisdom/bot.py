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

from telegram import InlineQueryResultPhoto, ChatAction, Update, InlineQueryResultCachedPhoto, ParseMode
from telegram.ext import CommandHandler, Filters, InlineQueryHandler, MessageHandler, Updater, \
    ChosenInlineResultHandler, CallbackContext
from telegram_click.argument import Argument
from telegram_click.decorator import command
from telegram_click.permission.base import Permission

from infinitewisdom.analysis import ImageAnalyser
from infinitewisdom.config.config import AppConfig
from infinitewisdom.const import COMMAND_START, REPLY_COMMAND_DELETE, IMAGE_ANALYSIS_TYPE_HUMAN, COMMAND_FORCE_ANALYSIS, \
    REPLY_COMMAND_INFO, COMMAND_INSPIRE, REPLY_COMMAND_TEXT, COMMAND_STATS, COMMAND_VERSION
from infinitewisdom.persistence import Image, ImageDataPersistence
from infinitewisdom.stats import INSPIRE_TIME, INLINE_TIME, START_TIME, CHOSEN_INLINE_RESULTS, format_metrics
from infinitewisdom.util import send_photo, send_message, parse_telegram_command

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)


def requires_image_reply(func):
    """
    Decorator to indicate that a command requires to be run as a reply to an image.
    :return:
    """

    if not callable(func):
        raise AttributeError("Unsupported type: {}".format(func))

    @functools.wraps(func)
    def wrapper(self, update: Update, context: CallbackContext, *args, **kwargs):
        bot = context.bot
        message = update.effective_message
        chat_id = message.chat_id
        reply_to_message = message.reply_to_message

        if (reply_to_message.from_user is None
                or reply_to_message.from_user.id != bot.id
                or reply_to_message.effective_attachment is None):
            send_message(bot, chat_id,
                         ":exclamation: You must directly reply to an image send by this bot to use reply commands.",
                         reply_to=message.message_id)
            return

        reply_to_message = message.reply_to_message
        for attachment in reply_to_message.effective_attachment:
            telegram_file_id = attachment.file_id
            entity = self._persistence.find_by_telegram_file_id(telegram_file_id)
            if entity is not None:
                break

        # otherwise call wrapped function as normal
        return func(self, update, context, entity, *args, **kwargs)

    return wrapper


class _ConfigAdmins(Permission):

    def __init__(self):
        self._config = AppConfig()

    def evaluate(self, update: Update, context: CallbackContext) -> bool:
        from_user = update.effective_message.from_user
        return from_user.username in self._config.TELEGRAM_ADMIN_USERNAMES.value


CONFIG_ADMINS = _ConfigAdmins()


class InfiniteWisdomBot:
    """
    The main entry class of the InfiniteWisdom telegram bot
    """

    def __init__(self, config: AppConfig, persistence: ImageDataPersistence, image_analysers: [ImageAnalyser]):
        """
        Creates an instance.
        :param config: configuration object
        :param persistence: image persistence
        :param image_analysers: list of image analysers
        """
        self._config = config
        self._persistence = persistence
        self._image_analysers = image_analysers

        self._updater = Updater(token=self._config.TELEGRAM_BOT_TOKEN.value, use_context=True)
        LOGGER.debug("Using bot id '{}' ({})".format(self._updater.bot.id, self._updater.bot.name))

        self._dispatcher = self._updater.dispatcher

        handlers = [
            CommandHandler(COMMAND_START,
                           filters=(~ Filters.reply) & (~ Filters.forwarded),
                           callback=self._start_callback),
            CommandHandler(COMMAND_INSPIRE,
                           filters=(~ Filters.reply) & (~ Filters.forwarded),
                           callback=self._inspire_callback),
            CommandHandler(COMMAND_FORCE_ANALYSIS,
                           filters=(~ Filters.reply) & (~ Filters.forwarded),
                           callback=self._forceanalysis_callback),
            CommandHandler(COMMAND_STATS,
                           filters=(~ Filters.reply) & (~ Filters.forwarded),
                           callback=self._stats_callback),
            CommandHandler(REPLY_COMMAND_INFO,
                           filters=Filters.reply & (~ Filters.forwarded),
                           callback=self._reply_info_command_callback),
            CommandHandler(REPLY_COMMAND_TEXT,
                           filters=Filters.reply & (~ Filters.forwarded),
                           callback=self._reply_text_command_callback),
            CommandHandler(COMMAND_FORCE_ANALYSIS,
                           filters=Filters.reply & (~ Filters.forwarded),
                           callback=self._reply_force_analysis_command_callback),
            CommandHandler(REPLY_COMMAND_DELETE,
                           filters=Filters.reply & (~ Filters.forwarded),
                           callback=self._reply_delete_command_callback),
            CommandHandler(COMMAND_VERSION,
                           filters=(~ Filters.reply) & (~ Filters.forwarded),
                           callback=self._version_command_callback),
            # unknown command handler
            MessageHandler(
                filters=Filters.command & (~ Filters.forwarded),
                callback=self._unknown_command_callback),
            InlineQueryHandler(self._inline_query_callback),
            ChosenInlineResultHandler(self._inline_result_chosen_callback)
        ]

        for handler in handlers:
            self._updater.dispatcher.add_handler(handler)

    @property
    def bot(self):
        return self._updater.bot

    def start(self):
        """
        Starts up the bot.
        This means filling the url pool and listening for messages.
        """
        self._updater.start_polling()
        self._updater.idle()

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
            send_message(bot=bot, chat_id=update.message.chat_id, message=greeting_message)

    @command(
        name=COMMAND_INSPIRE,
        description="Get inspired by a random quote of infinite wisdom."
    )
    @INSPIRE_TIME.time()
    def _inspire_callback(self, update: Update, context: CallbackContext) -> None:
        """
        /inspire command handler
        :param update: the chat update object
        :param context: telegram context
        """
        self._send_random_quote(update, context)

    @command(
        name=COMMAND_FORCE_ANALYSIS,
        description="Force a reset of the existing image analysis data of the given image.",
        arguments=[
            Argument(
                name="image_hash",
                description="The hash of the image to reset.",
                example="d41d8cd98f00b204e9800998ecf8427e"
            )
        ],
        permissions=CONFIG_ADMINS
    )
    def _forceanalysis_callback(self, update: Update, context: CallbackContext, image_hash: str) -> None:
        """
        /forceanalysis command handler (with an argument)
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        entity = self._persistence.find_by_image_hash(image_hash)
        if entity is None:
            send_message(bot, chat_id,
                         ":exclamation: No entity found for hash: {}".format(image_hash),
                         reply_to=message.message_id)
            return

        entity.analyser = None
        entity.analyser_quality = None
        self._persistence.update(entity)
        send_message(bot, chat_id,
                     ":wrench: Reset analyser data for image with hash: {})".format(entity.image_hash),
                     reply_to=message.message_id)

    @command(
        name=COMMAND_STATS,
        description="List statistics of this bot.",
        permissions=CONFIG_ADMINS
    )
    def _stats_callback(self, update: Update, context: CallbackContext) -> None:
        """
        /stats command handler
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        text = format_metrics()

        send_message(bot, chat_id, text, reply_to=message.message_id)

    @command(
        name=COMMAND_VERSION,
        description="Show the version of this bot.",
        permissions=CONFIG_ADMINS
    )
    def _version_command_callback(self, update: Update, context: CallbackContext) -> None:
        """
        /stats command handler
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        from infinitewisdom.const import __version__
        text = "{}".format(__version__)
        send_message(bot, chat_id, text, reply_to=message.message_id)

    @command(
        name=REPLY_COMMAND_INFO,
        description="Show information of the image that is referenced via message reply.",
        permissions=CONFIG_ADMINS
    )
    @requires_image_reply
    def _reply_info_command_callback(self, update: Update, context: CallbackContext,
                                     entity_of_reply: Image or None) -> None:
        """
        /info reply command handler
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        send_message(bot, chat_id, "{}".format(entity_of_reply),
                     parse_mode=ParseMode.MARKDOWN,
                     reply_to=message.message_id)

    @command(
        name=REPLY_COMMAND_TEXT,
        description="Set the text of the image that is referenced via message reply.",
        arguments=[
            Argument(
                name="text",
                description="The text to set.",
                example="This is a very inspirational quote.",
                validator=lambda x: x and x.strip()
            )
        ],
        permissions=CONFIG_ADMINS
    )
    @requires_image_reply
    def _reply_text_command_callback(self, update: Update, context: CallbackContext,
                                     entity_of_reply: Image or None, text: str) -> None:
        """
        /text reply command handler
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        entity_of_reply.analyser = IMAGE_ANALYSIS_TYPE_HUMAN
        entity_of_reply.analyser_quality = 1.0
        entity_of_reply.text = text
        self._persistence.update(entity_of_reply)
        send_message(bot, chat_id,
                     ":wrench: Updated text for referenced image to '{}' (Hash: {})".format(entity_of_reply.text,
                                                                                            entity_of_reply.image_hash),
                     reply_to=message.message_id)

    @command(
        name=REPLY_COMMAND_DELETE,
        description="Delete the image that is referenced via message reply.",
        permissions=CONFIG_ADMINS
    )
    @requires_image_reply
    def _reply_delete_command_callback(self, update: Update, context: CallbackContext,
                                       entity_of_reply: Image or None) -> None:
        """
        /text reply command handler
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id
        is_edit = hasattr(message, 'edited_message') and message.edited_message is not None

        if is_edit:
            LOGGER.debug("Ignoring edited delete command")
            return

        self._persistence.delete(entity_of_reply)
        send_message(bot, chat_id,
                     "Deleted referenced image from persistence (Hash: {})".format(entity_of_reply.image_hash),
                     reply_to=message.message_id)

    @command(
        name=COMMAND_FORCE_ANALYSIS,
        description="Force a reset of the existing image analysis data "
                    "of the image that is referenced via message reply.",
        permissions=CONFIG_ADMINS
    )
    @requires_image_reply
    def _reply_force_analysis_command_callback(self, update: Update, context: CallbackContext,
                                               entity_of_reply: Image or None) -> None:
        """
        /forceanalysis reply command handler
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        entity_of_reply.analyser = None
        entity_of_reply.analyser_quality = None
        self._persistence.update(entity_of_reply)
        send_message(bot, chat_id,
                     ":wrench: Reset analyser data for the referenced image. (Hash: {})".format(
                         entity_of_reply.image_hash),
                     reply_to=message.message_id)

    # @command(
    #     name=COMMAND_COMMANDS,
    #     description="List commands supported by this bot.",
    # )
    def _unknown_command_callback(self, update: Update, context: CallbackContext) -> None:
        """
        Handles unknown commands send by a user
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id
        username = "N/A"
        if update.effective_user is not None:
            username = update.effective_user.username
        command, args = parse_telegram_command(message.text)

        user_is_admin = username in self._config.TELEGRAM_ADMIN_USERNAMES.value
        if user_is_admin:
            send_message(bot, chat_id, ":eyes: Unsupported command: `/{}`".format(command),
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
        chat_id = update.effective_chat.id
        bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        entity = self._persistence.get_random()
        LOGGER.debug("Sending random quote '{}' to chat id: {}".format(entity.image_hash, chat_id))

        caption = None
        if self._config.TELEGRAM_CAPTION_IMAGES_WITH_TEXT.value:
            caption = entity.text

        if len(entity.telegram_file_ids) > 0:
            file_ids = send_photo(bot=bot, chat_id=chat_id, file_id=entity.telegram_file_ids[0].id, caption=caption)
            for file_id in file_ids:
                entity.add_file_id(file_id)
            self._persistence.update(entity)
            return

        image_bytes = self._persistence._image_data_store.get(entity.image_hash)
        file_ids = send_photo(bot=bot, chat_id=chat_id, image_data=image_bytes, caption=caption)
        for file_id in file_ids:
            entity.add_file_id(file_id)
        self._persistence.update(entity, image_bytes)

    @staticmethod
    def _entity_to_inline_query_result(entity: Image):
        """
        Creates a telegram inline query result object for the given entity
        :param entity: the entity to use
        :return: inline result object
        """
        if len(entity.telegram_file_ids) > 0:
            return InlineQueryResultCachedPhoto(
                id=entity.image_hash,
                photo_file_id=str(entity.telegram_file_ids[0].id),
            )
        else:
            return InlineQueryResultPhoto(
                id=entity.image_hash,
                photo_url=entity.url,
                thumb_url=entity.url,
                photo_height=50,
                photo_width=50
            )
