import { ChatBox } from "#root/component/ChatBox";

export const ChatView = () => {
	return (
		<div className="flex-1 flex flex-col relative overflow-hidden">
			<div className="flex-1 overflow-y-auto p-6 space-y-4"></div>
			<ChatBox onSubmit={() => {}} onStop={() => {}} isStreaming={false} />
		</div>
	);
};
