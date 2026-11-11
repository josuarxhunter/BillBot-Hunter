from collections.abc import Callable
from datetime import datetime, timedelta
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
from src.core.config import BehaviorSettings, ConfigurableAutoSettings, RouteFailureAction
from src.core.config import HarvestGoal
from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ObjectItem, ObjectItemInventory
from DBDofusUnity.datas.protos.non_obf.game.teleportation_pb2 import (
    TeleportDestinationsEvent,
    TeleportDestination,
)
from src.core.behaviors.movements.waypoint_behavior import WaypointErrorCode
from src.core.signals.bot_signals import FarmDecision
from src.core.engine.movements.world.farm_travel import FarmTravelPlan


def test_preferences_are_saved_per_account(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SettingsService()
    chosen = ConfigurableAutoSettings(
        area_id=AreaEnum.ASTRUB,
        on_route_failure=RouteFailureAction.WAIT,
        goal=HarvestGoal.TARGETS,
        target_resource_ids=(100,),
        target_quantity=10,
        reserve_kamas=4321,
        occasional_combat=False,
    )
    service.update_configurable_auto(101, chosen)
    service.update_configurable_auto(202, ConfigurableAutoSettings(area_id=AreaEnum.INCARNAM))
    monkeypatch.setattr(service, "_settings", None)
    assert service.configurable_auto(101) == chosen
    assert service.configurable_auto(202).area_id == AreaEnum.INCARNAM
    assert service.configurable_auto(303) == ConfigurableAutoSettings()


@pytest.mark.parametrize("scheduled", [False, True])
def test_default_start_uses_saved_account_preferences(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch, scheduled: bool
) -> None:
    preferences = ConfigurableAutoSettings(area_id=AreaEnum.ASTRUB, occasional_combat=False)
    SettingsService().update_configurable_auto(runtime_bot.account.apikey.accountId, preferences)
    coordinator = runtime_bot.behavior_coordinator
    start = Mock()

    def play_action(action: Callable[[Callable[[str], None]], None]) -> None:
        action(Mock())

    monkeypatch.setattr(runtime_bot.configurable_auto_behavior, "start", start)
    monkeypatch.setattr(coordinator, "play_action", play_action)
    monkeypatch.setattr(coordinator, "get_bot_config", Mock(return_value=Mock(schedule_profile="day")))

    if scheduled:
        coordinator.run_current_bot_action()
    else:
        runtime_bot.bot_signals.play_configurable_auto.emit(None)

    start.assert_called_once()
    assert start.call_args.kwargs["preferences"] == preferences


def test_due_dungeon_runs_once_and_resumes_configurable_farming(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    SettingsService().update_behaviors(BehaviorSettings(do_dungeon=True, do_sale_hotel=False), False)
    behavior = runtime_bot.configurable_auto_behavior
    now = datetime.now()
    behavior.start_planned_session(now - timedelta(hours=2), now + timedelta(seconds=1))
    dungeon_start = Mock()
    resume_harvesting = Mock()

    def run_timer(_delay: tuple[float, float] | float, callback: Callable[[], None]) -> None:
        callback()

    monkeypatch.setattr(behavior.dungeon_behavior, "start", dungeon_start)
    monkeypatch.setattr(behavior, "play_multi_farming", resume_harvesting)
    monkeypatch.setattr(behavior, "run_timer", run_timer)

    behavior.on_multi_farming_behavior_finished(BaseFarmingErrorCode.STOP_CONDITION_TRIGGERED)

    dungeon_start.assert_called_once()
    resume_harvesting.assert_not_called()
    behavior.dungeon_behavior._activity_performed = True
    callback = cast(Callable[[str | None], None], dungeon_start.call_args.kwargs["callback"])
    callback(None)
    resume_harvesting.assert_called_once_with()

    behavior.on_multi_farming_behavior_finished(BaseFarmingErrorCode.STOP_CONDITION_TRIGGERED)
    dungeon_start.assert_called_once()
    assert resume_harvesting.call_count == 2


@pytest.mark.parametrize("action", list(RouteFailureAction))
def test_configurable_mode_reports_route_failure_and_applies_preference(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch, action: RouteFailureAction
) -> None:
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
    monkeypatch.setattr(behavior, "_plan_zone", Mock(return_value=FarmTravelPlan(0)))
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


def test_zone_selection_excludes_unreachable_and_poor_candidates(
    runtime_bot: Bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    behavior = runtime_bot.configurable_auto_behavior
    candidates = {AreaInfo(area_id=index): float(score) for index, score in ((1, 100), (2, 10), (3, 200))}
    monkeypatch.setattr(configurable, "get_harvesting_area_weights", Mock(return_value=candidates))

    def plan(zone: AreaInfo) -> FarmTravelPlan | None:
        return None if zone.area_id == 3 else FarmTravelPlan(0)

    monkeypatch.setattr(behavior, "_plan_zone", plan)
    zone, _ = behavior._select_zone()
    assert zone == AreaInfo(area_id=1)


def test_zone_selection_keeps_current_zone_when_improvement_does_not_pay_for_travel(
    runtime_bot: Bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    behavior = runtime_bot.configurable_auto_behavior
    current = AreaInfo(area_id=1)
    other = AreaInfo(area_id=2)
    behavior._selected_zone = current
    monkeypatch.setattr(
        configurable, "get_harvesting_area_weights", Mock(return_value={current: 100, other: 110})
    )
    monkeypatch.setattr(behavior, "_plan_zone", Mock(return_value=FarmTravelPlan(0)))
    zone, _ = behavior._select_zone()
    assert zone == current


def test_failed_zone_becomes_eligible_after_cooldown(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    behavior = runtime_bot.configurable_auto_behavior
    zone = AreaInfo(area_id=1)
    behavior._failed_zones[(1, None)] = 200
    monkeypatch.setattr(configurable, "get_harvesting_area_weights", Mock(return_value={zone: 1}))
    monkeypatch.setattr(behavior, "_plan_zone", Mock(return_value=FarmTravelPlan(0)))
    monkeypatch.setattr(configurable, "monotonic", lambda: 100)
    assert behavior._select_zone()[0] is None
    monkeypatch.setattr(configurable, "monotonic", lambda: 201)
    assert behavior._select_zone()[0] == zone


def test_low_productivity_fails_even_when_some_resources_are_collected(
    runtime_bot: Bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    farming = cast(
        configurable.ConfigurableFarmingBehavior,
        runtime_bot.configurable_auto_behavior.multi_farming_behavior,
    )
    runtime_bot.game_state.configurable_auto = ConfigurableAutoSettings(
        productivity_window_minutes=1,
        minimum_collections_per_minute=2,
    )
    farming._observing_since = 0
    farming.collect_behavior.completed_collections = 1
    finish = Mock()
    monkeypatch.setattr(farming, "finish", finish)
    monkeypatch.setattr(configurable, "monotonic", lambda: 61)
    farming.on_collect_behavior_finished(None)
    finish.assert_called_once_with(configurable.RouteFailure.LOW_PRODUCTIVITY)


def test_full_inventory_does_not_enable_recovery_combat_by_default(
    runtime_bot: Bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    behavior = runtime_bot.configurable_auto_behavior
    finish = Mock()
    fight = Mock()
    monkeypatch.setattr(behavior, "finish", finish)
    monkeypatch.setattr(behavior.fighter_behavior, "start", fight)
    behavior.play_fighter()
    fight.assert_not_called()
    finish.assert_called_once()


def test_resource_target_stops_when_bank_and_inventory_reach_requested_quantity(runtime_bot: Bot) -> None:
    behavior = runtime_bot.configurable_auto_behavior
    behavior._preferences = ConfigurableAutoSettings(
        goal=HarvestGoal.TARGETS,
        target_resource_ids=(100,),
        target_quantity=10,
    )
    inventory = behavior.game_state.inventory
    inventory.bank_objects_by_uid = {1: ObjectItemInventory(item=ObjectItem(gid=100, quantity=6))}
    inventory.objects_by_uid.clear()
    inventory.objects_by_uid[2] = ObjectItemInventory(item=ObjectItem(gid=100, quantity=4))
    assert behavior._targets_completed()


@pytest.mark.parametrize("cost,allowed", [(500, True), (1500, False)])
def test_zaap_checks_current_quote_before_spending_protected_kamas(
    runtime_bot: Bot,
    monkeypatch: pytest.MonkeyPatch,
    cost: int,
    allowed: bool,
) -> None:
    route = runtime_bot.configurable_auto_behavior.multi_farming_behavior.random_farm_behavior
    waypoint = (
        route.auto_trip_smart_behavior.auto_trip_explorator_behavior.auto_trip_zaap_behavior.waypoint_behavior
    )
    runtime_bot.game_state.configurable_auto = ConfigurableAutoSettings(reserve_kamas=1000)
    runtime_bot.game_state.inventory.kamas = 2000
    send = Mock()
    finish = Mock()
    monkeypatch.setattr(waypoint, "_send_teleport", send)
    monkeypatch.setattr(waypoint, "finish", finish)
    waypoint.on_quoted_destinations(
        TeleportDestinationsEvent(
            destinations=[
                TeleportDestination(map_id=10, cost=cost),
            ]
        ),
        10,
    )
    send.assert_not_called()
    waypoint.on_zaap_used(None, 10)
    if allowed:
        send.assert_called_once_with(10)
        finish.assert_not_called()
    else:
        send.assert_not_called()
        finish.assert_called_once_with(WaypointErrorCode.UNAFFORDABLE)
