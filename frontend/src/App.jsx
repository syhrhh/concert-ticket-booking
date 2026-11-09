import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api';

const ICONS = {
  ticket: <><path d="M3 8.5A2.5 2.5 0 0 0 5.5 6H20v4a2 2 0 0 0 0 4v4H5.5A2.5 2.5 0 0 0 3 15.5Z"/><path d="M13 6v2m0 3v2m0 3v2"/></>,
  arrow: <><path d="M5 12h14m-6-6 6 6-6 6"/></>,
  arrowUp: <><path d="M7 17 17 7M8 7h9v9"/></>,
  search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18"/></>,
  pin: <><path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></>,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M5.5 9a7 7 0 0 1 12.6-2.4L20 12M4 12l1.9 5.4A7 7 0 0 0 18.5 15"/></>,
  close: <><path d="M18 6 6 18M6 6l12 12"/></>,
  check: <><path d="m5 12 4 4L19 6"/></>,
  bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4"/></>,
  shield: <><path d="m12 22 7-4V6l-7-4-7 4v12l7 4Z"/><path d="m9 12 2 2 4-4"/></>,
  user: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  alert: <><path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v4m0 4v.01"/></>,
  sparkle: <><path d="m12 2 1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8L12 2Zm7 14 .7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z"/></>,
  menu: <><path d="M4 7h16M4 12h16M4 17h16"/></>,
  layers: <><path d="m12 2 9 5-9 5-9-5 9-5Zm-9 10 9 5 9-5m-18 5 9 5 9-5"/></>,
  copy: <><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8v.01"/></>,
  music: <><path d="M9 18V5l12-2v13M9 8l12-2"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></>,
  chevron: <><path d="m7 10 5 5 5-5"/></>,
};

function Icon({ name, size = 18, className = '' }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICONS[name] || ICONS.ticket}</svg>;
}

const money = value => new Intl.NumberFormat('en-MY', { style: 'currency', currency: 'MYR', maximumFractionDigits: 2 }).format(Number(value || 0));
const fullDate = date => {
  if (!date) return 'Date to be announced';
  const value = new Date(`${date}T12:00:00`);
  return Number.isNaN(value.getTime()) ? date : new Intl.DateTimeFormat('en-MY', { day: 'numeric', month: 'long', year: 'numeric' }).format(value);
};
const dateBits = date => {
  if (!date) return { day: '--', month: 'TBA' };
  const value = new Date(`${date}T12:00:00`);
  if (Number.isNaN(value.getTime())) return { day: '--', month: 'TBA' };
  return { day: String(value.getDate()).padStart(2, '0'), month: new Intl.DateTimeFormat('en-MY', { month: 'short' }).format(value).toUpperCase() };
};
const prettyTime = time => time ? time.slice(0, 5) : 'Time TBA';
const statusClass = status => String(status || '').toLowerCase();

function Logo({ onClick }) {
  return <button className="brand" type="button" onClick={onClick} aria-label="ENCORE home">
    <span className="brand-symbol"><span/><span/><span/><span/></span>
    <span>encore<span className="brand-dot">.</span></span>
  </button>;
}

function GradientButton({ children, onClick, disabled, type = 'button', className = '', icon = 'arrow' }) {
  return <button className={`gradient-button ${className}`} type={type} onClick={onClick} disabled={disabled}>
    <span>{children}</span><Icon name={icon} size={18}/>
  </button>;
}

function StateView({ icon = 'alert', title, message, onRetry, actionLabel = 'Try again' }) {
  return <div className="state-view glass-surface">
    <div className="state-icon"><Icon name={icon} size={25}/></div>
    <h3>{title}</h3><p>{message}</p>
    {onRetry && <button type="button" className="button-outline" onClick={onRetry}><Icon name="refresh" size={15}/>{actionLabel}</button>}
  </div>;
}

function SkeletonCards() { return <div className="events-grid" aria-label="Loading concerts">{[0, 1, 2].map(n => <div key={n} className="event-card loading-card"><div className="loading-image skeleton"/><div className="loading-lines"><div className="skeleton"/><div className="skeleton short"/></div></div>)}</div>; }

function ConcertCard({ concert, index, onSelect }) {
  const date = dateBits(concert.concert_date);
  return <article className="event-card">
    <div className={`event-visual visual-${index % 4}`}>
      <div className="visual-orb orb-one"/><div className="visual-orb orb-two"/>
      <div className="poster-lines"><i/><i/><i/><i/><i/><i/><i/></div>
      <div className="event-date"><strong>{date.day}</strong><span>{date.month}</span></div>
      <span className="poster-word">LIVE<span>.</span></span>
      <div className="poster-badge"><Icon name="music" size={13}/> THE LIVE EXPERIENCE</div>
    </div>
    <div className="event-content">
      <span className="eyebrow small">LIVE PERFORMANCE <span className="tiny-dot"/> {fullDate(concert.concert_date)}</span>
      <h3>{concert.concert_name}</h3>
      <p className="event-artist">{concert.artist_name || 'Live concert'}</p>
      <div className="event-bottom"><span className="venue"><Icon name="pin" size={15}/>{concert.venue}</span>
        <button type="button" className="circular-arrow" aria-label={`View seats for ${concert.concert_name}`} onClick={() => onSelect(concert.concert_id)}><Icon name="arrowUp" size={19}/></button>
      </div>
    </div>
  </article>;
}

function StatusPill({ statuses }) {
  const core = statuses.booking === 'online' && statuses.availability === 'online';
  const checking = statuses.booking === 'checking' || statuses.availability === 'checking';
  const noticeDown = core && statuses.notifications === 'offline';
  return <div className={`service-status ${checking ? 'checking' : core ? 'healthy' : 'down'}`} title={`Booking: ${statuses.booking}; Availability: ${statuses.availability}; Notification: ${statuses.notifications}`}>
    <span className="status-light"/>
    <span>{checking ? 'Checking services' : noticeDown ? 'Notifications delayed' : core ? 'Core services live' : 'Services offline'}</span>
  </div>;
}

function Modal({ children, onClose, wide = false }) {
  useEffect(() => {
    const listener = event => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', listener);
    return () => document.removeEventListener('keydown', listener);
  }, [onClose]);
  return <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className={`modal-content ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label="Booking dialog">
      <button className="modal-close" onClick={onClose} type="button" aria-label="Close dialog"><Icon name="close" size={21}/></button>{children}
    </div>
  </div>;
}

function App() {
  const [page, setPage] = useState('discover');
  const [concerts, setConcerts] = useState([]);
  const [loadingConcerts, setLoadingConcerts] = useState(true);
  const [concertError, setConcertError] = useState('');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('soonest');
  const [selectedConcertId, setSelectedConcertId] = useState(null);
  const [selectedSeatId, setSelectedSeatId] = useState(null);
  const [seatsByConcert, setSeatsByConcert] = useState({});
  const [seatLoading, setSeatLoading] = useState(false);
  const [seatError, setSeatError] = useState('');
  const [userId, setUserId] = useState(() => {
    const stored = localStorage.getItem('encore.demoUser');
    return stored === '2' ? 2 : 1;
  });
  const [bookings, setBookings] = useState([]);
  const [bookingsLoading, setBookingsLoading] = useState(false);
  const [bookingsError, setBookingsError] = useState('');
  const [notifications, setNotifications] = useState([]);
  const [notificationsError, setNotificationsError] = useState('');
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [statuses, setStatuses] = useState({ booking: 'checking', availability: 'checking', notifications: 'checking' });
  const [modal, setModal] = useState(null);
  const [modalError, setModalError] = useState('');
  const [modalErrorCode, setModalErrorCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const seatSectionRef = useRef(null);
  const notificationPanelRef = useRef(null);

  useEffect(() => { localStorage.setItem('encore.demoUser', String(userId)); }, [userId]);
  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(null), 4800); return () => clearTimeout(t); }, [toast]);
  useEffect(() => {
    function closeOnOutside(event) { if (notificationPanelRef.current && !notificationPanelRef.current.contains(event.target)) setNoticeOpen(false); }
    document.addEventListener('pointerdown', closeOnOutside);
    return () => document.removeEventListener('pointerdown', closeOnOutside);
  }, []);

  const loadConcerts = useCallback(async () => {
    setLoadingConcerts(true); setConcertError('');
    try { const { data } = await api.concerts(); setConcerts(Array.isArray(data) ? data : []); }
    catch (err) { setConcertError(err.message); }
    finally { setLoadingConcerts(false); }
  }, []);
  const loadSeats = useCallback(async concertId => {
    if (!concertId) return;
    setSeatLoading(true); setSeatError('');
    try {
      const { data } = await api.seats(concertId);
      setSeatsByConcert(prev => ({ ...prev, [concertId]: Array.isArray(data) ? data : [] }));
    } catch (err) { setSeatError(err.message); }
    finally { setSeatLoading(false); }
  }, []);
  const loadBookings = useCallback(async id => {
    setBookingsLoading(true); setBookingsError('');
    try { const { data } = await api.bookings(id); setBookings(Array.isArray(data) ? data : []); }
    catch (err) { setBookingsError(err.message); setBookings([]); }
    finally { setBookingsLoading(false); }
  }, []);
  const loadNotifications = useCallback(async id => {
    setNotificationsError('');
    try { const { data } = await api.notifications(id); setNotifications(Array.isArray(data) ? data : []); }
    catch (err) { setNotificationsError(err.message); setNotifications([]); }
  }, []);
  const checkServices = useCallback(async () => {
    const result = await Promise.all(['booking', 'availability', 'notifications'].map(async key => {
      try { await api.health(key); return [key, 'online']; } catch { return [key, 'offline']; }
    }));
    setStatuses(Object.fromEntries(result));
  }, []);

  useEffect(() => { loadConcerts(); checkServices(); }, [loadConcerts, checkServices]);
  useEffect(() => { loadBookings(userId); loadNotifications(userId); }, [userId, loadBookings, loadNotifications]);
  useEffect(() => { if (selectedConcertId) loadSeats(selectedConcertId); }, [selectedConcertId, loadSeats]);

  const filteredConcerts = useMemo(() => {
    const q = search.trim().toLowerCase();
    const items = concerts.filter(item => [item.concert_name, item.artist_name, item.venue, item.description].some(value => String(value || '').toLowerCase().includes(q)));
    return items.sort((a,b) => sort === 'az' ? String(a.concert_name).localeCompare(String(b.concert_name)) : String(a.concert_date).localeCompare(String(b.concert_date)));
  }, [concerts, search, sort]);
  const selectedConcert = concerts.find(item => item.concert_id === selectedConcertId);
  const seats = seatsByConcert[selectedConcertId] || [];
  const selectedSeat = seats.find(item => item.seat_id === selectedSeatId);
  const seatGroups = useMemo(() => {
    const groups = new Map();
    seats.forEach(seat => {
      const name = `${seat.section || 'General'} • Row ${seat.row_number || '?'}`;
      if (!groups.has(name)) groups.set(name, []);
      groups.get(name).push(seat);
    });
    return [...groups.entries()];
  }, [seats]);
  const availableCount = seats.filter(s => s.status === 'AVAILABLE').length;
  const confirmedCount = bookings.filter(b => b.status === 'CONFIRMED').length;
  const bookingLookup = useMemo(() => Object.fromEntries(concerts.map(c => [c.concert_id,c])), [concerts]);

  const navigate = name => {
    setPage(name); setNoticeOpen(false);
    if (name === 'tickets') loadBookings(userId);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };
  const chooseConcert = id => {
    setPage('discover'); setSelectedConcertId(id); setSelectedSeatId(null); loadSeats(id);
    setTimeout(() => seatSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);
  };
  const selectSeat = seat => {
    if (seat.status !== 'AVAILABLE') return;
    setSelectedSeatId(seat.seat_id);
  };
  const openBooking = () => {
    if (!selectedSeat || !selectedConcert) return;
    setModalError(''); setModalErrorCode('');
    setModal({ type: 'confirm', concert: selectedConcert, seat: selectedSeat, key: crypto.randomUUID() });
  };
  const confirmBooking = async () => {
    if (busy || modal?.type !== 'confirm') return;
    const current = modal;
    setBusy(true); setModalError(''); setModalErrorCode('');
    try {
      const response = await api.book({ userId, concertId: current.concert.concert_id, seatId: current.seat.seat_id, idempotencyKey: current.key });
      setModal({ type: 'result', booking: response.data, concert: current.concert, seat: current.seat, replay: response.replay });
      setSelectedSeatId(null);
      loadSeats(current.concert.concert_id);
      loadBookings(userId);
      setTimeout(() => loadNotifications(userId), 900);
      checkServices();
    } catch (err) {
      setModalError(err.message); setModalErrorCode(err.code);
      if (err.code === 'SEAT_NOT_AVAILABLE' || err.code === 'SEAT_NOT_FOUND') loadSeats(current.concert.concert_id);
      checkServices();
    } finally { setBusy(false); }
  };
  const cancelBooking = async () => {
    if (busy || modal?.type !== 'cancel') return;
    const booking = modal.booking;
    setBusy(true); setModalError('');
    try {
      const { data } = await api.cancel(booking.booking_id, userId);
      setModal(null);
      setToast({ type: 'success', title: 'Booking cancelled', message: data.seat_release_status === 'PENDING' ? 'Seat release is processing in the background.' : 'Your booking has been cancelled.' });
      loadBookings(userId); loadSeats(booking.concert_id);
      setTimeout(() => loadNotifications(userId), 900);
    } catch (err) { setModalError(err.message); }
    finally { setBusy(false); }
  };
  const refreshDashboard = () => { loadConcerts(); loadBookings(userId); loadNotifications(userId); checkServices(); if (selectedConcertId) loadSeats(selectedConcertId); };

  return <div className="app-shell">
    <div className="background-glow bg-glow-one"/><div className="background-glow bg-glow-two"/>
    <header className="site-header">
      <div className="header-inner page-width">
        <Logo onClick={() => navigate('discover')}/>
        <nav className="nav-links" aria-label="Main navigation">
          <button type="button" className={page === 'discover' ? 'active' : ''} onClick={() => navigate('discover')}>Discover</button>
          <button type="button" className={page === 'tickets' ? 'active' : ''} onClick={() => navigate('tickets')}>My tickets <span className="ticket-count">{confirmedCount}</span></button>
        </nav>
        <div className="header-actions">
          <StatusPill statuses={statuses}/>
          <div className="notification-container" ref={notificationPanelRef}>
            <button type="button" className={`icon-button bell-button ${noticeOpen ? 'selected' : ''}`} onClick={() => { setNoticeOpen(o => !o); loadNotifications(userId); }} aria-label="View notifications" aria-expanded={noticeOpen}><Icon name="bell" size={19}/>{notifications.length > 0 && <span className="notif-dot"/>}</button>
            {noticeOpen && <div className="notification-popover glass-surface">
              <div className="popover-heading"><h3>Notifications</h3><button type="button" onClick={() => loadNotifications(userId)} className="small-refresh" aria-label="Refresh notifications"><Icon name="refresh" size={15}/></button></div>
              {notificationsError ? <div className="mini-error">{notificationsError}</div> : notifications.length === 0 ? <p className="no-notifications">No notifications delivered yet. Booking confirmations will appear here.</p> : <div className="notifications-list">{[...notifications].reverse().slice(0,8).map(note => <div className="notification-item" key={note.notification_id}><span className="notification-check"><Icon name="check" size={14}/></span><div><strong>{note.type === 'BOOKING_CANCELLED' ? 'Booking cancelled' : 'Booking confirmed'}</strong><p>{note.message}</p></div></div>)}</div>}
              <p className="popover-foot">Notifications are delivered by a separate service and may be delayed.</p>
            </div>}
          </div>
          <label className="user-select"><Icon name="user" size={16}/><span className="user-text">Demo user</span><select value={userId} aria-label="Choose demo user" onChange={event => { setUserId(Number(event.target.value)); setSelectedSeatId(null); }}><option value={1}>01</option><option value={2}>02</option></select><Icon name="chevron" size={13}/></label>
        </div>
      </div>
    </header>

    <main>
      {page === 'discover' ? <>
        <section className="hero page-width">
          <div className="hero-copy">
            <div className="hero-kicker"><span className="hero-kicker-line"/> YOUR FRONT ROW STARTS HERE</div>
            <h1>LIVE FOR<br/>THE <span className="gradient-text">MOMENT.</span></h1>
            <p>Big nights. Unforgettable sounds. The best seat in the house is waiting for you.</p>
            <div className="hero-actions"><GradientButton onClick={() => document.getElementById('concerts')?.scrollIntoView({ behavior:'smooth' })}>Explore concerts</GradientButton><div className="hero-trust"><span><Icon name="shield" size={15}/> Conflict-safe bookings</span><span><Icon name="layers" size={15}/> Distributed by design</span></div></div>
            <div className="hero-bottom"><div className="hero-rule"/><span><strong>{loadingConcerts ? '—' : String(concerts.length).padStart(2,'0')}</strong> CONCERTS IN THE SYSTEM</span><span><strong>04</strong> INDEPENDENT COMPONENTS</span></div>
          </div>
          <div className="hero-art" aria-hidden="true">
            <div className="art-disk disk-back"/><div className="art-glow"/><div className="art-ring ring-outer"/><div className="art-ring ring-inner"/>
            <div className="art-vinyl"><div className="vinyl-line v1"/><div className="vinyl-line v2"/><div className="vinyl-line v3"/><div className="vinyl-label"><div className="vinyl-dot"/><span>ENCORE<br/>LIVE</span></div></div>
            <div className="floating-label label-top">FEEL THE<br/><strong>FREQUENCY.</strong></div>
            <div className="floating-label label-bottom"><span className="label-pulse"/> THE SHOW STARTS WITH YOU</div>
            <div className="glow-stripe"/>
          </div>
        </section>
        <div className="feature-strip"><div className="page-width feature-strip-inner"><span><Icon name="ticket" size={18}/> PICK YOUR SEAT</span><i/><span><Icon name="shield" size={18}/> SECURE YOUR SPOT</span><i/><span><Icon name="sparkle" size={18}/> MAKE IT MEMORABLE</span><i/><span className="strip-extra">NO PAYMENT REQUIRED — DEMO</span></div></div>
        <section id="concerts" className="concert-section page-width">
          <div className="section-heading"><div><span className="eyebrow"><span className="tiny-dot"/> THE LINEUP</span><h2>Find your next <em>obsession.</em></h2><p>Discover upcoming shows and choose exactly where you want to be.</p></div><button type="button" className="refresh-button" onClick={refreshDashboard} aria-label="Refresh concert listing"><Icon name="refresh" size={16}/> Refresh</button></div>
          <div className="filter-bar glass-surface"><label className="search-field"><Icon name="search" size={20}/><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search concerts, artists, venues..." aria-label="Search concerts"/></label><div className="filter-separator"/><label className="sort-field"><span>Sort by</span><select value={sort} onChange={event => setSort(event.target.value)} aria-label="Sort concerts"><option value="soonest">Upcoming first</option><option value="az">A to Z</option></select><Icon name="chevron" size={15}/></label></div>
          {loadingConcerts ? <SkeletonCards/> : concertError ? <StateView title="Could not load concerts" message={concertError} onRetry={loadConcerts}/> : filteredConcerts.length === 0 ? <StateView icon="search" title={search ? 'No matching concerts' : 'No concerts found'} message={search ? 'Try another artist or venue.' : 'The connected database currently has no concert records.'} onRetry={search ? () => setSearch('') : loadConcerts} actionLabel={search ? 'Clear search' : 'Refresh'}/> : <div className="events-grid">{filteredConcerts.map((c,i) => <ConcertCard key={c.concert_id} concert={c} index={i} onSelect={chooseConcert}/>)}</div>}
        </section>
        <section className="booking-section page-width" id="seat-section" ref={seatSectionRef}>
          <div className="section-heading section-heading-book"><div><span className="eyebrow"><span className="tiny-dot"/> YOUR SEAT, YOUR STORY</span><h2>Choose your <em>spot.</em></h2><p>Select a concert above, then choose an available seat below.</p></div></div>
          {!selectedConcert ? <div className="choose-event-state glass-surface"><div className="choose-event-icon"><Icon name="ticket" size={35}/></div><h3>The best nights start with a seat.</h3><p>Select any concert from the lineup to view the live seating chart.</p><button type="button" className="button-outline" onClick={() => document.getElementById('concerts')?.scrollIntoView({behavior:'smooth'})}>Browse the lineup <Icon name="arrow" size={15}/></button></div> :
          <div className="seat-layout">
            <div className="seat-map glass-surface">
              <div className="seat-map-header"><div><span className="eyebrow small">SEAT SELECTION</span><h3>{selectedConcert.concert_name}</h3><p><Icon name="pin" size={14}/> {selectedConcert.venue}</p></div><button type="button" className="small-refresh" onClick={() => loadSeats(selectedConcertId)} aria-label="Refresh seat availability"><Icon name="refresh" size={17}/></button></div>
              <div className="stage"><div className="stage-gradient"/><span>STAGE</span></div>
              <div className="seat-legend"><span><i className="seat-available"/> Available</span><span><i className="seat-selected"/> Selected</span><span><i className="seat-taken"/> Unavailable</span></div>
              {seatLoading ? <div className="seats-status"><div className="spinner"/> Checking current seat availability...</div> : seatError ? <StateView title="Seats unavailable" message={seatError} onRetry={() => loadSeats(selectedConcertId)}/> : seatGroups.length === 0 ? <div className="seats-status">No seats are configured for this concert.</div> : <div className="seat-groups">{seatGroups.map(([group, groupSeats]) => <div className="seat-group" key={group}><div className="seat-group-heading"><span>{group}</span><small>{money(Math.min(...groupSeats.map(s => Number(s.price))))} / seat</small></div><div className="seat-grid">{groupSeats.map(seat => <button key={seat.seat_id} type="button" className={`seat ${seat.status === 'AVAILABLE' ? 'available' : 'unavailable'} ${selectedSeatId === seat.seat_id ? 'picked' : ''}`} disabled={seat.status !== 'AVAILABLE'} onClick={() => selectSeat(seat)} aria-pressed={selectedSeatId === seat.seat_id} title={`${seat.seat_number} • ${seat.status} • ${money(seat.price)}`}>{seat.seat_number}</button>)}</div></div>)}</div>}
              <div className="seat-map-footer"><Icon name="info" size={15}/><span>{seatLoading ? 'Updating availability' : `${availableCount} seat${availableCount === 1 ? '' : 's'} currently available. Availability may change before confirmation.`}</span></div>
            </div>
            <aside className="booking-summary glass-surface"><span className="eyebrow small">YOUR EXPERIENCE</span><h3>Booking summary</h3><div className="summary-divider"/><div className="summary-row"><span>Concert</span><strong>{selectedConcert.concert_name}</strong></div><div className="summary-row"><span>Date & time</span><strong>{fullDate(selectedConcert.concert_date)}<br/>{prettyTime(selectedConcert.concert_time)}</strong></div><div className="summary-row"><span>Seat</span><strong>{selectedSeat ? `${selectedSeat.section || 'General'} · ${selectedSeat.seat_number}` : 'Not selected'}</strong></div><div className="summary-price"><span>Total</span><strong>{selectedSeat ? money(selectedSeat.price) : '—'}</strong></div><GradientButton disabled={!selectedSeat || seatLoading} onClick={openBooking} className="booking-pay">{selectedSeat ? 'Continue to booking' : 'Choose a seat first'}</GradientButton><p className="summary-fineprint"><Icon name="shield" size={14}/> Booking is confirmed only after the server reserves the seat. Demo only — no payment.</p></aside>
          </div>}
        </section>
      </> : <section className="tickets-page page-width"><div className="tickets-header"><div><span className="eyebrow"><span className="tiny-dot"/> YOUR PERSONAL BACKSTAGE PASS</span><h1>My <span className="gradient-text">tickets.</span></h1><p>Review your reservations, check status and cancel a booking.</p></div><button type="button" className="button-outline" onClick={() => { loadBookings(userId); loadNotifications(userId); }}><Icon name="refresh" size={16}/> Refresh bookings</button></div><div className="account-banner glass-surface"><span className="account-avatar"><Icon name="user" size={21}/></span><div><span className="eyebrow small">DEMO ACCOUNT</span><strong>User {String(userId).padStart(2, '0')}</strong></div><div className="account-stat"><strong>{confirmedCount}</strong><span>ACTIVE TICKETS</span></div></div>
          {bookingsLoading ? <div className="seats-status"><div className="spinner"/> Fetching your tickets...</div> : bookingsError ? <StateView title="Could not load tickets" message={bookingsError} onRetry={() => loadBookings(userId)}/> : bookings.length === 0 ? <StateView icon="ticket" title="No tickets yet" message="Your next unforgettable night is waiting. Browse concerts to reserve your first seat." onRetry={() => navigate('discover')} actionLabel="Discover concerts"/> : <div className="ticket-list">{bookings.map(b => { const c = bookingLookup[b.concert_id]; const seat = (seatsByConcert[b.concert_id] || []).find(s => s.seat_id === b.seat_id); return <article className="ticket-item glass-surface" key={b.booking_id}><div className="ticket-stub"><span>ENCORE</span><Icon name="ticket" size={31}/><small>ADMIT ONE</small></div><div className="ticket-info"><div className="ticket-meta"><span className={`booking-status ${statusClass(b.status)}`}>{b.status}</span><span className="ticket-id">{b.booking_id}</span></div><h3>{c?.concert_name || `Concert #${b.concert_id}`}</h3><p>{c ? `${fullDate(c.concert_date)} · ${c.venue}` : `Concert ID ${b.concert_id}`}</p><div className="ticket-notes"><span><Icon name="ticket" size={14}/> Seat {seat?.seat_number || `#${b.seat_id}`}</span><span><Icon name="bell" size={14}/> Notification: {b.notification_status || '—'}</span>{b.seat_release_status && <span><Icon name="refresh" size={14}/> Seat release: {b.seat_release_status}</span>}</div></div><div className="ticket-actions">{b.status === 'CONFIRMED' && <button type="button" className="cancel-button" onClick={() => { setModal({type:'cancel', booking:b, concert:c, seat}); setModalError(''); setModalErrorCode(''); }}>Cancel ticket</button>}</div></article>; })}</div>}
        </section>}
    </main>
    <footer className="site-footer"><div className="page-width footer-inner"><Logo onClick={() => navigate('discover')}/><span>MADE FOR THE MOMENTS THAT MATTER.</span><p>Distributed Systems proof of concept · No real ticket sales or payment processing.</p></div></footer>

    {toast && <div role="status" className={`toast toast-${toast.type || 'info'}`}><Icon name={toast.type === 'success' ? 'check' : 'info'} size={19}/><div><strong>{toast.title}</strong><span>{toast.message}</span></div><button type="button" onClick={() => setToast(null)} aria-label="Dismiss"><Icon name="close" size={15}/></button></div>}
    {modal && <Modal onClose={() => { if (!busy) { setModal(null); setModalError(''); } }}>
      {modal.type === 'confirm' && <><div className="modal-top-icon"><Icon name="ticket" size={26}/></div><span className="eyebrow small">ONE STEP TO THE SHOW</span><h2>Confirm your seat.</h2><p className="modal-description">Your seat will be reserved through the live Booking and Availability services.</p><div className="modal-receipt"><div><span>Concert</span><strong>{modal.concert.concert_name}</strong></div><div><span>Selected seat</span><strong>{modal.seat.section} / {modal.seat.seat_number}</strong></div><div><span>Demo account</span><strong>User {String(userId).padStart(2,'0')}</strong></div><div className="receipt-total"><span>Total (demo)</span><strong>{money(modal.seat.price)}</strong></div></div>{modalError && <div className="modal-error" role="alert"><Icon name="alert" size={18}/>{modalError}</div>}<GradientButton className="modal-primary" disabled={busy} onClick={() => { if (modalError && !['NETWORK_ERROR','TIMEOUT','AVAILABILITY_SERVICE_UNAVAILABLE','RECOVERY_IN_PROGRESS','REQUEST_IN_PROGRESS','SERVICE_UNAVAILABLE','DATABASE_UNAVAILABLE'].includes(modalErrorCode)) { setModal(null); setSelectedSeatId(null); loadSeats(modal.concert.concert_id); } else confirmBooking(); }}>{busy ? 'Contacting booking service...' : modalError && !['NETWORK_ERROR','TIMEOUT','AVAILABILITY_SERVICE_UNAVAILABLE','RECOVERY_IN_PROGRESS','REQUEST_IN_PROGRESS','SERVICE_UNAVAILABLE','DATABASE_UNAVAILABLE'].includes(modalErrorCode) ? 'Choose another seat' : modalError ? 'Retry safely' : 'Confirm booking'}</GradientButton><p className="modal-footnote">Retries reuse the same request key to prevent duplicate bookings.</p></>}
      {modal.type === 'result' && <><div className="modal-top-icon result-success"><Icon name="check" size={28}/></div><span className="eyebrow small">YOU'RE ON THE LIST</span><h2>It's official.</h2><p className="modal-description">Your booking has been confirmed by the server. See you at the show!</p><div className="result-badge">{modal.booking.status}</div><div className="modal-receipt"><div><span>Booking reference</span><strong className="reference-number">{modal.booking.booking_id}</strong></div><div><span>Concert</span><strong>{modal.concert.concert_name}</strong></div><div><span>Seat</span><strong>{modal.seat.seat_number}</strong></div><div><span>Notification</span><strong>{modal.booking.notification_status || 'Processing'}</strong></div></div>{modal.replay && <p className="replay-note">An existing booking was returned safely using your original request key.</p>}<GradientButton className="modal-primary" onClick={() => { setModal(null); navigate('tickets'); }}>View my tickets</GradientButton><button className="text-action" type="button" onClick={() => setModal(null)}>Back to concerts</button></>}
      {modal.type === 'cancel' && <><div className="modal-top-icon warning-icon"><Icon name="alert" size={26}/></div><span className="eyebrow small">BOOKING MANAGEMENT</span><h2>Cancel this ticket?</h2><p className="modal-description">This action will cancel booking <strong>{modal.booking.booking_id}</strong>. Your seat will be released by the availability service.</p><div className="modal-receipt"><div><span>Concert</span><strong>{modal.concert?.concert_name || `Concert #${modal.booking.concert_id}`}</strong></div><div><span>Booking status</span><strong>{modal.booking.status}</strong></div></div>{modalError && <div className="modal-error" role="alert"><Icon name="alert" size={18}/>{modalError}</div>}<button type="button" className="danger-button" disabled={busy} onClick={cancelBooking}>{busy ? 'Cancelling...' : 'Yes, cancel this ticket'}</button><button type="button" className="text-action" onClick={() => setModal(null)} disabled={busy}>Keep my booking</button></>}
    </Modal>}
  </div>;
}

export default App;
