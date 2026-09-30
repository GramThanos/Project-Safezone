// Admin › Loot Boxes: create named boxes and shape each one's loot pool.
//
// A box used to be a fixed size (small/medium/big/bonus). It is now a record an
// operator creates and names, with its own draw count and loot pool. Which box a
// player actually receives is decided on the Events screen; this page is only
// about the boxes themselves and what can come out of them.
//
// The list lives in a table: create a box from the "Add box" modal, then edit a
// box's identity and pool from its "Manage" modal.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useDialog } from '../../context/DialogContext';
import api from '../../services/api';
import { Spinner } from './helpers';
import BoxConfigModal from '../../components/BoxConfigModal';
import BoxCreateModal from '../../components/BoxCreateModal';
import BoxManageModal from '../../components/BoxManageModal';

const slugify = (name) => (name || 'box')
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, '-')
  .replace(/^-+|-+$/g, '') || 'box';

// How many rewards in the pool can actually drop (active, positive weight).
const droppableCount = (box) =>
  (box.pool || []).filter((e) => e.reward?.active && (e.weight || 0) > 0).length;

function Boxes() {
  const { token, isAdmin } = useAuth();
  const { confirm, prompt } = useDialog();
  const admin = isAdmin();
  const [boxes, setBoxes] = useState([]);
  const [rewards, setRewards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [showImport, setShowImport] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [manageBoxId, setManageBoxId] = useState(null);

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setError('');
    try {
      const [boxesData, rewardsData] = await Promise.all([
        api.admin.boxes.getAll(token),
        api.admin.rewards.getAll(token)
      ]);
      setBoxes(boxesData.boxes || []);
      setRewards(rewardsData.rewards || []);
    } catch (err) {
      console.error('Load boxes error:', err);
      setError('Failed to load loot boxes');
    }
    setLoading(false);
  };

  // These actions throw on failure so the modal that called them can surface the
  // error over its own content. Each reloads so open modals see fresh box data.
  const createBox = async (payload) => {
    await api.admin.boxes.create(token, payload);
    await loadData();
    setNotice('Box created. Open its Manage view to fill the loot pool.');
  };

  // Used by the import modal when the config lands in a brand-new box: creates
  // the box and returns it so the modal can import the config's pool into it.
  const createBoxFromConfig = async (payload) => {
    const data = await api.admin.boxes.create(token, payload);
    return data.box;
  };

  // Undo for the above: if the pool import fails after the box was created, the
  // modal hands the box back so the whole import lands or nothing does.
  const discardBoxFromConfig = async (box) => {
    await api.admin.boxes.remove(token, box.id);
  };

  const updateBoxField = async (box, patch) => {
    await api.admin.boxes.update(token, box.id, patch);
    await loadData();
  };

  const deleteBox = async (box) => {
    await api.admin.boxes.remove(token, box.id);
    setManageBoxId(null);
    await loadData();
    setNotice('Box deleted.');
  };

  // Delete straight from the table row: confirm here (the manage modal has its
  // own confirm for its Delete button) and surface any failure on the page.
  const handleDeleteRow = async (box) => {
    const linked = (box.events || []).length;
    const extra = linked
      ? ` It will be removed from ${linked} event${linked === 1 ? '' : 's'}.`
      : '';
    if (!(await confirm({
      title: 'Delete box?',
      message: `Delete the "${box.name}" box? Its loot pool goes with it.${extra}`,
      confirmLabel: 'Delete'
    }))) {
      return;
    }
    setError('');
    setNotice('');
    try {
      await deleteBox(box);
    } catch (err) {
      console.error('Delete box error:', err);
      setError(err.message || 'Failed to delete that box');
    }
  };

  const addPool = async (box, { reward_id, count }) => {
    await api.admin.boxPools.add(token, {
      box_id: box.id, reward_id, weight: 1, count
    });
    await loadData();
  };

  const removePool = async (id) => {
    await api.admin.boxPools.remove(token, id);
    await loadData();
  };

  const setPoolWeight = async (entryId, weight) => {
    await api.admin.boxPools.setWeight(token, entryId, weight);
    await loadData();
  };

  const setPoolCount = async (entryId, count) => {
    await api.admin.boxPools.setCount(token, entryId, count);
    await loadData();
  };

  const exportBox = async (box) => {
    const answer = await prompt({
      title: 'Export box configuration',
      confirmLabel: 'Export',
      fields: [
        { name: 'name', label: 'Name for this box configuration', initial: box.name, required: true },
        { name: 'description', label: 'Short description (optional)', initial: box.description || '' }
      ]
    });
    if (!answer) return;
    const name = answer.name.trim();
    const description = answer.description.trim();
    const config = await api.admin.rewardBoxes.export(token, { box_id: box.id, name, description });
    const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${slugify(name)}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleImported = (summary, boxName) => {
    setShowImport(false);
    setError('');
    const s = summary || {};
    setNotice(
      `Imported into the ${boxName} box: ${s.created || 0} reward(s) created, ` +
      `${s.added || 0} added to the pool, ${s.reweighted || 0} reweighted` +
      (s.removed ? `, ${s.removed} removed` : '') + '.'
    );
    loadData();
  };

  if (loading) return <Spinner />;

  const unhealthy = boxes.filter((b) => b.health && (b.health.empty || b.health.thin));
  const manageBox = boxes.find((b) => b.id === manageBoxId) || null;

  return (
    <>
      <div className="d-flex flex-wrap justify-content-between align-items-baseline gap-2">
        <h4 className="font-display mb-1">Loot Boxes</h4>
        {admin && (
          <div className="d-flex gap-2">
            <button className="btn btn-sm btn-outline-secondary" onClick={() => setShowImport(true)}>
              <i className="fas fa-upload me-1"></i> Import config
            </button>
            <button className="btn btn-sm btn-danger" onClick={() => setShowCreate(true)}>
              <i className="fas fa-plus me-1"></i> Add box
            </button>
          </div>
        )}
      </div>
      <p className="text-body-secondary">
        Manage and configure the available reward boxes.
      </p>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      {unhealthy.length > 0 && (
        <div className="alert alert-warning">
          {unhealthy.filter((b) => b.health.empty).map((b) => (
            <div key={b.id}>
              <strong>{b.name}</strong> has nothing that can drop. A player who gets
              this box will not be able to open it.
            </div>
          ))}
          {unhealthy.filter((b) => b.health.thin).map((b) => (
            <div key={b.id}>
              <strong>{b.name}</strong> draws {b.health.draws} but only{' '}
              {b.health.droppable} reward{b.health.droppable === 1 ? '' : 's'} can
              drop, so it will repeat them.
            </div>
          ))}
        </div>
      )}

      {boxes.length === 0 ? (
        <p className="text-body-secondary">
          No boxes yet.{admin && ' Use “Add box” to create one.'}
        </p>
      ) : (
        <div className="card">
          <div className="table-responsive">
            <table className="table table-hover align-middle mb-0">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Description</th>
                  <th style={{ width: '5rem' }}>Draws</th>
                  <th style={{ width: '10rem' }}>Loot pool</th>
                  <th style={{ width: '12rem' }}>Events</th>
                  <th style={{ width: '6rem' }}></th>
                </tr>
              </thead>
              <tbody>
                {boxes.map((box) => {
                  const total = (box.pool || []).length;
                  const droppable = droppableCount(box);
                  const empty = box.health?.empty;
                  const thin = box.health?.thin;
                  return (
                    <tr key={box.id}>
                      <td className="fw-semibold">{box.name}</td>
                      <td className="text-body-secondary">
                        {box.description || <span className="fst-italic">—</span>}
                      </td>
                      <td>{box.draws}</td>
                      <td>
                        <span className="text-body-secondary">
                          {droppable}/{total} can drop
                        </span>
                        {empty && (
                          <span className="badge text-bg-danger ms-2">empty</span>
                        )}
                        {!empty && thin && (
                          <span className="badge text-bg-warning ms-2">thin</span>
                        )}
                      </td>
                      <td>
                        {(box.events || []).length === 0 ? (
                          <span className="text-body-secondary fst-italic">—</span>
                        ) : (
                          <div className="d-flex flex-wrap gap-1">
                            {box.events.map((ev) => (
                              <span
                                key={ev.id}
                                className="badge text-bg-secondary"
                                title={`Linked to the ${ev.name} event`}
                              >
                                {ev.name}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="text-end">
                        {admin ? (
                          <div className="btn-group btn-group-sm">
                            <button
                              className="btn btn-outline-secondary"
                              title="Edit this box"
                              onClick={() => setManageBoxId(box.id)}
                            >
                              <i className="fas fa-pen"></i>
                            </button>
                            <button
                              className="btn btn-outline-danger"
                              title="Delete this box"
                              onClick={() => handleDeleteRow(box)}
                            >
                              <i className="fas fa-trash"></i>
                            </button>
                          </div>
                        ) : (
                          <button
                            className="btn btn-sm btn-outline-secondary"
                            title="View this box"
                            onClick={() => setManageBoxId(box.id)}
                          >
                            <i className="fas fa-eye me-1"></i> View
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showCreate && (
        <BoxCreateModal
          onCreate={createBox}
          onClose={() => setShowCreate(false)}
        />
      )}

      {manageBox && (
        <BoxManageModal
          box={manageBox}
          rewards={rewards}
          admin={admin}
          onUpdateField={updateBoxField}
          onDelete={deleteBox}
          onExport={exportBox}
          onAddPool={addPool}
          onRemovePool={removePool}
          onReweight={setPoolWeight}
          onRecount={setPoolCount}
          onClose={() => setManageBoxId(null)}
        />
      )}

      {showImport && (
        <BoxConfigModal
          boxes={boxes.map((b) => ({ id: b.id, name: b.name }))}
          onCreateBox={createBoxFromConfig}
          onDiscardBox={discardBoxFromConfig}
          onImported={handleImported}
          onClose={() => setShowImport(false)}
        />
      )}
    </>
  );
}

export default Boxes;
