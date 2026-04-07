"""OpenChimera HealthMonitor — Subsystem health tracking with history.

Monitors health of all subsystems and tracks health history over time.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class HealthRecord:
    """Health check record for a subsystem."""
    subsystem: str
    status: str  # healthy, degraded, failed, unknown
    timestamp: float = field(default_factory=time.time)
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class HealthMonitor:
    """Subsystem health tracking with history.
    
    Features:
    - Health status tracking for all subsystems
    - Health history with configurable retention
    - Health degradation detection
    - Aggregate health reporting
    """
    
    def __init__(
        self,
        bus: Any | None = None,
        history_size: int = 100,
    ) -> None:
        self._bus = bus
        self._history_size = history_size
        self._current: dict[str, HealthRecord] = {}
        self._history: dict[str, deque[HealthRecord]] = {}
        self._lock = threading.RLock()
        log.info("HealthMonitor initialized with history_size=%d", history_size)
    
    def record_health(
        self,
        subsystem: str,
        status: str,
        details: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Record a health check for a subsystem.
        
        Args:
            subsystem: Subsystem name
            status: Health status (healthy, degraded, failed, unknown)
            details: Optional health details
            error: Optional error message
        """
        with self._lock:
            record = HealthRecord(
                subsystem=subsystem,
                status=status,
                details=details or {},
                error=error,
            )
            
            # Update current status
            prev_status = None
            if subsystem in self._current:
                prev_status = self._current[subsystem].status
            self._current[subsystem] = record
            
            # Add to history
            if subsystem not in self._history:
                self._history[subsystem] = deque(maxlen=self._history_size)
            self._history[subsystem].append(record)
            
            # Emit event if status changed
            if prev_status != status and self._bus:
                self._bus.publish_nowait("health/status_changed", {
                    "subsystem": subsystem,
                    "old_status": prev_status,
                    "new_status": status,
                    "timestamp": record.timestamp,
                })
            
            log.debug("Health check: %s = %s", subsystem, status)
    
    def get_current_health(self, subsystem: str) -> HealthRecord | None:
        """Get current health status for a subsystem."""
        with self._lock:
            return self._current.get(subsystem)
    
    def get_health_history(
        self,
        subsystem: str,
        limit: int | None = None,
    ) -> list[HealthRecord]:
        """Get health history for a subsystem.
        
        Args:
            subsystem: Subsystem name
            limit: Maximum number of records to return (None = all)
            
        Returns:
            List of health records, newest first
        """
        with self._lock:
            if subsystem not in self._history:
                return []
            
            history = list(self._history[subsystem])
            history.reverse()  # Newest first
            
            if limit is not None:
                history = history[:limit]
            
            return history
    
    def get_all_current_health(self) -> dict[str, HealthRecord]:
        """Get current health status for all subsystems."""
        with self._lock:
            return dict(self._current)
    
    def get_aggregate_status(self) -> str:
        """Get aggregate health status across all subsystems.
        
        Returns:
            "healthy" if all healthy
            "degraded" if any degraded
            "failed" if any failed
            "unknown" if no data
        """
        with self._lock:
            if not self._current:
                return "unknown"
            
            statuses = {r.status for r in self._current.values()}
            
            if "failed" in statuses:
                return "failed"
            if "degraded" in statuses:
                return "degraded"
            if "unknown" in statuses:
                return "degraded"  # Treat unknown as degraded
            return "healthy"
    
    def get_subsystems_by_status(self, status: str) -> list[str]:
        """Get list of subsystems with the specified status."""
        with self._lock:
            return [
                subsystem
                for subsystem, record in self._current.items()
                if record.status == status
            ]
    
    def check_degradation(
        self,
        subsystem: str,
        window_size: int = 5,
        threshold: float = 0.6,
    ) -> bool:
        """Check if a subsystem is showing degradation patterns.
        
        Args:
            subsystem: Subsystem to check
            window_size: Number of recent checks to examine
            threshold: Fraction of failed/degraded checks to trigger alert
            
        Returns:
            True if degradation detected
        """
        with self._lock:
            if subsystem not in self._history:
                return False
            
            recent = list(self._history[subsystem])[-window_size:]
            if not recent:
                return False
            
            unhealthy = sum(
                1 for r in recent
                if r.status in ("failed", "degraded")
            )
            
            return (unhealthy / len(recent)) >= threshold
    
    def status(self) -> dict[str, Any]:
        """Get health monitor status."""
        with self._lock:
            status_counts = {}
            for record in self._current.values():
                status_counts[record.status] = status_counts.get(record.status, 0) + 1
            
            return {
                "tracked_subsystems": len(self._current),
                "aggregate_status": self.get_aggregate_status(),
                "status_counts": status_counts,
                "healthy": len(self.get_subsystems_by_status("healthy")),
                "degraded": len(self.get_subsystems_by_status("degraded")),
                "failed": len(self.get_subsystems_by_status("failed")),
                "unknown": len(self.get_subsystems_by_status("unknown")),
                "history_size": self._history_size,
                "total_history_records": sum(len(h) for h in self._history.values()),
            }
