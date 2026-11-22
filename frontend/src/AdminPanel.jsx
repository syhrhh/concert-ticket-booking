import { useCallback, useEffect, useState } from 'react';
import { api } from './api';
import './admin.css';

const TOKEN_KEY = 'encore_admin_token';
const readToken = () => { try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } };
const saveToken = token => { try { token ? sessionStorage.setItem(TOKEN_KEY, token) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* storage blocked: session lasts until refresh */ } };

const money = v => new Intl.NumberFormat('en-MY', { style: 'currency', currency: 'MYR' }).format(Number(v || 0));
const when = iso => iso ? new Date(iso).toLocaleString('en-MY', { dateStyle: 'medium', timeStyle: 'short' }) : '-';
const STATUSES = ['CONFIRMED', 'PENDING', 'CANCELLED', 'REJECTED', 'FAILED'];

function AdminLogin({ onLoggedIn }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async event => {
    event.preventDefault();
    setBusy(true); setError('');
    try {
      const { data } = await api.adminLogin(email.trim(), password);
      saveToken(data.token);
      onLoggedIn(data.token, data.admin);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  return <section className="admin-login page-width">
    <form className="admin-card glass-surface" onSubmit={submit}>
      <span className="eyebrow small">STAFF ONLY</span>
      <h2>Admin sign in</h2>
      <p className="admin-muted">Sign in to monitor bookings, seat occupancy and delivery status.</p>
      <label>E-mail<input type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="username" required /></label>
      <label>Password<input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" required /></label>
      {error && <div className="admin-error" role="alert">{error}</div>}
      <button className="admin-primary" type="submit" disabled={busy}>{busy ? 'Signing in...' : 'Sign in'}</button>
    </form>
  </section>;
}

function Tile({ label, value, tone }) {
  return <div className={`admin-tile glass-surface ${tone || ''}`}><span>{label}</span><strong>{value}</strong></div>;
}

function SeatManager({ token, concerts, onChanged }) {
  const [concertId, setConcertId] = useState(concerts[0]?.concert_id || '');
  const [seats, setSeats] = useState([]);
  const [section, setSection] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!concertId) return;
    try { const { data } = await api.seats(concertId); setSeats(Array.isArray(data) ? data : []); setError(''); }
    catch (err) { setError(err.message); }
  }, [concertId]);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);

  const sections = [...new Set(seats.map(x => x.section))];
  const active = sections.includes(section) ? section : sections[0] || '';
  const rows = {};
  seats.filter(x => x.section === active).forEach(x => { (rows[x.row_number] ||= []).push(x); });
  const counts = seats.filter(x => x.section === active).reduce((a, x) => ({ ...a, [x.status]: (a[x.status] || 0) + 1 }), {});

  const run = async fn => {
    setBusy(true);
    try { await fn(); setError(''); await load(); onChanged(); } catch (err) { setError(err.message); await load(); }
    finally { setBusy(false); }
  };
  const toggle = seat => {
    if (seat.status === 'AVAILABLE') return run(() => api.adminSeatAction(token, concertId, seat.seat_id, 'block'));
    if (seat.status === 'BLOCKED') return run(() => api.adminSeatAction(token, concertId, seat.seat_id, 'unblock'));
  };

  return <div className="admin-card glass-surface">
    <div className="admin-filters">
      <h3>Seat control</h3>
      <select value={concertId} onChange={e => { setConcertId(e.target.value); setSection(''); }} aria-label="Concert">
        {concerts.map(c => <option key={c.concert_id} value={c.concert_id}>{c.concert_name}</option>)}
      </select>
      <select value={active} onChange={e => setSection(e.target.value)} aria-label="Section">
        {sections.map(sec => <option key={sec} value={sec}>Section {sec}</option>)}
      </select>
      <button type="button" className="admin-ghost" disabled={busy || !active} onClick={() => run(() => api.adminSectionAction(token, concertId, active, 'block'))}>Block section</button>
      <button type="button" className="admin-ghost" disabled={busy || !active} onClick={() => run(() => api.adminSectionAction(token, concertId, active, 'unblock'))}>Unblock section</button>
    </div>
    <p className="admin-muted">Click an available seat to take it off sale; click a blocked seat to put it back. Booked seats must be cancelled in the bookings list first. Customers see changes within a few seconds.</p>
    {error && <div className="admin-error" role="alert">{error}</div>}
    <div className="seat-legend"><span><i className="sq available" />Available {counts.AVAILABLE || 0}</span><span><i className="sq blocked" />Blocked {counts.BLOCKED || 0}</span><span><i className="sq booked" />Booked/reserved {(counts.BOOKED || 0) + (counts.RESERVED || 0)}</span></div>
    <div className="seat-grid">
      {Object.entries(rows).map(([row, list]) => <div className="seat-row" key={row}>
        <b>{row}</b>
        {list.map(seat => <button key={seat.seat_id} type="button" disabled={busy || seat.status === 'BOOKED' || seat.status === 'RESERVED'}
          className={`seat-cell ${seat.status.toLowerCase()}`} onClick={() => toggle(seat)}
          title={`${seat.seat_number} · ${seat.status}`} aria-label={`${seat.seat_number} ${seat.status}`}>{seat.seat_number.split('-')[1]?.slice(1) || ''}</button>)}
      </div>)}
    </div>
  </div>;
}

function Dashboard({ token, admin, onLogout }) {
  const [stats, setStats] = useState(null);
  const [bookings, setBookings] = useState([]);
  const [filters, setFilters] = useState({ status: '', concertId: '', q: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState('');
  const [cancelling, setCancelling] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    try {
      const [s, b] = await Promise.all([api.adminStats(token), api.adminBookings(token, filters)]);
      setStats(s.data); setBookings(b.data); setError('');
    } catch (err) {
      if (err.status === 401 || err.status === 403) { saveToken(''); onLogout(err.message); return; }
      setError(err.message);
    } finally { setLoading(false); }
  }, [token, filters, onLogout]);

  useEffect(() => { load(); const timer = setInterval(load, 5000); return () => clearInterval(timer); }, [load]);

  const cancel = async id => {
    setCancelling(id); setNotice('');
    try {
      await api.adminCancel(token, id);
      setNotice(`Booking ${id} cancelled. The seat release and customer notification are delivered in the background.`);
      setConfirming('');
      await load();
    } catch (err) { setError(err.message); }
    finally { setCancelling(''); }
  };

  const by = stats?.bookings_by_status || {};
  const backlog = stats ? Object.entries(stats.outbox_backlog) : [];

  return <section className="admin-page page-width">
    <div className="admin-head">
      <div><span className="eyebrow small">STAFF CONSOLE</span><h2>Operations dashboard</h2>
        <p className="admin-muted">Signed in as {admin?.name || 'admin'} · refreshes every 5 seconds</p></div>
      <div className="admin-head-actions">
        <button type="button" className="admin-ghost" onClick={load}>Refresh</button>
        <button type="button" className="admin-ghost" onClick={() => { saveToken(''); onLogout(''); }}>Sign out</button>
      </div>
    </div>

    {error && <div className="admin-error" role="alert">{error}</div>}
    {notice && <div className="admin-ok" role="status">{notice}</div>}

    <div className="admin-tiles">
      <Tile label="Confirmed" value={by.CONFIRMED ?? '-'} tone="good" />
      <Tile label="Cancelled" value={by.CANCELLED ?? '-'} />
      <Tile label="Rejected (seat taken)" value={by.REJECTED ?? '-'} />
      <Tile label="Failed (technical)" value={by.FAILED ?? '-'} tone={by.FAILED ? 'warn' : ''} />
      <Tile label="Confirmed revenue" value={stats ? money(stats.confirmed_revenue) : '-'} />
    </div>

    <div className="admin-grid">
      <div className="admin-card glass-surface">
        <h3>Seat occupancy</h3>
        {(stats?.concerts || []).map(c => {
          const pct = n => c.total_seats ? (n / c.total_seats) * 100 : 0;
          return <div className="occ" key={c.concert_id}>
            <div className="occ-title"><strong>{c.concert_name}</strong><span>{c.venue} · {c.concert_date}</span></div>
            <div className="occ-bar" role="img" aria-label={`${c.booked} booked, ${c.reserved} reserved, ${c.blocked} blocked, ${c.available} available`}>
              <i className="booked" style={{ width: `${pct(c.booked)}%` }} />
              <i className="reserved" style={{ width: `${pct(c.reserved)}%` }} />
              <i className="blocked" style={{ width: `${pct(c.blocked)}%` }} />
            </div>
            <div className="occ-legend"><span><b className="dot booked" />Booked {c.booked}</span><span><b className="dot reserved" />Reserved {c.reserved}</span><span><b className="dot blocked" />Blocked {c.blocked}</span><span><b className="dot free" />Available {c.available}</span><span>Total {c.total_seats}</span></div>
          </div>;
        })}
        {!stats && <p className="admin-muted">Loading...</p>}
      </div>
      <div className="admin-card glass-surface">
        <h3>Background delivery</h3>
        {backlog.length === 0
          ? <p className="admin-muted">Nothing waiting. All notifications and seat releases are delivered.</p>
          : <><p className="admin-muted">Queued for delivery (retried automatically if a service is down):</p>
            <ul className="backlog">{backlog.map(([key, n]) => <li key={key} className={key.endsWith('DEAD') ? 'dead' : ''}><span>{key.replace(':', ' · ')}</span><b>{n}</b></li>)}</ul></>}
      </div>
    </div>

    {stats && stats.concerts.length > 0 && <SeatManager token={token} concerts={stats.concerts} onChanged={load} />}

    <div className="admin-card glass-surface">
      <div className="admin-filters">
        <h3>All bookings</h3>
        <select value={filters.status} onChange={e => setFilters(f => ({ ...f, status: e.target.value }))} aria-label="Filter by status">
          <option value="">All statuses</option>{STATUSES.map(s => <option key={s}>{s}</option>)}
        </select>
        <select value={filters.concertId} onChange={e => setFilters(f => ({ ...f, concertId: e.target.value }))} aria-label="Filter by concert">
          <option value="">All concerts</option>{(stats?.concerts || []).map(c => <option key={c.concert_id} value={c.concert_id}>{c.concert_name}</option>)}
        </select>
        <input type="search" placeholder="Search booking ID, name or e-mail" value={filters.q} onChange={e => setFilters(f => ({ ...f, q: e.target.value }))} />
      </div>
      {loading ? <p className="admin-muted">Loading bookings...</p> : bookings.length === 0 ? <p className="admin-muted">No bookings match.</p> :
        <div className="admin-table-wrap"><table className="admin-table">
          <thead><tr><th>Booking</th><th>Customer</th><th>Concert / seat</th><th>Price</th><th>Status</th><th>Notification</th><th>Seat release</th><th>Created</th><th /></tr></thead>
          <tbody>{bookings.map(b => <tr key={b.booking_id}>
            <td className="mono">{b.booking_id}</td>
            <td>{b.customer_name}<small>{b.customer_email}</small></td>
            <td>{b.concert_name}<small>{b.seat_number} · Sec {b.section}</small></td>
            <td>{money(b.price)}</td>
            <td><span className={`pill ${b.status.toLowerCase()}`}>{b.status}</span>{b.failure_reason && <small>{b.failure_reason}</small>}</td>
            <td>{b.cancellation_notification_status || b.notification_status || '-'}</td>
            <td>{b.seat_release_status || '-'}</td>
            <td>{when(b.created_at)}</td>
            <td>{b.status === 'CONFIRMED' && (confirming === b.booking_id
              ? <span className="confirm-row"><button type="button" className="admin-danger" disabled={cancelling === b.booking_id} onClick={() => cancel(b.booking_id)}>{cancelling === b.booking_id ? '...' : 'Confirm'}</button><button type="button" className="admin-ghost" onClick={() => setConfirming('')}>No</button></span>
              : <button type="button" className="admin-ghost" onClick={() => setConfirming(b.booking_id)}>Cancel</button>)}</td>
          </tr>)}</tbody>
        </table></div>}
    </div>
  </section>;
}

export default function AdminPanel() {
  const [token, setToken] = useState(readToken);
  const [admin, setAdmin] = useState(null);
  const [checking, setChecking] = useState(Boolean(readToken()));

  // Restore a saved session: validate the token with the server.
  useEffect(() => {
    if (!token || admin) { setChecking(false); return; }
    api.adminMe(token).then(({ data }) => setAdmin(data)).catch(() => { saveToken(''); setToken(''); }).finally(() => setChecking(false));
  }, [token, admin]);

  const logout = useCallback(() => { setToken(''); setAdmin(null); }, []);

  if (checking) return <section className="admin-login page-width"><p className="admin-muted">Checking your session...</p></section>;
  if (!token || !admin) return <AdminLogin onLoggedIn={(t, a) => { setToken(t); setAdmin(a); }} />;
  return <Dashboard token={token} admin={admin} onLogout={logout} />;
}
