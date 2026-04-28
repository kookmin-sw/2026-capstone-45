import { notifications } from "@mantine/notifications";
import { ChatBox } from "#root/component/ChatBox";
import { DocumentCard } from "#root/component/DocumentCard.tsx";
import { DocumentCardList } from "#root/component/DocumentCardList.tsx";
import { EmptyDocumentList } from "#root/component/EmptyDocumentList.tsx";
import { useMutateCreateChat } from "#root/query/createChat";
import { type Document, useQueryDocumentList } from "#root/query/documentList";
import { useAppStore } from "#root/store/useAppStore";
import { useNewChatStore } from "#root/store/useNewChatStore";

export const NewChatView = () => {
	const { data } = useQueryDocumentList();
	const { mutateAsync: createChat } = useMutateCreateChat();
	const { setActiveChat, setView } = useAppStore();
	const { targetDoc, sourceDocs, setTargetDoc, setSourceDocs, reset } =
		useNewChatStore();

	const isDocValid = targetDoc !== null && sourceDocs.length !== 0;

	const docs: Document[] = data?.docs ?? [];

	const handleCreateChat = async (query: string) => {
		if (!isDocValid) {
			// UI상 어짜피 막혀있음
			return;
		}

		setView("CHAT");

		try {
			const chatId = await createChat({
				target_doc: targetDoc,
				source_docs: sourceDocs,
				query,
			});
			setActiveChat(chatId.toString());
			reset();
		} catch (error) {
			console.error(error);
			notifications.show({
				title: "오류",
				message: "채팅을 생성하는데 실패했습니다",
				color: "red",
			});

			const state = useAppStore.getState();
			if (state.view === "CHAT" && state.activeChatId === null) {
				state.setView("NEW_CHAT");
			}
		}
	};

	const selections: { id: number; kind: "source" | "target" }[] =
		sourceDocs.map((docId) => ({ id: docId, kind: "target" }));
	if (targetDoc !== null) {
		selections.push({ id: targetDoc, kind: "source" });
	}

	const removeSelection = (docId: number) => {
		if (targetDoc === docId) setTargetDoc(null);
		setSourceDocs((prev) => prev.filter((id) => id !== docId));
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
					<h1 className="text-3xl font-bold text-foreground pb-8">
						새 채팅 시작
					</h1>

					<DocumentCardList>
						{docs.map((doc) => {
							const isTarget = targetDoc === doc.doc_id;
							const isSource = sourceDocs.includes(doc.doc_id);

							return (
								<DocumentCard
									key={doc.doc_id}
									document={doc}
									onOpen={() => {}}
									selectionState={
										isTarget ? "target" : isSource ? "source" : undefined
									}
									buttons={[
										{
											variant: isTarget ? "light" : "filled",
											color: "blue",
											text: isTarget ? "선택 취소" : "타겟 문서로 선택",
											action: (docId: number) => {
												if (!isTarget) {
													setTargetDoc(docId);
													setSourceDocs((prev) =>
														prev.filter((id) => id !== docId),
													);
												} else {
													removeSelection(docId);
												}
											},
										},
										{
											variant: isSource ? "light" : "filled",
											color: "gray",
											text: isSource ? "선택 취소" : "소스 문서로 선택",
											action: (docId: number) => {
												if (!isSource) {
													setSourceDocs((prev) => [
														...new Set([...prev, docId]),
													]);
													if (targetDoc === docId) setTargetDoc(null);
												} else {
													removeSelection(docId);
												}
											},
										},
									]}
								/>
							);
						})}
					</DocumentCardList>
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
