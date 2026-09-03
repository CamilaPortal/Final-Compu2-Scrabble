import argparse
import asyncio
import json
import os
import sys
import termios

try:
    from client.ui import render_board, render_player_panel, render_menu, console
except (ImportError, ModuleNotFoundError):
    from ui import render_board, render_player_panel, render_menu, console  # type: ignore

from rich.panel import Panel
from rich import box

async def send_json(writer, data: dict):
    """Envía un diccionario serializado en JSON terminado en \n."""
    try:
        if writer is None or writer.is_closing():
            return
        raw_msg = (json.dumps(data) + "\n").encode("utf-8")
        writer.write(raw_msg)
        await writer.drain()
    except (ConnectionResetError, BrokenPipeError, OSError, asyncio.CancelledError):
        pass

async def recv_json(reader, timeout: float | None = None) -> dict | None:
    """Lee una línea del socket y la deserializa como JSON."""
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

class StdinReader:
    """Lector asíncrono de terminal no bloqueante basado en el selector de asyncio."""
    def __init__(self):
        self.future = None
        self._registered = False

    def _on_data(self):
        line = sys.stdin.readline()
        if self.future and not self.future.done():
            self.future.set_result(line.strip())

    async def readline(self, prompt: str = "") -> str:
        try:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            pass
        if prompt:
            sys.stdout.write(prompt)
            sys.stdout.flush()

        loop = asyncio.get_running_loop()
        self.future = loop.create_future()

        if not self._registered:
            loop.add_reader(sys.stdin.fileno(), self._on_data)
            self._registered = True

        try:
            return await self.future
        except asyncio.CancelledError:
            raise
        finally:
            self.future = None

    def close(self):
        if self._registered:
            try:
                loop = asyncio.get_running_loop()
                loop.remove_reader(sys.stdin.fileno())
            except Exception:
                pass
            self._registered = False

class ScrabbleClient:
    def __init__(self, name: str, host: str = "127.0.0.1", port: int = 5000):
        self.name = name
        self.host = host
        self.port = port
        self.player_id = 0
        self.room_id = 1
        self.my_tiles = []
        self.my_score = 0
        self.is_my_turn = False
        self.turn_action_task = None
        self.stdin_reader = StdinReader()

    async def run(self):
        console.print(f"[bold cyan]Conectando al servidor Scrabble en {self.host}:{self.port}...[/bold cyan]")
        try:
            reader, writer = await asyncio.open_connection(self.host, self.port)
        except Exception as e:
            console.print(f"[bold red]Error al conectar con el servidor: {e}[/bold red]")
            return

        # 1. Enviar handshake de bienvenida
        await send_json(writer, {"action": "join", "name": self.name})

        # 2. Bucle principal de eventos de red
        try:
            while True:
                msg = await recv_json(reader)
                if msg is None:
                    console.print("[bold red]Conexión cerrada por el servidor.[/bold red]")
                    break

                event = msg.get("event")

                if event == "welcome":
                    self.player_id = msg.get("player_id", 0)
                    self.room_id = msg.get("room_id", 1)
                    console.print(Panel(
                        f"[bold green]¡Bienvenido, {self.name}![/bold green]\n"
                        f"Asignado a la [bold yellow]Sala #{self.room_id}[/bold yellow] (Jugador #{self.player_id})",
                        box=box.SQUARE,
                        title="CONEXION EXITOSA"
                    ))

                elif event == "lobby_update":
                    players = msg.get("players", [])
                    p_count = msg.get("player_count", len(players))
                    state = msg.get("state", "")
                    console.print(f"[cyan]Sala #{self.room_id} [{state}]: {p_count}/4 jugadores conectados -> {players}[/cyan]")

                elif event == "lobby_countdown":
                    sec = msg.get("remaining_seconds", 30)
                    console.print(f"[bold yellow] La partida comenzará en {sec} segundos...[/bold yellow]")

                elif event == "message":
                    m_type = msg.get("type", "info")
                    text = msg.get("text", "")
                    if m_type == "error":
                        console.print(f"[bold red]{text}[/bold red]")
                    elif m_type == "warning":
                        console.print(f"[bold yellow]{text}[/bold yellow]")
                    else:
                        console.print(f"[bold green]{text}[/bold green]")

                elif event == "action_result":
                    success = msg.get("success", True)
                    text = msg.get("message", "")
                    if success:
                        console.print(f"[bold green]{text}[/bold green]")
                    else:
                        console.print(f"[bold red]{text}[/bold red]")
                        if self.is_my_turn:
                            console.print("[yellow] Podés intentar otra palabra, cambiar fichas o pasar.[/yellow]")
                            self.trigger_turn_prompt(writer)

                elif event == "rack_update":
                    self.my_tiles = msg.get("rack", [])

                elif event == "turn_info":
                    board_data = msg.get("board", [])
                    self.my_tiles = msg.get("rack", [])
                    scores = msg.get("scores", {})
                    self.my_score = scores.get(self.name, 0)
                    bag_count = msg.get("bag_count", 0)
                    current_name = msg.get("current_player_name", "")
                    self.is_my_turn = msg.get("is_your_turn", False)

                    render_board(board_data)
                    render_player_panel(self.name, self.player_id, self.my_tiles, self.my_score, bag_count)

                    if self.is_my_turn:
                        console.print("[bold green]¡ES TU TURNO! (Tenés 60 segundos)[/bold green]")
                        self.trigger_turn_prompt(writer)
                    else:
                        self.cancel_current_prompt()
                        console.print(f"[dim] Esperando la jugada de {current_name}...[/dim]")

                elif event == "game_over":
                    self.cancel_current_prompt()
                    winners = msg.get("winners", [])
                    final_scores = msg.get("final_scores", {})
                    
                    scores_str = "\n".join([f"  • {p}: {s} pts" for p, s in final_scores.items()])
                    winner_str = ", ".join(winners)
                    console.print(Panel(
                        f"[bold yellow] GANADOR(ES): {winner_str}[/bold yellow]\n\n"
                        f"[bold white]Puntajes Finales:[/bold white]\n{scores_str}",
                        box=box.SQUARE,
                        title="PARTIDA FINALIZADA"
                    ))
                    break

        except (ConnectionResetError, asyncio.CancelledError):
            console.print("[red]Conexión finalizada.[/red]")
        finally:
            self.cancel_current_prompt()
            self.stdin_reader.close()
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def cancel_current_prompt(self):
        if self.turn_action_task and not self.turn_action_task.done():
            self.turn_action_task.cancel()

    def trigger_turn_prompt(self, writer):
        self.cancel_current_prompt()
        self.turn_action_task = asyncio.create_task(self.prompt_turn_action(writer))

    async def prompt_turn_action(self, writer):
        """Pide al usuario su opción y envía el comando correspondiente."""
        try:
            render_menu()
            choice = await self.stdin_reader.readline("\n Seleccione una opción (1-5): ")
            
            if not self.is_my_turn:
                return

            if choice == "1":
                try:
                    word = (await self.stdin_reader.readline("Ingrese la palabra: ")).upper()
                    row = int(await self.stdin_reader.readline("Ingrese la fila (0-14): "))
                    col = int(await self.stdin_reader.readline("Ingrese la columna (0-14): "))
                    orient = (await self.stdin_reader.readline("Ingrese orientación (H/V): ")).upper()
                    if orient not in ("H", "V"):
                        console.print("[red]Error: La orientación debe ser 'H' (Horizontal) o 'V' (Vertical).[/red]")
                        if self.is_my_turn:
                            self.trigger_turn_prompt(writer)
                        return
                    await send_json(writer, {
                        "action": "play_word",
                        "word": word,
                        "row": row,
                        "col": col,
                        "orientation": orient
                    })
                except ValueError:
                    console.print("[red]Error: Fila y columna deben ser números enteros.[/red]")
                    if self.is_my_turn:
                        self.trigger_turn_prompt(writer)

            elif choice == "2":
                letters_raw = await self.stdin_reader.readline("Ingrese las letras a cambiar separadas por espacio (o 'todas'): ")
                if letters_raw.lower() == "todas":
                    letters = [t.get("letter") for t in self.my_tiles]
                else:
                    letters = [c.upper() for c in letters_raw.split() if c.strip()]
                await send_json(writer, {"action": "change_tiles", "letters": letters})

            elif choice == "3":
                if not any(t.get("letter") == "*" for t in self.my_tiles):
                    console.print("[red]Error: No tienes ningún comodín (*) en tu atril.[/red]")
                    if self.is_my_turn:
                        self.trigger_turn_prompt(writer)
                    return
                letter = (await self.stdin_reader.readline("Ingrese la letra por la que desea cambiar el comodín: ")).upper()
                await send_json(writer, {"action": "convert_joker", "letter": letter})

            elif choice == "4":
                await send_json(writer, {"action": "pass"})

            elif choice == "5":
                await send_json(writer, {"action": "quit"})
                console.print("\n[bold yellow]¡Gracias por jugar! Saliendo...[/bold yellow]")
                os._exit(0)

            else:
                console.print("[red]Opción inválida. Intente de nuevo.[/red]")
                if self.is_my_turn:
                    self.trigger_turn_prompt(writer)

        except asyncio.CancelledError:
            pass

def main():
    parser = argparse.ArgumentParser(description="Cliente de Scrabble Multijugador")
    parser.add_argument("--name", "-n", default="Jugador", help="Nombre o alias del jugador")
    parser.add_argument("--host", "-H", default="127.0.0.1", help="IP del servidor (default: 127.0.0.1)")
    parser.add_argument("--port", "-p", type=int, default=5000, help="Puerto del servidor (default: 5000)")
    args = parser.parse_args()

    client = ScrabbleClient(name=args.name, host=args.host, port=args.port)
    try:
        asyncio.run(client.run())
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == "__main__":
    main()
