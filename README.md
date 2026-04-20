# Open Mission Ops Lab (OMOL) 🚀

**Open Mission Ops Lab (OMOL)** 是一個專為航太工程、衛星通訊教育以及 CubeSat 任務規劃打造的互動式模擬平台。  
透過 Python 與 Streamlit 驅動，本工具協助學生與研究人員快速掌握軌道力學、都卜勒效應（Doppler Effect）、鏈路預算（Link Budget）與 3D 全球視覺化等核心概念。

> **Disclaimer**：本工具僅供教育與早期任務概念探索使用，不適用於飛行認證或安全關鍵操作。

---

## 🌟 核心功能

### 1. 軌道計算與過境預測 (Orbit & Pass Prediction)

- **TLE 即時獲取**：串接 CelesTrak API，輸入 NORAD ID 自動下載最新兩行式軌道根數（TLE）。
- **多場景支援**：內建 ISS（國際太空站）、太陽同步軌道（SSO）及業餘衛星（AMSAT）等三組典型範例。
- **高精度計算**：基於 Skyfield，計算仰角（Elevation）、方位角（Azimuth）、距離（Range）及地面軌跡（Ground Track）。
- **可調仰角門檻**：支援 0°–30° 最低仰角遮罩，模擬實際天線視野限制。

### 2. 通訊鏈路分析 (Link Budget & SNR)

- **Friis 傳輸方程式**：即時計算自由空間路徑損耗（FSPL）、接收功率、SNR 與 $E_b/N_0$。
- **多樣化損耗模型**：支援大氣吸收（3 dB）、雨衰（Rain Fade, 10 dB）、極化損耗（1 dB）及自訂損耗。
- **KPI 面板**：自動計算單次過境的最大仰角、預估下行資料量、最大都卜勒偏移與鏈路可用率。
- **Link Margin 視覺化**：紅色陰影標示 $E_b/N_0$ 低於門檻的不可靠通訊時段。

### 3. 多維度視覺化 (Visualization)

- **Elevation & Doppler 複合圖**：雙 Y 軸 Plotly 圖表，同時呈現仰角與都卜勒偏移隨時間的變化。
- **SNR / Eb/No 趨勢圖**：含 Required Eb/No 門檻線與 Link Margin 陰影區。
- **Skyplot**：以極座標模擬地面站視角的天空追蹤圖（方位角 vs 仰角）。
- **2D 地圖軌跡**：Plotly Mapbox 呈現衛星地面軌跡與地面站標記。
- **3D 全球檢視**：整合 **CesiumJS 1.140.0**，以可互動 3D 地球觀察衛星過境幾何關係，並支援獨立分頁開啟。

### 4. 內建教學手冊 (Embedded Education Guide)

側邊欄以折疊式章節提供 10 個深度教材模組：

| 章節 | 主題 |
|------|------|
| 1 | Link Budget — 通訊收支總表（含流程圖） |
| 2 | 自由空間路徑損耗（FSPL）公式與數值直覺 |
| 3 | 接收功率方程式與課堂計算範例 |
| 4 | 熱雜訊功率與系統雜訊溫度 $T_{\mathrm{sys}}$ |
| 5 | SNR 與 $E_b/N_0$ 的物理意義及 BER 關係 |
| 6 | Link Margin 與鏈路可用時間分析 |
| 7 | 都卜勒效應與 LEO 頻率補償 |
| 8 | 大氣吸收、雨衰與極化損耗（各頻段對照表） |
| 9 | 調變方式（BPSK / QPSK / QAM）對 $E_b/N_0$ 需求比較 |
| 10 | 即時參數面板（與主畫面同步）+ 課堂互動建議 |

---

## 🛠️ 技術棧

| 層次 | 工具 / 函式庫 |
|------|--------------|
| **Frontend** | [Streamlit](https://streamlit.io/) ≥ 1.33 |
| **Orbit Propagator** | [Skyfield](https://rhodesmill.org/skyfield/) ≥ 1.49 |
| **2D Visualization** | [Plotly](https://plotly.com/) ≥ 5.20、Mapbox |
| **3D Globe** | [CesiumJS](https://cesium.com/) 1.140.0（via jsDelivr CDN） |
| **Data** | Pandas ≥ 2.2、NumPy ≥ 1.26 |
| **TLE Source** | [CelesTrak](https://celestrak.org/) REST API |
| **2D Map** | Leafmap (foliumap backend)、Folium |

---

## 🚀 快速開始

### 1. 複製儲存庫

```bash
git clone https://github.com/your-username/open-mission-ops-lab.git
cd open-mission-ops-lab
```

### 2. 建立環境並安裝依賴

**使用 Conda（建議）**

```bash
conda create -n open-mission-ops-lab python=3.10
conda activate open-mission-ops-lab
pip install -e .
```

**使用 venv**

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -e .
```

核心依賴項（`pyproject.toml` 管理）：

```
streamlit>=1.33  plotly>=5.20  skyfield>=1.49  numpy>=1.26  pandas>=2.2
```

額外依賴（Cesium 地圖與 2D 視圖）：

```bash
pip install requests leafmap folium
```

### 3. 啟動應用程式

```bash
streamlit run app/app.py
```

開啟瀏覽器前往 `http://localhost:8501`。

> **注意**：Cesium 3D Globe 透過 Streamlit Static File Serving 提供服務，`.streamlit/config.toml` 已預設啟用 `enableStaticServing = true`。

---

## 📖 使用說明

1. **(可選) 載入範例場景**：點選下拉選單選擇預設情境，再按 **Load example**。
2. **調整輸入參數**：設定 TLE、地面站座標、最低仰角與鏈路參數。
3. **(可選) 即時獲取 TLE**：輸入 NORAD ID，按 **Fetch TLE from CelesTrak**。
4. 點選 **Run Demo** 執行計算。
5. 透過六個分頁探索結果：

| 分頁 | 內容 |
|------|------|
| **Overview** | 過境摘要表 + KPI 指標 + CSV 下載 |
| **Elevation & Doppler** | 仰角與都卜勒複合時序圖 |
| **Link & Eb/No** | SNR / Eb/No 趨勢圖 + Link Margin 陰影 + 下行量估算 |
| **Skyplot** | 極座標天空追蹤圖 |
| **Map** | 2D 地面軌跡 + 地面站標記 |
| **3D Globe** | CesiumJS 互動式 3D 地球（支援新分頁開啟）|

---

## 📁 專案結構

```text
open-mission-ops-lab/
├── app/
│   ├── app.py                  # 主程式入口（整合所有功能）
│   └── static/
│       └── orbit_3d_view.html  # Cesium 3D HTML（由 app.py 動態產生）
├── src/
│   ├── models.py               # Satellite / GroundStation / LinkProfile / Scenario
│   ├── pass_calculator.py      # 過境預測：仰角、方位角、距離、地面軌跡
│   ├── link_budget.py          # FSPL、接收功率、SNR、Eb/No（純量與時序）
│   └── doppler.py              # 都卜勒偏移估算
├── examples/
│   ├── scenario_taipei_iss.json
│   ├── scenario_taipei_sso_earth_obs.json
│   └── scenario_taipei_uhf_amsat.json
├── tests/                      # pytest 測試
├── docs/
│   └── img/                    # README 截圖
├── .streamlit/
│   └── config.toml             # enableStaticServing = true
├── pyproject.toml
└── README.md
```

---

## 📐 核心公式

**自由空間路徑損耗（Friis FSPL）**

$$\mathrm{FSPL\,(dB)} = 92.45 + 20\log_{10}(f_{\mathrm{MHz}}) + 20\log_{10}(R_{\mathrm{km}})$$

**接收功率**

$$P_r\,[\mathrm{dBW}] = P_t + G_t + G_r - \mathrm{FSPL} - L_{\mathrm{extra}}$$

**熱雜訊功率**

$$N\,[\mathrm{dBW}] = -228.6 + 10\log_{10}(T_{\mathrm{sys}}) + 10\log_{10}(B)$$

**SNR 與 Eb/N0**

$$\mathrm{SNR\,(dB)} = P_r - N \qquad \frac{E_b}{N_0}\,[\mathrm{dB}] = \mathrm{SNR} + 10\log_{10}\!\left(\frac{B}{R_b}\right)$$

**都卜勒偏移（近似）**

$$f_D \approx -\frac{v_r}{c}\,f_c$$

> 以上公式均為教學簡化版本，適合初學者建立直覺。

---

## 📊 課堂應用範例

1. **鏈路受限分析**  
   將 Loss model 切換至 `Rain fade (10 dB)`，觀察 $E_b/N_0$ 曲線整體下移 10 dB，並記錄紅色陰影區（不可靠通訊時段）的擴大情況。

2. **都卜勒補償演習**  
   觀察 ISS 在 AOS、TCA 與 LOS 三個時刻的頻率偏移量，理解為何 9600 bps 窄頻通訊需要即時拉頻補償。

3. **軌道高度比較**  
   切換 ISS（約 420 km）與 SSO EO（約 500 km）兩個範例，比較 FSPL 差異與單次過境可見時間。

4. **3D 幾何直覺**  
   在 3D Globe 分頁觀察衛星過境弧線與地面站的空間關係，驗證最大仰角對應的最短傳播距離。

---

## 🗺️ 開發路線圖

- [ ] 多地面站支援與過境排程（Pass Ranking & Scheduler）
- [ ] 每日下行機會統計與累積下載量估算
- [ ] 多衛星星座模式
- [ ] 匯出 STK / Orekit 相容格式
- [ ] 更多教學場景與作業模板

---

## 📄 授權協議

本專案採用 **MIT License** — 詳見 [LICENSE](LICENSE) 檔案。  
歡迎在課程、研究或自製 CubeSat 專案中自由使用與修改。

## 🤝 貢獻

歡迎透過 Pull Request 或 Issue 協助優化本教學工具！  
報告問題前請先確認 Python 版本（≥ 3.10）與依賴版本符合 `pyproject.toml` 規格。

---

## 參考資料

- ITU-R P.676（大氣衰減）、P.838（雨衰）、P.618（Earth-space propagation）  
- Proakis, J. G. — *Digital Communications*, 5th ed.  
- Wertz, J. R. & Larson, W. J. — *Space Mission Engineering: The New SMAD*  
- [CelesTrak TLE Archive](https://celestrak.org/)  
- [CesiumJS Documentation](https://cesium.com/learn/cesiumjs/)

---

*This project is part of a Space STEM initiative to lower the barrier to entry for satellite mission operations education.*
