// Markdown renderer for the legal pages
import React from 'react';

const safeHref = (url) => {
	const trimmed = (url || '').trim();
	if (/^(https?:|mailto:)/i.test(trimmed)) return trimmed;
	if (/^[/#]/.test(trimmed)) return trimmed;
	return null;
};

const INLINE = [
	{ re: /\*\*([^*]+)\*\*/, render: (m, key, next) => <strong key={key}>{next(m[1])}</strong> },
	{ re: /\*([^*]+)\*/, render: (m, key, next) => <em key={key}>{next(m[1])}</em> },
	{ re: /`([^`]+)`/, render: (m, key) => <code key={key}>{m[1]}</code> },
	{
		re: /\[([^\]]+)\]\(([^)]+)\)/,
		render: (m, key, next) => {
			const href = safeHref(m[2]);
			if (!href) return <span key={key}>{next(m[1])}</span>;
			const external = /^https?:/i.test(href);
			return (
				<a
					key={key}
					href={href}
					{...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
				>
					{next(m[1])}
				</a>
			);
		}
	}
];

function inline(text, depth = 0) {
	if (depth >= INLINE.length) return text;
	const { re, render } = INLINE[depth];
	const parts = [];
	let rest = text;
	let key = 0;
	for (;;) {
		const match = rest.match(re);
		if (!match) {
			parts.push(inline(rest, depth + 1));
			break;
		}
		if (match.index > 0) parts.push(inline(rest.slice(0, match.index), depth + 1));
		parts.push(render(match, `i${depth}-${key += 1}`, (t) => inline(t, depth + 1)));
		rest = rest.slice(match.index + match[0].length);
	}
	return parts;
}

// Group the source into blocks
function blocks(markdown) {
	const lines = (markdown || '').replace(/\r\n?/g, '\n').split('\n');
	const out = [];
	let paragraph = [];
	let list = null;          // { ordered, items: [] }

	const flushParagraph = () => {
		if (paragraph.length) {
			out.push({ type: 'p', text: paragraph.join(' ') });
			paragraph = [];
		}
	};
	const flushList = () => {
		if (list) {
			out.push({ type: 'list', ordered: list.ordered, items: list.items });
			list = null;
		}
	};
	const flush = () => { flushParagraph(); flushList(); };

	for (const raw of lines) {
		const line = raw.trim();

		if (!line) { flush(); continue; }

		const heading = line.match(/^(#{1,6})\s+(.*)$/);
		if (heading) {
			flush();
			out.push({ type: 'h', level: heading[1].length, text: heading[2] });
			continue;
		}

		if (/^(-{3,}|\*{3,}|_{3,})$/.test(line)) { flush(); out.push({ type: 'hr' }); continue; }

		const bullet = line.match(/^[-*]\s+(.*)$/);
		const numbered = line.match(/^\d+[.)]\s+(.*)$/);
		if (bullet || numbered) {
			flushParagraph();
			const ordered = Boolean(numbered);
			if (!list || list.ordered !== ordered) { flushList(); list = { ordered, items: [] }; }
			list.items.push((bullet || numbered)[1]);
			continue;
		}

		const quote = line.match(/^>\s?(.*)$/);
		if (quote) { flush(); out.push({ type: 'quote', text: quote[1] }); continue; }

		flushList();
		paragraph.push(line);
	}
	flush();
	return out;
}

function Markdown({ children, className = '' }) {
	const source = typeof children === 'string' ? children : '';
	const parsed = blocks(source);

	return (
		<div className={className}>
			{parsed.map((block, index) => {
				const key = `b${index}`;
				switch (block.type) {
					case 'h': {
						const Tag = `h${Math.min(block.level + 1, 6)}`;   // # is the page's h2
						return <Tag key={key} className="font-display mt-4 mb-2">{inline(block.text)}</Tag>;
					}
					case 'hr':
						return <hr key={key} />;
					case 'quote':
						return (
							<blockquote key={key} className="border-start border-3 ps-3 text-body-secondary">
								{inline(block.text)}
							</blockquote>
						);
					case 'list': {
						const Tag = block.ordered ? 'ol' : 'ul';
						return (
							<Tag key={key}>
								{block.items.map((item, i) => <li key={`${key}-${i}`}>{inline(item)}</li>)}
							</Tag>
						);
					}
					default:
						return <p key={key}>{inline(block.text)}</p>;
				}
			})}
		</div>
	);
}

export default Markdown;
