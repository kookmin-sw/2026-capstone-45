import { useState } from "react";
import { DocumentCard } from "#root/component/DocumentCard.tsx";
import { DocumentCardList } from "#root/component/DocumentCardList.tsx";
import { EmptyDocumentList } from "#root/component/EmptyDocumentList.tsx";
import { type Document, useQueryDocumentList } from "#root/query/documentList";

export const LibraryView = () => {
	const { data } = useQueryDocumentList();
	const [_focusedDoc, setFocusedDoc] = useState<number | null>(null);

	const docs: Document[] = data?.docs ?? [];

	const onRename = (docId: number) => {
		setFocusedDoc(docId);
		//TODO: Show modal
	};

	const onDelete = (docId: number) => {
		setFocusedDoc(docId);
		//TODO: Show modal
	};

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
				<DocumentCardList>
					{docs.map((doc) => {
						return (
							<DocumentCard
								key={doc.doc_id}
								document={doc}
								onOpen={() => {}}
								buttons={[
									{
										className: "bg-white",
										text: "이름 바꾸기",
										action: onRename,
									},
									{
										className: "bg-destructive text-white",
										text: "삭제",
										action: onDelete,
									},
								]}
							/>
						);
					})}
				</DocumentCardList>
			</div>
		</div>
	);
};
