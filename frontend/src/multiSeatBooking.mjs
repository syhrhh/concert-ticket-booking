/**
 * Frontend-only multi-seat checkout.
 * The Booking API still receives one POST per seat, each with its own idempotency key.
 * No cross-seat atomicity is promised: mixed success/rejection is expected and shown.
 */
export const MAX_SEATS_PER_CHECKOUT = 6;

export function toggleSeatId(ids, seatId, max = MAX_SEATS_PER_CHECKOUT) {
  if (ids.includes(seatId)) return ids.filter(id => id !== seatId);
  return ids.length < max ? [...ids, seatId] : ids;
}

export function reconcileSeatIds(ids, seats) {
  const availableIds = new Set(seats.filter(seat => seat.status === 'AVAILABLE').map(seat => seat.seat_id));
  return ids.filter(id => availableIds.has(id));
}

export function createCheckoutItems(seats, createKey = () => crypto.randomUUID()) {
  return seats.map(seat => ({
    seat,
    key: createKey(),
    state: 'pending',
    booking: null,
    replay: false,
    error: null,
  }));
}

const RETRYABLE_ERRORS = new Set([
  'TIMEOUT', 'NETWORK_ERROR', 'REQUEST_IN_PROGRESS', 'RECOVERY_IN_PROGRESS',
  'SERVICE_UNAVAILABLE', 'AVAILABILITY_SERVICE_UNAVAILABLE', 'DATABASE_UNAVAILABLE',
]);

export function isRetryableError(error) {
  return RETRYABLE_ERRORS.has(error?.code) || Number(error?.status) >= 500;
}

/** Retry only pending / uncertain seats, with EXACTLY the same per-seat key. */
export async function submitCheckoutItems(items, book, { userId, concertId }) {
  const retryIndices = items.reduce((acc, item, index) => {
    if (item.state === 'pending' || item.state === 'uncertain') acc.push(index);
    return acc;
  }, []);
  const settled = await Promise.allSettled(retryIndices.map(index => {
    const item = items[index];
    return book({ userId, concertId, seatId: item.seat.seat_id, idempotencyKey: item.key });
  }));
  const updated = items.map(item => ({ ...item }));
  settled.forEach((result, resultIndex) => {
    const index = retryIndices[resultIndex];
    const item = updated[index];
    if (result.status === 'fulfilled') {
      const booking = result.value.data;
      if (booking?.status === 'CONFIRMED') {
        updated[index] = { ...item, state: 'confirmed', booking, replay: Boolean(result.value.replay), error: null };
      } else {
        // An unexpected PENDING response is not a confirmed seat.
        updated[index] = { ...item, state: 'uncertain', booking, error: { message: `Booking status: ${booking?.status || 'unknown'}`, code: 'UNCONFIRMED_STATUS' } };
      }
    } else {
      const error = result.reason;
      updated[index] = { ...item, state: isRetryableError(error) ? 'uncertain' : 'rejected', error: { message: error?.message || 'Booking failed', code: error?.code || 'UNKNOWN' } };
    }
  });
  return updated;
}

export function checkoutCounts(items) {
  return items.reduce((counts, item) => ({ ...counts, [item.state]: (counts[item.state] || 0) + 1 }), { confirmed: 0, rejected: 0, uncertain: 0, pending: 0 });
}
