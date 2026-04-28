import { Check } from "lucide-react";

interface BadgeProps {
	variant: "target" | "source";
}

export const Badge = ({ variant }: BadgeProps) => {
	if (variant === "target") {
		return (
			<div className="flex items-center gap-1 px-2 py-1 bg-primary text-primary-foreground text-xs font-semibold rounded-full shadow-sm">
				Target
			</div>
		);
	}

	return (
		<div className="flex items-center gap-1 px-2 py-1 bg-muted text-muted-foreground text-xs font-semibold rounded-full shadow-sm">
			<Check className="w-3 h-3" />
			Selected
		</div>
	);
};
