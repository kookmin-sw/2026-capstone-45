import { Maximize2 } from "lucide-react";
import { useState } from "react";
import type { Document } from "#root/query/documentList";
import { cn } from "../utils/cn";
import { Badge } from "./Badge";

export interface DocumentCardButton {
	className: string;
	text: string;
	action: (docId: number) => unknown;
}

interface DocumentCardProps {
	document: Document;
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
				className="h-[80%] w-full bg-no-repeat bg-cover"
				style={{
					backgroundImage: `url(/api/documents/${doc.doc_id}/image/0)`,
				}}
			/>

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
					<button
						type="button"
						onClick={onOpen}
						className="absolute top-2 right-2 p-1.5 bg-white/20 hover:bg-white/30 rounded-lg text-white transition-colors"
					>
						<Maximize2 className="w-5 h-5" />
					</button>

					{buttons?.map((btn, i) => (
						<button
							// biome-ignore lint/suspicious/noArrayIndexKey: won't change
							key={i}
							type="button"
							onClick={() => btn.action(doc.doc_id)}
							className={`px-4 py-2 text-foreground rounded-lg font-semibold transition-colors ${btn.className}`}
						>
							{btn.text}
						</button>
					))}
				</div>
			)}
		</div>
	);
};
