import { test } from 'node:test';
import assert from 'node:assert/strict';
import { api, ApiError } from '../src/api.js';

function mockFetch(expected, reply, headers = {}) {
  let captured;
  globalThis.fetch = async (url, opts) => {
    captured = { url, opts };
    assert.match(url, expected);
    return {
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      text: async () => JSON.stringify(reply.body),
      headers: { get: key => headers[key] || null },
    };
  };
  return () => captured;
}

test('reads concerts from the Availability API, not hardcoded data', async () => {
  const captured = mockFetch(/\/gateway\/availability\/api\/concerts$/, { status: 200, body: [{ concert_id: 1, concert_name: 'Demo Concert A' }] });
  const result = await api.concerts();
  assert.equal(result.data[0].concert_name, 'Demo Concert A');
  assert.equal(captured().opts.method, 'GET');
});

test('books with the agreed payload and idempotency header', async () => {
  const captured = mockFetch(/\/gateway\/booking\/api\/bookings$/, { status: 201, body: { booking_id: 'B0123456789AB', status: 'CONFIRMED' } });
  const result = await api.book({ userId: 1, concertId: 2, seatId: 11, idempotencyKey: 'aaa-bbb-12345678' });
  assert.equal(result.status, 201);
  assert.equal(captured().opts.method, 'POST');
  assert.equal(captured().opts.headers['Idempotency-Key'], 'aaa-bbb-12345678');
  assert.deepEqual(JSON.parse(captured().opts.body), { user_id: 1, concert_id: 2, seat_id: 11 });
});

test('cancels using the required query parameter, not a JSON body', async () => {
  const captured = mockFetch(/\/gateway\/booking\/api\/bookings\/B0123456789AB\?user_id=2$/, { status: 200, body: { status: 'CANCELLED' } });
  await api.cancel('B0123456789AB', 2);
  assert.equal(captured().opts.method, 'DELETE');
  assert.equal(captured().opts.body, undefined);
});

test('maps backend detail errors to a user-facing seat conflict message', async () => {
  mockFetch(/\/gateway\/booking\/api\/bookings$/, { status: 409, body: { detail: 'SEAT_NOT_AVAILABLE', booking: { status: 'REJECTED' } } });
  await assert.rejects(() => api.book({ userId: 1, concertId: 1, seatId: 9, idempotencyKey: 'repeat-12345678' }), error => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 409);
    assert.equal(error.code, 'SEAT_NOT_AVAILABLE');
    assert.match(error.message, /another seat/);
    return true;
  });
});

test('detects a safe idempotent replay response', async () => {
  mockFetch(/\/gateway\/booking\/api\/bookings$/, { status: 200, body: { booking_id: 'B0123456789AB', status: 'CONFIRMED' } }, { 'Idempotent-Replay': 'true' });
  const result = await api.book({ userId: 1, concertId: 1, seatId: 9, idempotencyKey: 'repeat-12345678' });
  assert.equal(result.replay, true);
});

test('reads notifications from the separate Notification API', async () => {
  const captured = mockFetch(/\/gateway\/notifications\/api\/users\/1\/notifications$/, { status: 200, body: [] });
  assert.deepEqual((await api.notifications(1)).data, []);
  assert.equal(captured().opts.method, 'GET');
});
