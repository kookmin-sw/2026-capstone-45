import { ActionIcon, Tooltip } from "@mantine/core";
import { Printer } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useAppStore } from "#root/store/useAppStore";
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

function DocumentRender({
	chatId,
	hideControls = false,
	initialZoom = 500,
	autoPrint = false,
}: {
	chatId?: string;
	hideControls?: boolean;
	initialZoom?: number;
	autoPrint?: boolean;
}) {
	const [zoom, setZoom] = useState(initialZoom);
	const { activeChatId } = useAppStore();
	const targetChatId = chatId ?? activeChatId;
	const doc = useQueryRenderedDocument(
		targetChatId ?? "",
		targetChatId !== null && targetChatId !== undefined,
	);

	useEffect(() => {
		if (autoPrint && doc.isSuccess) {
			const timer = setTimeout(() => {
				window.print();
			}, 0);
			return () => clearTimeout(timer);
		}
	}, [autoPrint, doc.isSuccess]);

	const renderedPages = useMemo(() => {
		if (!doc.isSuccess) {
			return null;
		}

		return renderPages(doc.data.pages, zoom / 1000);
	}, [doc, zoom]);

	const handlePrint = () => {
		if (targetChatId) {
			window.open(`/chat/${targetChatId}/print`, "_blank");
		}
	};

	return (
		<>
			{!hideControls && (
				<div className="p-2 border-b border-border bg-background flex items-center gap-2">
					<span className="text-sm font-medium ml-2">줌:&nbsp;</span>
					<ActionIcon
						variant="light"
						color="gray"
						size="sm"
						onClick={() => setZoom((x) => Math.max(x - 25, 25))}
					>
						-
					</ActionIcon>
					<ActionIcon
						variant="light"
						color="gray"
						size="sm"
						onClick={() => setZoom((x) => x + 25)}
					>
						+
					</ActionIcon>
					<span className="text-sm text-muted-foreground">
						&nbsp;{zoom / 1000}x
					</span>
					<div className="ml-auto flex items-center gap-2">
						<Tooltip label="인쇄하기">
							<ActionIcon
								variant="subtle"
								color="gray"
								size="sm"
								onClick={handlePrint}
								disabled={!targetChatId}
							>
								<Printer size={16} />
							</ActionIcon>
						</Tooltip>
					</div>
				</div>
			)}
			<div className="printable flex-1 overflow-auto bg-muted p-4">
				{renderedPages}
			</div>
		</>
	);
}

export default DocumentRender;
