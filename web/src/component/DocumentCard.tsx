import {
	ActionIcon,
	Button,
	type ButtonVariant,
	type DefaultMantineColor,
	Loader,
} from "@mantine/core";
import { AlertTriangleIcon, Maximize2 } from "lucide-react";
import { useState } from "react";
import type { DocumentListEntry } from "#root/query/documentList";
import { cn } from "../utils/cn";
import { Badge } from "./Badge";

export interface DocumentCardButton {
	text: string;
	variant: ButtonVariant;
	color: DefaultMantineColor;
	action: (docId: number) => unknown;
}

interface DocumentCardProps {
	document: DocumentListEntry;
	onOpen: () => void;
	buttons?: DocumentCardButton[];
	selectionState?: "target" | "source";
}

export const DocumentCard = ({
	document: doc,
	onOpen,
	buttons,
	selectionState,
}: DocumentCardProps) => {
	const [hovered, setHovered] = useState(false);

	return (
		<div
			className={cn(
				"relative aspect-3/4 bg-background border-2 rounded-xl overflow-hidden transition-all group cursor-pointer",
				selectionState === "target" && "border-primary shadow-md",
				selectionState === "source" && "border-secondary shadow-sm",
				selectionState === undefined && "border-border hover:border-border/80",
			)}
			onMouseEnter={() => setHovered(true)}
			onMouseLeave={() => setHovered(false)}
			onClick={onOpen}
		>
			{/* Thumbnail */}
			<div
				className="h-[80%] w-full bg-no-repeat bg-cover flex items-center justify-center"
				style={{
					backgroundImage: `url(/api/documents/${doc.doc_id}/image/0)`,
				}}
			>
				{doc.process_status === "error" ? (
					<AlertTriangleIcon size={40} />
				) : (
					doc.process_status !== "completed" && <Loader size="xl" />
				)}
			</div>

			{/* Footer */}
			<div className="h-[20%] w-full flex items-center px-3 bg-background border-t border-border pointer-events-none">
				<span className="text-sm font-medium truncate">{doc.display_name}</span>
			</div>

			{/* Selection Badge */}
			{selectionState !== undefined && (
				<div className="absolute top-2 left-2 pointer-events-none">
					<Badge variant={selectionState === "target" ? "target" : "source"} />
				</div>
			)}

			{/* Hover Overlay */}
			{hovered && (
				<div className="absolute inset-0 bg-black/60 flex flex-col items-center justify-center gap-3 animate-in fade-in duration-200 z-10">
					<div className="absolute top-2 right-2">
						<ActionIcon variant="subtle" color="white" onClick={onOpen}>
							<Maximize2 size={20} />
						</ActionIcon>
					</div>

					{buttons?.map((btn, i) => (
						<Button
							// biome-ignore lint/suspicious/noArrayIndexKey: won't change
							key={i}
							onClick={(e) => {
								e.stopPropagation();
								btn.action(doc.doc_id);
							}}
							variant={btn.variant}
							color={btn.color}
						>
							{btn.text}
						</Button>
					))}
				</div>
			)}
		</div>
	);
};
