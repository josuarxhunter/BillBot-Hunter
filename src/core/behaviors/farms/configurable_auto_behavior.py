import random
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from functools import partial
from threading import RLock
from time import monotonic

from DBDofusUnity.dofus_unity_reader.data_center.area_info import AreaInfo
from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from src.controller.settings import SettingsService
from src.core.behaviors.behavior import BehaviorState
from src.core.behaviors.craft.craft_behavior import CraftBehavior, CraftRequest
from src.core.behaviors.farms.base_farm_behavior import BaseFarmingErrorCode
from src.core.behaviors.farms.fight.fighter_behavior import FighterBehavior
from src.core.behaviors.farms.harvest.multi_farming_behavior import MultiFarmingBehavior
from src.core.behaviors.idle_behavior import IdleBehavior
from src.core.behaviors.items.auto_equipment_behavior import AutoEquipmentBehavior
from src.core.behaviors.movements.auto_trip.auto_trip_behavior import AutoTripErrorCode
from src.core.behaviors.quests.dungeon_behavior import DungeonBehavior
from src.core.behaviors.recovery_behavior import RecoverableBehavior
from src.core.behaviors.sale_hotel.sale_hotel_sell_behavior import SaleHotelErrorCode, SaleHotelSellBehavior
from src.core.behaviors.storage.enter_chests.enter_bank_chest_behavior import EnterBankChestErrorCode
from src.core.bot.session_activity_plan import SessionActivity, SessionActivityPlan
from src.core.config import ConfigurableAutoSettings, HarvestGoal, RouteFailureAction
from src.core.engine.contexts import HarvesterAreaContext
from src.core.engine.crafts.recipes import (
    get_recipes_for_job_lvl_up_or_benefice,
    is_not_valid_recipe_for_lvl_up_job_or_benefice,
)
from src.core.engine.movements.world.farm_travel import FarmTravelPlan, plan_farm_travel
from src.core.engine.weights.weight_areas import get_harvesting_area_weights
from src.core.engine.weights.harvester.weight_collectable import (
    get_harvest_requirements,
    get_weight_collectable,
)
from src.core.signals.bot_signals import BotSignals, FarmDecision
from src.core.states.area_state import CURRENT_AREAS_PLAYING_INFOS_BY_SERVER_AND_CHARACTER
from src.gui.i18n import tr
from src.services.human_timings import HumanTimingsService


AREA_CHOICE_LOCK = RLock()


class RouteFailure(StrEnum):
    NO_RESOURCES = "The consecutive empty-map limit was reached."
    LOW_PRODUCTIVITY = "Harvesting productivity stayed below the configured minimum."
    NO_ROUTE = "No usable route to or within the selected zone."
    NO_ZONE = "No eligible zone remains."


@dataclass
class ConfigurableFarmingBehavior(MultiFarmingBehavior):
    _empty_maps: int = field(init=False, default=0)
    _last_checked_map: int | None = field(init=False, default=None)
    _observations: deque[tuple[float, int]] = field(init=False, default_factory=deque[tuple[float, int]])
    _observing_since: float | None = field(init=False, default=None)
    _available: int = field(init=False, default=0)

    def run(
        self,
        area_id: int | None,
        sub_area_id: int | None,
        is_stopped_at_new_map_condition: Callable[[], bool] | None = None,
        target_resource_item_ids: set[int] | None = None,
    ) -> None:
        self._empty_maps = 0
        self._last_checked_map = None
        self._observations.clear()
        self._observing_since = None
        super().run(area_id, sub_area_id, is_stopped_at_new_map_condition, target_resource_item_ids)
        self._schedule_combat()

    def _schedule_combat(self) -> None:
        preferences = self.game_state.configurable_auto
        if preferences is not None:
            enabled = preferences.occasional_combat and self.game_state.settings.do_fighter
            self._next_time_attacker = datetime.now() + timedelta(
                minutes=preferences.combat_interval_minutes * random.uniform(0.75, 1.25)
                if enabled
                else 10_000_000
            )

    def on_new_map(self) -> None:
        if self.game_state.map.map_id in self.random_farm_behavior.map_ids:
            if self._observing_since is None:
                self._observing_since = monotonic()
            self._available = len(self.game_state.interactive.get_farmable_collectables())
        super().on_new_map()

    def on_attacker_behavior_finished(self, error_code: str | None, count_fighted_on_map: int) -> None:
        self._schedule_combat()
        self._observations.clear()
        self._observing_since = None
        super().on_attacker_behavior_finished(error_code, count_fighted_on_map)

    def on_unload_finished(self, error_code: str | None) -> None:
        self._observations.clear()
        self._observing_since = None
        super().on_unload_finished(error_code)

    def fight_on_map(self) -> None:
        self.report_status("Fighting a group of monsters…")
        super().fight_on_map()

    def on_full_pods(self) -> None:
        self.report_status("Handling the full inventory…")
        super().on_full_pods()

    def on_collect_behavior_finished(self, error_code: str | None) -> None:
        if error_code is not None:
            return super().on_collect_behavior_finished(error_code)
        preferences = self.game_state.configurable_auto or ConfigurableAutoSettings()
        map_id = self.game_state.map.map_id
        if self.collect_behavior.completed_collections:
            self._empty_maps = 0
        elif error_code is None and map_id != self._last_checked_map:
            self._empty_maps += 1
        self._last_checked_map = map_id

        now = monotonic()
        window = preferences.productivity_window_minutes * 60
        self._observations.append((now, self.collect_behavior.completed_collections))
        while self._observations and self._observations[0][0] < now - window:
            self._observations.popleft()
        elapsed = now - self._observing_since if self._observing_since is not None else 0
        rate = sum(count for _, count in self._observations) * 60 / max(1, min(elapsed, window))
        self.report_status(
            tr(
                "Harvest: {rate:.2f} collections/min; empty maps: {empty}; available: {available}; unreachable: {failed}.",
                rate=rate,
                empty=self._empty_maps,
                available=self._available,
                failed=len(self.collect_behavior.excluded_element_ids),
            )
        )
        if self._empty_maps >= preferences.empty_map_limit:
            return self.finish(RouteFailure.NO_RESOURCES)
        if elapsed >= window and rate < preferences.minimum_collections_per_minute:
            return self.finish(RouteFailure.LOW_PRODUCTIVITY)
        super().on_collect_behavior_finished(error_code)


@dataclass
class ConfigurableAutoBehavior(RecoverableBehavior):
    auto_equipment_behavior: AutoEquipmentBehavior
    fighter_behavior: FighterBehavior
    multi_farming_behavior: ConfigurableFarmingBehavior
    dungeon_behavior: DungeonBehavior
    idle_behavior: IdleBehavior
    craft_behavior: CraftBehavior
    sale_hotel_sell_behavior: SaleHotelSellBehavior
    _previous_area_info_played: list[AreaInfo] = field(init=False, default_factory=list[AreaInfo])
    bot_signals: BotSignals
    _session_activity_plan: SessionActivityPlan | None = field(init=False, default=None)
    _preferences: ConfigurableAutoSettings = field(init=False, default_factory=ConfigurableAutoSettings)
    _failed_zones: dict[tuple[int, int | None], float] = field(
        init=False, default_factory=dict[tuple[int, int | None], float]
    )
    _zone_started_at: float = field(init=False, default=0)
    _travel_plans: dict[AreaInfo, FarmTravelPlan] = field(
        init=False, default_factory=dict[AreaInfo, FarmTravelPlan]
    )
    _recovering_since: float | None = field(init=False, default=None)
    _selected_zone: AreaInfo | None = field(init=False, default=None)
    _registered_zone: tuple[tuple[int, int], AreaInfo] | None = field(init=False, default=None)
    _priority_resource_ids: tuple[int, ...] = ()

    def start_planned_session(self, session_start: datetime, session_end: datetime) -> None:
        self.game_state.apply_settings(SettingsService().get().behaviors)
        activities: list[SessionActivity] = []
        if self.game_state.settings.do_idle:
            activities.append(SessionActivity.IDLE)
        if self.game_state.settings.do_dungeon:
            activities.append(SessionActivity.DUNGEON)
        if self.game_state.settings.do_craft:
            activities.append(SessionActivity.CRAFT)
        if self.game_state.settings.do_sale_hotel:
            activities.append(SessionActivity.SALE_HOTEL)
        self._session_activity_plan = SessionActivityPlan.create(
            session_start=session_start,
            session_end=session_end,
            activities=activities,
        )
        planned_slots = [
            f"{slot.activity} at {slot.starts_at:%H:%M}" for slot in self._session_activity_plan.slots
        ]
        self.logger.info("Planned session activities: %s", planned_slots)

    def clear_planned_session(self) -> None:
        self._session_activity_plan = None

    def get_harvester_area_context(self) -> HarvesterAreaContext:
        return HarvesterAreaContext(
            player_level=self.game_state.player.level,
            player_waypoint_map_ids=frozenset(self.game_state.player.waypoint_map_ids),
            player_is_sub=self.game_state.player.is_sub,
            player_server_id=self.game_state.player.server_id,
            player_jobs_lvl_by_id=self.game_state.player.jobs_lvl_by_id,
            bank_storage_by_gid=self.game_state.inventory.get_bank_objects_by_gid(),
            current_area_infos_by_server_and_character=(CURRENT_AREAS_PLAYING_INFOS_BY_SERVER_AND_CHARACTER),
        )

    def start_playing(self) -> None:
        if self.game_state.inventory.is_full_pods:
            return self.play()
        self.auto_equipment_behavior.start(callback=self.on_initial_auto_equipment_finished, parent=self)

    def on_initial_auto_equipment_finished(self, error_code: str | None) -> None:
        self.raise_if_error(error_code)
        self.play()

    def play(self) -> None:
        if not self.game_state.inventory.is_full_pods or self.game_state.inventory.can_use_bank:
            return self.play_multi_farming()
        if self.game_state.settings.do_fighter:
            return self.play_fighter()
        self.finish(EnterBankChestErrorCode.NOT_ENOUGH_KAMAS)

    def _get_due_activity(self) -> SessionActivity | None:
        if self._session_activity_plan is None:
            return None
        return self._session_activity_plan.get_due_activity(datetime.now())

    def _start_session_activity(self, activity: SessionActivity) -> None:
        self.logger.info("Starting planned session activity: %s", activity)
        if activity is SessionActivity.IDLE:
            idle_duration = HumanTimingsService().get_timing_session_idle_duration()
            self.logger.info("Taking planned idle break: %.1fmin", idle_duration / 60)
            return self.idle_behavior.start(
                duration=idle_duration,
                callback=partial(self._on_session_activity_finished, activity),
                parent=self,
            )

        if activity is SessionActivity.DUNGEON:
            return self.dungeon_behavior.start(
                callback=partial(self._on_session_activity_finished, activity),
                parent=self,
            )

        if activity is SessionActivity.CRAFT:
            recipes = get_recipes_for_job_lvl_up_or_benefice(
                self.game_state.player.is_sub, self.game_state.player.jobs_lvl_by_id
            )
            return self.craft_behavior.start(
                craft_requests=[
                    CraftRequest(
                        recipe=recipe,
                        stop_condition=partial(
                            is_not_valid_recipe_for_lvl_up_job_or_benefice,
                            is_sub=self.game_state.player.is_sub,
                            jobs_lvl_by_id=self.game_state.player.jobs_lvl_by_id,
                        ),
                    )
                    for recipe in recipes
                ],
                callback=partial(self._on_session_activity_finished, activity),
                parent=self,
            )

        assert activity is SessionActivity.SALE_HOTEL, f"Unsupported session activity: {activity}"
        self.sale_hotel_sell_behavior.start(
            callback=partial(self._on_session_activity_finished, activity), parent=self
        )

    def _on_session_activity_finished(self, activity: SessionActivity, error_code: str | None) -> None:
        if error_code is not None:
            self.logger.warning("Planned session activity %s finished with %s", activity, error_code)
        assert self._session_activity_plan is not None, "A planned activity requires an active session plan"
        if error_code is None and not self._activity_was_performed(activity):
            self._session_activity_plan.discard_empty_activity(activity, datetime.now())
            self.logger.info("Removed empty planned session activity: %s", activity)
        else:
            self._session_activity_plan.mark_activity_completed(activity)
        self.run_timer(HumanTimingsService().get_timing_base_action(), self.play_multi_farming)

    def _activity_was_performed(self, activity: SessionActivity) -> bool:
        if activity is SessionActivity.IDLE:
            return True
        if activity is SessionActivity.DUNGEON:
            return self.dungeon_behavior.activity_performed
        if activity is SessionActivity.CRAFT:
            return self.craft_behavior.activity_performed
        assert activity is SessionActivity.SALE_HOTEL, f"Unsupported planned activity: {activity}"
        return self.sale_hotel_sell_behavior.activity_performed

    def run(
        self,
        preferences: ConfigurableAutoSettings,
    ) -> None:
        self._preferences = preferences
        self._failed_zones.clear()
        self._previous_area_info_played.clear()
        self._selected_zone = None
        self._recovering_since = None
        self._travel_plans.clear()
        self._priority_resource_ids = ()
        self.game_state.configurable_auto = self._preferences
        if any(gid not in DataReader().gathered_item_ids for gid in self._preferences.target_resource_ids):
            return self.finish("The selected resource list contains an unknown resource.")
        self._publish("Preparing", "Configurable mode started.", "Check equipment and choose a zone.")
        self.ensure_free_to_act(self.start_playing)

    def _release_zone(self) -> None:
        with AREA_CHOICE_LOCK:
            if self._registered_zone is not None:
                key, zone = self._registered_zone
                if CURRENT_AREAS_PLAYING_INFOS_BY_SERVER_AND_CHARACTER.get(key) is zone:
                    del CURRENT_AREAS_PLAYING_INFOS_BY_SERVER_AND_CHARACTER[key]
                self._registered_zone = None

    def clear_behavior(self) -> None:
        self._release_zone()
        super().clear_behavior()
        self.game_state.configurable_auto = None

    def _publish(self, activity: str, reason: str, next_action: str) -> None:
        zone = self._selected_zone
        plan = self._travel_plans.get(zone) if zone is not None else None
        self.logger.info(
            "%s: %s Zone=%s/%s. Next: %s",
            activity,
            reason,
            zone.area_id if zone else None,
            zone.sub_area_id if zone else None,
            next_action,
        )
        self.bot_signals.configurable_auto_decision.emit(
            FarmDecision(
                activity,
                reason,
                next_action,
                zone.area_id if zone else None,
                zone.sub_area_id if zone else None,
                self._priority_resource_ids,
                plan.seconds if plan is not None else None,
                plan.cost if plan is not None else None,
                plan.waypoint_map_id if plan is not None else None,
            )
        )

    def _select_zone(self) -> tuple[AreaInfo | None, str]:
        self._travel_plans.clear()
        now = monotonic()
        self._failed_zones = {key: until for key, until in self._failed_zones.items() if until > now}
        area_id = self._preferences.area_id
        sub_area_id = self._preferences.sub_area_id
        if area_id is not None and not self._failed_zones:
            return AreaInfo(area_id=area_id, sub_area_id=sub_area_id), "Zone set in account preferences."

        candidates = {
            zone: weight
            for zone, weight in get_harvesting_area_weights(
                replace(
                    self.get_harvester_area_context(),
                    bank_storage_by_gid=self.game_state.inventory.get_harvest_stock_by_gid(),
                ),
                [],
                self._preferences,
            ).items()
            if (zone.area_id, zone.sub_area_id) not in self._failed_zones
            and (zone.area_id, None) not in self._failed_zones
            and (
                zone.sub_area_id is not None
                or not any(failed_area == zone.area_id for failed_area, _ in self._failed_zones)
            )
        }
        if not candidates:
            return None, RouteFailure.NO_ZONE
        scores: dict[AreaInfo, float] = {}
        for zone, weight in candidates.items():
            plan = self._plan_zone(zone)
            if plan is None:
                continue
            self._travel_plans[zone] = plan
            horizon = self._preferences.rotation_minutes * 60
            scores[zone] = weight * horizon / (horizon + plan.effort(self._preferences))
        if not scores:
            return None, RouteFailure.NO_ROUTE
        current = self._selected_zone
        best_score = max(scores.values())
        if current in scores and (
            now - self._zone_started_at < self._preferences.minimum_stay_minutes * 60
            or best_score <= scores[current] * (1 + self._preferences.minimum_improvement_percent / 100)
        ):
            return current, "The current zone is productive; the travel does not justify changing it."
        eligible = {
            zone: score / (1 + self._previous_area_info_played.count(zone))
            for zone, score in scores.items()
            if score >= best_score * self._preferences.candidate_quality_percent / 100
        }
        zone = random.choices(list(eligible), weights=list(eligible.values()), k=1)[0]
        return zone, tr(
            "Goal: {goal}. Score after travel and competition: {score:.1f}.",
            goal=tr(self._preferences.goal.value),
            score=scores[zone],
        )

    def _plan_zone(self, zone: AreaInfo) -> FarmTravelPlan | None:
        route = self.multi_farming_behavior.random_farm_behavior
        finder = route.auto_trip_smart_behavior.auto_trip_explorator_behavior.auto_trip_zaap_behavior.auto_trip_behavior.world_path_finder
        return plan_farm_travel(
            self.game_state,
            finder,
            route.get_map_ids(zone.area_id, zone.sub_area_id),
            self._preferences,
        )

    def _zone_has_maps(self, zone: AreaInfo) -> bool:
        reader = DataReader()
        if zone.area_id not in reader.area_by_id:
            return False
        if zone.sub_area_id is None and zone.area_id not in reader.sub_areas_by_area_id:
            return False
        if zone.sub_area_id is not None:
            subarea = reader.sub_area_by_id.get(zone.sub_area_id)
            if subarea is None or subarea.areaId != zone.area_id:
                return False
        if not self.multi_farming_behavior.random_farm_behavior.get_map_ids(zone.area_id, zone.sub_area_id):
            return False
        if zone not in self._travel_plans:
            plan = self._plan_zone(zone)
            if plan is None:
                return False
            self._travel_plans[zone] = plan
        return True

    def _start_harvesting_zone(self, zone: AreaInfo, reason: str) -> None:
        if not self._zone_has_maps(zone):
            return self._on_route_failure(RouteFailure.NO_ROUTE)
        if not get_harvesting_area_weights(
            replace(
                self.get_harvester_area_context(),
                bank_storage_by_gid=self.game_state.inventory.get_harvest_stock_by_gid(),
            ),
            [],
            self._preferences,
            [zone],
        ):
            return self._on_route_failure(RouteFailure.NO_RESOURCES)
        if zone not in self._travel_plans:
            plan = self._plan_zone(zone)
            if plan is not None:
                self._travel_plans[zone] = plan
        reader = DataReader()
        subareas = (
            [zone.sub_area_id]
            if zone.sub_area_id is not None
            else reader.sub_areas_by_area_id.get(zone.area_id, set())
        )
        requirements = get_harvest_requirements()
        stock = self.game_state.inventory.get_harvest_stock_by_gid()
        weights: dict[int, float] = {}
        for subarea_id in subareas:
            for gid in reader.sub_area_by_id[subarea_id].harvestables:
                if gid not in requirements:
                    continue
                job_id, _ = requirements[gid]
                value = get_weight_collectable(
                    job_id,
                    self.game_state.player.jobs_lvl_by_id.get(job_id, 1),
                    gid,
                    stock,
                    self.game_state.player.is_sub,
                    self.game_state.player.server_id,
                    self._preferences,
                )
                if value > 0:
                    weights[gid] = value
        self._priority_resource_ids = tuple(sorted(weights, key=lambda gid: weights[gid], reverse=True)[:5])
        self._publish("Harvesting", reason, "Follow the route and reevaluate the zone.")
        rotate_at = monotonic() + self._preferences.rotation_minutes * 60 * random.uniform(0.75, 1.25)
        self.multi_farming_behavior.start(
            area_id=zone.area_id,
            sub_area_id=zone.sub_area_id,
            is_stopped_at_new_map_condition=lambda: (
                self._get_due_activity() is not None or monotonic() >= rotate_at or self._targets_completed()
            ),
            target_resource_item_ids=(
                set(self._preferences.target_resource_ids)
                if self._preferences.goal is HarvestGoal.TARGETS
                else None
            ),
            callback=self.on_multi_farming_behavior_finished,
            parent=self,
        )

    def _set_zone(self, zone: AreaInfo | None) -> None:
        if zone != self._selected_zone:
            self._zone_started_at = monotonic()
            self._priority_resource_ids = ()
        self._selected_zone = zone
        if zone is not None:
            player = self.game_state.player
            key = player.server_id, player.character_id
            self._registered_zone = key, zone
            CURRENT_AREAS_PLAYING_INFOS_BY_SERVER_AND_CHARACTER[key] = zone
            self._previous_area_info_played.append(zone)

    def play_multi_farming(self) -> None:
        self._recovering_since = None
        if self._targets_completed():
            return self.finish("The requested resource quantities are complete.")
        with AREA_CHOICE_LOCK:
            self._release_zone()
            zone, reason = self._select_zone()
            self._set_zone(zone)
        if zone is None:
            return self._on_route_failure(RouteFailure(reason))
        self._start_harvesting_zone(zone, reason)

    def _retry_zone(self, zone: AreaInfo) -> None:
        self._travel_plans.pop(zone, None)
        with AREA_CHOICE_LOCK:
            self._set_zone(zone)
        self._start_harvesting_zone(zone, "Retrying the same zone after waiting.")

    def _on_route_failure(self, reason: RouteFailure) -> None:
        self._release_zone()
        zone = self._selected_zone
        action = self._preferences.on_route_failure
        if action is RouteFailureAction.WAIT and zone is not None:
            self._publish("Waiting", reason, "Retry the same zone after the configured delay.")
            return self.run_timer(self._preferences.retry_seconds, lambda: self._retry_zone(zone))
        if action is RouteFailureAction.WAIT and zone is None:
            self._publish("Waiting", reason, "Look for a zone again after the configured delay.")
            return self.run_timer(self._preferences.retry_seconds, self.play_multi_farming)
        if action is RouteFailureAction.CHANGE_AREA and zone is not None:
            self._failed_zones[(zone.area_id, zone.sub_area_id)] = (
                monotonic() + self._preferences.zone_cooldown_minutes * 60
            )
            self._publish("Changing zone", reason, "Look for another eligible zone.")
            return self.run_timer(0, self.play_multi_farming)
        if action is RouteFailureAction.CHANGE_AREA and self._failed_zones:
            delay = max(1, min(self._failed_zones.values()) - monotonic())
            self._publish("Waiting", reason, "Wait for a failed zone to become eligible again.")
            return self.run_timer(delay, self.play_multi_farming)
        self.finish(reason)

    def on_multi_farming_behavior_finished(self, error_code: str | None) -> None:
        if error_code in (RouteFailure.NO_RESOURCES, RouteFailure.LOW_PRODUCTIVITY):
            return self._on_route_failure(RouteFailure(error_code))
        if error_code == AutoTripErrorCode.PATH_NOT_FOUND:
            return self._on_route_failure(RouteFailure.NO_ROUTE)
        if error_code is BaseFarmingErrorCode.STOP_CONDITION_TRIGGERED:
            due_activity = self._get_due_activity()
            if due_activity is not None:
                return self._start_session_activity(due_activity)
            return self.run_timer(HumanTimingsService().get_timing_base_action(), self.play_multi_farming)
        if error_code in {EnterBankChestErrorCode.NOT_ENOUGH_KAMAS, SaleHotelErrorCode.NOT_ENOUGH_KAMAS}:
            self.logger.info("Not enough kamas for bank: switching to fighter")
            return self.run_timer(HumanTimingsService().get_timing_base_action(), self.play_fighter)
        self.finish(error_code)

    def play_fighter(self) -> None:
        if (
            not self._preferences.recovery_combat
            or not self.game_state.settings.do_fighter
            or not (self.game_state.player.is_sub or self.game_state.player.is_former_sub)
        ):
            return self.finish("The inventory cannot be unloaded. Check bank access and kamas.")
        now = monotonic()
        if self._recovering_since is None:
            self._recovering_since = now
        if now - self._recovering_since >= self._preferences.recovery_combat_minutes * 60:
            return self.finish("Combat did not recover bank access within the configured time.")
        if self._selected_zone is None:
            with AREA_CHOICE_LOCK:
                zone, _ = self._select_zone()
                self._set_zone(zone)
        if self._selected_zone is None:
            return self._on_route_failure(RouteFailure.NO_ZONE)
        if not self._zone_has_maps(self._selected_zone):
            return self._on_route_failure(RouteFailure.NO_ROUTE)
        self._publish(
            "Combat", "The inventory cannot be unloaded right now.", "Recheck whether harvesting can resume."
        )
        self.fighter_behavior.start(
            area_id=self._selected_zone.area_id,
            sub_area_id=self._selected_zone.sub_area_id,
            is_stopped_at_new_map_condition=lambda: (
                self.game_state.inventory.can_use_bank
                or monotonic() - now >= self._preferences.recovery_combat_minutes * 60
            ),
            callback=self.on_fighter_behavior_finished,
            parent=self,
        )

    def _targets_completed(self) -> bool:
        if self._preferences.goal is not HarvestGoal.TARGETS or not self._preferences.target_quantity:
            return False
        stock = self.game_state.inventory.get_harvest_stock_by_gid()
        return all(
            gid in stock and stock[gid].item.quantity >= self._preferences.target_quantity
            for gid in self._preferences.target_resource_ids
        )

    def on_fighter_behavior_finished(self, error_code: str | None) -> None:
        if error_code == AutoTripErrorCode.PATH_NOT_FOUND:
            return self._on_route_failure(RouteFailure.NO_ROUTE)
        if error_code == BaseFarmingErrorCode.STOP_CONDITION_TRIGGERED:
            if not self.game_state.inventory.can_use_bank:
                return self.finish("Combat did not recover bank access within the configured time.")
            return self.play()
        self.finish(error_code)

    def finish(self, error_code: str | None = None, *args: object, **kwargs: object) -> None:
        if self.state is BehaviorState.RUNNING:
            self._publish("Stopped", error_code or "The activity finished.", "Press Play to start again.")
        super().finish(error_code, *args, **kwargs)
