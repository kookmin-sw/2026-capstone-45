import { useAppStore } from "#root/store/useAppStore";

const NAME_MAP = {
	LIBRARY: "문서 목록",
	NEW_CHAT: "새 채팅",
	//TODO: 채팅 제목 표시
	CHAT: "채팅",
};

export const Header = () => {
	const { view } = useAppStore();

	return (
		<header className="h-16 border-b border-border bg-background flex items-center justify-between px-6 shrink-0">
			<div className="flex items-center gap-4">
				<h1 className="text-sm font-bold uppercase tracking-widest text-muted-foreground">
					{NAME_MAP[view]}
				</h1>
			</div>
		</header>
	);
};
