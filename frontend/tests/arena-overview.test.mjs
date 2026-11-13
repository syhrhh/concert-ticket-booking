import test from 'node:test';
import assert from 'node:assert/strict';
import { buildArenaPieces, sectionAvailable } from '../src/arenaLayout.mjs';
import { buildSeatLayout } from '../src/seatLayout.mjs';

const seats = [
  { seat_id: 11, section: 'VIP', row_number: 'A', seat_number: 'A1', status: 'AVAILABLE', price: 250 },
  { seat_id: 12, section: 'VIP', row_number: 'A', seat_number: 'A2', status: 'BOOKED', price: 250 },
  { seat_id: 13, section: 'STANDARD', row_number: 'B', seat_number: 'B1', status: 'AVAILABLE', price: 120 },
];

test('the overview creates one clickable map piece per real API section', () => {
  const zones = buildSeatLayout(seats);
  const shapes = buildArenaPieces(zones);
  assert.deepEqual(shapes.map(shape => shape.section), zones.map(zone => zone.section));
  assert.equal(shapes.length, 2);
  assert.notEqual(shapes[0].path, shapes[1].path);
  for (const shape of shapes) {
    assert.match(shape.path, /^M/);
    assert.ok(shape.path.endsWith(' Z'));
    assert.ok(Number.isFinite(shape.labelX));
  }
});

test('overview availability is calculated from actual seat status, not artwork', () => {
  const zones = buildSeatLayout(seats);
  assert.equal(zones[0].seatCount, 2);
  assert.equal(sectionAvailable(zones[0]), 1);
  assert.equal(sectionAvailable(zones[1]), 1);
  assert.equal(sectionAvailable({rows:[]}), 0);
});

test('works with empty, single and many backend sections without inventing zones', () => {
  assert.deepEqual(buildArenaPieces([]), []);
  const one = buildArenaPieces([{section:'VIP'}]);
  assert.equal(one.length, 1);
  const ten = buildArenaPieces(Array.from({length:10}, (_,i)=>({section:`${i+101}`})));
  assert.equal(ten.length, 10);
  assert.equal(new Set(ten.map(s => s.section)).size, 10);
  assert.equal(new Set(ten.map(s => s.path)).size, 10);
});
