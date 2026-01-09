"""
Типы данных для Neura Protocol
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class Coordinates:
    x: int
    y: int
    _id: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Coordinates":
        return cls(
            x=data.get("x", 0),
            y=data.get("y", 0),
            _id=data.get("_id", ""),
        )


@dataclass
class PulseData:
    id: str
    is_collected: bool
    coordinates: Coordinates
    _id: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PulseData":
        return cls(
            id=data.get("id", ""),
            is_collected=data.get("isCollected", False),
            coordinates=Coordinates.from_dict(data.get("coordinates", {})),
            _id=data.get("_id", ""),
        )


@dataclass
class Pulses:
    first_collected_at: Optional[datetime]
    last_collected_at: Optional[datetime]
    data: List[PulseData]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Pulses":
        first_collected_at = None
        last_collected_at = None
        
        if data.get("firstCollectedAt"):
            try:
                first_collected_at = datetime.fromisoformat(
                    data["firstCollectedAt"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass
                
        if data.get("lastCollectedAt"):
            try:
                last_collected_at = datetime.fromisoformat(
                    data["lastCollectedAt"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass
                
        pulses_data = [PulseData.from_dict(item) for item in data.get("data", [])]
        return cls(
            first_collected_at=first_collected_at,
            last_collected_at=last_collected_at,
            data=pulses_data,
        )


@dataclass
class TradingVolume:
    month: float
    all_time: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradingVolume":
        return cls(
            month=data.get("month", 0.0),
            all_time=data.get("allTime", 0.0),
        )


@dataclass
class UserData:
    address: str
    neura_points: int
    trading_volume: TradingVolume
    pulses: Pulses
    social_accounts: List[Any]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserData":
        return cls(
            address=data.get("address", ""),
            neura_points=data.get("neuraPoints", 0),
            trading_volume=TradingVolume.from_dict(data.get("tradingVolume", {})),
            pulses=Pulses.from_dict(data.get("pulses", {})),
            social_accounts=data.get("socialAccounts", []),
        )
