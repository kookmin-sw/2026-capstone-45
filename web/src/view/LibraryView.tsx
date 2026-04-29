import { Button, FileButton } from "@mantine/core";
import { Plus } from "lucide-react";
import { useState } from "react";
import { DocumentCard } from "#root/component/DocumentCard.tsx";
import { DocumentCardList } from "#root/component/DocumentCardList.tsx";
import { EmptyDocumentList } from "#root/component/EmptyDocumentList.tsx";
import { useMutateCreateDocument } from "#root/query/createDocument";
import {
	type DocumentListEntry,
	useQueryDocumentList,
} from "#root/query/documentList";

export const LibraryView = () => {
	const { data } = useQueryDocumentList();
	const { mutate } = useMutateCreateDocument();
	const [_focusedDoc, setFocusedDoc] = useState<number | null>(null);

	const docs: DocumentListEntry[] = data?.docs ?? [];

	const onRename = (docId: number) => {
		setFocusedDoc(docId);
		//TODO: Show modal
	};

	const onDelete = (docId: number) => {
		setFocusedDoc(docId);
		//TODO: Show modal
	};

	const handleUpload = (file: File | null) => {
		if (file) {
			mutate(file);
		}
	};

	if (docs.length === 0) {
		return (
			<div className="flex-1 p-8">
				<FileButton onChange={handleUpload} accept="application/pdf,text/plain">
					{(props) => <EmptyDocumentList onAddFile={props.onClick} />}
				</FileButton>
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
					<FileButton
						onChange={handleUpload}
						accept="application/pdf,text/plain"
					>
						{(props) => (
							<Button
								{...props}
								leftSection={<Plus size={18} />}
								variant="filled"
								color="blue"
							>
								파일 업로드
							</Button>
						)}
					</FileButton>
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
										variant: "light",
										color: "blue",
										text: "이름 바꾸기",
										action: onRename,
									},
									{
										variant: "filled",
										color: "red",
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
