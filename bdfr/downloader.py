#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging.handlers
import os
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from time import sleep

import praw
import praw.exceptions
import praw.models
import prawcore

from bdfr import exceptions as errors
from bdfr.configuration import Configuration
from bdfr.connector import RedditConnector
from bdfr.site_downloaders.download_factory import DownloadFactory

logger = logging.getLogger(__name__)


class RedditDownloader(RedditConnector):
    def __init__(self, args: Configuration, logging_handlers: Iterable[logging.Handler] = ()):
        super(RedditDownloader, self).__init__(args, logging_handlers)

    def download(self):
        try:
            for generator in self.reddit_lists:
                try:
                    for submission in generator:
                        try:
                            self._download_submission(submission)
                        except (prawcore.PrawcoreException, praw.exceptions.PRAWException) as e:
                            logger.error(f"Submission {submission.id} failed to download due to a PRAW exception: {e}")
                except (prawcore.PrawcoreException, praw.exceptions.PRAWException) as e:
                    logger.error(f"The submission after {submission.id} failed to download due to a PRAW exception: {e}")
                    logger.debug("Waiting 60 seconds to continue")
                    sleep(60)
        except Exception as e:
            logger.error(f"Uncaught exception: {e}")
            logger.exception(e)
        self._hash_list_save(False)

    def _download_submission(self, submission: praw.models.Submission):
        if submission.id in self.excluded_submission_ids:
            logger.debug(f"Object {submission.id} in exclusion list, skipping")
            return
        elif submission.subreddit.display_name.lower() in self.args.skip_subreddit:
            logger.debug(f"Submission {submission.id} in {submission.subreddit.display_name} in skip list")
            return
        elif (submission.author and submission.author.name in self.args.ignore_user) or (
            submission.author is None and "DELETED" in self.args.ignore_user
        ):
            logger.debug(
                f"Submission {submission.id} in {submission.subreddit.display_name} skipped"
                f' due to {submission.author.name if submission.author else "DELETED"} being an ignored user'
            )
            return
        elif self.args.min_score and submission.score < self.args.min_score:
            logger.debug(
                f"Submission {submission.id} filtered due to score {submission.score} < [{self.args.min_score}]"
            )
            return
        elif self.args.max_score and self.args.max_score < submission.score:
            logger.debug(
                f"Submission {submission.id} filtered due to score {submission.score} > [{self.args.max_score}]"
            )
            return
        elif (self.args.min_score_ratio and submission.upvote_ratio < self.args.min_score_ratio) or (
            self.args.max_score_ratio and self.args.max_score_ratio < submission.upvote_ratio
        ):
            logger.debug(f"Submission {submission.id} filtered due to score ratio ({submission.upvote_ratio})")
            return
        elif not isinstance(submission, praw.models.Submission):
            logger.warning(f"{submission.id} is not a submission")
            return
        elif not self.download_filter.check_url(submission.url):
            logger.debug(f"Submission {submission.id} filtered due to URL {submission.url}")
            return

        logger.debug(f"Attempting to download submission {submission.id}")
        if submission.url is None or submission.url == "":
            logger.debug("skipped empty url")
            return
        try:
            downloader_class = DownloadFactory.pull_lever(submission.url)
            downloader = downloader_class(submission, self.args)
            logger.debug(f"Using {downloader_class.__name__} with url {submission.url}")
        except errors.NotADownloadableLinkError as e:
            logger.error(f"Could not download submission {submission.id}: {e}")
            return
        if downloader_class.__name__.lower() in self.args.disable_module:
            logger.debug(f"Submission {submission.id} skipped due to disabled module {downloader_class.__name__}")
            return
        try:
            content = downloader.find_resources(self.authenticator)
        except errors.SiteDownloaderError as e:
            logger.error(f"Site {downloader_class.__name__} failed to download submission {submission.id}: {e}")
            return
        for destination, res in self.file_name_formatter.format_resource_paths(content, self.download_directory):
            if destination.exists():
                logger.debug(f"File {destination} from submission {submission.id} in {submission.subreddit.display_name} already exists, continuing")
                continue
            elif not self.download_filter.check_resource(res):
                logger.debug(f"Download filter removed {submission.id} file with URL {submission.url}")
                continue
            if self._check_url_exists_or_add(res.url, None):
                logger.debug(f"Url {res.url} from submission {submission.id} in {submission.subreddit.display_name} already downloaded before")
                continue

            try:
                res.download({"max_wait_time": self.args.max_wait_time, "fail_fast": self.args.fail_fast})
            except errors.BulkDownloaderException as e:
                logger.error(
                    f"Failed to download resource {res.url} in submission {submission.id} "
                    f"with downloader {downloader_class.__name__}: {e}"
                )
                return
            resource_hash = res.hash.hexdigest()
            destination.parent.mkdir(parents=True, exist_ok=True)
            if ((self.args.keep_hashes or self.args.keep_hashes_db) and self._check_hash_exists_or_add(None, resource_hash) or 
                (not self.args.keep_hashes and not self.args.keep_hashes_db) and resource_hash in self.master_hash_list):
                self._check_url_exists_or_add(res.url, resource_hash)
                if self.args.no_dupes:
                    logger.info(f"Resource hash {resource_hash} from submission {submission.id} downloaded elsewhere")
                    logger.debug(f"URL: {res.url}")
                    return
                elif self.args.make_hard_links:
                    hashed_item = self._get_hashed_item(resource_hash)
                    try:
                        destination.hardlink_to(hashed_item)
                    except AttributeError:
                        hashed_item.link_to(destination)
                    logger.info(
                        f"Hard link made linking {destination} to {hashed_item}"
                        f" in submission {submission.id}"
                    )
                    return
            try:
                with destination.open("wb") as file:
                    file.write(res.content)
                logger.debug(f"Written file to {destination}")
                logger.info(f"Downloaded submission {submission.id} from {submission.subreddit.display_name}")
            except OSError as e:
                logger.exception(e)
                logger.error(f"Failed to write file in submission {submission.id} to {destination}: {e}")
                return
            creation_time = time.mktime(datetime.fromtimestamp(submission.created_utc).timetuple())
            os.utime(destination, (creation_time, creation_time))
            if self.args.keep_hashes or self.args.keep_hashes_db:
                self._check_hash_exists_or_add(destination, resource_hash)
            else:
                self.master_hash_list[resource_hash] = destination
            self._check_url_exists_or_add(res.url, resource_hash)
            logger.debug(f"Hash added to master list: {resource_hash}")
