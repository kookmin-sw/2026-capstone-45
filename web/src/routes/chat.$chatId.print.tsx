import { createFileRoute } from "@tanstack/react-router";
import DocumentRender from "#root/component/DocumentRender";

export const Route = createFileRoute("/chat/$chatId/print")({
	component: ChatPrintComponent,
});

function ChatPrintComponent() {
	const { chatId } = Route.useParams();
	return (
		<div className="flex h-screen w-screen overflow-hidden">
			<DocumentRender
				chatId={chatId}
				hideControls
				initialZoom={1000}
				autoPrint
			/>
		</div>
	);
}
