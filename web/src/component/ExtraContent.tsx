import { FoldableMessage } from "./FoldableMessage";

interface ExtraContentProps {
	content: string | null | undefined;
	className?: string;
}

export const ExtraContent = ({ content, className }: ExtraContentProps) => {
	if (!content) return null;

	return (
		<div className={`mt-2 ${className}`}>
			<FoldableMessage title="세부사항">
				<div className="opacity-70 whitespace-pre-wrap wrap-break-word font-mono bg-muted/20 p-2 rounded">
					{content}
				</div>
			</FoldableMessage>
		</div>
	);
};
