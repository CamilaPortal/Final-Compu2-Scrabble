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

    while not game.finish_game():
        if len(room.players) == 0:
            logger.info(f"[PARTIDA #{room.room_id}] Todos los jugadores se desconectaron. Finalizando partida.")
            break

        current_idx = game.current_player
        if current_idx >= len(room.players):
            current_idx = current_idx % len(room.players)

        current_player_conn = room.players[current_idx]
        current_player_game = game.players[current_idx]
        
        # 1. Transmitir estado actualizado a cada jugador
        scores_dict = {room.players[i].name: game.players[i].score for i in range(len(room.players))}
        board_data = serialize_board(game.board)
        bag_count = len(game.bag_tiles.tiles)

        logger.info(f"[PARTIDA #{room.room_id}] [TURNO] Jugador #{current_idx} '{current_player_conn.name}' | Puntajes: {scores_dict} | Fichas en bolsa: {bag_count}")

        for i, p_conn in enumerate(list(room.players)):
            await send_json(p_conn.writer, {
                "event": "turn_info",
                "room_id": room.room_id,
                "current_player_idx": current_idx,
                "current_player_name": current_player_conn.name,
                "is_your_turn": (i == current_idx),
                "board": board_data,
                "rack": serialize_tiles(game.players[i].tiles),
                "scores": scores_dict,
                "bag_count": bag_count,
                "timeout": 60
            })

        # 2. Bucle interactivo de turno del jugador actual
        turn_completed = False
        while not turn_completed and not game.finish_game():
            action_data = await recv_json(current_player_conn.reader, timeout=60)
            
            if action_data is None:
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
                logger.warning(f"[PARTIDA #{room.room_id}] '{current_player_conn.name}' abandonó la partida.")
                await room.broadcast({
                    "event": "message",
                    "type": "warning",
                    "text": f"{current_player_conn.name} abandonó la partida."
                })
                game.pass_turn()
                turn_completed = True
                break

    # Fin de la partida
    room.state = "FINISHED"
    if len(room.players) > 0:
        winners_objs = game.compare_score()
        winner_names = [room.players[game.players.index(w)].name for w in winners_objs if game.players.index(w) < len(room.players)]
        final_scores = {room.players[i].name: game.players[i].score for i in range(len(room.players))}

        logger.info(f"[PARTIDA #{room.room_id}] FIN DEL JUEGO -> Ganador(es): {winner_names} | Puntajes finales: {final_scores}")

        await room.broadcast({
            "event": "game_over",
            "winners": winner_names,
            "final_scores": final_scores
        })
