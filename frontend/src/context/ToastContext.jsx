// Transient feedback.
//
// The site had one way to say anything: an alert pinned above the content. That
// works for state that must persist — a form error next to the form — and fails
// for everything that happens later, because a player who has scrolled down to
// their inventory never sees a message that appeared at the top of the page.
// Including, until now, the one saying their reward arrived.
//
// Toasts carry things that *happened*. Alerts stay where they are for things
// that are *true*. The region is a polite live region, so a screen reader hears
// the same news sighted users see.
import React, { createContext, useContext, useState, useCallback, useRef } from 'react';

const ToastContext = createContext({ push: () => {} });

export const useToast = () => useContext(ToastContext);

const LIFETIME_MS = 6000;

const ICONS = {
  success: 'fa-circle-check',
  error: 'fa-circle-exclamation',
  info: 'fa-circle-info'
};

export const ToastProvider = ({ children }) => {
  const [toasts, setToasts] = useState([]);
  const nextId = useRef(0);

  const dismiss = useCallback((id) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  // `action` is an optional { label, onClick } — this is what makes undo
  // possible, which is a kinder pattern than asking "are you sure?" first.
  const push = useCallback((message, { kind = 'info', action, duration = LIFETIME_MS } = {}) => {
    const id = (nextId.current += 1);
    setToasts((current) => [...current, { id, message, kind, action }]);
    if (duration > 0) setTimeout(() => dismiss(id), duration);
    return id;
  }, [dismiss]);

  return (
    <ToastContext.Provider value={{ push, dismiss }}>
      {children}
      <div
        className="toast-region position-fixed bottom-0 end-0 p-3 d-flex flex-column gap-2"
        style={{ zIndex: 1080, maxWidth: 'min(26rem, calc(100vw - 2rem))' }}
        role="status"
        aria-live="polite"
        aria-atomic="false"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`toast show align-items-center border-start border-4 border-${
              toast.kind === 'error' ? 'danger' : toast.kind === 'success' ? 'success' : 'info'
            }`}
          >
            <div className="d-flex align-items-center">
              <div className="toast-body d-flex align-items-center gap-2 flex-grow-1">
                <i className={`fas ${ICONS[toast.kind] || ICONS.info} text-body-secondary`}></i>
                <span>{toast.message}</span>
              </div>
              {toast.action && (
                <button
                  type="button"
                  className="btn btn-sm btn-link text-decoration-none me-1"
                  onClick={() => { toast.action.onClick(); dismiss(toast.id); }}
                >
                  {toast.action.label}
                </button>
              )}
              <button
                type="button"
                className="btn-close me-2 m-auto"
                aria-label="Dismiss"
                onClick={() => dismiss(toast.id)}
              ></button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};

export default ToastContext;
