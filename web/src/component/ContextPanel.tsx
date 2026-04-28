import type { Document } from "#root/query/documentList";
import { DocumentCard } from "./DocumentCard";

interface ContextPanelProps {
	target: Document;
	sources: Document[];
	onOpenDocument: (doc: Document) => void;
}

export const ContextPanel = ({
	target,
	sources,
	onOpenDocument,
}: ContextPanelProps) => {
	return (
		<aside className="w-64 h-full border-l border-border bg-background flex flex-col overflow-hidden">
			<div className="p-4 border-b border-border">
				<h3 className="text-sm font-bold text-foreground uppercase tracking-wider">
					Chat Context
				</h3>
			</div>
			<div className="flex-1 overflow-y-auto p-4 space-y-6">
				{/* Target Document */}
				<section>
					<h4 className="text-xs font-semibold text-muted-foreground mb-3 uppercase">
						Target
					</h4>
					<DocumentCard
						document={target}
						mode="context"
						onOpen={() => onOpenDocument(target)}
					/>
				</section>

				{/* Source Documents */}
				<section>
					<h4 className="text-xs font-semibold text-muted-foreground mb-3 uppercase">
						Sources
					</h4>
					<div className="space-y-4">
						{sources.map((doc) => (
							<DocumentCard
								key={doc.doc_id}
								document={doc}
								mode="context"
								onOpen={() => onOpenDocument(doc)}
							/>
						))}
					</div>
				</section>
			</div>
		</aside>
	);
};
