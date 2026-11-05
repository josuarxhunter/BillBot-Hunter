import logging
from collections import ChainMap
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from struct import error as StructError

from ankama_launcher_emulator.utils.environment import resolve_dofus_path

from DBDofusUnity.dofus_unity_reader.data_center.i18n import I18N
from DBDofusUnity.dofus_unity_reader.generator.i18n import I18NReader
from src.gui.i18n import get_language
from src.utils.runtime_support import RuntimeSetupError

logger = logging.getLogger(__name__)


@cache
def _spanish_names() -> dict[int, str]:
    try:
        game_directory = Path(resolve_dofus_path()).parent
        return I18NReader.read_names(game_directory / "Dofus_Data/StreamingAssets/Content/I18n/es.bin")
    except (RuntimeSetupError, OSError, ValueError, StructError, IndexError) as error:
        logger.warning("Unable to load Spanish game names: %s", error)
        return {}


def game_names() -> Mapping[int, str]:
    original = I18N().name_by_id
    if get_language() == "es":
        return ChainMap(_spanish_names(), original)
    return original
