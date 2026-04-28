import { EmptyDocumentList } from "#root/component/EmptyDocumentList.tsx";

export const NewChatView = () => {
	return (
		<div className="flex-1 p-8">
			<EmptyDocumentList onAddFile={() => {}} />
		</div>
	);
};
