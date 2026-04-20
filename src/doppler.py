import numpy as np

def compute_doppler(frequency_mhz, range_km_series, time_series):
    c = 299792.458
    rng = np.array(range_km_series)
    dt = np.array([(t - time_series[0]).total_seconds() for t in time_series])
    if len(dt) < 2:
        return [0.0]
    dr_dt = np.gradient(rng, dt)
    radial_km_s = dr_dt
    doppler_hz = -(radial_km_s / c) * frequency_mhz * 1e6
    return doppler_hz.tolist()