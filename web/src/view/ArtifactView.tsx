import { ChatBox } from "#root/component/ChatBox";
import { ChatMessage } from "#root/component/ChatMessage";
import DocumentRender from "#root/component/DocumentRender";
import { useQueryChatDetail } from "#root/query/chatDetail";
import { useAppStore } from "#root/store/useAppStore";

export const ArtifactView = () => {
	const { activeChatId } = useAppStore();
	const { data, isLoading } = useQueryChatDetail(Number(activeChatId));

	if (isLoading) {
		return (
			<div className="flex-1 flex items-center justify-center">Loading...</div>
		);
	}

	return (
		<div className="flex-1 flex overflow-hidden">
			{/* Left Half: Chat */}
			<div className="w-1/2 flex flex-col border-r border-border relative">
				<div className="flex-1 overflow-y-auto p-6 space-y-4">
					{data?.messages.map((msg) => (
						<ChatMessage
							key={msg.depth}
							role={msg.depth % 2 === 0 ? "user" : "agent"}
							content={msg.content}
						/>
					))}
				</div>
				<ChatBox onSubmit={() => {}} onStop={() => {}} isStreaming={false} />
			</div>

			{/* Right Half: Artifact */}
			<div className="w-1/2 flex flex-col bg-muted">
				<DocumentRender />
			</div>
		</div>
	);
};
