import json
import asyncio
from typing import List, Dict, Optional
from server.player_connection import ConnectedPlayer
from server.protocol import send_json
from server.logger import logger

class Room:
    def __init__(self, room_id: int, on_game_start_callback):
        self.room_id = room_id
        self.players: List[ConnectedPlayer] = []
        self.state = "WAITING"  # WAITING, STARTING, IN_GAME, FINISHED
        self.countdown_task: Optional[asyncio.Task] = None
        self.on_game_start_callback = on_game_start_callback
        self.countdown_seconds = 30

    @property
    def is_available(self) -> bool:
        return self.state in ("WAITING", "STARTING") and len(self.players) < 4

    async def add_player(self, player: ConnectedPlayer) -> bool:
        if not self.is_available:
            return False

        player.player_id = len(self.players)
        player.room_id = self.room_id
        self.players.append(player)
        logger.info(f"[SALA #{self.room_id}] Jugador '{player.name}' ingresó. Total en sala: {len(self.players)}/4")

        # Enviar bienvenida al jugador
        await send_json(player.writer, {
            "event": "welcome",
            "player_id": player.player_id,
            "room_id": self.room_id,
            "player_name": player.name
        })

        # Notificar a todos los jugadores de la sala
        await self.broadcast_lobby_status()

        # Evaluar inicio o cuenta regresiva
        if len(self.players) == 4:
            logger.info(f"[SALA #{self.room_id}] Sala llena (4 jugadores) -> Inicio instantáneo.")
            if self.countdown_task and not self.countdown_task.done():
                self.countdown_task.cancel()
            asyncio.create_task(self.start_game())
        elif len(self.players) >= 2 and self.state == "WAITING":
            self.state = "STARTING"
            logger.info(f"[SALA #{self.room_id}] 2 jugadores alcanzados -> Iniciando cuenta regresiva de {self.countdown_seconds}s.")
            self.countdown_task = asyncio.create_task(self._run_countdown(self.countdown_seconds))

        return True

    async def remove_player(self, player: ConnectedPlayer):
        if player in self.players:
            self.players.remove(player)
            logger.info(f"[SALA #{self.room_id}] Jugador '{player.name}' salió. Restan: {len(self.players)}/4")
            
            for idx, p in enumerate(self.players):
                p.player_id = idx

            if self.state == "STARTING" and len(self.players) < 2:
                logger.warning(f"[SALA #{self.room_id}] Menos de 2 jugadores -> Cuenta regresiva cancelada.")
                if self.countdown_task and not self.countdown_task.done():
                    self.countdown_task.cancel()
                self.state = "WAITING"
                await self.broadcast({
                    "event": "message",
                    "type": "warning",
                    "text": "Se canceló la cuenta regresiva por falta de jugadores (mínimo 2)."
                })

            if len(self.players) == 0:
                self.state = "WAITING"
                if self.countdown_task and not self.countdown_task.done():
                    self.countdown_task.cancel()

            await self.broadcast_lobby_status()

    async def _run_countdown(self, seconds: int):
        try:
            for remaining in range(seconds, 0, -1):
                if remaining in (30, 20, 15, 10, 5, 4, 3, 2, 1):
                    logger.info(f"[SALA #{self.room_id}] Cuenta regresiva: {remaining}s restantes...")
                    await self.broadcast({
                        "event": "lobby_countdown",
                        "remaining_seconds": remaining,
                        "players": [p.name for p in self.players]
                    })
                await asyncio.sleep(1)
            
            await self.start_game()
        except asyncio.CancelledError:
            pass

    async def start_game(self):
        if self.state == "IN_GAME":
            return
        if len(self.players) < 2:
            self.state = "WAITING"
            return

        self.state = "IN_GAME"
        player_names = [p.name for p in self.players]
        logger.info(f"[SALA #{self.room_id}] Partida iniciada oficialmente entre: {player_names}")
        await self.broadcast({
            "event": "game_start",
            "room_id": self.room_id,
            "players": player_names
        })
        await self.on_game_start_callback(self)

    async def broadcast(self, data: dict):
        for p in list(self.players):
            if p.writer.is_closing():
                await self.remove_player(p)
                continue
            try:
                raw_msg = (json.dumps(data) + "\n").encode("utf-8")
                p.writer.write(raw_msg)
                await p.writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError):
                await self.remove_player(p)

    async def close_all_connections(self):
        for p in list(self.players):
            try:
                p.writer.close()
                await p.writer.wait_closed()
            except Exception:
                pass
        self.players.clear()

    async def broadcast_lobby_status(self):
        player_names = [p.name for p in self.players]
        await self.broadcast({
            "event": "lobby_update",
            "room_id": self.room_id,
            "state": self.state,
            "player_count": len(self.players),
            "players": player_names
        })


class LobbyManager:
    def __init__(self, on_game_start_callback):
        self.rooms: Dict[int, Room] = {}
        self.next_room_id = 1
        self.on_game_start_callback = on_game_start_callback

    def get_or_create_available_room(self) -> Room:
        for room in self.rooms.values():
            if room.is_available:
                return room
        
        new_room = Room(self.next_room_id, self.on_game_start_callback)
        self.rooms[self.next_room_id] = new_room
        logger.info(f"[LOBBY] Nueva Sala #{self.next_room_id} creada y disponible.")
        self.next_room_id += 1
        return new_room

    def get_room(self, room_id: int) -> Optional[Room]:
        return self.rooms.get(room_id)

    def cleanup_room(self, room_id: int):
        if room_id in self.rooms:
            self.rooms.pop(room_id, None)
            logger.info(f"[LOBBY] Sala #{room_id} liberada.")
        
        active_rooms = [r for r in self.rooms.values() if r.state != "FINISHED"]
        if not active_rooms:
            self.rooms.clear()
            self.next_room_id = 1
            logger.info("[LOBBY] No hay salas activas. Próxima sala reiniciada a #1.")
