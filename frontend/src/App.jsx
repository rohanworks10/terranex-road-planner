import { useEffect, useState } from 'react'
import RouteMap from './RouteMap.jsx'

// ─── Styles ────────────────────────────────────────────────────────────────

const styles = {
  page:    { padding: '2rem', fontFamily: 'sans-serif', maxWidth: '1000px', margin: '0 auto', textAlign: 'left' },
  grid:    { display: 'grid', gap: '0.5rem' },
  input:   { padding: '0.4rem', fontSize: '1rem', borderRadius: '4px', border: '1px solid #ccc' },
  button:  { padding: '0.5rem 1rem', fontSize: '1rem', cursor: 'pointer', borderRadius: '4px', border: 'none', background: '#1a73e8', color: '#fff' },
  card:    { background: '#f8f9fa', border: '1px solid #dadce0', borderRadius: '8px', padding: '1rem', marginTop: '1rem' },
  row:     { display: 'flex', justifyContent: 'space-between', margin: '0.3rem 0' },
  label:   { color: '#5f6368' },
  value:   { fontWeight: 'bold' },
  warning: { background: '#fce8e6', border: '1px solid #f28b82', borderRadius: '6px', padding: '0.75rem', marginTop: '1rem', color: '#c5221f' },
  error:   { background: '#fce8e6', border: '1px solid #f28b82', borderRadius: '6px', padding: '0.75rem', marginTop: '1rem', color: '#c5221f' },
  success: { color: '#137333', marginTop: '1rem' },
  divider: { borderTop: '1px solid #dadce0', margin: '0.5rem 0' },
}

// ─── Helper: one display row ────────────────────────────────────────────────

function Row({ label, value }) {
  return (
    <div style={styles.row}>
      <span style={styles.label}>{label}</span>
      <span style={styles.value}>{value}</span>
    </div>
  )
}

// ─── Main app ───────────────────────────────────────────────────────────────

function App() {

  // Backend health status (top of page)
  const [status, setStatus] = useState('Checking...')
  useEffect(() => {
    fetch('http://127.0.0.1:8000/health')
      .then(r => r.json())
      .then(d => setStatus(d.status))
      .catch(() => setStatus('Cannot reach the backend'))
  }, [])

  // Form fields
  const [startLat, setStartLat] = useState('')
  const [startLon, setStartLon] = useState('')
  const [endLat,   setEndLat]   = useState('')
  const [endLon,   setEndLon]   = useState('')
  const [slope,    setSlope]    = useState('')
  const [bufferKm, setBufferKm] = useState('5')

  // UI state
  const [loading, setLoading]   = useState(false)
  const [error,   setError]     = useState(null)
  const [result,  setResult]    = useState(null)
  const [preparingTerrain, setPreparingTerrain] = useState(false)
  const [terrainError, setTerrainError] = useState(null)
  const [terrainResult, setTerrainResult] = useState(null)
  const [routeLoading, setRouteLoading] = useState(false)
  const [routeError, setRouteError] = useState(null)
  const [routeResult, setRouteResult] = useState(null)
  const [selectedRoute, setSelectedRoute] = useState('route_a')

  // ── Submit ──────────────────────────────────────────────────────────────

  function handleSubmit() {
    // Reset previous result and error
    setResult(null)
    setError(null)
    setLoading(true)

    fetch('http://127.0.0.1:8000/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        start: { lat: Number(startLat), lon: Number(startLon) },
        end:   { lat: Number(endLat),   lon: Number(endLon)   },
        endpoint_slope_degrees: Number(slope),
      }),
    })
      .then(response => {
        if (!response.ok) {
          // 422 Unprocessable Entity — schema validation failed
          return response.json().then(data => {
            const detail = data?.detail?.[0]?.msg || 'One or more values are not valid.'
            throw new Error(detail)
          })
        }
        return response.json()
      })
      .then(data => {
        if (data.status === 'error') {
          // The backend returned a 200 but with an application-level error
          setError(data.error)
        } else {
          setResult(data)
        }
      })
      .catch(err => {
        setError(err.message || 'Cannot reach the backend.')
      })
      .finally(() => setLoading(false))
  }

  function handlePrepareTerrain() {
    setTerrainError(null)
    setTerrainResult(null)
    setRouteError(null)
    setRouteResult(null)
    if (![startLat, startLon, endLat, endLon].every(value => value.trim() !== '')) {
      setTerrainError('Enter start and destination coordinates first.')
      return
    }

    const bufferMeters = Number(bufferKm) * 1000
    if (!Number.isFinite(bufferMeters) || bufferMeters <= 0) {
      setTerrainError('The study-area buffer must be greater than zero.')
      return
    }

    setPreparingTerrain(true)
    fetch('http://127.0.0.1:8000/terrain/prepare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        start: { lat: Number(startLat), lon: Number(startLon) },
        end:   { lat: Number(endLat),   lon: Number(endLon)   },
        buffer_m: bufferMeters,
      }),
    })
      .then(response => response.json().then(data => {
        if (!response.ok) {
          throw new Error(data?.detail || 'Could not prepare terrain data.')
        }
        return data
      }))
      .then(setTerrainResult)
      .catch(err => setTerrainError(err.message || 'Could not reach the backend.'))
      .finally(() => setPreparingTerrain(false))
  }

  function handleGenerateRoutes() {
    setRouteError(null)
    setRouteResult(null)
    if (![startLat, startLon, endLat, endLon].every(value => value.trim() !== '')) {
      setRouteError('Enter start and destination coordinates first.')
      return
    }

    const bufferMeters = Number(bufferKm) * 1000
    if (!Number.isFinite(bufferMeters) || bufferMeters <= 0) {
      setRouteError('The study-area buffer must be greater than zero.')
      return
    }

    setRouteLoading(true)
    fetch('http://127.0.0.1:8000/routes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        start: { lat: Number(startLat), lon: Number(startLon) },
        end:   { lat: Number(endLat),   lon: Number(endLon)   },
        buffer_m: bufferMeters,
        snap_radius_m: 90,
      }),
    })
      .then(response => response.json().then(data => {
        if (!response.ok) {
          const detail = Array.isArray(data?.detail)
            ? data.detail.map(item => item.msg).join(', ')
            : data?.detail
          throw new Error(detail || 'Could not generate terrain routes.')
        }
        return data
      }))
      .then(data => {
        setRouteResult(data)
        setSelectedRoute('route_a')
      })
      .catch(err => setRouteError(err.message || 'Could not reach the backend.'))
      .finally(() => setRouteLoading(false))
  }

  // ── Clear / plan another route ───────────────────────────────────────────

  function handleReset() {
    setResult(null)
    setError(null)
    setTerrainResult(null)
    setTerrainError(null)
    setRouteResult(null)
    setRouteError(null)
    setStartLat(''); setStartLon('')
    setEndLat('');   setEndLon('')
    setSlope('')
    setBufferKm('5')
  }

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div style={styles.page}>
      <h1>Road Corridor Planner</h1>
      <p>Backend status: <strong>{status}</strong></p>

      {/* ── Show results (or the form) ── */}
      {result ? (
        <ResultCard result={result} onReset={handleReset} />
      ) : (
        <RouteForm
          startLat={startLat} setStartLat={setStartLat}
          startLon={startLon} setStartLon={setStartLon}
          endLat={endLat}     setEndLat={setEndLat}
          endLon={endLon}     setEndLon={setEndLon}
          slope={slope}       setSlope={setSlope}
          bufferKm={bufferKm} setBufferKm={setBufferKm}
          loading={loading}
          error={error}
          preparingTerrain={preparingTerrain}
          terrainError={terrainError}
          terrainResult={terrainResult}
          routeLoading={routeLoading}
          routeError={routeError}
          routeResult={routeResult}
          selectedRoute={selectedRoute}
          onSelectRoute={setSelectedRoute}
          onSubmit={handleSubmit}
          onPrepareTerrain={handlePrepareTerrain}
          onGenerateRoutes={handleGenerateRoutes}
        />
      )}
    </div>
  )
}

// ─── Form component ──────────────────────────────────────────────────────────

function RouteForm({
  startLat, setStartLat, startLon, setStartLon,
  endLat,   setEndLat,   endLon,   setEndLon,
  slope,    setSlope, bufferKm, setBufferKm,
  loading, error, preparingTerrain, terrainError, terrainResult,
  routeLoading, routeError, routeResult, selectedRoute, onSelectRoute,
  onSubmit, onPrepareTerrain, onGenerateRoutes,
}) {
  return (
    <>
      <h2>Plan a road</h2>
      <div style={styles.grid}>
        <input style={styles.input} placeholder="Start latitude  (e.g. 15.85)"  value={startLat} onChange={e => setStartLat(e.target.value)} />
        <input style={styles.input} placeholder="Start longitude (e.g. 74.50)"  value={startLon} onChange={e => setStartLon(e.target.value)} />
        <input style={styles.input} placeholder="End latitude    (e.g. 15.60)"  value={endLat}   onChange={e => setEndLat(e.target.value)} />
        <input style={styles.input} placeholder="End longitude   (e.g. 74.30)"  value={endLon}   onChange={e => setEndLon(e.target.value)} />
        <input style={styles.input} placeholder="Expected overall endpoint slope magnitude (degrees, e.g. 5)" value={slope} onChange={e => setSlope(e.target.value)} />
        <label style={styles.label}>
          Study-area buffer around the endpoints (km)
          <input
            style={styles.input}
            type="number"
            min="0.1"
            step="0.5"
            value={bufferKm}
            onChange={e => setBufferKm(e.target.value)}
          />
        </label>
        <button style={styles.button} onClick={onSubmit} disabled={loading}>
          {loading ? '⏳ Calculating…' : 'Analyse terrain'}
        </button>
        <button
          style={{ ...styles.button, background: '#5f6368' }}
          onClick={onPrepareTerrain}
          disabled={preparingTerrain}
        >
          {preparingTerrain ? 'Preparing DEM…' : 'Prepare terrain grid'}
        </button>
        {terrainResult && (
          <button
            style={{ ...styles.button, background: '#188038' }}
            onClick={onGenerateRoutes}
            disabled={routeLoading}
          >
            {routeLoading ? 'Searching terrain grid…' : 'Generate two route alternatives'}
          </button>
        )}
      </div>

      {/* Loading hint */}
      {loading && (
        <p style={{ color: '#1a73e8' }}>
          Fetching real elevation data — this takes a few seconds…
        </p>
      )}

      {/* Error message */}
      {error && (
        <div style={styles.error}>
          <strong>Error:</strong> {error}
        </div>
      )}
      {preparingTerrain && (
        <p style={{ color: '#1a73e8' }}>
          Checking the selected area and reading only the required elevation tiles…
        </p>
      )}
      {terrainError && (
        <div style={styles.error}>
          <strong>Terrain preparation error:</strong> {terrainError}
        </div>
      )}
      {terrainResult && <TerrainPreparationCard result={terrainResult} />}
      {routeLoading && (
        <p style={{ color: '#188038' }}>
          Searching valid raster cells for the lowest-cost paths. This uses the prepared grid only.
        </p>
      )}
      {routeError && (
        <div style={styles.error}>
          <strong>Route generation error:</strong> {routeError}
        </div>
      )}
      {routeResult && (
        <RouteAlternativesCard
          result={routeResult}
          selectedRoute={selectedRoute}
          onSelectRoute={onSelectRoute}
        />
      )}
    </>
  )
}

function RouteAlternativesCard({ result, selectedRoute, onSelectRoute }) {
  const routeA = result.features.find(feature => feature.properties.route_id === 'route_a')
  const routeB = result.features.find(feature => feature.properties.route_id === 'route_b')
  const selectedColor = selectedRoute === 'route_a' ? '#1a73e8' : '#188038'

  return (
    <section style={{ ...styles.card, marginTop: '1.5rem' }}>
      <h2>Terrain route alternatives</h2>
      <p style={styles.label}>
        Straight-line endpoint distance: {result.straight_line_distance_km.toFixed(3)} km.
        Raster route distances follow cell centers and can be longer.
      </p>
      <p style={styles.label}>
        Elevation data: {result.terrain_data.source} ({result.terrain_data.release}),
        nominal {result.terrain_data.nominal_resolution_m} m; retrieved {result.terrain_data.retrieved_at_utc}.
      </p>
      <RouteMap
        result={result}
        selectedRoute={selectedRoute}
        onSelectRoute={onSelectRoute}
      />
      <div style={styles.grid}>
        {[routeA, routeB].map((feature, index) => {
          const routeId = index === 0 ? 'route_a' : 'route_b'
          const properties = feature.properties
          const color = routeId === 'route_a' ? '#1a73e8' : '#188038'
          const selected = routeId === selectedRoute
          return (
            <button
              key={routeId}
              type="button"
              onClick={() => onSelectRoute(routeId)}
              aria-pressed={selected}
              style={{
                ...styles.card,
                marginTop: '0.5rem',
                cursor: 'pointer',
                textAlign: 'left',
                border: `2px solid ${selected ? color : '#dadce0'}`,
                background: selected ? `${color}12` : '#f8f9fa',
              }}
            >
              <strong style={{ color }}>{properties.name}</strong>
              <div style={styles.divider} />
              <Row label="Raster route distance" value={`${properties.route_distance_km.toFixed(3)} km`} />
              <Row label="Distance-weighted average slope" value={`${properties.average_slope_degrees.toFixed(2)}° (${properties.average_slope_percent.toFixed(2)}%)`} />
              <Row label="Maximum local raster slope" value={`${properties.maximum_slope_degrees.toFixed(2)}° (${properties.maximum_slope_percent.toFixed(2)}%)`} />
              <Row label="Accumulated objective cost" value={`${properties.accumulated_cost_m.toLocaleString()} cost-weighted m`} />
              <Row label="Raster cells traversed" value={properties.cells_traversed.toLocaleString()} />
              <Row label="Endpoint snapping" value={`${properties.start_snap_distance_m} m / ${properties.destination_snap_distance_m} m`} />
              <p style={styles.label}>{properties.objective}</p>
            </button>
          )
        })}
      </div>
      <p style={{ ...styles.label, marginTop: '0.75rem' }}>
        {result.route_similarity.note} Costs use different weights, so compare each route's
        distance and slope measures rather than treating the two cost totals as the same scale.
      </p>
      <div style={styles.warning}>
        <strong>Limitations:</strong> These paths use slope only; water, land cover, and
        construction difficulty beyond slope are not modeled. The results are not engineering
        approval or a declaration of safety.
      </div>
      <p style={{ color: selectedColor, fontWeight: 'bold', marginTop: '0.5rem' }}>
        Selected on map: {selectedRoute === 'route_a' ? 'Route A (blue)' : 'Route B (green)'}
      </p>
    </section>
  )
}

function TerrainPreparationCard({ result }) {
  const { study_area: area, dataset, raster, slope_degrees: slope, cost_surface: cost } = result
  const bboxText = `${area.south.toFixed(5)}, ${area.west.toFixed(5)} to ${area.north.toFixed(5)}, ${area.east.toFixed(5)}`
  return (
    <div style={styles.card}>
      <strong>Terrain grid prepared</strong>
      <div style={styles.divider} />
      <Row label="Study-area bounds (south/west to north/east)" value={bboxText} />
      <Row label="DEM source" value={`${dataset.name}, ${dataset.release}`} />
      <Row label="Nominal DEM resolution" value={`${dataset.nominal_resolution_m} m`} />
      <Row label="Retrieved (UTC)" value={dataset.retrieved_at_utc} />
      <Row label="Grid" value={`${raster.width} × ${raster.height} cells in ${raster.crs}`} />
      <Row label="Valid slope cells" value={raster.valid_slope_cells.toLocaleString()} />
      <Row label="Slope range" value={`${slope.minimum}°–${slope.maximum}°`} />
      <Row label="Cost surface" value={cost.formula} />
      <p style={styles.label}>
        This prepares terrain data only. It does not generate or approve a road corridor.
        Water and land-cover data are not included.
      </p>
    </div>
  )
}

// ─── Results card ────────────────────────────────────────────────────────────

function ResultCard({ result, onReset }) {
  const distanceKm = (result.distance_m / 1000).toFixed(2)

  return (
    <>
      <h2>Terrain Analysis Results</h2>

      {/* Slope warning — shown prominently before the numbers */}
      {result.slope_warning && (
        <div style={styles.warning}>
          ⚠️ <strong>Slope mismatch warning</strong><br />
          Your entered endpoint slope magnitude ({result.user_slope_degrees.toFixed(1)}°) differs from the
          measured endpoint slope magnitude ({result.calculated_slope_degrees.toFixed(1)}°) by{' '}
          <strong>{result.slope_difference_degrees}°</strong>, which is more
          than the {result.slope_tolerance_degrees}° tolerance. Please verify
          your route design.
        </div>
      )}

      {/* Distance */}
      <div style={styles.card}>
        <strong>Distance</strong>
        <div style={styles.divider} />
        <Row label="Straight-line distance" value={`${distanceKm} km (${result.distance_m.toLocaleString()} m)`} />
        <Row label="Elevation samples" value={`${result.sample_count} points; average spacing ${result.sample_interval_distance_m} m`} />
      </div>

      {/* Slope comparison */}
      <div style={styles.card}>
        <strong>Slope comparison</strong>
        <div style={styles.divider} />
        <Row label="Entered endpoint slope magnitude" value={`${result.user_slope_degrees}° (${result.user_slope_percent}%)`} />
        <Row label="Measured endpoint slope (signed)" value={`${result.endpoint_slope_degrees.toFixed(1)}° (${result.endpoint_slope_percent.toFixed(1)}%)`} />
        <Row label="Endpoint slope magnitude (compared)" value={`${result.endpoint_slope_magnitude_degrees.toFixed(1)}°`} />
        <Row label="Difference"                   value={`${result.slope_difference_degrees}°`} />
        <Row label="Warning threshold"            value={`${result.slope_tolerance_degrees}°`} />
      </div>

      {/* Detailed terrain */}
      <div style={styles.card}>
        <strong>Terrain details</strong>
        <div style={styles.divider} />
        <Row label="Average absolute segment slope" value={`${result.average_absolute_segment_slope_degrees}° (${result.average_absolute_segment_slope_percent}%)`} />
        <Row label="Steepest terrain segment"       value={`${result.steepest_segment_slope_degrees}° (${result.steepest_segment_slope_percent}%)`} />
      </div>

      {/* Plan another route */}
      <div style={{ marginTop: '1.5rem' }}>
        <button style={{ ...styles.button, background: '#5f6368' }} onClick={onReset}>
          ← Plan another route
        </button>
      </div>
    </>
  )
}

export default App
