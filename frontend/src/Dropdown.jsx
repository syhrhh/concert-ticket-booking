import { useEffect, useRef, useState } from 'react';

/** Styled replacement for <select>, modelled on the account switcher menu:
 * pill trigger, dark glass panel, small caption, rounded options, check on the active one.
 * Keyboard: Enter/Space/ArrowDown opens, arrows move, Home/End jump, Esc closes. */
export default function Dropdown({ value, options, onChange, ariaLabel, caption = '', align = 'right', minWidth = 150 }) {
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  const trigger = useRef(null);
  const items = useRef([]);
  const index = Math.max(0, options.findIndex(o => String(o.value) === String(value)));
  const selected = options[index];

  useEffect(() => {
    if (!open) return undefined;
    const outside = event => { if (!box.current?.contains(event.target)) setOpen(false); };
    const escape = event => { if (event.key === 'Escape') { setOpen(false); trigger.current?.focus(); } };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [open]);

  useEffect(() => { if (open) items.current[index]?.focus(); }, [open, index]);

  const pick = option => { onChange(option.value); setOpen(false); trigger.current?.focus(); };
  const onOptionKey = (event, i) => {
    const last = options.length - 1;
    const move = target => { event.preventDefault(); items.current[target]?.focus(); };
    if (event.key === 'ArrowDown') move(i === last ? 0 : i + 1);
    else if (event.key === 'ArrowUp') move(i === 0 ? last : i - 1);
    else if (event.key === 'Home') move(0);
    else if (event.key === 'End') move(last);
  };

  return <div className="dd" ref={box}>
    <button type="button" ref={trigger} className={`dd-trigger ${open ? 'is-open' : ''}`} style={{ minWidth }}
      aria-haspopup="listbox" aria-expanded={open} aria-label={`${ariaLabel}: ${selected?.label ?? ''}`}
      onClick={() => setOpen(o => !o)}
      onKeyDown={event => { if (event.key === 'ArrowDown') { event.preventDefault(); setOpen(true); } }}>
      <span className="dd-value">{selected?.label ?? 'Select'}</span>
      <svg className="dd-chevron" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg>
    </button>
    {open && <div className={`dd-menu dd-${align}`} role="listbox" aria-label={ariaLabel}>
      {caption && <span className="dd-caption">{caption}</span>}
      {options.map((option, i) => {
        const active = String(option.value) === String(value);
        return <button type="button" key={String(option.value)} ref={el => { items.current[i] = el; }} role="option" aria-selected={active}
          className={`dd-option ${active ? 'is-active' : ''}`} onClick={() => pick(option)} onKeyDown={event => onOptionKey(event, i)}>
          <span className="dd-icon"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 8.5A2.5 2.5 0 0 0 5.5 6H20v4a2 2 0 0 0 0 4v4H5.5A2.5 2.5 0 0 0 3 15.5Z"/></svg></span>
          <span className="dd-label">{option.label}</span>
          {active && <svg className="dd-check" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>}
        </button>;
      })}
    </div>}
  </div>;
}
