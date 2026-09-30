// Confirmations and short questions, asked in the site's own modals.
//
// The browser's confirm/prompt dialogs look like the browser, not the site,
// block the whole tab, and on some mobile browsers can be silenced for the
// page entirely - after which every "are you sure?" answers itself. These
// keep the call sites as short as the originals:
//
//   if (!(await confirm({ title: 'Delete it?', message: '…' }))) return;
//   const values = await prompt({ title: 'Export', fields: [{ name, label }] });
import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import ConfirmDialog from '../components/ConfirmDialog';

const DialogContext = createContext({
	confirm: async () => false,
	prompt: async () => null
});

export const useDialog = () => useContext(DialogContext);

// Same stacking as ConfirmDialog, for the same reason.
const Z_INDEX = 1070;

function PromptDialog({ title, message, fields, confirmLabel = 'OK', onSubmit, onCancel }) {
	const [values, setValues] = useState(() => Object.fromEntries(
		fields.map((f) => [f.name, f.initial ?? ''])
	));
	const firstRef = useRef(null);

	useEffect(() => {
		firstRef.current?.focus();
		firstRef.current?.select();
		const onKey = (e) => {
			if (e.key !== 'Escape') return;
			e.stopPropagation();
			onCancel();
		};
		window.addEventListener('keydown', onKey, true);
		return () => window.removeEventListener('keydown', onKey, true);
	}, [onCancel]);

	const missing = fields.some((f) => f.required && !String(values[f.name]).trim());

	const submit = (e) => {
		e.preventDefault();
		if (!missing) onSubmit(values);
	};

	return (
		<div
			className="modal show d-block"
			style={{ backgroundColor: 'rgba(0,0,0,.6)', zIndex: Z_INDEX }}
			onClick={onCancel}
			role="dialog"
			aria-modal="true"
			aria-labelledby="prompt-title"
		>
			<div className="modal-dialog modal-dialog-centered" onClick={(e) => e.stopPropagation()}>
				<form className="modal-content" onSubmit={submit}>
					<div className="modal-header">
						<h5 className="modal-title font-display" id="prompt-title">{title}</h5>
					</div>
					<div className="modal-body">
						{message && <p style={{ whiteSpace: 'pre-line' }}>{message}</p>}
						{fields.map((f, i) => (
							<div key={f.name} className={i < fields.length - 1 ? 'mb-3' : ''}>
								<label className="form-label" htmlFor={`prompt-${f.name}`}>{f.label}</label>
								<input
									id={`prompt-${f.name}`}
									ref={i === 0 ? firstRef : undefined}
									className="form-control"
									value={values[f.name]}
									placeholder={f.placeholder}
									onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
								/>
							</div>
						))}
					</div>
					<div className="modal-footer">
						<button type="button" className="btn btn-outline-secondary" onClick={onCancel}>
							Cancel
						</button>
						<button type="submit" className="btn btn-danger" disabled={missing}>
							{confirmLabel}
						</button>
					</div>
				</form>
			</div>
		</div>
	);
}

export const DialogProvider = ({ children }) => {
	// One dialog at a time; asking again while one is open answers the first no.
	const [dialog, setDialog] = useState(null);

	const open = useCallback((kind, options, empty) => new Promise((resolve) => {
		setDialog((current) => {
			if (current) current.resolve(empty);
			return { kind, options, resolve };
		});
	}), []);

	const confirm = useCallback((options) => open('confirm', options, false), [open]);
	const prompt = useCallback((options) => open('prompt', options, null), [open]);

	const close = useCallback((answer) => {
		setDialog((current) => {
			if (current) current.resolve(answer);
			return null;
		});
	}, []);

	const cancelConfirm = useCallback(() => close(false), [close]);
	const cancelPrompt = useCallback(() => close(null), [close]);

	return (
		<DialogContext.Provider value={{ confirm, prompt }}>
			{children}
			{dialog?.kind === 'confirm' && (
				<ConfirmDialog
					title={dialog.options.title || 'Are you sure?'}
					confirmLabel={dialog.options.confirmLabel}
					danger={dialog.options.danger !== false}
					onConfirm={() => close(true)}
					onCancel={cancelConfirm}
				>
					{dialog.options.message}
				</ConfirmDialog>
			)}
			{dialog?.kind === 'prompt' && (
				<PromptDialog
					title={dialog.options.title}
					message={dialog.options.message}
					fields={dialog.options.fields}
					confirmLabel={dialog.options.confirmLabel}
					onSubmit={(values) => close(values)}
					onCancel={cancelPrompt}
				/>
			)}
		</DialogContext.Provider>
	);
};

export default DialogContext;
