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

"""
Holds important constants
"""

__version__ = "4.6.8"

TELEGRAM_CAPTION_LENGTH_LIMIT = 200

COMMAND_START = 'start'
COMMAND_COMMANDS = ['help', 'h']
COMMAND_INSPIRE = ['inspire', 'i']
COMMAND_FORCE_ANALYSIS = ['forceanalysis', 'fa']
COMMAND_STATS = 'stats'
COMMAND_VERSION = ['version', 'v']
COMMAND_CONFIG = ['config', 'c']

REPLY_COMMAND_INFO = 'info'
REPLY_COMMAND_TEXT = ['text', 't']

REPLY_COMMAND_DELETE = ['delete', 'd']

DEFAULT_SQL_PERSISTENCE_URL = "sqlite:///infinitewisdom.db"
DEFAULT_FILE_PERSISTENCE_BASE_PATH = "./.image_data"

CONFIG_FILE_NAME = "infinitewisdom"

IMAGE_ANALYSIS_TYPE_HUMAN = "human"
IMAGE_ANALYSIS_TYPE_TESSERACT = "tesseract"
IMAGE_ANALYSIS_TYPE_GOOGLE_VISION = "google-vision"
IMAGE_ANALYSIS_TYPE_AZURE = "microsoft-azure"

CONFIG_NODE_ROOT = "InfiniteWisdom"
CONFIG_NODE_TELEGRAM = "telegram"
CONFIG_NODE_CRAWLER = "crawler"
CONFIG_NODE_UPLOADER = "uploader"
CONFIG_NODE_PERSISTENCE = "persistence"
CONFIG_NODE_IMAGE_ANALYSIS = "image_analysis"
CONFIG_NODE_INTERVAL = "interval"
CONFIG_NODE_STATS = "stats"
CONFIG_NODE_PORT = "port"

CONFIG_NODE_TESSERACT = "tesseract"
CONFIG_NODE_GOOGLE_VISION = "google_vision"
CONFIG_NODE_MICROSOFT_AZURE = "microsoft_azure"

CONFIG_NODE_ENABLED = "enabled"
CONFIG_NODE_CAPACITY_PER_MONTH = "capacity_per_month"

REQUESTS_TIMEOUT = (5, 5)
