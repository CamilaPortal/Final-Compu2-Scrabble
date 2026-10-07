import os
import time
import queue
import multiprocessing
from game.scrabble import ScrabbleGame
from server.protocol import serialize_board, serialize_tiles
from server.logger import logger


class RoomGameSession:
    """
    Gestiona el ciclo de vida completo de una partida de Scrabble en un proceso hijo aislado.
    
    - Control del motor de juego ScrabbleGame.
    - Comunicación bidireccional IPC mediante colas multiprocessing.Queue.
    - Temporizador estricto por turno (60 segundos).
    - Despacho y validación de acciones (play_word, change_tiles, convert_joker, pass).
    - Gestión de desconexiones y finalización de partida.
    """

    def __init__(self, room_id: int, initial_players: list, action_queue: multiprocessing.Queue, event_queue: multiprocessing.Queue):
        self.room_id = room_id
        self.action_queue = action_queue
        self.event_queue = event_queue
        self.pid = os.getpid()
        self.active_players = list(initial_players)
        self.player_count = len(self.active_players)
        self.player_names = [p["name"] for p in self.active_players]
        self.turn_timeout = 60.0

        logger.info(f"[PROCESO SALA #{self.room_id} (PID {self.pid})] Proceso de sala iniciado con {self.player_count} jugadores: {self.player_names}")
        
        # Inicializar motor de juego Scrabble
        self.game = ScrabbleGame(self.player_count)
        logger.info(f"[PROCESO SALA #{self.room_id} (PID {self.pid})] Tablero y bolsa ({len(self.game.bag_tiles.tiles)} fichas) inicializados")

    def send_to(self, player_id: int, data: dict):
        """Envía un mensaje IPC a un jugador específico a través del servidor principal."""
        self.event_queue.put({"target": player_id, "data": data})

    def broadcast(self, data: dict):
        """Difunde un mensaje IPC a todos los jugadores de la sala."""
        self.event_queue.put({"target": "all", "data": data})

    def broadcast_message(self, text: str, msg_type: str = "info"):
        """Envía un mensaje de texto informativo o de advertencia a todos los jugadores."""
        self.broadcast({"event": "message", "type": msg_type, "text": text})

    def send_action_result(self, player_id: int, success: bool, message: str):
        """Notifica el resultado de una acción solicitada por un jugador."""
        self.send_to(player_id, {
            "event": "action_result",
            "success": success,
            "message": message
        })

    def handle_disconnect(self, sender_id: int) -> bool:
        """
        Gestiona la desconexión o abandono de un jugador.
        Retorna True si la partida finaliza (por falta de jugadores mínimos).
        """
        disc_player = next((p for p in self.active_players if p["id"] == sender_id), None)
        if not disc_player:
            return False

        disc_idx = self.active_players.index(disc_player)
        disc_name = disc_player["name"]
        self.active_players.remove(disc_player)
        logger.warning(f"[PROCESO SALA #{self.room_id} (PID {self.pid})] Jugador '{disc_name}' desconectado de la partida.")

        # Devolver fichas a la bolsa y quitar jugador del motor ScrabbleGame
        if disc_idx < len(self.game.players):
            disc_game_player = self.game.players[disc_idx]
            self.game.bag_tiles.put(disc_game_player.tiles)
            del self.game.players[disc_idx]

        # Ajustar índice de turno actual
        if disc_idx < self.game.current_player:
            self.game.current_player -= 1
        elif self.game.current_player >= len(self.game.players) and len(self.game.players) > 0:
            self.game.current_player = 0

        # Reiniciar contador de pases consecutivos
        self.game.consecutive_passes = 0

        # Evaluar si la partida debe terminar
        if len(self.active_players) < 2:
            if len(self.active_players) == 1:
                winner = self.active_players[0]
                winner_score = self.game.players[0].score if len(self.game.players) > 0 else 0
                logger.info(f"[PROCESO SALA #{self.room_id} (PID {self.pid})] Queda 1 jugador. '{winner['name']}' gana por abandono.")
                self.broadcast_message(
                    f"{disc_name} se ha desconectado. ¡Victoria por abandono para {winner['name']}!",
                    msg_type="warning"
                )
                self.broadcast({
                    "event": "game_over",
                    "winners": [winner["name"]],
                    "final_scores": {winner["name"]: winner_score}
                })
            else:
                logger.info(f"[PROCESO SALA #{self.room_id} (PID {self.pid})] Todos los jugadores se desconectaron.")
            return True
        else:
            remaining_names = [p["name"] for p in self.active_players]
            self.broadcast_message(
                f"{disc_name} se ha desconectado de la partida. La partida continúa con: {', '.join(remaining_names)}.",
                msg_type="warning"
            )
            return False

    def broadcast_turn_info(self, current_player: dict, current_idx: int):
        """Transmite el estado actualizado de la partida (tablero, atril, puntajes, etc.) a cada jugador."""
        scores_dict = {self.active_players[i]["name"]: self.game.players[i].score for i in range(len(self.active_players))}
        board_data = serialize_board(self.game.board)
        bag_count = len(self.game.bag_tiles.tiles)

        logger.info(
            f"[PROCESO SALA #{self.room_id} (PID {self.pid})] [TURNO] Jugador #{current_idx} '{current_player['name']}' "
            f"| Puntajes: {scores_dict} | Fichas en bolsa: {bag_count}"
        )

        for i, p in enumerate(self.active_players):
            self.send_to(p["id"], {
                "event": "turn_info",
                "room_id": self.room_id,
                "current_player_idx": current_idx,
                "current_player_name": current_player["name"],
                "is_your_turn": (i == current_idx),
                "board": board_data,
                "rack": serialize_tiles(self.game.players[i].tiles) if i < len(self.game.players) else [],
                "scores": scores_dict,
                "bag_count": bag_count,
                "timeout": int(self.turn_timeout)
            })

    def _handle_play_word(self, current_player: dict, current_player_game, action_data: dict) -> bool:
        """Procesa el intento de colocar una palabra en el tablero."""
        sender_id = current_player["id"]
        word = str(action_data.get("word", "")).upper()
        row = int(action_data.get("row", 0))
        col = int(action_data.get("col", 0))
        orientation = str(action_data.get("orientation", "H")).upper()

        try:
            prev_score = current_player_game.score
            self.game.play(word, (row, col), orientation, current_player_game.tiles)
            earned = current_player_game.score - prev_score

            logger.info(
                f"[PROCESO SALA #{self.room_id} (PID {self.pid})] Jugada válida: "
                f"'{current_player['name']}' colocó '{word}' en ({row}, {col}) [{orientation}] -> +{earned} pts"
            )

            self.send_action_result(sender_id, True, f"¡Palabra '{word}' jugada con éxito! (+{earned} pts)")
            self.broadcast_message(f"{current_player['name']} jugó '{word}' por {earned} pts.", msg_type="info")
            return True
        except Exception as e:
            logger.warning(f"[PROCESO SALA #{self.room_id} (PID {self.pid})] Jugada inválida de '{current_player['name']}': {e}")
            self.send_action_result(sender_id, False, f"Error: {e}")
            return False

    def _handle_change_tiles(self, current_player: dict, action_data: dict) -> bool:
        """Procesa el intercambio de fichas de un jugador con la bolsa."""
        sender_id = current_player["id"]
        letters = action_data.get("letters", [])
        try:
            self.game.change_tiles(letters)
            logger.info(f"[PROCESO SALA #{self.room_id} (PID {self.pid})] '{current_player['name']}' cambió {len(letters)} fichas: {letters}")
            self.send_action_result(sender_id, True, f"Se cambiaron {len(letters)} fichas con éxito.")
            self.broadcast_message(f"{current_player['name']} cambió {len(letters)} fichas y pasó su turno.", msg_type="info")
            return True
        except Exception as e:
            logger.warning(f"[PROCESO SALA #{self.room_id} (PID {self.pid})] Error en cambio de fichas de '{current_player['name']}': {e}")
            self.send_action_result(sender_id, False, f"Error: {e}")
            return False

    def _handle_convert_joker(self, current_player: dict, current_player_game, action_data: dict, remaining_turn_sec: int):
        """Convierte una ficha comodín ('?') en una letra específica del abecedario."""
        sender_id = current_player["id"]
        letter = str(action_data.get("letter", "")).strip().upper()
        if len(letter) != 1 or not letter.isalpha():
            self.send_action_result(sender_id, False, "Error: Debe ingresar una única letra del alfabeto para el comodín.")
            return

        try:
            self.game.convert_joker_to_letter(letter)
            logger.info(f"[PROCESO SALA #{self.room_id} (PID {self.pid})] '{current_player['name']}' convirtió comodín en '{letter}'")
            self.send_action_result(sender_id, True, f"Comodín convertido a '{letter}' con valor 0 pts.")

            # Reenviar turn_info con el atril actualizado y el tiempo restante
            scores = {self.active_players[i]["name"]: self.game.players[i].score for i in range(len(self.active_players))}
            self.send_to(sender_id, {
                "event": "turn_info",
                "board": serialize_board(self.game.board),
                "rack": serialize_tiles(current_player_game.tiles),
                "scores": scores,
                "bag_count": len(self.game.bag_tiles.tiles),
                "current_player_name": current_player["name"],
                "current_player_id": current_player["id"],
                "is_your_turn": True,
                "remaining_seconds": remaining_turn_sec
            })
        except Exception as e:
            logger.warning(f"[PROCESO SALA #{self.room_id} (PID {self.pid})] Error comodín de '{current_player['name']}': {e}")
            self.send_action_result(sender_id, False, f"Error: {e}")

    def _handle_pass(self, current_player: dict) -> bool:
        """Pasa voluntariamente el turno del jugador actual."""
        sender_id = current_player["id"]
        self.game.pass_turn()
        logger.info(f"[PROCESO SALA #{self.room_id} (PID {self.pid})] '{current_player['name']}' pasó su turno. (Pases consecutivos: {self.game.consecutive_passes})")
        self.send_action_result(sender_id, True, "Has pasado el turno.")
        self.broadcast_message(f"{current_player['name']} pasó su turno.", msg_type="info")
        return True

    def run_turn(self, current_player: dict, current_player_game) -> bool:
        """
        Ejecuta el ciclo de interacción de un turno con temporizador de 60 segundos.
        Retorna True si la partida debe terminar inmediatamente (por desconexión).
        """
        turn_completed = False
        turn_start_time = time.time()

        while not turn_completed and not self.game.finish_game() and len(self.active_players) >= 2:
            remaining_time = max(0.1, self.turn_timeout - (time.time() - turn_start_time))
            try:
                msg = self.action_queue.get(timeout=remaining_time)
            except queue.Empty:
                logger.warning(
                    f"[PROCESO SALA #{self.room_id} (PID {self.pid})] Timeout de {int(self.turn_timeout)}s "
                    f"alcanzado para '{current_player['name']}'. Pase de turno automático."
                )
                self.broadcast_message(
                    f"Tiempo agotado para {current_player['name']}. Se pasa el turno automáticamente.",
                    msg_type="warning"
                )
                self.game.pass_turn()
                return False

            sender_id = msg.get("player_id")
            action_data = msg.get("action_data", {})
            action = action_data.get("action")

            # Manejo de desconexión o abandono
            if action in ("disconnect", "quit"):
                game_finished = self.handle_disconnect(sender_id)
                return game_finished

            # Solo procesar acciones del jugador en turno
            if sender_id != current_player["id"]:
                continue

            if action == "play_word":
                turn_completed = self._handle_play_word(current_player, current_player_game, action_data)

            elif action == "change_tiles":
                turn_completed = self._handle_change_tiles(current_player, action_data)

            elif action == "convert_joker":
                rem_sec = max(1, int(self.turn_timeout - (time.time() - turn_start_time)))
                self._handle_convert_joker(current_player, current_player_game, action_data, rem_sec)

            elif action == "pass":
                turn_completed = self._handle_pass(current_player)

        return False

    def finalize_game(self):
        """Gestiona el fin de la partida y notifica ganadores."""
        if len(self.active_players) > 1:
            winners_objs = self.game.compare_score()
            winner_names = [
                self.active_players[self.game.players.index(w)]["name"]
                for w in winners_objs
                if self.game.players.index(w) < len(self.active_players)
            ]
            final_scores = {
                self.active_players[i]["name"]: self.game.players[i].score
                for i in range(len(self.active_players))
            }

            logger.info(
                f"[PROCESO SALA #{self.room_id} (PID {self.pid})] FIN DEL JUEGO "
                f"-> Ganador(es): {winner_names} | Puntajes: {final_scores}"
            )

            self.broadcast({
                "event": "game_over",
                "winners": winner_names,
                "final_scores": final_scores
            })

        self.event_queue.put({
            "target": "internal",
            "data": {
                "event": "room_finished"
            }
        })

        logger.info(f"[PROCESO SALA #{self.room_id} (PID {self.pid})] Proceso de sala concluyó su ejecución.")


    def run(self):
        """Bucle principal del proceso de sala."""
        self.broadcast_message(
            f"Partida iniciada en Sala #{self.room_id} (PID {self.pid}) con "
            f"{self.player_count} jugadores: {', '.join(self.player_names)}"
        )

        while not self.game.finish_game() and len(self.active_players) >= 2:
            current_idx = self.game.current_player
            if current_idx >= len(self.active_players):
                current_idx = current_idx % len(self.active_players)
                self.game.current_player = current_idx

            current_player = self.active_players[current_idx]
            current_player_game = self.game.players[current_idx]

            self.broadcast_turn_info(current_player, current_idx)

            game_ended = self.run_turn(current_player, current_player_game)
            if game_ended:
                break

        self.finalize_game()


def run_room_process(room_id: int, initial_players: list, action_queue: multiprocessing.Queue, event_queue: multiprocessing.Queue):
    """
    Función de entrada para el proceso hijo independiente de una sala de Scrabble.
    Instancia y ejecuta la sesión de juego delegando el ciclo de vida en RoomGameSession.
    """
    session = RoomGameSession(room_id, initial_players, action_queue, event_queue)
    session.run()
