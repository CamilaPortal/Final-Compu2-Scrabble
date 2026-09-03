import asyncio
from dataclasses import dataclass

@dataclass
class ConnectedPlayer:
    name: str
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    player_id: int = 0
    room_id: int = 1
