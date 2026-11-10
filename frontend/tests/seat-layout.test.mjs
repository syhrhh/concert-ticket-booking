import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSeatLayout, aisleAfter, seatPosition } from '../src/seatLayout.mjs';

const sample = [
  { seat_id: 1, concert_id: 1, section: 'VIP', row_number: 'A', seat_number: 'A1', price: 250, status: 'AVAILABLE' },
  { seat_id: 2, concert_id: 1, section: 'VIP', row_number: 'A', seat_number: 'A2', price: 250, status: 'BOOKED' },
  { seat_id: 3, concert_id: 1, section: 'VIP', row_number: 'A', seat_number: 'A3', price: 250, status: 'AVAILABLE' },
  { seat_id: 9, concert_id: 1, section: 'VIP', row_number: 'A', seat_number: 'A12', price: 250, status: 'AVAILABLE' },
  { seat_id: 10, concert_id: 1, section: 'VIP', row_number: 'A', seat_number: 'A13', price: 250, status: 'AVAILABLE' },
  { seat_id: 11, concert_id: 1, section: 'VIP', row_number: 'A', seat_number: 'A14', price: 250, status: 'AVAILABLE' },
  { seat_id: 4, concert_id: 1, section: 'STANDARD', row_number: 'B', seat_number: 'B1', price: 120, status: 'AVAILABLE' },
  { seat_id: 5, concert_id: 1, section: 'STANDARD', row_number: 'B', seat_number: 'B2', price: 120, status: 'AVAILABLE' },
  { seat_id: 6, concert_id: 1, section: 'STANDARD', row_number: 'B', seat_number: 'B3', price: 120, status: 'AVAILABLE' },
];

test('projects API seat numbers into physical columns without inventing selectable seats', () => {
  const [vip, standard] = buildSeatLayout(sample);
  assert.equal(vip.section, 'VIP');
  assert.equal(vip.columns, 14);
  assert.equal(vip.rows[0].slots[0].seat_number, 'A1');
  assert.equal(vip.rows[0].slots[11].seat_number, 'A12');
  assert.equal(vip.rows[0].slots[3], null); // A4 does not exist in backend.
  assert.equal(standard.section, 'STANDARD');
  assert.equal(standard.columns, 3);
  const allRendered = [vip, standard].flatMap(zone => zone.rows.flatMap(row => row.slots.filter(Boolean)));
  assert.equal(allRendered.length, sample.length);
  assert.deepEqual(new Set(allRendered.map(seat => seat.seat_id)), new Set(sample.map(seat => seat.seat_id)));
});

test('preserves availability status, price and seat IDs from API records', () => {
  const layout = buildSeatLayout(sample);
  const booked = layout[0].rows[0].slots[1];
  assert.deepEqual({ id: booked.seat_id, status: booked.status, price: booked.price }, {
    id: 2, status: 'BOOKED', price: 250,
  });
  assert.deepEqual(layout[0].prices, [250]);
});

test('orders sections and seat identifiers numerically instead of alphabetically', () => {
  const layout = buildSeatLayout([
    { seat_id: 7, section: 'GENERAL', row_number: 'B', seat_number: 'B10' },
    { seat_id: 8, section: 'GENERAL', row_number: 'B', seat_number: 'B2' },
    { seat_id: 9, section: 'VIP', row_number: 'A', seat_number: 'A1' },
  ]);
  assert.deepEqual(layout.map(z => z.section), ['VIP', 'GENERAL']);
  assert.equal(layout[1].rows[0].slots[1].seat_number, 'B2');
  assert.equal(layout[1].rows[0].slots[9].seat_number, 'B10');
});

test('unusual labels fall back to compact layout and remain selectable', () => {
  const layout = buildSeatLayout([
    { seat_id: 1, section: 'Balcony', row_number: 'C', seat_number: 'left' },
    { seat_id: 2, section: 'Balcony', row_number: 'C', seat_number: 'right' },
  ]);
  assert.equal(layout[0].columns, 2);
  assert.equal(layout[0].rows[0].slots.filter(Boolean).length, 2);
});

test('supports multiple rows with aligned slots and visual aisle breaks', () => {
  const seats = [];
  for (const row of ['A', 'B']) for (let n = 1; n <= 18; n++) {
    seats.push({ seat_id: `${row}${n}`, section: 'STANDARD', row_number: row, seat_number: `${row}${n}`, price: 120, status: 'AVAILABLE' });
  }
  const [zone] = buildSeatLayout(seats);
  assert.equal(zone.rows.length, 2);
  assert.equal(zone.columns, 18);
  assert.deepEqual(aisleAfter(18), [4, 14]);
  assert.deepEqual(aisleAfter(3), []);
  assert.equal(seatPosition({ seat_number: 'VIP-A14' }), 14);
});
