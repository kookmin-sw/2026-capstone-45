import { useMemo, useState } from "react";
import {
	type TRenderedPage,
	useQueryRenderedDocument,
} from "../query/documentRender";
import styles from "./DocumentRender.module.css";

const renderBlocks = (page: TRenderedPage, zoom: number) => {
	const divs = [];

	for (let i = 0; i < page.blocks.length; i++) {
		const block = page.blocks[i];

		const left = `${(block.bbox[0] * 100) / page.width}%`;
		const top = `${(block.bbox[1] * 100) / page.height}%`;
		const right = `${100 - (block.bbox[2] * 100) / page.width}%`;
		const bottom = `${100 - (block.bbox[3] * 100) / page.height}%`;

		divs.push(
			<div
				key={i}
				className={styles.renderBlock}
				style={{
					position: "absolute",
					left,
					right,
					top,
					bottom,
					lineHeight: `${block.line_height * zoom}px`,
					fontFamily: `'${block.font_family}', sans-serif`,
					fontSize: `${block.font_size * zoom}px`,
					color: block.color,
				}}
				// biome-ignore lint/security/noDangerouslySetInnerHtml: safe
				dangerouslySetInnerHTML={{ __html: block.html }}
			></div>,
		);
	}

	return divs;
};

const renderPages = (pages: TRenderedPage[], zoom: number) => {
	const divs = [];

	for (let i = 0; i < pages.length; i++) {
		const page = pages[i];
		const effectiveWidth = `${page.width * zoom}px`;
		const effectiveHeight = `${page.height * zoom}px`;

		divs.push(
			<div
				key={i}
				style={{
					position: "relative",
					margin: "1rem",
					backgroundColor: "white",
					boxShadow: "5px 5px 3px #666",
					width: effectiveWidth,
					maxWidth: effectiveWidth,
					height: effectiveHeight,
					maxHeight: effectiveHeight,
					background: `url(${page.bg_url}) center / 100% 100% no-repeat`,
				}}
			>
				{renderBlocks(page, zoom)}
			</div>,
		);
	}

	return divs;
};

function DocumentRender() {
	const [zoom, setZoom] = useState(500);
	const [chatId, setChatId] = useState("");
	const doc = useQueryRenderedDocument(chatId, chatId !== "");

	const renderedPages = useMemo(() => {
		if (!doc.isSuccess) {
			return null;
		}

		return renderPages(doc.data.pages, zoom / 1000);
	}, [doc, zoom]);

	return (
		<>
			<div>
				<span>채팅 ID: </span>
				<input
					style={{ border: "1px solid #000" }}
					value={chatId}
					onChange={(e) => setChatId(e.target.value)}
				/>
				<span style={{ marginLeft: "1rem" }}>줌:&nbsp;</span>
				<button
					type="button"
					onClick={() => setZoom((x) => Math.max(x - 25, 25))}
				>
					-
				</button>
				<button type="button" onClick={() => setZoom((x) => x + 25)}>
					+
				</button>
				<span>&nbsp;{zoom / 1000}x</span>
			</div>
			<div
				className="printable"
				style={{ backgroundColor: "#ddd", padding: "1px" }}
			>
				{renderedPages}
			</div>
		</>
	);
}

export default DocumentRender;
