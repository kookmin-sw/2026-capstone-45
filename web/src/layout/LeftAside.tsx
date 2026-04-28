import { ChevronLeft, Library, Menu, Plus } from "lucide-react";
import { ChatHistoryItem } from "#root/component/ChatHistoryItem";
import { type Chat, useQueryChatList } from "#root/query/chatList";
import { useAppStore } from "#root/store/useAppStore";

export const LeftAside = () => {
	const {
		view,
		setView,
		sidebarFolded,
		toggleSidebar,
		activeChatId,
		setActiveChat,
	} = useAppStore();

	const { data } = useQueryChatList();

	const chats: Chat[] = data?.chats ?? [];

	return (
		<aside
			className={`h-full bg-muted/30 border-r border-border flex flex-col transition-all duration-300 relative ${
				sidebarFolded ? "w-16" : "w-64"
			}`}
		>
			{/* Header / Toggle */}
			<div
				className={`p-4 flex items-center ${sidebarFolded ? "justify-center" : "justify-between"}`}
			>
				{!sidebarFolded && (
					<h2 className="font-bold text-lg text-foreground">지정문서 생성</h2>
				)}
				<button
					type="button"
					onClick={toggleSidebar}
					className={`p-2 rounded-lg hover:bg-muted transition-colors ${
						sidebarFolded ? "" : "ml-auto"
					}`}
				>
					{sidebarFolded ? (
						<Menu className="w-5 h-5" />
					) : (
						<ChevronLeft className="w-5 h-5" />
					)}
				</button>
			</div>

			{/* Navigation Actions */}
			<div className="px-3 py-2 space-y-1">
				<button
					type="button"
					onClick={() => setView("LIBRARY")}
					className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
						view === "LIBRARY"
							? "bg-primary text-primary-foreground shadow-sm"
							: "text-muted-foreground hover:bg-muted hover:text-foreground"
					}`}
				>
					<Library className="w-5 h-5 shrink-0" />
					{!sidebarFolded && (
						<span className="font-semibold text-sm">문서 목록</span>
					)}
				</button>
				<button
					type="button"
					onClick={() => setView("NEW_CHAT")}
					className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
						view === "NEW_CHAT"
							? "bg-primary text-primary-foreground shadow-sm"
							: "text-muted-foreground hover:bg-muted hover:text-foreground"
					}`}
				>
					<Plus className="w-5 h-5 shrink-0" />
					{!sidebarFolded && (
						<span className="font-semibold text-sm">새 채팅</span>
					)}
				</button>
			</div>

			{/* Chat History */}
			{!sidebarFolded && (
				<div className="flex-1 overflow-y-auto mt-4 px-3 py-2">
					<div className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-4 px-3">
						채팅 내역
					</div>
					<div className="space-y-1">
						{chats.map((chat) => (
							<ChatHistoryItem
								key={chat.chat_id}
								chat={chat}
								active={activeChatId === chat.chat_id.toString()}
								onSelect={() =>
									setActiveChat(chat.chat_id.toString(), chat.has_render)
								}
								onPin={() => {}} // TODO
								onRename={() => {}} // TODO
								onDelete={() => {}} // TODO
							/>
						))}
					</div>
				</div>
			)}
		</aside>
	);
};
