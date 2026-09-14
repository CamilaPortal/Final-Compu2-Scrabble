import asyncio
from dataclasses import dataclass
from typing import Optional, Any

@dataclass
class ConnectedPlayer:
    name: str
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    user_id: Optional[int] = None
    player_id: int = 0
    room_id: int = 1
    action_queue: Optional[Any] = None
