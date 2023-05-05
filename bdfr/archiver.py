#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import hashlib
import io
import json
import logging
import re
from collections.abc import Iterable, Iterator
from itertools import islice
from pathlib import Path
from time import sleep
from typing import Union

import dict2xml
import praw.exceptions
import praw.models
import prawcore
import yaml

from bdfr.archive_entry.base_archive_entry import BaseArchiveEntry
from bdfr.archive_entry.comment_archive_entry import CommentArchiveEntry
from bdfr.archive_entry.submission_archive_entry import SubmissionArchiveEntry
from bdfr.configuration import Configuration
from bdfr.connector import RedditConnector
from bdfr.exceptions import ArchiverError
from bdfr.resource import Resource

logger = logging.getLogger(__name__)


def _calc_string_hash(content: str):
    md5_hash = hashlib.md5()
    md5_hash.update(bytes(content, 'UTF-8'))
    hash = md5_hash.hexdigest()
    return hash


class Archiver(RedditConnector):
    def __init__(self, args: Configuration, logging_handlers: Iterable[logging.Handler] = ()):
        super(Archiver, self).__init__(args, logging_handlers)

    def download(self):
        try:
            for generator in self.reddit_lists:
                for chunk in batched(generator, 100):
                    try:
                        submissions = self.load_submissions(chunk)
                        for submission in submissions:
                            try:
                                if (submission.author and submission.author.name in self.args.ignore_user) or (
                                    submission.author is None and "DELETED" in self.args.ignore_user
                                ):
                                    logger.debug(
                                        f"Submission {submission.id} in {submission.subreddit.display_name} skipped due to"
                                        f" {submission.author.name if submission.author else 'DELETED'} being an ignored user"
                                    )
                                    continue
                                if submission.id in self.excluded_submission_ids:
                                    logger.debug(f"Object {submission.id} in exclusion list, skipping")
                                    continue
                                logger.debug(f"Attempting to archive submission {submission.id}")
                                self.write_entry(submission)
                            except (prawcore.PrawcoreException, praw.exceptions.PRAWException) as e:
                                logger.error(f"Submission {submission.id} failed to be archived due to a PRAW exception: {e}")
                    except (prawcore.PrawcoreException, praw.exceptions.PRAWException) as e:
                        logger.error(f"The submission after {submission.id} failed to download due to a PRAW exception: {e}")
                        logger.debug("Waiting 60 seconds to continue")
                        sleep(60)
        except Exception as e:
            logger.error(f"Uncaught exception: {e}")
        if self.args.keep_hashes:
            self._hash_list_save(False)

    def get_submissions_from_link(self) -> list[list[praw.models.Submission]]:
        supplied_submissions = []
        for sub_id in self.args.link:
            try:
                if len(sub_id) in (6, 7):
                    supplied_submissions.append(self.reddit_instance.submission(id=sub_id))
                elif re.match(r"^\w{7}$", sub_id):
                    supplied_submissions.append(self.reddit_instance.comment(id=sub_id))
                else:
                    supplied_submissions.append(self.reddit_instance.submission(url=sub_id))
            except (prawcore.PrawcoreException, praw.exceptions.PRAWException) as e:
                logger.error(f"Error getting submission {sub_id} from link: {e}")
        return [supplied_submissions]

    def get_user_data(self) -> list[Iterator]:
        results = super(Archiver, self).get_user_data()
        if self.args.user and self.args.all_comments:
            sort = self.determine_sort_function()
            for user in self.args.user:
                logger.debug(f"Retrieving comments of user {user}")
                results.append(sort(self.reddit_instance.redditor(user).comments, limit=self.args.limit))
        return results

    @staticmethod
    def _pull_lever_entry_factory(praw_item: Union[praw.models.Submission, praw.models.Comment], no_comments: bool) -> BaseArchiveEntry:
        if isinstance(praw_item, praw.models.Submission):
            return SubmissionArchiveEntry(praw_item, no_comments)
        elif isinstance(praw_item, praw.models.Comment):
            return CommentArchiveEntry(praw_item)
        else:
            raise ArchiverError(f"Factory failed to classify item of type {type(praw_item).__name__}")

    def write_entry(self, praw_item: Union[praw.models.Submission, praw.models.Comment]):
        if self.args.comment_context and isinstance(praw_item, praw.models.Comment):
            logger.debug(f"Converting comment {praw_item.id} to submission {praw_item.submission.id}")
            praw_item = praw_item.submission
        entry = self._pull_lever_entry_factory(praw_item, self.args.no_comments)
        if self.args.format == "json":
            content = json.dumps(entry.compile())
        elif self.args.format == "xml":
            content = dict2xml.dict2xml(entry.compile(), wrap="root")
        elif self.args.format == "yaml":
            content = yaml.safe_dump(entry.compile())
        else:
            raise ArchiverError(f"Unknown format {self.args.format} given")
        if self.args.ignore_score:
            praw_item.score = 0
            if isinstance(praw_item, praw.models.Submission):
                praw_item.upvote_ratio = 0
                praw_item.num_comments = 0
            entry = self._pull_lever_entry_factory(praw_item, self.args.no_comments)
        if self.args.format == "json":
            content = json.dumps(entry.compile()) if self.args.ignore_score else content
            hash = _calc_string_hash(content) if self.args.keep_hashes else None
            self._write_entry_json(entry, content, hash)
        elif self.args.format == "xml":
            content = dict2xml.dict2xml(entry.compile(), wrap="root") if self.args.ignore_score else content
            hash = _calc_string_hash(content) if self.args.keep_hashes else None
            self._write_entry_xml(entry, content, hash)
        elif self.args.format == "yaml":
            content = yaml.safe_dump(entry.compile()) if self.args.ignore_score else content
            hash = _calc_string_hash(content) if self.args.keep_hashes else None
            self._write_entry_yaml(entry, content, hash)

    def _write_entry_json(self, entry: BaseArchiveEntry, content: str, hash: str):
        resource = Resource(entry.source, "", lambda: None, ".json")
        self._write_content_to_disk(resource, content, hash)

    def _write_entry_xml(self, entry: BaseArchiveEntry, content: str, hash: str):
        resource = Resource(entry.source, "", lambda: None, ".xml")
        self._write_content_to_disk(resource, content, hash)

    def _write_entry_yaml(self, entry: BaseArchiveEntry, content: str, hash: str):
        resource = Resource(entry.source, "", lambda: None, ".yaml")
        self._write_content_to_disk(resource, content, hash)

    def _write_content_to_disk(self, resource: Resource, content: str, hash: str):
        file_path = self.file_name_formatter.format_path(resource, self.download_directory)
        
        if self.args.keep_hashes:
            if str(file_path) in self.master_file_list:
                if hash == self.master_file_list[str(file_path)]:
                    logger.debug(f"{resource.extension[1:].upper()} for {resource.source_submission.id} already saved before")
                    return
            self.master_hash_list[hash] = file_path
            self.master_file_list[str(file_path)] = hash
            self._hash_list_save(True)

        file_path.parent.mkdir(exist_ok=True, parents=True)
        with Path(file_path).open(mode="w", encoding="utf-8") as file:
            logger.debug(
                f"Writing entry {resource.source_submission.id} to file in {resource.extension[1:].upper()}"
                f" format at {file_path}"
            )
            file.write(content)
        logger.info(f"Record for entry item {resource.source_submission.id} written to disk")

    def load_submissions(self, lst: list[praw.models.Submission]) -> list[praw.models.Submission]:
        if not self.args.no_comments:
            return lst
        dic = {}
        for index, x in enumerate(lst):
            if not x._fetched:
                dic[x.id] = index
        list_ids = dic.keys()
        list_ids = [id if id.startswith('t3_') else f't3_{id}' for id in list_ids]
        submissions = self.reddit_instance.info(fullnames=list_ids)
        for sub in submissions:
            index = dic.get(sub.id, dic.get(sub.id[3:]))
            if not index is None:
                lst[index] = sub
        return lst

def batched(iterable, n):
    "Batch data into lists of length n. The last batch may be shorter."
    # batched('ABCDEFG', 3) --> ABC DEF G
    it = iter(iterable)
    while True:
        batch = list(islice(it, n))
        if not batch:
            return
        yield batch
