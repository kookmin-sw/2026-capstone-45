import ReactMarkdown from "react-markdown";

interface ChatMessageProps {
	role: "user" | "agent" | "error";
	content: string;
	timestamp?: Date;
}

export const ChatMessage = ({ role, content, timestamp }: ChatMessageProps) => {
	const isUser = role === "user";
	const isError = role === "error";

	return (
		<div
			className={`flex flex-col ${isUser ? "items-end" : "items-start"} mb-4 w-full`}
		>
			<div
				className={`max-w-[80%] px-4 py-2 rounded-2xl ${
					isUser
						? "bg-primary text-primary-foreground rounded-tr-none"
						: isError
							? "bg-destructive/10 text-destructive border border-destructive/20"
							: "bg-muted text-foreground rounded-tl-none"
				}`}
			>
				{role === "agent" ? (
					<div className="prose prose-sm dark:prose-invert max-w-none">
						<ReactMarkdown>{content}</ReactMarkdown>
					</div>
				) : (
					<div className="whitespace-pre-wrap break-words">{content}</div>
				)}
			</div>
			{timestamp && (
				<span className="text-[10px] text-muted-foreground mt-1 px-1">
					{timestamp.toLocaleTimeString(undefined, {
						hour: "2-digit",
						minute: "2-digit",
					})}
				</span>
			)}
		</div>
	);
};
