import { useCallback, useEffect, useMemo, useState } from "react";
import { MapContainer, Marker, Popup, TileLayer, Polyline, Polygon, useMap, useMapEvents } from "react-leaflet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LocateFixed, MapPinned, Route, X, Save, MapPinPlus } from "lucide-react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

interface CampusLocation {
  id: string;
  name: string;
  department?: string;
  latitude: number;
  longitude: number;
  description?: string;
  aliases?: string[];
  floor?: string | number | null;
  room?: string | null;
  source?: string;
  verified?: boolean;
}

interface CampusLocationSuggestion {
  id: string;
  name: string;
  aliases: string[];
  description: string;
  verified: false;
}

interface CampusRouteResponse {
  start: string;
  end: string;
  distance_m: number;
  route: string[];
  path_coordinates: [number, number][];
  estimated_walking_minutes: number;
  steps: Array<{
    from: string;
    to: string;
    instruction: string;
    distance_m: number;
  }>;
}

interface CampusLocationsResponse {
  locations: CampusLocation[];
  suggestions?: CampusLocationSuggestion[];
  boundary: [number, number][];
  boundary_source: string;
}

const campusCenter: [number, number] = [19.0221717, 72.8562039];
const placementsUrl = "https://vjti.ac.in/training-and-placement-office/";

const pinIcon = (color: string) =>
  L.divIcon({
    className: "campus-pin-marker",
    html: `<span style="display:flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:9999px;background:${color};border:2px solid white;box-shadow:0 4px 12px rgba(15,23,42,0.25);"></span>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });

function MapViewport({
  routeCoordinates,
  focusedLocation,
}: {
  routeCoordinates: [number, number][];
  focusedLocation?: CampusLocation;
}) {
  const map = useMap();
  useEffect(() => {
    if (routeCoordinates.length > 1) {
      map.fitBounds(L.latLngBounds(routeCoordinates), { padding: [24, 24] });
    } else if (focusedLocation) {
      map.flyTo([focusedLocation.latitude, focusedLocation.longitude], 17, { duration: 0.5 });
    }
  }, [focusedLocation, map, routeCoordinates]);

  return null;
}

function LocationPicker({
  enabled,
  onPick,
}: {
  enabled: boolean;
  onPick: (coordinates: [number, number]) => void;
}) {
  useMapEvents({
    click(event) {
      if (enabled) {
        onPick([event.latlng.lat, event.latlng.lng]);
      }
    },
  });
  return null;
}

const API_BASE_URL = `${window.location.protocol}//${window.location.hostname}:5000`;

interface CampusMapPanelProps {
  onClose?: () => void;
  focusLocationId?: string;
  focusQuery?: string;
  routeStartId?: string;
  routeEndId?: string;
  isAdmin?: boolean;
}

const CampusMapPanel = ({
  onClose,
  focusLocationId,
  focusQuery,
  routeStartId,
  routeEndId,
  isAdmin = false,
}: CampusMapPanelProps) => {
  const [locations, setLocations] = useState<CampusLocation[]>([]);
  const [suggestions, setSuggestions] = useState<CampusLocationSuggestion[]>([]);
  const [boundary, setBoundary] = useState<[number, number][]>([]);
  const [boundarySource, setBoundarySource] = useState("");
  const [search, setSearch] = useState("");
  const [route, setRoute] = useState<CampusRouteResponse | null>(null);
  const [startId, setStartId] = useState("");
  const [endId, setEndId] = useState("vjti_campus");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [isPickingLocation, setIsPickingLocation] = useState(false);
  const [draftCoordinates, setDraftCoordinates] = useState<[number, number] | null>(null);
  const [draftName, setDraftName] = useState("");
  const [draftDepartment, setDraftDepartment] = useState("");
  const [draftAliases, setDraftAliases] = useState("");
  const [draftSource, setDraftSource] = useState("");
  const [draftDescription, setDraftDescription] = useState("");
  const [confirmedVerified, setConfirmedVerified] = useState(false);
  const [isSavingLocation, setIsSavingLocation] = useState(false);

  useEffect(() => {
    const fetchLocations = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/campus/locations`, {
          credentials: "include",
        });
        if (!response.ok) {
          throw new Error("Unable to load campus locations.");
        }

        const body: CampusLocationsResponse = await response.json();
        const list = Array.isArray(body.locations) ? body.locations : [];
        setLocations(list);
        setSuggestions(Array.isArray(body.suggestions) ? body.suggestions : []);
        setBoundary(Array.isArray(body.boundary) ? body.boundary : []);
        setBoundarySource(body.boundary_source ?? "");
        if (list.length > 0) {
          setStartId(routeStartId ?? "");
          setEndId(
            routeEndId ??
              focusLocationId ??
              list[0].id,
          );
        }
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Could not load the campus map.");
      } finally {
        setIsLoading(false);
      }
    };

    fetchLocations();
  }, [focusLocationId, routeEndId, routeStartId]);

  useEffect(() => {
    if (focusQuery) {
      setSearch(focusQuery);
    }
    if (focusLocationId && locations.length) {
      const focused = locations.find((location) => location.id === focusLocationId);
      if (focused) {
        setEndId(focused.id);
        setSearch(focused.name);
      }
    }
  }, [focusLocationId, focusQuery, locations, routeEndId, routeStartId]);

  const filteredLocations = useMemo(() => {
    const value = search.trim().toLowerCase();
    if (!value) return locations;
    return locations.filter((location) => {
      const haystack = [
        location.name,
        location.department ?? "",
        location.description ?? "",
        ...(location.aliases ?? []),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(value);
    });
  }, [locations, search]);

  const filteredSuggestions = useMemo(() => {
    const value = search.trim().toLowerCase();
    if (!value) return suggestions;
    return suggestions.filter((location) =>
      [location.name, ...location.aliases].some((term) => term.toLowerCase().includes(value)),
    );
  }, [search, suggestions]);

  const requestDirections = useCallback(async (start: string, end: string) => {
    if (!start || !end || start === end) {
      setRoute(null);
      setError("Choose two different campus locations to get directions.");
      return;
    }

    const locationNeedingPin = suggestions.find(
      (location) => location.id === start || location.id === end,
    );
    if (locationNeedingPin) {
      setRoute(null);
      setError(
        `${locationNeedingPin.name} does not have a verified map pin yet. An administrator must verify and add its building entrance before it can be routed.`,
      );
      return;
    }

    setError("");
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/campus/route?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
        { credentials: "include" },
      );

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.message || "Walking route unavailable: no verified campus pathway connects these locations.");
      }

      const body = await response.json();
      setRoute(body);
      if (!Array.isArray(body.path_coordinates) || body.path_coordinates.length < 2) {
        setRoute(null);
        setError("Walking route unavailable: verified pathway geometry is not configured.");
      }
    } catch (routeError) {
      setError(routeError instanceof Error ? routeError.message : "Route not available.");
      setRoute(null);
    }
  }, [suggestions]);

  const clearRoute = () => {
    setRoute(null);
    setError("");
  };

  const saveLocation = async () => {
    if (!draftCoordinates || !draftName.trim() || !draftSource.trim() || !confirmedVerified) {
      setError("Select a map point and enter its name and source, then confirm it is verified.");
      return;
    }

    setIsSavingLocation(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/campus/locations`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: draftName.trim(),
          department: draftDepartment.trim(),
          aliases: draftAliases.split(",").map((alias) => alias.trim()).filter(Boolean),
          description: draftDescription.trim(),
          source: draftSource.trim(),
          latitude: draftCoordinates[0],
          longitude: draftCoordinates[1],
          verified: confirmedVerified,
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.error || "Unable to save verified location.");
      }
      setLocations((current) => [...current, body.location]);
      setSuggestions((current) =>
        current.filter(
          (suggestion) => suggestion.name.toLowerCase() !== body.location.name.toLowerCase(),
        ),
      );
      setEndId(body.location.id);
      setSearch(body.location.name);
      setDraftName("");
      setDraftDepartment("");
      setDraftAliases("");
      setDraftDescription("");
      setDraftSource("");
      setDraftCoordinates(null);
      setConfirmedVerified(false);
      setIsPickingLocation(false);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Unable to save verified location.");
    } finally {
      setIsSavingLocation(false);
    }
  };

  const routeCoordinates = useMemo(() => {
    return route?.path_coordinates ?? [];
  }, [route]);

  useEffect(() => {
    if (!routeStartId || !routeEndId || !locations.length) return;
    const startExists = locations.some((location) => location.id === routeStartId);
    const endExists = locations.some((location) => location.id === routeEndId);
    if (!startExists || !endExists) return;
    setStartId(routeStartId);
    setEndId(routeEndId);
    void requestDirections(routeStartId, routeEndId);
  }, [locations, requestDirections, routeEndId, routeStartId]);

  const focusedLocation = locations.find((location) => location.id === focusLocationId);
  const hasSelectedSuggestion = suggestions.some(
    (suggestion) => suggestion.id === startId || suggestion.id === endId,
  );
  const showSuggestionDetails = Boolean(search.trim()) || hasSelectedSuggestion;
  const tpoSearch = /\b(tpo|training and placement office|placement office)\b/i.test(search);

  return (
    <div className="rounded-2xl border border-border/70 bg-card/80 p-4 shadow-card backdrop-blur-sm">
      <div className="mb-4 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <MapPinned className="h-5 w-5 text-primary" />
          <h2 className="text-lg font-semibold">VJTI Campus Map</h2>
        </div>
        {onClose && (
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close campus map">
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      <div className="mb-4 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search buildings or departments"
          aria-label="Search campus buildings"
          className="h-10 min-w-0 w-full"
        />
        <label className="grid min-w-0 gap-1 text-xs text-muted-foreground">
          <span>From</span>
          <select
            aria-label="Route starting location"
            className="h-10 min-w-0 rounded-md border border-input bg-background px-3 text-sm text-foreground"
            value={startId}
            onChange={(event) => setStartId(event.target.value)}
          >
            <option value="">Select a starting location</option>
            <optgroup label="Verified map locations">
              {locations.map((location) => (
                <option key={location.id} value={location.id}>{location.name}</option>
              ))}
            </optgroup>
            {suggestions.length > 0 && (
              <optgroup label="Known locations — pin needs verification">
                {suggestions.map((location) => (
                  <option key={location.id} value={location.id}>{location.name} (pin needed)</option>
                ))}
              </optgroup>
            )}
          </select>
        </label>
        <label className="grid min-w-0 gap-1 text-xs text-muted-foreground">
          <span>To</span>
          <select
            aria-label="Route destination"
            className="h-10 min-w-0 rounded-md border border-input bg-background px-3 text-sm text-foreground"
            value={endId}
            onChange={(event) => setEndId(event.target.value)}
          >
            <option value="">Select a destination</option>
            <optgroup label="Verified map locations">
              {locations.map((location) => (
                <option key={location.id} value={location.id}>{location.name}</option>
              ))}
            </optgroup>
            {suggestions.length > 0 && (
              <optgroup label="Known locations — pin needs verification">
                {suggestions.map((location) => (
                  <option key={location.id} value={location.id}>{location.name} (pin needed)</option>
                ))}
              </optgroup>
            )}
          </select>
        </label>
        <Button onClick={() => void requestDirections(startId, endId)} className="h-10 self-end gap-2" variant="default">
          <Route className="h-4 w-4" />
          Directions
        </Button>
      </div>

      {isAdmin && (
        <div className="mb-4 rounded-lg border border-border bg-muted/30 p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-medium">Add an administrator-verified campus location</p>
            <Button
              variant={isPickingLocation ? "default" : "outline"}
              size="sm"
              onClick={() => {
                setIsPickingLocation((active) => !active);
                setDraftCoordinates(null);
              }}
            >
              <MapPinPlus className="mr-2 h-4 w-4" />
              {isPickingLocation ? "Cancel point selection" : "Select point on map"}
            </Button>
          </div>
          {isPickingLocation && (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Input value={draftName} onChange={(event) => setDraftName(event.target.value)} placeholder="Building or facility name" aria-label="New location name" />
              <Input value={draftDepartment} onChange={(event) => setDraftDepartment(event.target.value)} placeholder="Department (optional)" aria-label="New location department" />
              <Input value={draftAliases} onChange={(event) => setDraftAliases(event.target.value)} placeholder="Aliases, comma separated" aria-label="Location search aliases" />
              <Input value={draftSource} onChange={(event) => setDraftSource(event.target.value)} placeholder="Verification source (OSM URL or survey reference)" aria-label="Location verification source" />
              <Input value={draftDescription} onChange={(event) => setDraftDescription(event.target.value)} placeholder="Description (optional)" aria-label="Location description" />
              <p className="self-center text-xs text-muted-foreground">
                {draftCoordinates
                  ? `Selected: ${draftCoordinates[0].toFixed(6)}, ${draftCoordinates[1].toFixed(6)}`
                  : "Click the map at the verified building entrance."}
              </p>
              <label className="flex items-start gap-2 text-xs text-muted-foreground sm:col-span-2">
                <input type="checkbox" checked={confirmedVerified} onChange={(event) => setConfirmedVerified(event.target.checked)} />
                I verified this point against the cited map or an on-site survey; this is not an estimated pin.
              </label>
              <Button onClick={() => void saveLocation()} disabled={isSavingLocation} className="sm:col-span-2 sm:justify-self-end">
                <Save className="mr-2 h-4 w-4" />
                {isSavingLocation ? "Saving..." : "Save verified location"}
              </Button>
            </div>
          )}
        </div>
      )}

      {error && <p className="mb-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">{error}</p>}
      {!isLoading && search.trim() && filteredLocations.length === 0 && filteredSuggestions.length === 0 && (
        <p className="mb-3 text-sm text-muted-foreground">No campus location matches “{search}”.</p>
      )}
      {showSuggestionDetails && filteredSuggestions.length > 0 && (
        <div className="mb-3 space-y-2">
          {filteredSuggestions.map((suggestion) => (
            <div key={suggestion.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2">
              <p className="text-sm">
                <span className="font-medium">{suggestion.name}</span>
                <span className="text-muted-foreground"> — no verified map pin yet.</span>
              </p>
              {isAdmin && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setDraftName(suggestion.name);
                    setDraftAliases(suggestion.aliases.join(", "));
                    setDraftDepartment("");
                    setDraftDescription("");
                    setDraftCoordinates(null);
                    setDraftSource("");
                    setConfirmedVerified(false);
                    setIsPickingLocation(true);
                    setError("");
                  }}
                >
                  <MapPinPlus className="mr-2 h-4 w-4" />
                  Verify map pin
                </Button>
              )}
            </div>
          ))}
          {tpoSearch && (
            <p className="text-sm text-muted-foreground">
              The map cannot confirm the TPO building or room. For current office details, visit{" "}
              <a href={placementsUrl} target="_blank" rel="noopener noreferrer" className="font-medium text-primary underline underline-offset-2">
                VJTI’s official TPO page
              </a>.
            </p>
          )}
        </div>
      )}

      <div className="relative overflow-hidden rounded-xl border border-border">
        <MapContainer center={campusCenter} zoom={16} scrollWheelZoom className="h-[360px] w-full" zoomControl>
          <TileLayer
            attribution="&copy; OpenStreetMap contributors"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {boundary.length > 0 && (
            <Polygon
              positions={boundary}
              pathOptions={{ color: "#0f766e", fillColor: "#14b8a6", fillOpacity: 0.08, weight: 2 }}
            />
          )}
          <LocationPicker enabled={isPickingLocation} onPick={setDraftCoordinates} />
          <MapViewport routeCoordinates={routeCoordinates} focusedLocation={focusedLocation} />
          {filteredLocations.map((location) => (
            <Marker
              key={location.id}
              position={[location.latitude, location.longitude]}
              icon={pinIcon(
                location.id === startId ? "#2563eb" : location.id === endId ? "#16a34a" : "#f97316",
              )}
            >
              <Popup>
                <div className="space-y-1 text-sm">
                  <p className="font-semibold">{location.name}</p>
                  {location.department && <p>{location.department}</p>}
                  {location.description && <p className="text-muted-foreground">{location.description}</p>}
                  {location.room && <p>Room: {location.room}</p>}
                </div>
              </Popup>
            </Marker>
          ))}
          {draftCoordinates && (
            <Marker position={draftCoordinates} icon={pinIcon("#7c3aed")} />
          )}
          {routeCoordinates.length > 1 && <Polyline positions={routeCoordinates} pathOptions={{ color: "#2563eb", weight: 5 }} />}
        </MapContainer>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <LocateFixed className="h-4 w-4" />
          <span>
            {isLoading
              ? "Loading campus data..."
              : `${filteredLocations.length} verified map points · ${filteredSuggestions.length} place names need pins`}
          </span>
        </div>
        <Button variant="outline" size="sm" onClick={clearRoute}>Reset route</Button>
      </div>
      {boundarySource && (
        <p className="mt-2 text-xs text-muted-foreground">
          Campus boundary and reference point:{" "}
          <a href={boundarySource} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
            OpenStreetMap contributors
          </a>
          . Internal building entrances and pathways need verification.
        </p>
      )}

      {route && (
        <div className="mt-4 rounded-lg border border-border bg-muted/40 p-3 text-sm">
          <p className="font-semibold">Route summary</p>
          <p className="mt-1">
            {route.distance_m} metres · approximately {route.estimated_walking_minutes} minutes
          </p>
        </div>
      )}
    </div>
  );
};

export default CampusMapPanel;
