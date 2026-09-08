import argparse
import asyncio
import os
import socket
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import multiprocessing
import queue
from typing import Optional
from server.logger import logger
from server.lobby import LobbyManager, Room
from server.player_connection import ConnectedPlayer
from server.room_process import run_room_process
from server.protocol import recv_json, send_json

class ScrabbleServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 5000):
        self.host = host
        self.port = port
        self.lobby = LobbyManager(on_game_start_callback=self.on_room_game_start)

    async def on_room_game_start(self, room):
        player_names = [p.name for p in room.players]
        logger.info(f"[SALA #{room.room_id}] Partida iniciada con {len(room.players)} jugadores: {player_names}")
        asyncio.create_task(self._run_room_multiprocess(room))

    async def _run_room_multiprocess(self, room: Room):
        """
        Administra el ciclo de vida del proceso hijo de la sala y el puente de red con los clientes.
        """
        mp_ctx = multiprocessing.get_context("spawn")
        action_queue = mp_ctx.Queue()
        event_queue = mp_ctx.Queue()

        players_data = [{"id": p.player_id, "name": p.name} for p in room.players]
        players_by_id = {p.player_id: p for p in room.players}

        # Lanzar proceso hijo usando contexto spawn
        proc = mp_ctx.Process(
            target=run_room_process,
            args=(room.room_id, players_data, action_queue, event_queue),
            name=f"RoomProcess-{room.room_id}"
        )
        proc.start()
        logger.info(f"[LOBBY] Proceso de Sala #{room.room_id} iniciado en proceso hijo con PID {proc.pid}")

        # Tarea A: Leer de cada socket TCP y enviar acciones al proceso hijo por IPC
        async def client_reader(p: ConnectedPlayer):
            pid_fixed = p.player_id
            name_fixed = p.name
            try:
                while True:
                    msg = await recv_json(p.reader)
                    if msg is None:
                        logger.warning(f"[BRIDGE] Socket cerrado (EOF) de '{name_fixed}' (id={pid_fixed})")
                        action_queue.put({"player_id": pid_fixed, "action_data": {"action": "disconnect"}})
                        break
                    action_queue.put({"player_id": pid_fixed, "action_data": msg})
            except asyncio.CancelledError:
                pass
            except (ConnectionResetError, BrokenPipeError):
                logger.warning(f"[BRIDGE] Conexión reseteada para '{name_fixed}' (id={pid_fixed})")
                action_queue.put({"player_id": pid_fixed, "action_data": {"action": "disconnect"}})
            except Exception as e:
                logger.error(f"[SALA #{room.room_id}] Error leyendo socket de '{name_fixed}': {e}")
                action_queue.put({"player_id": pid_fixed, "action_data": {"action": "disconnect"}})

        reader_tasks = [asyncio.create_task(client_reader(p)) for p in room.players]

        # Tarea B: Leer eventos del proceso hijo por IPC y transmitirlos a los sockets
        try:
            while True:
                try:
                    item = await asyncio.to_thread(event_queue.get, timeout=0.2)
                except queue.Empty:
                    if not proc.is_alive():
                        break
                    continue

                target = item.get("target")
                data = item.get("data", {})

                if target == "internal" and data.get("event") == "room_finished":
                    break

                if target == "all":
                    await room.broadcast(data)
                elif isinstance(target, int) and target in players_by_id:
                    p_target = players_by_id[target]
                    await send_json(p_target.writer, data)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[SALA #{room.room_id}] Error en despachador de eventos IPC: {e}")
        finally:
            for t in reader_tasks:
                t.cancel()

            try:
                await asyncio.to_thread(proc.join, timeout=3.0)
                if proc.is_alive():
                    proc.terminate()
                    await asyncio.to_thread(proc.join)
            except Exception:
                pass

            try:
                action_queue.cancel_join_thread()
                event_queue.cancel_join_thread()
                action_queue.close()
                event_queue.close()
            except Exception:
                pass

            await room.close_all_connections()
            self.lobby.cleanup_room(room.room_id)
            logger.info(f"[LOBBY] Proceso de Sala #{room.room_id} (PID {proc.pid}) finalizado y recursos liberados.")

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

            # 3. Esperar a que la conexión termine sin tocar el reader (client_reader en _run_room_multiprocess es el lector)
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
