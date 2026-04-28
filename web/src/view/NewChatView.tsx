import { useState } from "react";
import { ChatBox } from "#root/component/ChatBox";
import { DocumentCard } from "#root/component/DocumentCard.tsx";
import { EmptyDocumentList } from "#root/component/EmptyDocumentList.tsx";
import { useMutateCreateChat } from "#root/query/createChat";
import { type Document, useQueryDocumentList } from "#root/query/documentList";
import { useAppStore } from "#root/store/useAppStore";

export const NewChatView = () => {
	const { data } = useQueryDocumentList();
	const { mutateAsync: createChat } = useMutateCreateChat();
	const { setActiveChat } = useAppStore();

	const [targetDoc, setTargetDoc] = useState<number | null>(null);
	const [sourceDocs, setSourceDocs] = useState<number[]>([]);

	const isDocValid = targetDoc !== null && sourceDocs.length !== 0;

	const docs: Document[] = data?.docs ?? [];

	const handleCreateChat = async (query: string) => {
		if (!isDocValid) {
			alert("문서를 선택해주세요.");
			return;
		}
		try {
			const chatId = await createChat({
				target_doc: targetDoc,
				source_docs: sourceDocs,
				query,
			});
			setActiveChat(chatId.toString());
		} catch (error) {
			console.error("Failed to create chat", error);
		}
	};

	if (docs.length === 0) {
		return (
			<div className="flex-1 p-8">
				<EmptyDocumentList onAddFile={() => {}} />
			</div>
		);
	}

	return (
		<div className="flex-1 flex flex-col overflow-hidden">
			<div className="flex-1 p-8 overflow-y-auto">
				<div className="max-w-5xl mx-auto">
					<h1 className="text-3xl font-bold text-foreground mb-8">
						새 채팅 시작
					</h1>

					<div className="mb-8">
						<h2 className="text-lg font-semibold mb-4">문서 선택</h2>
						<div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
							{docs.map((doc) => (
								<DocumentCard
									key={doc.doc_id}
									document={doc}
									mode="select"
									onOpen={() => {}}
									selectionState={
										targetDoc === doc.doc_id
											? "target"
											: sourceDocs.includes(doc.doc_id)
												? "source"
												: "none"
									}
									onSetTarget={() => {
										setTargetDoc(doc.doc_id);
										setSourceDocs((prev) =>
											prev.filter((id) => id !== doc.doc_id),
										);
									}}
									onAddSource={() => {
										setSourceDocs((prev) => [
											...new Set([...prev, doc.doc_id]),
										]);
										if (targetDoc === doc.doc_id) setTargetDoc(null);
									}}
									onRemoveSelection={() => {
										if (targetDoc === doc.doc_id) setTargetDoc(null);
										setSourceDocs((prev) =>
											prev.filter((id) => id !== doc.doc_id),
										);
									}}
								/>
							))}
						</div>
					</div>
				</div>
			</div>

			<div className="bg-background border-t border-border">
				<div className="max-w-4xl mx-auto p-4">
					<ChatBox
						onSubmit={handleCreateChat}
						onStop={() => {}}
						isStreaming={false}
						disabled={!isDocValid}
						placeholder={
							isDocValid
								? "원하는 문서 내용을 알려주세요"
								: "타깃 문서를 먼저 선택하세요"
						}
					/>
				</div>
			</div>
		</div>
	);
};
