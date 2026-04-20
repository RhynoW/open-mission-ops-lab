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
st.caption("CubeSat access, Doppler, starter link budget, skyplot & ground track demo")

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
    st.title("太空通訊基礎知識")

    st.markdown("### 1. Link Budget 的基本概念")
    st.write(
        "Link Budget 就像通訊系統的收支表：\n"
        "- 發射端：Tx 功率 + 天線增益\n"
        "- 傳播損耗：自由空間損耗 + 額外衰減（大氣、降雨、極化等）\n"
        "- 接收端：Rx 天線增益 + 接收機雜訊\n"
        "最後得到的 **信噪比 (SNR)** 或 **Eb/No**，決定能不能可靠解調。"
    )

    st.markdown("### 2. 自由空間路徑損耗 (FSPL)")
    st.latex(
        r"\text{FSPL(dB)} = 92.45 + 20 \log_{10}(f_{\mathrm{MHz}}) + 20 \log_{10}(R_{\mathrm{km}})"
    )
    st.write(
        "這個公式假設：\n"
        "- f 以 MHz 為單位\n"
        "- R 以 km 為單位\n"
        "頻率越高、距離越遠，FSPL 越大，代表路上「虧損」越多。"
    )

    st.markdown("### 3. 接收功率 (Received Power)")
    st.latex(
        r"P_r(\mathrm{dBW}) = P_t(\mathrm{dBW}) + G_t(\mathrm{dBi}) + G_r(\mathrm{dBi})"
        r"- \text{FSPL(dB)} - L_{\text{extra}}(\mathrm{dB})"
    )
    st.write(
        "其中：\n"
        "- $P_t$：發射功率\n"
        "- $G_t, G_r$：發射 / 接收天線增益\n"
        "- $L_{\\text{extra}}$：額外損耗（大氣、降雨、極化等），在本工具中可由下拉選單選擇。"
    )

    st.markdown("### 4. 熱雜訊功率與雜訊溫度")
    st.write(
        "任何有溫度的物體都會產生熱雜訊。對於接收機等效雜訊溫度 $T_\\text{sys}$，"
        "在頻寬 $B$ 下的熱雜訊功率為："
    )
    st.latex(r"N = k T_\text{sys} B")
    st.write("常用 dB 單位寫成：")
    st.latex(
        r"N(\mathrm{dBW}) = -228.6 + 10 \log_{10}(T_\text{sys}) + 10 \log_{10}(B)"
    )
    st.write(
        "這裡 $-228.6\\,\\mathrm{dBW/Hz/K}$ 是玻茲曼常數 $k$ 的 dB 形式，[web:102][web:105]\n"
        "$T_\\text{sys}$ 越低（例如用低雜訊 LNA），雜訊功率越小，SNR 就越高。"
    )

    st.markdown("### 5. SNR 與 Eb/No")
    st.latex(r"\text{SNR(dB)} = P_r(\mathrm{dBW}) - N(\mathrm{dBW})")
    st.latex(
        r"E_b/N_0(\mathrm{dB}) = \text{SNR(dB)} + 10 \log_{10}\left(\frac{B}{R_b}\right)"
    )
    st.write(
        "這裡 $R_b$ 是位元率 (bit rate)。在同樣的 SNR 下，如果 bit 速率比較低，"
        "每個 bit 分到的能量比較多，Eb/No 也會比較高。[web:98][web:106][web:112]"
    )

    st.markdown("### 6. Link Margin 與門檻 Eb/No")
    st.write(
        "實務系統會指定一個「所需 Eb/No 門檻」，例如 QPSK 要求 3~6 dB 以上才能達到目標 BER。[web:98][web:106]\n"
        "本工具在 Link & Eb/No 分頁中提供：\n"
        "- 綠色曲線：實際 Eb/No 隨時間變化\n"
        "- 紅色虛線：你設定的 Required Eb/No\n"
        "- 紅色陰影區：**Eb/No 低於門檻** 的時間區段，代表 link 可能不可靠"
    )

    st.markdown("### 7. 系統雜訊溫度的物理意義")
    st.write(
        "系統雜訊溫度 $T_\\text{sys}$ 可以視為「把所有雜訊來源折算成一個等效黑體」，包括：\n"
        "- 天線看到的天空背景、地面、太陽等\n"
        "- 前端 LNA / LNB 的雜訊溫度\n"
        "- 後端混頻與 IF / Baseband 級的雜訊貢獻\n"
        "在實務 link budget 裡，常常會把雜訊 figure (NF, dB) 轉成雜訊溫度來計算。[web:110][web:104]"
    )

    st.markdown("### 8. 雨衰減模型 (Rain Fade)")
    st.write(
        "在 Ku、Ka 頻段甚至更高頻率，雨滴會對電磁波產生明顯吸收與散射，"
        "造成額外的路徑衰減，稱為 **雨衰減 (rain fade)**。[web:98][web:106][web:108]"
    )
    st.write("ITU-R P.838 模型常用形式是先算比衰減 $\\gamma_R$（dB/km）：")
    st.latex(r"\gamma_R(f, R) = k(f)\, R^{\alpha(f)} \quad [\mathrm{dB/km}]")
    st.write(
        "其中 $k(f)$ 和 $\\alpha(f)$ 由 ITU 提供，[web:108] 再乘上有效雨區路徑長度 $L_{\\mathrm{eff}}$ 得到總雨衰減："
    )
    st.latex(r"A_R = \gamma_R \cdot L_{\mathrm{eff}} \quad [\mathrm{dB}]")
    st.write(
        "本工具為了簡化，使用下拉選單提供固定的示意損耗：\n"
        "- **Free-space only**：只考慮 FSPL\n"
        "- **Atmospheric loss (3 dB)**：晴朗天氣下的大氣吸收等效損耗\n"
        "- **Rain fade (10 dB)**：中到大雨時可能出現的額外 10 dB 衰減\n"
        "- **Polarization loss (1 dB)**：極化失配造成的損耗\n"
        "- **Custom loss**：自行輸入任意額外損耗值"
    )

    st.markdown("### 9. 不同調變方式的 Eb/No 需求比較")
    st.write(
        "下表是常見調變方式在 BER ≈ $10^{-5}$~$10^{-6}$ 時大約所需的 Eb/No，"
        "僅供教學參考，實際系統會依編碼與實作略有差異。[web:98][web:106][web:112]"
    )
    ebno_data = {
        "調變方式": [
            "BPSK (未編碼)",
            "QPSK (未編碼)",
            "8-PSK (未編碼)",
            "16-QAM (未編碼)",
            "64-QAM (未編碼)",
            "QPSK + 強 FEC",
        ],
        "目標 BER 範圍": [
            "≈ 1e-5",
            "≈ 1e-5",
            "≈ 1e-5",
            "≈ 1e-5",
            "≈ 1e-5",
            "≈ 1e-6",
        ],
        "典型所需 Eb/No (dB)": [9.5, 9.5, 12.0, 14.0, 18.0, 2.0],
    }
    ebno_df = pd.DataFrame(ebno_data)
    st.dataframe(ebno_df, use_container_width=True)
    st.caption(
        "備註：數值為理想或近似理想情況的典型值，實際系統會隨濾波、同步、編碼等有所不同。[web:98][web:106][web:112]"
    )

    st.markdown("### 10. 與主畫面互動的即時設定")
    current_loss_model = st.session_state.get("current_loss_model", "Free-space only")
    current_extra_loss_db = st.session_state.get("current_extra_loss_db", 0.0)
    current_required_ebno = st.session_state.get("current_required_ebno", 3.0)

    st.write("你在主畫面目前選擇的是：")
    st.markdown(
        f"- **Loss model**：{current_loss_model}\n"
        f"- **額外損耗 Extra Loss**：{current_extra_loss_db:.1f} dB\n"
        f"- **Required Eb/No**：{current_required_ebno:.1f} dB"
    )
    st.write(
        "對照 Link & Eb/No 圖表：\n"
        "- 綠線 = 實際 Eb/No 隨時間\n"
        "- 紅線 = Required Eb/No\n"
        "- 紅色陰影區 = Eb/No 低於門檻的時間（link margin < 0）\n"
        "試著把 Loss model 從「Free-space only」改成「Rain fade (10 dB)」，"
        "觀察整條 Eb/No 曲線往下平移約 10 dB，以及可用時間的變化。"
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
                "gs_lat": lat,
                "gs_lon": lon,
                "gs_name": gs_name,
                "extra_loss_db": extra_loss_db,
                "loss_model": loss_model,
            }
            st.session_state.active_pass_index = 0
        else:
            st.warning("No visible passes found in the time window.")
            st.session_state.results = {
                "passes": [],
                "per_pass_metrics": [],
                "gs_lat": lat,
                "gs_lon": lon,
                "gs_name": gs_name,
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

    tab_overview, tab_elev_dopp, tab_link, tab_skyplot, tab_map = st.tabs(
        ["Overview", "Elevation & Doppler", "Link & Eb/No", "Skyplot", "Map"]
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

                # Est. data volume (fixed efficiency)
                duration_min = first["duration_min"]
                duration_sec = duration_min * 60.0
                bits_max = data_rate * duration_sec
                kpi_eff = 0.7
                bits_eff = bits_max * kpi_eff
                mb_eff = bits_eff / 8.0 / 1e6

                k2.metric("Est. Data Volume (MB)", f"{mb_eff:.1f}")

                # Max |Doppler|
                if doppler_series:
                    max_dopp = max(doppler_series)
                    min_dopp = min(doppler_series)
                    max_abs_dopp = max(abs(max_dopp), abs(min_dopp))
                else:
                    max_abs_dopp = 0.0
                k3.metric("Max |Doppler| (Hz)", f"{max_abs_dopp:.0f}")

                # Link availability 先用 default required Eb/No（或目前設定）
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

        # --- Link & Eb/No tab + threshold / margin shading ---
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