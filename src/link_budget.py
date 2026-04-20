import numpy as np


def compute_link_budget(link_profile, frequency_mhz, range_km, extra_loss_db: float = 0.0):
    """Single-point link budget with optional extra loss (dB)."""
    fspl_db = 92.45 + 20 * np.log10(frequency_mhz) + 20 * np.log10(range_km)
    total_loss_db = fspl_db + extra_loss_db

    pr_dbw = (
        link_profile.tx_power_dbw
        + link_profile.tx_gain_dbi
        + link_profile.rx_gain_dbi
        - total_loss_db
    )

    k_dbw_per_hz_k = -228.6
    n_dbw = (
        k_dbw_per_hz_k
        + 10 * np.log10(link_profile.system_temp_k)
        + 10 * np.log10(link_profile.bandwidth_hz)
    )
    snr_db = pr_dbw - n_dbw
    ebno_db = snr_db + 10 * np.log10(
        link_profile.bandwidth_hz / link_profile.data_rate_bps
    )

    return {
        "fspl_db": float(fspl_db),
        "extra_loss_db": float(extra_loss_db),
        "total_loss_db": float(total_loss_db),
        "pr_dbw": float(pr_dbw),
        "noise_dbw": float(n_dbw),
        "snr_db": float(snr_db),
        "ebno_db": float(ebno_db),
    }


def compute_link_budget_series(
    link_profile, frequency_mhz, range_km_series, extra_loss_db: float = 0.0
):
    """Link budget series over a pass with optional extra loss (dB)."""
    rng = np.array(range_km_series)
    fspl_db = 92.45 + 20 * np.log10(frequency_mhz) + 20 * np.log10(rng)
    total_loss_db = fspl_db + extra_loss_db

    pr_dbw = (
        link_profile.tx_power_dbw
        + link_profile.tx_gain_dbi
        + link_profile.rx_gain_dbi
        - total_loss_db
    )

    k_dbw_per_hz_k = -228.6
    n_dbw = (
        k_dbw_per_hz_k
        + 10 * np.log10(link_profile.system_temp_k)
        + 10 * np.log10(link_profile.bandwidth_hz)
    )
    snr_db = pr_dbw - n_dbw
    ebno_db = snr_db + 10 * np.log10(
        link_profile.bandwidth_hz / link_profile.data_rate_bps
    )

    return {
        "fspl_db": fspl_db.tolist(),
        "extra_loss_db": [float(extra_loss_db)] * len(rng),
        "total_loss_db": total_loss_db.tolist(),
        "pr_dbw": pr_dbw.tolist(),
        "noise_dbw": [float(n_dbw)] * len(rng),
        "snr_db": snr_db.tolist(),
        "ebno_db": ebno_db.tolist(),
    }