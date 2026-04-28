import type { ChatMessageEntry } from "#root/query/chatDetail";
import { ChatMessage } from "./ChatMessage";
import { ExtraContent } from "./ExtraContent";
import { FoldableMessage } from "./FoldableMessage";

interface MessageListProps {
	messages: ChatMessageEntry[];
}

export const MessageList = ({ messages }: MessageListProps) => {
	const blocks: Array<
		| { type: "single"; message: ChatMessageEntry }
		| { type: "log_group"; messages: ChatMessageEntry[] }
	> = [];

	let currentLogGroup: ChatMessageEntry[] = [];

	const flushLogs = () => {
		if (currentLogGroup.length > 0) {
			blocks.push({
				type: "log_group",
				messages: [...currentLogGroup],
			});
			currentLogGroup = [];
		}
	};

	for (const msg of messages) {
		const depth = msg.depth;
		if (depth === 60 || depth === 70) {
			currentLogGroup.push(msg);
		} else {
			flushLogs();
			blocks.push({ type: "single", message: msg });
		}
	}
	flushLogs();

	return (
		<div className="flex flex-col w-full">
			{blocks.map((block, idx) => {
				if (block.type === "log_group") {
					return (
						<FoldableMessage
							// biome-ignore lint/suspicious/noArrayIndexKey: FIXME: stable order
							key={`log-${idx}`}
							title={`내부 로그 ${block.messages.length}건`}
						>
							<div className="space-y-2 pb-2">
								{block.messages.map((m, i) => (
									<div
										// biome-ignore lint/suspicious/noArrayIndexKey: FIXME: stable order
										key={i}
										className="text-muted-foreground/70 border-l-2 border-muted pl-3 py-1"
									>
										<div className="whitespace-pre-wrap wrap-break-word">
											{m.content}
										</div>
										<ExtraContent content={m.extra_content} />
									</div>
								))}
							</div>
						</FoldableMessage>
					);
				}

				const msg = block.message;
				const depth = msg.depth;

				const roleMap: Record<number, "user" | "error" | "warning"> = {
					10: "user",
					20: "error",
					30: "warning",
				};

				const role = roleMap[depth];
				if (role) {
					return (
						<ChatMessage
							// biome-ignore lint/suspicious/noArrayIndexKey: FIXME: stable order
							key={idx}
							role={role}
							content={msg.content}
							extraContent={msg.extra_content}
						/>
					);
				}

				if (depth === 50) {
					return (
						<FoldableMessage
							// biome-ignore lint/suspicious/noArrayIndexKey: FIXME: stable order
							key={idx}
							title="reasoning 로그"
						>
							<div className="text-muted-foreground italic whitespace-pre-wrap wrap-break-word pb-2">
								{msg.content}
							</div>
							<ExtraContent content={msg.extra_content} className="mb-2" />
						</FoldableMessage>
					);
				}
				if (depth === 51) {
					let toolName = "tool";
					try {
						// FIXME: tool 이름 표시
						// const data = JSON.parse(msg.content);
						toolName = "tool";
					} catch (_e) {}
					return (
						<FoldableMessage
							// biome-ignore lint/suspicious/noArrayIndexKey: FIXME: stable order
							key={idx}
							title={`${toolName} 호출`}
						>
							<div className="pb-2">{msg.content}</div>
							<ExtraContent content={msg.extra_content} className="mb-2" />
						</FoldableMessage>
					);
				}

				return null;
			})}
		</div>
	);
};
