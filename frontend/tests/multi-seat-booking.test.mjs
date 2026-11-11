import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_SEATS_PER_CHECKOUT, toggleSeatId, reconcileSeatIds,
  createCheckoutItems, submitCheckoutItems, checkoutCounts
} from '../src/multiSeatBooking.mjs';

const seats = Array.from({length:8}, (_,i)=>({ seat_id:i+1, seat_number:`114-A${String(i+1).padStart(2,'0')}`, status:'AVAILABLE', price:450 }));

test('select/deselect up to six seats', () => {
  let ids = [];
  for (const seat of seats) ids = toggleSeatId(ids, seat.seat_id);
  assert.equal(ids.length, MAX_SEATS_PER_CHECKOUT);
  assert.deepEqual(ids, [1,2,3,4,5,6]);
  assert.deepEqual(toggleSeatId(ids, 3), [1,2,4,5,6]);
  assert.deepEqual(toggleSeatId([1,2,4,5,6], 7), [1,2,4,5,6,7]);
});

test('refresh removes newly unavailable seats but keeps others', () => {
  assert.deepEqual(reconcileSeatIds([1,2,3], [{...seats[0]}, {...seats[1], status:'BOOKED'}, {...seats[2]}]), [1,3]);
});

test('a batch creates unique per-seat keys; the original keys are reused on retry', async () => {
  const items = createCheckoutItems(seats.slice(0,3), (()=> { let n = 0; return ()=>`key-${++n}`; })());
  const calls=[];
  const first = await submitCheckoutItems(items, async params => {
    calls.push(params);
    if (params.seatId === 1) return { data:{booking_id:'B1',status:'CONFIRMED'} };
    if (params.seatId === 2) throw { code:'SEAT_NOT_AVAILABLE', status:409, message:'Seat already taken' };
    throw { code:'TIMEOUT', status:0, message:'Timeout' };
  }, {userId:1,concertId:1});
  assert.deepEqual(first.map(x=>x.state), ['confirmed','rejected','uncertain']);
  assert.deepEqual(calls.map(x=>x.idempotencyKey), ['key-1','key-2','key-3']);
  assert.deepEqual(checkoutCounts(first), { confirmed:1, rejected:1, uncertain:1, pending:0 });
  const retryCalls = [];
  const second = await submitCheckoutItems(first, async params => {
    retryCalls.push(params);
    return {data:{booking_id:'B3',status:'CONFIRMED'}, replay:true};
  }, {userId:1,concertId:1});
  assert.equal(retryCalls.length,1);
  assert.equal(retryCalls[0].idempotencyKey, 'key-3');
  assert.deepEqual(second.map(x=>x.state), ['confirmed','rejected','confirmed']);
});

test('backend unknown/PENDING status is not shown as confirmed', async () => {
  const [item] = await submitCheckoutItems(createCheckoutItems(seats.slice(0,1), ()=> 'abc'),
    async ()=>({data:{booking_id:'B4',status:'PENDING'}}), { userId:1, concertId:1 });
  assert.equal(item.state,'uncertain');
});
