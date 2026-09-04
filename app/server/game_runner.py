import asyncio
from game.scrabble import ScrabbleGame
from server.protocol import send_json, recv_json, serialize_board, serialize_tiles
from server.lobby import Room
from server.logger import logger

async def run_game_loop(room: Room):
    """Maneja el ciclo de vida completo de la partida en una sala activa."""
    player_count = len(room.players)
    game = ScrabbleGame(player_count)
    
    player_names = [p.name for p in room.players]
    logger.info(f"[PARTIDA #{room.room_id}] Tablero 15x15 y Bolsa ({len(game.bag_tiles.tiles)} fichas) inicializados para {player_names}")

    await room.broadcast({
        "event": "message",
        "type": "info",
        "text": f"¡La partida en Sala #{room.room_id} ha comenzado con {player_count} jugadores: {', '.join(player_names)}!"
    })

    async def handle_disconnection(disconnected_player_conn) -> bool:
        """
        Gestiona la salida de un jugador durante la partida.
        Retorna True si la partida debe finalizar inmediatamente, False si continúa.
        """
        logger.warning(f"[PARTIDA #{room.room_id}] Jugador '{disconnected_player_conn.name}' se desconectó.")
        
        if disconnected_player_conn in room.players:
            disc_idx = room.players.index(disconnected_player_conn)
            room.players.remove(disconnected_player_conn)
            
            # Devolver las fichas del jugador desconectado a la bolsa
            if disc_idx < len(game.players):
                disc_game_player = game.players[disc_idx]
                game.bag_tiles.put(disc_game_player.tiles)
                del game.players[disc_idx]
            
            # Ajustar índice del turno actual si el jugador eliminado estaba antes
            if disc_idx < game.current_player:
                game.current_player -= 1
            elif game.current_player >= len(game.players) and len(game.players) > 0:
                game.current_player = 0

            # Reiniciar pases consecutivos para que no dispare fin por bloqueo anterior
            game.consecutive_passes = 0

        # Evaluar jugadores restantes
        if len(room.players) < 2:
            room.state = "FINISHED"
            if len(room.players) == 1:
                winner_conn = room.players[0]
                winner_score = game.players[0].score if len(game.players) > 0 else 0
                logger.info(f"[PARTIDA #{room.room_id}] Queda 1 jugador. '{winner_conn.name}' gana por abandono.")
                
                await room.broadcast({
                    "event": "message",
                    "type": "warning",
                    "text": f"{disconnected_player_conn.name} se ha desconectado. ¡Victoria por abandono para {winner_conn.name}!"
                })
                await room.broadcast({
                    "event": "game_over",
                    "winners": [winner_conn.name],
                    "final_scores": {winner_conn.name: winner_score}
                })
            else:
                logger.info(f"[PARTIDA #{room.room_id}] Todos los jugadores se desconectaron. Finalizando partida.")
            return True
        else:
            remaining_names = [p.name for p in room.players]
            await room.broadcast({
                "event": "message",
                "type": "warning",
                "text": f"{disconnected_player_conn.name} se ha desconectado de la partida. La partida continúa con: {', '.join(remaining_names)}."
            })
            return False

    async def watch_player_disconnect(player_conn):
        """Monitorea si un jugador que está esperando desconecta su socket o sale."""
        try:
            msg = await recv_json(player_conn.reader)
            if msg is None or msg.get("action") == "quit":
                return player_conn
        except Exception:
            return player_conn
        return None

    while not game.finish_game() and room.state != "FINISHED":
        if len(room.players) < 2:
            if len(room.players) == 1:
                await handle_disconnection(room.players[0])
            break

        # Limpiar jugadores con socket cerrado antes de iniciar el turno
        game_ended = False
        for p in list(room.players):
            if p.writer.is_closing():
                if await handle_disconnection(p):
                    game_ended = True
                    break
        if game_ended or room.state == "FINISHED" or len(room.players) < 2:
            break

        current_idx = game.current_player
        if current_idx >= len(room.players):
            current_idx = current_idx % len(room.players)
            game.current_player = current_idx

        current_player_conn = room.players[current_idx]
        current_player_game = game.players[current_idx]
        
        # 1. Transmitir estado actualizado a cada jugador
        scores_dict = {room.players[i].name: game.players[i].score for i in range(len(room.players))}
        board_data = serialize_board(game.board)
        bag_count = len(game.bag_tiles.tiles)

        logger.info(f"[PARTIDA #{room.room_id}] [TURNO] Jugador #{current_idx} '{current_player_conn.name}' | Puntajes: {scores_dict} | Fichas en bolsa: {bag_count}")

        turn_info_aborted = False
        for i, p_conn in enumerate(list(room.players)):
            sent = await send_json(p_conn.writer, {
                "event": "turn_info",
                "room_id": room.room_id,
                "current_player_idx": current_idx,
                "current_player_name": current_player_conn.name,
                "is_your_turn": (i == current_idx),
                "board": board_data,
                "rack": serialize_tiles(game.players[i].tiles) if i < len(game.players) else [],
                "scores": scores_dict,
                "bag_count": bag_count,
                "timeout": 60
            })
            if not sent:
                if await handle_disconnection(p_conn):
                    turn_info_aborted = True
                    break

        if turn_info_aborted or room.state == "FINISHED" or len(room.players) < 2:
            break

        # 2. Bucle interactivo de turno del jugador actual
        turn_completed = False
        while not turn_completed and not game.finish_game() and len(room.players) >= 2:
            # Tarea principal: Jugada del jugador activo con timeout de 60s
            action_task = asyncio.create_task(recv_json(current_player_conn.reader, timeout=60))

            # Tareas vigía: Monitorear desconexión de jugadores que esperan su turno
            watcher_map = {}
            for p in list(room.players):
                if p != current_player_conn:
                    t = asyncio.create_task(watch_player_disconnect(p))
                    watcher_map[t] = p

            all_tasks = [action_task] + list(watcher_map.keys())
            done, pending = await asyncio.wait(all_tasks, return_when=asyncio.FIRST_COMPLETED)

            # Cancelar tareas pendientes
            for p_task in pending:
                p_task.cancel()
                try:
                    await p_task
                except (asyncio.CancelledError, Exception):
                    pass

            # Caso 1: Un jugador en espera se desconectó
            waiting_disconnect = None
            for d_task in done:
                if d_task in watcher_map:
                    waiting_disconnect = watcher_map[d_task]
                    break

            if waiting_disconnect:
                logger.warning(f"[PARTIDA #{room.room_id}] Jugador en espera '{waiting_disconnect.name}' se desconectó mientras '{current_player_conn.name}' jugaba.")
                game_ended = await handle_disconnection(waiting_disconnect)
                # Salir del turno para reenviar turn_info con la lista y turno actualizados a los que siguen
                turn_completed = True
                break

            # Caso 2: El jugador activo completó su acción o timeout
            action_data = action_task.result() if action_task in done else None

            if action_data is None:
                # Desconexión del jugador actual
                logger.warning(f"[PARTIDA #{room.room_id}] Jugador '{current_player_conn.name}' se desconectó en su turno.")
                await handle_disconnection(current_player_conn)
                turn_completed = True
                break

            elif action_data.get("_error_") == "timeout":
                logger.warning(f"[PARTIDA #{room.room_id}] Timeout de 60s alcanzado para '{current_player_conn.name}'. Pase de turno automático.")
                await room.broadcast({
                    "event": "message",
                    "type": "warning",
                    "text": f"Tiempo agotado para {current_player_conn.name}. Se pasa el turno automáticamente."
                })
                game.pass_turn()
                turn_completed = True
                break

            action = action_data.get("action")
            logger.info(f"[PARTIDA #{room.room_id}] Acción recibida de '{current_player_conn.name}': {action_data}")

            if action == "play_word":
                word = str(action_data.get("word", "")).upper()
                row = int(action_data.get("row", 0))
                col = int(action_data.get("col", 0))
                orientation = str(action_data.get("orientation", "H")).upper()
                
                try:
                    prev_score = current_player_game.score
                    game.play(word, (row, col), orientation, current_player_game.tiles)
                    earned = current_player_game.score - prev_score
                    
                    logger.info(f"[PARTIDA #{room.room_id}] Jugada válida: '{current_player_conn.name}' colocó '{word}' en ({row}, {col}) [{orientation}] -> +{earned} pts (Total: {current_player_game.score} pts)")

                    await send_json(current_player_conn.writer, {
                        "event": "action_result",
                        "success": True,
                        "message": f"¡Palabra '{word}' jugada con éxito! (+{earned} pts)"
                    })
                    await room.broadcast({
                        "event": "message",
                        "type": "info",
                        "text": f"{current_player_conn.name} jugó '{word}' por {earned} pts."
                    })
                    turn_completed = True
                except Exception as e:
                    logger.warning(f"[PARTIDA #{room.room_id}] Jugada inválida de '{current_player_conn.name}' ('{word}'): {e}")
                    await send_json(current_player_conn.writer, {
                        "event": "action_result",
                        "success": False,
                        "message": f"Error: {e}"
                    })

            elif action == "change_tiles":
                letters = action_data.get("letters", [])
                try:
                    game.change_tiles(letters)
                    logger.info(f"[PARTIDA #{room.room_id}] '{current_player_conn.name}' cambió {len(letters)} fichas: {letters}")
                    await send_json(current_player_conn.writer, {
                        "event": "action_result",
                        "success": True,
                        "message": f"Se cambiaron {len(letters)} fichas con éxito."
                    })
                    await room.broadcast({
                        "event": "message",
                        "type": "info",
                        "text": f"{current_player_conn.name} cambió {len(letters)} fichas y pasó su turno."
                    })
                    turn_completed = True
                except Exception as e:
                    logger.warning(f"[PARTIDA #{room.room_id}] Error en cambio de fichas de '{current_player_conn.name}': {e}")
                    await send_json(current_player_conn.writer, {
                        "event": "action_result",
                        "success": False,
                        "message": f"Error: {e}"
                    })

            elif action == "convert_joker":
                letter = str(action_data.get("letter", "")).upper()
                try:
                    game.convert_joker_to_letter(letter)
                    logger.info(f"[PARTIDA #{room.room_id}] '{current_player_conn.name}' convirtió comodín '*' en '{letter}' (0 pts)")
                    await send_json(current_player_conn.writer, {
                        "event": "action_result",
                        "success": True,
                        "message": f"Comodín convertido a '{letter}' con valor 0 pts."
                    })
                    await send_json(current_player_conn.writer, {
                        "event": "rack_update",
                        "rack": serialize_tiles(current_player_game.tiles)
                    })
                except Exception as e:
                    logger.warning(f"[PARTIDA #{room.room_id}] Error comodín de '{current_player_conn.name}': {e}")
                    await send_json(current_player_conn.writer, {
                        "event": "action_result",
                        "success": False,
                        "message": f"Error: {e}"
                    })

            elif action == "pass":
                game.pass_turn()
                logger.info(f"[PARTIDA #{room.room_id}] '{current_player_conn.name}' pasó su turno. (Pases consecutivos: {game.consecutive_passes})")
                await send_json(current_player_conn.writer, {
                    "event": "action_result",
                    "success": True,
                    "message": "Has pasado el turno."
                })
                await room.broadcast({
                    "event": "message",
                    "type": "info",
                    "text": f"{current_player_conn.name} pasó su turno."
                })
                turn_completed = True

            elif action == "quit":
                logger.warning(f"[PARTIDA #{room.room_id}] '{current_player_conn.name}' abandonó la partida voluntariamente.")
                await handle_disconnection(current_player_conn)
                turn_completed = True
                break

    # Fin de la partida (si terminó normalmente por reglas de Scrabble)
    if room.state != "FINISHED":
        room.state = "FINISHED"
        if len(room.players) > 1:
            winners_objs = game.compare_score()
            winner_names = [room.players[game.players.index(w)].name for w in winners_objs if game.players.index(w) < len(room.players)]
            final_scores = {room.players[i].name: game.players[i].score for i in range(len(room.players))}

            logger.info(f"[PARTIDA #{room.room_id}] FIN DEL JUEGO -> Ganador(es): {winner_names} | Puntajes finales: {final_scores}")

            await room.broadcast({
                "event": "game_over",
                "winners": winner_names,
                "final_scores": final_scores
            })
