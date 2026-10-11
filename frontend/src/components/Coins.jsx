// A coin amount, drawn the same way wherever one appears: the balance in the
// account menu, a price in the shop, what a sale pays.
import React from 'react';

export const coinWord = (n) => `coin${n === 1 ? '' : 's'}`;

function Coins({ amount, className = '', label = false }) {
	const n = amount || 0;
	return (
		<span className={`text-nowrap ${className}`} title={`${n.toLocaleString()} ${coinWord(n)}`}>
			<i className="fas fa-coins text-warning me-1" aria-hidden="true"></i>
			{n.toLocaleString()}
			{label && ` ${coinWord(n)}`}
		</span>
	);
}

export default Coins;
