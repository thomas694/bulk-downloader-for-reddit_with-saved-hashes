# BDFR Testing Framework for Enhancements

This directory contains a comprehensive testing framework for testing BDFR enhancements **without touching Reddit's servers**.

## Overview

The testing framework consists of three main components:

1. **Mock Reddit Data** (`mock_reddit_data.py`)
   - Realistic mock PRAW objects (submissions, comments, users)
   - Mock Reddit instance factory
   - Mock hash databases for testing duplicate detection
   - Submission generators with various profiles

2. **Performance Benchmarks** (`test_efficiency_benchmarks.py`)
   - Hash database performance tests (100k+ entries)
   - SQLite optimization benchmarks (indexed vs unindexed)
   - Filter optimization tests
   - Concurrent processing simulations
   - Memory optimization validation

3. **Integration Tests** (`test_integration_mock_reddit.py`)
   - End-to-end workflow tests
   - Filtering logic verification
   - Hash detection workflows
   - Error handling and retry logic
   - Rate limiting behavior

## Why Mock Reddit Data?

Reddit's API has strict rate limits:
- 60 requests/minute per user
- Risk of temporary bans for excessive requests
- Slow development/testing cycle

Our mock framework allows:
- **Instant testing** with unlimited data
- **Deterministic behavior** for reproducible tests
- **Scale testing** (1k, 10k, 100k+ submissions)
- **No rate limit concerns**
- **No authentication needed**

## Running Tests

### Run all tests:
```bash
pytest tests/
```

### Run only mock Reddit tests:
```bash
pytest tests/test_efficiency_benchmarks.py tests/test_integration_mock_reddit.py -v
```

### Run specific test class:
```bash
pytest tests/test_efficiency_benchmarks.py::TestHashPerformance -v
```

### Run with timing information:
```bash
pytest tests/test_efficiency_benchmarks.py -v -s
```

## Test Categories

### 1. Hash Performance Tests

**File**: `test_efficiency_benchmarks.py::TestHashPerformance`

Tests hash-related operations at scale:
- Adding 100,000 hashes
- Hash lookups (1,000 lookups)
- Duplicate checking (10,000 checks)
- SQLite indexed vs unindexed performance

**Expected Results**:
- Hash additions: <10 seconds
- Hash lookups: >1000 lookups/second
- Duplicate checks: >10,000 checks/second
- Indexed queries: 10-100x faster than unindexed

### 2. Filtering Performance Tests

**File**: `test_efficiency_benchmarks.py::TestFilteringPerformance`

Tests filtering optimizations:
- Early filtering vs late filtering
- Batch filtering with caching
- Multiple filter combinations

**Expected Results**:
- Early filtering: 1.1-1.5x faster
- Cached filtering: Minimal overhead

### 3. Concurrency Tests

**File**: `test_efficiency_benchmarks.py::TestConcurrencyPerformance`

Tests parallel processing:
- Sequential vs concurrent processing (1000 submissions)
- Rate-limited concurrent operations
- Worker pool simulation

**Expected Results**:
- Concurrent with 3 workers: ~2.5x faster than sequential

### 4. Integration Tests

**File**: `test_integration_mock_reddit.py`

Tests complete workflows:
- Download filtering
- Hash database workflows
- Duplicate detection
- End-to-end runs with cache
- Error handling

**Expected Results**:
- All filtering logic works correctly
- Duplicate detection catches 95%+ of duplicates
- Cache survives re-runs correctly

## Creating Test Data

The `mock_reddit_data.py` module provides factories for creating test data:

### Create Single Submission:
```python
from tests.mock_reddit_data import MockSubmissionFactory

sub = MockSubmissionFactory.create_submission(
    submission_id="test_1",
    title="Test Submission",
    score=100,
    upvote_ratio=0.95,
    subreddit="gonewild"
)
```

### Create Batch of Submissions:
```python
from tests.mock_reddit_data import MockSubmissionFactory

submissions = MockSubmissionFactory.create_batch(
    count=1000,
    subreddit="test"
)
```

### Create Diverse Test Set:
```python
from tests.mock_reddit_data import MockSubmissionGenerator

submissions = MockSubmissionGenerator.create_diverse_submissions(10000)
```

### Create Hash Database:
```python
from tests.mock_reddit_data import MockHashDatabase

db = MockHashDatabase()
db.add_hash("/path/file.jpg", "abc123xyz", size=1024000)
if db.is_duplicate("abc123xyz"):
    print("Duplicate found!")
```

## Writing New Tests

### Test Template:

```python
import pytest
from tests.mock_reddit_data import MockSubmissionGenerator

class TestNewFeature:
    def test_my_feature(self):
        # Setup
        submissions = MockSubmissionGenerator.create_diverse_submissions(100)
        
        # Execute
        results = my_feature(submissions)
        
        # Verify
        assert len(results) > 0
        assert all(result.is_valid for result in results)
```

## Performance Baseline

Once optimizations are implemented, use these benchmarks to verify improvements:

```bash
# Baseline run (before optimizations)
pytest tests/test_efficiency_benchmarks.py -v --tb=short

# After optimizations
pytest tests/test_efficiency_benchmarks.py -v --tb=short

# Compare results in output
```

## Common Test Patterns

### Testing Filtering Logic:
```python
def test_score_filter():
    submissions = MockSubmissionGenerator.create_diverse_submissions(100)
    
    min_score = 50
    filtered = [s for s in submissions if s.score >= min_score]
    
    assert all(s.score >= min_score for s in filtered)
    assert len(filtered) < len(submissions)
```

### Testing Duplicate Detection:
```python
def test_duplicate_detection():
    db = MockHashDatabase()
    
    # Add original
    db.add_hash("/path/file1.jpg", "hash_abc")
    
    # Check duplicate
    assert db.is_duplicate("hash_abc")
    assert not db.is_duplicate("hash_xyz")
```

### Testing Concurrent Behavior:
```python
def test_concurrent_processing():
    submissions = MockSubmissionGenerator.create_diverse_submissions(100)
    
    # Simulate concurrent processing
    processed = [process(s) for s in submissions]
    
    assert len(processed) == 100
```

## Benchmarking Tips

1. **Run multiple times** - CPU/system state varies
2. **Disable background apps** - Reduces noise
3. **Use `pytest-benchmark`** for more accurate results:
   ```bash
   pip install pytest-benchmark
   pytest tests/ --benchmark-only
   ```
4. **Record baseline** before making changes
5. **Compare results** between runs

## Continuous Integration

These tests are designed for CI/CD:
- Fast execution (benchmarks run in <60 seconds)
- No external dependencies
- No authentication needed
- Deterministic results
- Good for pre-commit hooks

### Pre-commit Hook Example:
```bash
#!/bin/bash
pytest tests/test_efficiency_benchmarks.py -q
if [ $? -ne 0 ]; then
    echo "Tests failed"
    exit 1
fi
```

## Troubleshooting

**Issue**: Tests are slow
- **Solution**: Check if other processes are consuming resources
- **Solution**: Run single test class instead of all tests

**Issue**: Inconsistent test results
- **Solution**: This is normal for timing-based tests
- **Solution**: Run multiple times and check average

**Issue**: Mock data seems unrealistic
- **Solution**: Adjust parameters in factories
- **Solution**: Add custom data generation in test

## Next Steps

1. **Run baseline tests** to establish current performance
2. **Implement Phase 1 optimizations** (see EFFICIENCY_ROADMAP.md)
3. **Re-run tests** to measure improvement
4. **Add tests for new features** as they're implemented
5. **Benchmark against real Reddit** (optional, for final validation)

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [PRAW Mock Patterns](https://praw.readthedocs.io/)
- [Performance Testing Best Practices](https://pytest-benchmark.readthedocs.io/)
- [EFFICIENCY_ROADMAP.md](../docs/EFFICIENCY_ROADMAP.md) - Implementation guide
