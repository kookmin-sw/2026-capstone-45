import { useEffect } from "react";
import { ChatBox } from "#root/component/ChatBox";
import { MessageList } from "#root/component/MessageList";
import { useQueryChatDetail } from "#root/query/chatDetail";
import { useAppStore } from "#root/store/useAppStore";

export const ChatView = () => {
	const { activeChatId, setView } = useAppStore();
	const { data, isLoading } = useQueryChatDetail(Number(activeChatId));

	useEffect(() => {
		if (data?.has_render) {
			setView("CHAT_AND_ARTIFACT");
		}
	}, [data?.has_render, setView]);

	if (isLoading) {
		return (
			<div className="flex-1 flex items-center justify-center">Loading...</div>
		);
	}

	return (
		<div className="flex-1 flex flex-col relative overflow-hidden">
			<div className="flex-1 overflow-y-auto p-6">
				<MessageList messages={data?.messages || []} />
			</div>
			<ChatBox onSubmit={() => {}} onStop={() => {}} isStreaming={false} />
		</div>
	);
};
