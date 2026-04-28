import { FileText } from "lucide-react";
import { ChatBox } from "#root/component/ChatBox";
import DocumentRender from "#root/component/DocumentRender";
import { MessageList } from "#root/component/MessageList";
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
		<div className="flex-1 flex overflow-hidden">
			{/* Left Half: Chat */}
			<div className="w-1/2 flex flex-col border-r border-border relative">
				<div className="flex-1 overflow-y-auto p-6">
					<MessageList messages={data?.messages || []} />
				</div>
				<ChatBox onSubmit={() => {}} onStop={() => {}} isStreaming={false} />
			</div>

			{/* Right Half: Artifact */}
			<div className="w-1/2 flex flex-col bg-muted">
				{data?.has_render ? (
					<DocumentRender />
				) : (
					<div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-4">
						<FileText className="w-12 h-12 opacity-20" />
						<p>아직 문서가 생성되지 않았습니다</p>
					</div>
				)}
			</div>
		</div>
	);
};
