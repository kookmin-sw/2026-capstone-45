import { ChatBox } from "#root/component/ChatBox";
import { ChatMessage } from "#root/component/ChatMessage";
import { useQueryChatDetail } from "#root/query/chatDetail";
import { useAppStore } from "#root/store/useAppStore";

export const ChatView = () => {
	const { activeChatId } = useAppStore();
	const { data, isLoading } = useQueryChatDetail(Number(activeChatId));

	if (isLoading) {
		return (
			<div className="flex-1 flex items-center justify-center">Loading...</div>
		);
	}

	return (
		<div className="flex-1 flex flex-col relative overflow-hidden">
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
	);
};
