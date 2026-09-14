import argparse
import asyncio
import os
import socket
import sys
import multiprocessing
import queue
from datetime import datetime, timezone
from typing import Dict, Optional

from database import (
    init_db,
    register_user,
    authenticate_user,
    save_finished_game,
    get_top_players,
)
from server.logger import logger
from server.lobby import LobbyManager, Room
from server.player_connection import ConnectedPlayer
from server.room_process import run_room_process
from server.protocol import recv_json, send_json

class ScrabbleServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 5000):
        self.host = host
        self.port = port
        init_db()
        self.active_sessions: Dict[str, Optional[ConnectedPlayer]] = {}
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

        started_at = datetime.now()
        players_data = [{"id": p.player_id, "name": p.name, "user_id": p.user_id} for p in room.players]
        players_by_id = {p.player_id: p for p in room.players}

        # Lanzar proceso hijo usando contexto spawn
        proc = mp_ctx.Process(
            target=run_room_process,
            args=(room.room_id, players_data, action_queue, event_queue),
            name=f"RoomProcess-{room.room_id}"
        )
        proc.start()
        logger.info(f"[LOBBY] Proceso de Sala #{room.room_id} iniciado en proceso hijo con PID {proc.pid}")

        # Asignar la cola de acciones a cada jugador para que handle_client transmita las jugadas por IPC
        for p in room.players:
            p.action_queue = action_queue

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

                if data.get("event") == "game_over":
                    finished_at = datetime.now()
                    duration_seconds = max(1, int((finished_at - started_at).total_seconds()))
                    try:
                        await asyncio.to_thread(
                            save_finished_game,
                            room.room_id,
                            started_at,
                            finished_at,
                            duration_seconds,
                            players_data,
                            data.get("final_scores", {}),
                            data.get("winners", []),
                        )
                        logger.info(f"[SALA #{room.room_id}] Partida guardada exitosamente en la base de datos.")
                    except Exception as dbe:
                        logger.error(f"[SALA #{room.room_id}] Error al guardar partida en base de datos: {dbe}")

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
            for p in room.players:
                p.action_queue = None

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
        session_key: Optional[str] = None
        player_name: str = "Jugador"

        try:
            # 1. Bucle de autenticación y menú previo al ingreso al lobby
            authenticated_user = None
            while True:
                msg = await recv_json(reader)
                if msg is None:
                    logger.info(f"[CONEXIÓN] Cliente {addr} desconectado antes de autenticarse.")
                    return

                action = msg.get("action")

                if action == "register":
                    u_name = str(msg.get("username", "")).strip()
                    u_pass = str(msg.get("password", ""))
                    ok, message, u_data = await asyncio.to_thread(register_user, u_name, u_pass)
                    if ok:
                        logger.info(f"[AUTH] Usuario '{u_name}' registrado exitosamente desde {addr}")
                        session_key = u_name.lower()
                        if session_key in self.active_sessions:
                            await send_json(writer, {"event": "auth_error", "message": "Esta cuenta ya tiene una sesión activa."})
                            session_key = None
                            continue
                        self.active_sessions[session_key] = None
                        authenticated_user = u_data
                        await send_json(writer, {
                            "event": "auth_success",
                            "message": message,
                            "username": u_data["username"],
                            "user_id": u_data["id"],
                        })
                        break
                    else:
                        logger.warning(f"[AUTH] Falló registro para '{u_name}' desde {addr}: {message}")
                        await send_json(writer, {"event": "auth_error", "message": message})

                elif action == "login":
                    u_name = str(msg.get("username", "")).strip()
                    u_pass = str(msg.get("password", ""))
                    s_key = u_name.lower()
                    if s_key in self.active_sessions:
                        logger.warning(f"[AUTH] Intento de doble sesión para '{u_name}' desde {addr}")
                        await send_json(writer, {"event": "auth_error", "message": f"La cuenta '{u_name}' ya tiene una sesión activa en el servidor."})
                        continue

                    ok, message, u_data = await asyncio.to_thread(authenticate_user, u_name, u_pass)
                    if ok:
                        logger.info(f"[AUTH] Usuario '{u_name}' autenticado exitosamente desde {addr}")
                        session_key = s_key
                        self.active_sessions[session_key] = None
                        authenticated_user = u_data
                        await send_json(writer, {
                            "event": "auth_success",
                            "message": message,
                            "username": u_data["username"],
                            "user_id": u_data["id"],
                        })
                        break
                    else:
                        logger.warning(f"[AUTH] Credenciales inválidas para '{u_name}' desde {addr}")
                        await send_json(writer, {"event": "auth_error", "message": message})

                elif action == "get_ranking":
                    ranking = await asyncio.to_thread(get_top_players, 10)
                    await send_json(writer, {
                        "event": "ranking_data",
                        "ranking": ranking,
                    })

                elif action == "join":
                    u_name = str(msg.get("name", "Jugador")).strip() or "Jugador"
                    s_key = u_name.lower()
                    if s_key in self.active_sessions:
                        await send_json(writer, {"event": "auth_error", "message": f"El nombre '{u_name}' ya está en uso en el servidor."})
                        continue
                    session_key = s_key
                    self.active_sessions[session_key] = None
                    authenticated_user = {"id": None, "username": u_name}
                    await send_json(writer, {
                        "event": "auth_success",
                        "message": f"Bienvenido, {u_name}",
                        "username": u_name,
                        "user_id": None,
                    })
                    break
                else:
                    await send_json(writer, {"event": "auth_error", "message": "Acción no reconocida."})

            # 2. Asignar a sala disponible en el lobby
            player_name = authenticated_user["username"]
            player = ConnectedPlayer(
                name=player_name,
                reader=reader,
                writer=writer,
                user_id=authenticated_user.get("id"),
            )
            if session_key:
                self.active_sessions[session_key] = player

            room = self.lobby.get_or_create_available_room()
            logger.info(f"[LOBBY] Jugador '{player_name}' ({addr}) asignado a Sala #{room.room_id}")
            added = await room.add_player(player)

            if not added:
                logger.warning(f"[LOBBY] No se pudo unir a '{player_name}' a la Sala #{room.room_id}")
                await send_json(writer, {"event": "error", "message": "No se pudo unir a la sala disponible."})
                return

            # 3. Bucle único de lectura de red para este cliente durante toda su sesión
            while True:
                msg = await recv_json(reader)
                if msg is None:
                    if room is not None and room.state in ("WAITING", "STARTING"):
                        logger.info(f"[LOBBY] Cliente '{player_name}' se desconectó del lobby.")
                        await room.remove_player(player)
                    elif player.action_queue is not None:
                        logger.warning(f"[BRIDGE] Socket cerrado (EOF) de '{player_name}' (id={player.player_id})")
                        player.action_queue.put({
                            "player_id": player.player_id,
                            "action_data": {"action": "disconnect"}
                        })
                    break

                if player.action_queue is not None:
                    player.action_queue.put({
                        "player_id": player.player_id,
                        "action_data": msg
                    })

        except (ConnectionResetError, BrokenPipeError):
            if room is not None and room.state in ("WAITING", "STARTING"):
                logger.info(f"[LOBBY] Conexión reseteada para '{player_name}' en el lobby.")
                await room.remove_player(player)
            elif player is not None and player.action_queue is not None:
                player.action_queue.put({
                    "player_id": player.player_id,
                    "action_data": {"action": "disconnect"}
                })
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[ERROR] Conexión con {addr}: {e}")
        finally:
            if session_key and session_key in self.active_sessions:
                del self.active_sessions[session_key]
                logger.info(f"[AUTH] Sesión liberada para '{session_key}'")
            if room is not None and player is not None and room.state in ("WAITING", "STARTING") and player in room.players:
                try:
                    await room.remove_player(player)
                except Exception:
                    pass
            try:
                writer.close()
                await writer.wait_closed()
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
