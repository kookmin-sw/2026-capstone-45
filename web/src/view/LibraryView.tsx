import { EmptyDocumentList } from "#root/component/EmptyDocumentList.tsx";

export const LibraryView = () => {
	return (
		<div className="flex-1 p-8">
			<EmptyDocumentList onAddFile={() => {}} />
		</div>
	);
};
