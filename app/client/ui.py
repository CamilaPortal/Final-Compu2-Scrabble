from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()

def render_board(board):
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
            cell = board.grid[r][c]
            if cell.letter is not None:
                row.append(f"[bold black on white] {cell.letter.letter} [/]")
            else:
                if r == 7 and c == 7:
                    row.append("[bold yellow] * [/]")
                elif cell.multiplier_type == "word" and cell.multiplier == 3:
                    row.append("[bold red]3P [/]")
                elif cell.multiplier_type == "word" and cell.multiplier == 2:
                    row.append("[bold magenta]2P [/]")
                elif cell.multiplier_type == "letter" and cell.multiplier == 3:
                    row.append("[bold blue]3L [/]")
                elif cell.multiplier_type == "letter" and cell.multiplier == 2:
                    row.append("[bold cyan]2L [/]")
                else:
                    row.append("[dim] · [/]")
        table.add_row(*row)

    console.print(table)

def render_player_panel(player_name, player_index, player, bag_count):
    rack_list = [f"[bold black on white] {t.letter}:{t.value} [/]" for t in player.tiles]
    rack_str = "  ".join(rack_list) if rack_list else "(Atril vacio)"
    
    content = (
        f"Jugador: {player_name}  |  Puntaje: {player.score} pts  |  Fichas restantes en bolsa: {bag_count}\n\n"
        f"Atril actual:  {rack_str}"
    )
    console.print(Panel(content, title="INFORMACION DEL JUGADOR", box=box.SQUARE, title_align="left"))

def render_menu():
    menu_table = Table(box=box.SQUARE, show_header=False, padding=(0, 2))
    menu_table.add_column("Opcion", style="bold yellow", width=6)
    menu_table.add_column("Accion", style="white")
    menu_table.add_row("[1]", "Jugar palabra (fila, columna, orientacion y palabra)")
    menu_table.add_row("[2]", "Cambiar fichas (seleccionar letras a cambiar)")
    menu_table.add_row("[3]", "Convertir comodin (asignar letra al comodin *)")
    menu_table.add_row("[4]", "Pasar turno")
    menu_table.add_row("[5]", "Terminar juego")
    console.print(menu_table)
