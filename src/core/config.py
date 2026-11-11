import datetime
from random import uniform
from enum import StrEnum
from typing import Self

from utils.language import GameLanguage

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator

from DBDofusUnity.dofus_unity_reader.game_constants.job import JobEnum
from DBDofusUnity.dofus_unity_reader.game_constants.map_id import MapIdEnum
from src.utils.project_paths import ENV_PATH, IS_PACKAGED
from utils.env_config import get_bool_from_env

load_dotenv(ENV_PATH)
DEBUG = get_bool_from_env("DEBUG", default=True)
ENABLE_MSG_CAPTURE = not IS_PACKAGED

ENABLE_SESSION_CONTEXT = False


class BehaviorSettings(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    do_fighter: bool = True
    do_sale_hotel: bool = True
    do_craft: bool = False
    do_use_guild_chest: bool = False
    do_dungeon: bool = False
    do_idle: bool = False
    enable_auto_equipment_market_purchases: bool = False
    enable_auto_ogrine_subscriptions: bool = False
    enable_auto_paysafecard_subscriptions: bool = False


class RouteFailureAction(StrEnum):
    STOP = "stop"
    WAIT = "wait"
    CHANGE_AREA = "change_area"


class HarvestGoal(StrEnum):
    BALANCED = "balanced"
    PROFIT = "profit"
    EXPERIENCE = "experience"
    TARGETS = "targets"


class ConfigurableAutoSettings(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    area_id: int | None = None
    sub_area_id: int | None = None
    on_route_failure: RouteFailureAction = RouteFailureAction.STOP
    goal: HarvestGoal = HarvestGoal.BALANCED
    target_resource_ids: tuple[int, ...] = ()
    target_quantity: int = Field(default=0, ge=0, le=1_000_000)
    price_half_life_hours: int = Field(default=168, ge=1, le=8760)
    rotation_minutes: int = Field(default=60, ge=5, le=240)
    minimum_stay_minutes: int = Field(default=10, ge=0, le=240)
    minimum_improvement_percent: int = Field(default=20, ge=0, le=500)
    candidate_quality_percent: int = Field(default=80, ge=1, le=100)
    empty_map_limit: int = Field(default=5, ge=1, le=100)
    productivity_window_minutes: int = Field(default=10, ge=1, le=120)
    minimum_collections_per_minute: float = Field(default=0.2, ge=0, le=60)
    retry_seconds: int = Field(default=60, ge=5, le=3600)
    zone_cooldown_minutes: int = Field(default=15, ge=1, le=240)
    reserve_kamas: int = Field(default=1000, ge=0, le=10_000_000)
    maximum_zaap_cost: int = Field(default=2000, ge=0, le=100_000)
    seconds_per_map: int = Field(default=15, ge=1, le=120)
    teleport_seconds: int = Field(default=30, ge=1, le=300)
    travel_value_per_minute: int = Field(default=1000, ge=1, le=1_000_000)
    discover_zaaps: bool = False
    occasional_combat: bool = True
    combat_interval_minutes: int = Field(default=20, ge=1, le=240)
    recovery_combat: bool = False
    recovery_combat_minutes: int = Field(default=5, ge=1, le=30)

    @model_validator(mode="after")
    def validate_zone(self) -> Self:
        if self.sub_area_id is not None and self.area_id is None:
            raise ValueError("A subarea requires an area.")
        if self.minimum_stay_minutes > self.rotation_minutes:
            raise ValueError("Minimum stay cannot exceed the rotation interval.")
        if any(resource_id <= 0 for resource_id in self.target_resource_ids):
            raise ValueError("Resource identifiers must be positive.")
        if self.goal is HarvestGoal.TARGETS and not self.target_resource_ids:
            raise ValueError("Select at least one target resource.")
        return self


class DungeonSettings(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    dungeon_id: int | None = Field(default=None, gt=0)
    follow_sequence: bool = False
    sequence: tuple[int, ...] = ()

    @model_validator(mode="after")
    def validate_sequence(self) -> Self:
        if any(dungeon_id <= 0 for dungeon_id in self.sequence):
            raise ValueError("Dungeon identifiers must be positive.")
        if self.follow_sequence and not self.sequence:
            raise ValueError("Add at least one dungeon to the sequence.")
        return self


class GlobalSettings(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    behaviors: BehaviorSettings = BehaviorSettings()
    enable_account_automation: bool = False
    language: GameLanguage = "fr"
    sonji_api_key: str | None = None
    configurable_auto_by_account: dict[str, ConfigurableAutoSettings] = Field(default_factory=dict)
    dungeons_by_account: dict[str, DungeonSettings] = Field(default_factory=dict)


FIGHT_GROUP_LVL_MULTIPLIER = 2
FIGHT_GROUP_LVL_OFFSET = 5


def get_default_fight_group_lvl_limit(level: int) -> float:
    return level * FIGHT_GROUP_LVL_MULTIPLIER + FIGHT_GROUP_LVL_OFFSET


USEFUL_UNLOAD = 0.15

OCCUPIED_MESSAGE_ID: int = 474
OCCUPIED_STUCK_LIMIT = 2

BOT_MINIMAL_KAMAS: int = 2_000_000
MULE_BANK_MAP_ID = MapIdEnum.ASTRUB_BANK

MAX_QUANTITY_ON_SELL = 10_000
MIN_KAMAS_TO_GO_SALE_HOTEL = 1_500


def get_time_beween_sale_hotel_prices():
    return datetime.timedelta(hours=4, minutes=0) * uniform(0.75, 1.25)


def get_time_between_attacker(enabled: bool) -> datetime.timedelta:
    return (
        datetime.timedelta(minutes=20) * uniform(0.75, 1.25)
        if enabled
        else datetime.timedelta(datetime.MAXYEAR)
    )


WEIGHT_BY_JOB: dict[JobEnum, float] = {
    JobEnum.MINER: 5,
    JobEnum.WOODCUTTER: 5,
    JobEnum.ALCHEMIST: 5,
    JobEnum.FISHERMAN: 5,
    JobEnum.PEASANT: 2.5,
    JobEnum.BASE: 1,
}


BETWEEN_COLLECT_PAUSE_PROBABILITY = 0.1
FIRST_COLLECT_MOVEMENT_CANCEL_PROBABILITY = 1 / 3
SUBSEQUENT_COLLECT_MOVEMENT_CANCEL_PROBABILITY = 1 / 8
STATIC_INTERACTION_CANCEL_PROBABILITY = 1 / 8

PLACEMENT_REPOSITIONING_PROBABILITY = 0.08
PLACEMENT_NON_OPTIMAL_MOVE_PROBABILITY = 0.1
