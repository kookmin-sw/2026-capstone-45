import { ActionIcon } from "@mantine/core";
import { Send, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface ChatBoxProps {
	onSubmit: (message: string) => void;
	onStop: () => void;
	isStreaming: boolean;
	disabled?: boolean;
	placeholder?: string;
}

export const ChatBox = ({
	onSubmit,
	onStop,
	isStreaming,
	disabled = false,
	placeholder,
}: ChatBoxProps) => {
	const [value, setValue] = useState("");
	const textareaRef = useRef<HTMLTextAreaElement>(null);

	useEffect(() => {
		const textarea = textareaRef.current;
		if (textarea) {
			textarea.style.height = "auto";
			textarea.style.height = `${Math.min(textarea.scrollHeight, window.innerHeight * 0.3)}px`;
		}
	}, []);

	const handleKeyDown = (e: React.KeyboardEvent) => {
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			handleSend();
		}
	};

	const handleSend = () => {
		if (value.trim() && !disabled && !isStreaming) {
			onSubmit(value.trim());
			setValue("");
		}
	};

	return (
		<div className="w-full bg-background p-4">
			<div className="max-w-4xl mx-auto relative flex items-end gap-2 bg-muted/50 rounded-2xl border border-border focus-within:border-primary/50 transition-colors p-2 px-3">
				<textarea
					ref={textareaRef}
					rows={1}
					value={value}
					onChange={(e) => setValue(e.target.value)}
					onKeyDown={handleKeyDown}
					disabled={disabled}
					placeholder={placeholder}
					className="flex-1 bg-transparent border-none focus:ring-0 resize-none py-2 text-sm max-h-[30vh] disabled:opacity-50"
				/>
				<div className="flex items-center pb-1">
					{isStreaming ? (
						<ActionIcon
							variant="filled"
							color="dark"
							size="lg"
							radius="xl"
							onClick={onStop}
						>
							<Square size={16} fill="currentColor" />
						</ActionIcon>
					) : (
						<ActionIcon
							variant="filled"
							color="blue"
							size="lg"
							radius="xl"
							onClick={handleSend}
							disabled={disabled || !value.trim()}
						>
							<Send size={16} />
						</ActionIcon>
					)}
				</div>
			</div>
		</div>
	);
};
