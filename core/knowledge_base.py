"""OpenChimera KnowledgeBase — Structured knowledge storage and retrieval.

Provides add/search/delete/export operations for factual knowledge.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.config import ROOT

log = logging.getLogger(__name__)


@dataclass
class KnowledgeEntry:
    """A single knowledge entry."""
    entry_id: str
    content: str
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class KnowledgeBase:
    """Structured knowledge storage and retrieval.
    
    Features:
    - Add/update/delete knowledge entries
    - Search by keyword, category, or tag
    - Export knowledge base
    - Thread-safe operations
    """
    
    def __init__(
        self,
        bus: Any | None = None,
        storage_path: Path | None = None,
    ) -> None:
        self._bus = bus
        self._storage_path = storage_path or (ROOT / "data" / "knowledge_base.json")
        self._entries: dict[str, KnowledgeEntry] = {}
        self._lock = threading.RLock()
        self._load()
        log.info("KnowledgeBase initialized with %d entries", len(self._entries))
    
    def add(
        self,
        content: str,
        category: str = "general",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeEntry:
        """Add a new knowledge entry."""
        with self._lock:
            entry_id = f"kb_{uuid.uuid4().hex[:8]}"
            entry = KnowledgeEntry(
                entry_id=entry_id,
                content=content,
                category=category,
                tags=tags or [],
                metadata=metadata or {},
            )
            
            self._entries[entry_id] = entry
            self._save()
            
            if self._bus:
                self._bus.publish_nowait("knowledge/added", {
                    "entry_id": entry_id,
                    "category": category,
                })
            
            log.debug("Added knowledge entry %s", entry_id)
            return entry
    
    def update(
        self,
        entry_id: str,
        content: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Update an existing knowledge entry."""
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return False
            
            if content is not None:
                entry.content = content
            if category is not None:
                entry.category = category
            if tags is not None:
                entry.tags = tags
            if metadata is not None:
                entry.metadata.update(metadata)
            
            entry.updated_at = time.time()
            self._save()
            return True
    
    def delete(self, entry_id: str) -> bool:
        """Delete a knowledge entry."""
        with self._lock:
            if entry_id in self._entries:
                del self._entries[entry_id]
                self._save()
                log.debug("Deleted knowledge entry %s", entry_id)
                return True
            return False
    
    def search(
        self,
        query: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> list[KnowledgeEntry]:
        """Search knowledge entries.
        
        Args:
            query: Search query (matches content)
            category: Filter by category
            tags: Filter by tags (entry must have all specified tags)
            
        Returns:
            List of matching entries
        """
        with self._lock:
            results = list(self._entries.values())
            
            if category:
                results = [e for e in results if e.category == category]
            
            if tags:
                results = [e for e in results if all(t in e.tags for t in tags)]
            
            if query:
                query_lower = query.lower()
                results = [e for e in results if query_lower in e.content.lower()]
            
            return results
    
    def get(self, entry_id: str) -> KnowledgeEntry | None:
        """Get a knowledge entry by ID."""
        with self._lock:
            return self._entries.get(entry_id)
    
    def list_categories(self) -> list[str]:
        """List all categories."""
        with self._lock:
            return sorted(set(e.category for e in self._entries.values()))
    
    def list_tags(self) -> list[str]:
        """List all tags."""
        with self._lock:
            tags = set()
            for entry in self._entries.values():
                tags.update(entry.tags)
            return sorted(tags)
    
    def export(self) -> dict[str, Any]:
        """Export entire knowledge base."""
        with self._lock:
            return {
                "entries": [
                    {
                        "entry_id": e.entry_id,
                        "content": e.content,
                        "category": e.category,
                        "tags": e.tags,
                        "metadata": e.metadata,
                        "created_at": e.created_at,
                        "updated_at": e.updated_at,
                    }
                    for e in self._entries.values()
                ],
                "exported_at": time.time(),
                "total_entries": len(self._entries),
            }
    
    def _load(self) -> None:
        """Load from storage."""
        if not self._storage_path.exists():
            return
        
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            for entry_data in data.get("entries", []):
                entry = KnowledgeEntry(
                    entry_id=entry_data["entry_id"],
                    content=entry_data["content"],
                    category=entry_data.get("category", "general"),
                    tags=entry_data.get("tags", []),
                    metadata=entry_data.get("metadata", {}),
                    created_at=entry_data.get("created_at", time.time()),
                    updated_at=entry_data.get("updated_at", time.time()),
                )
                self._entries[entry.entry_id] = entry
        except Exception as exc:
            log.warning("Failed to load knowledge base: %s", exc)
    
    def _save(self) -> None:
        """Save to storage."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._storage_path.write_text(
                json.dumps(self.export(), indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            log.error("Failed to save knowledge base: %s", exc)
    
    def status(self) -> dict[str, Any]:
        """Get knowledge base status."""
        with self._lock:
            return {
                "total_entries": len(self._entries),
                "categories": len(self.list_categories()),
                "tags": len(self.list_tags()),
                "storage_path": str(self._storage_path),
            }
