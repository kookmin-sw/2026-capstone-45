import { Button } from "@mantine/core";
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
			<Button
				variant="subtle"
				color="gray"
				fullWidth
				justify="flex-start"
				onClick={() => setIsOpen(!isOpen)}
				leftSection={
					isOpen ? (
						<ChevronDown className="w-4 h-4" />
					) : (
						<ChevronRight className="w-4 h-4" />
					)
				}
				styles={{
					label: {
						fontWeight: 500,
						color: "var(--muted-foreground)",
					},
				}}
			>
				{title}
			</Button>
			{isOpen && <div className="mt-1 ml-6 space-y-2">{children}</div>}
		</div>
	);
};
