from collections.abc import Callable
from typing import cast
from unittest.mock import Mock

import pytest

from DBDofusUnity.dofus_unity_reader.data_center.area_info import AreaInfo
from DBDofusUnity.dofus_unity_reader.game_constants.area import AreaEnum
from src.controller.settings import SettingsService
from src.core.behaviors.behavior import Behavior, BehaviorState
from src.core.behaviors.farms import configurable_auto_behavior as configurable
from src.core.behaviors.farms.base_farm_behavior import BaseFarmingErrorCode
from src.core.behaviors.movements.auto_trip.auto_trip_behavior import AutoTripErrorCode
from src.core.bot.bot import Bot
from src.core.config import ConfigurableAutoSettings, RouteFailureAction
from src.core.signals.bot_signals import FarmDecision


def test_preferences_are_saved_per_account(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SettingsService()
    chosen = ConfigurableAutoSettings(area_id=AreaEnum.ASTRUB, on_route_failure=RouteFailureAction.WAIT)
    service.update_configurable_auto(101, chosen)
    service.update_configurable_auto(202, ConfigurableAutoSettings(area_id=AreaEnum.INCARNAM))
    monkeypatch.setattr(service, "_settings", None)
    assert service.configurable_auto(101) == chosen
    assert service.configurable_auto(202).area_id == AreaEnum.INCARNAM
    assert service.configurable_auto(303) == ConfigurableAutoSettings()


@pytest.mark.parametrize("action", list(RouteFailureAction))
def test_configurable_mode_reports_route_failure_and_applies_preference(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch, action: RouteFailureAction
) -> None:
    original = runtime_bot.auto_bot_behavior
    behavior = runtime_bot.configurable_auto_behavior
    start_harvesting = Mock()
    timers = Mock()
    finished = Mock()
    decisions: list[FarmDecision] = []
    runtime_bot.bot_signals.configurable_auto_decision.connect(decisions.append)

    def skip_equipment(*, callback: Callable[[str | None], None], parent: Behavior) -> None:
        callback(None)

    monkeypatch.setattr(behavior.auto_equipment_behavior, "start", skip_equipment)
    monkeypatch.setattr(behavior.multi_farming_behavior, "start", start_harvesting)
    monkeypatch.setattr(behavior, "run_timer", timers)
    monkeypatch.setattr(behavior, "_zone_has_maps", Mock(return_value=True))
    monkeypatch.setattr(
        configurable,
        "get_harvesting_area_weights",
        Mock(
            return_value={
                AreaInfo(area_id=AreaEnum.ASTRUB): 1.0,
                AreaInfo(area_id=AreaEnum.INCARNAM): 1.0,
            }
        ),
    )

    try:
        behavior.start(
            callback=finished,
            parent=None,
            preferences=ConfigurableAutoSettings(
                area_id=AreaEnum.ASTRUB,
                on_route_failure=action,
            ),
        )
        assert original.state is BehaviorState.STOPPED
        assert decisions[-1].area_id == AreaEnum.ASTRUB
        assert start_harvesting.call_args.kwargs["area_id"] == AreaEnum.ASTRUB

        callback = cast(Callable[[str | None], None], start_harvesting.call_args.kwargs["callback"])
        callback(BaseFarmingErrorCode.STOP_CONDITION_TRIGGERED)
        rotate = cast(Callable[[], None], timers.call_args.args[1])
        rotate()
        assert decisions[-1].area_id == AreaEnum.ASTRUB
        timers.reset_mock()

        callback = cast(Callable[[str | None], None], start_harvesting.call_args.kwargs["callback"])
        callback(AutoTripErrorCode.PATH_NOT_FOUND)
        assert decisions[-1].reason == configurable.RouteFailure.NO_ROUTE

        if action is RouteFailureAction.STOP:
            assert decisions[-1].activity == "Stopped"
            assert behavior.state is BehaviorState.STOPPED
            finished.assert_called_once_with(configurable.RouteFailure.NO_ROUTE)
            timers.assert_not_called()
        else:
            assert decisions[-1].activity == (
                "Waiting" if action is RouteFailureAction.WAIT else "Changing zone"
            )
            retry = cast(Callable[[], None], timers.call_args.args[1])
            retry()
            expected_zone = AreaEnum.ASTRUB if action is RouteFailureAction.WAIT else AreaEnum.INCARNAM
            assert decisions[-1].area_id == expected_zone
            assert start_harvesting.call_args.kwargs["area_id"] == expected_zone
            finished.assert_not_called()
    finally:
        behavior.stop()


def test_five_empty_maps_trigger_resource_failure(runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch) -> None:
    farming = runtime_bot.configurable_auto_behavior.multi_farming_behavior
    advance = Mock()
    finish = Mock()
    monkeypatch.setattr(farming, "run_next_step", advance)
    monkeypatch.setattr(farming, "finish", finish)
    farming.collect_behavior.completed_collections = 0

    for map_id in range(1, 5):
        monkeypatch.setattr(farming.game_state.map, "_map_id", map_id)
        farming.on_collect_behavior_finished(None)
    finish.assert_not_called()

    monkeypatch.setattr(farming.game_state.map, "_map_id", 5)
    farming.on_collect_behavior_finished(None)
    finish.assert_called_once_with(configurable.RouteFailure.NO_RESOURCES)
