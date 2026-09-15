from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()

def render_board(board_data: list):
    """Renderiza el tablero 15x15 desde los datos JSON recibidos del servidor."""
    if not board_data:
        return

    table = Table(
        box=box.SQUARE,
        show_lines=True,
        padding=(0, 0),
        title="TABLERO DE SCRABBLE (15x15)",
        title_style="bold white",
        header_style="bold cyan",
        expand=False
    )
    table.add_column("F\\C", no_wrap=True)
    for c in range(15):
        if c < 10:
            table.add_column(f" {c} ", no_wrap=True)
        else:
            table.add_column(f"{c} ", no_wrap=True)

    for r in range(15):
        if r < 10:
            row = [f" {r} "]
        else:
            row = [f"{r} "]
            
        for c in range(15):
            cell = board_data[r][c]
            letter_info = cell.get("letter")
            letter_char = letter_info.get("letter") if letter_info else None
            m_type = cell.get("multiplier_type")
            m_val = cell.get("multiplier", 1)

            if letter_char is not None:
                row.append(f"[bold black on white] {letter_char} [/]")
            else:
                if r == 7 and c == 7:
                    row.append("[bold yellow] * [/]")
                elif m_type == "word" and m_val == 3:
                    row.append("[bold red]3P [/]")
                elif m_type == "word" and m_val == 2:
                    row.append("[bold magenta]2P [/]")
                elif m_type == "letter" and m_val == 3:
                    row.append("[bold blue]3L [/]")
                elif m_type == "letter" and m_val == 2:
                    row.append("[bold cyan]2L [/]")
                else:
                    row.append("[dim] · [/]")
        table.add_row(*row)

    console.print(table)

def render_player_panel(player_name: str, player_index: int, tiles_data: list, score: int, bag_count: int):
    """Renderiza el panel de información del jugador desde los datos JSON."""
    rack_list = [f"[bold black on white] {t.get('letter')}:{t.get('value')} [/]" for t in (tiles_data or [])]
    rack_str = "  ".join(rack_list) if rack_list else "(Atril vacio)"
    
    content = (
        f"Jugador: {player_name}  |  Puntaje: {score} pts  |  Fichas restantes en bolsa: {bag_count}\n\n"
        f"Atril actual:  {rack_str}"
    )
    console.print(Panel(content, title="INFORMACION DEL JUGADOR", box=box.SQUARE, title_align="left"))

def render_menu():
    """Renderiza el menú de opciones numéricas."""
    menu_table = Table(box=box.SQUARE, show_header=False, padding=(0, 2))
    menu_table.add_column("Opcion", style="bold yellow", width=6)
    menu_table.add_column("Accion", style="white")
    menu_table.add_row("[1]", "Jugar palabra (fila, columna, orientacion y palabra)")
    menu_table.add_row("[2]", "Cambiar fichas (seleccionar letras a cambiar)")
    menu_table.add_row("[3]", "Convertir comodin (asignar letra al comodin *)")
    menu_table.add_row("[4]", "Pasar turno")
    menu_table.add_row("[5]", "Terminar juego")
    console.print(menu_table)


def render_welcome_menu():
    """Menú interactivo de bienvenida y autenticación."""
    menu_table = Table(
        box=box.SQUARE,
        title="SCRABBLE EN RED - ACCESO",
        title_style="bold cyan",
        show_header=False,
        padding=(0, 2),
    )
    menu_table.add_column("Opcion", style="bold yellow", width=6)
    menu_table.add_column("Accion", style="white")
    menu_table.add_row("[1]", "Iniciar sesión (Login)")
    menu_table.add_row("[2]", "Registrarse (Crear nueva cuenta)")
    menu_table.add_row("[3]", "Ver ranking histórico")
    menu_table.add_row("[4]", "Jugar como invitado")
    menu_table.add_row("[5]", "Salir")
    console.print(menu_table)


def render_ranking(ranking_data: list):
    """Tabla de posiciones histórica en la terminal."""
    if not ranking_data:
        console.print(Panel("[yellow]Aún no hay registros en el ranking histórico.[/yellow]", box=box.SQUARE))
        return

    table = Table(
        box=box.SQUARE,
        title="RANKING HISTORICO DE JUGADORES",
        title_style="bold yellow",
        header_style="bold cyan",
        padding=(0, 2),
    )
    table.add_column("Pos.", justify="center", style="bold yellow", width=6)
    table.add_column("Jugador", style="bold white", width=16)
    table.add_column("Victorias", justify="center", style="bold green", width=11)
    table.add_column("Partidas", justify="center", style="white", width=10)
    table.add_column("Efectividad", justify="center", style="magenta", width=13)
    table.add_column("Mejor Puntaje", justify="center", style="bold cyan", width=15)
    table.add_column("Promedio", justify="center", style="blue", width=11)

    for item in ranking_data:
        rank = item.get("rank", "-")
        user = item.get("username", "Anon")
        wins = str(item.get("wins", 0))
        games = str(item.get("games_played", 0))
        rate = f"{item.get('win_rate', 0.0)}%"
        best = f"{item.get('best_score', 0)} pts"
        avg = f"{item.get('avg_score', 0.0)} pts"
        table.add_row(str(rank), user, wins, games, rate, best, avg)

    console.print(table)
