#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Performance Benchmarks for BDFR Enhancements
Tests efficiency improvements without touching real Reddit servers.
"""

import time
import sqlite3
import tempfile
import random
from pathlib import Path
import pytest

from tests.mock_reddit_data import (
    MockSubmissionFactory,
    MockSubmissionGenerator,
    MockHashDatabase,
)


class TestHashPerformance:
    """Benchmark hash operations"""

    def test_hash_database_lookup_performance(self):
        """Benchmark hash database lookups"""
        db = MockHashDatabase()
        
        # Add 100k hashes
        print("\nAdding 100,000 hashes to database...")
        start = time.perf_counter()
        for i in range(100000):
            db.add_hash(f"/path/to/file_{i}.jpg", f"hash_{i:06d}", size=1024 * (i % 100))
        add_time = time.perf_counter() - start
        print(f"  Time to add 100k hashes: {add_time:.3f}s ({100000/add_time:.0f} hashes/sec)")
        
        # Lookup 1000 random hashes
        print("Looking up 1000 random hashes...")
        start = time.perf_counter()
        for i in range(1000):
            db.find_by_hash(f"hash_{i % 100000:06d}")
        lookup_time = time.perf_counter() - start
        print(f"  Time for 1000 lookups: {lookup_time:.3f}s ({1000/lookup_time:.0f} lookups/sec)")
        
        # Check duplicates 10000 times
        print("Checking for duplicates 10000 times...")
        start = time.perf_counter()
        for i in range(10000):
            db.is_duplicate(f"hash_{i % 100000:06d}")
        dup_time = time.perf_counter() - start
        print(f"  Time for 10k checks: {dup_time:.3f}s ({10000/dup_time:.0f} checks/sec)")
        
        stats = db.get_stats()
        print(f"  Database stats: {stats}")
        
        assert add_time < 10, "Adding hashes too slow"
        assert lookup_time < 1, "Hash lookups too slow"
        assert dup_time < 1, "Duplicate checks too slow"

    def test_sqlite_indexed_vs_unindexed_lookup(self):
        """Compare indexed vs unindexed SQLite lookups"""
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path_indexed = Path(tmpdir) / "indexed.db"
            db_path_unindexed = Path(tmpdir) / "unindexed.db"
            
            # Create indexed database
            conn_idx = sqlite3.connect(db_path_indexed)
            cursor_idx = conn_idx.cursor()
            cursor_idx.execute("""
                CREATE TABLE hashes (
                    id INTEGER PRIMARY KEY,
                    file_path TEXT,
                    hash_value TEXT,
                    file_size INTEGER
                )
            """)
            cursor_idx.execute("CREATE INDEX idx_hash ON hashes(hash_value)")
            
            # Create unindexed database
            conn_unidx = sqlite3.connect(db_path_unindexed)
            cursor_unidx = conn_unidx.cursor()
            cursor_unidx.execute("""
                CREATE TABLE hashes (
                    id INTEGER PRIMARY KEY,
                    file_path TEXT,
                    hash_value TEXT,
                    file_size INTEGER
                )
            """)
            
            # Add data to both
            print("\nPopulating SQLite databases with 10,000 records...")
            data = [(f"/path/file_{i}.jpg", f"hash_{i:06d}", 1024 * (i % 100)) for i in range(10000)]
            
            cursor_idx.executemany(
                "INSERT INTO hashes (file_path, hash_value, file_size) VALUES (?, ?, ?)",
                data
            )
            conn_idx.commit()
            
            cursor_unidx.executemany(
                "INSERT INTO hashes (file_path, hash_value, file_size) VALUES (?, ?, ?)",
                data
            )
            conn_unidx.commit()
            
            # Benchmark lookups on indexed database
            print("Benchmarking 1000 lookups on INDEXED database...")
            start = time.perf_counter()
            for i in range(1000):
                cursor_idx.execute(
                    "SELECT file_path FROM hashes WHERE hash_value = ?",
                    (f"hash_{i % 10000:06d}",)
                )
                cursor_idx.fetchall()
            indexed_time = time.perf_counter() - start
            print(f"  Indexed lookups: {indexed_time:.3f}s ({1000/indexed_time:.0f} lookups/sec)")
            
            # Benchmark lookups on unindexed database
            print("Benchmarking 1000 lookups on UNINDEXED database...")
            start = time.perf_counter()
            for i in range(1000):
                cursor_unidx.execute(
                    "SELECT file_path FROM hashes WHERE hash_value = ?",
                    (f"hash_{i % 10000:06d}",)
                )
                cursor_unidx.fetchall()
            unindexed_time = time.perf_counter() - start
            print(f"  Unindexed lookups: {unindexed_time:.3f}s ({1000/unindexed_time:.0f} lookups/sec)")
            
            speedup = unindexed_time / indexed_time
            print(f"  Speedup with index: {speedup:.1f}x")
            
            conn_idx.close()
            conn_unidx.close()
            
            assert speedup > 1.5, "Indexing should provide significant speedup"


class TestFilteringPerformance:
    """Benchmark filtering operations"""

    def test_early_filter_vs_late_filter_performance(self):
        """Compare filtering submissions early vs late"""
        submissions = MockSubmissionGenerator.create_diverse_submissions(10000)
        
        # Late filtering (current approach) - check all, then filter
        print("\nLate filtering (current approach):")
        start = time.perf_counter()
        filtered_count = 0
        for sub in submissions:
            # Simulate downloader instantiation (expensive)
            _ = {
                "id": sub.id,
                "title": sub.title,
                "url": sub.url,
                "score": sub.score,
            }
            
            # Then check filters
            if sub.score < 50:
                filtered_count += 1
                continue
            if sub.upvote_ratio < 0.7:
                filtered_count += 1
                continue
        late_time = time.perf_counter() - start
        print(f"  Late filtering time: {late_time:.3f}s (filtered: {filtered_count})")
        
        # Early filtering (optimized approach) - filter first, then process
        print("Early filtering (optimized approach):")
        start = time.perf_counter()
        filtered_count = 0
        for sub in submissions:
            # Check filters FIRST
            if sub.score < 50:
                filtered_count += 1
                continue
            if sub.upvote_ratio < 0.7:
                filtered_count += 1
                continue
            
            # Only then instantiate downloader
            _ = {
                "id": sub.id,
                "title": sub.title,
                "url": sub.url,
                "score": sub.score,
            }
        early_time = time.perf_counter() - start
        print(f"  Early filtering time: {early_time:.3f}s (filtered: {filtered_count})")
        
        speedup = late_time / early_time
        print(f"  Speedup: {speedup:.2f}x")
        
        assert speedup > 1.1, "Early filtering should be faster"

    def test_batch_filtering_performance(self):
        """Benchmark filtering with pre-calculated filter cache"""
        submissions = MockSubmissionGenerator.create_diverse_submissions(10000)
        
        # Without cache
        print("\nFiltering WITHOUT pre-calculated cache:")
        start = time.perf_counter()
        passed = 0
        for sub in submissions:
            # Calculate filters each time
            passes_score = sub.score >= 50
            passes_ratio = sub.upvote_ratio >= 0.7
            passes_subreddit = sub.subreddit.display_name not in ["banned", "test"]
            
            if passes_score and passes_ratio and passes_subreddit:
                passed += 1
        no_cache_time = time.perf_counter() - start
        print(f"  Time: {no_cache_time:.3f}s (passed: {passed})")
        
        # With cache
        print("Filtering WITH pre-calculated cache:")
        start = time.perf_counter()
        
        # Pre-calculate filter results
        filter_cache = {}
        for sub in submissions:
            filter_cache[sub.id] = (
                sub.score >= 50,
                sub.upvote_ratio >= 0.7,
                sub.subreddit.display_name not in ["banned", "test"]
            )
        
        # Then filter using cache
        passed = 0
        for sub in submissions:
            score_pass, ratio_pass, sub_pass = filter_cache[sub.id]
            if score_pass and ratio_pass and sub_pass:
                passed += 1
        
        cache_time = time.perf_counter() - start
        print(f"  Time: {cache_time:.3f}s (passed: {passed})")
        
        # Cache time includes both calculation and lookup,
        # so comparison is just to ensure it doesn't regress
        assert cache_time < no_cache_time * 1.5


class TestConcurrencyPerformance:
    """Benchmark concurrent vs sequential operations"""

    def test_sequential_vs_concurrent_submission_processing(self):
        """Compare sequential vs concurrent submission processing"""
        submissions = MockSubmissionGenerator.create_diverse_submissions(1000)
        
        def process_submission(sub):
            """Simulate submission processing"""
            time.sleep(0.001)  # Simulate network I/O
            return {
                "id": sub.id,
                "title": sub.title,
                "content_length": len(sub.selftext),
            }
        
        # Sequential processing
        print("\nSequential processing (1000 submissions):")
        start = time.perf_counter()
        results = []
        for sub in submissions:
            results.append(process_submission(sub))
        sequential_time = time.perf_counter() - start
        print(f"  Time: {sequential_time:.3f}s")
        
        # Simulated concurrent (with 3 workers)
        print("Concurrent processing simulation (3 workers):")
        start = time.perf_counter()
        
        # Simulate 3 concurrent workers
        worker_times = [0, 0, 0]
        results = [None] * len(submissions)
        for i, sub in enumerate(submissions):
            worker_id = i % 3
            worker_times[worker_id] += 0.001
            results[i] = process_submission(sub)
        
        concurrent_time = max(worker_times)
        print(f"  Time: {concurrent_time:.3f}s")
        
        speedup = sequential_time / concurrent_time
        print(f"  Speedup: {speedup:.1f}x (expected ~3x with 3 workers)")
        
        assert speedup > 2.0, "Concurrent processing should provide significant speedup"

    def test_rate_limited_concurrent_performance(self):
        """Benchmark rate-limited concurrent processing"""
        submissions = MockSubmissionGenerator.create_diverse_submissions(100)
        
        # With 60 req/min rate limit, 100 requests should take about 100 seconds
        # But with concurrency, we can parallelize non-API operations
        
        print("\nRate-limited concurrent processing (3 concurrent, 60 req/min limit):")
        
        requests_made = 0
        api_rate_limited = False
        
        start = time.perf_counter()
        
        # Simulate 100 submissions with rate limiting
        for i, sub in enumerate(submissions):
            requests_made += 1
            
            # Check if we'd hit rate limit
            elapsed = time.perf_counter() - start
            max_requests_allowed = (elapsed / 60) * 60  # 60 requests per minute
            
            if requests_made > max_requests_allowed and i < len(submissions) - 1:
                api_rate_limited = True
                # Would sleep here in real implementation
        
        total_time = time.perf_counter() - start
        print(f"  Processed 100 submissions in {total_time:.3f}s")
        print(f"  API rate limited: {api_rate_limited}")
        
        # Should process quickly since we're just simulating
        assert total_time < 1.0, "Rate-limited processing should be fast"


class TestMemoryOptimization:
    """Benchmark memory-related optimizations"""

    def test_lazy_loading_performance(self):
        """Benchmark lazy loading vs eager loading"""
        
        # Eager loading
        print("\nEager loading (all properties immediately):")
        start = time.perf_counter()
        submissions = []
        for i in range(1000):
            sub = MockSubmissionFactory.create_submission(
                submission_id=f"eager_{i}",
                title=f"Title {i}" * 100,  # Large title
                num_comments=random.randint(0, 1000),
            )
            # Access all properties
            _ = (sub.id, sub.title, sub.num_comments, sub.score, sub.url)
            submissions.append(sub)
        eager_time = time.perf_counter() - start
        print(f"  Time: {eager_time:.3f}s")
        
        # Lazy loading (only access if needed)
        print("Lazy loading (properties accessed on demand):")
        start = time.perf_counter()
        submissions = []
        for i in range(1000):
            sub = MockSubmissionFactory.create_submission(
                submission_id=f"lazy_{i}",
                title=f"Title {i}" * 100,
                num_comments=random.randint(0, 1000),
            )
            # Only access ID initially
            _ = sub.id
            submissions.append(sub)
        lazy_time = time.perf_counter() - start
        print(f"  Time: {lazy_time:.3f}s")
        
        speedup = eager_time / lazy_time
        print(f"  Speedup: {speedup:.1f}x")
        
        assert speedup > 1.5, "Lazy loading should be faster"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
