import os
import time
import queue
import multiprocessing
from game.scrabble import ScrabbleGame
from server.protocol import serialize_board, serialize_tiles
from server.logger import logger

def run_room_process(room_id: int, initial_players: list, action_queue: multiprocessing.Queue, event_queue: multiprocessing.Queue):
    """
    Función de entrada para el proceso hijo independiente de una sala de Scrabble.
    Corre en su propio espacio de memoria y PID del sistema operativo.
    Comunica acciones y eventos con el servidor principal mediante IPC (multiprocessing.Queue).
    """
    pid = os.getpid()
    active_players = list(initial_players)  # Lista de diccionarios: [{'id': int, 'name': str}, ...]
    player_count = len(active_players)
    player_names = [p["name"] for p in active_players]

    logger.info(f"[PROCESO SALA #{room_id} (PID {pid})] Proceso de sala iniciado con {player_count} jugadores: {player_names}")

    # Inicializar motor de Scrabble en este proceso
    game = ScrabbleGame(player_count)
    logger.info(f"[PROCESO SALA #{room_id} (PID {pid})] Tablero y bolsa ({len(game.bag_tiles.tiles)} fichas) inicializados")

    # Notificar inicio de la partida
    event_queue.put({
        "target": "all",
        "data": {
            "event": "message",
            "type": "info",
            "text": f"Partida iniciada en Sala #{room_id} (PID {pid}) con {player_count} jugadores: {', '.join(player_names)}"
        }
    })

    def handle_disconnect(sender_id: int) -> bool:
        """Gestiona la desconexión o abandono de un jugador. Retorna True si la partida finaliza."""
        disc_player = next((p for p in active_players if p["id"] == sender_id), None)
        if not disc_player:
            return False

        disc_idx = active_players.index(disc_player)
        disc_name = disc_player["name"]
        active_players.remove(disc_player)
        logger.warning(f"[PROCESO SALA #{room_id} (PID {pid})] Jugador '{disc_name}' desconectado de la partida.")

        # Devolver fichas a la bolsa y quitar de ScrabbleGame
        if disc_idx < len(game.players):
            disc_game_player = game.players[disc_idx]
            game.bag_tiles.put(disc_game_player.tiles)
            del game.players[disc_idx]

        # Ajustar índice de turno actual
        if disc_idx < game.current_player:
            game.current_player -= 1
        elif game.current_player >= len(game.players) and len(game.players) > 0:
            game.current_player = 0

        # Reiniciar pases consecutivos
        game.consecutive_passes = 0

        # Evaluar si la partida debe terminar
        if len(active_players) < 2:
            if len(active_players) == 1:
                winner = active_players[0]
                winner_score = game.players[0].score if len(game.players) > 0 else 0
                logger.info(f"[PROCESO SALA #{room_id} (PID {pid})] Queda 1 jugador. '{winner['name']}' gana por abandono.")
                event_queue.put({
                    "target": "all",
                    "data": {
                        "event": "message",
                        "type": "warning",
                        "text": f"{disc_name} se ha desconectado. ¡Victoria por abandono para {winner['name']}!"
                    }
                })
                event_queue.put({
                    "target": "all",
                    "data": {
                        "event": "game_over",
                        "winners": [winner["name"]],
                        "final_scores": {winner["name"]: winner_score}
                    }
                })
            else:
                logger.info(f"[PROCESO SALA #{room_id} (PID {pid})] Todos los jugadores se desconectaron.")
            return True
        else:
            remaining_names = [p["name"] for p in active_players]
            event_queue.put({
                "target": "all",
                "data": {
                    "event": "message",
                    "type": "warning",
                    "text": f"{disc_name} se ha desconectado de la partida. La partida continúa con: {', '.join(remaining_names)}."
                }
            })
            return False

    # Bucle principal de la partida
    while not game.finish_game() and len(active_players) >= 2:
        current_idx = game.current_player
        if current_idx >= len(active_players):
            current_idx = current_idx % len(active_players)
            game.current_player = current_idx

        current_player = active_players[current_idx]
        current_player_game = game.players[current_idx]

        # 1. Transmitir estado actualizado (tablero, atril, puntajes)
        scores_dict = {active_players[i]["name"]: game.players[i].score for i in range(len(active_players))}
        board_data = serialize_board(game.board)
        bag_count = len(game.bag_tiles.tiles)

        logger.info(f"[PROCESO SALA #{room_id} (PID {pid})] [TURNO] Jugador #{current_idx} '{current_player['name']}' | Puntajes: {scores_dict} | Fichas en bolsa: {bag_count}")

        for i, p in enumerate(active_players):
            event_queue.put({
                "target": p["id"],
                "data": {
                    "event": "turn_info",
                    "room_id": room_id,
                    "current_player_idx": current_idx,
                    "current_player_name": current_player["name"],
                    "is_your_turn": (i == current_idx),
                    "board": board_data,
                    "rack": serialize_tiles(game.players[i].tiles) if i < len(game.players) else [],
                    "scores": scores_dict,
                    "bag_count": bag_count,
                    "timeout": 60
                }
            })

        # 2. Bucle interactivo del turno con temporizador estricto de 60 segundos
        turn_completed = False
        turn_start_time = time.time()
        turn_timeout = 60.0

        while not turn_completed and not game.finish_game() and len(active_players) >= 2:
            remaining_time = max(0.1, turn_timeout - (time.time() - turn_start_time))
            try:
                msg = action_queue.get(timeout=remaining_time)
            except queue.Empty:
                # Timeout alcanzado para el jugador actual
                logger.warning(f"[PROCESO SALA #{room_id} (PID {pid})] Timeout de 60s alcanzado para '{current_player['name']}'. Pase de turno automático.")
                event_queue.put({
                    "target": "all",
                    "data": {
                        "event": "message",
                        "type": "warning",
                        "text": f"Tiempo agotado para {current_player['name']}. Se pasa el turno automáticamente."
                    }
                })
                game.pass_turn()
                turn_completed = True
                break

            sender_id = msg.get("player_id")
            action_data = msg.get("action_data", {})
            action = action_data.get("action")

            # Manejar desconexión o abandono voluntario
            if action in ("disconnect", "quit"):
                game_finished = handle_disconnect(sender_id)
                turn_completed = True
                if game_finished:
                    break
                else:
                    # Quedan al menos 2 jugadores: reiniciar turno con la nueva configuración
                    break

            # Solo procesar acciones del jugador en turno
            if sender_id != current_player["id"]:
                continue

            if action == "play_word":
                word = str(action_data.get("word", "")).upper()
                row = int(action_data.get("row", 0))
                col = int(action_data.get("col", 0))
                orientation = str(action_data.get("orientation", "H")).upper()

                try:
                    prev_score = current_player_game.score
                    game.play(word, (row, col), orientation, current_player_game.tiles)
                    earned = current_player_game.score - prev_score

                    logger.info(f"[PROCESO SALA #{room_id} (PID {pid})] Jugada válida: '{current_player['name']}' colocó '{word}' en ({row}, {col}) [{orientation}] -> +{earned} pts")

                    event_queue.put({
                        "target": sender_id,
                        "data": {
                            "event": "action_result",
                            "success": True,
                            "message": f"¡Palabra '{word}' jugada con éxito! (+{earned} pts)"
                        }
                    })
                    event_queue.put({
                        "target": "all",
                        "data": {
                            "event": "message",
                            "type": "info",
                            "text": f"{current_player['name']} jugó '{word}' por {earned} pts."
                        }
                    })
                    turn_completed = True
                except Exception as e:
                    logger.warning(f"[PROCESO SALA #{room_id} (PID {pid})] Jugada inválida de '{current_player['name']}': {e}")
                    event_queue.put({
                        "target": sender_id,
                        "data": {
                            "event": "action_result",
                            "success": False,
                            "message": f"Error: {e}"
                        }
                    })

            elif action == "change_tiles":
                letters = action_data.get("letters", [])
                try:
                    game.change_tiles(letters)
                    logger.info(f"[PROCESO SALA #{room_id} (PID {pid})] '{current_player['name']}' cambió {len(letters)} fichas: {letters}")
                    event_queue.put({
                        "target": sender_id,
                        "data": {
                            "event": "action_result",
                            "success": True,
                            "message": f"Se cambiaron {len(letters)} fichas con éxito."
                        }
                    })
                    event_queue.put({
                        "target": "all",
                        "data": {
                            "event": "message",
                            "type": "info",
                            "text": f"{current_player['name']} cambió {len(letters)} fichas y pasó su turno."
                        }
                    })
                    turn_completed = True
                except Exception as e:
                    logger.warning(f"[PROCESO SALA #{room_id} (PID {pid})] Error en cambio de fichas de '{current_player['name']}': {e}")
                    event_queue.put({
                        "target": sender_id,
                        "data": {
                            "event": "action_result",
                            "success": False,
                            "message": f"Error: {e}"
                        }
                    })

            elif action == "convert_joker":
                letter = str(action_data.get("letter", "")).upper()
                try:
                    game.convert_joker_to_letter(letter)
                    logger.info(f"[PROCESO SALA #{room_id} (PID {pid})] '{current_player['name']}' convirtió comodín en '{letter}'")
                    event_queue.put({
                        "target": sender_id,
                        "data": {
                            "event": "action_result",
                            "success": True,
                            "message": f"Comodín convertido a '{letter}' con valor 0 pts."
                        }
                    })
                    event_queue.put({
                        "target": sender_id,
                        "data": {
                            "event": "rack_update",
                            "rack": serialize_tiles(current_player_game.tiles)
                        }
                    })
                except Exception as e:
                    logger.warning(f"[PROCESO SALA #{room_id} (PID {pid})] Error comodín de '{current_player['name']}': {e}")
                    event_queue.put({
                        "target": sender_id,
                        "data": {
                            "event": "action_result",
                            "success": False,
                            "message": f"Error: {e}"
                        }
                    })

            elif action == "pass":
                game.pass_turn()
                logger.info(f"[PROCESO SALA #{room_id} (PID {pid})] '{current_player['name']}' pasó su turno. (Pases consecutivos: {game.consecutive_passes})")
                event_queue.put({
                    "target": sender_id,
                    "data": {
                        "event": "action_result",
                        "success": True,
                        "message": "Has pasado el turno."
                    }
                })
                event_queue.put({
                    "target": "all",
                    "data": {
                        "event": "message",
                        "type": "info",
                        "text": f"{current_player['name']} pasó su turno."
                    }
                })
                turn_completed = True

    # Fin de la partida (por reglas oficiales si quedaron 2 o más jugadores)
    if len(active_players) > 1:
        winners_objs = game.compare_score()
        winner_names = [active_players[game.players.index(w)]["name"] for w in winners_objs if game.players.index(w) < len(active_players)]
        final_scores = {active_players[i]["name"]: game.players[i].score for i in range(len(active_players))}

        logger.info(f"[PROCESO SALA #{room_id} (PID {pid})] FIN DEL JUEGO -> Ganador(es): {winner_names} | Puntajes: {final_scores}")

        event_queue.put({
            "target": "all",
            "data": {
                "event": "game_over",
                "winners": winner_names,
                "final_scores": final_scores
            }
        })

    # Señal interna para que el despachador de eventos sepa que el proceso concluyó
    event_queue.put({
        "target": "internal",
        "data": {
            "event": "room_finished"
        }
    })

    logger.info(f"[PROCESO SALA #{room_id} (PID {pid})] Proceso de sala concluyó su ejecución.")
