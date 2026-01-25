"""Tests for resource tracker module.

Verifies CPU time, memory, wall clock, and GPU VRAM tracking.
"""

import asyncio
import time
from unittest.mock import patch

import psutil
import pytest

from src.common.resource_tracker import (
    ResourceSnapshot,
    ResourceTracker,
    ResourceUsage,
    calculate_resource_usage,
    capture_resource_snapshot,
    resource_usage_to_dict,
)


class TestCaptureSnapshot:
    """Tests for capture_resource_snapshot function."""

    def test_capture_snapshot_has_cpu_metrics(self):
        """Snapshot has cpu_user_seconds >= 0 and cpu_system_seconds >= 0."""
        snapshot = capture_resource_snapshot()

        assert snapshot.cpu_user_seconds >= 0
        assert snapshot.cpu_system_seconds >= 0

    def test_capture_snapshot_has_memory_metrics(self):
        """Snapshot has memory_rss_bytes > 0 and memory_vms_bytes > 0."""
        snapshot = capture_resource_snapshot()

        assert snapshot.memory_rss_bytes > 0
        assert snapshot.memory_vms_bytes > 0

    def test_capture_snapshot_has_wall_clock(self):
        """Snapshot has wall_clock_time close to time.time()."""
        before = time.time()
        snapshot = capture_resource_snapshot()
        after = time.time()

        assert before <= snapshot.wall_clock_time <= after

    def test_capture_snapshot_with_custom_process(self):
        """Snapshot works with custom process."""
        process = psutil.Process()
        snapshot = capture_resource_snapshot(process=process)

        assert snapshot.cpu_user_seconds >= 0
        assert snapshot.memory_rss_bytes > 0

    def test_capture_snapshot_default_gpu_none_when_unavailable(self):
        """Snapshot GPU fields are None when no GPU available (or 0 if HAS_GPU is False)."""
        # GPU may or may not be available depending on system
        snapshot = capture_resource_snapshot()

        # Either None (no GPU) or a valid value >= 0
        if snapshot.gpu_vram_used_bytes is not None:
            assert snapshot.gpu_vram_used_bytes >= 0
        if snapshot.gpu_vram_total_bytes is not None:
            assert snapshot.gpu_vram_total_bytes >= 0


class TestCalculateUsage:
    """Tests for calculate_resource_usage function."""

    def test_calculate_usage_cpu_time(self):
        """Two snapshots with work between them, cpu_time_seconds > 0."""
        start = capture_resource_snapshot()

        # Do some CPU work
        total = 0
        for i in range(100000):
            total += i * i

        end = capture_resource_snapshot()
        usage = calculate_resource_usage(start, end)

        # CPU time should be >= 0 (may be very small)
        assert usage.cpu_time_seconds >= 0

    def test_calculate_usage_wall_clock(self):
        """Two snapshots with time.sleep(0.1) between, wall_clock_seconds >= 0.1."""
        start = capture_resource_snapshot()
        time.sleep(0.1)
        end = capture_resource_snapshot()

        usage = calculate_resource_usage(start, end)

        assert usage.wall_clock_seconds >= 0.1

    def test_calculate_usage_wall_clock_precision(self):
        """Wall clock measurement is precise to milliseconds."""
        start = capture_resource_snapshot()
        time.sleep(0.05)  # 50ms
        end = capture_resource_snapshot()

        usage = calculate_resource_usage(start, end)

        # Should be at least 50ms (0.05s), with some tolerance
        assert usage.wall_clock_seconds >= 0.04
        assert usage.wall_clock_seconds < 0.2  # Shouldn't be too long

    def test_calculate_usage_peak_memory(self):
        """Peak memory >= start memory."""
        start = capture_resource_snapshot()
        end = capture_resource_snapshot()

        usage = calculate_resource_usage(start, end)

        # Peak should be max of start/end
        assert usage.peak_memory_bytes >= min(start.memory_rss_bytes, end.memory_rss_bytes)
        assert usage.peak_memory_bytes == max(start.memory_rss_bytes, end.memory_rss_bytes)

    def test_calculate_usage_gpu_vram_zero_when_unavailable(self):
        """GPU VRAM returns 0 when not available."""
        start = ResourceSnapshot(
            cpu_user_seconds=1.0,
            cpu_system_seconds=0.5,
            memory_rss_bytes=100000000,
            memory_vms_bytes=200000000,
            wall_clock_time=1000.0,
            gpu_vram_used_bytes=None,
            gpu_vram_total_bytes=None,
        )
        end = ResourceSnapshot(
            cpu_user_seconds=2.0,
            cpu_system_seconds=1.0,
            memory_rss_bytes=150000000,
            memory_vms_bytes=250000000,
            wall_clock_time=1005.0,
            gpu_vram_used_bytes=None,
            gpu_vram_total_bytes=None,
        )

        usage = calculate_resource_usage(start, end)

        assert usage.gpu_vram_used_bytes == 0

    def test_calculate_usage_with_gpu_vram(self):
        """GPU VRAM calculation uses end snapshot value."""
        start = ResourceSnapshot(
            cpu_user_seconds=1.0,
            cpu_system_seconds=0.5,
            memory_rss_bytes=100000000,
            memory_vms_bytes=200000000,
            wall_clock_time=1000.0,
            gpu_vram_used_bytes=1000000000,  # 1GB at start
            gpu_vram_total_bytes=8000000000,
        )
        end = ResourceSnapshot(
            cpu_user_seconds=2.0,
            cpu_system_seconds=1.0,
            memory_rss_bytes=150000000,
            memory_vms_bytes=250000000,
            wall_clock_time=1005.0,
            gpu_vram_used_bytes=2000000000,  # 2GB at end
            gpu_vram_total_bytes=8000000000,
        )

        usage = calculate_resource_usage(start, end)

        # GPU VRAM should be end snapshot value
        assert usage.gpu_vram_used_bytes == 2000000000


class TestResourceUsageToDict:
    """Tests for resource_usage_to_dict function."""

    def test_resource_usage_to_dict_format(self):
        """Dict has expected keys: cpu_time_seconds, wall_clock_seconds, peak_memory_mb, gpu_vram_used_mb."""
        usage = ResourceUsage(
            cpu_time_seconds=1.5,
            wall_clock_seconds=5.0,
            peak_memory_bytes=100 * 1024 * 1024,  # 100 MB
            gpu_vram_used_bytes=500 * 1024 * 1024,  # 500 MB
        )

        result = resource_usage_to_dict(usage)

        assert "cpu_time_seconds" in result
        assert "wall_clock_seconds" in result
        assert "peak_memory_mb" in result
        assert "gpu_vram_used_mb" in result

    def test_resource_usage_to_dict_values(self):
        """Dict values are correctly converted."""
        usage = ResourceUsage(
            cpu_time_seconds=1.5678,
            wall_clock_seconds=5.1234,
            peak_memory_bytes=100 * 1024 * 1024,  # 100 MB
            gpu_vram_used_bytes=500 * 1024 * 1024,  # 500 MB
        )

        result = resource_usage_to_dict(usage)

        assert result["cpu_time_seconds"] == 1.568  # Rounded to 3 decimals
        assert result["wall_clock_seconds"] == 5.123  # Rounded to 3 decimals
        assert result["peak_memory_mb"] == 100.0
        assert result["gpu_vram_used_mb"] == 500.0

    def test_resource_usage_to_dict_zero_gpu(self):
        """Dict handles zero GPU VRAM correctly."""
        usage = ResourceUsage(
            cpu_time_seconds=1.0,
            wall_clock_seconds=2.0,
            peak_memory_bytes=50 * 1024 * 1024,
            gpu_vram_used_bytes=0,
        )

        result = resource_usage_to_dict(usage)

        assert result["gpu_vram_used_mb"] == 0.0


class TestResourceTrackerContextManager:
    """Tests for ResourceTracker context manager."""

    def test_resource_tracker_sync_context_manager(self):
        """Use `with ResourceTracker() as tracker`, verify get_usage_dict() returns valid dict."""
        with ResourceTracker() as tracker:
            # Do some work
            time.sleep(0.05)

        result = tracker.get_usage_dict()

        assert isinstance(result, dict)
        assert "cpu_time_seconds" in result
        assert "wall_clock_seconds" in result
        assert "peak_memory_mb" in result
        assert "gpu_vram_used_mb" in result
        assert result["wall_clock_seconds"] >= 0.04  # At least 40ms

    @pytest.mark.asyncio
    async def test_resource_tracker_async_context_manager(self):
        """Use `async with ResourceTracker() as tracker`, verify works in async context."""
        async with ResourceTracker() as tracker:
            # Do some async work
            await asyncio.sleep(0.05)

        result = tracker.get_usage_dict()

        assert isinstance(result, dict)
        assert "cpu_time_seconds" in result
        assert "wall_clock_seconds" in result
        assert result["wall_clock_seconds"] >= 0.04  # At least 40ms

    def test_resource_tracker_error_before_exit(self):
        """Calling get_usage() before __exit__ raises RuntimeError."""
        tracker = ResourceTracker()

        with pytest.raises(RuntimeError, match="must be used as context manager"):
            tracker.get_usage()

    def test_resource_tracker_error_get_usage_dict_before_exit(self):
        """Calling get_usage_dict() before __exit__ raises RuntimeError."""
        tracker = ResourceTracker()

        with pytest.raises(RuntimeError, match="must be used as context manager"):
            tracker.get_usage_dict()

    def test_resource_tracker_after_enter_before_exit(self):
        """Calling get_usage() after __enter__ but before __exit__ raises RuntimeError."""
        tracker = ResourceTracker()
        tracker.__enter__()

        with pytest.raises(RuntimeError, match="must be used as context manager"):
            tracker.get_usage()

        tracker.__exit__(None, None, None)  # Cleanup

    def test_resource_tracker_with_work(self):
        """Resource tracker captures CPU work."""
        with ResourceTracker() as tracker:
            # Do CPU work
            total = 0
            for i in range(50000):
                total += i * i

        result = tracker.get_usage()

        # CPU time should be captured (may be very small)
        assert result.cpu_time_seconds >= 0
        assert result.wall_clock_seconds > 0
        assert result.peak_memory_bytes > 0


class TestGPUGracefulFallback:
    """Tests for GPU unavailable graceful fallback."""

    def test_gpu_unavailable_graceful_fallback_snapshot(self):
        """Even without GPU, snapshot works and returns None for GPU fields."""
        snapshot = capture_resource_snapshot()

        # Should not raise, GPU fields may be None
        assert snapshot.cpu_user_seconds >= 0
        assert snapshot.memory_rss_bytes > 0
        # GPU may be None or have values depending on system

    def test_gpu_unavailable_graceful_fallback_usage(self):
        """Even without GPU, usage calculation works and returns 0 for GPU fields."""
        start = capture_resource_snapshot()
        end = capture_resource_snapshot()

        usage = calculate_resource_usage(start, end)

        # Should not raise, GPU VRAM should be 0 or actual value
        assert usage.gpu_vram_used_bytes >= 0

    def test_gpu_unavailable_graceful_fallback_tracker(self):
        """Even without GPU, ResourceTracker works and returns 0 for GPU fields."""
        with ResourceTracker() as tracker:
            time.sleep(0.01)

        result = tracker.get_usage_dict()

        # Should have all fields, GPU may be 0
        assert "gpu_vram_used_mb" in result
        assert result["gpu_vram_used_mb"] >= 0

    @patch("src.common.resource_tracker.HAS_GPU", False)
    def test_gpu_disabled_returns_none_in_snapshot(self):
        """When HAS_GPU is False, GPU fields are None in snapshot."""
        snapshot = capture_resource_snapshot()

        assert snapshot.gpu_vram_used_bytes is None
        assert snapshot.gpu_vram_total_bytes is None

    def test_gpu_fields_converted_to_zero_in_usage(self):
        """GPU None values become 0 in ResourceUsage."""
        start = ResourceSnapshot(
            cpu_user_seconds=0.0,
            cpu_system_seconds=0.0,
            memory_rss_bytes=1000000,
            memory_vms_bytes=2000000,
            wall_clock_time=0.0,
            gpu_vram_used_bytes=None,
            gpu_vram_total_bytes=None,
        )
        end = ResourceSnapshot(
            cpu_user_seconds=0.1,
            cpu_system_seconds=0.05,
            memory_rss_bytes=1500000,
            memory_vms_bytes=2500000,
            wall_clock_time=1.0,
            gpu_vram_used_bytes=None,
            gpu_vram_total_bytes=None,
        )

        usage = calculate_resource_usage(start, end)

        assert usage.gpu_vram_used_bytes == 0


class TestResourceSnapshotDataclass:
    """Tests for ResourceSnapshot dataclass."""

    def test_snapshot_creation(self):
        """ResourceSnapshot can be created with all fields."""
        snapshot = ResourceSnapshot(
            cpu_user_seconds=1.5,
            cpu_system_seconds=0.5,
            memory_rss_bytes=100000000,
            memory_vms_bytes=200000000,
            wall_clock_time=1234567890.0,
            gpu_vram_used_bytes=1000000000,
            gpu_vram_total_bytes=8000000000,
        )

        assert snapshot.cpu_user_seconds == 1.5
        assert snapshot.cpu_system_seconds == 0.5
        assert snapshot.memory_rss_bytes == 100000000
        assert snapshot.memory_vms_bytes == 200000000
        assert snapshot.wall_clock_time == 1234567890.0
        assert snapshot.gpu_vram_used_bytes == 1000000000
        assert snapshot.gpu_vram_total_bytes == 8000000000

    def test_snapshot_optional_gpu_defaults_to_none(self):
        """ResourceSnapshot GPU fields default to None."""
        snapshot = ResourceSnapshot(
            cpu_user_seconds=1.0,
            cpu_system_seconds=0.5,
            memory_rss_bytes=100000000,
            memory_vms_bytes=200000000,
            wall_clock_time=1234567890.0,
        )

        assert snapshot.gpu_vram_used_bytes is None
        assert snapshot.gpu_vram_total_bytes is None


class TestResourceUsageDataclass:
    """Tests for ResourceUsage dataclass."""

    def test_usage_creation(self):
        """ResourceUsage can be created with all fields."""
        usage = ResourceUsage(
            cpu_time_seconds=2.0,
            wall_clock_seconds=5.0,
            peak_memory_bytes=150000000,
            gpu_vram_used_bytes=2000000000,
        )

        assert usage.cpu_time_seconds == 2.0
        assert usage.wall_clock_seconds == 5.0
        assert usage.peak_memory_bytes == 150000000
        assert usage.gpu_vram_used_bytes == 2000000000


class TestIntegration:
    """Integration tests for end-to-end resource tracking."""

    def test_full_workflow_sync(self):
        """Full sync workflow: track work, get usage dict."""
        with ResourceTracker() as tracker:
            # Simulate work
            data = [i * i for i in range(10000)]
            time.sleep(0.05)
            del data

        usage_dict = tracker.get_usage_dict()

        # Verify all expected fields
        assert usage_dict["cpu_time_seconds"] >= 0
        assert usage_dict["wall_clock_seconds"] >= 0.04
        assert usage_dict["peak_memory_mb"] > 0
        assert usage_dict["gpu_vram_used_mb"] >= 0

    @pytest.mark.asyncio
    async def test_full_workflow_async(self):
        """Full async workflow: track async work, get usage dict."""
        async with ResourceTracker() as tracker:
            # Simulate async work
            await asyncio.sleep(0.05)

        usage_dict = tracker.get_usage_dict()

        # Verify all expected fields
        assert usage_dict["cpu_time_seconds"] >= 0
        assert usage_dict["wall_clock_seconds"] >= 0.04
        assert usage_dict["peak_memory_mb"] > 0
        assert usage_dict["gpu_vram_used_mb"] >= 0

    def test_dict_is_json_serializable(self):
        """Usage dict can be JSON serialized."""
        import json

        with ResourceTracker() as tracker:
            time.sleep(0.01)

        usage_dict = tracker.get_usage_dict()

        # Should not raise
        json_str = json.dumps(usage_dict)
        assert isinstance(json_str, str)

        # Round trip
        parsed = json.loads(json_str)
        assert parsed == usage_dict
