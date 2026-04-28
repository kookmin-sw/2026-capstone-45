import { GhostOverlay } from "#root/component/GhostOverlay";
import { useAppStore } from "#root/store/useAppStore";
import { ArtifactView } from "#root/view/ArtifactView";
import { ChatView } from "#root/view/ChatView";
import { LibraryView } from "#root/view/LibraryView";
import { NewChatView } from "#root/view/NewChatView";

export const MainWorkspace = () => {
	const { view } = useAppStore();

	const renderView = () => {
		switch (view) {
			case "LIBRARY":
				return <LibraryView />;
			case "NEW_CHAT":
				return <NewChatView />;
			case "CHAT":
				return <ChatView />;
			case "CHAT_AND_ARTIFACT":
				return <ArtifactView />;
			default:
				return <NewChatView />;
		}
	};

	const ghostActive = view === "LIBRARY" || view === "NEW_CHAT";

	return (
		<main className="flex-1 flex overflow-hidden relative">
			<div className="flex-1 flex flex-col overflow-hidden">{renderView()}</div>

			<GhostOverlay active={ghostActive} onDrop={() => {}} />
		</main>
	);
};
