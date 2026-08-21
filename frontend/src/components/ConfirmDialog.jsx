// In-page confirmation prompt
import React, { useEffect, useRef } from 'react';

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
		const onKey = (e) => { if (e.key === 'Escape' && !busy) onCancel(); };
		document.addEventListener('keydown', onKey);
		return () => document.removeEventListener('keydown', onKey);
	}, [onCancel, busy]);

	return (
		<div
			className="modal show d-block"
			style={{ backgroundColor: 'rgba(0,0,0,.6)' }}
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
					<div className="modal-body">{children}</div>
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
