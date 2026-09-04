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
