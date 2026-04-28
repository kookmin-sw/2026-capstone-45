import { Upload } from "lucide-react";
import { useEffect, useState } from "react";

interface GhostOverlayProps {
	active: boolean;
	onDrop: (files: File[]) => void;
}

export const GhostOverlay = ({ active, onDrop }: GhostOverlayProps) => {
	const [draggingOver, setDraggingOver] = useState(false);

	useEffect(() => {
		if (!active) return;

		const handleDragEnter = (e: DragEvent) => {
			e.preventDefault();
			e.stopPropagation();
			setDraggingOver(true);
		};

		const handleDragLeave = (e: DragEvent) => {
			e.preventDefault();
			e.stopPropagation();
			// Only set to false if we're leaving the window
			if (e.relatedTarget === null) {
				setDraggingOver(false);
			}
		};

		const handleDragOver = (e: DragEvent) => {
			e.preventDefault();
			e.stopPropagation();
		};

		const handleDrop = (e: DragEvent) => {
			e.preventDefault();
			e.stopPropagation();
			setDraggingOver(false);

			if (e.dataTransfer?.files) {
				onDrop(Array.from(e.dataTransfer.files));
			}
		};

		window.addEventListener("dragenter", handleDragEnter);
		window.addEventListener("dragleave", handleDragLeave);
		window.addEventListener("dragover", handleDragOver);
		window.addEventListener("drop", handleDrop);

		return () => {
			window.removeEventListener("dragenter", handleDragEnter);
			window.removeEventListener("dragleave", handleDragLeave);
			window.removeEventListener("dragover", handleDragOver);
			window.removeEventListener("drop", handleDrop);
		};
	}, [active, onDrop]);

	if (!active || !draggingOver) return null;

	return (
		<div className="fixed inset-0 z-200 flex items-center justify-center bg-primary/10 backdrop-blur-[2px] pointer-events-none">
			<div className="w-[calc(100%-40px)] h-[calc(100%-40px)] border-4 border-dashed border-primary rounded-2xl flex flex-col items-center justify-center gap-4 bg-background/80 shadow-2xl animate-in zoom-in-95 duration-200">
				<div className="p-6 rounded-full bg-primary/10">
					<Upload className="w-16 h-16 text-primary animate-bounce" />
				</div>
				<div className="text-center">
					<h2 className="text-3xl font-bold text-foreground">문서 업로드</h2>
				</div>
			</div>
		</div>
	);
};
