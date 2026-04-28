import { DocumentCard } from "#root/component/DocumentCard.tsx";
import { EmptyDocumentList } from "#root/component/EmptyDocumentList.tsx";
import { useQueryDocumentList } from "#root/query/documentList";
import type { Document } from "#root/types";

export const LibraryView = () => {
	const { data } = useQueryDocumentList();

	const docs: Document[] =
		data?.docs.map((doc) => ({
			id: doc.doc_id.toString(),
			filename: doc.display_name,
			uploadedAt: new Date(),
			sizeBytes: 0,
			thumbnailUrl: "",
			src: "",
		})) ?? [];

	if (docs.length === 0) {
		return (
			<div className="flex-1 p-8">
				<EmptyDocumentList onAddFile={() => {}} />
			</div>
		);
	}

	return (
		<div className="flex-1 p-8 overflow-y-auto">
			<div className="max-w-5xl mx-auto">
				<div className="flex justify-between items-center mb-8">
					<h1 className="text-3xl font-bold text-foreground">
						문서 라이브러리
					</h1>
				</div>
				<div className="grid grid-cols-1 gap-4">
					{docs.map((doc) => (
						<DocumentCard
							key={doc.id}
							document={doc}
							mode="library"
							onOpen={() => {}}
						/>
					))}
				</div>
			</div>
		</div>
	);
};
