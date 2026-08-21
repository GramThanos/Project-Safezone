// Admin › shared action picker: choose a whitelisted console action and fill in
// its parameters. The catalog (and every validation rule) comes from the
// game-server, so this component renders whatever the API describes rather than
// hard-coding any command.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { WIKI_COMMANDS } from './helpers';

// Defaults for an action's parameters, so a freshly picked action is valid.
export function defaultParams(action) {
  const values = {};
  (action?.params || []).forEach((p) => {
    if (p.default !== undefined) values[p.name] = p.default;
    else if (p.type === 'bool') values[p.name] = false;
    else values[p.name] = '';
  });
  return values;
}

// Drop empty optional values so the API sees "not provided" rather than "".
export function cleanParams(action, values) {
  const out = {};
  (action?.params || []).forEach((p) => {
    const v = values[p.name];
    if (v === '' || v === undefined || v === null) return;
    out[p.name] = p.type === 'int' ? parseInt(v, 10) : v;
  });
  return out;
}

function ParamField({ param, value, onChange }) {
  const label = param.label || param.name;
  if (param.type === 'bool') {
    return (
      <div className="col-md-4">
        <label className="form-label text-body-secondary">{label}</label>
        <select
          className="form-select"
          value={value ? 'true' : 'false'}
          onChange={(e) => onChange(e.target.value === 'true')}
        >
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      </div>
    );
  }
  if (param.type === 'enum') {
    return (
      <div className="col-md-4">
        <label className="form-label text-body-secondary">{label}</label>
        <select className="form-select" value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
          <option value="">Select…</option>
          {param.options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>
    );
  }
  return (
    <div className="col-md-4">
      <label className="form-label text-body-secondary">{label}</label>
      <input
        type={param.type === 'int' ? 'number' : 'text'}
        className="form-control"
        min={param.min}
        max={param.max}
        placeholder={param.placeholder || ''}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
      />
      {param.help && <div className="form-text">{param.help}</div>}
    </div>
  );
}

/**
 * Props:
 *   droppableOnly  only list actions that may be handed out as loot
 *   actionId       currently selected action id
 *   params         current parameter values
 *   onChange       ({ action_id, action_params, action }) => void
 */
function ActionPicker({ droppableOnly = false, actionId, params, onChange }) {
  const { token } = useAuth();
  const [actions, setActions] = useState([]);
  const [categories, setCategories] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    const load = async () => {
      try {
        const data = await api.admin.actions.getAll(token, droppableOnly);
        setActions(data.actions || []);
        setCategories(data.categories || []);
      } catch (err) {
        console.error('Load actions error:', err);
        setError('Failed to load the action catalog');
      }
    };
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [droppableOnly]);

  const selected = actions.find((a) => a.id === actionId) || null;

  const handleSelect = (id) => {
    const action = actions.find((a) => a.id === id) || null;
    onChange({ action_id: id, action_params: defaultParams(action), action });
  };

  const handleParam = (name, value) => {
    onChange({ action_id: actionId, action_params: { ...params, [name]: value }, action: selected });
  };

  // Only render groups that actually have actions at this role / scope.
  const groups = categories
    .map((c) => ({ ...c, items: actions.filter((a) => a.category === c.id) }))
    .filter((g) => g.items.length > 0);

  return (
    <>
      {error && <div className="col-12"><div className="alert alert-warning py-2 mb-0">{error}</div></div>}
      <div className="col-md-6">
        <label className="form-label text-body-secondary">
          Action
          {/* Every catalog entry maps to a documented console command, so the
              wiki is the reference for what one actually does in game. */}
          <a
            className="link-secondary ms-2"
            href={WIKI_COMMANDS}
            target="_blank"
            rel="noopener noreferrer"
            title="Admin command reference on PZwiki"
          >
            <i className="fas fa-circle-question"></i>
          </a>
        </label>
        <select className="form-select" value={actionId || ''} onChange={(e) => handleSelect(e.target.value)}>
          <option value="">Select an action…</option>
          {groups.map((g) => (
            <optgroup key={g.id} label={g.label}>
              {g.items.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.flavor ? `${a.label} — ${a.flavor}` : a.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>
      {selected && (
        <div className="col-12">
          <div className="form-text mb-2">
            {selected.description}{' '}
            <code>/{selected.command}</code>
            {selected.requires_online && <span className="badge text-bg-secondary ms-2">target must be online</span>}
            {!selected.droppable && <span className="badge text-bg-warning ms-2">staff only</span>}
          </div>
          <div className="row g-2">
            {selected.params.map((p) => (
              <ParamField
                key={p.name}
                param={p}
                value={params?.[p.name]}
                onChange={(v) => handleParam(p.name, v)}
              />
            ))}
          </div>
        </div>
      )}
    </>
  );
}

export default ActionPicker;
