import { useState } from "react";
import { ChatBox } from "#root/component/ChatBox";
import { DocumentCard } from "#root/component/DocumentCard.tsx";
import { EmptyDocumentList } from "#root/component/EmptyDocumentList.tsx";
import { useMutateCreateChat } from "#root/query/createChat";
import { useQueryDocumentList } from "#root/query/documentList";
import { useAppStore } from "#root/store/useAppStore";
import type { Document } from "#root/types";

export const NewChatView = () => {
	const { data } = useQueryDocumentList();
	const { mutateAsync: createChat } = useMutateCreateChat();
	const { setActiveChat } = useAppStore();

	const [targetDoc, setTargetDoc] = useState<string | null>(null);
	const [sourceDocs, setSourceDocs] = useState<string[]>([]);

	const isDocValid = targetDoc !== null && sourceDocs.length !== 0;

	const docs: Document[] =
		data?.docs.map((doc) => ({
			id: doc.doc_id.toString(),
			filename: doc.display_name,
			uploadedAt: new Date(),
			sizeBytes: 0,
			thumbnailUrl: "",
			src: "",
		})) ?? [];

	const handleCreateChat = async (query: string) => {
		if (!isDocValid) {
			alert("문서를 선택해주세요.");
			return;
		}
		try {
			const chatId = await createChat({
				target_doc: Number(targetDoc),
				source_docs: sourceDocs.map(Number),
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
									key={doc.id}
									document={doc}
									mode="select"
									onOpen={() => {}}
									selectionState={
										targetDoc === doc.id
											? "target"
											: sourceDocs.includes(doc.id)
												? "source"
												: "none"
									}
									onSetTarget={() => {
										setTargetDoc(doc.id);
										setSourceDocs((prev) => prev.filter((id) => id !== doc.id));
									}}
									onAddSource={() => {
										setSourceDocs((prev) => [...new Set([...prev, doc.id])]);
										if (targetDoc === doc.id) setTargetDoc(null);
									}}
									onRemoveSelection={() => {
										if (targetDoc === doc.id) setTargetDoc(null);
										setSourceDocs((prev) => prev.filter((id) => id !== doc.id));
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
