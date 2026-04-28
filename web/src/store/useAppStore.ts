import { create } from "zustand";
import type { AppView } from "#root/types";

interface AppState {
	view: AppView;
	sidebarFolded: boolean;
	activeChatId: string | null;
	setView: (view: AppView) => void;
	setSidebarFolded: (folded: boolean) => void;
	toggleSidebar: () => void;
	setActiveChat: (chatId: string | null, hasRender?: boolean) => void;
}

export const useAppStore = create<AppState>((set) => ({
	view: "NEW_CHAT",
	sidebarFolded: false,
	activeChatId: null,
	setView: (view) =>
		set((state) => ({
			view,
			// NEW_CHAT으로 이동했다면 채팅을 선택 해제함
			activeChatId: view === "NEW_CHAT" ? null : state.activeChatId,
			// ARTIFACT로 이동했다면 사이드바를 접음
			sidebarFolded: view === "CHAT_AND_ARTIFACT" ? true : state.sidebarFolded,
		})),
	setSidebarFolded: (sidebarFolded) => set({ sidebarFolded }),
	toggleSidebar: () =>
		set((state) => ({ sidebarFolded: !state.sidebarFolded })),
	setActiveChat: (activeChatId, hasRender) =>
		set({
			activeChatId,
			view: hasRender ? "CHAT_AND_ARTIFACT" : "CHAT",
		}),
}));
