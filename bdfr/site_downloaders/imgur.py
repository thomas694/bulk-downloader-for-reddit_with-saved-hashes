#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import re
import urllib
from typing import Optional

from praw.models import Submission

from bdfr.configuration import Configuration
from bdfr.exceptions import SiteDownloaderError
from bdfr.resource import Resource
from bdfr.site_authenticator import SiteAuthenticator
from bdfr.site_downloaders.base_downloader import BaseDownloader

logger = logging.getLogger(__name__.replace("site_downloaders", ""))


class Imgur(BaseDownloader):
    def __init__(self, post: Submission, args: Configuration):
        super().__init__(post, args)
        self.raw_data = {}

    def find_resources(self, authenticator: Optional[SiteAuthenticator] = None) -> list[Resource]:
        if re.search(r".*/(i.|)imgur.com/[^/]*(.jpg|.jpeg|.png|.mp4)(\?1|)$", self.post.url):
            self.raw_data["link"] = self.post.url.replace("http://", "https://")
        else:
            try:
                self.raw_data = self._get_data(self.post.url)
            except Exception as e:
                if (self.args.imgur_fix404 and
                        str(e).startswith("Server responded with 404 to") and
                        re.search(r".*(.gif|.gifv)$", self.post.url)):
                    logger.debug(f"{e}")
                    out = []
                    if re.search(r".*(.gifv)$", self.post.url):
                        bytes = urllib.request.urlopen(self.post.url[:-1]).read(3)
                        if not self.args.imgur_originals or bytes == b"\xff\xd8\xff":
                            logger.debug(f"using {self.post.url[:-4]}mp4")
                            out.append(Resource(self.post, self.post.url[:-4] + "mp4", Resource.retry_download(self.post.url[:-4] + "mp4")))
                        else:
                            logger.debug(f"using {self.post.url[:-1]}")
                            out.append(Resource(self.post, self.post.url[:-1], Resource.retry_download(self.post.url[:-1])))
                    else:
                        logger.debug(f"using {self.post.url}")
                        out.append(Resource(self.post, self.post.url, Resource.retry_download(self.post.url)))
                    return out
                raise

        out = []
        if "is_album" in self.raw_data:
            for image in self.raw_data["images"]:
                if not self.args.imgur_originals and "mp4" in image:
                    out.append(Resource(self.post, image["mp4"], Resource.retry_download(image["mp4"])))
                else:
                    out.append(Resource(self.post, image["link"], Resource.retry_download(image["link"])))
        else:
            if not self.args.imgur_originals and "mp4" in self.raw_data:
                out.append(Resource(self.post, self.raw_data["mp4"], Resource.retry_download(self.raw_data["mp4"])))
            else:
                out.append(Resource(self.post, self.raw_data["link"], Resource.retry_download(self.raw_data["link"])))
        return out

    @staticmethod
    def _get_data(link: str) -> dict:
        try:
            if link.endswith("/"):
                link = link.removesuffix("/")
            if re.search(r".*/(.*?)(gallery/|a/)", link):
                imgur_id = re.match(r".*/(?:gallery/|a/)(.*?)(?:/.*)?$", link).group(1)
                link = f"https://api.imgur.com/3/album/{imgur_id}"
            else:
                imgur_id = re.match(r".*/(.*?)(?:_d)?(?:\..{0,})?$", link).group(1)
                link = f"https://api.imgur.com/3/image/{imgur_id}"
        except AttributeError:
            raise SiteDownloaderError(f"Could not extract Imgur ID from {link}")

        headers = {
            "referer": "https://imgur.com/",
            "origin": "https://imgur.com",
            "content-type": "application/json",
            "Authorization": "Client-ID 546c25a59c58ad7",
        }
        res = Imgur.retrieve_url(link, headers=headers)

        try:
            image_dict = json.loads(res.text)
        except json.JSONDecodeError as e:
            raise SiteDownloaderError(f"Could not parse received response as JSON: {e}")

        return image_dict["data"]
