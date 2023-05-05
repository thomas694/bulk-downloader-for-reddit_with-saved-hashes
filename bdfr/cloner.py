#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from collections.abc import Iterable
from time import sleep

import praw.exceptions
import prawcore

from bdfr.archiver import Archiver, batched
from bdfr.configuration import Configuration
from bdfr.downloader import RedditDownloader

logger = logging.getLogger(__name__)


class RedditCloner(RedditDownloader, Archiver):
    def __init__(self, args: Configuration, logging_handlers: Iterable[logging.Handler] = ()):
        super(RedditCloner, self).__init__(args, logging_handlers)

    def download(self):
        try:
            for generator in self.reddit_lists:
                for chunk in batched(generator, 100):
                    try:
                        submissions = self.load_submissions(chunk)
                        for submission in submissions:
                            try:
                                self._download_submission(submission)
                                if "Reddit_imgur" not in str(self.download_directory) or "imgur.com" in submission.url:
                                    self.write_entry(submission)
                            except (prawcore.PrawcoreException, praw.exceptions.PRAWException) as e:
                                logger.error(f"Submission {submission.id} failed to be cloned due to a PRAW exception: {e}")
                    except (prawcore.PrawcoreException, praw.exceptions.PRAWException) as e:
                        logger.error(f"The submission after {submission.id} failed to download due to a PRAW exception: {e}")
                        logger.debug("Waiting 60 seconds to continue")
                        sleep(60)
        except Exception as e:
            logger.error(f"Uncaught exception: {e}")
        if self.args.keep_hashes:
            self._hash_list_save(False)
