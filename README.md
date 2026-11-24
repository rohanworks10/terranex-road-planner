# 🛣️ TerraNex — Climate-Resilient Road Corridor Planning Agent

> **Give it two points and a hill slope. Get back two feasible road corridors, and a clear explanation of the trade-offs between them.**

**Team:** TerraNex

🎥 **Demo video:** `ADD LINK HERE`  

---

## 🌧️ The problem

Planning a road in hilly, high-rainfall regions means juggling terrain, rainfall, soil, land cover, drainage and engineering standards. This information lives in different datasets and long reference documents, so planners spend a lot of effort just bringing it together.

Most tools solve only one slice: a route finder gives the shortest line (often an unrealistic one), and a landslide model gives a risk map (but no road). **TerraNex joins these pieces into one transparent planning aid.**

## 💡 What TerraNex does

The user provides a **start point**, a **destination** and an **estimated average hill slope**. TerraNex then:

1. **Validates** the input (coordinates, slope unit and range).
2. **Fetches real elevation data** and calculates terrain slope itself.
3. **Cross-checks** the user's slope estimate against the calculated terrain and **warns about large mismatches**. The user's number is treated as an estimate, not ground truth.
4. **Generates two corridor alternatives** over the terrain:
   - **Route A: Travel efficiency** (shorter, more direct, still within feasibility limits)
   - **Route B: Safety & practicality** (avoids steep ground, lower terrain exposure)
5. **Explains the trade-offs** with measurable numbers (distance, slope, steepness exposure).

Both options are meant to be *conventional and feasible*. The efficiency route does not take unreasonable shortcuts; the two routes differ only in how they weight the trade-offs.

## 🧠 Design principle: the LLM explains, code calculates

The biggest risk with AI in engineering is **made-up numbers**. TerraNex is built to avoid that:

| Job | Who does it |
|---|---|
| Slope, distance, elevation, route scoring | **Deterministic Python code** (tested, repeatable) |
| Choosing route weights and constraints | **Explicit, visible parameters** (not hidden AI reasoning) |
| Explaining results in plain language | **AI agent layer**, only from calculated values and cited references |
| Engineering recommendations | **Constrained, traceable reference library**, no invented standards or clauses |

Every output is meant to separate **observed data**, **calculated values**, **modelled estimates** and **assumptions**, and to say clearly when data is missing instead of guessing.

## ✅ Current status (honest snapshot)

| Feature | Status |
|---|---|
| FastAPI backend with input validation (`POST /plan`) | ✅ Working |
| Real elevation data + slope profile along the straight line | ✅ Working |
| User-slope vs. calculated-slope mismatch warnings | ✅ Working |
| Terrain grid preparation (`POST /terrain/prepare`) | ✅ Working |
| Two routes via A\* search with different slope weights (`POST /routes`) | ✅ Working |
| React dashboard: input form, terrain card, route cards, interactive map | ✅ Working |
| Automated backend test suite | ✅ 77 tests passing |
| Historical rainfall / weather profile (Open-Meteo) | 🔜 In progress |
| Rivers, roads and crossings from OpenStreetMap | 🔜 Planned |
| Reference library + drainage/material guidance with citations | 🔜 Planned |
| AI explanation layer | 🔜 Planned |
| Land cover screening (ESA WorldCover) | 🔜 Planned |
| Soil context screening (ISRIC SoilGrids) | 🔜 Planned |
| Future climate projections (long-term resilience lens) | 🔜 Planned |
| Route scoring with transparent, adjustable weights | 🔜 Planned |
| Confidence and data-quality warnings per route | 🔜 Planned |
| Exportable route comparison report | 🔜 Planned |

> We list what is **not** done yet on purpose. Claiming only what is verified is part of how this project is designed.

## 🏗️ Architecture

```
┌──────────────────────┐        ┌───────────────────────────────┐
│  React + Leaflet UI  │ ─────► │        FastAPI backend        │
│  form · cards · map  │ ◄───── │  validation · terrain · routes│
└──────────────────────┘        └──────────────┬────────────────┘
                                               │
                         ┌─────────────────────┼─────────────────────┐
                         ▼                     ▼                     ▼
                 Open-Meteo APIs        Terrain/slope code     Route search (A*)
              (elevation, weather)      (deterministic)        (two weightings)
```

**Tech stack:** Python 3.12 · FastAPI · pytest · React (Vite) · Leaflet

## 🚀 Run it locally

Tested on Windows with PowerShell. You need **Python 3.12** and **Node.js** installed.

### 1. Clone the project

```powershell
git clone https://github.com/rohanworks10/terranex-road-planner.git
cd terranex-road-planner
```

### 2. Start the backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

The backend runs at `http://127.0.0.1:8000`. Interactive API docs are at `http://127.0.0.1:8000/docs`.

### 3. Start the frontend (in a second terminal)

```powershell
cd frontend
npm install
npm run dev
```

Open the address that Vite prints (usually `http://localhost:5173`).

### 4. Try an example

Enter a start and destination in a hilly area, plus an estimated average slope in degrees. Example region (Western Ghats, Karnataka):

- Start: `15.85, 74.50`
- End: `15.60, 74.30`

### 5. Run the tests

```powershell
cd backend
pytest
```

## ⚠️ Limitations (what TerraNex does *not* claim)

- It is a **preliminary decision-support tool**, not a final engineering design.
- It does **not** guarantee a road is safe or landslide-proof, and does not replace geotechnical surveys, hydrological studies or a qualified engineer.
- It does **not** produce construction-ready geometry, culvert sizes or certified pavement designs.
- Elevation data has limited resolution; short weather histories are **not** a long-term climate baseline.
- The prototype targets **hilly, high-rainfall terrain**, not every road type or landscape.

## 🗺️ Roadmap

- [x] Backend, validation, tests
- [x] Terrain slope analysis and mismatch warnings
- [x] Two-route generation and map view
- [ ] Rainfall and weather profile
- [ ] Rivers, roads and crossings (OpenStreetMap)
- [ ] Curated reference library (IRC, MoRTH, FHWA) with source and clause tracking
- [ ] Drainage and material recommendations tied to site conditions
- [ ] AI agent that explains results using only calculated data and cited references
- [ ] Land cover and soil screening layers

## 📚 Data & references

| Source | Use |
|---|---|
| Open-Meteo | Elevation, historical weather, climate projections |
| OpenStreetMap | Roads, waterways, mapped features (planned) |
| ESA WorldCover, ISRIC SoilGrids | Land cover and soil screening (planned) |
| IRC, MoRTH, FHWA | Engineering and drainage references (planned) |

## 👥 Team TerraNex

- **Rohan** ([@rohanworks10](https://github.com/rohanworks10)): Team captain
- **Atharv**: Team member
