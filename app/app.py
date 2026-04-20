import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import json
from pathlib import Path
from datetime import datetime, timedelta

import requests
import streamlit as st
from src.models import Satellite, GroundStation, LinkProfile, Scenario
from src.pass_calculator import compute_passes
from src.link_budget import compute_link_budget, compute_link_budget_series
from src.doppler import compute_doppler
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
import pandas as pd

st.set_page_config(page_title="Open Mission Ops Lab", layout="wide")
st.title("Open Mission Ops Lab v0.1")
st.caption("CubeSat access, Doppler, starter link budget, skyplot, ground track & 3D globe demo")

if "results" not in st.session_state:
    st.session_state.results = None

# --------------------------------------------------------------------
# Example scenario configuration
# --------------------------------------------------------------------

EXAMPLE_SCENARIOS = {
    "ISS over Taipei": "scenario_taipei_iss.json",
    "SSO EO 500km over Taipei": "scenario_taipei_sso_earth_obs.json",
    "UHF AMSAT over Taipei": "scenario_taipei_uhf_amsat.json",
}

CELESTRAK_TLE_URL = "https://celestrak.org/NORAD/elements/gp.php"


def load_example_scenario(filename: str):
    """Load example scenario JSON into session_state."""
    base_dir = Path(__file__).resolve().parents[1]
    scenario_path = base_dir / "examples" / filename
    if not scenario_path.exists():
        st.warning(f"Example scenario file not found: {scenario_path}")
        return

    with scenario_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    sat = data["satellite"]
    gs = data["ground_station"]
    link = data["link_profile"]

    st.session_state.example_sat_name = sat["name"]
    st.session_state.example_tle1 = sat["tle1"]
    st.session_state.example_tle2 = sat["tle2"]

    st.session_state.example_gs_name = gs["name"]
    st.session_state.example_lat = gs["lat"]
    st.session_state.example_lon = gs["lon"]
    st.session_state.example_alt_m = gs["alt_m"]
    st.session_state.example_min_el = gs["min_elevation_deg"]

    st.session_state.example_tx_power_dbw = link["tx_power_dbw"]
    st.session_state.example_tx_gain_dbi = link["tx_gain_dbi"]
    st.session_state.example_rx_gain_dbi = link["rx_gain_dbi"]
    st.session_state.example_bw = link["bandwidth_hz"]
    st.session_state.example_data_rate = link["data_rate_bps"]
    st.session_state.example_sys_temp = link["system_temp_k"]

    st.success(f"Loaded example: {sat['name']} over {gs['name']}")


def parse_tle_epoch(tle1: str) -> str:
    """Parse epoch from TLE line 1 and return ISO8601 string (UTC)."""
    try:
        year_str = tle1[18:20]
        day_str = tle1[20:32]
        year = int(year_str)
        year += 2000 if year < 57 else 1900  # TLE convention
        day_of_year = float(day_str)

        day_int = int(day_of_year)
        frac_day = day_of_year - day_int

        base_date = datetime(year, 1, 1)
        epoch_date = base_date + timedelta(days=day_int - 1 + frac_day)
        return epoch_date.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return "Unknown epoch"


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_tle_from_celestrak(norad_id: int):
    """Fetch latest TLE from CelesTrak for given NORAD ID (cached)."""
    try:
        params = {"CATNR": str(norad_id), "FORMAT": "TLE"}
        resp = requests.get(CELESTRAK_TLE_URL, params=params, timeout=5)
        resp.raise_for_status()
        lines = [ln.strip() for ln in resp.text.splitlines() if ln.strip()]
        if len(lines) < 3:
            raise ValueError("Unexpected TLE format from CelesTrak")
        name = lines[0]
        tle1 = lines[1]
        tle2 = lines[2]
        epoch_str = parse_tle_epoch(tle1)
        return name, tle1, tle2, epoch_str
    except Exception as e:
        raise RuntimeError(f"Failed to fetch TLE from CelesTrak: {e}")


# --------------------------------------------------------------------
# Sidebar: 太空通訊基礎知識
# --------------------------------------------------------------------

with st.sidebar:
    st.title("📡 太空通訊基礎知識")
    st.caption("Space Communications — Classroom Reference Guide")
    st.markdown("---")

    # ── Chapter 1 ──────────────────────────────────────────────────────
    with st.expander("1  Link Budget — 通訊收支總表", expanded=False):
        st.markdown(
            """
**定義**：Link Budget 是一張記錄訊號「收入」與「支出」的帳本，
用來預測接收端能否正確解調訊號。

| 項目 | 符號 | 典型單位 |
|------|------|----------|
| 發射功率 | $P_t$ | dBW |
| 發射天線增益 | $G_t$ | dBi |
| 自由空間損耗 | FSPL | dB |
| 接收天線增益 | $G_r$ | dBi |
| 系統雜訊 | $N$ | dBW |
| 訊雜比 | SNR / $E_b/N_0$ | dB |

**Link Budget 流程**：
```
Tx Power → (+) Tx Gain
         → (−) Free-Space Path Loss
         → (−) Extra Losses  (atm / rain / pol)
         → (+) Rx Gain
         → (−) Noise Power
         = SNR  →  Eb/N0  →  比較 Required Eb/N0
```
"""
        )

    # ── Chapter 2 ──────────────────────────────────────────────────────
    with st.expander("2  自由空間路徑損耗 (FSPL)", expanded=False):
        st.markdown("**公式**（Friis Free-Space Path Loss）：")
        st.latex(
            r"\mathrm{FSPL\,(dB)} = 92.45 "
            r"+ 20\log_{10}(f_{\mathrm{MHz}}) "
            r"+ 20\log_{10}(R_{\mathrm{km}})"
        )
        st.markdown(
            """
**變數說明**
- $f$：頻率（MHz）
- $R$：距離（km）
- 常數 92.45 由 $c = 3\times10^8$ m/s 推導而來

**數值直覺**（UHF 437 MHz）

| 距離 | FSPL |
|------|------|
| 500 km（LEO 天頂） | ≈ 147 dB |
| 1,000 km（低仰角） | ≈ 153 dB |
| 35,786 km（GEO） | ≈ 196 dB |

**重點**：距離加倍 → FSPL +6 dB；頻率加倍 → FSPL +6 dB。
"""
        )

    # ── Chapter 3 ──────────────────────────────────────────────────────
    with st.expander("3  接收功率方程式", expanded=False):
        st.markdown("**Friis Transmission Equation（dB 形式）**：")
        st.latex(
            r"P_r = P_t + G_t + G_r - \mathrm{FSPL} - L_{\mathrm{extra}}"
            r"\quad [\mathrm{dBW}]"
        )
        st.markdown(
            """
**各項說明**

| 符號 | 物理意義 | 正負影響 SNR |
|------|----------|-------------|
| $P_t$ | 發射功率 | 越大越好 ↑ |
| $G_t$ | 發射天線增益（定向性）| 越大越好 ↑ |
| $G_r$ | 接收天線增益 | 越大越好 ↑ |
| FSPL | 自由空間損耗 | 不可避免 ↓ |
| $L_{\\text{extra}}$ | 大氣、雨、極化損耗 | 可估算 ↓ |

**課堂計算範例**（ISS, 437 MHz, R = 800 km）
- $P_t$ = 1 W = 0 dBW
- $G_t = G_r$ = 0 dBi（全向天線）
- FSPL ≈ 149.7 dB
- $P_r$ ≈ 0 + 0 + 0 − 149.7 = **−149.7 dBW**
"""
        )

    # ── Chapter 4 ──────────────────────────────────────────────────────
    with st.expander("4  熱雜訊與系統雜訊溫度", expanded=False):
        st.markdown("**Johnson–Nyquist 熱雜訊功率**：")
        st.latex(r"N = k_B \, T_{\mathrm{sys}} \, B \quad [\mathrm{W}]")
        st.markdown("**dB 形式**：")
        st.latex(
            r"N\,[\mathrm{dBW}] = -228.6 "
            r"+ 10\log_{10}(T_{\mathrm{sys}}) "
            r"+ 10\log_{10}(B)"
        )
        st.markdown(
            """
**常數**：$k_B = 1.38\times10^{-23}$ J/K = −228.6 dBW/Hz/K

**系統雜訊溫度 $T_{\\mathrm{sys}}$ 的組成**

```
T_sys = T_sky + T_antenna + T_LNA + T_receiver
```
- $T_{\\text{sky}}$：天線指向天空的背景輻射（晴天 ≈ 50–100 K）
- $T_{\\text{LNA}}$：前級低雜訊放大器（優良 LNA ≈ 20–50 K）
- 本工具預設 $T_{\\text{sys}}$ = 500 K（典型業餘衛星地面站）

**數值範例**（$T_{\\text{sys}}$ = 500 K, $B$ = 125 kHz）：
- $N$ = −228.6 + 27.0 + 51.0 = **−150.6 dBW**
"""
        )

    # ── Chapter 5 ──────────────────────────────────────────────────────
    with st.expander("5  SNR 與 Eb/N0", expanded=False):
        st.latex(r"\mathrm{SNR\,(dB)} = P_r\,[\mathrm{dBW}] - N\,[\mathrm{dBW}]")
        st.latex(
            r"\frac{E_b}{N_0}\,[\mathrm{dB}] = \mathrm{SNR} "
            r"+ 10\log_{10}\!\left(\frac{B}{R_b}\right)"
        )
        st.markdown(
            """
**物理意義**

| 指標 | 意義 |
|------|------|
| SNR | 訊號 vs. 雜訊的功率比，與頻寬有關 |
| $E_b/N_0$ | 每 bit 能量 vs. 單邊雜訊密度，**與調變方式無關的通用指標** |

**關鍵關係**：
若 $B \gg R_b$（例如 LoRa 展頻），$E_b/N_0 \gg$ SNR，
代表可用較低 SNR 仍能可靠通訊。

**連結 BER**：AWGN 通道下 BPSK 的 BER：
"""
        )
        st.latex(r"\mathrm{BER} = Q\!\left(\sqrt{2\,E_b/N_0}\right)")
        st.markdown("$Q(x)$：互補誤差函數，$E_b/N_0$ 越高 → BER 越低。")

    # ── Chapter 6 ──────────────────────────────────────────────────────
    with st.expander("6  Link Margin 與可用時間", expanded=False):
        st.latex(
            r"\mathrm{Link\;Margin\,(dB)} = \frac{E_b}{N_0}\,[\text{actual}] "
            r"- \frac{E_b}{N_0}\,[\text{required}]"
        )
        st.markdown(
            """
**規則**
- Margin > 0 dB → 鏈路可靠（綠色區域）
- Margin < 0 dB → 鏈路中斷風險（紅色陰影區）
- 工程設計通常要求 Margin ≥ **3 dB**（考慮雨衰、指向誤差等不確定性）

**本工具圖形說明**

| 圖形元素 | 意義 |
|----------|------|
| 綠色曲線 | 實際 $E_b/N_0$ 隨時間變化 |
| 紅色虛線 | 設定的 Required $E_b/N_0$ |
| 紅色陰影 | Margin < 0，鏈路不可靠的時間段 |

**課堂練習**：把 Loss model 改成 *Rain fade (10 dB)*，
觀察 $E_b/N_0$ 曲線整體下移 10 dB，
並注意可用通訊時間百分比的變化。
"""
        )

    # ── Chapter 7 ──────────────────────────────────────────────────────
    with st.expander("7  Doppler 效應與頻率補償", expanded=False):
        st.latex(
            r"f_r = f_0 \cdot \frac{c \pm v_r}{c} "
            r"\approx f_0 \left(1 \pm \frac{v_r}{c}\right)"
        )
        st.markdown(
            """
**說明**
- $f_0$：標稱頻率；$v_r$：徑向速度（m/s）；$c$：光速
- 衛星接近時 $v_r > 0$ → 頻率升高；遠離時 → 頻率降低

**LEO 衛星典型值**（軌道速度 ≈ 7.8 km/s，UHF 437 MHz）

| 過頂階段 | 徑向速度 | Doppler 偏移 |
|----------|----------|--------------|
| AOS（出地平） | ≈ +5 km/s | ≈ +7.3 kHz |
| TCA（天頂） | ≈ 0 | ≈ 0 |
| LOS（入地平） | ≈ −5 km/s | ≈ −7.3 kHz |

**實務影響**：窄頻通訊（例如 9600 bps FSK）若不補償，
Doppler 偏移可能超過接收機的拉頻範圍，導致解調失敗。
"""
        )

    # ── Chapter 8 ──────────────────────────────────────────────────────
    with st.expander("8  額外損耗模型", expanded=False):
        st.markdown(
            """
**大氣吸收**（ITU-R P.676）

主要來源：氧氣（60 GHz 附近）與水蒸氣（22.2 GHz）。
UHF/L/S 頻段 < 1 GHz：大氣損耗通常 < 0.5 dB，可忽略。

**雨衰（ITU-R P.838）**
"""
        )
        st.latex(r"\gamma_R = k(f)\, R^{\alpha(f)} \quad [\mathrm{dB/km}]")
        st.latex(r"A_R = \gamma_R \cdot L_{\mathrm{eff}} \quad [\mathrm{dB}]")
        st.markdown(
            """
- $R$：降雨率（mm/hr）；$k, \\alpha$：ITU 頻率相關係數
- $L_{\\text{eff}}$：有效雨區路徑長度（取決於仰角與雨帶高度）

**頻段影響對照**

| 頻段 | 雨衰（中雨 10 mm/hr, 10° 仰角） |
|------|----------------------------------|
| UHF 437 MHz | < 0.1 dB |
| L-band 1.6 GHz | ≈ 0.3 dB |
| S-band 2.4 GHz | ≈ 0.5 dB |
| Ku-band 12 GHz | ≈ 5–10 dB |
| Ka-band 26 GHz | ≈ 15–30 dB |

**極化損耗**：天線極化不匹配（線偏 vs. 圓偏）典型損耗 1–3 dB。
"""
        )

    # ── Chapter 9 ──────────────────────────────────────────────────────
    with st.expander("9  調變方式與 Eb/N0 需求", expanded=False):
        st.markdown(
            "各種調變在 AWGN 通道、BER ≈ $10^{-5}$ 時所需的最低 $E_b/N_0$："
        )
        ebno_data = {
            "調變方式": [
                "BPSK", "QPSK", "8-PSK", "16-QAM", "64-QAM", "QPSK + Rate-1/2 FEC",
            ],
            "頻譜效率 (bit/s/Hz)": [1.0, 2.0, 3.0, 4.0, 6.0, 1.0],
            "所需 Eb/N0 (dB)": [9.5, 9.5, 12.0, 14.0, 18.0, 2.0],
            "適用場景": [
                "深空/低 SNR", "CubeSat 主流", "中速率衛星", "VSAT 下行", "寬頻地面網", "容錯鏈路",
            ],
        }
        st.dataframe(pd.DataFrame(ebno_data), use_container_width=True, hide_index=True)
        st.caption(
            "注意：加入前向糾錯碼（FEC）可將所需 Eb/N0 大幅降低，"
            "但代價是佔用更多頻寬或降低有效資料率。"
        )

    # ── Chapter 10 ─────────────────────────────────────────────────────
    with st.expander("10  即時參數面板（與主畫面同步）", expanded=True):
        current_loss_model = st.session_state.get("current_loss_model", "Free-space only")
        current_extra_loss_db = st.session_state.get("current_extra_loss_db", 0.0)
        current_required_ebno = st.session_state.get("current_required_ebno", 3.0)

        st.markdown("**目前選擇的設定**")
        st.markdown(
            f"| 設定項目 | 數值 |\n"
            f"|----------|------|\n"
            f"| Loss model | {current_loss_model} |\n"
            f"| Extra loss | {current_extra_loss_db:.1f} dB |\n"
            f"| Required Eb/N0 | {current_required_ebno:.1f} dB |"
        )
        st.markdown(
            """
**課堂互動建議**

1. 切換 Loss model → 觀察 Eb/N0 曲線整體平移
2. 調整 Required Eb/N0 → 觀察可用通訊時間百分比
3. 改變仰角門檻 → 觀察 Pass 次數與時長的取捨
4. 對比不同 TLE（不同軌道高度）→ 理解 FSPL 與過頂時間的關係
"""
        )

    st.markdown("---")
    st.caption(
        "參考標準：ITU-R P.676 / P.838 / P.618 | Proakis, *Digital Communications* | "
        "Wertz & Larson, *Space Mission Engineering*"
    )

# --------------------------------------------------------------------
# Top-level controls
# --------------------------------------------------------------------

col_btn1, col_btn2 = st.columns([2, 3])
with col_btn1:
    example_name = st.selectbox(
        "Example scenario",
        list(EXAMPLE_SCENARIOS.keys()),
        index=0,
    )
with col_btn2:
    if st.button("Load example"):
        filename = EXAMPLE_SCENARIOS[example_name]
        load_example_scenario(filename)

st.markdown("---")

col_tle1, col_tle2 = st.columns([1, 2])
with col_tle1:
    norad_id_str = st.text_input("NORAD ID for TLE fetch", "25544")
    valid_norad = norad_id_str.isdigit() and 1 <= len(norad_id_str) <= 5
with col_tle2:
    if st.button("Fetch TLE from CelesTrak"):
        if not valid_norad:
            st.error("Please enter a valid 1–5 digit NORAD ID.")
        else:
            try:
                norad_id = int(norad_id_str)
                name_fetched, tle1_fetched, tle2_fetched, epoch_str = fetch_tle_from_celestrak(
                    norad_id
                )
                st.session_state.example_sat_name = name_fetched
                st.session_state.example_tle1 = tle1_fetched
                st.session_state.example_tle2 = tle2_fetched
                st.success(
                    f"Fetched TLE for NORAD {norad_id}: {name_fetched} "
                    f"(epoch: {epoch_str})"
                )
                st.code(
                    f"{name_fetched}\n{tle1_fetched}\n{tle2_fetched}", language="text"
                )
            except RuntimeError as e:
                st.error(str(e))

st.markdown("---")

# --------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------

sat_default_name = st.session_state.get("example_sat_name", "ISS")
tle1_default = st.session_state.get(
    "example_tle1",
    "1 25544U 98067A   26109.54791667  .00016717  00000+0  29614-3 0  9991",
)
tle2_default = st.session_state.get(
    "example_tle2",
    "2 25544  51.6400  22.3050 0004100  79.2100 280.9300 15.50000000  1234",
)

gs_default_name = st.session_state.get("example_gs_name", "Taipei")
lat_default = st.session_state.get("example_lat", 25.0330)
lon_default = st.session_state.get("example_lon", 121.5654)
alt_default = st.session_state.get("example_alt_m", 10.0)
min_el_default = st.session_state.get("example_min_el", 10.0)

freq_default = st.session_state.get("example_freq_mhz", 437.0)
tx_default = st.session_state.get("example_tx_power_dbw", 10.0)
tx_gain_default = st.session_state.get("example_tx_gain_dbi", 0.0)
rx_gain_default = st.session_state.get("example_rx_gain_dbi", 0.0)
bw_default = st.session_state.get("example_bw", 125000.0)
dr_default = st.session_state.get("example_data_rate", 9600.0)
sys_temp_default = st.session_state.get("example_sys_temp", 500.0)

col1, col2 = st.columns(2)
with col1:
    tle1 = st.text_input("TLE Line 1", tle1_default)
    tle2 = st.text_input("TLE Line 2", tle2_default)
    sat_name = st.text_input("Satellite Name", sat_default_name)

with col2:
    gs_name = st.text_input("Ground Station Name", gs_default_name)
    lat = st.number_input("Latitude (deg)", value=float(lat_default), format="%.4f")
    lon = st.number_input("Longitude (deg)", value=float(lon_default), format="%.4f")
    alt_m = st.number_input("Altitude (m)", value=float(alt_default))
    min_el = st.slider(
        "Minimum Elevation (deg)", 0.0, 30.0, float(min_el_default), 1.0
    )

st.subheader("Link Profile")
lc1, lc2, lc3 = st.columns(3)
with lc1:
    frequency_mhz = st.number_input("Frequency (MHz)", value=float(freq_default), min_value=1.0)
    tx_power_dbw = st.number_input("Tx Power (dBW)", value=float(tx_default))
    tx_gain_dbi = st.number_input("Tx Gain (dBi)", value=float(tx_gain_default))
with lc2:
    rx_gain_dbi = st.number_input("Rx Gain (dBi)", value=float(rx_gain_default))
    bw = st.number_input("Bandwidth (Hz)", value=float(bw_default))
with lc3:
    data_rate = st.number_input("Data Rate (bps)", value=float(dr_default))
    sys_temp = st.number_input("System Temp (K)", value=float(sys_temp_default))

st.caption("Additional losses (education-level approximation)")

loss_col1, loss_col2 = st.columns([1, 1])
with loss_col1:
    loss_model = st.selectbox(
        "Additional loss model",
        [
            "Free-space only",
            "Atmospheric loss (3 dB)",
            "Rain fade (10 dB)",
            "Polarization loss (1 dB)",
            "Custom loss",
        ],
        index=0,
    )
with loss_col2:
    custom_loss_db = 0.0
    if loss_model == "Custom loss":
        custom_loss_db = st.number_input("Custom extra loss (dB)", value=0.0)

extra_loss_db = 0.0
if loss_model == "Atmospheric loss (3 dB)":
    extra_loss_db = 3.0
elif loss_model == "Rain fade (10 dB)":
    extra_loss_db = 10.0
elif loss_model == "Polarization loss (1 dB)":
    extra_loss_db = 1.0
elif loss_model == "Custom loss":
    extra_loss_db = custom_loss_db

st.session_state.current_loss_model = loss_model
st.session_state.current_extra_loss_db = float(extra_loss_db)

# --------------------------------------------------------------------
# Run computation (per-pass metrics + error handling)
# --------------------------------------------------------------------

if st.button("Run Demo"):
    try:
        sat = Satellite(sat_name, tle1, tle2, frequency_mhz=frequency_mhz)
        gs = GroundStation(gs_name, lat, lon, alt_m, min_el)
        link = LinkProfile(
            tx_power_dbw, tx_gain_dbi, rx_gain_dbi, bw, data_rate, sys_temp
        )
        scenario = Scenario(sat, gs, link)

        passes = compute_passes(scenario.satellite, scenario.ground_station)
    except Exception as e:
        st.error(
            f"Failed to compute passes. Please check TLE and inputs. Details: {e}"
        )
        st.session_state.results = None
    else:
        if passes:
            per_pass_metrics = []
            for p in passes:
                link_scalar = compute_link_budget(
                    scenario.link,
                    scenario.satellite.frequency_mhz,
                    max(p["range_km"]),
                    extra_loss_db=extra_loss_db,
                )
                link_series = compute_link_budget_series(
                    scenario.link,
                    scenario.satellite.frequency_mhz,
                    p["range_km"],
                    extra_loss_db=extra_loss_db,
                )
                doppler_series = compute_doppler(
                    scenario.satellite.frequency_mhz,
                    p["range_km"],
                    p["time"],
                )
                per_pass_metrics.append(
                    {
                        "link_scalar": link_scalar,
                        "link_series": link_series,
                        "doppler": doppler_series,
                    }
                )

            st.session_state.results = {
                "passes": passes,
                "per_pass_metrics": per_pass_metrics,
                "sat_name": sat_name,
                "gs_lat": lat,
                "gs_lon": lon,
                "gs_name": gs_name,
                "gs_alt_m": alt_m,
                "extra_loss_db": extra_loss_db,
                "loss_model": loss_model,
            }
            st.session_state.active_pass_index = 0
        else:
            st.warning("No visible passes found in the time window.")
            st.session_state.results = {
                "passes": [],
                "per_pass_metrics": [],
                "sat_name": sat_name,
                "gs_lat": lat,
                "gs_lon": lon,
                "gs_name": gs_name,
                "gs_alt_m": alt_m,
                "extra_loss_db": extra_loss_db,
                "loss_model": loss_model,
            }
            st.session_state.active_pass_index = 0

# --------------------------------------------------------------------
# Results
# --------------------------------------------------------------------

if st.session_state.results is not None:
    passes = st.session_state.results["passes"]
    per_pass_metrics = st.session_state.results["per_pass_metrics"]
    gs_lat = st.session_state.results["gs_lat"]
    gs_lon = st.session_state.results["gs_lon"]
    gs_name = st.session_state.results["gs_name"]
    gs_alt_m = st.session_state.results.get("gs_alt_m", 0.0)
    result_sat_name = st.session_state.results.get("sat_name", sat_name)
    extra_loss_db = st.session_state.results.get("extra_loss_db", 0.0)
    loss_model = st.session_state.results.get("loss_model", "Free-space only")

    if passes:
        pass_options = [
            f"Pass #{i+1} (AOS {p['aos'].strftime('%H:%M:%S')} UTC)"
            for i, p in enumerate(passes)
        ]
        default_index = st.session_state.get("active_pass_index", 0)
        default_index = min(default_index, len(pass_options) - 1)
        selected_label = st.selectbox(
            "Select pass to analyze", pass_options, index=default_index
        )
        active_idx = pass_options.index(selected_label)
        st.session_state.active_pass_index = active_idx
    else:
        active_idx = None

    tab_overview, tab_elev_dopp, tab_link, tab_skyplot, tab_map, tab_3d = st.tabs(
        ["Overview", "Elevation & Doppler", "Link & Eb/No", "Skyplot", "Map", "3D Globe"]
    )

    # --- Overview tab ---
    with tab_overview:
        if passes:
            df = pd.DataFrame(
                [
                    {
                        "AOS (UTC)": p["aos"],
                        "LOS (UTC)": p["los"],
                        "TCA (UTC)": p["tca"],
                        "Max Elevation (deg)": p["max_elevation_deg"],
                        "Duration (min)": p["duration_min"],
                    }
                    for p in passes
                ]
            )
            st.subheader("Pass summary")
            st.dataframe(df, use_container_width=True)

            csv_pass = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download pass summary (CSV)",
                data=csv_pass,
                file_name="pass_summary.csv",
                mime="text/csv",
            )

            if active_idx is not None and per_pass_metrics:
                first = passes[active_idx]
                metrics = per_pass_metrics[active_idx]
                link_scalar = metrics["link_scalar"]
                doppler_series = metrics["doppler"]
                link_series = metrics["link_series"]

                st.subheader("Mission KPI (selected pass)")
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Max Elevation (deg)", f"{first['max_elevation_deg']:.1f}")

                duration_min = first["duration_min"]
                duration_sec = duration_min * 60.0
                bits_max = data_rate * duration_sec
                kpi_eff = 0.7
                bits_eff = bits_max * kpi_eff
                mb_eff = bits_eff / 8.0 / 1e6

                k2.metric("Est. Data Volume (MB)", f"{mb_eff:.1f}")

                if doppler_series:
                    max_dopp = max(doppler_series)
                    min_dopp = min(doppler_series)
                    max_abs_dopp = max(abs(max_dopp), abs(min_dopp))
                else:
                    max_abs_dopp = 0.0
                k3.metric("Max |Doppler| (Hz)", f"{max_abs_dopp:.0f}")

                req_ebno_for_kpi = st.session_state.get("current_required_ebno", 3.0)
                ebno_arr_kpi = pd.Series(link_series["ebno_db"])
                if len(ebno_arr_kpi) > 0:
                    avail_mask = ebno_arr_kpi >= req_ebno_for_kpi
                    availability = avail_mask.sum() / len(ebno_arr_kpi)
                else:
                    availability = 0.0
                k4.metric("Link Availability (%)", f"{availability * 100.0:.1f}")

                st.caption(
                    f"KPI 假設：效率 {kpi_eff:.2f}，Required Eb/No {req_ebno_for_kpi:.1f} dB"
                )
                st.caption(f"Loss model: {loss_model}, Extra loss = {extra_loss_db:.1f} dB")
        else:
            st.warning(
                "No pass found for the current setup. Try a lower elevation mask or different TLE."
            )

    if passes and active_idx is not None and per_pass_metrics:
        p0 = passes[active_idx]
        metrics = per_pass_metrics[active_idx]
        link_series = metrics["link_series"]
        doppler = metrics["doppler"]

        # --- Elevation & Doppler tab ---
        with tab_elev_dopp:
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(
                go.Scatter(
                    x=p0["time"],
                    y=p0["elevation_deg"],
                    name="Elevation (deg)",
                ),
                secondary_y=False,
            )
            fig.add_trace(
                go.Scatter(
                    x=p0["time"],
                    y=doppler,
                    name="Doppler (Hz)",
                    line=dict(color="orange"),
                ),
                secondary_y=True,
            )
            fig.update_layout(title_text="Pass Elevation & Doppler")
            fig.update_xaxes(title_text="Time (UTC)")
            fig.update_yaxes(title_text="Elevation (deg)", secondary_y=False)
            fig.update_yaxes(title_text="Doppler (Hz)", secondary_y=True)
            st.plotly_chart(fig, use_container_width=True)

        # --- Link & Eb/No tab ---
        with tab_link:
            fig_snr = make_subplots(specs=[[{"secondary_y": True}]])
            fig_snr.add_trace(
                go.Scatter(
                    x=p0["time"],
                    y=link_series["snr_db"],
                    name="SNR (dB)",
                ),
                secondary_y=False,
            )
            fig_snr.add_trace(
                go.Scatter(
                    x=p0["time"],
                    y=link_series["ebno_db"],
                    name="Eb/No (dB)",
                    line=dict(color="green"),
                ),
                secondary_y=True,
            )

            required_ebno = st.slider(
                "Required Eb/No (dB)",
                0.0,
                15.0,
                st.session_state.get("current_required_ebno", 3.0),
                0.5,
                key="required_ebno_slider",
            )
            st.session_state.current_required_ebno = float(required_ebno)

            fig_snr.add_hline(
                y=required_ebno,
                line=dict(color="red", dash="dash"),
                secondary_y=True,
            )

            ebno_arr = pd.Series(link_series["ebno_db"])
            margin_arr = ebno_arr - required_ebno

            if (margin_arr < 0).any():
                fig_snr.add_shape(
                    type="rect",
                    xref="x",
                    yref="y2",
                    x0=min(p0["time"]),
                    x1=max(p0["time"]),
                    y0=min(min(ebno_arr.min(), required_ebno) - 1, required_ebno - 5),
                    y1=required_ebno,
                    fillcolor="rgba(255, 0, 0, 0.1)",
                    line=dict(width=0),
                )

            fig_snr.update_layout(title_text="SNR / EbNo over Pass")
            fig_snr.update_xaxes(title_text="Time (UTC)")
            fig_snr.update_yaxes(title_text="SNR (dB)", secondary_y=False)
            fig_snr.update_yaxes(title_text="Eb/No (dB)", secondary_y=True)
            st.plotly_chart(fig_snr, use_container_width=True)

            df_series = pd.DataFrame(
                {
                    "time_utc": p0["time"],
                    "elevation_deg": p0["elevation_deg"],
                    "range_km": p0["range_km"],
                    "snr_db": link_series["snr_db"],
                    "ebno_db": link_series["ebno_db"],
                    "extra_loss_db": link_series["extra_loss_db"],
                    "total_loss_db": link_series["total_loss_db"],
                }
            )
            csv_series = df_series.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download time series (CSV)",
                data=csv_series,
                file_name="pass_timeseries.csv",
                mime="text/csv",
            )

            duration_min_sel = p0["duration_min"]
            duration_sec = duration_min_sel * 60.0
            bits_max = data_rate * duration_sec

            eff = st.slider(
                "Downlink efficiency",
                0.1,
                1.0,
                0.7,
                0.05,
                key="efficiency_slider",
            )
            bits_eff = bits_max * eff
            mb_eff = bits_eff / 8.0 / 1e6

            st.info(
                f"Estimated downlink per selected pass ≈ {mb_eff:.1f} MB "
                f"(duration {duration_min_sel:.1f} min, data_rate {data_rate:.0f} bps, "
                f"efficiency {eff:.2f}, extra loss {extra_loss_db:.1f} dB)"
            )

        # --- Skyplot tab ---
        with tab_skyplot:
            elev = p0["elevation_deg"]
            az = p0.get("azimuth_deg", None)

            if az is None:
                st.warning("No azimuth data available in pass structure.")
            else:
                r = [90.0 - e for e in elev]

                fig_sky = go.Figure()
                fig_sky.add_trace(
                    go.Scatterpolar(
                        r=r,
                        theta=az,
                        mode="lines+markers",
                        name="Pass Track",
                    )
                )
                fig_sky.update_layout(
                    title="Skyplot (Azimuth vs Elevation)",
                    polar=dict(
                        radialaxis=dict(
                            title="Zenith angle (deg)",
                            range=[0, 90],
                            tickvals=[0, 30, 60, 90],
                            ticktext=["Zenith", "60°", "30°", "Horizon"],
                        ),
                        angularaxis=dict(
                            direction="clockwise",
                            rotation=0,
                            tickvals=[0, 90, 180, 270],
                            ticktext=["N", "E", "S", "W"],
                        ),
                    ),
                    showlegend=False,
                )
                st.plotly_chart(fig_sky, use_container_width=True)

        # --- Map tab ---
        with tab_map:
            lat_track = p0.get("sub_lat_deg", None)
            lon_track = p0.get("sub_lon_deg", None)

            if lat_track is None or lon_track is None:
                st.warning("No ground track data available.")
            else:
                df_map = pd.DataFrame(
                    {
                        "lat": lat_track,
                        "lon": lon_track,
                    }
                )
                df_gs = pd.DataFrame(
                    {
                        "lat": [gs_lat],
                        "lon": [gs_lon],
                        "name": [gs_name],
                    }
                )

                st.subheader("Ground track (selected pass)")
                fig_map = px.scatter_mapbox(
                    df_map,
                    lat="lat",
                    lon="lon",
                    zoom=1,
                    height=500,
                    mapbox_style="carto-positron",
                )
                fig_map.add_trace(
                    go.Scattermapbox(
                        lat=df_gs["lat"],
                        lon=df_gs["lon"],
                        mode="markers+text",
                        marker=dict(size=10, color="red"),
                        text=[gs_name],
                        textposition="top right",
                        name="Ground Station",
                    )
                )
                st.plotly_chart(fig_map, use_container_width=True)

        # --- 3D Globe tab ---
        with tab_3d:
            st.markdown("#### Cesium 3D Globe")
            enable_3d = st.checkbox("Generate Cesium 3D view", value=True)

            if enable_3d:
                orbit_data = {
                    "satellite": {"name": result_sat_name},
                    "ground_station": {
                        "name": gs_name,
                        "lat_deg": gs_lat,
                        "lon_deg": gs_lon,
                        "alt_m": gs_alt_m,
                    },
                    "pass": {
                        "aos_utc": p0["aos"].isoformat(),
                        "los_utc": p0["los"].isoformat(),
                        "tca_utc": p0["tca"].isoformat(),
                        "max_elevation_deg": p0["max_elevation_deg"],
                        "duration_sec": p0["duration_min"] * 60.0,
                    },
                    "track": [
                        {
                            "time_utc": t.isoformat(),
                            "sub_lat_deg": float(phi),
                            "sub_lon_deg": float(lam),
                            "elevation_deg": float(el),
                        }
                        for t, phi, lam, el in zip(
                            p0["time"],
                            p0["sub_lat_deg"],
                            p0["sub_lon_deg"],
                            p0["elevation_deg"],
                        )
                    ],
                }

                static_dir = Path(__file__).parent / "static"
                static_dir.mkdir(parents=True, exist_ok=True)
                html_path = static_dir / "orbit_3d_view.html"

                orbit_json_str = json.dumps(orbit_data)

                cesium_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Orbit 3D View</title>
  <script src="https://cdn.jsdelivr.net/npm/cesium@1.140.0/Build/Cesium/Cesium.js"></script>
  <link href="https://cdn.jsdelivr.net/npm/cesium@1.140.0/Build/Cesium/Widgets/widgets.css" rel="stylesheet">
  <style>
    html, body, #cesiumContainer {{
      width: 100%; height: 100%;
      margin: 0; padding: 0;
      overflow: hidden;
      background: #000;
    }}
    #satInfo {{
      position: absolute;
      top: 10px; right: 10px;
      z-index: 10;
      background: rgba(0,0,0,0.65);
      color: #eee;
      padding: 10px 14px;
      border-radius: 6px;
      font-family: "Courier New", monospace;
      font-size: 12px;
      max-width: 280px;
      border: 1px solid #444;
    }}
  </style>
</head>
<body>
  <div id="cesiumContainer"></div>
  <div id="satInfo">Loading...</div>

  <script>
    const CESIUM_CDN = "https://cdn.jsdelivr.net/npm/cesium@1.140.0/Build/Cesium/";
    window.CESIUM_BASE_URL = CESIUM_CDN;
    (function() {{
      const _Blob = window.Blob;
      window.Blob = function(parts, opts) {{
        if (Array.isArray(parts) && parts.length === 1 && typeof parts[0] === 'string') {{
          const s = parts[0];
          if (s.includes('importScripts') && !s.includes('http')) {{
            const fixed = s.replace(
              /importScripts\s*\(\s*['"]([^'"./][^'"]*)['"]\s*\)/g,
              (_, n) => "importScripts('" + CESIUM_CDN + "Workers/" + n + ".js')"
            );
            return new _Blob([fixed], opts);
          }}
        }}
        return new _Blob(parts, opts);
      }};
      window.Blob.prototype = _Blob.prototype;
    }})();

    Cesium.Ion.defaultAccessToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiIxNDY3NzlmZi00YjUyLTQ1OTUtYTNhYi03MzQ2YTAzODRiNzQiLCJpZCI6MTE3ODQsImlhdCI6MTc3NDc5OTA3OH0.NO0-3a2HXo7Id7B4iAoed9AvP7I6g9Ufo9n9smnL1-k';
    Cesium.buildModuleUrl.setBaseUrl(CESIUM_CDN);

    window.ORBIT_DATA = {orbit_json_str};

    const viewer = new Cesium.Viewer('cesiumContainer', {{
      terrainProvider: new Cesium.EllipsoidTerrainProvider(),
      baseLayer: Cesium.ImageryLayer.fromProviderAsync(
        Cesium.IonImageryProvider.fromAssetId(3)
      ),
      animation: false,
      timeline: false,
      baseLayerPicker: false,
      geocoder: false,
      homeButton: true,
      sceneModePicker: false,
      navigationHelpButton: false,
      fullscreenButton: false,
      selectionIndicator: false,
      infoBox: false,
    }});

    const infoDiv = document.getElementById('satInfo');

    (function render() {{
      const d  = window.ORBIT_DATA;
      if (!d || !Array.isArray(d.track) || d.track.length === 0) {{
        infoDiv.textContent = 'No track data.';
        return;
      }}

      const satName  = (d.satellite && d.satellite.name) || 'Satellite';
      const gs       = d.ground_station || {{}};
      const passInfo = d.pass || {{}};

      const positions = [];
      d.track.forEach(p => positions.push(
        Number(p.sub_lon_deg), Number(p.sub_lat_deg), 400000
      ));

      const trackEntity = viewer.entities.add({{
        name: satName + ' ground track',
        polyline: {{
          positions: Cesium.Cartesian3.fromDegreesArrayHeights(positions),
          width: 2.5,
          material: new Cesium.PolylineGlowMaterialProperty({{
            glowPower: 0.2,
            color: Cesium.Color.CYAN,
          }}),
          clampToGround: false,
        }},
      }});

      if (typeof gs.lon_deg === 'number' && typeof gs.lat_deg === 'number') {{
        viewer.entities.add({{
          name: gs.name || 'GS',
          position: Cesium.Cartesian3.fromDegrees(gs.lon_deg, gs.lat_deg, gs.alt_m || 0),
          point: {{
            pixelSize: 10,
            color: Cesium.Color.YELLOW,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
          }},
          label: {{
            text: gs.name || 'GS',
            font: '13px sans-serif',
            fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            pixelOffset: new Cesium.Cartesian2(0, -20),
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          }},
        }});
      }}

      viewer.zoomTo(trackEntity);

      const fmt = v => typeof v === 'number' ? v.toFixed(1) : 'N/A';
      infoDiv.innerHTML =
        '<b>' + satName + '</b><br>' +
        'GS: ' + (gs.name || '—') +
          ' (' + (gs.lat_deg||'?') + '°, ' + (gs.lon_deg||'?') + '°)<br>' +
        'AOS: ' + (passInfo.aos_utc || '—') + '<br>' +
        'LOS: ' + (passInfo.los_utc || '—') + '<br>' +
        'Max El: ' + fmt(passInfo.max_elevation_deg) + '°<br>' +
        'Duration: ' + (passInfo.duration_sec ? (passInfo.duration_sec/60).toFixed(1) + ' min' : 'N/A');
    }})();
  </script>
</body>
</html>"""

                try:
                    html_path.write_text(cesium_html, encoding="utf-8")
                except Exception as e:
                    st.error(f"Failed to write orbit_3d_view.html: {e}")
                    st.stop()

                try:
                    host = st.context.headers.get("host", "localhost:8501")
                    scheme = "http" if "localhost" in host or "127.0.0.1" in host else "https"
                    static_url = f"{scheme}://{host}/app/static/orbit_3d_view.html"
                except Exception:
                    static_url = "http://localhost:8501/app/static/orbit_3d_view.html"

                st.link_button("Open 3D Globe in new tab ↗", static_url)

                import streamlit.components.v1 as components
                components.iframe(static_url, height=650, scrolling=False)

            else:
                st.info("Check the box above to render the Cesium 3D globe for the selected pass.")

else:
    st.warning("No passes computed yet. Please click the button above to generate orbit data.")
