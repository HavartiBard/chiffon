"""Cache manager for semantic playbook mappings.

Provides PostgreSQL-backed caching for task-to-playbook semantic mappings
to avoid redundant LLM calls and improve response time.
"""

import hashlib
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from src.common.models import PlaybookMapping


class CacheManager:
    """Manages semantic mapping cache in PostgreSQL.

    Provides:
    - Lookup of previously cached intent mappings
    - Storage of new semantic matches for reuse
    - Usage tracking (last_used_at, use_count)
    - Retrieval of cached embeddings for FAISS index warmup
    """

    def __init__(self, db_session: AsyncSession):
        """Initialize cache manager with database session.

        Args:
            db_session: Async SQLAlchemy session for database operations
        """
        self.db = db_session

    async def lookup_cached_mapping(self, intent: str) -> Optional[PlaybookMapping]:
        """Look up cached mapping for task intent.

        Args:
            intent: Task intent text (will be normalized)

        Returns:
            PlaybookMapping if found with confidence >= 0.85, else None
        """
        # Normalize and hash intent
        normalized = PlaybookMapping.normalize_intent(intent)
        intent_hash = self._hash_intent(normalized)

        # Query for cached mapping with confidence threshold
        stmt = select(PlaybookMapping).where(
            PlaybookMapping.intent_hash == intent_hash, PlaybookMapping.confidence >= 0.85
        )
        result = await self.db.execute(stmt)
        mapping = result.scalar_one_or_none()

        if mapping:
            # Update usage tracking
            await self._update_usage(mapping.id)

        return mapping

    async def cache_mapping(
        self,
        intent: str,
        playbook_path: str,
        confidence: float,
        method: str,
        embedding: Optional[list[float]] = None,
    ):
        """Cache a task-to-playbook mapping.

        Args:
            intent: Task intent text (will be normalized)
            playbook_path: Path to matched playbook
            confidence: Match confidence (0.0-1.0)
            method: Match method ('exact', 'cached', 'semantic')
            embedding: Optional embedding vector for semantic matches
        """
        # Normalize and hash intent
        normalized = PlaybookMapping.normalize_intent(intent)
        intent_hash = self._hash_intent(normalized)

        # Prepare insert/update statement (upsert)
        stmt = insert(PlaybookMapping).values(
            intent=intent,
            intent_hash=intent_hash,
            playbook_path=playbook_path,
            confidence=confidence,
            match_method=method,
            embedding_vector=embedding,
            created_at=datetime.utcnow(),
            last_used_at=datetime.utcnow(),
            use_count=1,
        )

        # On conflict, update with new values
        stmt = stmt.on_conflict_do_update(
            index_elements=["intent_hash"],
            set_={
                "playbook_path": playbook_path,
                "confidence": confidence,
                "match_method": method,
                "embedding_vector": embedding,
                "last_used_at": datetime.utcnow(),
            },
        )

        await self.db.execute(stmt)
        await self.db.commit()

    async def get_all_cached_embeddings(self) -> list[tuple[str, list[float]]]:
        """Retrieve all cached embeddings for FAISS index warmup.

        Returns:
            List of (playbook_path, embedding_vector) tuples for entries with embeddings
        """
        stmt = select(PlaybookMapping.playbook_path, PlaybookMapping.embedding_vector).where(
            PlaybookMapping.embedding_vector.is_not(None)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        # Filter out None embeddings and return as list of tuples
        return [(row[0], row[1]) for row in rows if row[1] is not None]

    async def _update_usage(self, mapping_id: int):
        """Update last_used_at and increment use_count.

        Args:
            mapping_id: ID of the PlaybookMapping to update
        """
        stmt = (
            update(PlaybookMapping)
            .where(PlaybookMapping.id == mapping_id)
            .values(last_used_at=datetime.utcnow(), use_count=PlaybookMapping.use_count + 1)
        )

        await self.db.execute(stmt)
        await self.db.commit()

    @staticmethod
    def _hash_intent(normalized_intent: str) -> str:
        """Generate SHA256 hash of normalized intent.

        Args:
            normalized_intent: Normalized (lowercased, stripped) intent text

        Returns:
            Hexadecimal SHA256 hash string
        """
        return hashlib.sha256(normalized_intent.encode("utf-8")).hexdigest()
