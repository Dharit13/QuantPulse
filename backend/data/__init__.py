from backend.data.cache import data_cache
from backend.data.fetcher import DataFetcher

fetcher = DataFetcher()

__all__ = ["DataFetcher", "fetcher", "data_cache"]
