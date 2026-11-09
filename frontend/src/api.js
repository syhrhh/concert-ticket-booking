/**
 * Browser-facing REST client for the group's FastAPI services.
 * In Vite development, /gateway/* is proxied to the real backend ports.
 * Do not move bookings or reservations into frontend state; PostgreSQL is authoritative.
 */
const ROOTS = {
  availability: import.meta.env?.VITE_AVAILABILITY_API || '/gateway/availability',
  booking: import.meta.env?.VITE_BOOKING_API || '/gateway/booking',
  notifications: import.meta.env?.VITE_NOTIFICATION_API || '/gateway/notifications',
};

export class ApiError extends Error {
  constructor(message, status = 0, code = 'NETWORK_ERROR', extra = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

const friendlyErrors = {
  SEAT_NOT_AVAILABLE: 'This seat has just been booked. Please choose another seat.',
  SEAT_NOT_FOUND: 'That seat could not be found. Refresh the seat map.',
  CONCERT_NOT_FOUND: 'This concert is no longer available.',
  USER_NOT_FOUND: 'Demo user not found. Check that the database seed has been loaded.',
  BOOKING_NOT_FOUND: 'We could not find that booking.',
  NOT_BOOKING_OWNER: 'This booking belongs to another demo user.',
  BOOKING_NOT_CANCELLABLE: 'This booking cannot be cancelled in its current state.',
  AVAILABILITY_SERVICE_UNAVAILABLE: 'Seat availability is temporarily offline. Please retry your request.',
  SERVICE_UNAVAILABLE: 'A backend service is temporarily unavailable.',
  DATABASE_UNAVAILABLE: 'The database is temporarily unavailable.',
  RECOVERY_IN_PROGRESS: 'Your previous booking attempt is recovering. Wait a moment and retry.',
  REQUEST_IN_PROGRESS: 'Your booking request is still being processed. Retry in a moment.',
  IDEMPOTENCY_KEY_REUSED: 'The retry key belongs to another request. Select the seat again.',
  INVALID_REQUEST: 'Some of the submitted information is invalid.',
};

async function request(service, route, { method = 'GET', body, headers = {}, timeout = 15000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(`${ROOTS[service]}${route}`, {
      method,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...headers,
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      signal: controller.signal,
    });
    if (import.meta.env?.DEV) console.debug(`[ENCORE API] ${method} ${service}${route} → ${response.status}`);
    const raw = await response.text();
    let data = null;
    try { data = raw ? JSON.parse(raw) : null; } catch { data = { detail: raw }; }
    if (!response.ok) {
      const detail = data?.detail;
      const code = (typeof detail === 'string' ? detail : detail?.error_code) || data?.error_code || `HTTP_${response.status}`;
      const message = friendlyErrors[code] || data?.message || detail?.message || `Request failed (${response.status}).`;
      throw new ApiError(message, response.status, code, data || {});
    }
    return { data, status: response.status, replay: response.headers.get('Idempotent-Replay') === 'true' };
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const timeoutError = error?.name === 'AbortError';
    throw new ApiError(timeoutError
      ? 'The server took too long to respond. Your request may have been processed; retry safely.'
      : 'Cannot connect to the service. Check that the backend and database are running.', 0,
    timeoutError ? 'TIMEOUT' : 'NETWORK_ERROR');
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  concerts: () => request('availability', '/api/concerts'),
  seats: (concertId) => request('availability', `/api/concerts/${concertId}/seats`),
  seatStatus: (concertId, seatId) => request('availability', `/api/concerts/${concertId}/seats/${seatId}/availability`),
  book: ({ userId, concertId, seatId, idempotencyKey }) => request('booking', '/api/bookings', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: { user_id: Number(userId), concert_id: Number(concertId), seat_id: Number(seatId) },
  }),
  bookings: (userId) => request('booking', `/api/users/${userId}/bookings`),
  booking: (bookingId) => request('booking', `/api/bookings/${bookingId}`),
  cancel: (bookingId, userId) => request('booking', `/api/bookings/${bookingId}?user_id=${userId}`, { method: 'DELETE' }),
  notifications: (userId) => request('notifications', `/api/users/${userId}/notifications`),
  health: (service) => request(service, '/health', { timeout: 4000 }),
  dependencies: () => request('booking', '/health/dependencies', { timeout: 5000 }),
};
