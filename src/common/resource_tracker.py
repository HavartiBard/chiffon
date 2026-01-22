"""Resource tracking for task execution metrics.

Captures CPU time, memory, GPU VRAM before/after task execution.
Used by orchestrator to populate Task.actual_resources for audit trail.

Uses:
- psutil: CPU time (user + system), memory (RSS, VMS)
- pynvml: NVIDIA GPU VRAM (optional, graceful fallback)
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import psutil

logger = logging.getLogger(__name__)

# Try importing pynvml for GPU tracking
try:
    import pynvml

    pynvml.nvmlInit()
    HAS_GPU = True
    logger.info("pynvml initialized successfully - GPU tracking enabled")
except Exception as e:
    HAS_GPU = False
    logger.info(f"pynvml not available ({e}) - GPU tracking disabled")


@dataclass
class ResourceSnapshot:
    """Snapshot of resource state at a point in time."""

    cpu_user_seconds: float
    cpu_system_seconds: float
    memory_rss_bytes: int
    memory_vms_bytes: int
    wall_clock_time: float
    gpu_vram_used_bytes: Optional[int] = None
    gpu_vram_total_bytes: Optional[int] = None


def capture_resource_snapshot(
    process: Optional[psutil.Process] = None, gpu_index: int = 0
) -> ResourceSnapshot:
    """Capture current resource metrics for a process.

    Args:
        process: psutil.Process to measure. Defaults to current process.
        gpu_index: NVIDIA GPU index to query (default 0).

    Returns:
        ResourceSnapshot with current metrics.
    """
    if process is None:
        process = psutil.Process()

    cpu_times = process.cpu_times()
    memory_info = process.memory_info()

    snapshot = ResourceSnapshot(
        cpu_user_seconds=cpu_times.user,
        cpu_system_seconds=cpu_times.system,
        memory_rss_bytes=memory_info.rss,
        memory_vms_bytes=memory_info.vms,
        wall_clock_time=time.time(),
    )

    # Try GPU metrics if available
    if HAS_GPU:
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            snapshot.gpu_vram_used_bytes = mem_info.used
            snapshot.gpu_vram_total_bytes = mem_info.total
        except Exception as e:
            logger.debug(f"GPU metrics unavailable: {e}")

    return snapshot


@dataclass
class ResourceUsage:
    """Calculated resource usage between two snapshots."""

    cpu_time_seconds: float
    wall_clock_seconds: float
    peak_memory_bytes: int
    gpu_vram_used_bytes: int


def calculate_resource_usage(start: ResourceSnapshot, end: ResourceSnapshot) -> ResourceUsage:
    """Calculate resource delta between start and end snapshots.

    Args:
        start: Snapshot taken before work.
        end: Snapshot taken after work.

    Returns:
        ResourceUsage with calculated deltas.
    """
    cpu_time = (end.cpu_user_seconds - start.cpu_user_seconds) + (
        end.cpu_system_seconds - start.cpu_system_seconds
    )

    wall_clock = end.wall_clock_time - start.wall_clock_time

    # Peak memory is max of start/end RSS
    peak_memory = max(start.memory_rss_bytes, end.memory_rss_bytes)

    # GPU VRAM: use end snapshot if available, else 0
    gpu_vram = end.gpu_vram_used_bytes if end.gpu_vram_used_bytes else 0

    return ResourceUsage(
        cpu_time_seconds=cpu_time,
        wall_clock_seconds=wall_clock,
        peak_memory_bytes=peak_memory,
        gpu_vram_used_bytes=gpu_vram,
    )


def resource_usage_to_dict(usage: ResourceUsage) -> dict:
    """Convert ResourceUsage to dict for JSON serialization.

    Format matches Task.actual_resources expected structure.
    """
    return {
        "cpu_time_seconds": round(usage.cpu_time_seconds, 3),
        "wall_clock_seconds": round(usage.wall_clock_seconds, 3),
        "peak_memory_mb": round(usage.peak_memory_bytes / (1024 * 1024), 2),
        "gpu_vram_used_mb": round(usage.gpu_vram_used_bytes / (1024 * 1024), 2),
    }


class ResourceTracker:
    """Context manager for tracking resource usage during task execution.

    Usage:
        async with ResourceTracker() as tracker:
            # Do work...

        usage_dict = tracker.get_usage_dict()
        task.actual_resources = usage_dict
    """

    def __init__(self, gpu_index: int = 0):
        self.gpu_index = gpu_index
        self.start_snapshot: Optional[ResourceSnapshot] = None
        self.end_snapshot: Optional[ResourceSnapshot] = None

    async def __aenter__(self):
        self.start_snapshot = capture_resource_snapshot(gpu_index=self.gpu_index)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.end_snapshot = capture_resource_snapshot(gpu_index=self.gpu_index)
        return False

    def __enter__(self):
        self.start_snapshot = capture_resource_snapshot(gpu_index=self.gpu_index)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_snapshot = capture_resource_snapshot(gpu_index=self.gpu_index)
        return False

    def get_usage(self) -> ResourceUsage:
        """Get calculated resource usage after context exits."""
        if not self.start_snapshot or not self.end_snapshot:
            raise RuntimeError("ResourceTracker must be used as context manager")
        return calculate_resource_usage(self.start_snapshot, self.end_snapshot)

    def get_usage_dict(self) -> dict:
        """Get resource usage as dict for JSON storage."""
        return resource_usage_to_dict(self.get_usage())
