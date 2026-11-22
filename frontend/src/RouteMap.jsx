import { useEffect } from 'react'
import { CircleMarker, GeoJSON, MapContainer, TileLayer, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'

function FitRoutes({ features }) {
  const map = useMap()

  useEffect(() => {
    const coordinates = features.flatMap(feature => feature.geometry.coordinates)
    if (coordinates.length === 0) return

    const bounds = coordinates.map(([longitude, latitude]) => [latitude, longitude])
    map.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 })
  }, [features, map])

  return null
}

function RouteMap({ result, selectedRoute, onSelectRoute }) {
  const selectedLast = [...result.features].sort((a, b) => {
    if (a.properties.route_id === selectedRoute) return 1
    if (b.properties.route_id === selectedRoute) return -1
    return 0
  })
  const firstCoordinates = result.features[0].geometry.coordinates
  const start = firstCoordinates[0]
  const destination = firstCoordinates[firstCoordinates.length - 1]

  return (
    <div style={{ height: '420px', width: '100%', margin: '1rem 0', borderRadius: '8px', overflow: 'hidden' }}>
      <MapContainer
        center={[0, 0]}
        zoom={2}
        scrollWheelZoom
        style={{ height: '100%', width: '100%' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <GeoJSON
          key={selectedRoute}
          data={{ type: 'FeatureCollection', features: selectedLast }}
          style={feature => {
            const routeId = feature.properties.route_id
            const selected = routeId === selectedRoute
            return {
              color: routeId === 'route_a' ? '#1a73e8' : '#188038',
              weight: selected ? 7 : 4,
              opacity: selected ? 1 : 0.45,
            }
          }}
          onEachFeature={(feature, layer) => {
            layer.on('click', () => onSelectRoute(feature.properties.route_id))
          }}
        />
        <CircleMarker center={[start[1], start[0]]} radius={6} pathOptions={{ color: '#202124', fillColor: '#fff', fillOpacity: 1 }} />
        <CircleMarker center={[destination[1], destination[0]]} radius={6} pathOptions={{ color: '#202124', fillColor: '#fff', fillOpacity: 1 }} />
        <FitRoutes features={result.features} />
      </MapContainer>
    </div>
  )
}

export default RouteMap
