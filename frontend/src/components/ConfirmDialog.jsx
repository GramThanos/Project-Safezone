// In-page confirmation prompt
import React, { useEffect, useRef } from 'react';

// Above Bootstrap's own modals (1055), so a confirm raised from inside one
// opens on top of it rather than behind.
const Z_INDEX = 1070;

function ConfirmDialog({
	title,
	children,
	confirmLabel = 'Confirm',
	cancelLabel = 'Cancel',
	danger = true,
	busy = false,
	onConfirm,
	onCancel
}) {
	const cancelRef = useRef(null);

	useEffect(() => {
		cancelRef.current?.focus();
		// Captured on window and stopped there, so Escape closes this dialog
		// and not also the modal it was opened from.
		const onKey = (e) => {
			if (e.key !== 'Escape') return;
			e.stopPropagation();
			if (!busy) onCancel();
		};
		window.addEventListener('keydown', onKey, true);
		return () => window.removeEventListener('keydown', onKey, true);
	}, [onCancel, busy]);

	return (
		<div
			className="modal show d-block"
			style={{ backgroundColor: 'rgba(0,0,0,.6)', zIndex: Z_INDEX }}
			onClick={() => { if (!busy) onCancel(); }}
			role="dialog"
			aria-modal="true"
			aria-labelledby="confirm-title"
		>
			<div className="modal-dialog modal-dialog-centered" onClick={(e) => e.stopPropagation()}>
				<div className="modal-content">
					<div className="modal-header">
						<h5 className="modal-title font-display" id="confirm-title">{title}</h5>
					</div>
					<div className="modal-body" style={{ whiteSpace: 'pre-line' }}>{children}</div>
					<div className="modal-footer">
						<button
							ref={cancelRef}
							className="btn btn-outline-secondary"
							onClick={onCancel}
							disabled={busy}
						>
							{cancelLabel}
						</button>
						<button
							className={`btn btn-${danger ? 'danger' : 'primary'}`}
							onClick={onConfirm}
							disabled={busy}
						>
							{busy ? 'Working...' : confirmLabel}
						</button>
					</div>
				</div>
			</div>
		</div>
	);
}

export default ConfirmDialog;
