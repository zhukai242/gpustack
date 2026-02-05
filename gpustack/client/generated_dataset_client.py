import asyncio
import json
import logging
import threading
from typing import Any, Callable, Dict, Optional, Union, Awaitable

import httpx
from gpustack.api.exceptions import (
    raise_if_response_error,
    async_raise_if_response_error,
)
from gpustack.server.bus import Event, EventType
from gpustack.schemas import *
from gpustack.schemas.common import Pagination
from gpustack.schemas.datasets import DatasetPublic, DatasetsPublic

from .generated_http_client import HTTPClient

logger = logging.getLogger(__name__)


class DatasetClient:
    def __init__(self, client: HTTPClient, enable_cache: bool = True):
        self._client = client
        self._url = "/datasets"
        self._enable_cache = enable_cache
        self._cache: Dict[int, DatasetPublic] = {}
        self._cache_lock = None
        self._watch_started = False
        self._initial_sync_logged = False

    def _get_cache_lock(self):
        """Lazy initialization of cache lock."""
        if self._cache_lock is None:
            self._cache_lock = threading.Lock()
        return self._cache_lock

    def list(
        self, params: Dict[str, Any] = None, use_cache: bool = True
    ) -> DatasetsPublic:
        """
        List resources.

        Args:
            params: Query parameters for filtering
            use_cache: Whether to use cache. Defaults to True (use cache if available).
                      Automatically falls back to API if cache watch is not running.
                      Note: If 'page' or 'perPage' params are provided, always calls API.

        Returns:
            List of resources
        """
        if params and ("page" in params or "perPage" in params):
            use_cache = False

        if use_cache and self._watch_started:
            with self._get_cache_lock():
                items = list(self._cache.values())

            pagination = Pagination(
                page=1,
                perPage=len(items),
                total=len(items),
                totalPage=1,
            )
            return DatasetsPublic(items=items, pagination=pagination)

        response = self._client.get(self._url, params=params)
        raise_if_response_error(response)

        data = response.json()
        result = DatasetsPublic.model_validate(data)

        if self._enable_cache:
            with self._get_cache_lock():
                for item in result.items:
                    self._cache[item.id] = item

        return result

    def get(self, id: int, use_cache: bool = True) -> DatasetPublic:
        """
        Get a single resource.

        Args:
            id: Resource ID
            use_cache: Whether to use cache. Defaults to True (use cache if available).
                      Automatically falls back to API if cache watch is not running.

        Returns:
            Resource object
        """
        if use_cache and self._watch_started:
            with self._get_cache_lock():
                if id in self._cache:
                    return self._cache[id]

        response = self._client.get(f"{self._url}/{id}")
        raise_if_response_error(response)

        data = response.json()
        result = DatasetPublic.model_validate(data)

        if self._enable_cache:
            with self._get_cache_lock():
                self._cache[id] = result

        return result

    def watch(
        self,
        callback: Optional[Callable[[Event], None]] = None,
        params: Dict[str, Any] = None,
        stop_condition: Optional[Callable[[Event], bool]] = None,
    ):
        """
        Watch for resource changes.

        Args:
            callback: Optional callback function to call when an event is received
            params: Query parameters for filtering
            stop_condition: Optional function to stop watching when it returns True
        """
        if not self._watch_started:
            self._sync_cache()
            self._watch_started = True

        event_source = EventSource(self._client, self._url, params=params)

        for event in event_source:
            if callback:
                callback(event)

            if stop_condition and stop_condition(event):
                break

    async def awatch(
        self,
        callback: Optional[Callable[[Event], Awaitable[None]]] = None,
        params: Dict[str, Any] = None,
        stop_condition: Optional[Callable[[Event], bool]] = None,
    ):
        """
        Async watch for resource changes.

        Args:
            callback: Optional async callback function to call when an event is received
            params: Query parameters for filtering
            stop_condition: Optional function to stop watching when it returns True
        """
        if not self._watch_started:
            await self._async_sync_cache()
            self._watch_started = True

        event_source = AsyncEventSource(self._client, self._url, params=params)

        async for event in event_source:
            if callback:
                await callback(event)

            if stop_condition and stop_condition(event):
                break

    def _sync_cache(self):
        """
        Sync cache with server.
        """
        try:
            result = self.list(use_cache=False)
            with self._get_cache_lock():
                self._cache.clear()
                for item in result.items:
                    self._cache[item.id] = item

            if not self._initial_sync_logged:
                logger.debug(f"Synced {len(self._cache)} datasets to cache")
                self._initial_sync_logged = True
        except Exception as e:
            logger.warning(f"Failed to sync datasets cache: {e}")

    async def _async_sync_cache(self):
        """
        Async sync cache with server.
        """
        try:
            result = await self.alist(use_cache=False)
            with self._get_cache_lock():
                self._cache.clear()
                for item in result.items:
                    self._cache[item.id] = item

            if not self._initial_sync_logged:
                logger.debug(f"Synced {len(self._cache)} datasets to cache")
                self._initial_sync_logged = True
        except Exception as e:
            logger.warning(f"Failed to sync datasets cache: {e}")

    async def alist(
        self, params: Dict[str, Any] = None, use_cache: bool = True
    ) -> DatasetsPublic:
        """
        Async list resources.

        Args:
            params: Query parameters for filtering
            use_cache: Whether to use cache. Defaults to True (use cache if available).
                      Automatically falls back to API if cache watch is not running.
                      Note: If 'page' or 'perPage' params are provided, always calls API.

        Returns:
            List of resources
        """
        if params and ("page" in params or "perPage" in params):
            use_cache = False

        if use_cache and self._watch_started:
            with self._get_cache_lock():
                items = list(self._cache.values())

            pagination = Pagination(
                page=1,
                perPage=len(items),
                total=len(items),
                totalPage=1,
            )
            return DatasetsPublic(items=items, pagination=pagination)

        response = await self._client.aget(self._url, params=params)
        await async_raise_if_response_error(response)

        data = response.json()
        result = DatasetsPublic.model_validate(data)

        if self._enable_cache:
            with self._get_cache_lock():
                for item in result.items:
                    self._cache[item.id] = item

        return result

    async def aget(self, id: int, use_cache: bool = True) -> DatasetPublic:
        """
        Async get a single resource.

        Args:
            id: Resource ID
            use_cache: Whether to use cache. Defaults to True (use cache if available).
                      Automatically falls back to API if cache watch is not running.

        Returns:
            Resource object
        """
        if use_cache and self._watch_started:
            with self._get_cache_lock():
                if id in self._cache:
                    return self._cache[id]

        response = await self._client.aget(f"{self._url}/{id}")
        await async_raise_if_response_error(response)

        data = response.json()
        result = DatasetPublic.model_validate(data)

        if self._enable_cache:
            with self._get_cache_lock():
                self._cache[id] = result

        return result


class EventSource:
    """
    Event source for watching resource changes.
    """

    def __init__(self, client: HTTPClient, url: str, params: Dict[str, Any] = None):
        self._client = client
        self._url = url
        self._params = params

    def __iter__(self):
        while True:
            try:
                response = self._client.get(
                    f"{self._url}/watch",
                    params=self._params,
                    stream=True,
                    timeout=None,
                )

                for line in response.iter_lines():
                    if not line:
                        continue

                    event_data = json.loads(line)
                    event = Event.model_validate(event_data)
                    yield event
            except Exception as e:
                logger.warning(f"Error in event source: {e}")
                import time

                time.sleep(1)


class AsyncEventSource:
    """
    Async event source for watching resource changes.
    """

    def __init__(self, client: HTTPClient, url: str, params: Dict[str, Any] = None):
        self._client = client
        self._url = url
        self._params = params

    async def __aiter__(self):
        while True:
            try:
                async with self._client.aget(
                    f"{self._url}/watch",
                    params=self._params,
                    stream=True,
                    timeout=None,
                ) as response:
                    async for line in response.aiter_lines():
                        if not line:
                            continue

                        event_data = json.loads(line)
                        event = Event.model_validate(event_data)
                        yield event
            except Exception as e:
                logger.warning(f"Error in async event source: {e}")
                await asyncio.sleep(1)
