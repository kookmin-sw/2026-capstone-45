import type { ReactElement } from "react";

interface DocumentCardListProps {
	children: ReactElement[];
}

export const DocumentCardList = ({ children }: DocumentCardListProps) => {
	return (
		<div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
			{children}
		</div>
	);
};
