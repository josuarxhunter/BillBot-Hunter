from threading import Lock

_initialization_lock = Lock()
_initialized = False


def initialize_protocol() -> None:
    global _initialized
    if _initialized:
        return
    with _initialization_lock:
        if _initialized:
            return
        from DBDofusUnity.consts import PROTOS_ROOT
        from src.utils.registry import import_and_get_all_msg_from_folder

        for folder in ("obf/game", "non_obf/game", "non_obf/connection"):
            import_and_get_all_msg_from_folder(str(PROTOS_ROOT / folder))
        _initialized = True
