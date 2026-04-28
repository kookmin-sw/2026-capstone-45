import { useEffect } from "react";
import { ChatBox } from "#root/component/ChatBox";
import { ChatMessage } from "#root/component/ChatMessage";
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

	//FIXME: 이거랑 ArtifactView랑 코드가 중복됨
	return (
		<div className="flex-1 flex flex-col relative overflow-hidden">
			<div className="flex-1 overflow-y-auto p-6 space-y-4">
				{data?.messages.map((msg, i) => (
					// biome-ignore lint/suspicious/noArrayIndexKey: TODO: message_id를 API에서 받아오기
					<ChatMessage key={i} role="user" content={msg.content} />
				))}
			</div>
			<ChatBox onSubmit={() => {}} onStop={() => {}} isStreaming={false} />
		</div>
	);
};
