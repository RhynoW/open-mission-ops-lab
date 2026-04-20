import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
import json

import streamlit as st
from src.models import Satellite, GroundStation
from src.pass_calculator import compute_passes

import folium
from leafmap import foliumap  # folium backend — no Jupyter widget dependency

# --------------------------------------------------------------------
# Streamlit 基本設定
# --------------------------------------------------------------------
st.set_page_config(page_title="Open Mission Ops Lab - 3D", layout="wide")
st.title("Open Mission Ops Lab - 3D Orbit View (Leafmap + Cesium Prototype)")
st.caption("Ground track pipeline + 3D view using Leafmap (2D) and Cesium (3D HTML embed)")

st.info(
    "This page computes passes for a satellite-ground station pair, "
    "exports time-series orbit data, and visualizes the ground track in 2D and 3D."
)

# --------------------------------------------------------------------
# Session state init
# --------------------------------------------------------------------
if "passes" not in st.session_state:
    st.session_state.passes = None
if "sat_name" not in st.session_state:
    st.session_state.sat_name = ""
if "gs_params" not in st.session_state:
    st.session_state.gs_params = None

# --------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------
col1, col2 = st.columns(2)
with col1:
    tle1 = st.text_input(
        "TLE Line 1",
        "1 25544U 98067A   26109.54791667  .00016717  00000+0  29614-3 0  9991",
    )
    tle2 = st.text_input(
        "TLE Line 2",
        "2 25544  51.6400  22.3050 0004100  79.2100 280.9300 15.50000000  1234",
    )
    sat_name = st.text_input("Satellite Name", st.session_state.sat_name or "ISS")
    frequency_mhz = st.number_input("Frequency (MHz)", value=437.0, min_value=1.0)

with col2:
    gs_name = st.text_input("Ground Station Name", "Taipei")
    lat = st.number_input("Latitude (deg)", value=25.0330, format="%.4f")
    lon = st.number_input("Longitude (deg)", value=121.5654, format="%.4f")
    alt_m = st.number_input("Altitude (m)", value=10.0)
    min_el = st.slider("Minimum Elevation (deg)", 0.0, 30.0, 0.0, 1.0)

st.markdown("---")

col3, col4 = st.columns(2)
with col3:
    hours = st.number_input(
        "Time span to search passes (hours)",
        value=2.0,
        min_value=0.5,
        max_value=24.0,
        step=0.5,
    )
with col4:
    step_seconds = st.number_input(
        "Time step within pass (seconds)",
        value=30.0,
        min_value=5.0,
        max_value=600.0,
        step=5.0,
    )

# --------------------------------------------------------------------
# Compute passes & store in session_state
# --------------------------------------------------------------------
if st.button("Prepare orbit data & visualize"):
    try:
        sat = Satellite(sat_name, tle1, tle2, frequency_mhz=frequency_mhz)

        # 注意 GroundStation 參數名稱要與 src.models.GroundStation 一致
        gs = GroundStation(gs_name, lat, lon, alt_m, min_elevation_deg=min_el)

        passes = compute_passes(sat, gs, hours=hours, step_seconds=step_seconds)
        st.session_state.passes = passes
        st.session_state.sat_name = sat_name
        st.session_state.gs_params = {
            "gs_name": gs_name,
            "lat": lat,
            "lon": lon,
            "alt_m": alt_m,
            "min_el": min_el,
        }

        if not passes:
            st.warning("No visible passes found in the requested time window.")
        else:
            st.success(f"Computed {len(passes)} passes within {hours:.1f} hours.")

    except Exception as e:
        st.error(f"Failed to compute passes: {e}")
        st.session_state.passes = None

# --------------------------------------------------------------------
# If we already have passes, show selector + map
# --------------------------------------------------------------------
passes = st.session_state.passes

if passes:
    gs_params = st.session_state.gs_params or {
        "gs_name": gs_name,
        "lat": lat,
        "lon": lon,
        "alt_m": alt_m,
        "min_el": min_el,
    }

    st.markdown("### Select pass for visualization")

    pass_labels = [
        f"Pass #{i+1} (AOS {p['aos'].strftime('%H:%M:%S')} UTC, max elev {p['max_elevation_deg']:.1f}°)"
        for i, p in enumerate(passes)
    ]

    sel_idx = st.selectbox(
        "Pass",
        range(len(passes)),
        format_func=lambda i: pass_labels[i],
    )
    p_sel = passes[sel_idx]

    # ----------------------------------------------------------------
    # Build orbit_data structure
    # ----------------------------------------------------------------
    orbit_data = {
        "satellite": {
            "name": st.session_state.sat_name or sat_name,
        },
        "ground_station": {
            "name": gs_params["gs_name"],
            "lat_deg": gs_params["lat"],
            "lon_deg": gs_params["lon"],
            "alt_m": gs_params["alt_m"],
        },
        "pass": {
            "aos_utc": p_sel["aos"].isoformat(),
            "los_utc": p_sel["los"].isoformat(),
            "tca_utc": p_sel["tca"].isoformat(),
            "max_elevation_deg": p_sel["max_elevation_deg"],
            "duration_sec": p_sel["duration_min"] * 60.0,
        },
        "track": [
            {
                "time_utc": t.isoformat(),
                "sub_lat_deg": float(phi),
                "sub_lon_deg": float(lam),
                "elevation_deg": float(el),
            }
            for t, phi, lam, el in zip(
                p_sel["time"],
                p_sel["sub_lat_deg"],
                p_sel["sub_lon_deg"],
                p_sel["elevation_deg"],
            )
        ],
    }

    st.markdown("### Orbit data (JSON preview)")
    st.write(
        f"Track samples: {len(orbit_data['track'])} points "
        f"from {orbit_data['pass']['aos_utc']} to {orbit_data['pass']['los_utc']} (UTC)"
    )
    st.code(
        json.dumps(orbit_data, indent=2)[:2000] + "\n...\n",
        language="json",
    )

    st.download_button(
        "Download orbit_3d_pass.json",
        data=json.dumps(orbit_data, indent=2),
        file_name="orbit_3d_pass.json",
        mime="application/json",
    )

    # ----------------------------------------------------------------
    # 2D Visualization with Leafmap (先驗證 pipeline)
    # ----------------------------------------------------------------
    st.markdown("---")
    st.markdown("### Ground Track (2D, Leafmap)")

    if len(orbit_data["track"]) < 2:
        st.warning("Not enough points to draw a trajectory line.")
    else:
        # foliumap uses folium backend — no Jupyter widgets, no RequireJS conflicts
        m = foliumap.Map(
            center=[gs_params["lat"], gs_params["lon"]],
            zoom=3,
            height=600,
            draw_control=False,
        )

        # Satellite ground track — folium expects [lat, lon] order
        track_latlon = [[p["sub_lat_deg"], p["sub_lon_deg"]] for p in orbit_data["track"]]
        folium.PolyLine(
            track_latlon,
            color="red",
            weight=3,
            opacity=0.9,
            tooltip="Satellite Path",
        ).add_to(m)

        # Ground station marker
        folium.Marker(
            location=[gs_params["lat"], gs_params["lon"]],
            popup=gs_params["gs_name"],
            icon=folium.Icon(color="blue", icon="tower-broadcast", prefix="fa"),
        ).add_to(m)

        m.to_streamlit(height=600)

        st.info(
            "2D ground track is rendered with Leafmap. "
            "Once this looks correct, you can rely on the same orbit_data for 3D."
        )

    # ----------------------------------------------------------------
    # 3D Visualization with Cesium (HTML embed via leafmap.cesium_to_streamlit)
    # ----------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 3D Ground Track (Cesium, HTML embed)")

    # 3D 部分可以由 checkbox 控制是否輸出檔案與載入
    enable_3d = st.checkbox("Generate Cesium 3D view", value=True)

    if enable_3d:
        # Write HTML to app/static/ so Streamlit serves it via HTTP (avoids file:// origin)
        static_dir = Path(__file__).parent / "static"
        static_dir.mkdir(parents=True, exist_ok=True)
        html_path = static_dir / "orbit_3d_view.html"

        orbit_json_str = json.dumps(orbit_data)

        # Self-contained Cesium HTML — modelled on working reference HTML
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
    // Fix blob-worker importScripts paths before Cesium init
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

      // Ground track polyline (lon, lat, height=400 km altitude approx)
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

      // Ground station marker
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

        # Write to app/static/ — Streamlit serves this at /app/static/orbit_3d_view.html
        try:
            html_path.write_text(cesium_html, encoding="utf-8")
        except Exception as e:
            st.error(f"Failed to write orbit_3d_view.html: {e}")
            st.stop()

        static_url = "http://localhost:8501/app/static/orbit_3d_view.html"
        st.link_button("Open 3D Globe in new tab ↗", static_url)

        import streamlit.components.v1 as components
        components.iframe(static_url, height=650, scrolling=False)

        st.info(
            "Cesium 3D view is served via HTTP and embedded above. "
            "Use the link button to open it in a full browser tab."
        )

else:
    st.warning("No passes computed yet. Please click the button above to generate orbit data.")