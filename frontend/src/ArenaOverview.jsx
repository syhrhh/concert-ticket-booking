import { buildArenaPieces, sectionAvailable } from './arenaLayout.mjs';

/** Overview is a navigational schematic. Actual inventory always comes from the API. */
export default function ArenaOverview({ zones, money, onSelect, selectedSeats = [] }) {
  const pieces = buildArenaPieces(zones);
  return <div className="arena-overview" data-testid="arena-overview">
    <div className="arena-intro">
      <span className="eyebrow small">STEP 01 / CHOOSE YOUR SECTION</span>
      <h4>Where do you want to be?</h4>
      <p>Select a colored section to see the individual seats and their live availability.</p>
    </div>

    <div className="arena-diagram" role="group" aria-label="Interactive concert venue section map">
      <svg className="arena-svg" viewBox="0 0 880 485" role="group" aria-label="Schematic arena map. Select a section below or activate a colored section on the map.">
        <defs>
          <radialGradient id="arena-floor-glow"><stop offset="0" stopColor="#7d345e" stopOpacity=".30"/><stop offset="1" stopColor="#15131c" stopOpacity=".06"/></radialGradient>
          <linearGradient id="arena-stage-gradient" x1="0" x2="1"><stop stopColor="#f5d98d"/><stop offset=".55" stopColor="#f49ba7"/><stop offset="1" stopColor="#ee4d92"/></linearGradient>
          <filter id="arena-halo" x="-40%" y="-80%" width="180%" height="260%"><feGaussianBlur stdDeviation="10"/></filter>
        </defs>
        <ellipse cx="440" cy="287" rx="158" ry="102" fill="url(#arena-floor-glow)"/>
        <path d="M332 98 Q440 70 548 98 L528 137 Q440 117 352 137 Z" fill="#1d1a24" stroke="url(#arena-stage-gradient)" strokeWidth="2"/>
        <path d="M345 100 Q440 77 535 100" fill="none" stroke="#F78AA6" strokeWidth="8" opacity=".22" filter="url(#arena-halo)"/>
        <text x="440" y="108" textAnchor="middle" className="arena-stage-text">S T A G E</text>
        <text x="440" y="221" textAnchor="middle" className="arena-center-title">ENCORE</text>
        <text x="440" y="243" textAnchor="middle" className="arena-center-subtitle">THE LIVE EXPERIENCE</text>
        {pieces.map(piece => {
          const zone = zones.find(z => z.section === piece.section);
          const available = sectionAvailable(zone);
          const aria = `${piece.section}, ${available} available out of ${zone.seatCount} seats. View seats`;
          return <g key={piece.section} className="arena-piece" tabIndex={0} role="button" aria-label={aria}
            onClick={() => onSelect(piece.section)}
            onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(piece.section); } }}
            style={{ '--arena-piece-color':piece.color }}>
            <path className="arena-piece-shape" d={piece.path} fill={piece.color} fillOpacity=".68" stroke="#15131d" strokeWidth="5"/>
            <text x={piece.labelX} y={piece.labelY+4} textAnchor="middle" className="arena-piece-label">{piece.section.length > 12 ? `${piece.section.slice(0,10)}…` : piece.section}</text>
          </g>;
        })}
        <path d="M76 170 Q50 260 90 352" stroke="#ED8CA5" strokeOpacity=".22" strokeWidth="1.5" fill="none" strokeDasharray="4 7"/>
        <path d="M804 170 Q830 260 790 352" stroke="#ED8CA5" strokeOpacity=".22" strokeWidth="1.5" fill="none" strokeDasharray="4 7"/>
      </svg>
    </div>

    <div className="arena-section-heading"><strong>Available sections</strong><small>Click to explore seating <span aria-hidden="true">↗</span></small></div>
    <div className="arena-section-list">
      {zones.map((zone,i) => {
        const available = sectionAvailable(zone);
        const price = zone.prices.length === 1 ? money(zone.prices[0]) : zone.prices.length > 1 ? `From ${money(zone.prices[0])}` : 'Price TBA';
        return <button type="button" key={zone.section} className="arena-section-card" onClick={() => onSelect(zone.section)}>
          <span className="arena-section-swatch" style={{ background: pieces[i].color }}/>
          <span className="arena-section-detail"><strong>{zone.section}</strong><small>{available} of {zone.seatCount} seats available {selectedSeats.some(seat => seat.section === zone.section) ? ` · ${selectedSeats.filter(seat => seat.section === zone.section).length} selected` : ''}</small></span>
          <span className="arena-section-price">{price}</span><span className="arena-section-arrow" aria-hidden="true">↗</span>
        </button>;
      })}
    </div>
    <p className="arena-map-disclaimer">Venue layout is illustrative, not to scale. Only actual seats returned by the Availability Service can be booked.</p>
  </div>;
}
