// Chart showing the player-activity using Chart.js
import React, { useEffect, useRef } from 'react';
import { formatDayTime, formatTime, parseDate } from '../utils/dates';

const ACCENT = '#dc3545';
const MUTED = '#adb5bd';
const GRID = 'rgba(255, 255, 255, 0.08)';
const HOUR = 60 * 60 * 1000;
const TICK_HOURS = 6;

// Ticks on whole local hours that are a multiple of TICK_HOURS (00, 06, 12,
// 18 in the viewer's zone), so the axis reads like a clock.
const clockTicks = (axis) => {
	const ticks = [];
	const at = new Date(axis.min);
	at.setMinutes(0, 0, 0);
	if (at.getTime() < axis.min) at.setHours(at.getHours() + 1);
	while (at.getHours() % TICK_HOURS !== 0) at.setHours(at.getHours() + 1);
	for (; at.getTime() <= axis.max; at.setHours(at.getHours() + TICK_HOURS)) {
		ticks.push({ value: at.getTime() });
	}
	axis.ticks = ticks;
};

function PlayerActivityChart({ history = [], height = 170 }) {
	const canvasRef = useRef(null);
	const chartRef = useRef(null);

	useEffect(() => {
		const Chart = window.Chart;
		if (!Chart || !canvasRef.current) return undefined;

		// Times arrive with a UTC offset and are plotted as epoch milliseconds on
		// a linear axis, so spacing is true and labels are in the viewer's zone.
		const points = history
			.map((p) => ({ x: parseDate(p.t)?.getTime(), y: p.count }))
			.filter((p) => Number.isFinite(p.x));
		// A new server has no recorded activity yet; render a flat zero baseline
		// so the chart still shows instead of an empty placeholder.
		const now = Date.now();
		const data = points.length > 1
			? points
			: [{ x: now - 24 * HOUR, y: 0 }, { x: now, y: 0 }];

		chartRef.current = new Chart(canvasRef.current, {
			type: 'line',
			data: {
				datasets: [{
					label: 'online',
					data,
					borderColor: ACCENT,
					backgroundColor: 'rgba(220, 53, 69, 0.18)',
					fill: 'origin',
					// Monotone never overshoots, so the curve cannot dip below 0
					// or above a real peak.
					cubicInterpolationMode: 'monotone',
					borderWidth: 2,
					pointRadius: 0,
					pointHoverRadius: 4,
					// Draw the line over the chart-area edge instead of losing
					// half of it when it lies on 0.
					clip: false
				}]
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				animation: false,
				interaction: { intersect: false, mode: 'index' },
				layout: { padding: { top: 4 } },
				plugins: {
					legend: { display: false },
					tooltip: {
						callbacks: {
							// The bucket the point stands for: "Sun 11, 09:15 – 09:30".
							title: (items) => {
								const item = items[0];
								if (!item) return '';
								const start = item.parsed.x;
								const next = data[item.dataIndex + 1]?.x;
								const prev = data[item.dataIndex - 1]?.x;
								const width = next ? next - start : (prev ? start - prev : 0);
								const from = formatDayTime(start);
								// Not for the empty placeholder, whose two points are a day apart.
								return width && width <= HOUR ? `${from} – ${formatTime(start + width)}` : from;
							},
							label: (ctx) => {
								const n = ctx.parsed.y;
								return n === 0 ? 'Nobody online' : `Up to ${n} ${n === 1 ? 'survivor' : 'survivors'} online`;
							}
						}
					}
				},
				scales: {
					x: {
						type: 'linear',
						min: data[0].x,
						max: data[data.length - 1].x,
						afterBuildTicks: clockTicks,
						grid: { color: GRID },
						border: { display: false },
						ticks: {
							color: MUTED,
							font: { size: 10 },
							maxRotation: 0,
							callback: (value) => formatTime(value)
						}
					},
					y: {
						min: 0,
						// An empty server still gets a 0..1 range, so the zero
						// line sits on the bottom instead of the middle.
						suggestedMax: 1,
						grid: { color: GRID },
						border: { display: false },
						ticks: {
							color: MUTED,
							font: { size: 10 },
							precision: 0,
							maxTicksLimit: 3
						}
					}
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
			<canvas ref={canvasRef} aria-label="Players online over the last 24 hours" role="img" />
		</div>
	);
}

export default PlayerActivityChart;
