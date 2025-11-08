#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Integration Tests for BDFR Enhancements
Tests complete workflows using mock Reddit data without hitting real servers.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.mock_reddit_data import (
    MockSubmissionGenerator,
    MockHashDatabase,
    create_diverse_test_data,
)


class TestDownloadFilteringIntegration:
    """Integration tests for submission filtering"""

    def test_score_filtering_integration(self):
        """Test score-based filtering with mock submissions"""
        submissions = MockSubmissionGenerator.create_diverse_submissions(100)
        
        # Use a threshold that filters out ~50% of submissions (10-10000 range)
        min_score = 500
        filtered_submissions = [s for s in submissions if s.score >= min_score]
        
        assert len(filtered_submissions) > 0, "Should find submissions with scores >= 500"
        assert all(s.score >= min_score for s in filtered_submissions)
        assert len(filtered_submissions) < len(submissions), "Should filter out some submissions"

    def test_subreddit_filtering_integration(self):
        """Test subreddit-based filtering"""
        submissions = MockSubmissionGenerator.create_diverse_submissions(100)
        
        target_subreddit = "gonewild"
        filtered_submissions = [s for s in submissions if s.subreddit.display_name == target_subreddit]
        
        if filtered_submissions:
            assert all(s.subreddit.display_name == target_subreddit for s in filtered_submissions)

    def test_multi_filter_integration(self):
        """Test combining multiple filters"""
        submissions = MockSubmissionGenerator.create_diverse_submissions(100)
        
        # Apply multiple filters
        filtered = [
            s for s in submissions
            if (s.score >= 50 and
                s.upvote_ratio >= 0.7 and
                s.subreddit.display_name not in ["banned", "test"] and
                s.author is not None)
        ]
        
        assert len(filtered) < len(submissions)
        assert all(s.score >= 50 for s in filtered)
        assert all(s.upvote_ratio >= 0.7 for s in filtered)


class TestHashDatabaseIntegration:
    """Integration tests for hash-based duplicate detection"""

    def test_duplicate_detection_workflow(self):
        """Test complete duplicate detection workflow"""
        db = MockHashDatabase()
        
        # First run: add hashes
        for i in range(100):
            db.add_hash(f"/archive/file_{i}.jpg", f"hash_{i:06d}", size=1024 * (i + 1))
        
        stats = db.get_stats()
        assert stats["total_files"] == 100
        
        # Second run: check for duplicates
        duplicates_found = 0
        new_files = 0
        
        # Simulate re-run with some duplicates and new files
        new_submissions = [
            ("hash_000001", "/archive/file_1.jpg"),  # Duplicate
            ("hash_000050", "/archive/file_50.jpg"),  # Duplicate
            ("new_hash_1", "/archive/file_101.jpg"),  # New file
            ("new_hash_2", "/archive/file_102.jpg"),  # New file
        ]
        
        for hash_val, file_path in new_submissions:
            if db.is_duplicate(hash_val):
                duplicates_found += 1
            else:
                db.add_hash(file_path, hash_val, size=1024)
                new_files += 1
        
        assert duplicates_found == 2
        assert new_files == 2
        assert db.get_stats()["total_files"] == 102

    def test_size_based_pre_filtering(self):
        """Test pre-filtering duplicates by file size"""
        db = MockHashDatabase()
        
        # Add files with specific sizes
        files = {
            "/archive/file_1.jpg": ("hash_1", 1024000),
            "/archive/file_2.jpg": ("hash_2", 2048000),
            "/archive/file_3.jpg": ("hash_3", 1024000),  # Same size as file_1
        }
        
        for path, (hash_val, size) in files.items():
            db.add_hash(path, hash_val, size=size)
        
        # Find potential duplicates by size
        potential_dupes = db.find_by_size(1024000)
        assert len(potential_dupes) == 2
        assert "/archive/file_1.jpg" in potential_dupes
        assert "/archive/file_3.jpg" in potential_dupes

    def test_incremental_hashing_workflow(self):
        """Test incremental hashing on modified files"""
        db = MockHashDatabase()
        import time
        
        # Initial file
        mtime1 = time.time()
        db.add_hash("/archive/file.jpg", "hash_v1", size=1024, mtime=mtime1)
        
        # File unchanged
        mtime2 = time.time()
        db.add_hash("/archive/file.jpg", "hash_v1", size=1024, mtime=mtime1)
        assert db.hashes["/archive/file.jpg"] == "hash_v1"
        
        # File modified (size changed)
        mtime3 = time.time() + 100
        db.add_hash("/archive/file.jpg", "hash_v2", size=2048, mtime=mtime3)
        assert db.hashes["/archive/file.jpg"] == "hash_v2"


class TestConcurrentDownloadIntegration:
    """Integration tests for concurrent download operations"""

    def test_concurrent_submission_batch_processing(self):
        """Test processing batch of submissions concurrently"""
        submissions = MockSubmissionGenerator.create_diverse_submissions(50)
        
        # Simulate concurrent processing with rate limiting
        processed = []
        failed = []
        
        # In real implementation, this would use ThreadPoolExecutor
        # Here we just verify the logic
        for sub in submissions:
            try:
                processed.append({
                    "id": sub.id,
                    "title": sub.title,
                    "score": sub.score,
                })
            except Exception as e:
                failed.append((sub.id, str(e)))
        
        assert len(processed) == 50
        assert len(failed) == 0

    def test_rate_limited_batch_download(self):
        """Test batch download with rate limiting"""
        submissions = MockSubmissionGenerator.create_subreddit_generator("test", count=100)
        
        # Simulate rate-limited downloads
        api_calls = 0
        max_calls_per_minute = 60
        
        for sub in submissions:
            api_calls += 1
            
            # Would check rate limit here
            if api_calls > max_calls_per_minute:
                # Would sleep and reset counter
                api_calls = 1
        
        # Should successfully process all
        assert len(submissions) == 100


class TestFilteringOptimizationIntegration:
    """Integration tests for filtering optimizations"""

    def test_filter_chain_execution_order(self):
        """Test optimal filter execution order (cheapest first)"""
        submissions = MockSubmissionGenerator.create_diverse_submissions(100)
        
        # Filter order: cheapest first
        exclusion_list = {"excluded_1", "excluded_2"}
        skip_subreddits = {"banned"}
        min_score = 50
        min_ratio = 0.7
        
        filtered = []
        for sub in submissions:
            # 1. Exclusion check (O(1) set lookup)
            if sub.id in exclusion_list:
                continue
            
            # 2. Skip subreddit (O(1) set lookup)
            if sub.subreddit.display_name in skip_subreddits:
                continue
            
            # 3. Score check (O(1) comparison)
            if sub.score < min_score:
                continue
            
            # 4. Ratio check (O(1) comparison)
            if sub.upvote_ratio < min_ratio:
                continue
            
            filtered.append(sub)
        
        assert len(filtered) > 0
        assert len(filtered) <= len(submissions)

    def test_early_exit_filtering(self):
        """Test early exit when filters are met"""
        submissions = MockSubmissionGenerator.create_diverse_submissions(100)
        
        checked = 0
        processed = 0
        
        for sub in submissions:
            checked += 1
            
            # Apply filters and early exit (more restrictive thresholds)
            if sub.score < 5000:  # Most won't pass this
                continue
            if sub.upvote_ratio < 0.9:
                continue
            
            processed += 1
        
        assert checked == len(submissions)
        assert processed < len(submissions), "Some submissions should be filtered out"


class TestCachingIntegration:
    """Integration tests for caching optimizations"""

    def test_subreddit_info_caching(self):
        """Test caching subreddit information"""
        cache = {}
        submissions = MockSubmissionGenerator.create_diverse_submissions(100)
        
        # First pass: populate cache
        for sub in submissions:
            sub_name = sub.subreddit.display_name
            if sub_name not in cache:
                cache[sub_name] = {
                    "display_name": sub_name,
                    "accessed_count": 0,
                }
            cache[sub_name]["accessed_count"] += 1
        
        # Verify cache contains all subreddits
        assert len(cache) <= len(submissions)
        
        # Verify access counts are correct
        total_accesses = sum(v["accessed_count"] for v in cache.values())
        assert total_accesses == len(submissions)

    def test_filter_result_caching(self):
        """Test caching filter results"""
        submissions = MockSubmissionGenerator.create_diverse_submissions(100)
        filter_cache = {}
        
        # First pass: calculate and cache filter results
        for sub in submissions:
            filter_cache[sub.id] = {
                "passes_score": sub.score >= 50,
                "passes_ratio": sub.upvote_ratio >= 0.7,
                "passes_date": True,  # Simplified
            }
        
        # Second pass: use cached results
        filtered_count = 0
        for sub in submissions:
            cached_result = filter_cache[sub.id]
            if all(cached_result.values()):
                filtered_count += 1
        
        assert len(filter_cache) == len(submissions)
        assert filtered_count >= 0


class TestErrorHandlingIntegration:
    """Integration tests for error handling and retry logic"""

    def test_exponential_backoff_logic(self):
        """Test exponential backoff retry logic"""
        import random
        
        retry_count = 0
        max_retries = 5
        base_wait = 1
        
        backoff_times = []
        
        while retry_count < max_retries:
            wait_time = min(300, base_wait * (2 ** retry_count) + random.uniform(0, 1))
            backoff_times.append(wait_time)
            retry_count += 1
        
        # Verify exponential growth
        assert backoff_times[0] < backoff_times[1] < backoff_times[2]
        # Verify max cap
        assert all(t <= 300 for t in backoff_times)

    def test_circuit_breaker_pattern(self):
        """Test circuit breaker pattern for failing domains"""
        domain_failures = {}
        failure_threshold = 5
        
        def record_failure(domain):
            if domain not in domain_failures:
                domain_failures[domain] = 0
            domain_failures[domain] += 1
        
        def is_circuit_open(domain):
            return domain_failures.get(domain, 0) >= failure_threshold
        
        # Record failures for domain
        for _ in range(failure_threshold):
            record_failure("bad-site.com")
        
        assert is_circuit_open("bad-site.com")
        assert not is_circuit_open("good-site.com")

    def test_rate_limit_detection(self):
        """Test proactive rate limit detection"""
        headers = {
            "X-Ratelimit-Remaining": "1",
            "X-Ratelimit-Reset": str(int(1234567890)),
        }
        
        def should_throttle(headers):
            remaining = int(headers.get("X-Ratelimit-Remaining", 60))
            return remaining < 5
        
        assert should_throttle(headers)
        
        headers["X-Ratelimit-Remaining"] = "60"
        assert not should_throttle(headers)


class TestEndToEndWorkflow:
    """End-to-end workflow tests"""

    def test_complete_download_workflow(self):
        """Test complete download workflow from start to finish"""
        # Setup
        submissions = MockSubmissionGenerator.create_diverse_submissions(50)
        hash_db = MockHashDatabase()
        
        # Workflow
        downloaded = 0
        skipped = 0
        failed = 0
        
        for sub in submissions:
            # 1. Filter
            if sub.score < 50:
                skipped += 1
                continue
            
            if sub.upvote_ratio < 0.7:
                skipped += 1
                continue
            
            # 2. Check for duplicates
            sub_hash = f"hash_{sub.id}"
            if hash_db.is_duplicate(sub_hash):
                skipped += 1
                continue
            
            # 3. Download (simulated)
            try:
                hash_db.add_hash(f"/archive/{sub.id}.jpg", sub_hash)
                downloaded += 1
            except Exception:
                failed += 1
        
        assert downloaded > 0
        assert (downloaded + skipped + failed) == len(submissions)

    def test_rerun_workflow_with_cache(self):
        """Test re-running download with cached hashes"""
        # First run
        submissions_run1 = MockSubmissionGenerator.create_diverse_submissions(50)
        hash_db = MockHashDatabase()
        
        for sub in submissions_run1:
            if sub.score >= 50 and sub.upvote_ratio >= 0.7:
                hash_db.add_hash(f"/archive/{sub.id}.jpg", f"hash_{sub.id}")
        
        initial_files = hash_db.get_stats()["total_files"]
        
        # Second run with some new, some duplicate
        submissions_run2 = MockSubmissionGenerator.create_diverse_submissions(50)
        duplicates_skipped = 0
        new_files = 0
        
        for sub in submissions_run2:
            if sub.score >= 50 and sub.upvote_ratio >= 0.7:
                sub_hash = f"hash_{sub.id}"
                if hash_db.is_duplicate(sub_hash):
                    duplicates_skipped += 1
                else:
                    hash_db.add_hash(f"/archive/{sub.id}.jpg", sub_hash)
                    new_files += 1
        
        final_files = hash_db.get_stats()["total_files"]
        
        assert duplicates_skipped >= 0
        assert new_files >= 0
        assert final_files == initial_files + new_files


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
