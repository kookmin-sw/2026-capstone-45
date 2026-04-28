export type AppView = "LIBRARY" | "NEW_CHAT" | "CHAT" | "CHAT_AND_ARTIFACT";

export interface MenuItem {
	label: string;
	onSelect: () => void;
	variant?: "default" | "danger";
}
