"""Playbook discovery service for Ansible repository scanning.

Provides:
- PlaybookMetadata: Pydantic model for playbook metadata
- PlaybookDiscovery: Service for lazy scanning with caching
- Metadata extraction from YAML headers and filenames
- 1-hour cache TTL with force refresh option
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from ruamel.yaml import YAML

logger = logging.getLogger(__name__)


class PlaybookMetadata(BaseModel):
    """Metadata extracted from an Ansible playbook.

    Attributes:
        path: Full path to the playbook file
        filename: Just the filename (for display)
        service: Service name (from filename pattern or header comment)
        description: Human-readable description (from header or play name)
        required_vars: List of variable names required by playbook
        tags: List of tags for categorization
        discovered_at: Timestamp when this was scanned
    """

    path: str
    filename: str
    service: Optional[str] = None
    description: Optional[str] = None
    required_vars: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    discovered_at: datetime = Field(default_factory=datetime.utcnow)


class PlaybookDiscovery:
    """Service for discovering and cataloging Ansible playbooks.

    Scans repository recursively for *.yml and *.yaml files, extracts metadata,
    and caches results for 1 hour (configurable TTL).

    Features:
    - Lazy loading: Scans only on first discover_playbooks() call
    - Cache TTL: Default 1 hour, configurable
    - Metadata extraction: Service name, description, vars, tags
    - Error handling: Invalid YAML files skipped with warning logged
    """

    def __init__(
        self,
        repo_path: str,
        cache_ttl_seconds: int = 3600,
    ):
        """Initialize the playbook discovery service.

        Args:
            repo_path: Path to Ansible playbook repository
            cache_ttl_seconds: Cache time-to-live in seconds (default: 3600 = 1 hour)
        """
        self.repo_path = Path(repo_path).expanduser()
        self.cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._cache: dict[str, PlaybookMetadata] = {}
        self._cache_time: Optional[datetime] = None
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.default_flow_style = False

        logger.info(
            f"PlaybookDiscovery initialized: repo={self.repo_path}, ttl={cache_ttl_seconds}s"
        )

    def is_cache_valid(self) -> bool:
        """Check if cache is valid (within TTL).

        Returns:
            True if cache exists and hasn't expired, False otherwise
        """
        if self._cache_time is None:
            return False

        age = datetime.utcnow() - self._cache_time
        return age < self.cache_ttl

    async def discover_playbooks(
        self, force_refresh: bool = False
    ) -> list[PlaybookMetadata]:
        """Discover playbooks from repository.

        Scans recursively for *.yml and *.yaml files, extracts metadata,
        and caches results. Returns cached results if cache is valid
        and force_refresh is False.

        Args:
            force_refresh: If True, ignore cache and rescan repository

        Returns:
            List of PlaybookMetadata objects
        """
        # Check cache validity
        if not force_refresh and self.is_cache_valid():
            logger.info(
                f"Cache valid, returning {len(self._cache)} cached playbooks"
            )
            return list(self._cache.values())

        # Scan repository
        logger.info(f"Scanning repository: {self.repo_path}")

        if not self.repo_path.exists():
            logger.warning(f"Repository path does not exist: {self.repo_path}")
            return []

        catalog: list[PlaybookMetadata] = []
        playbook_files = list(self.repo_path.rglob("*.yml")) + list(
            self.repo_path.rglob("*.yaml")
        )

        logger.info(f"Found {len(playbook_files)} YAML files to scan")

        for playbook_path in playbook_files:
            try:
                metadata = await self._extract_metadata(playbook_path)
                if metadata:
                    catalog.append(metadata)
                    logger.debug(
                        f"Extracted metadata: {playbook_path.name} -> service={metadata.service}"
                    )
            except Exception as e:
                logger.warning(
                    f"Skipping invalid playbook {playbook_path}: {e}", exc_info=False
                )

        # Update cache
        self._cache = {pb.path: pb for pb in catalog}
        self._cache_time = datetime.utcnow()

        logger.info(
            f"Discovery complete: {len(catalog)} playbooks indexed, cache updated"
        )
        return catalog

    def get_cached_catalog(self) -> list[PlaybookMetadata]:
        """Get cached playbook catalog without rescanning.

        Returns:
            List of cached PlaybookMetadata objects (empty if cache invalid)
        """
        if self.is_cache_valid():
            return list(self._cache.values())
        return []

    async def _extract_metadata(
        self, playbook_path: Path
    ) -> Optional[PlaybookMetadata]:
        """Extract metadata from a playbook file.

        Metadata extraction strategy:
        1. Service name: Header comment (# chiffon:service=xxx) OR filename pattern
        2. Description: Header comment (# chiffon:description=xxx) OR first play name
        3. Required vars: First play's "vars:" section keys
        4. Tags: First play's "tags:" field

        Args:
            playbook_path: Path to playbook file

        Returns:
            PlaybookMetadata object or None if parsing fails
        """
        try:
            with open(playbook_path, "r") as f:
                # Read file content for header comment parsing
                content = f.read()
                f.seek(0)  # Reset for YAML parsing

                # Parse YAML
                data = self._yaml.load(f)

            # Initialize metadata
            metadata = PlaybookMetadata(
                path=str(playbook_path),
                filename=playbook_path.name,
            )

            # Extract service name from filename pattern
            # Example: kuma-deploy.yml -> service="kuma"
            filename_parts = playbook_path.stem.split("-")
            if filename_parts:
                metadata.service = filename_parts[0]

            # Override service from header comment if present
            # Format: # chiffon:service=kuma
            for line in content.split("\n"):
                if line.strip().startswith("#"):
                    if "chiffon:service=" in line:
                        service = line.split("chiffon:service=", 1)[1].strip()
                        metadata.service = service
                    if "chiffon:description=" in line:
                        description = line.split("chiffon:description=", 1)[1].strip()
                        metadata.description = description

            # Extract metadata from first play
            if isinstance(data, list) and len(data) > 0:
                play = data[0]

                # Description from play name if not set
                if metadata.description is None and "name" in play:
                    metadata.description = play["name"]

                # Required vars from play vars section
                if "vars" in play and isinstance(play["vars"], dict):
                    metadata.required_vars = list(play["vars"].keys())

                # Tags from play tags field
                if "tags" in play:
                    if isinstance(play["tags"], list):
                        metadata.tags = play["tags"]
                    elif isinstance(play["tags"], str):
                        metadata.tags = [play["tags"]]

            return metadata

        except Exception as e:
            logger.debug(f"Failed to extract metadata from {playbook_path}: {e}")
            return None
