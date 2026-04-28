import { Maximize2 } from "lucide-react";
import { useState } from "react";
import type { Document, MenuItem } from "#root/types";
import { Badge } from "./Badge";
import { FileMetadata } from "./FileMetadata";
import { ThreeDotMenu } from "./ThreeDotMenu";

interface DocumentCardProps {
	document: Document;
	// TODO: discriminated union
	mode: "library" | "select" | "context";
	onOpen: () => void;
	// mode="library"
	onDetails?: () => void;
	onRename?: () => void;
	onDelete?: () => void;
	// mode="select"
	selectionState?: "none" | "target" | "source";
	onSetTarget?: () => void;
	onAddSource?: () => void;
	onRemoveSelection?: () => void;
}

export const DocumentCard = ({
	document: doc,
	mode,
	onOpen,
	onDetails,
	onRename,
	onDelete,
	selectionState = "none",
	onSetTarget,
	onAddSource,
	onRemoveSelection,
}: DocumentCardProps) => {
	const [hovered, setHovered] = useState(false);

	if (mode === "library") {
		const menuItems: MenuItem[] = [
			{ label: "속성", onSelect: () => onDetails?.() },
			{ label: "이름 바꾸기", onSelect: () => onRename?.() },
			{ label: "삭제", onSelect: () => onDelete?.(), variant: "danger" },
		];

		return (
			<button
				type="button"
				className="group flex items-center justify-between p-4 bg-background border border-border rounded-lg hover:border-primary/50 hover:bg-muted/30 transition-all cursor-pointer w-full text-left"
				onClick={onOpen}
			>
				<div className="flex-1 min-w-0">
					<FileMetadata
						filename={doc.filename}
						uploadedAt={doc.uploadedAt}
						sizeBytes={doc.sizeBytes}
					/>
				</div>
				<ThreeDotMenu items={menuItems} />
			</button>
		);
	}

	if (mode === "select") {
		return (
			<div
				className={`relative aspect-[3/4] bg-background border-2 rounded-xl overflow-hidden transition-all group ${
					selectionState === "target"
						? "border-primary shadow-md"
						: selectionState === "source"
							? "border-secondary shadow-sm"
							: "border-border hover:border-border/80"
				}`}
				onMouseEnter={() => setHovered(true)}
				onMouseLeave={() => setHovered(false)}
			>
				{/* Background trigger to satisfy semantic requirements without nesting buttons */}
				<button
					type="button"
					className="absolute inset-0 w-full h-full z-0 p-0 border-none bg-transparent cursor-pointer"
					onClick={onOpen}
				/>

				{/* Thumbnail */}
				<div className="h-[80%] w-full bg-muted pointer-events-none">
					<img
						src={doc.thumbnailUrl}
						alt={doc.filename}
						className="w-full h-full object-cover"
					/>
				</div>

				{/* Footer */}
				<div className="h-[20%] w-full flex items-center px-3 bg-background border-t border-border pointer-events-none">
					<span className="text-sm font-medium truncate">{doc.filename}</span>
				</div>

				{/* Selection Badge */}
				{selectionState !== "none" && (
					<div className="absolute top-2 left-2 pointer-events-none">
						<Badge
							variant={selectionState === "target" ? "target" : "source"}
						/>
					</div>
				)}

				{/* Hover Overlay */}
				{hovered && (
					<div className="absolute inset-0 bg-black/60 flex flex-col items-center justify-center gap-3 animate-in fade-in duration-200 z-10">
						<button
							type="button"
							onClick={(e) => {
								e.stopPropagation();
								onOpen();
							}}
							className="absolute top-2 right-2 p-1.5 bg-white/20 hover:bg-white/30 rounded-lg text-white transition-colors"
						>
							<Maximize2 className="w-5 h-5" />
						</button>

						{selectionState === "target" ? (
							<button
								type="button"
								onClick={(e) => {
									e.stopPropagation();
									onRemoveSelection?.();
								}}
								className="px-4 py-2 bg-white text-foreground rounded-lg font-semibold hover:bg-white/90 transition-colors"
							>
								타깃 제거
							</button>
						) : (
							<button
								type="button"
								onClick={(e) => {
									e.stopPropagation();
									onSetTarget?.();
								}}
								className="px-4 py-2 bg-primary text-primary-foreground rounded-lg font-semibold hover:opacity-90 transition-colors"
							>
								타깃 설정
							</button>
						)}

						{selectionState === "source" ? (
							<button
								type="button"
								onClick={(e) => {
									e.stopPropagation();
									onRemoveSelection?.();
								}}
								className="px-4 py-2 bg-white/20 text-white border border-white/30 rounded-lg font-semibold hover:bg-white/30 transition-colors"
							>
								소스 제거
							</button>
						) : (
							<button
								type="button"
								onClick={(e) => {
									e.stopPropagation();
									onAddSource?.();
								}}
								className="px-4 py-2 bg-white/20 text-white border border-white/30 rounded-lg font-semibold hover:bg-white/30 transition-colors"
							>
								소스 추가
							</button>
						)}
					</div>
				)}
			</div>
		);
	}

	// mode === "context"
	return (
		<button
			type="button"
			className="relative aspect-[3/4] bg-background border border-border rounded-lg overflow-hidden group cursor-pointer transition-all hover:border-primary/50 shadow-sm w-full p-0"
			onMouseEnter={() => setHovered(true)}
			onMouseLeave={() => setHovered(false)}
			onClick={onOpen}
		>
			<img
				src={doc.thumbnailUrl}
				alt={doc.filename}
				className="w-full h-full object-cover"
			/>
			{hovered && (
				<div className="absolute inset-0 bg-black/40 flex items-center justify-center animate-in fade-in duration-200">
					<Maximize2 className="w-8 h-8 text-white opacity-80" />
				</div>
			)}
		</button>
	);
};
