"""Task-to-playbook mapper with hybrid matching strategy.

Maps service-level intents (e.g., "Deploy Kuma") to Ansible playbook paths
using a three-tier strategy:
1. Exact match (service name in intent)
2. Cached mapping lookup (PostgreSQL)
3. Semantic search (FAISS with sentence-transformers)
"""

import logging
from typing import Optional

import numpy as np
from pydantic import BaseModel, Field

from .cache_manager import CacheManager

logger = logging.getLogger(__name__)


class PlaybookMetadata(BaseModel):
    """Metadata for a discovered playbook.

    Attributes:
        path: Full path to playbook file
        filename: Playbook filename
        service: Optional service name (e.g., 'kuma', 'portainer')
        description: Optional human-readable description
        required_vars: List of required variables
        tags: List of playbook tags
    """

    path: str = Field(..., description="Full path to playbook file")
    filename: str = Field(..., description="Playbook filename")
    service: Optional[str] = Field(default=None, description="Service name")
    description: Optional[str] = Field(default=None, description="Playbook description")
    required_vars: list[str] = Field(default_factory=list, description="Required variables")
    tags: list[str] = Field(default_factory=list, description="Playbook tags")


class MappingResult(BaseModel):
    """Result of mapping a task intent to a playbook.

    Attributes:
        playbook_path: Path to matched playbook (None if no match)
        confidence: Match confidence (0.0-1.0)
        method: Match method ('exact', 'cached', 'semantic', 'none')
        alternatives: Other matches with scores (max 3)
        suggestion: Suggestion if no match found
    """

    playbook_path: Optional[str] = Field(default=None, description="Matched playbook path")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Match confidence")
    method: str = Field(
        ..., pattern="^(exact|cached|semantic|none)$", description="Match method used"
    )
    alternatives: list[dict] = Field(
        default_factory=list, description="Alternative matches with playbook_path and score"
    )
    suggestion: Optional[str] = Field(default=None, description="Suggestion if no match found")


class TaskMapper:
    """Maps task intents to playbook paths using hybrid matching.

    Three-tier matching strategy:
    1. Exact match: Service name appears in intent
    2. Cached match: Previously matched intent in PostgreSQL
    3. Semantic match: FAISS vector similarity search

    Semantic matches above confidence threshold (0.85) are cached for reuse.
    """

    CONFIDENCE_THRESHOLD = 0.85

    def __init__(self, cache_manager: CacheManager, playbook_catalog: list[PlaybookMetadata]):
        """Initialize TaskMapper with cache and playbook catalog.

        Args:
            cache_manager: CacheManager for semantic mapping persistence
            playbook_catalog: List of discovered playbooks with metadata
        """
        self.cache_manager = cache_manager
        self.playbook_catalog = playbook_catalog

        # Lazy-loaded components (only instantiated when semantic matching needed)
        self.embedder: Optional[object] = None  # SentenceTransformer
        self.index: Optional[object] = None  # faiss.IndexFlatIP
        self._catalog_embeddings: Optional[np.ndarray] = None
        self._catalog_index_map: Optional[list[int]] = None  # Maps FAISS index -> catalog index

    async def map_task_to_playbook(self, task_intent: str, top_k: int = 3) -> MappingResult:
        """Map task intent to playbook using hybrid strategy.

        Args:
            task_intent: Natural language task description
            top_k: Number of alternative matches to return

        Returns:
            MappingResult with best match and alternatives
        """
        # Step 1: Try exact match
        exact_path = self._exact_match(task_intent)
        if exact_path:
            logger.info(f"Exact match found for intent: {task_intent[:50]}...")
            return MappingResult(
                playbook_path=exact_path, confidence=1.0, method="exact", alternatives=[]
            )

        # Step 2: Try cached mapping
        cached_result = await self._cached_match(task_intent)
        if cached_result:
            logger.info(f"Cached match found for intent: {task_intent[:50]}...")
            return cached_result

        # Step 3: Try semantic matching
        semantic_result = await self._semantic_match(task_intent, top_k)
        return semantic_result

    def _exact_match(self, task_intent: str) -> Optional[str]:
        """Attempt exact match by checking if service name appears in intent.

        Args:
            task_intent: Task intent text

        Returns:
            Playbook path if service name found in intent, else None
        """
        intent_lower = task_intent.lower()

        for playbook in self.playbook_catalog:
            if playbook.service and playbook.service.lower() in intent_lower:
                return playbook.path

        return None

    async def _cached_match(self, task_intent: str) -> Optional[MappingResult]:
        """Look up cached mapping from previous semantic matches.

        Args:
            task_intent: Task intent text

        Returns:
            MappingResult if cached mapping found with confidence >= 0.85, else None
        """
        cached = await self.cache_manager.lookup_cached_mapping(task_intent)

        if cached:
            return MappingResult(
                playbook_path=cached.playbook_path,
                confidence=cached.confidence,
                method="cached",
                alternatives=[],
            )

        return None

    async def _semantic_match(self, task_intent: str, top_k: int) -> MappingResult:
        """Perform semantic similarity search using FAISS.

        Args:
            task_intent: Task intent text
            top_k: Number of matches to consider

        Returns:
            MappingResult with best match if confidence >= 0.85, else no-match result
        """
        # Lazy-load embedding model and FAISS index
        try:
            if not self.embedder:
                await self._lazy_load_embedder()

            if not self.index:
                await self._build_faiss_index()
        except Exception as e:
            logger.error(f"Failed to initialize semantic matching: {e}")
            return self._no_match_result(task_intent)

        # Handle empty catalog
        if not self.playbook_catalog:
            logger.warning("Empty playbook catalog, cannot perform semantic match")
            return self._no_match_result(task_intent)

        try:
            # Embed task intent
            query_embedding = self.embedder.encode([task_intent])[0]

            # Normalize for cosine similarity via inner product
            query_embedding = query_embedding / np.linalg.norm(query_embedding)

            # Search FAISS index
            scores, indices = self.index.search(
                np.array([query_embedding], dtype=np.float32),
                min(top_k, len(self.playbook_catalog)),
            )

            # Convert results to alternatives list
            alternatives = []
            for score, idx in zip(scores[0], indices[0], strict=False):
                if idx < len(self._catalog_index_map):
                    catalog_idx = self._catalog_index_map[idx]
                    playbook = self.playbook_catalog[catalog_idx]
                    alternatives.append(
                        {
                            "playbook_path": playbook.path,
                            "score": float(score),
                            "service": playbook.service,
                        }
                    )

            # Check if best match meets confidence threshold
            if alternatives and alternatives[0]["score"] >= self.CONFIDENCE_THRESHOLD:
                best_match = alternatives[0]

                # Cache the semantic match for future use
                await self.cache_manager.cache_mapping(
                    intent=task_intent,
                    playbook_path=best_match["playbook_path"],
                    confidence=best_match["score"],
                    method="semantic",
                    embedding=query_embedding.tolist(),
                )

                logger.info(
                    f"Semantic match found: {best_match['playbook_path']} "
                    f"(confidence: {best_match['score']:.2f})"
                )

                return MappingResult(
                    playbook_path=best_match["playbook_path"],
                    confidence=best_match["score"],
                    method="semantic",
                    alternatives=alternatives[1:3],  # Return next 2 alternatives
                )

            # No match above threshold
            logger.info(
                f"No semantic match above threshold ({self.CONFIDENCE_THRESHOLD}) "
                f"for intent: {task_intent[:50]}..."
            )
            return self._no_match_result(task_intent, alternatives[:3])

        except Exception as e:
            logger.error(f"Semantic matching failed: {e}")
            return self._no_match_result(task_intent)

    async def _lazy_load_embedder(self):
        """Lazy-load sentence-transformers embedding model."""
        try:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading sentence-transformers model: all-MiniLM-L6-v2")
            self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Embedding model loaded successfully")

        except ImportError:
            logger.error(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise

    async def _build_faiss_index(self):
        """Build FAISS index from playbook catalog descriptions."""
        try:
            import faiss
        except ImportError:
            logger.error("faiss not installed. " "Install with: pip install faiss-cpu")
            raise

        # Generate descriptions for each playbook
        descriptions = []
        self._catalog_index_map = []

        for idx, playbook in enumerate(self.playbook_catalog):
            # Create searchable description
            service = playbook.service or ""
            description = playbook.description or ""
            desc_text = f"{service} {description}".strip()

            if desc_text:  # Only include playbooks with some description
                descriptions.append(desc_text)
                self._catalog_index_map.append(idx)

        if not descriptions:
            logger.warning("No playbook descriptions available for semantic search")
            # Create empty index
            self.index = faiss.IndexFlatIP(384)  # all-MiniLM-L6-v2 has 384 dimensions
            return

        # Embed all descriptions
        logger.info(f"Embedding {len(descriptions)} playbook descriptions...")
        embeddings = self.embedder.encode(descriptions)

        # Normalize embeddings for cosine similarity
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

        # Create FAISS index
        dimension = embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dimension)  # Inner product = cosine for normalized
        self.index.add(embeddings.astype(np.float32))

        logger.info(f"FAISS index built with {self.index.ntotal} entries")

    def _no_match_result(
        self, task_intent: str, alternatives: Optional[list[dict]] = None
    ) -> MappingResult:
        """Generate no-match result with helpful suggestion.

        Args:
            task_intent: Original task intent
            alternatives: Optional low-confidence alternatives

        Returns:
            MappingResult with method='none' and suggestion
        """
        suggestion = self._generate_no_match_suggestion(task_intent)

        return MappingResult(
            playbook_path=None,
            confidence=0.0,
            method="none",
            alternatives=alternatives or [],
            suggestion=suggestion,
        )

    def _generate_no_match_suggestion(self, task_intent: str) -> str:
        """Generate helpful suggestion when no match found.

        Args:
            task_intent: Original task intent

        Returns:
            Suggestion string for user
        """
        # Extract likely service name (simple heuristic: first word after action verbs)
        words = task_intent.lower().split()
        action_verbs = ["deploy", "install", "setup", "configure", "run", "start"]

        service_name = None
        for i, word in enumerate(words):
            if word in action_verbs and i + 1 < len(words):
                service_name = words[i + 1]
                break

        if service_name:
            return (
                f"No matching playbook found for '{service_name}'. "
                f"Options: 1) Generate template for '{service_name}', "
                f"2) Search homelab-infra manually, "
                f"3) Create custom playbook"
            )
        else:
            return (
                "No matching playbook found. "
                "Options: 1) Provide more specific service name, "
                "2) Search homelab-infra manually, "
                "3) Create custom playbook"
            )
