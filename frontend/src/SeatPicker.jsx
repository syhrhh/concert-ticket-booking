import { useEffect, useMemo, useState } from 'react';
import ArenaOverview from './ArenaOverview';
import './arena-overview.css';
import { aisleAfter, buildSeatLayout, seatPosition } from './seatLayout.mjs';
import './seat-map.css';

function ChairIcon({ className = '' }) {
  return <svg className={className} viewBox="0 0 38 38" role="presentation" aria-hidden="true" focusable="false">
    <rect className="chair-back" x="7" y="3" width="24" height="25" rx="5" />
    <path className="chair-frame" d="M7 23H5a3 3 0 0 0-3 3v8h34v-8a3 3 0 0 0-3-3h-2M7 30V16m24 14V16" />
    <path className="chair-base" d="M7 34v2m24-2v2" />
  </svg>;
}

function RefreshSymbol() {
  return <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5"/><path d="M5.5 9a7 7 0 0 1 12.6-2.4L20 12M4 12l1.9 5.4A7 7 0 0 0 18.5 15"/></svg>;
}

function SeatButton({ seat, number, selected, onSeatSelect, money }) {
  const available = seat.status === 'AVAILABLE';
  const state = selected ? 'selected' : available ? 'available' : 'unavailable';
  const description = `${seat.section || 'General'} section, row ${seat.row_number || '?'}, seat ${seat.seat_number}, ${money(seat.price)}, ${selected ? 'selected' : seat.status.toLowerCase()}`;
  return <button
    type="button"
    className={`theater-chair ${state}`}
    disabled={!available}
    aria-label={description}
    aria-pressed={selected}
    title={description}
    data-seat-id={seat.seat_id}
    onClick={() => onSeatSelect(seat)}
  >
    <ChairIcon className="theater-chair-icon" />
    <span className="theater-chair-number">{number || seat.seat_number}</span>
  </button>;
}

/**
 * Seat-map UI only. All inventory and booking state remains owned by the APIs.
 * Selected seat is still passed back to the existing App.jsx booking workflow.
 */
export default function SeatPicker({
  concert, seats, selectedSeatId, onSeatSelect, loading, error, onRefresh,
  availableCount, selectedSeat, money,
}) {
  const zones = useMemo(() => buildSeatLayout(seats), [seats]);
  const [zoom, setZoom] = useState(1);
  const [activeSection, setActiveSection] = useState(null);
  useEffect(() => { setActiveSection(null); setZoom(1); }, [concert.concert_id]);
  useEffect(() => { if (activeSection && !loading && !zones.some(zone => zone.section === activeSection)) setActiveSection(null); }, [activeSection, loading, zones]);
  const selectedZone = zones.find(zone => zone.section === activeSection);
  const showDetail = Boolean(selectedZone);

  return <div className="seat-map seat-map-cinema glass-surface">
    <div className="seat-map-header">
      <div>
        <span className="eyebrow small">INTERACTIVE SEATING CHART</span>
        <h3>{concert.concert_name}</h3>
        <p><span className="map-location-mark" aria-hidden="true">⌖</span>{concert.venue}</p>
      </div>
      <button type="button" className="small-refresh" onClick={onRefresh} aria-label="Refresh seat availability" title="Refresh seat availability"><RefreshSymbol/></button>
    </div>

    {loading ? <div className="seats-status"><div className="spinner"/> Checking current seat availability...</div>
      : error ? <div className="seat-load-error" role="alert"><strong>Seats unavailable</strong><p>{error}</p><button className="button-outline" type="button" onClick={onRefresh}><RefreshSymbol/> Try again</button></div>
      : zones.length === 0 ? <div className="seats-status">No seats are configured for this concert.</div>
      : !showDetail ? <ArenaOverview zones={zones} money={money} selectedSeat={selectedSeat} onSelect={section => { if (selectedSeat && selectedSeat.section !== section) onSeatSelect(selectedSeat); setActiveSection(section); setZoom(1); }} />
      : <div className="seat-detail-screen" data-testid="seat-detail">
        <div className="arena-detail-top">
          <button type="button" className="arena-back-button" onClick={() => setActiveSection(null)} aria-label="Back to venue sections">← <span>All sections</span></button>
          <div className="arena-detail-title"><span className="eyebrow small">STEP 02 / SELECT YOUR SEAT</span><h4>{selectedZone.section}</h4><p>{selectedZone.rows.reduce((total,row)=>total+row.slots.filter(seat=>seat?.status==='AVAILABLE').length,0)} available seats in this section</p></div>
        </div>
        <div className="cinema-stage" aria-label="Stage is at the front of this seating chart"><span className="cinema-stage-caption">FRONT OF STAGE</span><div className="cinema-stage-edge"/><span className="cinema-stage-glow"/></div>
        <div className="cinema-toolbar"><div className="cinema-legend" aria-label="Seat status legend"><span><i className="cinema-legend-dot available"/> Available</span><span><i className="cinema-legend-dot selected"/> Selected</span><span><i className="cinema-legend-dot unavailable"/> Unavailable</span><span><i className="cinema-legend-dot gap"/> Not configured</span></div><div className="cinema-zoom" aria-label="Seat map size"><button type="button" onClick={() => setZoom(value => Math.max(.8, Number((value - .1).toFixed(1))))} disabled={zoom <= .8} aria-label="Make seats smaller">−</button><output aria-live="off">{Math.round(zoom * 100)}%</output><button type="button" onClick={() => setZoom(value => Math.min(1.2, Number((value + .1).toFixed(1))))} disabled={zoom >= 1.2} aria-label="Make seats larger">+</button></div></div>
        <div className="cinema-viewport" role="region" tabIndex={0} aria-label="Individual seats in chosen section; scroll horizontally to view all seats">
        <div className="cinema-zones" style={{ '--chair-size': `${Math.round(29 * zoom)}px`, '--chair-gap': `${Math.round(5 * zoom)}px` }}>
          {[selectedZone].map(zone => {
            const aisles = aisleAfter(zone.columns);
            return <section className="cinema-zone" key={zone.section} aria-label={`${zone.section} seats`}>
              <div className="cinema-zone-heading">
                <span className="cinema-zone-name"><span className="zone-dash"/>{zone.section}</span>
                <span className="cinema-zone-meta">{zone.prices.length === 1 ? money(zone.prices[0]) : zone.prices.length > 1 ? `${money(zone.prices[0])} – ${money(zone.prices.at(-1))}` : 'Price unavailable'} / seat</span>
              </div>
              <div className="cinema-rows">
                {zone.rows.map(row => <div className="cinema-row" key={`${zone.section}:${row.label}`}>
                  <span className="cinema-row-label" aria-hidden="true">{row.label}</span>
                  <div className="cinema-row-chairs">
                    {row.slots.map((seat, index) => <div
                      className={`cinema-position ${aisles.includes(index + 1) && index + 1 < zone.columns ? 'cinema-before-aisle' : ''}`}
                      key={seat ? `seat-${seat.seat_id}` : `empty-${zone.section}-${row.label}-${index}`}
                    >
                      {seat ? <SeatButton
                        seat={seat}
                        number={seatPosition(seat) ?? seat.seat_number}
                        selected={selectedSeatId === seat.seat_id}
                        onSeatSelect={onSeatSelect}
                        money={money}
                      /> : <span className="cinema-empty-position" aria-hidden="true"/>}
                    </div>)}
                  </div>
                  <span className="cinema-row-label" aria-hidden="true">{row.label}</span>
                </div>)}
              </div>
            </section>;
          })}
        </div>
      </div>
      </div>
    }

    <div className="cinema-selected-summary" aria-live="polite">
      <div className="cinema-selected-left">
        <span className={`selected-indicator ${selectedSeat ? 'has-selection' : ''}`}/>
        <div><small>{selectedSeat ? 'YOUR SELECTION' : 'PICK YOUR PERFECT VIEW'}</small><strong>{selectedSeat ? `${selectedSeat.section || 'General'} · Row ${selectedSeat.row_number || '?'} · Seat ${selectedSeat.seat_number}` : showDetail ? 'Tap an available chair above to select it' : 'Choose a section above to see its available seats'}</strong></div>
      </div>
      {selectedSeat && <strong className="selected-seat-price">{money(selectedSeat.price)}</strong>}
    </div>
    <div className="seat-map-footer">
      <span className="seat-map-foot-icon" aria-hidden="true">ⓘ</span>
      <span><strong>{availableCount}</strong> seat{availableCount === 1 ? '' : 's'} available. Only seats returned by the Availability Service can be selected. Availability may change before confirmation.</span>
    </div>
  </div>;
}
