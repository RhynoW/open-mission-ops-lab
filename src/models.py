from dataclasses import dataclass

@dataclass
class Satellite:
    name: str
    tle1: str
    tle2: str
    frequency_mhz: float = 437.0

@dataclass
class GroundStation:
    name: str
    lat: float
    lon: float
    alt_m: float = 0.0
    min_elevation_deg: float = 10.0

@dataclass
class LinkProfile:
    tx_power_dbw: float = 10.0
    tx_gain_dbi: float = 0.0
    rx_gain_dbi: float = 0.0
    bandwidth_hz: float = 125000.0
    data_rate_bps: float = 9600.0
    system_temp_k: float = 500.0

@dataclass
class Scenario:
    satellite: Satellite
    ground_station: GroundStation
    link: LinkProfile