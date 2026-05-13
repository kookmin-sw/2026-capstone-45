import { ActionIcon, Button } from "@mantine/core";
import { ChevronLeft, Library, Menu, Plus } from "lucide-react";
import { useState } from "react";
import { ChatHistoryItem } from "#root/component/ChatHistoryItem";
import { ConfirmDeleteModal } from "#root/component/ConfirmDeleteModal";
import { RenameChatModal } from "#root/component/RenameChatModal";
import { type Chat, useQueryChatList } from "#root/query/chatList";
import { useMutationDeleteChat } from "#root/query/deleteChat";
import { useAppStore } from "#root/store/useAppStore";
import { cn } from "../utils/cn";

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
	const deleteChatMutation = useMutationDeleteChat();

	const [chatToDelete, setChatToDelete] = useState<Chat | null>(null);
	const [chatToRename, setChatToRename] = useState<Chat | null>(null);

	const chats: Chat[] = data?.chats ?? [];

	const handleDeleteConfirm = async () => {
		if (!chatToDelete) return;

		const idToDelete = chatToDelete.chat_id.toString();
		await deleteChatMutation.mutateAsync(idToDelete);

		if (activeChatId === idToDelete) {
			setView("NEW_CHAT");
		}

		setChatToDelete(null);
	};
	const openRenameModal = (chat: Chat) => {
		setChatToRename(chat);
	};

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
				<ActionIcon
					variant="subtle"
					color="gray"
					onClick={toggleSidebar}
					className={cn(!sidebarFolded && "ml-auto")}
				>
					{sidebarFolded ? (
						<Menu className="w-5 h-5" />
					) : (
						<ChevronLeft className="w-5 h-5" />
					)}
				</ActionIcon>
			</div>

			{/* Navigation Actions */}
			<div className="px-3 py-2 space-y-1">
				{[
					{ id: "LIBRARY", icon: Library, label: "문서 목록" },
					{ id: "NEW_CHAT", icon: Plus, label: "새 채팅" },
				].map(({ id, icon: Icon, label }) => (
					<Button
						key={id}
						variant={view === id ? "filled" : "subtle"}
						color={view === id ? "blue" : "gray"}
						fullWidth
						justify="flex-start"
						leftSection={<Icon size={20} />}
						onClick={() => setView(id as "LIBRARY" | "NEW_CHAT")}
						styles={{
							inner: {
								justifyContent: sidebarFolded ? "center" : "flex-start",
							},
							section: {
								marginRight: sidebarFolded ? 0 : undefined,
							},
						}}
					>
						{!sidebarFolded && <span className="font-semibold">{label}</span>}
					</Button>
				))}
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
								onSelect={() => setActiveChat(chat.chat_id.toString())}
								onPin={() => {}} // TODO
								onRename={() => openRenameModal(chat)}
								onDelete={() => setChatToDelete(chat)}
							/>
						))}
					</div>
				</div>
			)}

			<ConfirmDeleteModal
				visible={!!chatToDelete}
				title="채팅 삭제"
				message="정말로 이 채팅을 삭제하시겠습니까?"
				onCancel={() => setChatToDelete(null)}
				onConfirm={handleDeleteConfirm}
			/>

			<RenameChatModal
				chatId={chatToRename?.chat_id.toString() ?? ""}
				currentName={chatToRename?.display_name ?? ""}
				visible={!!chatToRename}
				onClose={() => setChatToRename(null)}
			/>
		</aside>
	);
};
