"""Conteo de tracks cuando cruzan una línea virtual por primera vez."""


class CountingLine:
    """Cuenta cruces de izquierda a derecha sin duplicar identificadores."""

    def __init__(self, x_position: float) -> None:
        self.x_position = x_position
        self.counted: set[str] = set()
        self.count = 0

    def update(self, track_id: str, previous_x: float | None, current_x: float) -> int:
        """Actualiza el total al cruzar la línea hacia delante."""
        if track_id not in self.counted and previous_x is not None and previous_x < self.x_position <= current_x:
            self.counted.add(track_id)
            self.count += 1
        return self.count
