import json
import asyncio
from game.board import Board
from game.tiles import Tile

async def send_json(writer, data: dict):
    """Envía un objeto serializado en JSON terminado con \n a través del stream."""
    try:
        if writer is None or writer.is_closing():
            return
        raw_msg = (json.dumps(data) + "\n").encode("utf-8")
        writer.write(raw_msg)
        await writer.drain()
    except (ConnectionResetError, BrokenPipeError, OSError, asyncio.CancelledError):
        pass

async def recv_json(reader, timeout: float | None = None) -> dict | None:
    """Lee una línea del stream y la deserializa como JSON. Soporta timeout opcional."""
    try:
        if reader is None:
            return None
        if timeout:
            line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        else:
            line = await reader.readline()
        
        if not line:
            return None
        return json.loads(line.decode("utf-8").strip())
    except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError, OSError, json.JSONDecodeError):
        return None

def serialize_cell(cell) -> dict:
    return {
        "multiplier": cell.multiplier,
        "multiplier_type": cell.multiplier_type,
        "active": cell.active,
        "letter": {"letter": cell.letter.letter, "value": cell.letter.value} if cell.letter else None
    }

def serialize_board(board: Board) -> list:
    return [[serialize_cell(cell) for cell in row] for row in board.grid]

def deserialize_board(board_data: list) -> Board:
    board = Board()
    for r in range(15):
        for c in range(15):
            cdata = board_data[r][c]
            cell = board.grid[r][c]
            cell.multiplier = cdata["multiplier"]
            cell.multiplier_type = cdata["multiplier_type"]
            cell.active = cdata["active"]
            if cdata["letter"]:
                cell.letter = Tile(cdata["letter"]["letter"], cdata["letter"]["value"])
            else:
                cell.letter = None
    return board

def serialize_tiles(tiles: list) -> list:
    return [{"letter": t.letter, "value": t.value} for t in tiles]

def deserialize_tiles(tiles_data: list) -> list:
    return [Tile(td["letter"], td["value"]) for td in tiles_data]
