from game.board import Board
from game.player import Player
from game.tiles import BagTiles, Tile
from game.cell import Cell
from game.dictionary import validate_word as validate_word_dict

class InvalidWord(Exception):
    pass

class InvalidPlaceWordException(Exception):
    pass

class NoJoker(Exception):
    pass

class CannotChangeTilesException(Exception):
    pass

class ScrabbleGame:
    def __init__(self, players_count):
        self.board = Board()
        self.bag_tiles = BagTiles()
        self.players = []
        for _ in range(players_count):
            self.players.append(Player(bag_tiles=self.bag_tiles))   
        self.current_player = 0
        self.consecutive_passes = 0

    def next_turn(self):
        self.current_player = (self.current_player + 1)% len(self.players)

    def pass_turn(self):
        self.consecutive_passes += 1
        self.next_turn()
    
    def is_playing(self):
        return True
    
    def get_current_player(self):
        return self.players[self.current_player]
    
    def get_player_tiles(self):
        return self.players[self.current_player].tiles
    
    def get_board(self):
        return self.board
        
    def validate_word(self, word, location, orientation):
        word = word.upper()
        if not validate_word_dict(word):
            raise InvalidWord("No existe la palabra")
        elif not self.board.validate_word_inside_board(word, location, orientation):
            raise InvalidPlaceWordException("No es correcta la ubicación")
        elif not self.board.is_empty():
            if not self.board.is_valid_crossword(word, location, orientation):
                raise InvalidPlaceWordException("La palabra debe estar cruzada")
        elif not self.board.validate_word_place_board(word, location, orientation):
            raise InvalidPlaceWordException("No se puede colocar")
        
    def convert_joker_to_letter(self, letter):
        current_player = self.get_current_player()
        current_player.convert_joker(letter)

    def get_joker_index(self):
        joker_indices = [index for index, tile in enumerate(self.get_current_player().tiles) if tile.letter == '*']
        if joker_indices:
            return joker_indices[0]
        else:
            raise NoJoker("No tiene joker")
        
    def play(self, word, location, orientation, rack):

        self.validate_word(word, location, orientation)
        needed_letters = self.board.get_needed_letters(word, location, orientation)
        if not self.get_current_player().has_letters(needed_letters):
            raise InvalidPlaceWordException("No tienes las letras suficientes en tu atril")
        self.board.put_word(word, location, orientation, rack)
        word_cells = self.board.get_word_cells(word, location, orientation) 
        total_score = self.board.calculate_word_value(word_cells)
        self.players[self.current_player].score += total_score
        self.players[self.current_player].rellenar()
        self.consecutive_passes = 0
        self.next_turn()

    def change_tiles(self, letters):
        if len(self.bag_tiles.tiles) < 7:
            raise CannotChangeTilesException("No se pueden cambiar fichas: deben quedar al menos 7 fichas en la bolsa.")
        
        if not (1 <= len(letters) <= 7):
            raise CannotChangeTilesException("Debes seleccionar entre 1 y 7 fichas para cambiar.")
        
        current_player = self.get_current_player()
        letters_upper = [l.upper() for l in letters]
        
        if not current_player.has_letters(letters_upper):
            raise CannotChangeTilesException("No tienes esas letras en tu atril para cambiarlas.")
        
        tiles_to_put = []
        for letter in letters_upper:
            tile = next(t for t in current_player.tiles if t.letter == letter)
            current_player.tiles.remove(tile)
            tiles_to_put.append(tile)
        
        new_tiles = self.bag_tiles.take(len(tiles_to_put))
        current_player.tiles.extend(new_tiles)
        self.bag_tiles.put(tiles_to_put)
        self.consecutive_passes = 0
        
        self.next_turn()

    def compare_score(self):
        max_score = 0
        max_score_players = []

        for player in self.players:
            if player.score > max_score:
                max_score = player.score
                max_score_players = [player]
            elif player.score == max_score:
                max_score_players.append(player)

        return max_score_players
    
    def finish_game(self):
        # Condición 1: Bolsa vacía y al menos un jugador sin fichas en su atril
        if len(self.bag_tiles.tiles) == 0:
            for player in self.players:
                if len(player.tiles) == 0:
                    return True
        
        # Condición 2: Bloqueo - 2 rondas seguidas de pases (2 * cantidad de jugadores)
        if self.consecutive_passes >= len(self.players) * 2:
            return True
        
        return False
