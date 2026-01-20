"""Desktop agent for resource-constrained environments (GPU desktops, workstations).

Provides:
- CPU load averages (1-min, 5-min) for stable scheduling decisions
- GPU VRAM metrics with multi-vendor support (NVIDIA pynvml + nvidia-smi fallback)
- Available core calculation from load percentage
- Configuration-driven heartbeat intervals
- Graceful handling of metrics collection errors
"""

import asyncio
import logging
import subprocess
import time
from typing import Any

import psutil

from src.agents.base import BaseAgent
from src.common.config import Config
from src.common.protocol import WorkRequest, WorkResult

logger = logging.getLogger(__name__)


class DesktopAgent(BaseAgent):
    """Desktop agent with enhanced resource metrics collection.

    Extends BaseAgent with:
    - CPU load averages (1-min, 5-min, 15-min) instead of instantaneous percent
    - Available CPU core calculation from load percentage
    - Multi-vendor GPU detection (pynvml primary, nvidia-smi fallback)
    - Configuration-driven heartbeat intervals
    - Timeout protection for GPU detection
    """

    def __init__(self, agent_id: str, agent_type: str, config: Config):
        """Initialize the desktop agent.

        Args:
            agent_id: Unique identifier for this agent
            agent_type: Type of agent (typically "desktop")
            config: Configuration object with heartbeat settings
        """
        super().__init__(agent_id, agent_type, config)
        self.heartbeat_interval_seconds = getattr(config, "heartbeat_interval_seconds", 30)
        self.gpu_detection_timeout_seconds = getattr(config, "gpu_detection_timeout_seconds", 5)

    def _get_gpu_metrics(self) -> dict[str, Any]:
        """Get GPU VRAM metrics with multi-vendor support.

        Tries pynvml first (NVIDIA, fastest), falls back to nvidia-smi subprocess,
        and returns zeros if neither available. All subprocess calls wrapped with
        timeout to prevent agent hangs.

        Returns:
            Dict with gpu_vram_total_gb, gpu_vram_available_gb, gpu_type.
            Returns zeros if no GPU detected.
        """
        # === GPU Detection: Try pynvml first (NVIDIA, fastest) ===
        try:
            import pynvml

            try:
                pynvml.nvmlInit()
                device_count = pynvml.nvmlDeviceGetCount()

                if device_count > 0:
                    # Get first device
                    device = pynvml.nvmlDeviceGetHandleByIndex(0)
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(device)

                    total_gb = mem_info.total / (1024**3)
                    available_gb = mem_info.free / (1024**3)

                    logger.debug(
                        f"GPU metrics collected via pynvml: {available_gb:.2f}GB / {total_gb:.2f}GB available"
                    )

                    return {
                        "gpu_vram_total_gb": total_gb,
                        "gpu_vram_available_gb": available_gb,
                        "gpu_type": "nvidia",
                    }
            except pynvml.NVMLError as e:
                logger.debug(f"pynvml error (GPU may not be available): {e}")
            finally:
                try:
                    pynvml.nvmlShutdown()
                except Exception:
                    pass

        except ImportError:
            logger.debug("pynvml not installed, falling back to nvidia-smi")

        # === GPU Detection: Fallback to nvidia-smi subprocess ===
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.total,memory.free,name",
                    "--format=csv,nounits,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=self.gpu_detection_timeout_seconds,
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if lines and lines[0]:
                    parts = lines[0].split(",")
                    if len(parts) >= 3:
                        total_mb = float(parts[0].strip())
                        free_mb = float(parts[1].strip())
                        gpu_name = parts[2].strip().lower()

                        # Detect GPU type from name
                        gpu_type = "nvidia"
                        if "radeon" in gpu_name or "amd" in gpu_name:
                            gpu_type = "amd"
                        elif "arc" in gpu_name or "oneapi" in gpu_name or "intel" in gpu_name:
                            gpu_type = "intel"

                        total_gb = total_mb / 1024.0
                        available_gb = free_mb / 1024.0

                        logger.debug(
                            f"GPU metrics collected via nvidia-smi ({gpu_type}): "
                            f"{available_gb:.2f}GB / {total_gb:.2f}GB available"
                        )

                        return {
                            "gpu_vram_total_gb": total_gb,
                            "gpu_vram_available_gb": available_gb,
                            "gpu_type": gpu_type,
                        }

        except subprocess.TimeoutExpired:
            logger.debug(f"nvidia-smi timeout ({self.gpu_detection_timeout_seconds}s) - GPU query too slow")
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            logger.debug(f"nvidia-smi error or not found: {e}")
        except (ValueError, IndexError) as e:
            logger.debug(f"Failed to parse nvidia-smi output: {e}")
        except Exception as e:
            logger.debug(f"Unexpected error in GPU detection: {e}")

        # === Fallback: No GPU available ===
        logger.debug("No GPU detected - returning zeros")
        return {
            "gpu_vram_total_gb": 0.0,
            "gpu_vram_available_gb": 0.0,
            "gpu_type": "none",
        }

    def _get_resource_metrics(self) -> dict[str, Any]:
        """Collect enhanced resource metrics from system.

        Uses CPU load averages (1-min, 5-min, 15-min) for stable scheduling,
        calculates available cores from load percentage, and includes GPU metrics.

        Returns:
            Dict with CPU, memory, and GPU metrics ready for heartbeat dispatch.
        """
        try:
            # CPU metrics: Load averages (stable for scheduling)
            load_1min, load_5min, load_15min = psutil.getloadavg()

            # Physical core count (conservative for scheduling)
            physical_cores = psutil.cpu_count(logical=False) or 1

            # Available cores: max(1, physical_cores - load_1min)
            # Conservative calculation: if 50% load on 8 cores, report ~4 available
            available_cores = max(1, int(physical_cores - load_1min))

            # Memory metrics
            memory_info = psutil.virtual_memory()
            memory_percent = memory_info.percent
            memory_available_gb = memory_info.available / (1024**3)

            # GPU metrics
            gpu_metrics = self._get_gpu_metrics()

            metrics = {
                "cpu_load_1min": load_1min,
                "cpu_load_5min": load_5min,
                "cpu_load_15min": load_15min,
                "cpu_cores_physical": physical_cores,
                "cpu_cores_available": available_cores,
                "memory_percent": memory_percent,
                "memory_available_gb": memory_available_gb,
            }
            metrics.update(gpu_metrics)

            logger.info(
                f"Resource metrics collected: "
                f"{load_1min:.2f}L1 {load_5min:.2f}L5 "
                f"{available_cores}/{physical_cores} cores "
                f"{gpu_metrics.get('gpu_vram_available_gb', 0):.1f}GB GPU",
                extra={"metrics": metrics},
            )

            return metrics

        except Exception as e:
            logger.error(f"Error collecting resource metrics: {e}", exc_info=True)
            # Return safe defaults if collection fails
            return {
                "cpu_load_1min": 0.0,
                "cpu_load_5min": 0.0,
                "cpu_load_15min": 0.0,
                "cpu_cores_physical": 1,
                "cpu_cores_available": 1,
                "memory_percent": 0.0,
                "memory_available_gb": 0.0,
                "gpu_vram_total_gb": 0.0,
                "gpu_vram_available_gb": 0.0,
                "gpu_type": "none",
            }

    def get_agent_capabilities(self) -> dict[str, Any]:
        """Report agent capabilities to orchestrator.

        For Phase 4, desktop agents don't execute work yet (Phase 6).
        Returns capability placeholders for future implementation.

        Returns:
            Dict mapping capability to boolean (True if supported, False if not)
        """
        return {
            # Phase 4: Metrics collection only
            # Phase 6 will add: gpu_compute, inference, training
        }

    async def execute_work(self, work_request: WorkRequest) -> WorkResult:
        """Execute work request (stub for Phase 4).

        Phase 4 focuses on metrics collection only. Actual work execution
        is implemented in Phase 6 (Infrastructure Agent).

        Args:
            work_request: The work request with task_id, work_type, and parameters

        Returns:
            WorkResult with status "success" and placeholder message
        """
        logger.info(
            f"Phase 4: Desktop agent received work request (metrics only, no execution)",
            extra={"task_id": str(work_request.task_id)},
        )

        start_time = time.time()

        # Phase 4 stub: Just log and return success
        output = "Desktop agent phase 4 (metrics only) - work execution in Phase 6"

        duration_ms = int((time.time() - start_time) * 1000)

        return WorkResult(
            task_id=work_request.task_id,
            status="success",
            exit_code=0,
            output=output,
            duration_ms=duration_ms,
            resources_used=self._get_resource_metrics(),
        )
