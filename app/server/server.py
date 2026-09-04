import argparse
import asyncio
import os
import socket
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Optional
from server.logger import logger
from server.lobby import LobbyManager, Room
from server.player_connection import ConnectedPlayer
from server.game_runner import run_game_loop
from server.protocol import recv_json, send_json

class ScrabbleServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 5000):
        self.host = host
        self.port = port
        self.lobby = LobbyManager(on_game_start_callback=self.on_room_game_start)

    async def on_room_game_start(self, room):
        player_names = [p.name for p in room.players]
        logger.info(f"[SALA #{room.room_id}] Partida iniciada con {len(room.players)} jugadores: {player_names}")
        asyncio.create_task(self._run_and_cleanup_room(room))

    async def _run_and_cleanup_room(self, room):
        try:
            await run_game_loop(room)
        finally:
            await room.close_all_connections()
            self.lobby.cleanup_room(room.room_id)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        logger.info(f"[CONEXIÓN] Cliente conectado desde {addr}")
        player: Optional[ConnectedPlayer] = None
        room: Optional[Room] = None

        try:
            # 1. Esperar mensaje de join inicial
            join_msg = await recv_json(reader, timeout=15)
            if not join_msg or join_msg.get("action") != "join":
                logger.warning(f"[CONEXIÓN] Handshake inválido desde {addr}")
                await send_json(writer, {"event": "error", "message": "Handshake invalido. Debe enviar action: join"})
                writer.close()
                await writer.wait_closed()
                return

            player_name = str(join_msg.get("name", "Jugador")).strip() or "Jugador"
            player = ConnectedPlayer(name=player_name, reader=reader, writer=writer)

            # 2. Asignar a sala disponible
            room = self.lobby.get_or_create_available_room()
            logger.info(f"[LOBBY] Jugador '{player_name}' ({addr}) asignado a Sala #{room.room_id}")
            added = await room.add_player(player)

            if not added:
                logger.warning(f"[LOBBY] No se pudo unir a '{player_name}' a la Sala #{room.room_id}")
                await send_json(writer, {"event": "error", "message": "No se pudo unir a la sala disponible."})
                writer.close()
                await writer.wait_closed()
                return

            # 3. Esperar a que la conexión termine sin tocar el reader (game_runner es el único lector)
            try:
                await writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError, OSError, asyncio.CancelledError, GeneratorExit):
                pass

        except (ConnectionResetError, BrokenPipeError, OSError, asyncio.CancelledError, GeneratorExit):
            pass
        except Exception as e:
            logger.error(f"[ERROR] Conexión con {addr}: {e}")
        finally:
            if room is not None and player is not None and room.state in ("WAITING", "STARTING") and player in room.players:
                logger.info(f"[LOBBY] Limpiando jugador desconectado '{player.name}' de Sala #{room.room_id}")
                try:
                    await room.remove_player(player)
                except (Exception, GeneratorExit):
                    pass
            try:
                writer.close()
            except Exception:
                pass

    async def run(self):
        server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port,
            family=socket.AF_INET,
            reuse_address=True
        )
        addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
        logger.info(f"==================================================")
        logger.info(f"  SERVIDOR SCRABBLE ASYNCIO INICIADO")
        logger.info(f"  Escuchando en: {addrs}")
        logger.info(f"  Salas dinámicas (2-4 jugadores, temporizador 30s)")
        logger.info(f"==================================================")

        try:
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            server.close()
            await server.wait_closed()

def main():
    parser = argparse.ArgumentParser(description="Servidor de Scrabble Multijugador Asyncio")
    parser.add_argument("--host", default="0.0.0.0", help="Dirección IP de escucha (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Puerto de escucha (default: 5000)")
    args = parser.parse_args()

    server = ScrabbleServer(host=args.host, port=args.port)
    try:
        asyncio.run(server.run())
    except (KeyboardInterrupt, SystemExit):
        logger.info("[SERVIDOR] Detenido por el usuario.")
        sys.exit(0)

if __name__ == "__main__":
    main()
