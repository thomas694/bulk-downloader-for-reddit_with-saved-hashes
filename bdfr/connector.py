#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import configparser
import hashlib
import importlib.resources
import itertools
import json
import logging
import logging.handlers
import os
import re
import shutil
import sqlite3
import socket
from abc import ABCMeta, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from enum import Enum, auto
from multiprocessing import Pool
from pathlib import Path
from sqlite3 import Error, OperationalError
from time import sleep

import appdirs
import praw
import praw.exceptions
import praw.models
import prawcore

from bdfr import exceptions as errors
from bdfr.configuration import Configuration
from bdfr.download_filter import DownloadFilter
from bdfr.file_name_formatter import FileNameFormatter
from bdfr.oauth2 import OAuth2Authenticator, OAuth2TokenManager
from bdfr.site_authenticator import SiteAuthenticator

logger = logging.getLogger(__name__)


class RedditTypes:
    class SortType(Enum):
        CONTROVERSIAL = auto()
        HOT = auto()
        NEW = auto()
        RELEVENCE = auto()
        RISING = auto()
        TOP = auto()

    class TimeType(Enum):
        ALL = "all"
        DAY = "day"
        HOUR = "hour"
        MONTH = "month"
        WEEK = "week"
        YEAR = "year"


def _calc_hash(existing_file: Path):
    chunk_size = 1024 * 1024
    md5_hash = hashlib.md5()
    with existing_file.open("rb") as file:
        chunk = file.read(chunk_size)
        while chunk:
            md5_hash.update(chunk)
            chunk = file.read(chunk_size)
    file_hash = md5_hash.hexdigest()
    return existing_file, file_hash


class RedditConnector(metaclass=ABCMeta):

    __HASH_DB_NAME = "hashes.sqlite"

    def __init__(self, args: Configuration, logging_handlers: Iterable[logging.Handler] = ()):
        self.args = args
        self.config_directories = appdirs.AppDirs("bdfr", "BDFR")
        self.determine_directories()
        self.load_config()
        self.read_config()
        file_log = self.create_file_logger()
        self._apply_logging_handlers(itertools.chain(logging_handlers, [file_log]))
        self.run_time = datetime.now().isoformat()
        self._setup_internal_objects()

        self.reddit_lists = self.retrieve_reddit_lists()

        if self.args.search_existing:
            (self.master_hash_list, self.master_file_list, self.master_url_list) = self.scan_existing_files(self.download_directory, self.args.keep_hashes)
        elif self.args.keep_hashes:
            (self.master_hash_list, self.master_file_list, self.master_url_list) = self._load_hash_list(self.download_directory)
        if self.args.keep_hashes:
            self.__master_hash_list_cnt = len(self.master_hash_list)
            self.__master_file_list_cnt = len(self.master_file_list)
            self.__master_url_list_cnt = len(self.master_url_list)

    def _setup_internal_objects(self):

        self.parse_disabled_modules()

        self.download_filter = self.create_download_filter()
        logger.log(9, "Created download filter")
        self.time_filter = self.create_time_filter()
        logger.log(9, "Created time filter")
        self.sort_filter = self.create_sort_filter()
        logger.log(9, "Created sort filter")
        self.file_name_formatter = self.create_file_name_formatter()
        logger.log(9, "Create file name formatter")

        self.create_reddit_instance()
        self.args.user = list(filter(None, [self.resolve_user_name(user) for user in self.args.user]))

        self.excluded_submission_ids = set.union(
            set(self.read_id_files(self.args.exclude_id_file)),
            set(self.args.exclude_id),
        )

        self.args.link = list(itertools.chain(self.args.link, self.read_id_files(self.args.include_id_file)))

        self.__hash_db_conn = None
        self.__check_hash_params()

        self.master_hash_list = {}
        self.__master_hash_list_cnt = self.__master_file_list_cnt = self.__master_url_list_cnt = 0
        self.authenticator = self.create_authenticator()
        logger.log(9, "Created site authenticator")

        self.args.skip_subreddit = self.split_args_input(self.args.skip_subreddit)
        self.args.skip_subreddit = {sub.lower() for sub in self.args.skip_subreddit}

    def __check_hash_params(self):
        if self.args.keep_hashes_db:
            fn = os.path.join(self.download_directory, self.__HASH_DB_NAME)
            if self.args.keep_hashes:
                # one-time conversion, if hash files and no db file yet
                if not os.path.isfile(os.path.join(self.download_directory, "hash_list.json")):
                    raise Exception("option '--keep-hashes' specified, but no hash files found")
                elif os.path.isfile(fn):
                    raise Exception("Cannot convert hash files, a hash DB already exists.")
                else:
                    self.__convert_hash_files_to_db(fn)
            if not os.path.isfile(fn):
                self.__create_hash_db(fn)
            self.__open_hash_db(fn)
            
    def __convert_hash_files_to_db(self, db_path: Path):
        self.__create_hash_db(db_path)

        logger.info("Converting hash files...")
        cursor = self.__hash_db_conn.cursor()
        
        fn = os.path.join(self.download_directory, "hash_list.json")
        if os.path.isfile(fn):
            with open(fn) as fp:
                dict_json = json.load(fp)
            data = [(key, os.fsencode(value)) for key, value in dict_json.items()]
            logger.info(f"Loaded {len(dict_json)} hashes")
            query = "INSERT INTO hashes(hash, file_path) VALUES (?, ?)"
            try:
                cursor.executemany(query, data)
            except OperationalError as e:
                logger.critical(f"Error occurred: '{e}'")
            self.__hash_db_conn.commit()
            logger.info(f"Converted {len(dict_json)} hashes")
            dict_json = None
        else:
            raise Exception("hash_list.json missing")

        fn = os.path.join(self.download_directory, "hash_file_list.json")
        if os.path.isfile(fn):
            with open(fn) as fp:
                dict_json = json.load(fp)
            data = [(os.fsencode(key), value) for key, value in dict_json.items()]
            logger.info(f"Loaded {len(dict_json)} file entries")
            query = "INSERT INTO hashes_file(file_path, hash) VALUES (?, ?)"
            try:
                cursor.executemany(query, data)
            except OperationalError as e:
                logger.critical(f"Error occurred: '{e}'")
            self.__hash_db_conn.commit()
            logger.info(f"Converted {len(dict_json)} file entries")
            dict_json = None
        else:
            raise Exception("hash_file_list.json missing")
        
        fn = os.path.join(self.download_directory, "hash_url_list.json")
        if os.path.isfile(fn):
            with open(fn) as fp:
                dict_json = json.load(fp)
            data = [(key, value) for key, value in dict_json.items()]
            logger.info(f"Loaded {len(dict_json)} url entries")
            query = "INSERT INTO hashes_url(url, hash) VALUES (?, ?)"
            try:
                cursor.executemany(query, data)
            except OperationalError as e:
                logger.critical(f"Error occurred: '{e}'")
            self.__hash_db_conn.commit()
            logger.info(f"Converted {len(dict_json)} url entries")
            dict_json = None
        else:
            raise Exception("hash_url_list.json missing")
        
        self.args.keep_hashes = False
        
    def __open_hash_db(self, path: Path):
        try:
            if self.__hash_db_conn is None:
                self.__hash_db_conn = sqlite3.connect(path)
        except Error as e:
            logger.critical(f"Connection to SQLite DB failed: '{e}'")
        
    def __create_hash_db(self, path: Path):
        self.__open_hash_db(path)

        cursor = self.__hash_db_conn.cursor()
        try:
            query =  """
            CREATE TABLE IF NOT EXISTS hashes (
              hash TEXT PRIMARY KEY,
              file_path TEXT NOT NULL
            );
            """
            cursor.execute(query)
            query =  """
            CREATE TABLE IF NOT EXISTS hashes_file (
              file_path TEXT PRIMARY KEY,
              hash TEXT NOT NULL
            );
            """
            cursor.execute(query)
            query =  """
            CREATE TABLE IF NOT EXISTS hashes_url (
              url TEXT PRIMARY KEY,
              hash TEXT NOT NULL
            );
            """
            cursor.execute(query)
            self.__hash_db_conn.commit()
            logger.info("Hash tables created successfully")
        except Error as e:
            logger.critical(f"Error creating hash tables: '{e}'")

    @staticmethod
    def _apply_logging_handlers(handlers: Iterable[logging.Handler]):
        main_logger = logging.getLogger()
        for handler in handlers:
            main_logger.addHandler(handler)

    def read_config(self):
        """Read any cfg values that need to be processed"""
        if self.args.max_wait_time is None:
            self.args.max_wait_time = self.cfg_parser.getint("DEFAULT", "max_wait_time", fallback=120)
            logger.debug(f"Setting maximum download wait time to {self.args.max_wait_time} seconds")
        if self.args.time_format is None:
            option = self.cfg_parser.get("DEFAULT", "time_format", fallback="ISO")
            if re.match(r"^[\s\'\"]*$", option):
                option = "ISO"
            logger.debug(f"Setting datetime format string to {option}")
            self.args.time_format = option
        if not self.args.disable_module:
            self.args.disable_module = [self.cfg_parser.get("DEFAULT", "disabled_modules", fallback="")]
        if not self.args.filename_restriction_scheme:
            self.args.filename_restriction_scheme = self.cfg_parser.get(
                "DEFAULT", "filename_restriction_scheme", fallback=None
            )
            logger.debug(f"Setting filename restriction scheme to '{self.args.filename_restriction_scheme}'")
        # Update config on disk
        with Path(self.config_location).open(mode="w") as file:
            self.cfg_parser.write(file)

    def parse_disabled_modules(self):
        disabled_modules = self.args.disable_module
        disabled_modules = self.split_args_input(disabled_modules)
        disabled_modules = {name.strip().lower() for name in disabled_modules}
        self.args.disable_module = disabled_modules
        logger.debug(f'Disabling the following modules: {", ".join(self.args.disable_module)}')

    def create_reddit_instance(self):
        if self.args.authenticate:
            logger.debug("Using authenticated Reddit instance")
            if not self.cfg_parser.has_option("DEFAULT", "user_token"):
                logger.log(9, "Commencing OAuth2 authentication")
                scopes = self.cfg_parser.get("DEFAULT", "scopes", fallback="identity, history, read, save")
                scopes = OAuth2Authenticator.split_scopes(scopes)
                oauth2_authenticator = OAuth2Authenticator(
                    scopes,
                    self.cfg_parser.get("DEFAULT", "client_id"),
                    self.cfg_parser.get("DEFAULT", "client_secret"),
                )
                token = oauth2_authenticator.retrieve_new_token()
                self.cfg_parser["DEFAULT"]["user_token"] = token
                with Path(self.config_location).open(mode="w") as file:
                    self.cfg_parser.write(file, True)
            token_manager = OAuth2TokenManager(self.cfg_parser, self.config_location)

            self.authenticated = True
            self.reddit_instance = praw.Reddit(
                client_id=self.cfg_parser.get("DEFAULT", "client_id"),
                client_secret=self.cfg_parser.get("DEFAULT", "client_secret"),
                user_agent=socket.gethostname(),
                token_manager=token_manager,
            )
        else:
            logger.debug("Using unauthenticated Reddit instance")
            self.authenticated = False
            self.reddit_instance = praw.Reddit(
                client_id=self.cfg_parser.get("DEFAULT", "client_id"),
                client_secret=self.cfg_parser.get("DEFAULT", "client_secret"),
                user_agent=socket.gethostname(),
            )

    def retrieve_reddit_lists(self) -> list[praw.models.ListingGenerator]:
        master_list = []
        master_list.extend(self.get_subreddits())
        logger.log(9, "Retrieved subreddits")
        master_list.extend(self.get_multireddits())
        logger.log(9, "Retrieved multireddits")
        master_list.extend(self.get_user_data())
        logger.log(9, "Retrieved user data")
        master_list.extend(self.get_submissions_from_link())
        logger.log(9, "Retrieved submissions for given links")
        return master_list

    def determine_directories(self):
        self.download_directory = Path(self.args.directory).resolve().expanduser()
        self.config_directory = Path(self.config_directories.user_config_dir)

        self.download_directory.mkdir(exist_ok=True, parents=True)
        self.config_directory.mkdir(exist_ok=True, parents=True)

    def load_config(self):
        self.cfg_parser = configparser.ConfigParser()
        if self.args.config:
            if (cfg_path := Path(self.args.config)).exists():
                self.cfg_parser.read(cfg_path)
                self.config_location = cfg_path
                return
        possible_paths = [
            Path("./config.cfg"),
            Path("./default_config.cfg"),
            Path(self.config_directory, "config.cfg"),
            Path(self.config_directory, "default_config.cfg"),
        ]
        self.config_location = None
        for path in possible_paths:
            if path.resolve().expanduser().exists():
                self.config_location = path
                logger.debug(f"Loading configuration from {path}")
                break
        if not self.config_location:
            with importlib.resources.path("bdfr", "default_config.cfg") as path:
                self.config_location = path
                shutil.copy(self.config_location, Path(self.config_directory, "default_config.cfg"))
        if not self.config_location:
            raise errors.BulkDownloaderException("Could not find a configuration file to load")
        self.cfg_parser.read(self.config_location)

    def create_file_logger(self) -> logging.handlers.RotatingFileHandler:
        if self.args.log is None:
            log_path = Path(self.config_directory, "log_output.txt")
        else:
            log_path = Path(self.args.log).resolve().expanduser()
            if not log_path.parent.exists():
                raise errors.BulkDownloaderException("Designated location for logfile does not exist")
        backup_count = self.cfg_parser.getint("DEFAULT", "backup_log_count", fallback=3)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            mode="a",
            backupCount=backup_count,
            encoding="utf-8"
        )
        if log_path.exists():
            try:
                file_handler.doRollover()
            except PermissionError:
                logger.critical(
                    "Cannot rollover logfile, make sure this is the only "
                    "BDFR process or specify alternate logfile location"
                )
                raise
        formatter = logging.Formatter("[%(asctime)s - %(name)s - %(levelname)s] - %(message)s")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(0)
        return file_handler

    @staticmethod
    def sanitise_subreddit_name(subreddit: str) -> str:
        pattern = re.compile(r"^(?:https://www\.reddit\.com/)?(?:r/)?(.*?)/?$")
        match = re.match(pattern, subreddit)
        if not match:
            raise errors.BulkDownloaderException(f"Could not find subreddit name in string {subreddit}")
        return match.group(1)

    @staticmethod
    def split_args_input(entries: list[str]) -> set[str]:
        all_entries = []
        split_pattern = re.compile(r"[,;]\s?")
        for entry in entries:
            results = re.split(split_pattern, entry)
            all_entries.extend([RedditConnector.sanitise_subreddit_name(name) for name in results])
        return set(all_entries)

    def get_subreddits(self) -> list[praw.models.ListingGenerator]:
        out = []
        subscribed_subreddits = set()
        if self.args.subscribed:
            if self.args.authenticate:
                try:
                    subscribed_subreddits = list(self.reddit_instance.user.subreddits(limit=None))
                    subscribed_subreddits = {s.display_name for s in subscribed_subreddits}
                except prawcore.InsufficientScope:
                    logger.error("BDFR has insufficient scope to access subreddit lists")
            else:
                logger.error("Cannot find subscribed subreddits without an authenticated instance")
        if self.args.subreddit or subscribed_subreddits:
            for reddit in self.split_args_input(self.args.subreddit) | subscribed_subreddits:
                if reddit == "friends" and self.authenticated is False:
                    logger.error("Cannot read friends subreddit without an authenticated instance")
                    continue
                try:
                    reddit = self.reddit_instance.subreddit(reddit)
                    try:
                        self.check_subreddit_status(reddit)
                    except errors.BulkDownloaderException as e:
                        logger.error(e)
                        continue
                    if self.args.search:
                        out.append(
                            reddit.search(
                                self.args.search,
                                sort=self.sort_filter.name.lower(),
                                limit=self.args.limit,
                                time_filter=self.time_filter.value,
                            )
                        )
                        logger.debug(
                            f'Added submissions from subreddit {reddit} with the search term "{self.args.search}"'
                        )
                    else:
                        out.append(self.create_filtered_listing_generator(reddit))
                        logger.debug(f"Added submissions from subreddit {reddit}")
                except (errors.BulkDownloaderException, prawcore.PrawcoreException, praw.exceptions.PRAWException) as e:
                    logger.error(f"Failed to get submissions for subreddit {reddit}: {e}")
        return out

    def resolve_user_name(self, in_name: str) -> str:
        if in_name == "me":
            if self.authenticated:
                resolved_name = self.reddit_instance.user.me().name
                logger.log(9, f"Resolved user to {resolved_name}")
                return resolved_name
            else:
                logger.warning('To use "me" as a user, an authenticated Reddit instance must be used')
        else:
            return in_name

    def get_submissions_from_link(self) -> list[list[praw.models.Submission]]:
        supplied_submissions = []
        for sub_id in self.args.link:
            if re.match(r"^\w+$", sub_id):
                supplied_submissions.append(self.reddit_instance.submission(id=sub_id))
            else:
                supplied_submissions.append(self.reddit_instance.submission(url=sub_id))
        return [supplied_submissions]

    def determine_sort_function(self) -> Callable:
        if self.sort_filter is RedditTypes.SortType.NEW:
            sort_function = praw.models.Subreddit.new
        elif self.sort_filter is RedditTypes.SortType.RISING:
            sort_function = praw.models.Subreddit.rising
        elif self.sort_filter is RedditTypes.SortType.CONTROVERSIAL:
            sort_function = praw.models.Subreddit.controversial
        elif self.sort_filter is RedditTypes.SortType.TOP:
            sort_function = praw.models.Subreddit.top
        else:
            sort_function = praw.models.Subreddit.hot
        return sort_function

    def get_multireddits(self) -> list[Iterator]:
        if self.args.multireddit:
            if len(self.args.user) != 1:
                logger.error("Only 1 user can be supplied when retrieving from multireddits")
                return []
            out = []
            for multi in self.split_args_input(self.args.multireddit):
                try:
                    multi = self.reddit_instance.multireddit(redditor=self.args.user[0], name=multi)
                    if not multi.subreddits:
                        raise errors.BulkDownloaderException
                    out.append(self.create_filtered_listing_generator(multi))
                    logger.debug(f"Added submissions from multireddit {multi}")
                except (errors.BulkDownloaderException, praw.exceptions.PRAWException, prawcore.PrawcoreException) as e:
                    logger.error(f"Failed to get submissions for multireddit {multi}: {e}")
            return out
        else:
            return []

    def create_filtered_listing_generator(self, reddit_source) -> Iterator:
        sort_function = self.determine_sort_function()
        if self.sort_filter in (RedditTypes.SortType.TOP, RedditTypes.SortType.CONTROVERSIAL):
            return sort_function(reddit_source, limit=self.args.limit, time_filter=self.time_filter.value)
        else:
            return sort_function(reddit_source, limit=self.args.limit)

    def get_user_data(self) -> list[Iterator]:
        if any([self.args.submitted, self.args.upvoted, self.args.saved]):
            if not self.args.user:
                logger.warning("At least one user must be supplied to download user data")
                return []
            generators = []
            for user in self.args.user:
                try:
                    try:
                        self.check_user_existence(user)
                    except errors.BulkDownloaderException as e:
                        logger.error(e)
                        continue
                    if self.args.submitted:
                        logger.debug(f"Retrieving submitted posts of user {user}")
                        generators.append(
                            self.create_filtered_listing_generator(
                                self.reddit_instance.redditor(user).submissions,
                            )
                        )
                    if not self.authenticated and any((self.args.upvoted, self.args.saved)):
                        logger.warning("Accessing user lists requires authentication")
                    else:
                        if self.args.upvoted:
                            logger.debug(f"Retrieving upvoted posts of user {user}")
                            generators.append(self.reddit_instance.redditor(user).upvoted(limit=self.args.limit))
                        if self.args.saved:
                            logger.debug(f"Retrieving saved posts of user {user}")
                            generators.append(self.reddit_instance.redditor(user).saved(limit=self.args.limit))
                except (prawcore.PrawcoreException, praw.exceptions.PRAWException) as e:
                    logger.error(f"User {user} failed to be retrieved due to a PRAW exception: {e}")
                    logger.debug("Waiting 60 seconds to continue")
                    sleep(60)
            return generators
        else:
            return []

    def check_user_existence(self, name: str):
        user = self.reddit_instance.redditor(name=name)
        try:
            if user.id:
                return
        except prawcore.exceptions.NotFound:
            raise errors.BulkDownloaderException(f"Could not find user {name}")
        except AttributeError:
            if hasattr(user, "is_suspended"):
                raise errors.BulkDownloaderException(f"User {name} is banned")

    def create_file_name_formatter(self) -> FileNameFormatter:
        return FileNameFormatter(
            self.args.file_scheme, self.args.folder_scheme, self.args.time_format, self.args.filename_restriction_scheme,
            self.args.filename_character_set
        )

    def create_time_filter(self) -> RedditTypes.TimeType:
        try:
            return RedditTypes.TimeType[self.args.time.upper()]
        except (KeyError, AttributeError):
            return RedditTypes.TimeType.ALL

    def create_sort_filter(self) -> RedditTypes.SortType:
        try:
            return RedditTypes.SortType[self.args.sort.upper()]
        except (KeyError, AttributeError):
            return RedditTypes.SortType.HOT

    def create_download_filter(self) -> DownloadFilter:
        return DownloadFilter(self.args.skip, self.args.skip_domain)

    def create_authenticator(self) -> SiteAuthenticator:
        return SiteAuthenticator(self.cfg_parser)

    @abstractmethod
    def download(self):
        pass

    @staticmethod
    def check_subreddit_status(subreddit: praw.models.Subreddit):
        if subreddit.display_name in ("all", "friends"):
            return
        try:
            assert subreddit.id
        except prawcore.NotFound:
            raise errors.BulkDownloaderException(f"Source {subreddit.display_name} cannot be found")
        except prawcore.Redirect:
            raise errors.BulkDownloaderException(f"Source {subreddit.display_name} does not exist")
        except prawcore.Forbidden:
            raise errors.BulkDownloaderException(f"Source {subreddit.display_name} is private and cannot be scraped")

    @staticmethod
    def read_id_files(file_locations: list[str]) -> list[str]:
        out = {}
        for id_file in file_locations:
            id_file = Path(id_file).resolve().expanduser()
            if not id_file.exists():
                logger.warning(f"ID file at {id_file} does not exist")
                continue
            with id_file.open("r") as file:
                for line in file:
                    out[line.strip()] = None
        return out.keys()

    @staticmethod
    def scan_existing_files(directory: Path, keep_hashes: bool) -> (dict[str, Path], dict[str, str], dict[str, str]):
        if keep_hashes:
            (hash_list_loaded, filename_list_loaded, url_list) = RedditConnector._load_hash_list(directory)
        files = []
        for (dirpath, _dirnames, filenames) in os.walk(directory):
            files.extend([Path(dirpath, file) for file in filenames])
        if keep_hashes:
            files_new = list()
            for file in files:
                if str(file) not in filename_list_loaded:
                    files_new.append(file)
            files = []
            files.extend(files_new)
        logger.info(f"Calculating hashes for {len(files)} files")

        pool = Pool(15)
        results = pool.map(_calc_hash, files)
        pool.close()

        hash_list = {res[1]: res[0] for res in results}
        filename_list = {}
        if keep_hashes:
            filename_list = {str(res[0]): res[1] for res in results}
            filename_list_loaded.update(filename_list)
            filename_list = filename_list_loaded
            hash_list_loaded.update(hash_list)
            hash_list = hash_list_loaded
            if len(files_new) > 0:
                RedditConnector._save_hash_list(directory, hash_list, filename_list, url_list)
        else:
            url_list = {}
        return (hash_list, filename_list, url_list)

    @staticmethod
    def _load_hash_list(directory: Path) -> (dict[str, Path], dict[str, str], dict[str, str]):
        logger.info("Loading hashes...")
        
        fn = os.path.join(directory, "hash_list.json")
        hash_list = {}
        if os.path.isfile(fn):
            with open(fn) as fp:
                dict_json = json.load(fp)
            for x in dict_json:
                hash_list[x] = Path(dict_json[x])
        logger.info(f"Loaded {len(hash_list)} hashes")
        
        fn = os.path.join(directory, "hash_file_list.json")
        filename_list = {}
        if os.path.isfile(fn):
            with open(fn) as fp:
                filename_list = json.load(fp)
        logger.info(f"Loaded {len(filename_list)} file entries")

        fn = os.path.join(directory, "hash_url_list.json")
        url_list = {}
        if os.path.isfile(fn):
            with open(fn) as fp:
                url_list = json.load(fp)
        logger.info(f"Loaded {len(url_list)} url entries")
        
        return (hash_list, filename_list, url_list)

    @staticmethod
    def _save_hash_list(directory: Path, hash_list: dict[str, Path], filename_list: dict[str, str], url_list: dict[str, str]):
        dict_json = {}
        for x in hash_list:
            dict_json[x] = str(hash_list[x])
        fn = os.path.join(directory, "hash_list.json")
        if os.path.exists(fn):
            os.replace(fn, fn + '.bak')
        with open(fn, 'w') as fp:
            json.dump(dict_json, fp)
        logger.info(f"Saved {len(hash_list)} hashes")

        fn = os.path.join(directory, "hash_file_list.json")
        if os.path.exists(fn):
            os.replace(fn, fn + '.bak')
        with open(fn, 'w') as fp:
            json.dump(filename_list, fp)
        logger.info(f"Saved {len(filename_list)} file entries")

        fn = os.path.join(directory, "hash_url_list.json")
        if os.path.exists(fn):
            os.replace(fn, fn + '.bak')
        with open(fn, 'w') as fp:
            json.dump(url_list, fp)
        logger.info(f"Saved {len(url_list)} url entries")

    def _hash_list_save(self, periodic: bool):
        # no save necessary for keep_hashes_db, only for keep_hashes
        if self.args.keep_hashes and (not periodic or periodic and self.args.save_hashes_interval > 0 
            and (len(self.master_hash_list) - self.__master_hash_list_cnt > self.args.save_hashes_interval or
                 len(self.master_file_list) - self.__master_file_list_cnt > self.args.save_hashes_interval or
                 len(self.master_url_list) - self.__master_url_list_cnt > self.args.save_hashes_interval) ):
            self._save_hash_list(self.download_directory, self.master_hash_list, self.master_file_list, self.master_url_list)
            self.__master_hash_list_cnt = len(self.master_hash_list)
            self.__master_file_list_cnt = len(self.master_file_list)
            self.__master_url_list_cnt = len(self.master_url_list)

    def _check_hash_exists_or_add(self, file_path_obj: Path, hash: str):
        file_path = str(file_path_obj)
        if self.args.keep_hashes_db:
            file_path = os.fsencode(file_path)
            cursor = self.__hash_db_conn.cursor()
            if file_path_obj is None:
                query = "SELECT file_path FROM hashes WHERE hash = ?"
                cursor.execute(query, [hash])
                row = cursor.fetchone()
                cursor.close()
                return row is not None
            query = "SELECT hash FROM hashes_file WHERE file_path = ?"
            cursor.execute(query, [file_path])
            hash_found = cursor.fetchone()
            if hash_found and hash == hash_found[0]:
                cursor.close()
                return True
            if hash is not None:
                query = "INSERT OR REPLACE INTO hashes(hash, file_path) VALUES (?, ?)"
                cursor.execute(query, (hash, file_path))
                query = "INSERT OR REPLACE INTO hashes_file(file_path, hash) VALUES (?, ?)"
                cursor.execute(query, (file_path, hash))
                self.__hash_db_conn.commit()
            cursor.close()
        elif self.args.keep_hashes:
            if file_path_obj is None:
                return hash in self.master_hash_list
            hash_found = self.master_file_list.get(file_path, None)
            if hash_found is not None and hash == hash_found:
                return True
            if hash is not None:
                self.master_hash_list[hash] = file_path
                self.master_file_list[file_path] = hash
                self._hash_list_save(True)
        return False
        
    def _check_url_exists_or_add(self, url: str, hash: str):
        if self.args.keep_hashes_db:
            query = "SELECT hash FROM hashes_url WHERE url = ?"
            cursor = self.__hash_db_conn.cursor()
            cursor.execute(query, [url])
            row = cursor.fetchone()
            if row:
                cursor.close()
                return True
            if hash is not None:
                query = "INSERT INTO hashes_url(url, hash) VALUES (?, ?)"
                cursor.execute(query, (url, hash))
                self.__hash_db_conn.commit()
            cursor.close()
        elif self.args.keep_hashes:
            if url in self.master_url_list:
                return True
            if hash is not None:
                self.master_url_list[url] = hash
                self._hash_list_save(True)
        return False

    def _get_hashed_item(self, hash: str) -> Path:
        if self.args.keep_hashes_db:
            query = "SELECT file_path FROM hashes WHERE hash = ?"
            cursor = self.__hash_db_conn.cursor()
            cursor.execute(query, [hash])
            row = cursor.fetchone()
            cursor.close()
            if row:
                return Path(os.fsdecode(row[0]))
            else:
                return None
        else:
            return self.master_hash_list[hash]
