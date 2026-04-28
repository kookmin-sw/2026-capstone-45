import { AlertCircle, Info, X } from "lucide-react";
import { useEffect } from "react";

interface NotificationToastProps {
	type: "error" | "info";
	message: string;
	duration?: number;
	onDismiss?: () => void;
}

export const NotificationToast = ({
	type,
	message,
	duration = 4000,
	onDismiss,
}: NotificationToastProps) => {
	useEffect(() => {
		if (duration > 0) {
			const timer = setTimeout(() => {
				onDismiss?.();
			}, duration);
			return () => clearTimeout(timer);
		}
	}, [duration, onDismiss]);

	return (
		<div
			className={`fixed bottom-4 left-1/2 -translate-x-1/2 z-[100] flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg border transition-all animate-in fade-in slide-in-from-bottom-4 ${
				type === "error"
					? "bg-destructive/10 border-destructive/20 text-destructive"
					: "bg-background border-border text-foreground"
			}`}
		>
			{type === "error" ? (
				<AlertCircle className="w-5 h-5" />
			) : (
				<Info className="w-5 h-5 text-primary" />
			)}
			<span className="text-sm font-medium">{message}</span>
			<button
				type="button"
				onClick={onDismiss}
				className="ml-2 p-1 rounded-full hover:bg-black/5 transition-colors"
			>
				<X className="w-4 h-4" />
			</button>
		</div>
	);
};
