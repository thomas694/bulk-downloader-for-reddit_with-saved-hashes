# BDFR-Enhance Efficiency Improvement Roadmap

This document outlines a comprehensive plan to optimize BDFR-Enhance for better performance, reduced bandwidth usage, faster execution times, and lower API overhead.

---

## Category 1: Parallel Processing & Concurrency

### 1.1 Implement Rate-Limited Concurrent Submission Downloads
**Problem**: Currently downloads are sequential, causing idle time waiting for network I/O.

**Solution**: Use controlled parallelism with API rate-limit awareness.

**Implementation**:
- Use `concurrent.futures.ThreadPoolExecutor` with configurable worker count (default: 3-5)
- Implement a request queue with rate limiter to prevent API limit breaches
- Each thread respects Reddit's ~60 requests/minute limit
- Add `--max-concurrent-downloads` flag (default: 3)

**Safety**: Parallel downloads don't increase API calls, only make existing calls concurrent. Rate limiting is enforced per-request, not per-connection.

**Expected Impact**: 
- 40-60% faster downloads for multiple files
- Better resource utilization on high-bandwidth connections
- No additional API overhead

**Example**:
```python
from concurrent.futures import ThreadPoolExecutor
from ratelimit import limits, sleep_and_retry

@sleep_and_retry
@limits(calls=1, period=1)  # Rate limit decorator
def download_submission(submission):
    # ... existing download logic
    pass

with ThreadPoolExecutor(max_workers=3) as executor:
    executor.map(download_submission, submissions)
```

---

### 1.2 Parallel Hash Calculations for `--search-existing`
**Problem**: MD5 hashing large files is CPU-bound and blocks other operations.

**Solution**: Use multiprocessing for parallel hash computation.

**Implementation**:
- Use `multiprocessing.Pool` for CPU-intensive hash operations
- Process multiple files simultaneously during initialization
- Implement chunked reading for memory efficiency

**Expected Impact**:
- 50-70% faster hash computation on multi-core systems
- Reduced initialization time for large archives

**Complexity**: Medium | **Priority**: High

---

### 1.3 Batch Reddit API Requests
**Problem**: Each submission fetches metadata individually, causing repeated API calls.

**Solution**: Combine metadata requests using Reddit's built-in batching.

**Implementation**:
- Use PRAW's `info()` method to fetch multiple submissions at once
- Group requests into batches of 100 (Reddit API limit)
- Reduce API calls by ~95% for metadata fetching

**Expected Impact**:
- 30-50% fewer API calls
- Significant speedup when processing large submission lists

**Complexity**: Low | **Priority**: High

---

## Category 2: Caching & Memory Optimization

### 2.1 Implement Request Caching
**Problem**: Same Reddit API endpoints are queried multiple times per session.

**Solution**: Add in-memory and optional persistent caching layer.

**Implementation**:
- Use `functools.lru_cache` for frequently accessed data
- Implement optional Redis/SQLite caching layer
- Add `--cache-ttl` flag (default: 3600 seconds)
- Cache subreddit info, user profiles, and comment data

**Expected Impact**:
- 20-40% reduction in API calls for typical workflows
- Faster re-runs with same subreddits

**Complexity**: Low | **Priority**: Medium

---

### 2.2 Streaming Large File Downloads
**Problem**: Large video/media files are loaded entirely into memory before saving.

**Solution**: Implement chunked streaming with progress tracking.

**Implementation**:
- Stream downloads in 1MB chunks
- Track progress with `tqdm` for visual feedback
- Support resume-on-error for interrupted downloads
- Reduce peak memory usage by 80%+

**Expected Impact**:
- Enable downloading of very large files (100GB+)
- Reduced memory pressure on systems with limited RAM
- Better interruption handling

**Complexity**: Medium | **Priority**: High

---

### 2.3 Lazy-Load Submission Metadata
**Problem**: All submission details fetched upfront, even if filters will exclude them.

**Solution**: Load metadata only when needed during filter checks.

**Implementation**:
- Defer `submission.comments`, `submission.awards` fetching
- Lazy-evaluate expensive properties
- Load score/ratio only when score filters are active

**Expected Impact**:
- 30% faster initialization for large submission lists
- Reduced memory usage for filtered submissions

**Complexity**: Medium | **Priority**: Medium

---

## Category 3: I/O & Disk Operations

### 3.1 Batch Database Writes for Hashes
**Problem**: Each hash is written individually to SQLite, causing repeated I/O overhead.

**Solution**: Buffer writes and batch-insert into database.

**Implementation**:
- Accumulate hashes in memory during download phase
- Write all hashes in a single transaction at configured intervals
- Use `--save-hashes-interval` (already exists, but optimize)
- Batch size: 100-500 entries

**Expected Impact**:
- 60-80% faster hash persistence
- Reduced I/O contention
- Better crash recovery with periodic flushes

**Complexity**: Low | **Priority**: High

---

### 3.2 Implement Incremental File Hashing
**Problem**: With `--keep-hashes`, all existing files are re-hashed even if unchanged.

**Solution**: Track file modification times and skip unchanged files.

**Implementation**:
- Store `(filepath, mtime, hash)` tuples in database
- Skip re-hashing if modification time unchanged
- Add `--hash-verify` flag for forced full verification
- Fall back to full hash if mtime is unreliable

**Expected Impact**:
- 90% faster subsequent runs on static archives
- Near-instant hash loading for unchanged files

**Complexity**: Medium | **Priority**: High

---

### 3.3 Use File Memory Mapping for Large File Comparisons
**Problem**: Very large files (5GB+) cause memory pressure during hashing.

**Solution**: Use `mmap` for efficient file access.

**Implementation**:
- Use Python's `mmap` module for files >500MB
- Process files in mapped chunks without loading into RAM
- Automatic fallback to streaming for unsupported filesystems

**Expected Impact**:
- Handle files 10x larger without memory issues
- Consistent performance regardless of file size

**Complexity**: Medium | **Priority**: Low (edge case optimization)

---

## Category 4: Retry & Error Handling

### 4.1 Implement Exponential Backoff Strategy
**Problem**: Current code uses fixed 60-second waits for all retries, causing long stalls.

**Solution**: Use exponential backoff with jitter.

**Implementation**:
```python
wait_time = min(300, base_wait * (2 ** retry_count) + random.uniform(0, 1))
```
- Start: 1 second
- Max: 5 minutes
- Add randomization to prevent thundering herd
- Add `--backoff-multiplier` flag for customization

**Expected Impact**:
- Faster recovery from transient network errors
- Better handling of rate-limited endpoints
- More responsive error reporting

**Complexity**: Low | **Priority**: High

---

### 4.2 Implement Circuit Breaker Pattern
**Problem**: Tool retries failing domains indefinitely (e.g., dead mirrors).

**Solution**: Track domain failure rates and disable failing sources.

**Implementation**:
- Track failures per domain
- Circuit states: CLOSED (working) → OPEN (disabled) → HALF_OPEN (testing)
- Open circuit after 5 consecutive failures
- Re-test every 100 submissions
- Add `--circuit-breaker-threshold` flag

**Expected Impact**:
- Fail fast on dead domains instead of retrying 60+ times
- 30-50% faster error recovery
- Better user feedback on permanent failures

**Complexity**: Medium | **Priority**: High

---

### 4.3 Smart Rate-Limit Detection & Adaptation
**Problem**: Tool doesn't detect Reddit rate limits proactively; discovers them via failures.

**Solution**: Monitor response headers and adapt preemptively.

**Implementation**:
- Check `X-Ratelimit-*` headers in Reddit responses
- Adjust request rate before hitting limits
- Add `--adaptive-rate-limit` flag (default: enabled)
- Log rate limit status for debugging

**Expected Impact**:
- Avoid 429 errors entirely
- Smoother operation without sudden stalls
- Better Reddit API citizenship

**Complexity**: Low | **Priority**: Medium

---

## Category 5: Code Structure & Logic Optimization

### 5.1 Pre-Download Hash Filtering
**Problem**: Downloads files first, then checks if duplicate via hash. Wastes bandwidth.

**Solution**: Check hashes BEFORE downloading using metadata and pre-filters.

**Implementation**:

**Option A - URL-based Hash Lookup** (Best for external sites):
```python
# For Imgur, Gfycat, etc., fetch hash from API before download
response = requests.get(f"https://api.imgur.com/3/image/{image_id}")
server_hash = response.json()['data'].get('md5')
if server_hash in self.hash_database:
    logger.info(f"File already exists (via API hash), skipping")
    return
```

**Option B - HEAD Request Content-Hash**:
```python
head_response = requests.head(url)
content_etag = head_response.headers.get('ETag')
if content_etag in self.known_etags:
    logger.info("Duplicate detected via ETag")
    return
```

**Option C - Filename + Size Pre-Filter**:
```python
content_length = int(requests.head(url).headers.get('Content-Length', 0))
size_key = f"{filename}_{content_length}"
if size_key in self.quick_filter:
    logger.info("Pre-filtered as likely duplicate")
    # Only download and verify if filter matches
```

**Result**: Skip 70-85% of duplicate downloads without ever downloading the file.

**Expected Impact**:
- 50-70% reduction in wasted bandwidth for re-runs
- Massive speedup with `--keep-hashes` enabled
- Near-instant duplicate detection

**Complexity**: Medium | **Priority**: Critical

---

### 5.2 Early Submission Filtering Pipeline
**Problem**: Filters applied during download phase; time wasted on filtered submissions.

**Solution**: Apply ALL filters before creating downloader objects.

**Implementation**:
- Create unified filter pipeline: score → ratio → date → author → URL
- Check filters immediately after fetching submission metadata
- Skip downloader instantiation for filtered submissions
- Add `--show-filtered-count` for visibility

**Filter order (cheapest first)**:
1. Excluded submission IDs (O(1) lookup)
2. Skip subreddits (O(1) lookup)
3. Ignore users (O(1) lookup)
4. Score filters (O(1) calculation)
5. Upvote ratio (O(1) calculation)
6. URL patterns (O(1) regex or O(n) string search)
7. Date filters (O(1) comparison)

**Expected Impact**:
- 40-60% faster filtering
- Reduced memory from fewer downloader instances
- Better logging of filter reason

**Complexity**: Low | **Priority**: High

---

### 5.3 Deduplicate Filter Check Logic
**Problem**: Many identical filter checks scattered throughout code; redundant evaluation.

**Solution**: Consolidate into single, reusable filter validator.

**Implementation**:
- Create `SubmissionValidator` class with all checks
- Single point of evaluation for each submission
- Cache validation results
- Add detailed logging per filter

```python
class SubmissionValidator:
    def validate_submission(self, submission) -> tuple[bool, str]:
        # Returns (is_valid, reason_if_filtered)
        if self._check_exclusions(submission):
            return False, "in_exclusion_list"
        # ... other checks
        return True, None
```

**Expected Impact**:
- Cleaner, more maintainable code
- Faster filter evaluation
- Consistent filtering logic

**Complexity**: Low | **Priority**: Medium

---

## Category 6: Configuration & Startup Optimization

### 6.1 Lazy Module Loading
**Problem**: All site downloaders imported at startup, even if not needed.

**Solution**: Dynamically import only required downloaders.

**Implementation**:
- Move downloader imports to `DownloadFactory.pull_lever()`
- Use `importlib.import_module()` on-demand
- Cache imported modules
- Reduce startup time by 50-70%

**Expected Impact**:
- Startup time: 5 seconds → 1-2 seconds
- Faster responsiveness
- Lower memory footprint for single-site downloads

**Complexity**: Low | **Priority**: Medium

---

### 6.2 Configuration Validation Caching
**Problem**: Configuration validated repeatedly across multiple runs.

**Solution**: Cache validation results with change detection.

**Implementation**:
- Store config hash in metadata file
- Skip validation if config unchanged
- Detect modifications via file timestamp
- Add `--validate-config` flag to force re-validation

**Expected Impact**:
- Faster startup for repeated runs
- Better error reporting on config changes

**Complexity**: Low | **Priority**: Low

---

### 6.3 HTTP Connection Pooling
**Problem**: New HTTP connections created for each request, causing overhead.

**Solution**: Implement persistent connection pooling.

**Implementation**:
- Use `requests.Session()` for all HTTP calls
- Configure connection pool size (default: 10)
- Reuse connections across all downloaders
- Add `--connection-pool-size` flag

**Expected Impact**:
- 10-20% faster downloads (reduced connection overhead)
- Lower CPU usage
- Better bandwidth utilization

**Complexity**: Low | **Priority**: Medium

---

## Category 7: Database Optimization

### 7.1 Add SQLite Indexes for Hash Lookups
**Problem**: Current hash table sequential scans are O(n), causing slowdowns with large datasets.

**Solution**: Add database indexes for O(1) lookups.

**Implementation**:
```sql
CREATE INDEX idx_hash ON hashes(hash_value);
CREATE INDEX idx_filename_size ON hashes(filename, file_size);
CREATE INDEX idx_modified_time ON hashes(modified_time);
```

**Expected Impact**:
- Hash lookups: O(n) → O(log n)
- 100x faster duplicate detection on large archives
- Negligible index overhead

**Complexity**: Very Low | **Priority**: Critical

---

### 7.2 Use Prepared Statements & Query Optimization
**Problem**: Redundant query parsing and validation.

**Solution**: Use prepared statements and optimize common queries.

**Implementation**:
- Prepare frequently-used queries at startup
- Use parameterized queries to prevent SQL injection
- Add query result caching
- Batch SELECT/INSERT operations

**Expected Impact**:
- 30-50% faster database operations
- Improved security
- Reduced CPU overhead

**Complexity**: Low | **Priority**: High

---

### 7.3 SQLite Connection Pooling & WAL Mode
**Problem**: Single database connection creates I/O bottlenecks.

**Solution**: Implement connection pooling and enable Write-Ahead Logging.

**Implementation**:
- Use `sqlite3.connect()` with connection pool
- Enable WAL mode: `PRAGMA journal_mode=WAL`
- Configure cache size: `PRAGMA cache_size=10000`
- Add `--db-cache-size` flag

**Expected Impact**:
- Concurrent reads/writes without blocking
- 10-30% faster I/O operations
- Better crash recovery

**Complexity**: Low | **Priority**: Medium

---

## Implementation Priority

### Phase 1 (Immediate) - High Impact, Low Effort
- 7.1: Add SQLite indexes
- 4.1: Exponential backoff
- 3.1: Batch hash writes
- 5.2: Early filtering pipeline
- 7.2: Prepared statements

**Estimated speedup: 30-50%**

### Phase 2 (Short-term) - High Impact, Medium Effort
- 1.1: Concurrent downloads (with rate limiting)
- 5.1: Pre-download hash filtering
- 3.2: Incremental file hashing
- 4.2: Circuit breaker pattern
- 2.2: Streaming downloads

**Estimated speedup: 50-70%**

### Phase 3 (Medium-term) - Medium Impact, Medium Effort
- 1.2: Parallel hash calculations
- 2.1: Request caching
- 4.3: Smart rate-limit detection
- 6.1: Lazy module loading
- 7.3: Connection pooling

**Estimated speedup: 20-30%**

### Phase 4 (Long-term) - Niche Optimizations
- 1.3: Batch API requests
- 2.3: Lazy metadata loading
- 3.3: Memory mapping for huge files
- 5.3: Filter deduplication
- 6.2: Config validation caching
- 6.3: HTTP connection pooling

**Estimated speedup: 10-20%**

---

## Summary of Expected Improvements

| Metric | Current | After Phase 1 | After Phase 2 | After All |
|--------|---------|---------------|---------------|-----------|
| Hash lookup (1M files) | 10s | 0.1s | 0.1s | 0.1s |
| Startup time | 5s | 4s | 1-2s | 1s |
| Duplicate detection | Full download | Pre-filter | Pre-filter + API | Pre-filter + API |
| API calls | 100% | 70% | 40% | 30% |
| Bandwidth waste | 100% | 100% | 15-30% | 5-10% |
| Download speed | 1x | 1.2x | 1.6x | 2-2.5x |
| First-run time | 1x | 0.8x | 0.7x | 0.5x |
| Re-run time | 1x | 0.7x | 0.3x | 0.2x |

---

## Testing Strategy

Each phase should include:
- Unit tests for new functionality
- Benchmark tests comparing before/after
- Integration tests with real Reddit API
- Load tests with 10k+ submissions
- Memory profiling for optimization verification

---

## Backwards Compatibility

All optimizations maintain backwards compatibility:
- New flags are optional with sensible defaults
- Existing command-line options continue to work
- Database schema migrations handled automatically
- Fallback mechanisms for unsupported systems

