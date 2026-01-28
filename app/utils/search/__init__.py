# Unified search system
# Single search bar → intent detection → entity extraction → query execution → response formatting

from .pipeline import search
from .models.responses import SearchResponse

__all__ = ["search", "SearchResponse"]
