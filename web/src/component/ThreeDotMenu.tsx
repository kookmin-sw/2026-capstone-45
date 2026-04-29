import { ActionIcon, Button } from "@mantine/core";
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
			<ActionIcon
				variant="subtle"
				color="gray"
				onClick={handleToggle}
				radius="xl"
			>
				<MoreHorizontal className="w-5 h-5 text-muted-foreground" />
			</ActionIcon>

			{open && (
				<div className="absolute right-0 mt-1 w-36 bg-background border border-border rounded-md shadow-lg z-50 py-1">
					{items.map((item) => (
						<Button
							key={item.label}
							variant="subtle"
							color={item.variant === "danger" ? "red" : "gray"}
							fullWidth
							justify="flex-start"
							size="sm"
							onClick={(e) => {
								e.stopPropagation();
								item.onSelect();
								setOpen(false);
							}}
							styles={{
								root: {
									height: "36px",
									padding: "0 12px",
									fontWeight: 400,
								},
							}}
						>
							{item.label}
						</Button>
					))}
				</div>
			)}
		</div>
	);
};
