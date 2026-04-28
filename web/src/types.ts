export type AppView = "LIBRARY" | "NEW_CHAT" | "CHAT";

export interface MenuItem {
	label: string;
	onSelect: () => void;
	variant?: "default" | "danger";
}
