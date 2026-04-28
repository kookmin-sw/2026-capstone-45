import ReactMarkdown from "react-markdown";
import { cn } from "../utils/cn";
import { ExtraContent } from "./ExtraContent";

interface ChatMessageProps {
	role: "user" | "agent" | "error" | "warning";
	content: string;
	timestamp?: Date;
	extraContent?: string | null;
}

export const ChatMessage = ({
	role,
	content,
	timestamp,
	extraContent,
}: ChatMessageProps) => {
	const isUser = role === "user";
	const isError = role === "error";
	const isWarning = role === "warning";

	return (
		<div
			className={`flex flex-col ${isUser ? "items-end" : "items-start"} mb-4 w-full`}
		>
			<div
				className={cn(
					"max-w-[80%] px-4 py-2 rounded-2xl",
					isUser && "bg-primary text-primary-foreground rounded-tr-none",
					isError &&
						"bg-destructive/10 text-destructive border border-destructive/20",
					isWarning &&
						"bg-amber-100 text-amber-900 border border-amber-200 dark:bg-amber-900/20 dark:text-amber-100 dark:border-amber-800",
					role === "agent" && "bg-muted text-foreground rounded-tl-none",
				)}
			>
				{role === "agent" ? (
					<div className="prose prose-sm dark:prose-invert max-w-none">
						<ReactMarkdown>{content}</ReactMarkdown>
					</div>
				) : (
					<div className="whitespace-pre-wrap wrap-break-word">{content}</div>
				)}

				<ExtraContent
					content={extraContent}
					className="border-t border-current/10 pt-2"
				/>
			</div>
			{timestamp && (
				<span className="text-muted-foreground mt-1 px-1">
					{timestamp.toLocaleTimeString(undefined, {
						hour: "2-digit",
						minute: "2-digit",
					})}
				</span>
			)}
		</div>
	);
};
