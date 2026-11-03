"""Seguimiento ligero por IoU para mantener IDs entre fotogramas."""

from dataclasses import dataclass


@dataclass(slots=True)
class Track:
    """Detección seguida con último centro y cuadro delimitador."""

    track_id: str
    bbox: tuple[float, float, float, float]
    center: tuple[float, float]
    missed: int = 0
    hits: int = 1


class IoUTracker:
    """Asocia detecciones consecutivas usando el solapamiento de sus cuadros."""

    def __init__(self, threshold: float = 0.3, max_missed: int = 10) -> None:
        self.threshold = threshold
        self.max_missed = max_missed
        self._next_id = 1
        self._tracks: dict[str, Track] = {}

    @staticmethod
    def _iou(left, right) -> float:
        x1, y1 = max(left[0], right[0]), max(left[1], right[1])
        x2, y2 = min(left[2], right[2]), min(left[3], right[3])
        intersection = max(0, x2 - x1) * max(0, y2 - y1)
        left_area = max(0, left[2] - left[0]) * max(0, left[3] - left[1])
        right_area = max(0, right[2] - right[0]) * max(0, right[3] - right[1])
        union = left_area + right_area - intersection
        return intersection / union if union else 0.0

    def update(self, detections: list[dict]) -> list[dict]:
        """Asocia cuadros, crea IDs nuevos y descarta tracks ausentes."""
        matched: set[str] = set()
        output = []
        for detection in detections:
            bbox = tuple(detection["bbox"])
            candidates = [(self._iou(track.bbox, bbox), key) for key, track in self._tracks.items() if key not in matched]
            overlap, track_id = max(candidates, default=(0.0, ""))
            if overlap < self.threshold:
                track_id = f"track-{self._next_id}"
                self._next_id += 1
            matched.add(track_id)
            center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
            previous = self._tracks.get(track_id)
            hits = previous.hits + 1 if previous else 1
            detection_output = {**detection, "track_id": track_id, "center": center,
                                "previous_center": previous.center if previous else None, "hits": hits}
            self._tracks[track_id] = Track(track_id, bbox, center, hits=hits)
            output.append(detection_output)
        for track_id in tuple(self._tracks):
            if track_id not in matched:
                self._tracks[track_id].missed += 1
                if self._tracks[track_id].missed > self.max_missed:
                    del self._tracks[track_id]
        return output
