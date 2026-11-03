"""Registro en memoria de sesiones M3 sin persistencia de negocio."""

from threading import RLock

from app.config import VIDEO_MIN_TRACK_HITS
from app.session.session_state import VisionSession


class SessionRegistry:
    """Conserva el estado temporal de sesiones durante la vida del proceso."""

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, int], VisionSession] = {}
        self._lock = RLock()

    def start(self, data: dict) -> VisionSession:
        """Abre una sesión nueva o devuelve la misma clave idempotente."""
        key = (str(data["analysis_id"]), int(data["attempt"]))
        with self._lock:
            if key in self._sessions:
                return self._sessions[key]
            session = VisionSession(
                analysis_id=key[0], attempt=key[1],
                calibration_version=int(data["calibration_version"]),
                reference_length_cm=data.get("reference_length_cm"),
                reference_pixels=data.get("reference_pixels"),
                size_ranges=data.get("size_ranges", {}),
                detection_confidence=float(data.get("detection_confidence", 0)),
                visual_condition_confidence=float(data.get("visual_condition_confidence", 0)),
                # Una imagen suelta es un solo fotograma: no se puede exigir persistencia.
                min_track_hits=VIDEO_MIN_TRACK_HITS if data.get("source") == "video" else 1,
            )
            self._sessions[key] = session
            return session

    def get(self, analysis_id: str, attempt: int) -> VisionSession:
        """Obtiene una sesión activa o informa que no existe."""
        with self._lock:
            try:
                return self._sessions[(str(analysis_id), int(attempt))]
            except KeyError as exc:
                raise KeyError("Sesión de visión no encontrada.") from exc

    def reset(self) -> None:
        """Limpia el registro, principalmente para pruebas."""
        with self._lock:
            self._sessions.clear()


session_registry = SessionRegistry()
