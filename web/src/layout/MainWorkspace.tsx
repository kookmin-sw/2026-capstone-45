import { GhostOverlay } from "#root/component/GhostOverlay";
import { useMutateCreateDocument } from "#root/query/createDocument";
import { useAppStore } from "#root/store/useAppStore";
import { ChatView } from "#root/view/ChatView";
import { LibraryView } from "#root/view/LibraryView";
import { NewChatView } from "#root/view/NewChatView";

export const MainWorkspace = () => {
	const { view } = useAppStore();
	const { mutate } = useMutateCreateDocument();

	const renderView = () => {
		switch (view) {
			case "LIBRARY":
				return <LibraryView />;
			case "NEW_CHAT":
				return <NewChatView />;
			case "CHAT":
				return <ChatView />;
			default:
				return <NewChatView />;
		}
	};

	const ghostActive = view === "LIBRARY" || view === "NEW_CHAT";

	const handleDrop = (files: File[]) => {
		for (const file of files) {
			mutate(file);
		}
	};

	return (
		<main className="flex-1 flex overflow-hidden relative">
			<div className="flex-1 flex flex-col overflow-hidden">{renderView()}</div>

			<GhostOverlay active={ghostActive} onDrop={handleDrop} />
		</main>
	);
};
