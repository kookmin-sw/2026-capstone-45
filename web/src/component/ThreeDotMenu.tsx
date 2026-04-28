import { MoreHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { MenuItem } from "#root/types";

interface ThreeDotMenuProps {
	items: MenuItem[];
	onOpenChange?: (open: boolean) => void;
}

export const ThreeDotMenu = ({ items, onOpenChange }: ThreeDotMenuProps) => {
	const [open, setOpen] = useState(false);
	const menuRef = useRef<HTMLDivElement>(null);

	useEffect(() => {
		const handleClickOutside = (event: MouseEvent) => {
			if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
				setOpen(false);
			}
		};

		if (open) {
			document.addEventListener("mousedown", handleClickOutside);
		}
		return () => {
			document.removeEventListener("mousedown", handleClickOutside);
		};
	}, [open]);

	useEffect(() => {
		onOpenChange?.(open);
	}, [open, onOpenChange]);

	const handleToggle = (e: React.MouseEvent) => {
		e.stopPropagation();
		setOpen(!open);
	};

	return (
		<div className="relative" ref={menuRef}>
			<button
				type="button"
				onClick={handleToggle}
				className="p-1 rounded-full hover:bg-muted transition-colors"
			>
				<MoreHorizontal className="w-5 h-5 text-muted-foreground" />
			</button>

			{open && (
				<div className="absolute right-0 mt-1 w-36 bg-background border border-border rounded-md shadow-lg z-50 py-1">
					{items.map((item) => (
						<button
							key={item.label}
							type="button"
							className={`w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors ${
								item.variant === "danger"
									? "text-destructive"
									: "text-foreground"
							}`}
							onClick={(e) => {
								e.stopPropagation();
								item.onSelect();
								setOpen(false);
							}}
						>
							{item.label}
						</button>
					))}
				</div>
			)}
		</div>
	);
};
