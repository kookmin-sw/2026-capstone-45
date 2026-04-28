import { MessageSquare } from "lucide-react";
import type { Chat, MenuItem } from "#root/types";
import { ThreeDotMenu } from "./ThreeDotMenu";

interface ChatHistoryItemProps {
	chat: Chat;
	active: boolean;
	onSelect: () => void;
	onPin: () => void;
	onRename: () => void;
	onDelete: () => void;
}

export const ChatHistoryItem = ({
	chat,
	active,
	onSelect,
	onPin,
	onRename,
	onDelete,
}: ChatHistoryItemProps) => {
	const menuItems: MenuItem[] = [
		{ label: chat.isPinned ? "고정해제" : "고정", onSelect: onPin },
		{ label: "이름 바꾸기", onSelect: onRename },
		{ label: "삭제", onSelect: onDelete, variant: "danger" },
	];

	return (
		<div
			onClick={onSelect}
			className={`group relative flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors w-full text-left hover:cursor-pointer ${
				active
					? "bg-primary/10 text-primary"
					: "text-muted-foreground hover:bg-muted hover:text-foreground"
			}`}
		>
			<MessageSquare
				className={`w-4 h-4 shrink-0 ${active ? "text-primary" : "text-muted-foreground/60"}`}
			/>
			<span className="text-sm font-medium truncate flex-1">{chat.title}</span>
			<div
				className={`opacity-0 group-hover:opacity-100 transition-opacity ${active ? "opacity-100" : ""}`}
			>
				<ThreeDotMenu items={menuItems} />
			</div>
		</div>
	);
};
