from game.tiles import BagTiles

class NoJoker(Exception):
    pass

class Player:

    def __init__(self, bag_tiles=None):
        if bag_tiles is None:
            bag_tiles = BagTiles()
        self.bag_tiles = bag_tiles
        self.tiles = self.bag_tiles.take(7)
        self.score = 0
    
    def rellenar(self):
        self.tiles += self.bag_tiles.take(7 - len(self.tiles))

    def has_letters(self, letters):
        player_letters = [tile.letter for tile in self.tiles]
        for letter in letters:
            if letter in player_letters:
                player_letters.remove(letter)
            else:
                return False
        return True
    
    def joker_in_tiles(self):
        for tile in self.tiles:
            if tile.letter == '*':
                return True
        return False

    def convert_joker(self, letter):
        joker_tile = next((tile for tile in self.tiles if tile.letter == '*'), None)
        if joker_tile:
            joker_tile.letter = letter.upper()
            joker_tile.value = 0
            
        else:
            raise NoJoker("No tiene joker")
        
    

    

