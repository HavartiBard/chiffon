#!/usr/bin/env python3
"""Populate sample data for testing and development.

Creates 5-10 sample tasks with execution logs to enable:
- Testing post-mortem queries
- Development of task tracking UI
- Performance testing of database queries
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from uuid import uuid4

# Add parent directory to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.common.database import SessionLocal
from src.common.models import Task, ExecutionLog


def create_sample_data():
    """Create and persist sample task data."""
    session = SessionLocal()

    try:
        # Create 8 sample tasks
        base_time = datetime.now(timezone.utc).replace(tzinfo=None)

        # Task 1: Completed deployment from 2 days ago
        task1 = Task(
            task_id=uuid4(),
            project_id=uuid4(),
            request_text="Deploy Kuma Uptime to homelab",
            created_by="user@example.com",
            status="completed",
            created_at=base_time - timedelta(days=2),
            approved_at=base_time - timedelta(days=2, hours=1),
            completed_at=base_time - timedelta(days=2, hours=1, minutes=5),
            estimated_resources={
                "duration_seconds": 600,
                "gpu_vram_mb": 2048,
                "cpu_cores": 2,
            },
            actual_resources={
                "duration_seconds": 305,
                "gpu_vram_mb_used": 1800,
                "cpu_time_ms": 18500,
            },
            external_ai_used={
                "model": "claude-opus",
                "token_count": 5000,
                "cost_usd": 0.15,
            },
        )

        # Task 2: Completed update from 2 days ago
        task2 = Task(
            task_id=uuid4(),
            request_text="Update DNS configuration",
            created_by="admin@example.com",
            status="completed",
            created_at=base_time - timedelta(days=2, hours=6),
            approved_at=base_time - timedelta(days=2, hours=5),
            completed_at=base_time - timedelta(days=2, hours=4, minutes=30),
            estimated_resources={
                "duration_seconds": 120,
                "gpu_vram_mb": 512,
                "cpu_cores": 1,
            },
            actual_resources={
                "duration_seconds": 95,
                "gpu_vram_mb_used": 256,
                "cpu_time_ms": 4200,
            },
        )

        # Task 3: Failed task from 3 days ago
        task3 = Task(
            task_id=uuid4(),
            request_text="Deploy test application",
            created_by="dev@example.com",
            status="failed",
            created_at=base_time - timedelta(days=3),
            approved_at=base_time - timedelta(days=3, hours=1),
            completed_at=base_time - timedelta(days=3, hours=1, minutes=30),
            error_message="Container failed to start: port 8080 already in use",
            estimated_resources={
                "duration_seconds": 300,
                "gpu_vram_mb": 1024,
                "cpu_cores": 2,
            },
            actual_resources={
                "duration_seconds": 90,
                "gpu_vram_mb_used": 512,
                "cpu_time_ms": 8000,
            },
        )

        # Task 4: Failed task from 2 days ago
        task4 = Task(
            task_id=uuid4(),
            request_text="Sync Ansible playbooks from git",
            created_by="automation@example.com",
            status="failed",
            created_at=base_time - timedelta(days=2.5),
            approved_at=base_time - timedelta(days=2.5, hours=1),
            error_message="Git authentication failed: SSH key not found",
            estimated_resources={
                "duration_seconds": 60,
                "gpu_vram_mb": 256,
                "cpu_cores": 1,
            },
            actual_resources={
                "duration_seconds": 15,
                "gpu_vram_mb_used": 128,
                "cpu_time_ms": 800,
            },
        )

        # Task 5: Executing task (current)
        task5 = Task(
            task_id=uuid4(),
            request_text="Backup Portainer volumes",
            created_by="ops@example.com",
            status="executing",
            created_at=base_time - timedelta(minutes=15),
            approved_at=base_time - timedelta(minutes=10),
            estimated_resources={
                "duration_seconds": 900,
                "gpu_vram_mb": 512,
                "cpu_cores": 1,
            },
        )

        # Task 6: Approved pending task
        task6 = Task(
            task_id=uuid4(),
            request_text="Update Proxmox virtual machine",
            created_by="user@example.com",
            status="approved",
            created_at=base_time - timedelta(hours=2),
            approved_at=base_time - timedelta(hours=1),
            estimated_resources={
                "duration_seconds": 1200,
                "gpu_vram_mb": 4096,
                "cpu_cores": 4,
            },
        )

        # Task 7: Pending task (awaiting approval)
        task7 = Task(
            task_id=uuid4(),
            request_text="Install Unraid NAS backup service",
            created_by="user@example.com",
            status="pending",
            created_at=base_time - timedelta(minutes=30),
            estimated_resources={
                "duration_seconds": 1800,
                "gpu_vram_mb": 2048,
                "cpu_cores": 2,
            },
        )

        # Task 8: Another completed task with external AI usage
        task8 = Task(
            task_id=uuid4(),
            request_text="Generate infrastructure plan for new cluster",
            created_by="architect@example.com",
            status="completed",
            created_at=base_time - timedelta(days=1),
            approved_at=base_time - timedelta(days=1, hours=2),
            completed_at=base_time - timedelta(days=1, hours=1),
            estimated_resources={
                "duration_seconds": 300,
                "gpu_vram_mb": 0,
                "cpu_cores": 1,
            },
            actual_resources={
                "duration_seconds": 250,
                "gpu_vram_mb_used": 0,
                "cpu_time_ms": 12000,
            },
            external_ai_used={
                "model": "claude-opus",
                "token_count": 8000,
                "cost_usd": 0.24,
            },
        )

        session.add_all([task1, task2, task3, task4, task5, task6, task7, task8])
        session.flush()  # Ensure IDs are available

        # Create execution logs for each task

        # Task 1 logs (successful deployment)
        logs_task1 = [
            ExecutionLog(
                task_id=task1.task_id,
                step_number=1,
                agent_type="orchestrator",
                action="Parse user request for deployment",
                status="completed",
                duration_ms=1200,
                timestamp=task1.created_at + timedelta(seconds=5),
                output_summary="Parsed: Deploy Kuma to Unraid homelab",
            ),
            ExecutionLog(
                task_id=task1.task_id,
                step_number=2,
                agent_type="infra",
                action="Check current environment",
                status="completed",
                duration_ms=2300,
                timestamp=task1.created_at + timedelta(seconds=10),
                output_summary="Environment check: All systems operational",
            ),
            ExecutionLog(
                task_id=task1.task_id,
                step_number=3,
                agent_type="infra",
                action="Download Kuma container",
                status="completed",
                duration_ms=45000,
                timestamp=task1.created_at + timedelta(seconds=15),
                output_summary="Downloaded: louislam/uptime-kuma:1.23.0",
            ),
            ExecutionLog(
                task_id=task1.task_id,
                step_number=4,
                agent_type="infra",
                action="Deploy container via Portainer",
                status="completed",
                duration_ms=25000,
                timestamp=task1.created_at + timedelta(seconds=65),
                output_summary="Container deployed on Unraid, service started",
            ),
            ExecutionLog(
                task_id=task1.task_id,
                step_number=5,
                agent_type="orchestrator",
                action="Verify deployment success",
                status="completed",
                duration_ms=8000,
                timestamp=task1.created_at + timedelta(seconds=95),
                output_summary="Deployment verified: Service responding on 3001",
            ),
        ]

        # Task 2 logs (successful DNS update)
        logs_task2 = [
            ExecutionLog(
                task_id=task2.task_id,
                step_number=1,
                agent_type="orchestrator",
                action="Parse DNS update request",
                status="completed",
                duration_ms=800,
                timestamp=task2.created_at + timedelta(seconds=5),
            ),
            ExecutionLog(
                task_id=task2.task_id,
                step_number=2,
                agent_type="infra",
                action="Update DNS records",
                status="completed",
                duration_ms=3500,
                timestamp=task2.created_at + timedelta(seconds=10),
                output_summary="DNS updated: 5 A records, 2 CNAME records",
            ),
            ExecutionLog(
                task_id=task2.task_id,
                step_number=3,
                agent_type="orchestrator",
                action="Commit changes to git",
                status="completed",
                duration_ms=2000,
                timestamp=task2.created_at + timedelta(seconds=15),
                output_summary="Committed: dns/records.yml",
            ),
        ]

        # Task 3 logs (failed deployment)
        logs_task3 = [
            ExecutionLog(
                task_id=task3.task_id,
                step_number=1,
                agent_type="orchestrator",
                action="Parse deployment request",
                status="completed",
                duration_ms=600,
                timestamp=task3.created_at + timedelta(seconds=5),
            ),
            ExecutionLog(
                task_id=task3.task_id,
                step_number=2,
                agent_type="infra",
                action="Deploy container",
                status="failed",
                duration_ms=85000,
                timestamp=task3.created_at + timedelta(seconds=10),
                output_summary="Error: Container failed to start",
                output_full={
                    "error": "port 8080 already in use",
                    "container_id": "abc123def456",
                    "logs": "bind: address already in use",
                },
            ),
        ]

        # Task 4 logs (failed git sync)
        logs_task4 = [
            ExecutionLog(
                task_id=task4.task_id,
                step_number=1,
                agent_type="orchestrator",
                action="Initialize git sync task",
                status="completed",
                duration_ms=300,
                timestamp=task4.created_at + timedelta(seconds=5),
            ),
            ExecutionLog(
                task_id=task4.task_id,
                step_number=2,
                agent_type="infra",
                action="Git pull from remote",
                status="failed",
                duration_ms=10000,
                timestamp=task4.created_at + timedelta(seconds=10),
                output_summary="Git authentication failed",
                output_full={
                    "error": "ssh: permission denied (publickey)",
                    "remote": "git@github.com:user/infra.git",
                },
            ),
        ]

        # Task 5 logs (currently executing)
        logs_task5 = [
            ExecutionLog(
                task_id=task5.task_id,
                step_number=1,
                agent_type="orchestrator",
                action="Start backup task",
                status="completed",
                duration_ms=500,
                timestamp=task5.created_at + timedelta(seconds=5),
            ),
            ExecutionLog(
                task_id=task5.task_id,
                step_number=2,
                agent_type="infra",
                action="Prepare backup location",
                status="completed",
                duration_ms=2000,
                timestamp=task5.created_at + timedelta(seconds=10),
                output_summary="Backup location ready: /backup/portainer/2026-01-19",
            ),
            ExecutionLog(
                task_id=task5.task_id,
                step_number=3,
                agent_type="infra",
                action="Backup Portainer volumes",
                status="running",
                timestamp=task5.created_at + timedelta(seconds=15),
                output_summary="Currently backing up volumes...",
            ),
        ]

        # Task 8 logs (with Claude AI)
        logs_task8 = [
            ExecutionLog(
                task_id=task8.task_id,
                step_number=1,
                agent_type="orchestrator",
                action="Parse infrastructure planning request",
                status="completed",
                duration_ms=800,
                timestamp=task8.created_at + timedelta(seconds=5),
            ),
            ExecutionLog(
                task_id=task8.task_id,
                step_number=2,
                agent_type="research",
                action="Analyze current infrastructure",
                status="completed",
                duration_ms=5000,
                timestamp=task8.created_at + timedelta(seconds=10),
                output_summary="Current setup: 3 nodes, 256GB RAM, 2x RTX 4090",
            ),
            ExecutionLog(
                task_id=task8.task_id,
                step_number=3,
                agent_type="orchestrator",
                action="Request Claude for architecture design",
                status="completed",
                duration_ms=15000,
                timestamp=task8.created_at + timedelta(seconds=20),
                output_summary="Claude generated comprehensive cluster design",
                output_full={
                    "tokens_used": 8000,
                    "cost": 0.24,
                    "model": "claude-opus",
                },
            ),
        ]

        # Add all logs
        all_logs = logs_task1 + logs_task2 + logs_task3 + logs_task4 + logs_task5 + logs_task8
        session.add_all(all_logs)

        # Commit transaction
        session.commit()

        # Summary
        print(
            f"✓ Created {len([task1, task2, task3, task4, task5, task6, task7, task8])} sample tasks"
        )
        print(f"✓ Created {len(all_logs)} execution log entries")
        print(f"\nSample data distribution:")
        print(f"  - Completed: 2 tasks")
        print(f"  - Failed: 2 tasks")
        print(f"  - Executing: 1 task")
        print(f"  - Approved: 1 task")
        print(f"  - Pending: 1 task")

    except Exception as e:
        session.rollback()
        print(f"Error creating sample data: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    create_sample_data()
