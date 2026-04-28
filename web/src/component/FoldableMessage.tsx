import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

interface FoldableMessageProps {
	title: string;
	children: React.ReactNode;
	defaultOpen?: boolean;
}

export const FoldableMessage = ({
	title,
	children,
	defaultOpen = false,
}: FoldableMessageProps) => {
	const [isOpen, setIsOpen] = useState(defaultOpen);

	return (
		<div className="w-full mb-2">
			<button
				type="button"
				onClick={() => setIsOpen(!isOpen)}
				className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-muted/50 transition-colors font-medium text-muted-foreground w-full text-left"
			>
				{isOpen ? (
					<ChevronDown className="w-4 h-4" />
				) : (
					<ChevronRight className="w-4 h-4" />
				)}
				<span>{title}</span>
			</button>
			{isOpen && <div className="mt-1 ml-6 space-y-2">{children}</div>}
		</div>
	);
};
