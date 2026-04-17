import {
	useQueryRenderedDocument,
	type TRenderedBlock,
	type TRenderedPage,
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
					fontFamily: `${block.font_family}, sans-serif`,
					fontSize: `${block.font_size * zoom}px`,
					color: block.color,
				}}
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
	const zoom = 0.5;
	const doc = useQueryRenderedDocument("temp_id");

	if (!doc.isSuccess) {
		return null;
	}

	return (
		<div style={{ backgroundColor: "#ddd", padding: "1px" }}>
			{renderPages(doc.data.pages, zoom)}
		</div>
	);
}

export default DocumentRender;
