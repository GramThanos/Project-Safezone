// Chart showing the player-activity using Chart.js
import React, { useEffect, useRef } from 'react';

const ACCENT = '#dc3545';

function PlayerActivityChart({ history = [], height = 170 }) {
	const canvasRef = useRef(null);
	const chartRef = useRef(null);

	useEffect(() => {
		const Chart = window.Chart;
		if (!Chart || !canvasRef.current || history.length === 0) return undefined;

		chartRef.current = new Chart(canvasRef.current, {
			type: 'line',
			data: {
				labels: history.map((p) =>
					new Date(p.t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
				),
				datasets: [{
					label: 'online',
					data: history.map((p) => p.count),
					borderColor: ACCENT,
					backgroundColor: 'rgba(220, 53, 69, 0.18)',
					fill: true,
					tension: 0.3,
					borderWidth: 2,
					pointRadius: 0,
					pointHoverRadius: 4
				}]
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				animation: false,
				interaction: { intersect: false, mode: 'index' },
				plugins: {
					legend: { display: false },
					tooltip: {
						callbacks: {
							label: (ctx) => `${ctx.parsed.y} online`
						}
					}
				},
				scales: {
					x: { display: false },
					y: { display: false, beginAtZero: true }
				}
			}
		});

		return () => {
			chartRef.current?.destroy();
			chartRef.current = null;
		};
	}, [history]);

	if (history.length === 0) {
		return <p className="text-body-secondary small mb-0">No activity recorded yet.</p>;
	}

	return (
		<div style={{ height }}>
			<canvas ref={canvasRef} />
		</div>
	);
}

export default PlayerActivityChart;
