import { ChatBox } from "#root/component/ChatBox";

export const ArtifactView = () => {
	return (
		<div className="flex-1 flex overflow-hidden">
			{/* Left Half: Chat */}
			<div className="w-1/2 flex flex-col border-r border-border relative">
				<div className="flex-1 overflow-y-auto p-6 space-y-4"></div>
				<ChatBox onSubmit={() => {}} onStop={() => {}} isStreaming={false} />
			</div>

			{/* Right Half: Artifact */}
			<div className="w-1/2 bg-muted">{/* TODO */}</div>
		</div>
	);
};
