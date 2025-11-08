#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Mock Reddit Data for Testing
Provides realistic mock data to test BDFR enhancements without hitting Reddit's servers.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, PropertyMock
import random
import string


class MockSubmissionFactory:
    """Factory for creating mock PRAW submission objects"""

    @staticmethod
    def create_submission(
        submission_id: str = None,
        title: str = "Test Submission",
        url: str = "https://example.com/image.jpg",
        score: int = 100,
        upvote_ratio: float = 0.95,
        subreddit: str = "test",
        author: str = "test_user",
        created_utc: float = None,
        num_comments: int = 5,
        is_video: bool = False,
        is_gallery: bool = False,
    ) -> MagicMock:
        """
        Create a mock submission with realistic attributes.
        
        Args:
            submission_id: Reddit submission ID
            title: Submission title
            url: Content URL
            score: Upvote score
            upvote_ratio: Ratio of upvotes to total votes (0-1)
            subreddit: Subreddit name
            author: Author username
            created_utc: Unix timestamp of creation
            num_comments: Number of comments
            is_video: Whether this is a video
            is_gallery: Whether this is a gallery
        
        Returns:
            MagicMock: Mock submission object
        """
        if submission_id is None:
            submission_id = "".join(random.choices(string.ascii_letters + string.digits, k=6))
        
        if created_utc is None:
            created_utc = (datetime.now() - timedelta(days=random.randint(0, 365))).timestamp()
        
        mock_submission = MagicMock()
        mock_submission.id = submission_id
        mock_submission.title = title
        mock_submission.url = url
        mock_submission.score = score
        mock_submission.upvote_ratio = upvote_ratio
        mock_submission.created_utc = created_utc
        mock_submission.num_comments = num_comments
        mock_submission.is_video = is_video
        mock_submission.is_gallery = is_gallery
        mock_submission.selftext = f"Selftext content for {submission_id}"
        
        # Mock subreddit
        mock_subreddit = MagicMock()
        mock_subreddit.display_name = subreddit
        mock_submission.subreddit = mock_subreddit
        
        # Mock author
        if author:
            mock_author = MagicMock()
            mock_author.name = author
            mock_submission.author = mock_author
        else:
            mock_submission.author = None
        
        # Mock media info for videos
        if is_video:
            mock_submission.media = {
                "reddit_video": {
                    "fallback_url": "https://v.redd.it/fallback.mp4",
                    "height": 720,
                    "width": 1280,
                    "duration": 60
                }
            }
        else:
            mock_submission.media = None
        
        # Mock gallery items
        if is_gallery:
            mock_submission.gallery_data = {
                "items": [
                    {"media_id": "abc123", "id": 0},
                    {"media_id": "def456", "id": 1},
                ]
            }
        else:
            mock_submission.gallery_data = None
        
        return mock_submission

    @staticmethod
    def create_batch(count: int = 10, **kwargs) -> list:
        """Create multiple mock submissions"""
        return [
            MockSubmissionFactory.create_submission(
                submission_id=f"test_{i:06d}",
                score=random.randint(10, 10000),
                upvote_ratio=round(random.uniform(0.5, 1.0), 2),
                **kwargs
            )
            for i in range(count)
        ]


class MockCommentFactory:
    """Factory for creating mock PRAW comment objects"""

    @staticmethod
    def create_comment(
        comment_id: str = None,
        body: str = "Test comment",
        score: int = 10,
        author: str = "test_user",
        created_utc: float = None,
    ) -> MagicMock:
        """Create a mock comment"""
        if comment_id is None:
            comment_id = "".join(random.choices(string.ascii_letters + string.digits, k=6))
        
        if created_utc is None:
            created_utc = datetime.now().timestamp()
        
        mock_comment = MagicMock()
        mock_comment.id = comment_id
        mock_comment.body = body
        mock_comment.score = score
        mock_comment.created_utc = created_utc
        
        if author:
            mock_author = MagicMock()
            mock_author.name = author
            mock_comment.author = mock_author
        else:
            mock_comment.author = None
        
        return mock_comment

    @staticmethod
    def create_batch(count: int = 5) -> list:
        """Create multiple mock comments"""
        return [
            MockCommentFactory.create_comment(
                comment_id=f"comment_{i:06d}",
                score=random.randint(0, 1000),
            )
            for i in range(count)
        ]


class MockRedditInstanceFactory:
    """Factory for creating mock Reddit instances"""

    @staticmethod
    def create_mock_reddit(
        authenticated: bool = False,
        user_name: str = "test_user",
    ) -> MagicMock:
        """
        Create a mock Reddit instance with configurable behavior.
        
        Args:
            authenticated: Whether the instance is authenticated
            user_name: Username if authenticated
        
        Returns:
            MagicMock: Mock Reddit instance
        """
        mock_reddit = MagicMock()
        
        if authenticated:
            mock_user = MagicMock()
            mock_user.name = user_name
            mock_reddit.user.me.return_value = mock_user
        else:
            mock_reddit.user.me.side_effect = Exception("Not authenticated")
        
        return mock_reddit


class MockSubmissionGenerator:
    """Generate streams of mock submissions for testing"""

    @staticmethod
    def create_subreddit_generator(
        subreddit_name: str = "test",
        count: int = 100,
        score_range: tuple = (10, 10000),
        ratio_range: tuple = (0.5, 1.0),
    ) -> list:
        """Generate submissions for a subreddit"""
        submissions = []
        for i in range(count):
            submission = MockSubmissionFactory.create_submission(
                submission_id=f"{subreddit_name}_{i:06d}",
                subreddit=subreddit_name,
                score=random.randint(*score_range),
                upvote_ratio=round(random.uniform(*ratio_range), 2),
                url=f"https://example.com/{subreddit_name}_{i}.jpg",
            )
            submissions.append(submission)
        return submissions

    @staticmethod
    def create_user_submissions(
        user_name: str = "test_user",
        count: int = 50,
    ) -> list:
        """Generate submissions by a user"""
        submissions = []
        for i in range(count):
            submission = MockSubmissionFactory.create_submission(
                submission_id=f"{user_name}_post_{i:06d}",
                author=user_name,
                subreddit=f"r/sub_{i % 5}",  # Distribute across 5 subreddits
            )
            submissions.append(submission)
        return submissions

    @staticmethod
    def create_diverse_submissions(count: int = 100) -> list:
        """Create a diverse set of submissions for comprehensive testing"""
        submissions = []
        
        # Various content types
        content_types = [
            {"url": "https://imgur.com/abc123.jpg", "is_gallery": False, "is_video": False},
            {"url": "https://reddit.com/r/sub/comments/abc/gallery", "is_gallery": True, "is_video": False},
            {"url": "https://v.redd.it/abc123", "is_gallery": False, "is_video": True},
            {"url": "https://gfycat.com/abc", "is_gallery": False, "is_video": True},
            {"url": "https://youtube.com/watch?v=abc", "is_gallery": False, "is_video": False},
            {"url": "https://example.com/selfpost", "is_gallery": False, "is_video": False},
        ]
        
        subreddits = ["gonewild", "test", "pics", "videos", "funny", "videos"]
        
        for i in range(count):
            content = content_types[i % len(content_types)]
            subreddit = subreddits[i % len(subreddits)]
            
            submission = MockSubmissionFactory.create_submission(
                submission_id=f"diverse_{i:06d}",
                subreddit=subreddit,
                **content
            )
            submissions.append(submission)
        
        return submissions


class MockHashDatabase:
    """Mock hash database for testing hash operations"""

    def __init__(self):
        self.hashes = {}  # file_path -> hash
        self.file_sizes = {}  # file_path -> size
        self.modified_times = {}  # file_path -> mtime

    def add_hash(self, file_path: str, hash_value: str, size: int = 1024, mtime: float = None):
        """Add a hash entry"""
        if mtime is None:
            mtime = datetime.now().timestamp()
        
        self.hashes[file_path] = hash_value
        self.file_sizes[file_path] = size
        self.modified_times[file_path] = mtime

    def find_by_hash(self, hash_value: str) -> list:
        """Find files by hash"""
        return [path for path, h in self.hashes.items() if h == hash_value]

    def find_by_size(self, size: int) -> list:
        """Find files by size"""
        return [path for path, s in self.file_sizes.items() if s == size]

    def is_duplicate(self, hash_value: str) -> bool:
        """Check if hash exists"""
        return hash_value in self.hashes.values()

    def get_stats(self) -> dict:
        """Get database statistics"""
        return {
            "total_files": len(self.hashes),
            "total_size": sum(self.file_sizes.values()),
            "unique_hashes": len(set(self.hashes.values())),
        }


# Convenience functions for common test scenarios

def create_test_submissions(count: int = 50, **kwargs):
    """Create a batch of test submissions"""
    return MockSubmissionFactory.create_batch(count, **kwargs)


def create_test_reddit(authenticated: bool = False):
    """Create a test Reddit instance"""
    return MockRedditInstanceFactory.create_mock_reddit(authenticated=authenticated)


def create_diverse_test_data(submission_count: int = 100, comments_per_submission: int = 5):
    """Create a diverse set of test data"""
    submissions = MockSubmissionGenerator.create_diverse_submissions(submission_count)
    comments = {sub.id: MockCommentFactory.create_batch(comments_per_submission) for sub in submissions}
    return submissions, comments


if __name__ == "__main__":
    # Example usage
    print("Creating mock submissions...")
    submissions = MockSubmissionGenerator.create_diverse_submissions(10)
    for sub in submissions:
        print(f"  {sub.id}: {sub.title} ({sub.subreddit.display_name})")
    
    print("\nCreating mock hash database...")
    db = MockHashDatabase()
    db.add_hash("/path/to/file1.jpg", "abc123", size=1024000)
    db.add_hash("/path/to/file2.jpg", "def456", size=2048000)
    print(f"  Stats: {db.get_stats()}")
    print(f"  Is duplicate 'abc123'? {db.is_duplicate('abc123')}")
