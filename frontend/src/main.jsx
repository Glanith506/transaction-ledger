import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const API = (import.meta.env.VITE_API_URL || 'http://localhost:8000/api').replace(/\/$/, '');
const MODULES = [
  { id: 'dashboard', icon: '◫', label: 'Dashboard', title: 'Your money. A clearer picture.', subtitle: 'A focused summary of your accounts and latest movements.' },
  { id: 'accounts', icon: '◈', label: 'My accounts', title: 'Every account, in one place.', subtitle: 'Create an account, explore its details and choose your next move.' },
  { id: 'transactions', icon: '⇅', label: 'Credit / Debit', title: 'Make your next move.', subtitle: 'Record money coming in or going out of a selected account.' },
  { id: 'transfers', icon: '⇄', label: 'Transfers', title: 'Two accounts. One transfer.', subtitle: 'Move funds with both sides updated together.' },
  { id: 'history', icon: '≡', label: 'Transaction history', title: 'The story behind every balance.', subtitle: 'Explore, filter and export the records for your selected account.' },
];
const readView = () => MODULES.some(m => m.id === location.hash.slice(1)) ? location.hash.slice(1) : 'dashboard';
const cents = value => {
  const [whole, fraction = ''] = String(value || '0').split('.');
  return BigInt(whole || '0') * 100n + BigInt(fraction.padEnd(2, '0').slice(0, 2));
};
const money = value => {
  const amount = typeof value === 'bigint' ? value : cents(value);
  const absolute = amount < 0n ? -amount : amount;
  return `${amount < 0n ? '−' : ''}${(absolute / 100n).toLocaleString('en-IN')}.${String(absolute % 100n).padStart(2, '0')}`;
};
const newReference = () => `TX-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`}`;

async function request(path, body, signal) {
  const response = await fetch(API + path, {
    method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error?.fields?.map(f => `${f.field}: ${f.message}`).join(' · ') || data.error?.message || data.detail || 'The request could not be completed.');
  }
  return data;
}

function AccountPicker({ accounts, selected, onChange, label = 'Selected account', disabled }) {
  return <label className="account-picker">{label}<select value={selected} onChange={e => onChange(e.target.value)} disabled={disabled || !accounts.length} required>
    <option value="" disabled>Choose an account</option>
    {accounts.map(a => <option key={a.id} value={a.id}>{a.name} · {money(a.balance)} units · {a.id.slice(0, 8)}</option>)}
  </select></label>;
}

function ActivityTable({ data, loading, error }) {
  if (loading) return <div className="empty">Loading transactions…</div>;
  if (error) return <div className="empty error-text">{error}</div>;
  if (!data?.items.length) return <div className="empty"><span>◇</span><h3>No movements here yet</h3><p>Recorded transactions will appear here.</p></div>;
  return <div className="table-scroll"><table><thead><tr><th>Transaction</th><th>Reference</th><th>Recorded</th><th className="right">Amount</th></tr></thead><tbody>
    {data.items.map(t => <tr key={t.id}><td><div className="transaction-cell"><span className={`movement-icon ${t.type}`}>{t.type === 'credit' ? '↙' : '↗'}</span><div><strong>{t.description || (t.type === 'credit' ? 'Funds added' : 'Funds withdrawn')}</strong><small>{t.type} · <span title={t.id}>{t.id.slice(0, 8)}</span></small></div></div></td><td className="reference">{t.reference_id}</td><td>{new Date(t.created_at).toLocaleString()}</td><td className={`right amount ${t.type}`}>{t.type === 'credit' ? '+' : '−'}{money(t.amount)}</td></tr>)}
  </tbody></table></div>;
}
  

function TransactionForm({ account, busy, initialType, onSave }) {
  const [type, setType] = useState(initialType);
  const [amount, setAmount] = useState('');
  const [reference, setReference] = useState(newReference);
  const [description, setDescription] = useState('');
  const validAmount = /^\d+(\.\d{1,2})?$/.test(amount) && Number(amount) > 0 && Number(amount) <= 1000000000;
  const next = validAmount ? cents(account.balance) + (type === 'credit' ? cents(amount) : -cents(amount)) : null;
  async function submit(e) {
    e.preventDefault();
    const result = await onSave(`/accounts/${account.id}/transactions`, { type, amount, reference_id: reference.trim(), description: description.trim() }, `${type === 'credit' ? 'Credit' : 'Debit'} recorded for ${account.name}.`);
    if (result) { setAmount(''); setDescription(''); setReference(newReference()); }
  }
  return <form className="transaction-form" onSubmit={submit}><fieldset disabled={busy}>
    <div className="type-switch"><button type="button" className={type === 'credit' ? 'chosen' : ''} aria-pressed={type === 'credit'} onClick={() => setType('credit')}>↙ Credit · add funds</button><button type="button" className={type === 'debit' ? 'chosen' : ''} aria-pressed={type === 'debit'} onClick={() => setType('debit')}>↗ Debit · withdraw</button></div>
    <div className="form-grid"><label>Amount<input type="number" min="0.01" max="1000000000" step="0.01" required placeholder="0.00" value={amount} onChange={e => setAmount(e.target.value)} /></label><label>Reference ID<div className="input-action"><input required maxLength={100} value={reference} onChange={e => setReference(e.target.value)} /><button type="button" title="Generate a new reference" aria-label="Generate new reference" onClick={() => setReference(newReference())}>↻</button></div></label><label className="full">Description <span className="optional">optional</span><input maxLength={500} placeholder="What is this transaction for?" value={description} onChange={e => setDescription(e.target.value)} /></label></div>
    <p className="hint">A unique reference is generated for you. You can enter your own; never reuse one for the same account.</p>
    <div className={`preview ${next !== null && next < 0n ? 'invalid' : ''}`}><span>Balance after this transaction</span><strong>{next === null ? '—' : `${money(next)} units`}</strong></div>
    {next !== null && next < 0n && <p className="error-text">This debit exceeds the available balance.</p>}
    <button className="primary wide" disabled={!validAmount || !reference.trim() || (next !== null && next < 0n)}>{busy ? 'Recording…' : `Record ${type}`} <span>↗</span></button>
  </fieldset></form>;
}

function TransferForm({ account, accounts, busy, onSave }) {
  const [destination, setDestination] = useState('');
  const [amount, setAmount] = useState('');
  const [reference, setReference] = useState(newReference);
  const [description, setDescription] = useState('');
  const recipient = accounts.find(a => a.id === destination);
  const validAmount = /^\d+(\.\d{1,2})?$/.test(amount) && Number(amount) > 0 && Number(amount) <= 1000000000;
  const insufficient = validAmount && cents(amount) > cents(account.balance);
  async function submit(e) {
    e.preventDefault();
    const result = await onSave('/transfers', { source_account_id: account.id, destination_account_id: destination, amount, reference_id: reference.trim(), description: description.trim() }, `Transfer completed from ${account.name} to ${recipient?.name}.`);
    if (result) { setAmount(''); setDescription(''); setReference(newReference()); }
  }
  return <form onSubmit={submit}><fieldset disabled={busy}>
    <label>Destination account<select required value={destination} onChange={e => setDestination(e.target.value)}><option value="" disabled>Choose the receiving account</option>{accounts.filter(a => a.id !== account.id).map(a => <option key={a.id} value={a.id}>{a.name} · {a.id.slice(0, 8)}</option>)}</select></label>
    <div className="transfer-path"><div><small>FROM</small><strong>{account.name}</strong></div><span>→</span><div><small>TO</small><strong>{recipient?.name || 'Choose account'}</strong></div></div>
    <div className="form-grid"><label>Amount<input type="number" min="0.01" max="1000000000" step="0.01" required value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" /></label><label>Reference ID<div className="input-action"><input required maxLength={100} value={reference} onChange={e => setReference(e.target.value)} /><button type="button" aria-label="Generate transfer reference" onClick={() => setReference(newReference())}>↻</button></div></label><label className="full">Description <span className="optional">optional</span><input maxLength={500} value={description} onChange={e => setDescription(e.target.value)} placeholder="Add a transfer note" /></label></div>
    <div className={`preview ${insufficient ? 'invalid' : ''}`}><span>Source balance after transfer</span><strong>{validAmount ? `${money(cents(account.balance) - cents(amount))} units` : '—'}</strong></div>
    {insufficient && <p className="error-text">The source account has insufficient funds.</p>}
    <button className="primary wide" disabled={!destination || !validAmount || insufficient || !reference.trim()}>{busy ? 'Transferring…' : 'Confirm transfer'} <span>↗</span></button>
  </fieldset></form>;
}
function DashboardIcon({ type }) {
  const paths = {
    accounts: (
      <>
        <path d="M3 10 12 4l9 6" />
        <path d="M4 10h16M3 21h18M5 18h14" />
        <path d="M7 10v8M12 10v8M17 10v8" />
      </>
    ),

    balance: (
      <>
        <rect x="3" y="5" width="18" height="15" rx="3" />
        <path d="M3 9h18" />
        <path d="M16 13h5v4h-5a2 2 0 0 1 0-4Z" />
        <path d="M7 15h3" />
      </>
    ),

    selected: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="3" />
        <path d="M3 10h18M7 15h3" />
        <circle cx="18" cy="5" r="4" />
        <path d="m16.5 5 1 1 2-2" />
      </>
    ),

    credit: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v10M7 12h10" />
      </>
    ),

    debit: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M7 12h10" />
      </>
    ),

    transfers: (
      <>
        <path d="M4 7h15m-4-4 4 4-4 4" />
        <path d="M20 17H5m4-4-4 4 4 4" />
      </>
    ),
  };

  return (
    <svg
      width="26"
      height="26"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[type] || paths.balance}
    </svg>
  );
}
function App() {
  const [view, setView] = useState(readView);
  const [accounts, setAccounts] = useState([]);
  const [selected, setSelected] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const saving = useRef(false);
  const [revision, setRevision] = useState(0);
  const [notice, setNotice] = useState(null);
  const [search, setSearch] = useState('');
  const [name, setName] = useState('');
  const [typePreset, setTypePreset] = useState('credit');
  const [filter, setFilter] = useState('');
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(10);
  const [activity, setActivity] = useState(null);
  const [activityLoading, setActivityLoading] = useState(false);
  const [activityError, setActivityError] = useState('');
  const current = accounts.find(a => a.id === selected);
  const module = MODULES.find(m => m.id === view);
  const total = accounts.reduce((sum, a) => sum + cents(a.balance), 0n);

  useEffect(() => {
    const update = () => { setView(readView()); window.scrollTo({ top: 0 }); };
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    request('/accounts', undefined, controller.signal).then(rows => {
      setAccounts(rows);
      setSelected(old => rows.some(a => a.id === old) ? old : rows[0]?.id || '');
    }).catch(e => { if (e.name !== 'AbortError') setNotice({ error: true, text: `Could not refresh accounts: ${e.message}` }); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision]);

  useEffect(() => {
    setActivity(null); setActivityError(''); setActivityLoading(false);
    if (!selected || !['dashboard', 'history'].includes(view)) return;
    const controller = new AbortController();
    setActivityLoading(true);
    const query = new URLSearchParams({ page: String(view === 'dashboard' ? 1 : page), limit: String(view === 'dashboard' ? 5 : limit) });
    if (view === 'history' && filter) query.set('type', filter);
    request(`/accounts/${selected}/transactions?${query}`, undefined, controller.signal).then(setActivity)
      .catch(e => { if (e.name !== 'AbortError') setActivityError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setActivityLoading(false); });
    return () => controller.abort();
  }, [view, selected, filter, page, limit, revision]);

  function navigate(next, type) {
    if (saving.current) return;
    if (type) setTypePreset(type);
    setView(next);
    location.hash = next;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  function chooseAccount(id) { setSelected(id); setPage(1); }
  async function save(path, body, message) {
    if (saving.current) return null;
    saving.current = true; setBusy(true); setNotice(null);
    try {
      const result = await request(path, body);
      if (path === '/accounts') { setAccounts(old => [result, ...old]); chooseAccount(result.id); }
      setRevision(r => r + 1);
      setNotice({ text: message });
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return result;
    } catch (e) {
      setNotice({ error: true, text: e.message });
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return null;
    } finally { saving.current = false; setBusy(false); }
  }
  function exportPage() {
    if (!activity?.items.length) return;
    const cell = value => {
      let text = String(value ?? '');
      if (/^[\s]*[=+@\-]/.test(text) || /^[\t\r\n]/.test(text)) text = "'" + text;
      return '"' + text.replaceAll('"', '""') + '"';
    };
    const rows = [['ID', 'Account ID', 'Type', 'Amount', 'Reference', 'Description', 'Created at'], ...activity.items.map(t => [t.id, t.account_id, t.type, t.amount, t.reference_id, t.description, t.created_at])];
    const url = URL.createObjectURL(new Blob(['\ufeff' + rows.map(r => r.map(cell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = `ledger-${selected}-page-${page}.csv`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const picker = label => <AccountPicker accounts={accounts} selected={selected} onChange={chooseAccount} label={label} disabled={busy || loading} />;
  const emptyAccounts = <div className="panel empty"><span>◈</span><h3>Your first account starts here</h3><p>Create an account before recording movements.</p><button className="primary" onClick={() => navigate('accounts')}>Create an account ↗</button></div>;

  return <div className="app-shell"><aside className="sidebar">
    <button className="brand" onClick={() => navigate('dashboard')} disabled={busy}>▤ <span>ledger<span className="brand-dot">.</span></span></button>
    <div className="sidebar-caption">YOUR WORKSPACE</div>
    <nav aria-label="Main navigation">{MODULES.map(item => <button key={item.id} disabled={busy} className={view === item.id ? 'nav-item active' : 'nav-item'} aria-current={view === item.id ? 'page' : undefined} onClick={() => navigate(item.id)}><span className="nav-icon">{item.icon}</span>{item.label}{item.id === 'accounts' && <small>{accounts.length}</small>}<span className="nav-chevron">›</span></button>)}</nav>
    <div className="sidebar-account"><span className="sidebar-caption">ACTIVE ACCOUNT</span><strong>{current?.name || 'No account selected'}</strong><p>{current ? money(current.balance) : '0.00'} <small>units available</small></p></div>
   <div className="sidebar-note">
  <h3>Need another account?</h3>

  <p>
    Create a separate account for savings or everyday expenses.
  </p>

  <button
    type="button"
    onClick={() => navigate('accounts')}
    disabled={busy}
  >
    Manage accounts →
  </button>
</div>
    <div className="sidebar-footer"><span className="profile">LW</span><div><strong>Local workspace</strong><small>Your personal ledger</small></div></div>
  </aside><main>
    <div className="topbar"><span>Workspace <b>/ {module.label}</b></span><span>{new Date().toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}</span></div>
    <header className="page-heading"><div><div className="eyebrow">{module.label.toUpperCase()}</div><h1>{module.title}</h1><p>{module.subtitle}</p></div><button className="secondary" disabled={busy || loading} onClick={() => setRevision(r => r + 1)}>{loading ? 'Refreshing…' : '↻ Refresh'}</button></header>
    {notice && <div className={`notice ${notice.error ? 'error' : ''}`} role={notice.error ? 'alert' : 'status'}><span>{notice.text}</span><button aria-label="Dismiss notification" onClick={() => setNotice(null)}>×</button></div>}
    {view === 'dashboard' && <div className="module" key="dashboard">
      <section className="hero"><div><span className="eyebrow">A LITTLE CLARITY GOES A LONG WAY</span><h2>Your accounts.<br /><em>Your next chapter.</em></h2><p>Keep a clear view of what you have,<br />and a reliable record of where it goes.</p><button className="primary" onClick={() => navigate('transactions', 'credit')}>＋ Add funds</button></div><div className="atm-card-wrapper">
  <img
    src="/ledger-card.png"
    alt="Ledger demo debit card"
    className="atm-card-image"
  />
</div></section>
      <section className="stats">
  <article>
    <span className="stat-icon">
      <DashboardIcon type="accounts" />
    </span>

    <div>
      <small>TOTAL ACCOUNTS</small>
      <strong>{accounts.length}</strong>
    </div>
  </article>

  <article>
    <span className="stat-icon">
      <DashboardIcon type="balance" />
    </span>

    <div>
      <small>COMBINED BALANCE</small>

      <strong>
        {money(total)} <em>units</em>
      </strong>
    </div>
  </article>

  <article>
    <span className="stat-icon">
      <DashboardIcon type="selected" />
    </span>

    <div>
      <small>SELECTED ACCOUNT BALANCE</small>

      <strong>
        {current ? money(current.balance) : '0.00'}
        {' '}
        <em>units</em>
      </strong>
    </div>
  </article>
</section>
      <section className="quick-grid">{[{ label: 'New account', note: 'Make room for a new goal', icon: '＋', target: 'accounts' }, { label: 'Add funds', note: 'Record a credit', icon: '↙', target: 'transactions', type: 'credit' }, { label: 'Withdraw', note: 'Record a debit', icon: '↗', target: 'transactions', type: 'debit' }, { label: 'Transfer', note: 'Move between accounts', icon: '⇄', target: 'transfers' }].map(action => <button key={action.label} onClick={() => navigate(action.target, action.type)}><span>
  <DashboardIcon type={action.type || action.target} />
</span><div><strong>{action.label}</strong><small>{action.note}</small></div><em>↗</em></button>)}</section>
      <section className="panel"><div className="section-heading"><div><h2>Recent activity</h2><p>Latest five transactions for the selected account.</p></div><button className="text-button" onClick={() => navigate('history')}>View full history ↗</button></div>{picker('Activity account')}<ActivityTable data={activity} loading={activityLoading} error={activityError} /></section>
    </div>}
    {view === 'accounts' && <div className="module" key="accounts"><div className="accounts-layout"><section className="panel"><div className="section-heading"><div><h2>Your accounts <span className="count">{accounts.length}</span></h2><p>Select a card to inspect its details.</p></div></div><input className="search" aria-label="Search accounts" placeholder="Search by account name or ID…" value={search} onChange={e => setSearch(e.target.value)} /><div className="account-grid">{accounts.filter(a => `${a.name} ${a.id}`.toLowerCase().includes(search.toLowerCase())).map(a => <button key={a.id} disabled={busy} aria-pressed={selected === a.id} className={`account-card ${selected === a.id ? 'selected' : ''}`} onClick={() => chooseAccount(a.id)}><div className="card-top"><span className="avatar">{a.name.slice(0, 2).toUpperCase()}</span><small>{selected === a.id ? '● Selected' : 'View details ↗'}</small></div><h3>{a.name}</h3><strong>{money(a.balance)} <small>units</small></strong><span className="card-id">ID · {a.id.slice(0, 8)}</span><small>Opened {new Date(a.created_at).toLocaleDateString()}</small></button>)}</div>{!accounts.length && <div className="empty">No accounts yet. Create one using the form.</div>}{accounts.length > 0 && !accounts.some(a => `${a.name} ${a.id}`.toLowerCase().includes(search.toLowerCase())) && <div className="empty">No accounts match your search.</div>}</section>
      <section className="panel create-panel"><span className="feature-symbol">＋</span><h2>Open a new account</h2><p>Give your account a name you recognise. Every account starts at zero.</p><form onSubmit={async e => { e.preventDefault(); const result = await save('/accounts', { name: name.trim() }, 'Account created. Find it in My accounts.'); if (result) setName(''); }}><label>Account holder / name<input required maxLength={100} value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Savings or Robin Noronha" /></label><button className="primary wide" disabled={busy || !name.trim()}>{busy ? 'Creating…' : 'Create account'} <span>↗</span></button></form><p className="hint">The account ID and creation timestamp are generated automatically.</p></section></div>
      {current && <section className="panel account-details"><div><span className="eyebrow">SELECTED ACCOUNT</span><h2>{current.name}</h2><p className="full-id">{current.id}</p><small>Opened {new Date(current.created_at).toLocaleString()}</small></div><div className="detail-actions"><strong>{money(current.balance)} <small>units</small></strong><div><button className="secondary" onClick={() => navigate('transactions', 'credit')}>＋ Credit</button><button className="secondary" onClick={() => navigate('transactions', 'debit')}>− Debit</button><button className="secondary" onClick={() => navigate('history')}>View history ↗</button></div></div></section>}
    </div>}
    {view === 'transactions' && <div className="module" key="transactions">{!current ? emptyAccounts : <div className="work-layout"><section className="panel"><div className="section-heading"><div><h2>Record a transaction</h2><p>Choose the account before adding or withdrawing funds.</p></div><span className="pill">CREDIT / DEBIT</span></div>{picker('Apply to account')}<TransactionForm key={selected} account={current} busy={busy || loading} initialType={typePreset} onSave={save} /></section><aside className="context-card"><span className="eyebrow">AVAILABLE BALANCE</span><h3>{current.name}</h3><strong>{money(current.balance)}</strong><small>units</small><hr /><h4>Before you confirm</h4><p>Credits increase this balance. Debits decrease it and require sufficient funds.</p><p>Each reference must be unique within this account. Completed records cannot be edited or deleted.</p><button onClick={() => navigate('history')}>View this account’s history ↗</button></aside></div>}</div>}
    {view === 'transfers' && <div className="module" key="transfers">{accounts.length < 2 ? <section className="panel empty"><span>⇄</span><h3>A transfer takes two accounts</h3><p>Create another account to move funds between them.</p><button className="primary" onClick={() => navigate('accounts')}>Open an account ↗</button></section> : current && <div className="work-layout"><section className="panel"><div className="section-heading"><div><h2>Make a transfer</h2><p>Choose the source and receiving account.</p></div><span className="pill">ACCOUNT TO ACCOUNT</span></div>{picker('Source account')}<TransferForm key={selected} account={current} accounts={accounts} busy={busy || loading} onSave={save} /></section><aside className="context-card"><span className="feature-symbol">⇄</span><h3>One complete movement.</h3><p>The source debit and destination credit are saved together.</p><hr /><h4>All or nothing</h4><p>If either side fails, the entire transfer is rolled back. A partial transfer is never saved.</p><p>The reference must be unused on both accounts.</p></aside></div>}</div>}
    {view === 'history' && <div className="module" key="history">{!current ? emptyAccounts : <section className="panel"><div className="section-heading"><div><h2>Account activity</h2><p>Latest entries first. Records are read-only.</p></div><button className="secondary" disabled={activityLoading || !activity?.items.length} onClick={exportPage}>↓ Export page CSV</button></div>{picker('History account')}<div className="history-controls"><div className="filter-buttons">{[['', 'All entries'], ['credit', 'Credits'], ['debit', 'Debits']].map(([value, label]) => <button key={label} className={filter === value ? 'chosen' : ''} onClick={() => { setFilter(value); setPage(1); }}>{label}</button>)}</div><label>Rows per page<select value={limit} onChange={e => { setLimit(Number(e.target.value)); setPage(1); }}>{[5, 10, 25, 50].map(n => <option key={n} value={n}>{n}</option>)}</select></label></div><ActivityTable data={activity} loading={activityLoading} error={activityError} /><footer className="pagination"><span>{activity?.total_records || 0} matching records · Page {page} of {Math.max(1, activity?.total_pages || 0)}</span><div><button className="secondary" disabled={activityLoading || !activity || page <= 1} onClick={() => setPage(p => p - 1)}>← Previous</button><button className="secondary" disabled={activityLoading || !activity || page >= activity.total_pages} onClick={() => setPage(p => p + 1)}>Next →</button></div></footer></section>}</div>}
    <footer className="page-footer">
  <span>Developed by Glanith</span>
</footer>
  </main></div>;
}

createRoot(document.getElementById('root')).render(<App />);
