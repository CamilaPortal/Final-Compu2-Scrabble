from game.scrabble import ScrabbleGame, NoJoker
from game.board import Board, SoloVoHParaLaOrientacion
from game.cell import Cell
from game.player import Player
from client.ui import render_board, render_player_panel, render_menu, console

class Main:
    def get_player_count(self):
        while True:
            try:
                player_count= int(input("cantidad de jugadores (2-4): "))
                if player_count >= 2 and player_count <= 4:
                    break
            except Exception as e:
                print("Ingrese un numero entre 2 y 4")

        return player_count

    def show_board(self, board):
        render_board(board)

    def show_player(self, player_index, player, bag_count=0):
        render_player_panel(f"Jugador #{player_index}", player_index, player, bag_count)

    def get_location(self):
        while True:
            try:
                location_x = int(input("Ingrese la posición de la fila: "))
                location_y = int(input("Ingrese la posición de la columna: "))
                location = location_x,location_y
                return location
            except Exception as e:
                print("Error: Ingrese numeros validos para la posicion.")

    def get_word(self):
        while True:
            try:
                word = input("Ingrese la palabra: ").upper()
                if word.isalpha():
                    return word
            except Exception as e:
                print("Error: Ingresa una palabra valida")
    
    def get_orientation(self):
        while True:
            try:
                orientation = input("Ingrese la orientación (H para horizontal, V para vertical): ").upper()
                if orientation == 'H' or orientation == 'V':
                    return orientation
                else:
                    raise SoloVoHParaLaOrientacion("Orientación invalida. Por favor, ingrese H para horizontal o V para vertical.")
            except Exception as e:
                print(f"Error: {e}")

    def play_word(self, game):
        try:
            word = self.get_word()
            location = self.get_location()
            orientation = self.get_orientation()
            rack = game.get_player_tiles()
            game.play(word, location, orientation, rack)
        except Exception as e:
            print(f'Error: {e}')

    def joker(self, game):
        current_player = game.get_current_player()
        if not any(t.letter == '*' for t in current_player.tiles):
            print("\nError: No tienes ningún comodín (*) en tu atril.")
            return
        
        letter = input("Ingrese la letra por la que desea cambiar el comodín: ").strip().upper()
        if not letter or not letter.isalpha() or len(letter) != 1:
            print("Error: Ingrese una sola letra válida (A-Z).")
            return
        
        try:
            game.convert_joker_to_letter(letter)
            print(f"Comodín (*) convertido a '{letter}' con valor 0 pts con éxito.")
        except Exception as e:
            print(f"Error: {e}")

    def change(self, game):
        if len(game.bag_tiles.tiles) < 7:
            print("Error: No se pueden cambiar fichas. Deben quedar al menos 7 fichas en la bolsa.")
            return
        
        current_player = game.get_current_player()
        print(f"Tus fichas disponibles: {[t.letter for t in current_player.tiles]}")
        raw_input = input("Ingrese las letras que desea cambiar (ej: A B C o 'todas'): ").strip()
        if not raw_input:
            print("Operación cancelada: no ingresó letras.")
            return
        
        if raw_input.lower() == "todas":
            letters = [t.letter for t in current_player.tiles]
        else:
            if " " in raw_input:
                letters = [l.strip().upper() for l in raw_input.split() if l.strip()]
            else:
                letters = [c.upper() for c in raw_input if c.isalpha() or c == "*"]
        
        try:
            game.change_tiles(letters)
            print(f"Fichas cambiadas con éxito. Pasa el turno al jugador #{game.current_player}")
        except Exception as e:
            print(f"Error: {e}")

    def pass_turn(self, game):
        game.pass_turn()

    def end_game(self, game):
        winners = game.compare_score()
        if len(winners) == 1:
            winner = winners[0]
            print('-'*100)
            print(f"El ganador es: jugador #{game.players.index(winner)} con {winner.score} puntos")
        else:
            print('-'*100)
            print("¡Empate!")
            print("Los ganadores son:")
            for winner in winners:
                print(f"Jugador #{game.players.index(winner)} con {winner.score} puntos")
        exit()

    def play_scrabble(self):
        print("BIENVENIDO A SCRABBLE GAME")
        players_count = self.get_player_count()
        game = ScrabbleGame(players_count)
        menu_options = {
            '1': self.play_word,
            '2': self.change,
            '3': self.joker,
            '4': self.pass_turn,
            '5': self.end_game
        }
        while not game.finish_game():
            self.show_board(game.get_board())
            self.show_player(game.current_player, game.get_current_player(), len(game.bag_tiles.tiles))
            render_menu()

            choice = input("\nSeleccione una opción (1-5): ").strip()

            selected_option = menu_options.get(choice)
            if selected_option:
                selected_option(game)     
            else:
                print("Opción inválida. Por favor, seleccione una opción válida.")
        
        print('¡Juego finalizado!')
        self.end_game(game)


if __name__=="__main__":
    main = Main()
    main.play_scrabble()
