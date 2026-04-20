import numpy as np
from skyfield.api import EarthSatellite, wgs84, load


def compute_passes(satellite, ground_station, hours=24, step_seconds=30):
    """Compute visible passes for a satellite over a ground station.

    Parameters
    ----------
    satellite : Satellite
        Object with tle1, tle2, name attributes.
    ground_station : GroundStation
        Object with lat, lon, alt_m, min_elevation_deg attributes.
    hours : float
        Time span to search for passes (from now), in hours.
    step_seconds : float
        Time step for sampling, in seconds.

    Returns
    -------
    list[dict]
        Each dict contains:
        - aos, los, tca (datetime)
        - max_elevation_deg, duration_min (float)
        - time (list[datetime])
        - elevation_deg, azimuth_deg (list[float])
        - range_km (list[float])
        - sub_lat_deg, sub_lon_deg (ground track)
    """
    ts = load.timescale()
    sat = EarthSatellite(satellite.tle1, satellite.tle2, satellite.name, ts)

    # Ground station geographic position
    gs_geo = wgs84.latlon(
        ground_station.lat,
        ground_station.lon,
        elevation_m=ground_station.alt_m,
    )

    # Time grid
    t0 = ts.now()
    times = ts.utc(
        t0.utc_datetime().year,
        t0.utc_datetime().month,
        t0.utc_datetime().day,
        t0.utc_datetime().hour,
        t0.utc_datetime().minute,
        np.arange(0, hours * 3600, step_seconds),
    )

    # Satellite geocentric position
    sat_at = sat.at(times)

    # Ground station geocentric position at each time
    gs_at = gs_geo.at(times)

    # Sub-satellite point (ground track)
    subpoints = wgs84.subpoint(sat_at)
    sub_lat = subpoints.latitude.degrees
    sub_lon = subpoints.longitude.degrees

    # Topocentric relative to ground station
    topocentric = sat_at - gs_at
    alt, az, distance = topocentric.altaz()

    elev = alt.degrees
    az_deg = az.degrees
    rng_km = distance.km

    passes = []
    above = elev >= ground_station.min_elevation_deg
    start_idx = None

    for i in range(len(elev)):
        if above[i] and start_idx is None:
            # Rising through elevation mask
            start_idx = i

        if (not above[i] or i == len(elev) - 1) and start_idx is not None:
            # Falling below mask: last valid point is i-1; at final sample: include i
            end_idx = i - 1 if not above[i] else i
            idx = slice(start_idx, end_idx + 1)

            elev_seg = elev[idx]
            az_seg = az_deg[idx]
            rng_seg = rng_km[idx]
            t_seg = times[idx]
            lat_seg = sub_lat[idx]
            lon_seg = sub_lon[idx]

            max_idx = int(np.argmax(elev_seg))

            passes.append(
                {
                    "aos": t_seg[0].utc_datetime(),
                    "los": t_seg[-1].utc_datetime(),
                    "tca": t_seg[max_idx].utc_datetime(),
                    "max_elevation_deg": float(elev_seg[max_idx]),
                    "duration_min": (
                        t_seg[-1].utc_datetime() - t_seg[0].utc_datetime()
                    ).total_seconds()
                    / 60.0,
                    "time": [x.utc_datetime() for x in t_seg],
                    "elevation_deg": elev_seg.tolist(),
                    "azimuth_deg": az_seg.tolist(),
                    "range_km": rng_seg.tolist(),
                    "sub_lat_deg": lat_seg.tolist(),
                    "sub_lon_deg": lon_seg.tolist(),
                }
            )
            start_idx = None

    return passes