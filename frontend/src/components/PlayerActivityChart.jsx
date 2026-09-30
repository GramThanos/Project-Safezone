// Chart showing the player-activity using Chart.js
import React, { useEffect, useRef } from 'react';

const ACCENT = '#dc3545';

function PlayerActivityChart({ history = [], height = 170 }) {
	const canvasRef = useRef(null);
	const chartRef = useRef(null);

	// A new server has no recorded activity yet; render a flat zero baseline
	// so the chart still shows instead of an empty placeholder.
	const series = history.length > 0
		? history
		: [{ t: Date.now(), count: 0 }, { t: Date.now(), count: 0 }];

	useEffect(() => {
		const Chart = window.Chart;
		if (!Chart || !canvasRef.current) return undefined;

		chartRef.current = new Chart(canvasRef.current, {
			type: 'line',
			data: {
				labels: series.map((p) =>
					new Date(p.t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
				),
				datasets: [{
					label: 'online',
					data: series.map((p) => p.count),
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

	return (
		<div style={{ height }}>
			<canvas ref={canvasRef} />
		</div>
	);
}

export default PlayerActivityChart;
