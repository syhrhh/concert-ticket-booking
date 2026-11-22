import { useState } from 'react';
import { api } from './api';
import './admin.css';
import './login.css';

const QUICK_ACCOUNTS = {
  CUSTOMER: [
    { label: 'Customer 01', email: 'user.a@example.com', password: 'customer123' },
    { label: 'Customer 02', email: 'user.b@example.com', password: 'customer123' },
  ],
  ADMIN: [{ label: 'Staff', email: 'admin@encore.local', password: 'admin123' }],
};

export default function LoginPage({ onLogin, notice = '' }) {
  const [role, setRole] = useState('CUSTOMER');
  const [mode, setMode] = useState('signin'); // 'signin' | 'register' (customers only)
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const chooseRole = next => { setRole(next); setMode('signin'); setError(''); setName(''); setEmail(''); setPassword(''); };
  const registering = role === 'CUSTOMER' && mode === 'register';

  const submit = async event => {
    event.preventDefault();
    setBusy(true); setError('');
    try {
      if (registering) {
        // New accounts are always customers; the server never accepts a role here.
        const { data } = await api.register(name.trim(), email.trim(), password);
        onLogin({ token: data.token, user: data.user });
        return;
      }
      const { data } = await api.login(email.trim(), password);
      if (data.user.role !== role) {
        setError(role === 'CUSTOMER' ? 'This is a staff account. Use the Staff tab to sign in.' : 'This is a customer account. Use the Customer tab to sign in.');
        return;
      }
      onLogin({ token: data.token, user: data.user });
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  return <div className="login-shell">
    <div className="background-glow bg-glow-one"/><div className="background-glow bg-glow-two"/>
    <form className="login-card glass-surface" onSubmit={submit}>
      <div className="login-brand">encore<span className="brand-dot">.</span></div>
      <h1>{registering ? 'Create your account.' : 'Welcome back.'}</h1>
      <p className="admin-muted">{registering ? 'Register as a customer to book seats.' : 'Sign in to book seats or manage the show.'}</p>
      <div className="login-tabs" role="tablist" aria-label="Account type">
        <button type="button" role="tab" aria-selected={role === 'CUSTOMER'} className={role === 'CUSTOMER' ? 'active' : ''} onClick={() => chooseRole('CUSTOMER')}>Customer</button>
        <button type="button" role="tab" aria-selected={role === 'ADMIN'} className={role === 'ADMIN' ? 'active' : ''} onClick={() => chooseRole('ADMIN')}>Staff</button>
      </div>
      {notice && !error && <div className="admin-ok" role="status">{notice}</div>}
      {registering && <label>Full name<input value={name} onChange={e => setName(e.target.value)} autoComplete="name" maxLength={100} required /></label>}
      <label>E-mail<input type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="username" required /></label>
      <label>Password<input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete={registering ? 'new-password' : 'current-password'} minLength={registering ? 8 : undefined} required />{registering && <small>At least 8 characters.</small>}</label>
      {error && <div className="admin-error" role="alert">{error}</div>}
      <button className="admin-primary" type="submit" disabled={busy}>{busy ? (registering ? 'Creating account...' : 'Signing in...') : (registering ? 'Create account' : 'Sign in')}</button>
      {role === 'CUSTOMER'
        ? <p className="login-switch">{registering ? 'Already have an account?' : 'New here?'} <button type="button" onClick={() => { setMode(registering ? 'signin' : 'register'); setError(''); }}>{registering ? 'Sign in' : 'Create an account'}</button></p>
        : <p className="login-switch">Staff accounts are created by an administrator.</p>}
      {!registering && <div className="login-demo">
        <span>Quick sign-in (click to fill)</span>
        {QUICK_ACCOUNTS[role].map(d => <button type="button" key={d.email} onClick={() => { setEmail(d.email); setPassword(d.password); setError(''); }}>
          <b>{d.label}</b><small>{d.email} · {d.password}</small></button>)}
      </div>}
    </form>
  </div>;
}
