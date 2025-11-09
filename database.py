import enum
import threading
import pymongo
from typing import Optional, Callable
from constants import MONGO_URI
from utils import log_error

class ConnectionStatus(enum.Enum):
    """Enum representing different database connection states."""
    DISCONNECTED = enum.auto()
    CONNECTING = enum.auto()
    CONNECTED = enum.auto()
    ERROR = enum.auto()

class DatabaseConnectionError(Exception):
    """Custom exception for database connection failures."""
    pass

class DatabaseConnectionContext:
    """Context manager for database connections."""
    def __init__(self, client: pymongo.MongoClient, db_name: str = "SmartKitchen"):
        self._client = client
        self._db_name = db_name
        self._connection = None

    def __enter__(self):
        self._connection = self._client[self._db_name]
        return self._connection

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class DatabaseStateMachine:
    """State machine for managing database connections."""
    def __init__(self, connection_factory: Callable[[], pymongo.MongoClient]):
        self._factory = connection_factory
        self._client: Optional[pymongo.MongoClient] = None
        self._state = ConnectionStatus.DISCONNECTED
        self._lock = threading.Lock()
        self._connection_error: Optional[str] = None

    def connect(self) -> None:
        if self._state == ConnectionStatus.CONNECTED:
            return

        with self._lock:
            if self._state == ConnectionStatus.CONNECTED:
                return

            try:
                self._client = self._factory()
                self._client.server_info()
                self._state = ConnectionStatus.CONNECTED
                self._connection_error = None
            except Exception as e:
                self._state = ConnectionStatus.ERROR
                self._client = None
                self._connection_error = str(e)
                raise DatabaseConnectionError(f"Failed to establish database connection: {e}")

    def get_client(self) -> pymongo.MongoClient:
        if self._state != ConnectionStatus.CONNECTED:
            self.connect()
       
        if self._state == ConnectionStatus.ERROR:
            raise DatabaseConnectionError(
                f"Cannot establish database connection. Last error: {self._connection_error}"
            )
       
        return self._client

    @property
    def status(self) -> ConnectionStatus:
        return self._state

    @property
    def error(self) -> Optional[str]:
        return self._connection_error