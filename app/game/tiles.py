import random

class NoHayFichas(Exception):
    pass

class ImposibleCambiarMasDe7(Exception):
    pass

class BolsaLlena(Exception):
    pass

class NoEsUnJoker(Exception):
    pass

class Tile:
    def __init__(self, letter, value):
        self.letter = letter
        self.value = value

    def joker(self, new_letter):
        if self.letter == "*":
            self.letter = new_letter
        else:
            raise NoEsUnJoker(Exception)
        
    def __repr__(self):
        return f"{self.letter}:{self.value}"

class BagTiles:
    def __init__(self):
        distribution = [
            ("A", 1, 12), ("E", 1, 12), ("O", 1, 9), ("I", 1, 6), ("S", 1, 6),
            ("N", 1, 5), ("L", 1, 5), ("R", 1, 5), ("U", 1, 5), ("T", 1, 4),
            ("D", 2, 5), ("G", 2, 2), ("C", 3, 4), ("B", 3, 2), ("M", 3, 2),
            ("P", 3, 2), ("H", 4, 2), ("F", 4, 1), ("V", 4, 1), ("Y", 4, 1),
            ("Q", 5, 1), ("J", 8, 1), ("Ñ", 8, 1), ("X", 8, 1), ("Z", 10, 1),
            ("*", 0, 2),
        ]
        self.tiles = [
            Tile(letter, value)
            for letter, value, count in distribution
            for _ in range(count)
        ]
        random.shuffle(self.tiles)
    
    def take(self, count):
        tiles = []
        if len(self.tiles) == 0:
            raise NoHayFichas(Exception)
        else:
            for _ in range(count):
                tiles.append(self.tiles.pop())
            return tiles
        
    def put(self, tiles):
        if len(tiles) > 7:
            raise ImposibleCambiarMasDe7(Exception)
        elif len(self.tiles) == 100:
            raise BolsaLlena(Exception)
        else:
            self.tiles.extend(tiles)
            random.shuffle(self.tiles)


