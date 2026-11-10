/**
 * Layout-only helpers for visualizing real seats from the Availability API.
 * Nothing here changes a booking, creates an inventory item or assumes an empty
 * grid position is a seat. A position without backend seat_id is NEVER clickable.
 */
const priority = ['VIP', 'PREMIUM', 'GOLD', 'STANDARD', 'GENERAL', 'BALCONY'];

const naturalCompare = (a, b) => String(a).localeCompare(String(b), undefined, {
  numeric: true, sensitivity: 'base',
});

/** Extract numeric suffix from seat identifiers like A12, A-12 or 12. */
export function seatPosition(seat) {
  const label = String(seat.seat_number ?? '');
  const match = label.match(/(\d+)\s*$/);
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isSafeInteger(value) && value >= 1 ? value : null;
}

function sectionOrder(a, b) {
  const ia = priority.indexOf(a.toUpperCase());
  const ib = priority.indexOf(b.toUpperCase());
  if (ia !== ib) return (ia === -1 ? priority.length : ia) - (ib === -1 ? priority.length : ib);
  return naturalCompare(a, b);
}

/**
 * Builds visual zones and row slots from seat records returned by the API.
 * Missing slot = null, indicating empty venue space, NOT a bookable seat.
 * If labels aren't suitable for numeric positioning, use compact ordered slots.
 */
export function buildSeatLayout(seats) {
  const bySection = new Map();
  for (const seat of Array.isArray(seats) ? seats : []) {
    const section = String(seat.section || 'General').trim();
    const rowName = String(seat.row_number || '?').trim();
    if (!bySection.has(section)) bySection.set(section, new Map());
    const rows = bySection.get(section);
    if (!rows.has(rowName)) rows.set(rowName, []);
    rows.get(rowName).push(seat);
  }

  return [...bySection.entries()]
    .sort(([a], [b]) => sectionOrder(a, b))
    .map(([section, rowsMap]) => {
      const rows = [...rowsMap.entries()]
        .sort(([a], [b]) => naturalCompare(a, b))
        .map(([label, rowSeats]) => {
          const ordered = [...rowSeats].sort((a, b) => naturalCompare(a.seat_number, b.seat_number));
          return { label, seats: ordered };
        });

      const allSeats = rows.flatMap(row => row.seats);
      const positions = allSeats.map(seatPosition);
      const maxSeatNumber = Math.max(0, ...positions.filter(Boolean));
      const numericPositions = positions.every(p => p !== null)
        && new Set(rows.flatMap(row => row.seats.map(seat => `${row.label}:${seatPosition(seat)}`))).size === allSeats.length;

      // Cap numeric projection to avoid exceptionally numbered labels producing
      // a 100-column viewport. Real seats always remain rendered and selectable.
      const positional = numericPositions && maxSeatNumber <= 32;
      const columns = positional
        ? maxSeatNumber
        : Math.max(0, ...rows.map(row => row.seats.length));

      const renderedRows = rows.map(row => {
        const slots = Array.from({ length: columns }, () => null);
        row.seats.forEach((seat, index) => {
          const position = positional ? seatPosition(seat) - 1 : index;
          slots[position] = seat;
        });
        return { label: row.label, slots };
      });

      const prices = [...new Set(allSeats.map(seat => Number(seat.price)).filter(Number.isFinite))]
        .sort((a, b) => a - b);
      return { section, rows: renderedRows, columns, prices, seatCount: allSeats.length };
    });
}

/** Aisles are purely visual spacing; they never alter seat identifiers. */
export function aisleAfter(columnCount) {
  if (columnCount >= 12) {
    const side = Math.max(3, Math.round(columnCount * 0.24));
    return [side, columnCount - side];
  }
  if (columnCount >= 8) return [Math.floor(columnCount / 2)];
  return [];
}
